"""
大语言模型 API 客户端（轻量版）
统一封装 DeepSeek、OpenAI、硅基流动 Kimi、爱化身等平台的调用逻辑
支持思考模式（thinking mode）和 reasoning_effort 控制

实现说明：
- 仅依赖 Python 标准库 urllib，替代 openai SDK（体积约 15~20MB，含 pydantic/httpx/jiter
  等依赖），从而显著减小 PyInstaller 打包体积并加快桌面端启动。
- 协议兼容 OpenAI Chat Completions 与 Embeddings 端点：POST {base_url}/chat/completions、
  {base_url}/embeddings；流式响应按 SSE（data: 行）解析。
"""
import json
import time
import urllib.error
import urllib.request

from config import Config
from services.errors import friendly_error_message


class LLMClientError(Exception):
    """LLM API 调用异常"""
    pass


class LLMClient:
    """统一的大语言模型 API 客户端"""

    def __init__(self, provider='deepseek', api_key=None, base_url=None):
        """
        初始化客户端
        :param provider: 提供商名称（deepseek / openai / siliconflow / aihuashen / gemini）
        :param api_key: API密钥
        :param base_url: 自定义 base_url
        """
        self.provider = provider
        provider_config = Config.LLM_PROVIDERS.get(provider, {})

        if base_url:
            self.base_url = base_url.rstrip('/')
        else:
            self.base_url = provider_config.get('base_url', 'https://api.deepseek.com').rstrip('/')

        if not api_key or not api_key.strip():
            raise LLMClientError('API密钥不能为空')

        # 输入框既兼容纯 Token，也兼容用户从文档中复制的 ``Bearer <TOKEN>``。
        # 统一以 Authorization: Bearer 请求头鉴权（aihuashen 网关同样遵循该约定）。
        normalized_key = api_key.strip()
        if normalized_key.lower().startswith('bearer '):
            normalized_key = normalized_key[7:].strip()
        if not normalized_key:
            raise LLMClientError('API密钥不能为空')

        self.api_key = normalized_key
        self.headers = {
            'Authorization': f'Bearer {normalized_key}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            # 禁用 gzip 压缩，避免流式/响应体需要额外解压逻辑（桌面端本地网络无性能压力）
            'Accept-Encoding': 'identity',
        }

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
            # 通过 extra_body 透传未声明的请求字段（发送时合并进顶层）。
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

        if self.provider == 'gemini':
            model_config = next(
                (
                    item for item in Config.LLM_PROVIDERS['gemini']['models']
                    if item['id'] == configured.get('model')
                ),
                {},
            )
            thinking_mode = model_config.get('thinking_mode', 'always')

            # Gemini OpenAI 兼容端点通过 reasoning_effort 控制思考强度：
            # low / medium / high 对应思考 token 预算 1024 / 8192 / 24576，none 表示关闭思考。
            # 项目内思考强度仅支持 high / max，Gemini 最高档为 high，因此将 max 映射为 high。
            if thinking_enabled:
                configured['reasoning_effort'] = (
                    'high' if reasoning_effort == 'max' else reasoning_effort
                )
            elif thinking_mode == 'switchable':
                # 2.5 Flash 可显式关闭思考
                configured['reasoning_effort'] = 'none'
            else:
                # 2.5 Pro 无法关闭思考，降至最低强度以降低延迟与消耗
                configured['reasoning_effort'] = 'low'
            return configured

        if thinking_enabled:
            configured['reasoning_effort'] = reasoning_effort
            configured['extra_body'] = {'thinking': {'type': 'enabled'}}
        else:
            configured['temperature'] = 0.7
            configured['top_p'] = 0.9
        return configured

    # ---------- 底层 HTTP 请求 ----------

    def _build_body(self, params):
        """合并 extra_body（OpenAI SDK 专有透传字段）到请求体顶层。"""
        body = dict(params)
        extra = body.pop('extra_body', None)
        if isinstance(extra, dict):
            body.update(extra)
        return body

    def _post_json(self, path, payload, timeout=None):
        """POST JSON 并返回 (status, body_dict)；网络错误/5xx 按配置重试。"""
        url = f'{self.base_url}{path}'
        timeout = timeout or Config.LLM_TIMEOUT_SECONDS
        last_error = None
        attempts = Config.LLM_MAX_RETRIES + 1
        for attempt in range(attempts):
            request = urllib.request.Request(
                url,
                data=json.dumps(payload).encode('utf-8'),
                headers=self.headers,
                method='POST',
            )
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    raw = response.read()
                    status = response.status
                if not raw:
                    return status, {}
                return status, json.loads(raw.decode('utf-8'))
            except urllib.error.HTTPError as exc:
                status = exc.code
                body_text = ''
                try:
                    body_text = exc.read().decode('utf-8', errors='replace')
                except Exception:
                    pass
                error_message = self._extract_error_message(body_text, status)
                # 429 / 5xx 可重试，其余直接抛出
                if status in (429, 500, 502, 503, 504) and attempt < attempts - 1:
                    last_error = error_message
                    time.sleep(0.5 * (2 ** attempt))
                    continue
                raise LLMClientError(error_message) from exc
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                last_error = friendly_error_message(exc)
                if attempt < attempts - 1:
                    time.sleep(0.5 * (2 ** attempt))
                    continue
                raise LLMClientError(last_error) from exc
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise LLMClientError('模型服务返回了无法解析的数据，请稍后重试') from exc
        # 理论不可达（重试后必然抛出），防御性返回
        raise LLMClientError(last_error or '模型服务请求失败，请稍后重试')

    @staticmethod
    def _extract_error_message(body_text, status):
        """从错误响应体中提取 error.message 字段；失败则回退为通用中文提示。

        将 HTTP 状态码与纯文本拼接后再做关键词翻译，使 401/403/429/5xx 等
        即使没有命中文本关键词，也能按状态码给出准确的中文文案。
        """
        message = ''
        try:
            data = json.loads(body_text)
            error = data.get('error') or {}
            if isinstance(error, dict):
                message = str(error.get('message', '') or '').strip()
            elif isinstance(error, str):
                message = error.strip()
        except (json.JSONDecodeError, AttributeError, ValueError):
            pass
        if not message:
            message = body_text[:200] if body_text else ''
        combined = f'HTTP {status} {message}'.strip()
        translated = friendly_error_message(combined)
        # combined 未命中任何关键词时 friendly_error_message 会返回兜底文案；
        # 若纯 message 含可识别关键词（如 context length），单独再试一次更准确。
        if translated.startswith('操作失败'):
            translated = friendly_error_message(message)
        return translated

    def _post_stream(self, path, payload, timeout=None):
        """POST JSON 并以 SSE 逐行产出 `data:` 后的 JSON 对象。"""
        url = f'{self.base_url}{path}'
        timeout = timeout or Config.LLM_TIMEOUT_SECONDS
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode('utf-8'),
            headers=self.headers,
            method='POST',
        )
        try:
            response = urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as exc:
            body_text = ''
            try:
                body_text = exc.read().decode('utf-8', errors='replace')
            except Exception:
                pass
            raise LLMClientError(self._extract_error_message(body_text, exc.code)) from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            raise LLMClientError(friendly_error_message(exc)) from exc

        try:
            for raw_line in response:
                line = raw_line.decode('utf-8', errors='replace').strip()
                if not line or not line.startswith('data:'):
                    continue
                data = line[5:].strip()
                if data == '[DONE]':
                    break
                try:
                    obj = json.loads(data)
                except json.JSONDecodeError:
                    continue
                yield obj
        finally:
            close = getattr(response, 'close', None)
            if callable(close):
                close()

    # ---------- 对外 API ----------

    def embed(self, texts):
        """批量文本向量化（Style RAG 使用）。

        当前仅支持硅基流动 BAAI/bge-m3（OpenAI 兼容 embeddings 端点），
        中文语料效果最佳且费用极低。
        :param texts: 文本列表
        :return: list[list[float]]，与输入顺序一一对应
        """
        if self.provider != 'siliconflow':
            raise LLMClientError('当前仅支持硅基流动（siliconflow）的 Embedding 服务')
        model = Config.EMBEDDING_MODEL
        vectors = []
        for offset in range(0, len(texts), Config.EMBEDDING_BATCH_SIZE):
            batch = texts[offset:offset + Config.EMBEDDING_BATCH_SIZE]
            payload = {'model': model, 'input': batch}
            try:
                _, data = self._post_json('/embeddings', payload)
            except LLMClientError as exc:
                raise LLMClientError(f'Embedding 调用失败：{exc}') from exc
            items = data.get('data') or []
            ordered = sorted(items, key=lambda item: item.get('index', 0))
            vectors.extend([item['embedding'] for item in ordered])
        return vectors

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
            raise LLMClientError(f'API调用失败：{friendly_error_message(e)}') from e

    def _generate_sync(self, params):
        """同步（非流式）生成"""
        _, data = self._post_json('/chat/completions', self._build_body(params))

        choices = data.get('choices') or []
        if not choices:
            raise LLMClientError('模型返回结果为空，请稍后重试')
        message = choices[0].get('message') or {}
        result = {
            'content': message.get('content') or '',
            'reasoning_content': message.get('reasoning_content') or '',
            'usage': {
                'prompt_tokens': (data.get('usage') or {}).get('prompt_tokens', 0),
                'completion_tokens': (data.get('usage') or {}).get('completion_tokens', 0),
                'total_tokens': (data.get('usage') or {}).get('total_tokens', 0),
            },
        }
        return result

    def _generate_stream(self, params):
        """流式生成，返回生成器"""
        for chunk in self._post_stream('/chat/completions', self._build_body(params)):
            data = {
                'content': '',
                'reasoning_content': '',
                'finish_reason': None,
            }
            choices = chunk.get('choices') or []
            if choices:
                delta = choices[0].get('delta') or {}
                data['content'] = delta.get('content') or ''
                data['reasoning_content'] = delta.get('reasoning_content') or ''
                data['finish_reason'] = choices[0].get('finish_reason')
            yield data

    def generate_stream_aggregated(self, params):
        """流式生成并聚合结果"""
        full_reasoning = ''
        full_content = ''

        try:
            for chunk in self._post_stream('/chat/completions', self._build_body(params)):
                choices = chunk.get('choices') or []
                if not choices:
                    continue
                delta = choices[0].get('delta') or {}
                if delta.get('content'):
                    piece = delta['content']
                    full_content += piece
                    yield {'type': 'content', 'data': piece}
                if delta.get('reasoning_content'):
                    piece = delta['reasoning_content']
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
            pass
