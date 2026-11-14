"""统一异常体系。

对照课件 3.3 与 3.5：异常先分类，再决定要不要重试、怎么降级、给用户看什么话。

三层兜底依赖这里的分类：
- ``RETRYABLE_ERRORS``：网络抖动、超时、向量库不可用——值得重试；
- ``NON_RETRYABLE_ERRORS``：输入非法、鉴权失败——重试也没用，立即抛出；
- 其余 ``AppError``：业务异常，直接转成用户可读文案。

旧的 ``GenerationError`` 保留为 ``InvalidInputError`` 的子类，
迁移期旧代码 ``raise GenerationError('请输入API密钥')`` 语义不变。
"""

from __future__ import annotations

from typing import Any

DEFAULT_USER_MESSAGE = '服务暂时不可用，请稍后再试。'


class AppError(Exception):
    """所有业务异常的基类。"""

    status_code: int = 500
    user_message: str = DEFAULT_USER_MESSAGE
    event: str = 'app_error'
    # 为 True 时，构造参数里的 message 会原样展示给用户。
    # 只有"用户能看懂的错误"（如输入校验）才该这样，基础设施类异常不能泄内部细节。
    message_is_user_facing: bool = False

    def __init__(
        self,
        message: str = '',
        *,
        user_message: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message or self.user_message)
        self.message = message or self.user_message
        self.details = details or {}
        if user_message:
            self.user_message = user_message


class InvalidInputError(AppError):
    """请求参数不合法（400）。"""

    status_code = 400
    user_message = '请求参数有误，请检查后重试。'
    event = 'invalid_input'
    message_is_user_facing = True


class GenerationError(InvalidInputError):
    """兼容旧名：生成链路上的可预期输入错误。"""

    event = 'generation_error'


class AuthenticationError(AppError):
    """令牌缺失或无效（401）。"""

    status_code = 401
    user_message = '登录状态已失效，请重新打开应用。'
    event = 'authentication_error'


class NotFoundError(AppError):
    """资源不存在（404）。"""

    status_code = 404
    user_message = '请求的内容不存在。'
    event = 'not_found'


class LLMAPIError(AppError):
    """模型服务调用失败（502），可重试。"""

    status_code = 502
    user_message = '模型服务暂时不可用，请稍后重试。'
    event = 'llm_api_error'


class AgentExecutionError(AppError):
    """Agent 图执行失败（500）。"""

    status_code = 500
    user_message = '处理请求时遇到问题，请稍后重试。'
    event = 'agent_execution_error'


class PipelineError(AppError):
    """多 Agent 串联编排失败（500）。"""

    status_code = 500
    user_message = '多步骤处理未能完成，已完成的部分已保留。'
    event = 'pipeline_error'


class IntentRouteError(AppError):
    """意图路由失败（500）。"""

    status_code = 500
    user_message = '没有理解您的请求，请换一种说法。'
    event = 'intent_route_error'


# 三层兜底用的分类表
RETRYABLE_ERRORS: tuple[type[BaseException], ...] = (
    LLMAPIError,
    TimeoutError,
    ConnectionError,
    OSError,
)

NON_RETRYABLE_ERRORS: tuple[type[BaseException], ...] = (
    InvalidInputError,
    AuthenticationError,
    NotFoundError,
)


def to_user_message(exc: BaseException) -> str:
    """把任意异常翻成人话，保证用户永远能看到一句可读的原因。"""
    if isinstance(exc, AppError):
        # 输入类错误把原话给用户（旧版就是这样，如"请输入API密钥"）；
        # 基础设施类错误只给固定文案，避免把内部细节漏到界面。
        if exc.message_is_user_facing and exc.message:
            return exc.message
        return exc.user_message
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return '网络连接超时，请检查网络后重试。'
    return DEFAULT_USER_MESSAGE


def error_payload(exc: BaseException) -> dict[str, Any]:
    """统一错误响应体，形状与迁移前的 Flask 版本保持一致。"""
    payload: dict[str, Any] = {'success': False, 'error': to_user_message(exc)}
    if isinstance(exc, AppError) and exc.details:
        payload['details'] = exc.details
    return payload
