"""健康检查。

两套路径同时可达：``/api/health`` 是迁移前的旧路径，``/api/v1/health`` 是新路径。
双轨过渡期两者都保留，验收后删掉旧装饰器即可。
"""

from __future__ import annotations

from fastapi import APIRouter

from backend import __version__
from backend.config import get_settings
from backend.db import check_connection

router = APIRouter()


@router.get('/v1/health', tags=['系统'])
@router.get('/health', tags=['系统'], include_in_schema=False)
async def health() -> dict:
    settings = get_settings()
    db_ok = await check_connection()
    return {
        'success': True,
        'data': {
            'status': 'ok' if db_ok else 'degraded',
            'version': __version__,
            'env': settings.app_env,
            'database': 'ok' if db_ok else 'unavailable',
            'data_dir': str(settings.resolved_data_dir),
        },
    }
