"""FastAPI 依赖注入：数据库会话与本地用户。

对照课件 3.6：``get_db`` 负责会话生命周期，``get_current_user`` 负责身份。
与课件的差别只有一处——桌面端没有登录页，本地会话令牌由启动时静默签发，
``tenant_id`` 固定为 ``local_default``，角色固定 ``owner``。
"""

from __future__ import annotations

from typing import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.db import get_session_factory

LOCAL_USER_ID = 'local'
LOCAL_TENANT_ID = 'local_default'


async def get_db() -> AsyncIterator[AsyncSession]:
    """请求级会话：正常提交、异常回滚、结束时关闭。"""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_current_user() -> dict[str, str]:
    """本地用户。桌面端只有一个人用，不存在多租户切换。"""
    return {
        'user_id': LOCAL_USER_ID,
        'role': 'owner',
        'tenant_id': LOCAL_TENANT_ID,
    }


CurrentUser = Depends(get_current_user)
DbSession = Depends(get_db)
