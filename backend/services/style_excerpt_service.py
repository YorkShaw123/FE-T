"""范例文章切片与参考片段管理（异步版）。

切片规则原样保留：按自然段聚合，目标 560 字上下，单段超过 1000 字先按句号切开。
打标签走 ``style_profile_service._call_model`` 这个同一个接缝，每批 6 段。
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.exceptions import GenerationError
from backend.db.models import PromptTemplate, StyleExcerpt, StyleProfile
from backend.services.style_profile_service import (
    _call_model,
    _extract_response_json,
    style_source_hash,
)

SCENE_TYPES = {
    'dialogue', 'action', 'psychology', 'environment', 'transition', 'narration', 'mixed',
}
PACES = {'slow', 'medium', 'fast'}
SCENE_LABELS = {
    'dialogue': '对话', 'action': '动作', 'psychology': '心理',
    'environment': '环境', 'transition': '转场', 'narration': '叙述', 'mixed': '综合',
}

LABEL_SYSTEM_PROMPT = '你是文学场景片段标签器。只输出合法 JSON，不输出解释。'


def _content_hash(content: str | None) -> str:
    return hashlib.sha256((content or '').encode('utf-8')).hexdigest()


def _split_long_paragraph(paragraph: str, maximum: int) -> list[str]:
    sentences = re.split(r'(?<=[。！？!?])', paragraph)
    chunks: list[str] = []
    current = ''
    for sentence in sentences:
        if current and len(current) + len(sentence) > maximum:
            chunks.append(current.strip())
            current = sentence
        else:
            current += sentence
    if current.strip():
        chunks.append(current.strip())
    return chunks


def split_reference_text(
    content: str | None,
    target: int = 560,
    minimum: int = 260,
    maximum: int = 1000,
) -> list[str]:
    """按自然段聚合为 300—1000 字左右的语义片段。"""
    raw_paragraphs = [
        item.strip() for item in re.split(r'\n\s*\n+', content or '') if item.strip()
    ]
    paragraphs: list[str] = []
    for paragraph in raw_paragraphs:
        if len(paragraph) > maximum:
            paragraphs.extend(_split_long_paragraph(paragraph, maximum))
        else:
            paragraphs.append(paragraph)

    chunks: list[str] = []
    current: list[str] = []
    current_length = 0
    for paragraph in paragraphs:
        next_length = current_length + len(paragraph) + (2 if current else 0)
        if current and next_length > maximum:
            chunks.append('\n\n'.join(current))
            current, current_length = [], 0
        current.append(paragraph)
        current_length += len(paragraph) + (2 if len(current) > 1 else 0)
        if current_length >= target:
            chunks.append('\n\n'.join(current))
            current, current_length = [], 0
    if current:
        tail = '\n\n'.join(current)
        if chunks and len(tail) < minimum and len(chunks[-1]) + len(tail) + 2 <= maximum:
            chunks[-1] += '\n\n' + tail
        else:
            chunks.append(tail)
    return [item for item in chunks if item.strip()]


def _dialogue_ratio(content: str | None) -> float:
    quoted = ''.join(re.findall(r'[“\"]([^”\"]+)[”\"]', content or ''))
    return round(min(1.0, len(quoted) / max(1, len(content or ''))), 3)


def _label_prompt(batch: list[tuple[int, str]]) -> str:
    excerpts = '\n\n'.join(
        f'<excerpt index="{index}">{content}</excerpt>' for index, content in batch
    )
    return f"""请为下面的文学片段生成检索标签，不要总结剧情，不要复述原文。
只输出 JSON 对象，格式严格如下：
{{"items":[{{"index":0,"scene_type":"dialogue|action|psychology|environment|transition|narration|mixed",
"pov":"叙述人称与限制视角","emotion":"最多三个情绪词，以顿号连接",
"pace":"slow|medium|fast","tags":["最多5个可检索标签"],
"functions":["信息试探|关系变化等叙事功能"]}}]}}

