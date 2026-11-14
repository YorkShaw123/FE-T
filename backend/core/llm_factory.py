"""模型工厂（唯一入口）。

对照课件 3.4：所有 Agent 必须通过这里拿模型，不允许直接 new 一个 ChatOpenAI。

与课件的差别只有一处，而且是产品需要：Flora 允许用户**按次选择**服务商与模型，
所以 ``get_llm`` 支持显式覆盖；不传时才回落到该 Agent 类型的默认路由。
缓存键包含全部影响模型行为的参数（含 API Key 指纹），避免把上一个用户的
Key 复用给下一次请求。
"""

from __future__ import annotations

import hashlib
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.runnables import Runnable
from pydantic import BaseModel

from backend.adapters.llm_openai_compat import build_chat_model
from backend.config import LLM_PROVIDERS
from backend.core.logger import get_logger

logger = get_logger(__name__)

# Agent 类型 → 默认 (provider, model)。用户不指定时使用。
_AGENT_DEFAULT_ROUTE: dict[str, tuple[str, str]] = {
    'writing': ('deepseek', 'deepseek-v4-pro'),
    'style_qa': ('deepseek', 'deepseek-v4-flash'),
    'consistency': ('deepseek', 'deepseek-v4-pro'),
    'intent': ('deepseek', 'deepseek-v4-flash'),
    'summarize': ('deepseek', 'deepseek-v4-flash'),
    'style_card': ('deepseek', 'deepseek-v4-flash'),
    'style_excerpt': ('deepseek', 'deepseek-v4-flash'),
}


def _key_fingerprint(api_key: str) -> str:
    return hashlib.sha256((api_key or '').encode('utf-8')).hexdigest()[:12]


class LLMFactory:
    """按 Agent 类型取模型，带实例缓存。"""

    _instances: dict[str, BaseChatModel] = {}

    @classmethod
    def resolve_route(
        cls,
        agent_type: str,
        provider: str | None = None,
        model: str | None = None,
    ) -> tuple[str, str]:
        default_provider, default_model = _AGENT_DEFAULT_ROUTE.get(
            agent_type, ('deepseek', 'deepseek-v4-pro')
        )
        resolved_provider = provider or default_provider
        if resolved_provider not in LLM_PROVIDERS:
            raise ValueError(f'不支持的模型提供商: {resolved_provider}')

        resolved_model = model or (
            default_model if resolved_provider == default_provider else None
        )
        if not resolved_model:
            models = LLM_PROVIDERS[resolved_provider].get('models') or []
            if not models:
                raise ValueError(f'提供方 {resolved_provider} 没有可用模型')
            resolved_model = models[0]['id']

        available = {item['id'] for item in LLM_PROVIDERS[resolved_provider].get('models', [])}
        if available and resolved_model not in available:
            raise ValueError(f'模型 {resolved_model} 不属于提供方 {resolved_provider}')
        return resolved_provider, resolved_model

    @classmethod
    def get_llm(
        cls,
        agent_type: str,
        *,
        api_key: str,
        provider: str | None = None,
        model: str | None = None,
        temperature: float = 0,
        streaming: bool = False,
        max_tokens: int | None = None,
        thinking_enabled: bool = False,
        reasoning_effort: str = 'high',
        sampling: dict[str, Any] | None = None,
    ) -> tuple[BaseChatModel, list[str]]:
        """返回 ``(模型实例, 被丢弃的采样参数)``。"""
        if not api_key:
            raise ValueError('缺少 API Key')

        resolved_provider, resolved_model = cls.resolve_route(agent_type, provider, model)
        cache_key = '|'.join(
            [
                resolved_provider,
                resolved_model,
                str(temperature),
                str(streaming),
                str(max_tokens),
                str(thinking_enabled),
                reasoning_effort,
                repr(sorted((sampling or {}).items())),
                _key_fingerprint(api_key),
            ]
        )
        if cache_key in cls._instances:
            instance, dropped = cls._instances[cache_key]
            return instance, list(dropped)

        instance, dropped = build_chat_model(
            resolved_provider,
            resolved_model,
            api_key=api_key,
            temperature=temperature,
            streaming=streaming,
            max_tokens=max_tokens,
            thinking_enabled=thinking_enabled,
            reasoning_effort=reasoning_effort,
            sampling=sampling,
        )
        cls._instances[cache_key] = (instance, dropped)
        logger.info(
            'llm_factory.model_ready',
            agent_type=agent_type,
            provider=resolved_provider,
            model=resolved_model,
            streaming=streaming,
            thinking=thinking_enabled,
            dropped=','.join(dropped),
        )
        return instance, list(dropped)

    @classmethod
    def get_structured_llm(
        cls,
        agent_type: str,
        output_schema: type[BaseModel],
        **kwargs: Any,
    ) -> Runnable:
        """绑定结构化输出（DeepSeek 需要 function_calling 方式）。"""
        llm, _dropped = cls.get_llm(agent_type, **kwargs)
        return llm.with_structured_output(output_schema, method='function_calling')

    @classmethod
    def clear_cache(cls) -> None:
        cls._instances.clear()
        logger.info('llm_factory.cache_cleared')


def get_llm(agent_type: str, **kwargs: Any) -> tuple[BaseChatModel, list[str]]:
    return LLMFactory.get_llm(agent_type, **kwargs)


def get_structured_llm(
    agent_type: str,
    output_schema: type[BaseModel],
    **kwargs: Any,
) -> Runnable:
    return LLMFactory.get_structured_llm(agent_type, output_schema, **kwargs)
