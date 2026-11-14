"""写作路由：模型列表、分类、预览、生成（同步与流式）。

``generate`` 与 ``generate-stream`` 都走同一张写作图：流式只是把图内节点
推出来的事件转成 SSE，图本身只有一份实现。旧路径 ``/api/generation/*``
保留为别名，前端不用改。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator

from fastapi import APIRouter, Depends, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.adapters.llm_openai_compat import describe_provider
from backend.agents.writing.graph import build_writing_graph
from backend.agents.writing.nodes import assemble_prompt_node
from backend.agents.writing.streaming import use_writer
from backend.config import DEFAULT_DEAI_PROMPT, LLM_PROVIDERS, TEMPLATE_CATEGORIES
from backend.core.document_text import extract_uploaded_bytes
from backend.core.exceptions import GenerationError
from backend.core.logger import get_logger
from backend.core.token_budget import calculate_token_budget
from backend.db.models import PromptTemplate
from backend.dependencies import get_db
from backend.services import editing_service

logger = get_logger(__name__)
router = APIRouter()


class WritingRequest(BaseModel):
    """生成请求。字段与原 ``GenerationRequest.from_mapping`` 一一对应。"""

    model_config = ConfigDict(extra='ignore')

    api_key: str = ''
    provider: str = 'deepseek'
    model: str = 'deepseek-v4-pro'
    template_ids: list[int] = Field(default_factory=list)
    custom_prefix: str = ''
    custom_suffix: str = ''
    previous_article: str = ''
    deai_enabled: bool = False
    deai_prompt: str = ''
    title: str = ''
    style_strength: str = 'light'
    structured_prompt_enabled: bool = False
    style_mode: str = 'legacy'
    scene_type: str = 'auto'
    style_corpus_ids: list[int] = Field(default_factory=list)
    embedding_api_key: str = ''
    style_reference_enabled: bool = False
    strict_style_rewrite_enabled: bool | None = None
    thinking_enabled: bool = False
    reasoning_effort: str = 'high'
    max_tokens: int = 0
    sampling: dict[str, Any] = Field(default_factory=dict)
    stream: bool = False

    def resolved_style_reference(self) -> bool:
        """旧字段 strict_style_rewrite_enabled 是新开关的兼容别名。"""
        return bool(self.style_reference_enabled or self.strict_style_rewrite_enabled)


async def _load_templates(session: AsyncSession, ids: list[int]) -> list[dict[str, Any]]:
    if not ids:
        return []
    rows = (await session.execute(
        select(PromptTemplate).where(PromptTemplate.id.in_(ids))
    )).scalars().all()
    return [row.to_dict() for row in rows]


def _initial_state(payload: WritingRequest, templates: list[dict[str, Any]], *, stream: bool) -> dict:
    return {
        'templates': templates,
        'template_ids': [item['id'] for item in templates],
        'previous_article': payload.previous_article,
        'title': payload.title,
        'api_key': payload.api_key.strip(),
        'provider': payload.provider,
        'model': payload.model,
        'thinking_enabled': payload.thinking_enabled,
        'reasoning_effort': payload.reasoning_effort,
        'max_tokens': payload.max_tokens,
        'sampling': payload.sampling,
        'custom_prefix': payload.custom_prefix,
        'custom_suffix': payload.custom_suffix,
        'deai_enabled': payload.deai_enabled,
        'deai_prompt': payload.deai_prompt,
        'style_reference_enabled': payload.resolved_style_reference(),
        'style_mode': payload.style_mode,
        'style_strength': payload.style_strength,
        'scene_type': payload.scene_type,
        'style_corpus_ids': list(payload.style_corpus_ids),
        'embedding_api_key': payload.embedding_api_key,
        'structured_prompt_enabled': payload.structured_prompt_enabled,
        'stream': stream,
        'messages': [],
        'errors': [],
        'sampling_dropped': [],
    }


def _complete_payload(state: dict[str, Any]) -> dict[str, Any]:
    story = state.get('story_content', '')
    deai = state.get('deai_content', '')
    styled = state.get('style_reference_content', '')
    finish_reason = state.get('finish_reason')
    return {
        'record_id': state.get('record_id'),
        'reasoning_content': state.get('reasoning_content', ''),
        'first_content': story,
        'deai_content': deai,
        'style_rewrite_content': styled,
        'style_reference_content': styled,
        'final_content': state.get('final_content', ''),
        'finish_reason': finish_reason,
        'truncated': finish_reason == 'length',
        'sampling_dropped': state.get('sampling_dropped') or [],
        'style_reference_metadata': (state.get('style_metadata') or {}).get('style_reference', {}),
        'style_rewrite_status': state.get('style_rewrite_status', 'disabled'),
        'token_budget': state.get('token_budget'),
    }


def _validate(payload: WritingRequest) -> list[str]:
    errors: list[str] = []
    if not payload.api_key.strip():
        errors.append('请输入API密钥')
    if not payload.template_ids:
        errors.append('请至少启用一个提示词模板')
    if payload.provider not in LLM_PROVIDERS:
        errors.append('不支持的模型提供商')
    if payload.reasoning_effort not in {'high', 'max'}:
        errors.append('思考强度参数无效')
    return errors


def _sse(event: str, payload: Any) -> str:
    body = '' if payload is None else json.dumps(payload, ensure_ascii=False)
    return f'event: {event}\ndata: {body}\n\n'


# ── 元信息 ───────────────────────────────────────────────

@router.get('/v1/writing/models', tags=['写作'])
@router.get('/generation/models', tags=['写作'], include_in_schema=False)
async def get_models() -> dict[str, Any]:
    providers = {
        key: {
            'name': config['name'],
            'models': config['models'],
            'sampling': describe_provider(key),
        }
        for key, config in LLM_PROVIDERS.items()
    }
    return {'success': True, 'data': providers}


@router.get('/v1/writing/categories', tags=['写作'])
@router.get('/generation/categories', tags=['写作'], include_in_schema=False)
async def get_categories() -> dict[str, Any]:
    return {'success': True, 'data': TEMPLATE_CATEGORIES}


@router.get('/v1/writing/deai-prompt', tags=['写作'])
@router.get('/generation/default-deai-prompt', tags=['写作'], include_in_schema=False)
async def get_default_deai_prompt() -> dict[str, Any]:
    return {'success': True, 'data': DEFAULT_DEAI_PROMPT}


# ── 提示词预览（不调用模型）───────────────────────────────

@router.post('/v1/writing/preview', tags=['写作'])
@router.post('/generation/preview-prompt', tags=['写作'], include_in_schema=False)
async def preview_prompt(
    payload: WritingRequest,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    templates = await _load_templates(db, payload.template_ids)
    state: dict[str, Any] = {
        'templates': templates,
        'custom_prefix': payload.custom_prefix,
        'custom_suffix': payload.custom_suffix,
        'previous_article': payload.previous_article,
        'style_strength': payload.style_strength,
        'structured_prompt_enabled': payload.structured_prompt_enabled,
        'style_mode': payload.style_mode,
    }
    assembled = await assemble_prompt_node(state)
    state.update(assembled)

    budget = calculate_token_budget(
        state['assembled_prompt'],
        payload.provider,
        payload.model,
        deai_enabled=payload.deai_enabled,
        deai_prompt=payload.deai_prompt,
        thinking_enabled=payload.thinking_enabled,
        reasoning_effort=payload.reasoning_effort,
        messages=state['messages'] if payload.structured_prompt_enabled else None,
        style_reference_enabled=payload.resolved_style_reference(),
        max_tokens=payload.max_tokens,
    )

    style_mode = payload.style_mode
    if style_mode == 'smart':
        style_mode = 'smart_fallback_legacy'

    return {
        'success': True,
        'data': {
            'assembled_prompt': state['assembled_prompt'],
            'messages': state['messages'],
            'prompt_mode': state.get('prompt_route', 'legacy'),
            'message_count': len(state['messages']),
            'template_count': len(templates),
            'char_count': len(state['assembled_prompt']),
            'token_budget': budget,
            'style_mode': style_mode,
            'style_metadata': state.get('style_metadata', {}),
            'style_reference_plan': {},
        },
    }


# ── 生成（同步）────────────────────────────────────────────

@router.post('/v1/writing/generate', tags=['写作'])
@router.post('/generation/generate', tags=['写作'], include_in_schema=False)
async def generate(payload: WritingRequest, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    errors = _validate(payload)
    if errors:
        raise GenerationError(errors[0])

    templates = await _load_templates(db, payload.template_ids)
    if not templates:
        raise GenerationError('没有活跃的模板')

    graph = build_writing_graph()
    state = await graph.ainvoke(_initial_state(payload, templates, stream=False))

    if state.get('errors'):
        raise GenerationError(state['errors'][0])

    logger.info('writing.generate_done', record_id=state.get('record_id'))
    return {'success': True, 'data': _complete_payload(state)}


# ── 局部编辑（选中文字）─────────────────────────────────────

class TransformRequest(BaseModel):
    model_config = ConfigDict(extra='ignore')

    api_key: str = ''
    text: str = ''
    operation: str = 'rewrite'
    instruction: str = ''
    surrounding_context: str = ''
    provider: str = 'deepseek'
    model: str = 'deepseek-v4-pro'


@router.post('/v1/writing/transform', tags=['写作'])
@router.post('/generation/transform-text', tags=['写作'], include_in_schema=False)
async def transform_text(payload: TransformRequest) -> dict[str, Any]:
    result = await editing_service.transform_text(
        text=payload.text,
        operation=payload.operation,
        instruction=payload.instruction,
        surrounding_context=payload.surrounding_context,
        api_key=payload.api_key,
        provider=payload.provider,
        model=payload.model,
    )
    return {
        'success': True,
        'data': {'content': result['content'], 'usage': result.get('usage', {})},
    }


# ── 前置文章导入（TXT / DOCX / DOC）──────────────────────────

@router.post('/v1/writing/extract-text', tags=['写作'])
@router.post('/generation/extract-text', tags=['写作'], include_in_schema=False)
async def extract_article_text(file: UploadFile) -> JSONResponse:
    filename = file.filename or ''
    try:
        raw = await file.read()
        text = extract_uploaded_bytes(raw, filename)
    except OverflowError as exc:
        return JSONResponse(status_code=413, content={'success': False, 'error': str(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=400, content={'success': False, 'error': str(exc)})

    return JSONResponse(content={
        'success': True,
        'data': {'text': text, 'char_count': len(text), 'filename': filename},
    })


# ── 生成（流式 SSE）────────────────────────────────────────

async def writing_event_stream(
    payload: WritingRequest,
    templates: list[dict[str, Any]],
) -> AsyncIterator[str]:
    """把写作图跑成一条 SSE 事件流。

    统一入口 ``/api/v1/chat/stream`` 也复用这段，避免写两套流式逻辑。
    """
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    initial = _initial_state(payload, templates, stream=True)

    async def runner() -> None:
        # 事件出口绑定在当前任务里：节点 emit 的事件会进队列
        with use_writer(queue.put_nowait):
            try:
                state = await build_writing_graph().ainvoke(initial)
                if state.get('errors'):
                    await queue.put({'type': 'error', 'data': state['errors'][0]})
                else:
                    await queue.put({'type': 'complete', 'data': _complete_payload(state)})
            except Exception as exc:  # 图内异常也要让前端收到明确原因
                logger.exception('writing.stream_failed', error=str(exc))
                await queue.put({'type': 'error', 'data': '生成过程中出现异常，请稍后重试。'})
            finally:
                await queue.put(None)

    task = asyncio.create_task(runner())
    try:
        yield _sse('status', {'type': 'status', 'data': 'prompt_preparing'})
        while True:
            item = await queue.get()
            if item is None:
                break
            yield _sse(item.get('type', 'status'), item)
    finally:
        if not task.done():
            task.cancel()
        else:
            task.exception()  # 取走异常，避免 asyncio 警告
        yield _sse('done', {})


@router.post('/v1/writing/generate-stream', tags=['写作'])
@router.post('/generation/generate-stream', tags=['写作'], include_in_schema=False)
async def generate_stream(
    payload: WritingRequest,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    errors = _validate(payload)
    if errors:
        raise GenerationError(errors[0])

    templates = await _load_templates(db, payload.template_ids)
    if not templates:
        raise GenerationError('没有活跃的模板')

    return StreamingResponse(
        writing_event_stream(payload, templates),
        media_type='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
        },
    )
