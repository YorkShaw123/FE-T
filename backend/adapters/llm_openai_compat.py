"""OpenAI 兼容协议适配。

对照课件 3.4：所有 Agent 通过 ``core/llm_factory`` 拿模型，模型工厂再回来用这里的
构造函数。Provider 的差异只允许出现在这个文件里：

- 每家提供方的 ``base_url`` 与思考协议（``thinking_protocol``）来自
  ``backend/provider_catalog.py``，与迁移前完全一致；
- 采样参数的支持范围与越界过滤沿用旧 ``LLMAdapter`` 的规则；
- DeepSeek 思考模式下主动剔除 temperature / top_p 等无效参数，避免界面产生错误预期。
"""

from __future__ import annotations

from typing import Any

from langchain_openai import ChatOpenAI

from backend.config import LLM_PROVIDERS

SAMPLING_PARAM_META: dict[str, tuple[str, tuple[float, float]]] = {
    'temperature': ('控制输出随机性与创造性', (0, 2)),
    'top_p': ('核采样范围', (0, 1)),
    'max_tokens': ('单次生成的最大 token 数', (1, 131072)),
    'frequency_penalty': ('对反复出现的 token 施加惩罚', (-2, 2)),
    'presence_penalty': ('鼓励引入尚未出现的内容', (-2, 2)),
}

_DEFAULT_SUPPORTED = tuple(SAMPLING_PARAM_META)

# 这些参数在 ChatOpenAI 构造函数里是直接字段；其余键（未知参数）一律丢弃。
_CHAT_MODEL_FIELDS = {
    'temperature',
    'top_p',
    'max_tokens',
    'frequency_penalty',
    'presence_penalty',
}


def normalize_sampling(
    sampling: dict[str, Any] | None,
    provider: str,
) -> tuple[dict[str, Any], list[str]]:
    """过滤未知、不支持或越界的采样参数，返回 ``(有效参数, 被丢弃的键)``。"""
    if not sampling:
        return {}, []

    config = LLM_PROVIDERS.get(provider, {})
    supported = set(config.get('sampling_params') or _DEFAULT_SUPPORTED)
    overrides = config.get('sampling_param_overrides') or {}

    filtered: dict[str, Any] = {}
    dropped: list[str] = []
    for key, value in sampling.items():
        if value is None or key not in SAMPLING_PARAM_META:
            continue
        if key not in supported:
            dropped.append(key)
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            dropped.append(key)
            continue

        low, high = SAMPLING_PARAM_META[key][1]
        override = overrides.get(key, {})
        low = override.get('min', low)
        high = override.get('max', high)
        if value < low or value > high:
            dropped.append(key)
            continue

        filtered[key] = value
    return filtered, dropped


def _model_config(provider: str, model: str) -> dict[str, Any]:
    for item in LLM_PROVIDERS.get(provider, {}).get('models', []):
        if item.get('id') == model:
            return item
    return {}


def thinking_kwargs(
    provider: str,
    model: str,
    thinking_enabled: bool,
    reasoning_effort: str,
) -> dict[str, Any]:
    """按提供方的思考协议生成请求侧参数（与旧 ``configure_generation_params`` 等价）。"""
    provider_config = LLM_PROVIDERS.get(provider, {})
    model_config = _model_config(provider, model)
    thinking_mode = model_config.get('thinking_mode', 'disabled')
    protocol = provider_config.get('thinking_protocol', 'none')

    if protocol == 'enable_thinking':
        if thinking_mode != 'switchable':
            return {}
        extra: dict[str, Any] = {'enable_thinking': bool(thinking_enabled)}
        if thinking_enabled:
            extra['thinking_budget'] = 16384 if reasoning_effort == 'max' else 8192
        return {'extra_body': extra}

    if protocol == 'gemini_effort':
        if thinking_enabled:
            return {'reasoning_effort': 'high' if reasoning_effort == 'max' else reasoning_effort}
        if thinking_mode == 'switchable':
            return {'reasoning_effort': 'none'}
        return {'reasoning_effort': 'low'}

    if protocol in {'thinking_object', 'thinking_object_with_effort'}:
        enabled = bool(thinking_enabled or thinking_mode == 'always')
        kwargs: dict[str, Any] = {
            'extra_body': {'thinking': {'type': 'enabled' if enabled else 'disabled'}},
        }
        if enabled and protocol == 'thinking_object_with_effort':
            kwargs['reasoning_effort'] = reasoning_effort
        return kwargs

    return {}


def build_chat_model(
    provider: str,
    model: str,
    *,
    api_key: str,
    temperature: float = 0,
    streaming: bool = False,
    max_tokens: int | None = None,
    thinking_enabled: bool = False,
    reasoning_effort: str = 'high',
    sampling: dict[str, Any] | None = None,
) -> tuple[ChatOpenAI, list[str]]:
    """构造一个 ChatOpenAI 客户端，返回 ``(模型, 被丢弃的采样参数)``。"""
    provider_config = LLM_PROVIDERS.get(provider)
    if provider_config is None:
        raise ValueError(f'不支持的模型提供商: {provider}')

    base_url = provider_config['base_url']
    filtered, dropped = normalize_sampling(sampling, provider)
    thinking = thinking_kwargs(provider, model, thinking_enabled, reasoning_effort)

    # DeepSeek 明确说明思考模式不支持这些采样参数，协议边界处直接剔除
    model_config = _model_config(provider, model)
    thinking_active = thinking_enabled or model_config.get('thinking_mode') == 'always'
    if provider == 'deepseek' and thinking_active:
        for key in ('temperature', 'top_p', 'frequency_penalty', 'presence_penalty'):
            filtered.pop(key, None)
            if key in dropped:
                dropped.remove(key)

    kwargs: dict[str, Any] = {
        'model': model,
        'api_key': api_key,
        'base_url': base_url,
        'streaming': streaming,
        'max_retries': 0,  # 重试统一由 core/retry.py 管
    }
    if not thinking_active:
        kwargs['temperature'] = filtered.pop('temperature', temperature)
    for key, value in filtered.items():
        if key == 'max_tokens':
            continue
        kwargs[key] = value

    limit = max_tokens if max_tokens else filtered.get('max_tokens')
    if limit:
        kwargs['max_tokens'] = int(limit)

    for key, value in thinking.items():
        kwargs[key] = value

    return ChatOpenAI(**kwargs), dropped


def describe_provider(provider: str) -> dict[str, Any]:
    """前端高级面板需要的参数说明（与旧 ``LLMAdapter.describe`` 输出一致）。"""
    config = LLM_PROVIDERS.get(provider, {})
    supported = set(config.get('sampling_params') or _DEFAULT_SUPPORTED)
    overrides = config.get('sampling_param_overrides') or {}
    parameters: dict[str, Any] = {}
    for key, (description, (low, high)) in SAMPLING_PARAM_META.items():
        parameters[key] = {
            'supported': key in supported,
            'description': description,
            'min': low,
            'max': high,
        }
    for key, override in overrides.items():
        if key in parameters:
            parameters[key].update(override)
    return {
        'provider': provider,
        'note': config.get('sampling_note', ''),
        'parameters': parameters,
    }
