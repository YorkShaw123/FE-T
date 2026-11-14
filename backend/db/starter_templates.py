"""入门示例模板的写入逻辑（异步版）。

与旧 ``server/database/starter_templates.py`` 行为一致：
首次初始化（``starter_templates_seeded_v1`` 未写入时）自动补一次；
用户也可以在界面上主动触发补齐，已有同名同类模板不会重复创建。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db.models import ProjectSetting, PromptTemplate
from backend.db.starter_templates_data import STARTER_TEMPLATES

STARTER_TEMPLATES_SETTING_KEY = 'starter_templates_seeded_v1'


async def _add_missing(session: AsyncSession) -> list[PromptTemplate]:
    created: list[PromptTemplate] = []
    for data in STARTER_TEMPLATES:
        existing = (await session.execute(
            select(PromptTemplate.id).where(
                PromptTemplate.name == data['name'],
                PromptTemplate.category == data['category'],
            )
        )).first()
        if existing is not None:
            continue
        template = PromptTemplate(
            **data,
            is_active=True,
            is_sample=False,
            style_strength='light',
            version=1,
        )
        session.add(template)
        created.append(template)
    if created:
        await session.flush()
    return created


async def ensure_starter_templates(session: AsyncSession) -> bool:
    """仅首次初始化时写入示例模板。"""
    seeded = (await session.execute(
        select(ProjectSetting).where(ProjectSetting.key == STARTER_TEMPLATES_SETTING_KEY)
    )).scalar_one_or_none()
    if seeded is not None:
        return False

    created = await _add_missing(session)
    session.add(ProjectSetting(key=STARTER_TEMPLATES_SETTING_KEY, value='1'))
    await session.flush()
    return bool(created)


async def create_missing_starter_templates(session: AsyncSession) -> list[PromptTemplate]:
    """用户主动触发：补齐缺失的示例模板。"""
    return await _add_missing(session)
