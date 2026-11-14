"""生成记录路由（5 个端点）。

路径从旧的 ``/api/generation/records*`` 独立出来，成为 ``/api/v1/records*``；
旧路径以别名挂载，前端不受影响。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.exceptions import GenerationError
from backend.dependencies import get_db
from backend.services import record_service as svc

router = APIRouter()

RECORD_NOT_FOUND = {'success': False, 'error': '记录不存在'}


class RecordUpdate(BaseModel):
    """只允许这六个字段，与旧实现的白名单一致。

    ``extra='allow'`` 是刻意的：旧接口收到未知字段会明确回报
    "不允许更新字段: xxx"（400），而不是静默忽略。若用 Pydantic 默认的
    ignore，前端写错字段时会以为更新成功。
    """

    model_config = ConfigDict(extra='allow')

    title: str | None = None
    edited_content: str | None = None
    edit_history: str | None = None
    rating: int | None = None
    pinned: bool | None = None
    notes: str | None = None


@router.get('/v1/records', tags=['生成记录'])
@router.get('/generation/records', tags=['生成记录'], include_in_schema=False)
async def list_records(
    page: int = 1,
    per_page: int = 50,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    result = await svc.get_records(db, page=page, per_page=per_page)
    return {'success': True, 'data': result}


@router.get('/v1/records/{record_id}', tags=['生成记录'])
@router.get('/generation/records/{record_id}', tags=['生成记录'], include_in_schema=False)
async def get_single_record(record_id: int, db: AsyncSession = Depends(get_db)) -> Any:
    record = await svc.get_record(db, record_id)
    if not record:
        return JSONResponse(status_code=404, content=RECORD_NOT_FOUND)
    return {'success': True, 'data': record.to_dict()}


@router.put('/v1/records/{record_id}', tags=['生成记录'])
@router.put('/generation/records/{record_id}', tags=['生成记录'], include_in_schema=False)
async def edit_record(
    record_id: int,
    payload: RecordUpdate,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    changes = payload.model_dump(exclude_none=True)
    unknown = set(changes) - svc.UPDATABLE_FIELDS
    if unknown:
        raise GenerationError(f'不允许更新字段: {", ".join(sorted(unknown))}')
    record = await svc.update_record(db, record_id, **changes)
    return {'success': True, 'data': record.to_dict()}


@router.delete('/v1/records/{record_id}', tags=['生成记录'])
@router.delete('/generation/records/{record_id}', tags=['生成记录'], include_in_schema=False)
async def remove_record(record_id: int, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await svc.delete_record(db, record_id)
    return {'success': True}


@router.delete('/v1/records', tags=['生成记录'])
@router.delete('/generation/records', tags=['生成记录'], include_in_schema=False)
async def remove_all_records(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await svc.delete_all_records(db)
    return {'success': True, 'deleted': True}
