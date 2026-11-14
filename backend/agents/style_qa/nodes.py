"""风格问答图的节点。

四分支是课件第五章的结构：精确问题直接检索，模糊问题先造"假设性回答"，
宽泛问题先拆成多个查询，无关问题直接回答。检索后按置信度决定是引用片段作答，
还是坦白"语料里没有、先按经验回答"，并把问题记进待补队列。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import select

from backend.agents.style_qa.state import StyleQAState
from backend.core.exceptions import LLMAPIError
from backend.core.knowledge_base import get_kb_backend
from backend.core.llm_factory import LLMFactory
from backend.core.logger import get_logger
from backend.db import session_scope
from backend.db.models import StylePendingQuestion

logger = get_logger(__name__)

# 置信阈值：Top1 综合分低于它就不敢引用，转直答
CONFIDENCE_THRESHOLD = 0.45
# 记忆压缩阈值（字符数），与写作侧的前置文章压缩保持一致
MEMORY_COMPRESS_THRESHOLD = 2000

CLASSIFY_SYSTEM = '你是问题分类器。只输出一个词：PRECISE / VAGUE / BROAD / GENERAL。'
ANSWER_SYSTEM = (
    '你是一名中文文学编辑。回答要具体、可执行，不要复述原文，'
    '不要使用"优美、生动、有画面感"这类空泛评价。'
)

_VAGUE_MARKERS = ('这段', '这里', '怎么样', '好不好', '是不是有点')
_BROAD_MARKERS = ('还有', '以及', '同时', '顺便', '并且', '和')
_GENERAL_MARKERS = ('你好', '你是谁', '你能做什么', '怎么用')


def _build_model(state: StyleQAState):
    """模型接缝（测试替换此函数）。"""
    llm, _dropped = LLMFactory.get_llm(
        'style_qa',
        api_key=state.get('api_key', ''),
        provider=state.get('provider'),
        model=state.get('model'),
        temperature=0.3,
    )
    return llm


async def _call(messages: list[dict[str, str]], state: StyleQAState) -> str:
    llm = _build_model(state)
    response = await llm.ainvoke([
        SystemMessage(content=item['content']) if item['role'] == 'system'
        else HumanMessage(content=item['content'])
        for item in messages
    ])
    content = response.content
    if isinstance(content, list):
        return ''.join(
            part.get('text', '') if isinstance(part, dict) else str(part) for part in content
        )
    return content or ''


# ── 节点 1：分类 ──────────────────────────────────────────

def classify_by_rules(message: str) -> str | None:
    """规则优先：明显的句子不需要花一次模型调用。"""
    text = (message or '').strip()
    if not text:
        return 'GENERAL'
    if any(marker in text for marker in _GENERAL_MARKERS):
        return 'GENERAL'
    if any(marker in text for marker in _VAGUE_MARKERS):
        return 'VAGUE'
    if any(marker in text for marker in _BROAD_MARKERS) and text.count('，') + text.count('。') >= 2:
        return 'BROAD'
    if len(text) >= 6 and (
        '怎么' in text or '为什么' in text or '如何' in text
        or '？' in text or '?' in text
    ):
        return 'PRECISE'
    return None


async def classify_query_node(state: StyleQAState) -> dict[str, Any]:
    message = state.get('user_message', '')
    query_type = classify_by_rules(message)

    if query_type is None and state.get('api_key'):
        try:
            label = (await _call([
                {'role': 'system', 'content': CLASSIFY_SYSTEM},
                {'role': 'user', 'content': message},
            ], state)).strip().upper()
            query_type = label if label in {'PRECISE', 'VAGUE', 'BROAD', 'GENERAL'} else 'PRECISE'
        except LLMAPIError as exc:  # 分类失败不阻断，按精确问题处理
            logger.warning('style_qa.classify_failed', error=str(exc))
            query_type = 'PRECISE'

    return {'query_type': query_type or 'PRECISE'}


# ── 节点 2/3：模糊与宽泛问题的预处理 ───────────────────────

async def hyde_generate_node(state: StyleQAState) -> dict[str, Any]:
    """VAGUE：先让模型写一段"假设性回答"，用它的措辞去检索。"""
    if not state.get('api_key'):
        return {'hyde_doc': state.get('user_message', '')}
    doc = await _call([
        {'role': 'system', 'content': '请用两三句话写出这个写作问题的可能答案，只输出正文。'},
        {'role': 'user', 'content': state.get('user_message', '')},
    ], state)
    return {'hyde_doc': doc.strip()}


async def multi_query_rewrite_node(state: StyleQAState) -> dict[str, Any]:
    """BROAD：把问题拆成三个不同角度的检索式。"""
    if not state.get('api_key'):
        return {'rewritten_queries': [state.get('user_message', '')]}
    raw = await _call([
        {'role': 'system', 'content': '把用户的问题改写成三个不同角度的检索式，每行一个，不要编号。'},
        {'role': 'user', 'content': state.get('user_message', '')},
    ], state)
    queries = [line.strip() for line in raw.splitlines() if line.strip()][:3]
    return {'rewritten_queries': queries or [state.get('user_message', '')]}


# ── 节点 4：检索 ──────────────────────────────────────────

async def retrieve_node(state: StyleQAState) -> dict[str, Any]:
    query = state.get('hyde_doc') or ' '.join(
        state.get('rewritten_queries') or [state.get('user_message', '')]
    )
    backend = get_kb_backend()
    items, meta = await backend.search(
        query_text=query,
        corpus_ids=list(state.get('corpus_ids') or []),
        scene_type=state.get('scene_type', 'auto'),
        top_k=3,
        api_key=state.get('api_key', ''),
    )
    top_score = max((item.get('score', 0.0) for item in items), default=0.0)
    return {
        'chunks': items,
        'confidence': round(float(top_score), 4),
        'is_high_confidence': bool(items) and top_score >= CONFIDENCE_THRESHOLD,
        'sources': [item.get('source', '') for item in items],
        'errors': [] if meta else [],
    }


# ── 节点 5/6/7：三种作答 ─────────────────────────────────

def _reference_block(chunks: list[dict[str, Any]]) -> str:
    lines = []
    for index, chunk in enumerate(chunks, start=1):
        lines.append(f'【参考片段 {index}】\n{chunk.get("content", "")}')
    return '\n\n'.join(lines)


async def generate_rag_node(state: StyleQAState) -> dict[str, Any]:
    answer = await _call([
        {'role': 'system', 'content': ANSWER_SYSTEM},
        {'role': 'user', 'content': (
            f'用户问题：{state.get("user_message", "")}\n\n'
            f'可参考的写作片段：\n{_reference_block(state.get("chunks") or [])}\n\n'
            '只回答"该怎么写"，不要抄这些片段里的句子。'
        )},
    ], state)
    return {'answer': answer.strip(), 'answer_mode': 'rag'}


async def generate_direct_node(state: StyleQAState) -> dict[str, Any]:
    answer = await _call([
        {'role': 'system', 'content': ANSWER_SYSTEM},
        {'role': 'user', 'content': (
            f'用户问题：{state.get("user_message", "")}\n\n'
            '文风语料库中没有足够相关的片段，请按通用写作经验回答，'
            '并在结尾用一句话说明这是经验判断而非你的语料。'
        )},
    ], state)
    return {'answer': answer.strip(), 'answer_mode': 'direct'}


async def generate_general_node(state: StyleQAState) -> dict[str, Any]:
    answer = await _call([
        {'role': 'system', 'content': ANSWER_SYSTEM},
        {'role': 'user', 'content': state.get('user_message', '')},
    ], state)
    return {'answer': answer.strip(), 'answer_mode': 'general'}


# ── 节点 8：低置信度入队 ──────────────────────────────────

async def enqueue_pending_node(state: StyleQAState) -> dict[str, Any]:
    """把语料答不上来的问题记下来，用户下次可以据此补语料。"""
    message = (state.get('user_message') or '').strip()
    if not message:
        return {'pending_enqueued': False}

    dedupe = hashlib.sha256(message.encode('utf-8')).hexdigest()[:32]
    async with session_scope() as session:
        existing = (await session.execute(
            select(StylePendingQuestion.id).where(
                StylePendingQuestion.dedupe_key == dedupe
            )
        )).first()
        if existing is not None:
            return {'pending_enqueued': False}
        session.add(StylePendingQuestion(
            question=message,
            dedupe_key=dedupe,
            scene_type=state.get('scene_type', 'auto'),
            corpus_ids=json.dumps(state.get('corpus_ids') or []),
        ))
    return {'pending_enqueued': True}


# ── 节点 9：记忆保存 ─────────────────────────────────────

async def save_memory_node(state: StyleQAState) -> dict[str, Any]:
    """把本轮问答压进 messages，供多轮对话复用。"""
    messages = list(state.get('messages') or [])
    messages.append({'role': 'user', 'content': state.get('user_message', '')})
    answer = state.get('answer', '')
    messages.append({'role': 'assistant', 'content': answer})

    total = sum(len(item.get('content', '')) for item in messages)
    if total > MEMORY_COMPRESS_THRESHOLD:
        # 超出阈值只保留最近四轮，避免上下文无限膨胀
        messages = messages[-4:]
    return {'messages': messages}
