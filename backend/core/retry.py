"""三层兜底：自动重试 → Agent 级降级 → 系统级兜底。

对照课件 3.5，规则一字不改：

1. 可重试异常（模型服务、网络、超时）自动重试两次，间隔 1s / 3s；
2. 三次都失败后按 Agent 类型降级，尽量保住核心结果；
3. 连降级都失败，返回一句人话，保证调用方永远拿得到响应。

与课件的一处差异：单次超时默认取 ``FLORA_LLM_TIMEOUT_SECONDS``（180 秒）而不是
课件的 30 秒。写作场景一次生成五分钟很正常，30 秒会把正常请求当失败重试三次。
"""

from __future__ import annotations

import asyncio
from functools import wraps
from typing import Any, Callable

from backend.config import get_settings
from backend.core.exceptions import (
    NON_RETRYABLE_ERRORS,
    RETRYABLE_ERRORS,
    AuthenticationError,
    InvalidInputError,
    LLMAPIError,
)
from backend.core.logger import get_logger

logger = get_logger(__name__)

MAX_RETRIES = 2
RETRY_DELAYS = (1.0, 3.0)


def _default_timeout() -> float:
    return float(get_settings().llm_timeout_seconds)


class AgentFallbackHandler:
    """第二层：按 Agent 类型给"退而求其次"的结果。"""

    @classmethod
    async def handle(cls, agent_type: str, original_error: Exception) -> Any:
        handler = {
            'writing': cls._writing_fallback,
            'style_qa': cls._style_qa_fallback,
            'consistency': cls._consistency_fallback,
        }.get(agent_type)
        if handler is None:
            raise original_error
        return await handler(original_error)

    @staticmethod
    async def _writing_fallback(error: Exception) -> dict[str, Any]:
        logger.info('fallback.writing_degraded', error=str(error))
        return {
            'fallback_used': True,
            'system_fallback': False,
            'final_content': '',
            'content': '本次生成未能完成，模型服务暂时不可用。已保留你在界面上的设置，稍后可直接重试。',
            'error_msg': str(error),
        }

    @staticmethod
    async def _style_qa_fallback(error: Exception) -> dict[str, Any]:
        logger.info('fallback.style_qa_degraded', error=str(error))
        return {
            'fallback_used': True,
            'system_fallback': False,
            'answer': '参考检索暂时不可用，可以先按自己的判断继续写，稍后再试一次风格诊断。',
            'content': '参考检索暂时不可用，可以先按自己的判断继续写，稍后再试一次风格诊断。',
            'error_msg': str(error),
        }

    @staticmethod
    async def _consistency_fallback(error: Exception) -> dict[str, Any]:
        logger.info('fallback.consistency_degraded', error=str(error))
        return {
            'fallback_used': True,
            'system_fallback': False,
            'report': '',
            'content': '一致性检查未能完成，正文已保存。稍后可单独再跑一次审查。',
            'error_msg': str(error),
        }


def _system_fallback_response(agent_type: str, error: Exception | None) -> dict[str, Any]:
    """第三层：所有路径都失败时的保底响应，保证接口一定有人话返回。"""
    logger.error(
        'fallback.system_level',
        agent_type=agent_type,
        error=str(error) if error else '',
    )
    messages = {
        'writing': '非常抱歉，写作服务暂时不可用。你已有的内容都已保存，请稍后重试。',
        'style_qa': '非常抱歉，风格问答暂时不可用，请稍后再试。',
        'consistency': '非常抱歉，一致性审查暂时不可用，请稍后再试。',
    }
    content = messages.get(agent_type, '服务暂时不可用，请稍后再试。')
    return {
        'fallback_used': True,
        'system_fallback': True,
        'content': content,
        'final_content': '',
        'error_msg': str(error) if error else '',
    }


def with_retry(
    agent_type: str = '',
    *,
    timeout: float | None = None,
    max_retries: int | None = None,
    delays: tuple[float, ...] | None = None,
) -> Callable:
    """三层兜底装饰器工厂。重复装饰不同函数时各自独立，互不影响。"""
    retries = MAX_RETRIES if max_retries is None else max_retries
    waits = RETRY_DELAYS if delays is None else delays

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_error: Exception | None = None

            for attempt in range(retries + 1):
                try:
                    return await asyncio.wait_for(
                        func(*args, **kwargs),
                        timeout=timeout if timeout is not None else _default_timeout(),
                    )
                except NON_RETRYABLE_ERRORS:
                    logger.warning('retry.non_retryable', agent_type=agent_type)
                    raise
                except RETRYABLE_ERRORS as exc:
                    last_error = exc
                    if attempt < retries:
                        delay = waits[attempt] if attempt < len(waits) else waits[-1]
                        logger.warning(
                            'retry.attempt_failed',
                            agent_type=agent_type,
                            attempt=attempt + 1,
                            delay=delay,
                            error=str(exc),
                        )
                        await asyncio.sleep(delay)
                    else:
                        logger.error(
                            'retry.all_attempts_failed',
                            agent_type=agent_type,
                            error=str(exc),
                        )
                except Exception as exc:  # 未分类异常同样走兜底，不向上抛
                    last_error = exc
                    logger.error(
                        'retry.unexpected_error',
                        agent_type=agent_type,
                        error=str(exc),
                        exc_info=True,
                    )
                    break

            try:
                degraded = await AgentFallbackHandler.handle(agent_type, last_error or LLMAPIError(''))
                logger.info('retry.fallback_succeeded', agent_type=agent_type)
                return degraded
            except Exception as fallback_error:
                logger.error(
                    'retry.fallback_failed',
                    agent_type=agent_type,
                    error=str(fallback_error),
                )

            return _system_fallback_response(agent_type, last_error)

        return wrapper

    return decorator


__all__ = [
    'MAX_RETRIES',
    'RETRY_DELAYS',
    'AgentFallbackHandler',
    'with_retry',
    'InvalidInputError',
    'AuthenticationError',
]
