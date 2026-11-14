"""范例文章 Style Card 的分析、校验与持久化（异步版）。

与原实现逐函数对应，唯一的结构差异是把模型调用抽成 ``_call_model`` 一个接缝：
- 生产环境走 ``core/llm_factory``；
- 测试里替换这一个小函数就能整条跑通，不需要网络。

校验规则一字未改：schema_version 固定为 1，五组对象必填，checkable_rules
每条必须带 rule，priority 只认 hard/high/medium。
"""

from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from sqlalchemy import delete, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.exceptions import GenerationError
from backend.core.llm_factory import LLMFactory
from backend.core.logger import get_logger
from backend.db.models import PromptTemplate, StyleExcerpt, StyleProfile

logger = get_logger(__name__)

STYLE_CARD_SCHEMA_VERSION = 1
REQUIRED_OBJECTS = ('narration', 'rhythm', 'language', 'dialogue', 'description_balance')
DEFAULT_CARD: dict[str, Any] = {
    'schema_version': STYLE_CARD_SCHEMA_VERSION,
    'summary': '',
    'narration': {'person': '', 'distance': '', 'tense': '', 'pov_rules': []},
    'rhythm': {'sentence_pattern': '', 'paragraph_pattern': '', 'transition_style': ''},
    'language': {
        'register': '', 'imagery': '', 'rhetoric_frequency': '',
        'preferred_behaviors': [],
    },
    'dialogue': {'ratio': '', 'length': '', 'subtext': '', 'tag_style': ''},
    'description_balance': {
        'action': '', 'dialogue': '', 'psychology': '', 'environment': '',
    },
    'avoid': [],
    'checkable_rules': [],
}

STYLE_ANALYSIS_SYSTEM_PROMPT = """你是一名文学风格分析器。你的任务不是总结故事内容，而是将
参考文本转换为可迁移、可执行、可检查的写作规则。禁止使用“优美、细腻、有感染力、很有画面感”
等模糊评价。只输出一个合法 JSON 对象，不要 Markdown 代码块、解释或前后缀。"""


def style_source_hash(content: str | None) -> str:
    return hashlib.sha256((content or '').strip().encode('utf-8')).hexdigest()


def _analysis_prompt(content: str) -> str:
    schema = json.dumps(DEFAULT_CARD, ensure_ascii=False, indent=2)
    return f"""请忽略参考文本的故事内容，只分析可迁移的语言机制。

必须提取：叙述视角与距离、句长与停顿、段落组织、转场方式、对话比例与潜台词、动作/心理/环境
描写比例、修辞频率、正向写作行为、明确禁用表达，以及至少 8 条可检查规则。

checkable_rules 每项格式：
{{"id":"唯一规则ID","rule":"具体规则","priority":"hard|high|medium"}}

严格沿用下面的 JSON 字段结构；未知值使用空字符串或空数组，不得新增故事人物、地点或情节：
{schema}

<reference_text>
{content.strip()}
</reference_text>"""


def _extract_json_object(text: str | None) -> dict[str, Any]:
    raw = (text or '').strip()
    if raw.startswith('```'):
        raw = raw.strip('`').strip()
        if raw.lower().startswith('json'):
            raw = raw[4:].strip()
    start = raw.find('{')
    end = raw.rfind('}')
    if start < 0 or end <= start:
        raise GenerationError('风格分析没有返回有效 JSON')
    try:
        return json.loads(raw[start:end + 1])
    except json.JSONDecodeError as exc:
        raise GenerationError('风格分析结果不是有效的 JSON 格式，请重试') from exc


def _extract_response_json(response: dict[str, Any] | None) -> dict[str, Any]:
    """优先解析正文；正文无有效 JSON 时兼容固定思考模型的 reasoning 字段。"""
    errors: list[Exception] = []
    for field in ('content', 'reasoning_content'):
        candidate = (response or {}).get(field, '')
        if not str(candidate or '').strip():
            continue
        try:
            return _extract_json_object(candidate)
        except GenerationError as exc:
            errors.append(exc)
    if errors:
        raise errors[-1]
    raise GenerationError('风格分析没有返回有效 JSON')


