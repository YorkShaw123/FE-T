"""模板管理路由（13 个端点）。

每个端点都挂了两个装饰器：``/api/v1/templates/*`` 是正式路径，
``/api/templates/*`` 是迁移期的旧路径别名，前端因此可以零改动。

响应形状与旧 Flask 版本逐字段一致：``{"success": true, "data": ...}``；
错误由 ``TemplateServiceError``（400）与 404 分支分别处理。
"""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.v1.schemas import TemplateCreate, TemplateExportRequest, TemplateUpdate
from backend.db.starter_templates import create_missing_starter_templates
from backend.dependencies import get_db
from backend.services import template_service as svc

router = APIRouter()

NOT_FOUND_BODY = {'success': False, 'error': '模板不存在'}


def _not_found() -> JSONResponse:
    return JSONResponse(status_code=404, content=NOT_FOUND_BODY)


@router.get('/v1/templates', tags=['模板'])
@router.get('/templates', tags=['模板'], include_in_schema=False)
async def list_templates(
    category: str | None = None,
    active_only: bool = False,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    templates = await svc.get_all_templates(db, category=category, active_only=active_only)
    return {'success': True, 'data': [template.to_dict() for template in templates]}


@router.get('/v1/templates/grouped', tags=['模板'])
@router.get('/templates/grouped', tags=['模板'], include_in_schema=False)
async def list_grouped_templates(
    active_only: bool = False,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    grouped = await svc.get_templates_by_category(db, active_only=active_only)
    return {'success': True, 'data': grouped}


@router.delete('/v1/templates', tags=['模板'])
@router.delete('/templates/all', tags=['模板'], include_in_schema=False)
async def remove_all_templates(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await svc.delete_all_templates(db)
    return {'success': True, 'deleted': True}


@router.post('/v1/templates/starter', tags=['模板'])
@router.post('/templates/starter', tags=['模板'], include_in_schema=False)
async def add_starter_templates(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    created = await create_missing_starter_templates(db)
    return {
        'success': True,
        'created': len(created),
        'data': [template.to_dict() for template in created],
    }


@router.post('/v1/templates/export', tags=['模板'])
@router.post('/templates/export', tags=['模板'], include_in_schema=False)
async def export_templates_route(
    payload: TemplateExportRequest | None = None,
    db: AsyncSession = Depends(get_db),
) -> Response:
    request_data = payload or TemplateExportRequest()
    content = await svc.export_templates(
        db, template_ids=request_data.ids, format=request_data.format
    )
    is_json = request_data.format == 'json'
    return Response(
        content=content,
        media_type='application/json' if is_json else 'text/markdown',
        headers={
            'Content-Disposition': (
                f'attachment; filename=templates_export.{"json" if is_json else "md"}'
            )
        },
    )


@router.post('/v1/templates/import', tags=['模板'])
@router.post('/templates/import', tags=['模板'], include_in_schema=False)
async def import_templates_route(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    content_type = request.headers.get('content-type', '')
    json_data = ''

    if 'multipart/form-data' in content_type:
        form = await request.form()
        upload = form.get('file')
        if upload is not None and hasattr(upload, 'read'):
            json_data = (await upload.read()).decode('utf-8')
    else:
        body = await request.json()
        if isinstance(body, dict):
            json_data = body.get('data') or json.dumps(body, ensure_ascii=False)

    if not json_data:
        raise svc.TemplateServiceError('请提供JSON文件或数据')

    imported, skipped = await svc.import_templates(db, json_data)
    return {'success': True, 'imported': imported, 'skipped': skipped}


@router.get('/v1/templates/{template_id}', tags=['模板'])
@router.get('/templates/{template_id}', tags=['模板'], include_in_schema=False)
async def get_single_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
) -> Any:
    template = await svc.get_template(db, template_id)
    if not template:
        return _not_found()
    return {'success': True, 'data': template.to_dict()}


@router.post('/v1/templates', tags=['模板'], status_code=201)
@router.post('/templates', tags=['模板'], status_code=201, include_in_schema=False)
async def add_template(
    payload: TemplateCreate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    template = await svc.create_template(
        db,
        name=payload.name,
        category=payload.category,
        content=payload.content,
        description=payload.description,
        sort_order=payload.sort_order,
        style_strength=payload.style_strength,
    )
    return {'success': True, 'data': template.to_dict()}


@router.put('/v1/templates/{template_id}', tags=['模板'])
@router.put('/templates/{template_id}', tags=['模板'], include_in_schema=False)
async def edit_template(
    template_id: int,
    payload: TemplateUpdate,
    db: AsyncSession = Depends(get_db),
) -> Any:
    existing = await svc.get_template(db, template_id)
    if not existing:
        return _not_found()

    template = await svc.update_template(db, template_id, **payload.allowed_kwargs())
    return {
        'success': True,
        'data': template.to_dict(),
        'is_new_version': bool(template.version and template.version > 1 and template.parent_id),
    }


@router.delete('/v1/templates/{template_id}', tags=['模板'])
@router.delete('/templates/{template_id}', tags=['模板'], include_in_schema=False)
async def remove_template(template_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await svc.delete_template(db, template_id)
    return {'success': True}


@router.post('/v1/templates/{template_id}/toggle', tags=['模板'])
@router.post('/templates/{template_id}/toggle', tags=['模板'], include_in_schema=False)
async def toggle_template(template_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    template = await svc.toggle_template_active(db, template_id)
    return {'success': True, 'data': template.to_dict()}


@router.get('/v1/templates/{template_id}/versions', tags=['模板'])
@router.get('/templates/{template_id}/versions', tags=['模板'], include_in_schema=False)
async def template_versions(template_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    history = await svc.get_version_history(db, template_id)
    return {'success': True, 'data': history}


@router.post('/v1/templates/{template_id}/versions/{version_id}/restore', tags=['模板'])
@router.post(
    '/templates/{template_id}/restore/{version_id}',
    tags=['模板'],
    include_in_schema=False,
)
async def restore_template_version(
    template_id: int,
    version_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    template = await svc.restore_version(db, template_id, version_id)
    return {'success': True, 'data': template.to_dict()}
