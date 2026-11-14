"""统一入口：一句话进来，先判断要干什么，再分发到对应的图。

对照课件 8.4 / 8.5 的四步：

1. 规则前置拦截（零 Token）：问候、感谢、道别、问身份、问能力，直接给模板回复；
2. 意图路由：明确的写作指令走规则，含糊的交给 LLM 判类，失败默认落到写作；
3. 推 ``routing_decision`` 事件，前端据此显示"已切换到 XX"；
4. 分发：写作走流式图；风格问答与一致性审查在 P3 接入，当前先给引导。

与课件的差别是"能干什么"不同：EduAgent 是问答/批改/简历/面试，Flora 是
写作/风格诊断/一致性审查。
"""

from __future__ import annotations

import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.v1.writing import (
    WritingRequest,
    _load_templates,
    _sse,
    writing_event_stream,
)
from backend.core.llm_factory import LLMFactory
from backend.core.logger import get_logger
from backend.dependencies import get_db

logger = get_logger(__name__)
router = APIRouter()

LABELS = ('writing', 'style_qa', 'consistency', 'clarify')

_DISPLAY = {
    'writing': '写作',
    'style_qa': '风格诊断',
    'consistency': '一致性审查',
    'clarify': '需要确认',
}

# 规则命中：明确的写作指令不需要花 Token 去猜
_WRITING_KEYWORDS = (
    '写一', '写个', '写章', '生成', '续写', '接着写', '扩写', '重写', '润色',
)
_CONSISTENCY_KEYWORDS = ('矛盾', '前后不一致', '人设', '审稿', '校对', '检查设定')
_STYLE_KEYWORDS = ('风格', '文风', '像不像', '太平', '节奏', '语感')

# 五类社交/元场景的模板回复（不消耗 Token）
_REPLY_HELLO = (
    '你好，我是雨生编辑器的写作助手。\n\n'
    '你可以直接说要写什么，比如「接着上一章写一段」；'
    '也可以让我检查稿件，比如「看看这段有没有前后矛盾」。'
)
_REPLY_THANKS = '不客气。需要接着写或检查稿件时，随时说一声。'
_REPLY_BYE = '好，稿子都存好了。下次打开还在。'
_REPLY_IDENTITY = (
    '我是这个编辑器里的写作助手，负责三件事：按你的设定和文风写正文、'
    '诊断文风、检查前后是否一致。'
)
_REPLY_CAPABILITY = (
    '我能做三件事。\n\n'
    '一是写作：按你启用的模板写新章或续写。\n'
    '二是风格诊断：看你的稿子和目标文风差在哪。\n'
    '三是设定审查：查人物、时间线、伏笔有没有冲突。\n\n'
    '直接说需求就行，我会判断该用哪一种。'
)

_HELLO = frozenset(['你好', '您好', 'hi', 'hello', '在吗', '嗨', '哈喽'])
_THANKS = frozenset(['谢谢', '感谢', '多谢', '辛苦了', '好的', '收到', '明白了'])
_BYE = frozenset(['再见', '拜拜', 'bye', '先走了', '晚安'])

_ROUTE_PROMPT = """判断用户这句话想让写作助手做什么，只能选一个：
- writing      : 希望生成或改写正文（提到写、续写、扩写、润色、生成）
- style_qa     : 希望讨论或诊断文风（提到风格、文风、节奏、语感、像不像）
- consistency  : 希望检查设定是否冲突（提到矛盾、人设、时间线、伏笔、审稿）
- clarify      : 意图不明确，需要追问

严格按 JSON 返回，不要其他内容：{{"label": "选项", "reason": "一句话依据"}}

用户输入：{message}"""


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra='ignore')

    session_id: str = 'default'
    message: str = Field(default='', max_length=2000)
    # 写作需要模板与密钥；context 里放一个完整的写作请求即可
    context: dict[str, Any] = Field(default_factory=dict)


def pre_filter(message: str) -> str | None:
    """零 Token 的规则前置拦截。命中返回模板回复，否则 None。"""
    text = (message or '').strip().rstrip('!?！？。~～,.，、')
    lowered = text.lower()
    if lowered in _HELLO:
        return _REPLY_HELLO
    if lowered in _THANKS:
        return _REPLY_THANKS
    if lowered in _BYE:
        return _REPLY_BYE
    if '你是谁' in text or '介绍一下你自己' in text:
        return _REPLY_IDENTITY
    if '你能做什么' in text or '怎么用' in text or '有什么功能' in text:
        return _REPLY_CAPABILITY
    return None


