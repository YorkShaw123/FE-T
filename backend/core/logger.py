"""结构化日志。

对照课件 3.3：一条日志 = 一个事件名 + 若干键值对，方便事后按 agent 类型、
会话 id、语料库 id 去筛。调用方式保持课件里的写法::

    logger.info("kb.search_done", corpus_id=1, candidates=12, elapsed_ms=87)

底层仍是标准库 logging，只是把关键字参数拼进同一条消息，不引入额外依赖。
"""

from __future__ import annotations

import logging
import sys
from typing import Any

_CONFIGURED = False
_DEFAULT_FORMAT = '%(asctime)s %(levelname)-7s [%(name)s] %(message)s'


class _KeyValueFormatter(logging.Formatter):
    """把 extra 里的 kv_fields 渲染成 key=value 串。"""

    def format(self, record: logging.LogRecord) -> str:
        base = super().format(record)
        fields = getattr(record, 'kv_fields', None)
        if not fields:
            return base
        rendered = ' '.join(f'{key}={value}' for key, value in fields.items())
        return f'{base}  {rendered}'


def configure_logging(level: str = 'INFO', stream=None) -> None:
    """初始化根日志器（幂等，多次调用只生效一次）。"""
    global _CONFIGURED
    root = logging.getLogger()
    if _CONFIGURED:
        root.setLevel(getattr(logging, level.upper(), logging.INFO))
        return

    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(_KeyValueFormatter(_DEFAULT_FORMAT))
    root.handlers = [handler]
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # 第三方库的噪音压到警告级
    for noisy in ('httpx', 'httpcore', 'urllib3', 'aiosqlite'):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True


class KeyValueLogger:
    """薄封装：支持 ``logger.info("event", key=value)`` 的调用风格。"""

    __slots__ = ('_logger',)

    def __init__(self, name: str) -> None:
        self._logger = logging.getLogger(name)

    def _emit(self, level: int, event: str, fields: dict[str, Any]) -> None:
        if not self._logger.isEnabledFor(level):
            return
        self._logger.log(level, event, extra={'kv_fields': fields})

    def debug(self, event: str, **fields: Any) -> None:
        self._emit(logging.DEBUG, event, fields)

    def info(self, event: str, **fields: Any) -> None:
        self._emit(logging.INFO, event, fields)

    def warning(self, event: str, **fields: Any) -> None:
        self._emit(logging.WARNING, event, fields)

    def error(self, event: str, **fields: Any) -> None:
        self._emit(logging.ERROR, event, fields)

    def exception(self, event: str, **fields: Any) -> None:
        self._emit(logging.ERROR, event, fields)


def get_logger(name: str) -> KeyValueLogger:
    return KeyValueLogger(name)