{excerpts}"""


def _normalize_label(item: dict[str, Any], index: int) -> dict[str, Any]:
    scene_type = str(item.get('scene_type', 'mixed')).strip().lower()
    pace = str(item.get('pace', 'medium')).strip().lower()
    try:
        normalized_index = int(item.get('index', index))
    except (TypeError, ValueError):
        normalized_index = index
    return {
        'index': normalized_index,
        'scene_type': scene_type if scene_type in SCENE_TYPES else 'mixed',
        'pov': str(item.get('pov', '')).strip(),
        'emotion': str(item.get('emotion', '')).strip(),
        'pace': pace if pace in PACES else 'medium',
        'tags': [str(v).strip() for v in item.get('tags', []) if str(v).strip()][:5],
        'functions': [str(v).strip() for v in item.get('functions', []) if str(v).strip()][:5],
    }


async def _label_batches(
    chunks: list[str],
    *,
    api_key: str,
    provider: str,
    model: str,
) -> dict[int, dict[str, Any]]:
    labels: dict[int, dict[str, Any]] = {}
    for offset in range(0, len(chunks), 6):
        batch_contents = chunks[offset:offset + 6]
        batch = list(enumerate(batch_contents, start=offset))
        response = await _call_model(
            agent_type='style_excerpt',
            api_key=api_key,
            provider=provider,
            model=model,
            system_prompt=LABEL_SYSTEM_PROMPT,
            user_prompt=_label_prompt(batch),
            max_tokens=2500,
        )
        payload = _extract_response_json(response)
        items = payload.get('items', []) if isinstance(payload, dict) else []
        if not isinstance(items, list):
            raise GenerationError('片段标签结果缺少 items 数组')
        for fallback_index, item in enumerate(items, start=offset):
            if isinstance(item, dict):
                normalized = _normalize_label(item, fallback_index)
                labels[normalized['index']] = normalized
    return labels


async def rebuild_style_excerpts(
    session: AsyncSession,
    template_id: int,
    api_key: str,
    provider: str,
    model: str,
) -> list[StyleExcerpt]:
    template = await session.get(PromptTemplate, template_id)
    if not template or template.category != 'example':
        raise GenerationError('只有范例文章模板可以生成参考片段')

    profile = (await session.execute(
        select(StyleProfile).where(StyleProfile.template_id == template.id)
    )).scalar_one_or_none()
    if not profile or profile.analysis_status != 'ready':
        raise GenerationError('请先生成有效的 Style Card')
    if profile.source_hash != style_source_hash(template.content):
        raise GenerationError('Style Card 已过期，请先重新分析风格')
    if not api_key or not api_key.strip():
        raise GenerationError('请先输入 API 密钥')

    chunks = split_reference_text(template.content)
    if not chunks:
        raise GenerationError('范例文章没有可切分的正文')

    labels = await _label_batches(chunks, api_key=api_key, provider=provider, model=model)
    if set(labels) != set(range(len(chunks))):
        raise GenerationError('部分片段未获得有效标签，请重新分析')

    await session.execute(
        delete(StyleExcerpt).where(StyleExcerpt.style_profile_id == profile.id)
    )
    now = datetime.now(timezone.utc)
    for index, content in enumerate(chunks):
        label = labels[index]
        session.add(StyleExcerpt(
            style_profile_id=profile.id,
            content=content,
            content_hash=_content_hash(content),
            source_order=index,
            scene_type=label['scene_type'],
            pov=label['pov'],
            emotion=label['emotion'],
            dialogue_ratio=_dialogue_ratio(content),
            pace=label['pace'],
            tags_json=json.dumps(label['tags'], ensure_ascii=False),
            functions_json=json.dumps(label['functions'], ensure_ascii=False),
            analysis_model=model,
            analysis_status='ready',
            created_at=now,
            updated_at=now,
        ))
    await session.flush()

    return list((await session.execute(
        select(StyleExcerpt)
        .where(StyleExcerpt.style_profile_id == profile.id)
        .order_by(StyleExcerpt.source_order)
    )).scalars().all())


async def get_style_excerpts(
    session: AsyncSession,
    template_id: int,
) -> list[StyleExcerpt]:
    template = await session.get(PromptTemplate, template_id)
    if not template:
        raise GenerationError('模板不存在')
    profile = (await session.execute(
        select(StyleProfile).where(StyleProfile.template_id == template.id)
    )).scalar_one_or_none()
    if not profile:
        return []
    return list((await session.execute(
        select(StyleExcerpt)
        .where(StyleExcerpt.style_profile_id == profile.id)
        .order_by(StyleExcerpt.source_order)
    )).scalars().all())


async def _load_excerpt(
    session: AsyncSession,
    template_id: int,
    excerpt_id: int,
) -> StyleExcerpt:
    template = await session.get(PromptTemplate, template_id)
    excerpt = await session.get(StyleExcerpt, excerpt_id)
    if not template or not excerpt:
        raise GenerationError('参考片段不存在')

    profile = await session.get(StyleProfile, excerpt.style_profile_id)
    if not profile or profile.template_id != template.id:
        raise GenerationError('参考片段不存在')
    return excerpt


async def update_style_excerpt(
    session: AsyncSession,
    template_id: int,
    excerpt_id: int,
    data: dict[str, Any],
) -> StyleExcerpt:
    excerpt = await _load_excerpt(session, template_id, excerpt_id)

    if 'scene_type' in data:
        value = str(data['scene_type']).strip().lower()
        excerpt.scene_type = value if value in SCENE_TYPES else 'mixed'
    if 'pov' in data:
        excerpt.pov = str(data['pov']).strip()
    if 'emotion' in data:
        excerpt.emotion = str(data['emotion']).strip()
    if 'pace' in data:
        value = str(data['pace']).strip().lower()
        excerpt.pace = value if value in PACES else 'medium'
    if 'tags' in data and isinstance(data['tags'], list):
        excerpt.tags_json = json.dumps(
            [str(item).strip() for item in data['tags'] if str(item).strip()][:5],
            ensure_ascii=False,
        )
    if 'functions' in data and isinstance(data['functions'], list):
        excerpt.functions_json = json.dumps(
            [str(item).strip() for item in data['functions'] if str(item).strip()][:5],
            ensure_ascii=False,
        )
    if 'is_enabled' in data:
        excerpt.is_enabled = bool(data['is_enabled'])
    if 'is_pinned' in data:
        excerpt.is_pinned = bool(data['is_pinned'])

    excerpt.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return excerpt


async def delete_style_excerpt(
    session: AsyncSession,
    template_id: int,
    excerpt_id: int,
) -> None:
    excerpt = await _load_excerpt(session, template_id, excerpt_id)
    await session.delete(excerpt)
    await session.flush()