def rule_route(message: str) -> tuple[str, str] | None:
    """关键词规则路由：足够明确的句子不需要调模型。"""
    text = message or ''
    for keyword in _CONSISTENCY_KEYWORDS:
        if keyword in text:
            return 'consistency', f'命中关键词「{keyword}」'
    for keyword in _STYLE_KEYWORDS:
        if keyword in text:
            return 'style_qa', f'命中关键词「{keyword}」'
    for keyword in _WRITING_KEYWORDS:
        if keyword in text:
            return 'writing', f'命中关键词「{keyword}」'
    return None


async def llm_route(
    message: str,
    *,
    api_key: str,
    provider: str | None,
    model: str | None,
) -> tuple[str, str]:
    """含糊输入交给 LLM 判类；失败一律落到 clarify，不阻塞主流程。"""
    try:
        llm, _dropped = LLMFactory.get_llm(
            'intent',
            api_key=api_key,
            provider=provider,
            model=model,
            temperature=0,
        )
        response = await llm.ainvoke([
            HumanMessage(content=_ROUTE_PROMPT.format(message=message)),
        ])
        raw = response.content if isinstance(response.content, str) else ''
        parsed = json.loads(raw.strip().strip('`'))
        label = str(parsed.get('label', 'clarify')).strip().lower()
        if label not in LABELS:
            label = 'clarify'
        return label, str(parsed.get('reason', 'LLM 判断'))
    except Exception as exc:  # 路由失败不该让整个请求挂掉
        logger.warning('chat.route_failed', error=str(exc))
        return 'clarify', '路由判断失败，需要你补充一句'


def _guidance(label: str) -> dict[str, Any]:
    if label == 'style_qa':
        return {
            'type': 'guidance',
            'message': '风格诊断正在接入中：它会先检索你导入的文风语料，再指出这篇稿子差在哪。',
            'action_label': '打开文风管理',
            'action_url': '#styles',
        }
    if label == 'consistency':
        return {
            'type': 'guidance',
            'message': '一致性审查正在接入中：它会比对人设、时间线和伏笔，列出冲突点。',
            'action_label': '打开工作台',
            'action_url': '#workspace',
        }
    return {
        'type': 'guidance',
        'message': '我还不太确定你想做什么。是要写一段新内容，还是检查这篇稿子？',
        'action_label': '',
        'action_url': '',
    }


def _writing_payload(request: ChatRequest) -> WritingRequest | None:
    raw = request.context.get('payload')
    if not isinstance(raw, dict):
        return None
    payload = WritingRequest(**raw)
    if not payload.api_key.strip() or not payload.template_ids:
        return None
    return payload


@router.post('/v1/chat/stream', tags=['AI 助手'])
async def chat_stream(request: ChatRequest, db: AsyncSession = Depends(get_db)) -> StreamingResponse:
    async def event_stream() -> AsyncIterator[str]:
        # Step 0：规则前置拦截
        canned = pre_filter(request.message)
        if canned is not None:
            yield _sse('token', {'type': 'token', 'data': canned})
            yield _sse('done', {})
            return

        # Step 1：意图路由（规则优先，含糊才问模型）
        routed = rule_route(request.message)
        if routed is None:
            payload = _writing_payload(request)
            api_key = (payload.api_key if payload else '') or str(
                request.context.get('api_key', '') or ''
            )
            if api_key:
                routed = await llm_route(
                    request.message,
                    api_key=api_key,
                    provider=(payload.provider if payload else None),
                    model=(payload.model if payload else None),
                )
            else:
                routed = ('clarify', '没有可用的 API Key，按规则无法判断')

        label, reason = routed

        # Step 2：推路由决策，前端显示"已切换到 XX"
        yield _sse('routing_decision', {
            'type': 'routing_decision',
            'agent_type': label,
            'agent_display': _DISPLAY.get(label, ''),
            'reason': reason,
        })

        # Step 3：分发
        if label == 'writing':
            payload = _writing_payload(request)
            if payload is None:
                yield _sse('guidance', {
                    'type': 'guidance',
                    'message': '需要在顶部填写 API Key，并在左侧启用至少一个模板，才能开始写。',
                    'action_label': '打开工作台',
                    'action_url': '#workspace',
                })
            else:
                templates = await _load_templates(db, payload.template_ids)
                if not templates:
                    yield _sse('guidance', {
                        'type': 'guidance',
                        'message': '启用的模板都找不到，请重新选择模板。',
                        'action_label': '',
                        'action_url': '',
                    })
                else:
                    async for event in writing_event_stream(payload, templates):
                        yield event
                    return
        else:
            yield _sse('guidance', _guidance(label))

        yield _sse('done', {})

    return StreamingResponse(
        event_stream(),
        media_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
        },
    )
