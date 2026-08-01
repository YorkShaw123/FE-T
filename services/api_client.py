"""
大语言模型 API 客户端
统一封装 DeepSeek、OpenAI、硅基流动 Kimi、爱化身等平台的调用逻辑
支持思考模式（thinking mode）和 reasoning_effort 控制
"""
from openai import OpenAI
from config import Config


class LLMClientError(Exception):
    """LLM API 调用异常"""
    pass


class LLMClient:
    """统一的大语言模型 API 客户端"""

    def __init__(self, provider='deepseek', api_key=None, base_url=None):
        """
        初始化客户端
        :param provider: 提供商名称（deepseek / openai / siliconflow / aihuashen）
        :param api_key: API密钥
        :param base_url: 自定义 base_url
        """
        self.provider = provider
        provider_config = Config.LLM_PROVIDERS.get(provider, {})

        if base_url:
            self.base_url = base_url
        else:
            self.base_url = provider_config.get('base_url', 'https://api.deepseek.com')

        if not api_key or not api_key.strip():
            raise LLMClientError('API密钥不能为空')

        # 输入框既兼容纯 Token，也兼容用户从文档中复制的 ``Bearer <TOKEN>``。
        # OpenAI SDK 的 api_key 会自动生成 Authorization: Bearer 请求头；
        # 爱化身接口额外显式设置该请求头，确保兼容其网关鉴权要求。
        normalized_key = api_key.strip()
        if normalized_key.lower().startswith('bearer '):
            normalized_key = normalized_key[7:].strip()
        if not normalized_key:
            raise LLMClientError('API密钥不能为空')

        client_options = dict(
            api_key=normalized_key,
            base_url=self.base_url,
            timeout=Config.LLM_TIMEOUT_SECONDS,
            max_retries=Config.LLM_MAX_RETRIES,
        )
        if self.provider == 'aihuashen':
            client_options['default_headers'] = {
                'Authorization': f'Bearer {normalized_key}',
            }
        self.client = OpenAI(**client_options)

    @staticmethod
    def validate_model(provider, model_id):
        """验证模型是否在配置中支持"""
        provider_config = Config.LLM_PROVIDERS.get(provider, {})
        models = provider_config.get('models', [])
        model_ids = [m['id'] for m in models]
        return model_id in model_ids

    def configure_generation_params(
        self,
        params,
        thinking_enabled=False,
        reasoning_effort='high',
    ):
        """根据不同提供商补充兼容的采样与思考参数。"""
        configured = dict(params)

        if self.provider == 'aihuashen':
            # 爱化身是标准 OpenAI Chat Completions 兼容端点，当前模型不接收
            # reasoning_effort、thinking 或 enable_thinking 等厂商扩展字段。
            configured.pop('reasoning_effort', None)
            configured.pop('extra_body', None)
            configured['temperature'] = 1
            configured['top_p'] = 1
            return configured

        if self.provider == 'siliconflow':
            model_config = next(
                (
                    item for item in Config.LLM_PROVIDERS['siliconflow']['models']
                    if item['id'] == configured.get('model')
                ),
                {},
            )
            thinking_mode = model_config.get('thinking_mode', 'disabled')

            # 硅基流动使用 enable_thinking / thinking_budget，
            # 并通过 extra_body 透传 OpenAI SDK 未声明的请求字段。
            if thinking_mode == 'switchable':
                configured['extra_body'] = {
                    'enable_thinking': bool(thinking_enabled),
                }
                if thinking_enabled:
                    configured['extra_body']['thinking_budget'] = (
                        16384 if reasoning_effort == 'max' else 8192
                    )

            # 固定思考模型无需传开关；指令模型也不接收思考参数。
            if not thinking_enabled and thinking_mode != 'always':
                configured['temperature'] = 0.7
                configured['top_p'] = 0.9
            return configured

        if thinking_enabled:
            configured['reasoning_effort'] = reasoning_effort
            configured['extra_body'] = {'thinking': {'type': 'enabled'}}
        else:
            configured['temperature'] = 0.7
            configured['top_p'] = 0.9
        return configured

    def generate(
        self,
        model,
        messages,
        stream=False,
        thinking_enabled=False,
        reasoning_effort='high',
        max_tokens=None,
    ):
        """
        调用 LLM 生成内容
        :param model: 模型ID
        :param messages: 消息列表
        :param stream: 是否流式输出
        :param thinking_enabled: 是否启用思考模式
        :param reasoning_effort: 思考强度 (high / max)
        :param max_tokens: 最大输出 token 数
        :return: dict {
            'content': str,
            'reasoning_content': str (if thinking enabled),
            'usage': dict
        }
        """
        if not self.validate_model(self.provider, model):
            raise LLMClientError(f'当前提供商不支持模型：{model}')
        if reasoning_effort not in {'high', 'max'}:
            raise LLMClientError('思考强度仅支持 high 或 max')

        try:
            # 构建通用参数
            params = {
                'model': model,
                'messages': messages,
                'stream': stream,
                'max_tokens': max_tokens or Config.DEFAULT_MAX_TOKENS,
            }

            params = self.configure_generation_params(
                params,
                thinking_enabled=thinking_enabled,
                reasoning_effort=reasoning_effort,
            )

            if stream:
                return self._generate_stream(params)
            else:
                return self._generate_sync(params)

        except LLMClientError:
            raise
        except Exception as e:
            raise LLMClientError(f'API调用失败: {str(e)}') from e

    def _generate_sync(self, params):
        """同步（非流式）生成"""
        response = self.client.chat.completions.create(**params)

        result = {
            'content': response.choices[0].message.content or '',
            'reasoning_content': '',
            'usage': {
                'prompt_tokens': response.usage.prompt_tokens if response.usage else 0,
                'completion_tokens': response.usage.completion_tokens if response.usage else 0,
                'total_tokens': response.usage.total_tokens if response.usage else 0,
            },
        }

        # 提取思维链内容
        if hasattr(response.choices[0].message, 'reasoning_content'):
            result['reasoning_content'] = response.choices[0].message.reasoning_content or ''

        return result

    def _generate_stream(self, params):
        """流式生成，返回生成器"""
        response = self.client.chat.completions.create(**params)

        for chunk in response:
            data = {
                'content': '',
                'reasoning_content': '',
                'finish_reason': None,
            }

            if chunk.choices and len(chunk.choices) > 0:
                delta = chunk.choices[0].delta
                if delta.content:
                    data['content'] = delta.content
                if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                    data['reasoning_content'] = delta.reasoning_content
                if chunk.choices[0].finish_reason:
                    data['finish_reason'] = chunk.choices[0].finish_reason

            yield data

    def generate_stream_aggregated(self, params):
        """流式生成并聚合结果"""
        response = self.client.chat.completions.create(**params)

        full_reasoning = ''
        full_content = ''

        try:
            for chunk in response:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if delta.content:
                        piece = delta.content
                        full_content += piece
                        yield {'type': 'content', 'data': piece}
                    if hasattr(delta, 'reasoning_content') and delta.reasoning_content:
                        piece = delta.reasoning_content
                        full_reasoning += piece
                        yield {'type': 'reasoning', 'data': piece}

            yield {
                'type': 'done',
                'result': {
                    'content': full_content,
                    'reasoning_content': full_reasoning,
                },
            }
        finally:
            close_response = getattr(response, 'close', None)
            if callable(close_response):
                close_response()
