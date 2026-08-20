"""不同 OpenAI 兼容 Provider 的采样参数适配。"""


class LLMAdapter:
    """统一描述、校验并过滤生成采样参数。"""

    SAMPLING_PARAM_META = {
        'temperature': (
            '控制输出随机性与创造性；越低越稳定，越高越多样。通常与 top_p 二选一调整。',
            (0, 2), 0.7, 0.1,
        ),
        'top_p': (
            '核采样范围；越小越保守集中，越大越多样。通常与 temperature 二选一调整。',
            (0, 1), 0.9, 0.05,
        ),
        'max_tokens': (
            '单次生成的最大 token 数。达到上限会停止输出，并在前端提供续写入口。',
            (1, 131072), 8192, 512,
        ),
        'frequency_penalty': (
            '对反复出现的 token 施加惩罚，适合减少逐字重复。',
            (-2, 2), 0, 0.1,
        ),
        'presence_penalty': (
            '鼓励引入尚未出现的内容，适合减少内容原地打转。',
            (-2, 2), 0, 0.1,
        ),
    }
    _DEFAULT_SUPPORTED = tuple(SAMPLING_PARAM_META)

    @classmethod
    def describe(cls, provider, provider_config=None):
        """返回前端高级面板需要的参数说明与支持状态。"""
        config = provider_config or {}
        supported = set(config.get('sampling_params') or cls._DEFAULT_SUPPORTED)
        overrides = config.get('sampling_param_overrides') or {}
        parameters = {
            key: {
                'supported': key in supported,
                'description': description,
                'min': low,
                'max': high,
                'default': default,
                'step': step,
            }
            for key, (description, (low, high), default, step) in cls.SAMPLING_PARAM_META.items()
        }
        for key, override in overrides.items():
            if key in parameters:
                parameters[key].update(override)
        return {
            'provider': provider,
            'note': config.get('sampling_note', ''),
            'parameters': parameters,
        }

    @classmethod
    def _validate_value(cls, key, value):
        if key not in cls.SAMPLING_PARAM_META:
            raise ValueError(f'不支持的采样参数：{key}')
        if value is None:
            return
        _description, (low, high), _default, _step = cls.SAMPLING_PARAM_META[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f'{key} 必须是数值')
        if value < low or value > high:
            raise ValueError(f'{key} 必须在 {low} 到 {high} 之间')

    @classmethod
    def normalize_sampling(cls, sampling, provider, provider_config=None):
        """过滤未知、不支持或越界参数，返回 `(有效参数, 被丢弃参数)`。"""
        del provider
        if not sampling:
            return {}, []
        config = provider_config or {}
        supported = set(config.get('sampling_params') or cls._DEFAULT_SUPPORTED)
        filtered = {}
        dropped = []
        for key, value in sampling.items():
            if value is None or key not in cls.SAMPLING_PARAM_META:
                continue
            if key not in supported:
                dropped.append(key)
                continue
            try:
                cls._validate_value(key, value)
                override = (config.get('sampling_param_overrides') or {}).get(key, {})
                low = override.get('min')
                high = override.get('max')
                if low is not None and value < low:
                    raise ValueError
                if high is not None and value > high:
                    raise ValueError
            except ValueError:
                dropped.append(key)
                continue
            filtered[key] = value
        return filtered, dropped