def validate_style_card(card: Any) -> dict[str, Any]:
    """校验并补齐 V1 已知字段，保留用户手工加入的扩展字段。"""
    if not isinstance(card, dict):
        raise GenerationError('Style Card 必须是 JSON 对象')

    normalized = copy.deepcopy(card)
    normalized['schema_version'] = STYLE_CARD_SCHEMA_VERSION

    summary = card.get('summary', '')
    if summary is None:
        summary = ''
    if not isinstance(summary, str):
        raise GenerationError('Style Card 的 summary 必须是字符串')
    normalized['summary'] = summary.strip()

    for key in REQUIRED_OBJECTS:
        source = card.get(key, {})
        if source is None:
            source = {}
        if not isinstance(source, dict):
            raise GenerationError(f'Style Card 的 {key} 必须是对象')
        normalized[key] = copy.deepcopy(source)
        for field, default in DEFAULT_CARD[key].items():
            value = source.get(field, copy.deepcopy(default))
            if value is None:
                value = copy.deepcopy(default)
            if isinstance(default, list):
                if not isinstance(value, list):
                    raise GenerationError(f'Style Card 的 {key}.{field} 必须是数组')
                normalized[key][field] = [
                    str(item).strip() for item in value if str(item).strip()
                ]
            else:
                if not isinstance(value, str):
                    raise GenerationError(f'Style Card 的 {key}.{field} 必须是字符串')
                normalized[key][field] = value.strip()

    for key in ('avoid', 'checkable_rules'):
        value = card.get(key, [])
        if value is None:
            value = []
        if not isinstance(value, list):
            raise GenerationError(f'Style Card 的 {key} 必须是数组')
        normalized[key] = value

    rules = []
    for index, item in enumerate(normalized['checkable_rules'], start=1):
        if isinstance(item, str):
            item = {'id': f'rule_{index:02d}', 'rule': item, 'priority': 'medium'}
        if not isinstance(item, dict) or not str(item.get('rule', '')).strip():
            raise GenerationError('每条 checkable_rules 都必须包含 rule')
        priority = item.get('priority', 'medium')
        if priority not in {'hard', 'high', 'medium'}:
            priority = 'medium'
        rules.append({
            'id': str(item.get('id') or f'rule_{index:02d}'),
            'rule': str(item['rule']).strip(),
            'priority': priority,
        })
    normalized['checkable_rules'] = rules
    normalized['avoid'] = [str(item).strip() for item in normalized['avoid'] if str(item).strip()]
    return normalized


async def _call_model(
    *,
    agent_type: str,
    api_key: str,
    provider: str,
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
) -> dict[str, Any]:
    """唯一的模型调用接缝（测试可替换）。"""
    llm, _dropped = LLMFactory.get_llm(
        agent_type,
        api_key=api_key,
        provider=provider,
        model=model,
        temperature=0,
        streaming=False,
        max_tokens=max_tokens,
    )
    response = await llm.ainvoke([
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_prompt),
    ])
    content = response.content if isinstance(response.content, str) else json.dumps(
        response.content, ensure_ascii=False
    )
    metadata = getattr(response, 'response_metadata', None) or {}
    additional = getattr(response, 'additional_kwargs', None) or {}
    return {
        'content': content,
        'reasoning_content': metadata.get('reasoning_content') or additional.get(
            'reasoning_content', ''
        ),
    }


async def get_style_profile(
    session: AsyncSession,
    template_id: int,
) -> tuple[PromptTemplate, StyleProfile | None]:
    template = await session.get(PromptTemplate, template_id)
    if not template:
        raise GenerationError('模板不存在')
    profile = (await session.execute(
        select(StyleProfile).where(StyleProfile.template_id == template.id)
    )).scalar_one_or_none()
    return template, profile


