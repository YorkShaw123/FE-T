"""生成记录的读写（异步版）。

与旧 ``server/services/generation/records.py`` 语义一致：
列表按「置顶优先、时间倒序」排序并分页；更新只允许六个字段；
删除与清空是物理删除。
"""

from __future__ import annotations

import math
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.exceptions import GenerationError
from backend.db.models import GenerationRecord

UPDATABLE_FIELDS = {'title', 'edited_content', 'edit_history', 'rating', 'pinned', 'notes'}


async def get_record(session: AsyncSession, record_id: int) -> GenerationRecord | None:
    return await session.get(GenerationRecord, record_id)


async def get_records(
    session: AsyncSession,
    page: int = 1,
    per_page: int = 50,
) -> dict[str, Any]:
    page = max(page, 1)
    per_page = min(max(per_page, 1), 100)

    total = (await session.execute(
        select(func.count()).select_from(GenerationRecord)
    )).scalar_one()

    stmt = (
        select(GenerationRecord)
        .order_by(GenerationRecord.pinned.desc(), GenerationRecord.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    items = list((await session.execute(stmt)).scalars().all())

    return {
        'items': [record.to_brief_dict() for record in items],
        'total': total,
        'pages': math.ceil(total / per_page) if total else 0,
        'current_page': page,
    }


async def update_record(
    session: AsyncSession,
    record_id: int,
    **kwargs: Any,
) -> GenerationRecord:
    record = await get_record(session, record_id)
    if not record:
        raise GenerationError(f'记录不存在: {record_id}')

    unknown = set(kwargs) - UPDATABLE_FIELDS
    if unknown:
        raise GenerationError(f'不允许更新字段: {", ".join(sorted(unknown))}')

    for key, value in kwargs.items():
        setattr(record, key, value)
    await session.flush()
    return record


async def delete_record(session: AsyncSession, record_id: int) -> None:
    record = await get_record(session, record_id)
    if not record:
        raise GenerationError(f'记录不存在: {record_id}')
    await session.delete(record)
    await session.flush()


async def delete_all_records(session: AsyncSession) -> None:
    await session.execute(delete(GenerationRecord))
    await session.flush()
