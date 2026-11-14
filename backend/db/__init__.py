"""数据层：异步引擎与会话。

对照课件 3.2/3.3：SQLAlchemy 2.0 异步写法，连接串由 ``Settings.database_url``
统一给出（桌面端是 aiosqlite，云端版换成 asyncpg 只改一行）。

迁移期旧代码仍走 Flask-SQLAlchemy 的同步 Session，两套引擎指向同一个
``flora.db`` 文件；SQLite 的 WAL 模式允许一读一写并存，但为了避免锁冲突，
新代码在写入时与旧代码不并发（旧进程在桌面端只作为 Sidecar 存在，验收后退役）。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from backend.config import get_settings
from backend.core.logger import get_logger

logger = get_logger(__name__)

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """惰性创建全局引擎（进程内单例）。"""
    global _engine
    if _engine is None:
        settings = get_settings()
        settings.resolved_data_dir.mkdir(parents=True, exist_ok=True)
        _engine = create_async_engine(
            settings.database_url,
            echo=False,
            future=True,
            connect_args={'timeout': 30},
        )
        logger.info('db.engine_created', url=settings.database_url)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            expire_on_commit=False,
            class_=AsyncSession,
        )
    return _session_factory


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession]:
    """事务边界：正常提交、异常回滚、无论如何关闭。"""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def check_connection() -> bool:
    """健康检查用：真的开一次连接跑 SELECT 1。"""
    try:
        async with get_engine().connect() as conn:
            await conn.execute(text('SELECT 1'))
        return True
    except Exception as exc:  # noqa: BLE001 - 健康检查需要吞掉所有异常
        logger.warning('db.healthcheck_failed', error=str(exc))
        return False


async def dispose_engine() -> None:
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info('db.engine_disposed')