async def analyze_style_profile(
    session: AsyncSession,
    template_id: int,
    api_key: str,
    provider: str,
    model: str,
) -> StyleProfile:
    template = await session.get(PromptTemplate, template_id)
    if not template:
        raise GenerationError('模板不存在')
    if template.category != 'example':
        raise GenerationError('只有范例文章模板可以生成 Style Card')
    if len((template.content or '').strip()) < 100:
        raise GenerationError('范例文章过短，至少需要 100 个字符才能分析风格')
    if not api_key or not api_key.strip():
        raise GenerationError('请先输入 API 密钥')

    profile = (await session.execute(
        select(StyleProfile).where(StyleProfile.template_id == template.id)
    )).scalar_one_or_none()
    if not profile:
        profile = StyleProfile(
            template_id=template.id,
            template_version=template.version,
            source_hash=style_source_hash(template.content),
            analysis_status='analyzing',
        )
        session.add(profile)
    else:
        profile.analysis_status = 'analyzing'
        profile.error_message = ''
    # 这里必须提交而不是 flush：前端会轮询这个状态显示"分析中"；
    # 同时模型调用失败回滚时，记录本身要留下，才能把状态改成 error。
    await session.commit()

    try:
        response = await _call_model(
            agent_type='style_card',
            api_key=api_key,
            provider=provider,
            model=model,
            system_prompt=STYLE_ANALYSIS_SYSTEM_PROMPT,
            user_prompt=_analysis_prompt(template.content),
            max_tokens=4096,
        )
        card = validate_style_card(_extract_response_json(response))
        card_json = json.dumps(card, ensure_ascii=False, indent=2)

        previous_source_hash = profile.source_hash
        profile.template_version = template.version
        profile.source_hash = style_source_hash(template.content)
        profile.schema_version = STYLE_CARD_SCHEMA_VERSION
        profile.analysis_card_json = card_json
        profile.card_json = card_json
        profile.analysis_model = model
        profile.analysis_status = 'ready'
        profile.error_message = ''
        profile.updated_at = datetime.now(timezone.utc)

        if previous_source_hash and previous_source_hash != profile.source_hash:
            # 原文变了，旧片段不再对应当前 Style Card
            await session.execute(
                delete(StyleExcerpt).where(StyleExcerpt.style_profile_id == profile.id)
            )
        await session.flush()
        return profile

    except Exception as exc:
        await session.rollback()
        # rollback 之后 ORM 实例已过期，直接读属性会触发惰性加载（MissingGreenlet）。
        # 这里改用 Core 语句读写状态，绕开身份映射，行为确定且与旧实现一致：
        # 有旧卡片就保留 ready，没有就标 error，并把错误信息落库。
        row = (await session.execute(
            text('SELECT id, card_json FROM style_profiles WHERE template_id = :tid'),
            {'tid': template_id},
        )).first()
        if row is not None:
            profile_id, card_json = row[0], row[1]
            try:
                previous_card = json.loads(card_json or '{}')
            except (TypeError, json.JSONDecodeError):
                previous_card = {}
            has_previous = isinstance(previous_card, dict) and bool(previous_card)
            await session.execute(
                text(
                    'UPDATE style_profiles SET analysis_status = :status, '
                    'error_message = :message WHERE id = :profile_id'
                ),
                {
                    'status': 'ready' if has_previous else 'error',
                    'message': str(exc),
                    'profile_id': profile_id,
                },
            )
            # 必须提交：上层依赖在异常时会 rollback，只 flush 会把状态改回 analyzing。
            await session.commit()
        if isinstance(exc, GenerationError):
            raise
        raise GenerationError(f'风格分析失败：{exc}') from exc


async def update_style_profile(
    session: AsyncSession,
    template_id: int,
    card: Any,
    is_primary: bool | None = None,
) -> StyleProfile:
    template, profile = await get_style_profile(session, template_id)
    if template.category != 'example':
        raise GenerationError('只有范例文章模板可以保存 Style Card')
    if not profile:
        raise GenerationError('请先分析该范例文章')

    normalized = validate_style_card(card)
    profile.card_json = json.dumps(normalized, ensure_ascii=False, indent=2)
    profile.analysis_status = 'ready'
    profile.error_message = ''
    if is_primary is not None:
        if bool(is_primary):
            others = (await session.execute(
                select(StyleProfile).where(StyleProfile.id != profile.id)
            )).scalars().all()
            for item in others:
                item.is_primary = False
        profile.is_primary = bool(is_primary)
    profile.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return profile


async def restore_analysis_card(session: AsyncSession, template_id: int) -> StyleProfile:
    _template, profile = await get_style_profile(session, template_id)
    if not profile or not profile.analysis_card_json:
        raise GenerationError('没有可恢复的自动分析结果')
    try:
        stored_card = json.loads(profile.analysis_card_json)
    except (TypeError, json.JSONDecodeError) as exc:
        raise GenerationError('自动分析结果已损坏，请重新分析') from exc

    card = validate_style_card(stored_card)
    profile.card_json = json.dumps(card, ensure_ascii=False, indent=2)
    profile.analysis_status = 'ready'
    profile.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return profile
