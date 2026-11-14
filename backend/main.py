"""FastAPI 应用入口。

对照课件 3.1 与 8.6：
- ``create_app()`` 只做装配，不承载业务；
- ``lifespan`` 负责日志、数据目录、数据库连通性；
- 统一异常处理器把任何异常翻成 ``{"success": false, "error": "中文原因"}``，
  与迁移前的 Flask 响应形状保持一致，前端无需改动。

桌面端由 Tauri 以 Sidecar 方式拉起（``uvicorn backend.main:app``），
端口来自 ``FLORA_PORT`` 环境变量。
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend import __version__
from backend.api.router import api_router
from backend.config import get_settings
from backend.core.exceptions import AppError, error_payload, to_user_message
from backend.core.logger import configure_logging, get_logger
from backend.db import check_connection, dispose_engine, session_scope
from backend.db.migrations import run_migrations
from backend.db.starter_templates import ensure_starter_templates

logger = get_logger(__name__)

SECURITY_HEADERS = {
    'X-Content-Type-Options': 'nosniff',
    'X-Frame-Options': 'DENY',
    'Referrer-Policy': 'no-referrer',
}

HTTP_ERROR_MESSAGES = {
    400: '请求参数有误，请检查后重试。',
    401: '登录状态已失效，请重新打开应用。',
    403: '没有权限执行该操作。',
    404: '请求的内容不存在。',
    405: '该地址不支持此请求方式。',
    413: '上传内容超过大小限制。',
    429: '请求过于频繁，请稍后再试。',
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    settings.resolved_data_dir.mkdir(parents=True, exist_ok=True)
    settings.resolved_models_dir.mkdir(parents=True, exist_ok=True)

    # 启动时执行幂等迁移（与旧 Flask 版本的行为一致）
    migration_summary = await run_migrations()

    # 首次初始化时写入入门示例模板；已有用户不会重复写入
    async with session_scope() as session:
        seeded = await ensure_starter_templates(session)

    db_ok = await check_connection()
    logger.info(
        'app.startup',
        version=__version__,
        env=settings.app_env,
        data_dir=str(settings.resolved_data_dir),
        database='ok' if db_ok else 'unavailable',
        starter_seeded=seeded,
        **migration_summary,
    )
    try:
        yield
    finally:
        await dispose_engine()
        logger.info('app.shutdown')


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title=f'{settings.app_name} API',
        version=__version__,
        lifespan=lifespan,
        docs_url='/api/docs',
        openapi_url='/api/openapi.json',
    )

    # ── 安全响应头（与旧 Flask 版本保持一致）──────────────
    @app.middleware('http')
    async def add_security_headers(request: Request, call_next):
        response = await call_next(request)
        for key, value in SECURITY_HEADERS.items():
            response.headers.setdefault(key, value)
        return response

    # ── 统一异常处理：形状与迁移前一致 ─────────────────────
    @app.exception_handler(StarletteHTTPException)
    async def handle_http_error(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        # 404/405 之类默认返回 {"detail": ...}，这里统一成 {"success": false, "error": ...}
        message = HTTP_ERROR_MESSAGES.get(exc.status_code, '请求无法处理，请稍后重试。')
        logger.warning('request.http_error', path=request.url.path, status=exc.status_code)
        return JSONResponse(status_code=exc.status_code, content={'success': False, 'error': message})

    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        logger.warning(exc.event, path=request.url.path, error=exc.message)
        return JSONResponse(status_code=exc.status_code, content=error_payload(exc))

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # 旧接口用的是 400 + 中文说明；FastAPI 默认 422，这里压回来
        first = exc.errors()[0] if exc.errors() else {}
        field = '.'.join(str(part) for part in first.get('loc', [])) or '请求体'
        logger.warning('request.validation_failed', path=request.url.path, field=field)
        return JSONResponse(
            status_code=400,
            content={'success': False, 'error': f'{field} 参数不合法，请检查后重试。'},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        logger.exception('request.unhandled', path=request.url.path, error=str(exc))
        return JSONResponse(
            status_code=500,
            content={'success': False, 'error': to_user_message(exc)},
        )

    # ── 路由 ────────────────────────────────────────────
    app.include_router(api_router)

    # ── 静态资源与首页（与旧版共用同一套前端文件）──────────
    if settings.static_dir.is_dir():
        app.mount('/static', StaticFiles(directory=str(settings.static_dir)), name='static')

    @app.get('/', include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(settings.templates_dir / 'index.html')

    return app


app = create_app()


def main() -> None:
    """本机开发入口：``python -m backend.main``。"""
    import uvicorn

    settings = get_settings()
    port = int(os.environ.get('FLORA_PORT', settings.port))
    uvicorn.run(app, host=settings.host, port=port, log_level=settings.log_level.lower())


if __name__ == '__main__':
    main()
