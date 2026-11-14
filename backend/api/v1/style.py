"""范例文章 Style Card 与参考片段路由（9 个端点）。

旧前缀 ``/api/style-profiles`` 保留为别名；新前缀 ``/api/v1/style``。
GET 类接口在模板不存在时按旧行为返回 404，其余业务错误走统一的 400。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.exceptions import GenerationError
from backend.dependencies import get_db
from backend.services import style_excerpt_service as excerpt_svc
from backend.services import style_profile_service as profile_svc

router = APIRouter()


class AnalyzeRequest(BaseModel):
    api_key: str = ''
    provider: str = 'deepseek'
    model: str = 'deepseek-v4-pro'


class StyleCardUpdate(BaseModel):
    model_config = ConfigDict(extra='allow')

    card: dict[str, Any] | None = None
    is_primary: bool | None = None


class ExcerptUpdate(BaseModel):
    model_config = ConfigDict(extra='allow')

    scene_type: str | None = None
    pov: str | None = None
    emotion: str | None = None
    pace: str | None = None
    tags: list[str] | None = None
    functions: list[str] | None = None
    is_enabled: bool | None = None
    is_pinned: bool | None = None


def _profile_payload(profile, template) -> dict[str, Any]:
    if profile is not None:
        return profile.to_dict(profile_svc.style_source_hash(template.content))
    return {
        'template_id': template.id,
        'analysis_status': 'missing',
        'is_stale': False,
        'card': None,
        'is_primary': False,
    }


@router.get('/v1/style/{template_id}', tags=['文风'])
@router.get('/style-profiles/{template_id}', tags=['文风'], include_in_schema=False)
async def get_profile(template_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    try:
        template, profile = await profile_svc.get_style_profile(db, template_id)
    except GenerationError as exc:
        return JSONResponse(status_code=404, content={'success': False, 'error': str(exc)})
    return {'success': True, 'data': _profile_payload(profile, template)}


@router.put('/v1/style/{template_id}', tags=['文风'])
@router.put('/style-profiles/{template_id}', tags=['文风'], include_in_schema=False)
async def save_profile(
    template_id: int,
    payload: StyleCardUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    profile = await profile_svc.update_style_profile(
        db,
        template_id,
        card=payload.card,
        is_primary=payload.is_primary,
    )
    template, _ = await profile_svc.get_style_profile(db, template_id)
    return {'success': True, 'data': _profile_payload(profile, template)}


async def _analyze(template_id: int, payload: AnalyzeRequest, db: AsyncSession):
    profile = await profile_svc.analyze_style_profile(
        db,
        template_id=template_id,
        api_key=payload.api_key.strip(),
        provider=payload.provider or 'deepseek',
        model=payload.model or 'deepseek-v4-pro',
    )
    template, _ = await profile_svc.get_style_profile(db, template_id)
    return {'success': True, 'data': _profile_payload(profile, template)}


@router.post('/v1/style/{template_id}/analyze', tags=['文风'])
@router.post('/style-profiles/{template_id}/analyze', tags=['文风'], include_in_schema=False)
async def analyze_profile(
    template_id: int,
    payload: AnalyzeRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _analyze(template_id, payload or AnalyzeRequest(), db)


@router.post('/v1/style/{template_id}/refresh', tags=['文风'])
@router.post('/style-profiles/{template_id}/refresh', tags=['文风'], include_in_schema=False)
async def refresh_profile(
    template_id: int,
    payload: AnalyzeRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    return await _analyze(template_id, payload or AnalyzeRequest(), db)


@router.post('/v1/style/{template_id}/restore', tags=['文风'])
@router.post('/style-profiles/{template_id}/restore', tags=['文风'], include_in_schema=False)
async def restore_profile(template_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    profile = await profile_svc.restore_analysis_card(db, template_id)
    template, _ = await profile_svc.get_style_profile(db, template_id)
    return {'success': True, 'data': _profile_payload(profile, template)}


@router.get('/v1/style/{template_id}/excerpts', tags=['文风'])
@router.get('/style-profiles/{template_id}/excerpts', tags=['文风'], include_in_schema=False)
async def list_excerpts(template_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    try:
        excerpts = await excerpt_svc.get_style_excerpts(db, template_id)
    except GenerationError as exc:
        return JSONResponse(status_code=404, content={'success': False, 'error': str(exc)})
    return {'success': True, 'data': [item.to_dict() for item in excerpts]}


@router.post('/v1/style/{template_id}/excerpts/rebuild', tags=['文风'])
@router.post(
    '/style-profiles/{template_id}/excerpts/rebuild',
    tags=['文风'],
    include_in_schema=False,
)
async def rebuild_excerpts(
    template_id: int,
    payload: AnalyzeRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    request_data = payload or AnalyzeRequest()
    excerpts = await excerpt_svc.rebuild_style_excerpts(
        db,
        template_id=template_id,
        api_key=request_data.api_key.strip(),
        provider=request_data.provider or 'deepseek',
        model=request_data.model or 'deepseek-v4-pro',
    )
    return {'success': True, 'data': [item.to_dict() for item in excerpts]}


@router.put('/v1/style/{template_id}/excerpts/{excerpt_id}', tags=['文风'])
@router.put(
    '/style-profiles/{template_id}/excerpts/{excerpt_id}',
    tags=['文风'],
    include_in_schema=False,
)
async def save_excerpt(
    template_id: int,
    excerpt_id: int,
    payload: ExcerptUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    changes = payload.model_dump(exclude_none=True)
    excerpt = await excerpt_svc.update_style_excerpt(db, template_id, excerpt_id, changes)
    return {'success': True, 'data': excerpt.to_dict()}


@router.delete('/v1/style/{template_id}/excerpts/{excerpt_id}', tags=['文风'])
@router.delete(
    '/style-profiles/{template_id}/excerpts/{excerpt_id}',
    tags=['文风'],
    include_in_schema=False,
)
async def remove_excerpt(
    template_id: int,
    excerpt_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await excerpt_svc.delete_style_excerpt(db, template_id, excerpt_id)
    return {'success': True}
