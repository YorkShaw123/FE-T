"""跨服务层共享的领域异常与面向用户的中文错误文案。"""
import re


class GenerationError(Exception):
    """用户可修正的文章生成或记录操作错误。"""


def friendly_error_message(exc):
    """
    将任意异常转换为用户能看懂的中文提示。

    - GenerationError 等业务异常文案本身已是中文，原样返回
    - 常见的英文 SDK/网络异常（鉴权、限流、余额、超时等）翻译为中文
    - 未知异常返回通用提示，避免把技术细节直接暴露给用户
    """
    message = str(exc).strip()
    if not message:
        return '操作失败，请稍后重试'
    # 文案已含中文则原样返回（业务异常均为中文）
    if re.search(r'[\u4e00-\u9fff]', message):
        return message

    lowered = message.lower()
    # 鉴权失败
    if any(key in lowered for key in (
        'invalid api key', 'invalid_api_key', 'unauthorized',
        'authentication', 'permission denied', 'access denied',
        '401', '403',
    )):
        return 'API 密钥无效或已失效，请检查密钥是否正确、是否已过期'
    # 余额或配额不足
    if any(key in lowered for key in (
        'insufficient balance', 'insufficient_balance', 'balance not enough',
        'insufficient quota', 'no balance', 'exceeded your current quota',
    )):
        return '账户余额不足或额度已用尽，请充值或补充额度后重试'
    # 限流
    if any(key in lowered for key in ('rate limit', 'rate_limit', 'too many requests', '429')):
        return '请求过于频繁，已触发限流，请稍等片刻再试'
    # 连接与超时
    if 'timeout' in lowered:
        return '连接模型服务超时，请检查网络后重试'
    if any(key in lowered for key in (
        'connection error', 'connection_error', 'connection refused',
        'connection reset', 'connect error', 'network error', 'network is unreachable',
    )):
        return '无法连接模型服务，请检查网络设置后重试'
    # 上下文超长
    if any(key in lowered for key in (
        'maximum context length', 'context length', 'context_length',
        'context window', 'token limit', 'tokens exceed', 'too long',
    )):
        return '输入内容超出模型的上下文长度限制，请减少前置文章或模板内容后重试'
    # 模型相关
    if any(key in lowered for key in (
        'model not found', 'model_not_found', 'does not exist',
        'not exist', 'invalid model', 'unknown model',
    )):
        return '所选模型不存在或不可用，请刷新模型列表后重试'
    # 内容安全拦截
    if any(key in lowered for key in (
        'content policy', 'content_filter', 'content filter',
        'moderation', 'sensitive content', 'safety',
    )):
        return '生成内容被模型的安全策略拦截，请调整提示词后重试'
    # 服务端不可用
    if any(key in lowered for key in (
        'server error', 'internal server', 'bad gateway', 'service unavailable',
        'overloaded', 'backend', '500', '502', '503', '504',
    )):
        return '模型服务暂时不可用（服务器繁忙），请稍后重试'
    return '操作失败，请稍后重试（若问题持续出现，请检查配置或联系管理员）'
