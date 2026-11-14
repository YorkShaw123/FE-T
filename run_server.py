"""PyInstaller 打包入口：拉起 FastAPI 后端（替代旧的 server/app.py）。

桌面端由 Tauri 以 Sidecar 方式启动本程序，端口通过 ``FLORA_PORT`` 传入。

窗口模式（console=False）下没有控制台，任何异常都会静默丢失，
所以这里做了两件事：
1. stdout/stderr 为 None 时接一个空壳，避免日志配置直接炸；
2. 启动异常一律写入 ``<数据目录>/sidecar-error.log``，便于现场排错。
"""

from __future__ import annotations

import io
import os
import sys
import traceback


def _ensure_stdio() -> None:
    if sys.stdout is None:
        sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding='utf-8', errors='replace')
    if sys.stderr is None:
        sys.stderr = io.TextIOWrapper(io.BytesIO(), encoding='utf-8', errors='replace')


def _error_log_path() -> str:
    try:
        from backend.config import get_settings

        return str(get_settings().resolved_data_dir / 'sidecar-error.log')
    except Exception:
        return os.path.join(os.path.expanduser('~'), 'flora-sidecar-error.log')


def _record_failure(exc: BaseException) -> None:
    path = _error_log_path()
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'a', encoding='utf-8') as handle:
            handle.write('=' * 60 + '\n')
            handle.write(traceback.format_exc())
            handle.write(f'\nargv={sys.argv}\n')
            handle.write(f'frozen={getattr(sys, "frozen", False)} meipass={getattr(sys, "_MEIPASS", "")}\n')
            handle.write(f'FLORA_PORT={os.environ.get("FLORA_PORT")}\n')
    except Exception:
        pass


def main() -> None:
    _ensure_stdio()

    try:
        import uvicorn

        from backend.config import get_settings
        from backend.main import app

        settings = get_settings()
        port = int(os.environ.get('FLORA_PORT', settings.port))
        uvicorn.run(
            app,
            host=settings.host,
            port=port,
            log_level=settings.log_level.lower(),
            log_config=None,   # 不接管日志配置，窗口模式下更稳
            access_log=False,
        )
    except BaseException as exc:  # noqa: BLE001 - 冻结环境下必须兜住一切
        _record_failure(exc)
        raise


if __name__ == '__main__':
    main()
