"""写作图的八个节点。

每个节点只做一件事：取 State、调服务、写回增量。提示词在 ``prompts.py``，
模型在 ``core/llm_factory``，检索在 ``retrieval.py``，落库在 ``db``。

模型调用统一走 ``_build_model`` 这个接缝，测试替换它就能整图离线跑通。
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from backend.agents.writing.prompts import (
    assemble_prompt,
    assemble_structured_messages,
    messages_preview,
)
from backend.agents.writing.retrieval import retrieve_reference_excerpts
from backend.agents.writing.state import WritingState
from backend.agents.writing.streaming import emit
from backend.core.exceptions import GenerationError
from backend.core.llm_factory import LLMFactory
from backend.core.logger import get_logger
from backend.core.token_budget import (
    build_deai_rewrite_instruction,
    build_style_reference_rewrite_instruction,
    calculate_token_budget,
    format_budget_error,
)
from backend.config import GENERATION_SYSTEM_PROMPT, get_settings
from backend.db import session_scope
from backend.db.models import GenerationRecord

logger = get_logger(__name__)

_ROLE_MESSAGES = {'system': SystemMessage, 'user': HumanMessage, 'assistant': AIMessage}


# ── 接缝：模型构造 ────────────────────────────────────────

def _build_model(state: WritingState):
    """按请求参数构造聊天模型（测试替换此函数）。"""
    llm, dropped = LLMFactory.get_llm(
        'writing',
        api_key=state.get('api_key', ''),
        provider=state.get('provider'),
        model=state.get('model'),
        temperature=0,
        streaming=bool(state.get('stream')),
        max_tokens=state.get('max_tokens') or None,
        thinking_enabled=bool(state.get('thinking_enabled')),
        reasoning_effort=state.get('reasoning_effort', 'high'),
        sampling=state.get('sampling') or None,
    )
    state.setdefault('sampling_dropped', [])
    if dropped:
        state['sampling_dropped'] = list(dropped)
    return llm


def _to_lc_messages(messages: list[dict[str, str]]):
    converted = []
    for item in messages:
        role = item.get('role', 'user')
        cls = _ROLE_MESSAGES.get(role, HumanMessage)
        converted.append(cls(content=item.get('content', '')))
    return converted


def _chunk_text(chunk: Any) -> str:
    content = getattr(chunk, 'content', '')
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return ''.join(
            part.get('text', '') if isinstance(part, dict) else str(part) for part in content
        )
    return ''


def _chunk_reasoning(chunk: Any) -> str:
    additional = getattr(chunk, 'additional_kwargs', None) or {}
    return str(additional.get('reasoning_content') or '')


def _chunk_finish(chunk: Any) -> str | None:
    metadata = getattr(chunk, 'response_metadata', None) or {}
    return metadata.get('finish_reason')


async def _generate(state: WritingState, messages: list[dict[str, str]]) -> dict[str, Any]:
    """跑一次模型调用，把增量推到事件通道，返回聚合结果。"""
    llm = _build_model(state)
    lc_messages = _to_lc_messages(messages)

    if not state.get('stream'):
        response = await llm.ainvoke(lc_messages)
        text = _chunk_text(response)
        reasoning = _chunk_reasoning(response)
        return {
            'content': text,
            'reasoning': reasoning,
            'finish_reason': _chunk_finish(response),
        }

    text_parts: list[str] = []
    reasoning_parts: list[str] = []
    finish_reason: str | None = None
    async for chunk in llm.astream(lc_messages):
        piece = _chunk_text(chunk)
        if piece:
            text_parts.append(piece)
            emit({'type': 'token', 'data': piece})
        think = _chunk_reasoning(chunk)
        if think:
            reasoning_parts.append(think)
            emit({'type': 'reasoning', 'data': think})
        finish_reason = _chunk_finish(chunk) or finish_reason

    return {
        'content': ''.join(text_parts),
        'reasoning': ''.join(reasoning_parts),
        'finish_reason': finish_reason,
    }


def _template_views(state: WritingState) -> list[SimpleNamespace]:
    """模板在 State 里是 dict，组装器只需要几个属性，转成轻量视图。"""
    views = []
    for item in state.get('templates') or []:
        views.append(SimpleNamespace(
            id=item.get('id'),
            name=item.get('name', ''),
            category=item.get('category', ''),
            content=item.get('content', ''),
            is_active=item.get('is_active', True),
            style_strength=item.get('style_strength', 'light'),
        ))
    return views


# ── 节点 1：组装提示词 ────────────────────────────────────

async def assemble_prompt_node(state: WritingState) -> dict[str, Any]:
    templates = _template_views(state)
    route = 'structured' if state.get('structured_prompt_enabled') else 'legacy'
    style_mode = state.get('style_mode', 'legacy')
    style_metadata: dict[str, Any] = {'profiles': [], 'fallback_reason': ''}

    if style_mode == 'smart':
        # 风格链需要 Style Card 与片段精选，P3 接入后再启用；先显式降级并留痕。
        route = 'structured' if state.get('structured_prompt_enabled') else 'legacy'
        style_metadata['fallback_reason'] = 'smart 路线待 P3 接入风格卡与片段精选'
        logger.info('writing.smart_route_fallback')
    elif style_mode == 'off':
        templates = [item for item in templates if item.category != 'example']

    if route == 'structured':
        messages = assemble_structured_messages(
            templates,
            custom_prefix=state.get('custom_prefix', ''),
            custom_suffix=state.get('custom_suffix', ''),
            previous_article=state.get('previous_article', ''),
            style_strength=state.get('style_strength', 'light'),
            system_prompt=GENERATION_SYSTEM_PROMPT,
        )
        assembled = messages_preview(messages)
    else:
        assembled = assemble_prompt(
            templates,
            custom_prefix=state.get('custom_prefix', ''),
            custom_suffix=state.get('custom_suffix', ''),
            previous_article=state.get('previous_article', ''),
            style_strength=state.get('style_strength', 'light'),
        )
        messages = [
            {'role': 'system', 'content': GENERATION_SYSTEM_PROMPT},
            {'role': 'user', 'content': assembled},
        ]

    emit({'type': 'status', 'data': 'prompt_ready', 'details': {'route': route}})
    return {
        'messages': messages,
        'assembled_prompt': assembled,
        'prompt_route': route,
        'style_metadata': style_metadata,
    }


# ── 节点 2：预算检查 ──────────────────────────────────────

async def budget_check_node(state: WritingState) -> dict[str, Any]:
    budget = calculate_token_budget(
        state.get('assembled_prompt', ''),
        state.get('provider', 'deepseek'),
        state.get('model', 'deepseek-v4-pro'),
        deai_enabled=bool(state.get('deai_enabled')),
        deai_prompt=state.get('deai_prompt', ''),
        thinking_enabled=bool(state.get('thinking_enabled')),
        reasoning_effort=state.get('reasoning_effort', 'high'),
        messages=state.get('messages') if state.get('structured_prompt_enabled') else None,
        style_reference_enabled=bool(state.get('style_reference_enabled')),
        max_tokens=int(state.get('max_tokens') or 0),
    )
    emit({'type': 'token_budget', 'data': budget})
    if budget['status'] == 'over':
        return {
            'token_budget': budget,
            'errors': [format_budget_error(budget)],
            'final_content': '',
        }
    return {'token_budget': budget}


# ── 节点 3：生成初稿 ──────────────────────────────────────

async def draft_node(state: WritingState) -> dict[str, Any]:
    result = await _generate(state, state.get('messages', []))
    return {
        'story_content': result['content'],
        'reasoning_content': result['reasoning'],
        'finish_reason': result['finish_reason'],
    }


# ── 节点 4：语言自然化 ────────────────────────────────────

async def deai_rewrite_node(state: WritingState) -> dict[str, Any]:
    emit({'type': 'status', 'data': 'deai_start'})
    messages = [
        *state.get('messages', []),
        {'role': 'assistant', 'content': state.get('story_content', '')},
        {'role': 'user', 'content': build_deai_rewrite_instruction(state.get('deai_prompt', ''))},
    ]
    result = await _generate(state, messages)
    emit({'type': 'status', 'data': 'deai_done'})
    return {'deai_content': result['content']}


# ── 节点 5：风格参考检索 ──────────────────────────────────

async def style_retrieve_node(state: WritingState) -> dict[str, Any]:
    emit({'type': 'status', 'data': 'style_reference_retrieving'})
    latest = state.get('deai_content') or state.get('story_content') or ''
    excerpts, meta = await retrieve_reference_excerpts(
        query_text=latest,
        corpus_ids=list(state.get('style_corpus_ids') or []),
        scene_type=state.get('scene_type', 'auto'),
        api_key=state.get('embedding_api_key', ''),
    )
    style_metadata = dict(state.get('style_metadata') or {})
    style_metadata['style_reference'] = meta

    if not excerpts:
        emit({
            'type': 'status',
            'data': 'style_reference_skipped',
            'reason': meta.get('reason', '没有可用的参考片段'),
        })
        return {
            'reference_excerpts': [],
            'style_rewrite_status': 'skipped',
            'style_metadata': style_metadata,
        }
    return {
        'reference_excerpts': excerpts,
        'style_rewrite_status': 'retrieved',
        'style_metadata': style_metadata,
    }


# ── 节点 6：风格参考改写 ──────────────────────────────────

async def style_rewrite_node(state: WritingState) -> dict[str, Any]:
    excerpts = state.get('reference_excerpts') or []
    if not excerpts:
        return {'style_rewrite_status': 'skipped'}

    emit({
        'type': 'status',
        'data': 'style_reference_start',
        'details': {
            'reference_count': len(excerpts),
            'corpus_ids': list(state.get('style_corpus_ids') or []),
        },
    })
    latest = state.get('deai_content') or state.get('story_content') or ''
    messages = [
        *state.get('messages', []),
        {'role': 'assistant', 'content': latest},
        {
            'role': 'user',
            'content': build_style_reference_rewrite_instruction(
                [item.get('content', '') for item in excerpts]
            ),
        },
    ]
    result = await _generate(state, messages)
    emit({'type': 'status', 'data': 'style_reference_done'})
    status = 'applied' if result['content'] else 'empty_response'
    return {'style_reference_content': result['content'], 'style_rewrite_status': status}


# ── 节点 7：定稿 ──────────────────────────────────────────

async def finalize_node(state: WritingState) -> dict[str, Any]:
    story = state.get('story_content', '')
    deai = state.get('deai_content', '')
    styled = state.get('style_reference_content', '')
    reasoning = state.get('reasoning_content', '')

    final = styled or deai or story
    # 思维链混进正文的兜底：正文为空但思考内容有料时，回显思考内容并标记
    if not final.strip() and reasoning.strip():
        emit({'type': 'status', 'data': 'reasoning_fallback'})
        final = reasoning

    return {'final_content': final}


# ── 节点 8：落库 ──────────────────────────────────────────

async def persist_node(state: WritingState) -> dict[str, Any]:
    settings = get_settings()
    story = state.get('story_content', '')
    deai = state.get('deai_content', '')
    styled = state.get('style_reference_content', '')
    title = state.get('title') or '未命名'
    partial = not story.strip()

    record = GenerationRecord(
        title=f'{title}（未完成）' if partial else title,
        content=story,
        deai_content=deai,
        style_rewrite_content=styled,
        style_diff_json='{}',
        style_rewrite_enabled=bool(state.get('style_reference_enabled')),
        style_rewrite_applied=bool(styled),
        style_rewrite_count=1 if styled else 0,
        model_used=state.get('model', ''),
        thinking_enabled=bool(state.get('thinking_enabled')),
        reasoning_content=state.get('reasoning_content', ''),
        assembled_prompt=state.get('assembled_prompt', ''),
        templates_used=str(state.get('template_ids') or []),
        deai_prompt=state.get('deai_prompt', '') if state.get('deai_enabled') else '',
        notes='生成未完成，已保存当前内容' if partial else '',
        style_mode=state.get('style_mode', 'legacy'),
        style_profile_snapshot=_json_dump(state.get('style_metadata') or {}),
    )

    async with session_scope() as session:
        session.add(record)
        await session.flush()
        record_id = record.id

    logger.info('writing.record_saved', record_id=record_id, chars=len(story), partial=partial)
    if settings.debug:
        logger.debug('writing.record_debug', title=title)
    return {'record_id': record_id}


def _json_dump(payload: dict[str, Any]) -> str:
    try:
        return json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError):
        return '{}'


__all__ = [
    'GenerationError',
    'assemble_prompt_node',
    'budget_check_node',
    'draft_node',
    'deai_rewrite_node',
    'finalize_node',
    'persist_node',
    'style_retrieve_node',
    'style_rewrite_node',
]
