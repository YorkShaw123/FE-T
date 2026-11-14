"""总路由聚合。

对照课件 8.6：所有子路由在这里带上前缀与标签聚合，``main.py`` 只挂一个 ``api_router``。
新路由一律挂在 ``/api/v1/*`` 之下；旧 ``/api/*`` 由各子路由以别名装饰器提供。
"""

from __future__ import annotations

from fastapi import APIRouter

from backend.api.v1 import chat, health, modes, records, style, templates, writing

api_router = APIRouter(prefix='/api')
api_router.include_router(health.router)
api_router.include_router(chat.router)
api_router.include_router(templates.router)
api_router.include_router(records.router)
api_router.include_router(style.router)
api_router.include_router(writing.router)
api_router.include_router(modes.router)
