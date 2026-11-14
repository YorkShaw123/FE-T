"""Orchestrator：Agent 编排层。

对照课件 8.2 / 8.3：
- 统一入参 ``AgentRequest`` 与统一出参 ``AgentResponse``，前端只认一套；
- 单 Agent 直达：取出该类型的编译图，跑一次，从最终 State 里提取结果；
- 多 Agent 串联：按 Pipeline 定义顺序执行，前一步的 structured 注入后一步 context；
- 澄清：意图不明时返回结构化追问，不硬猜。

与课件的两处本地化：``student_id`` 换成 ``user_id``；``tenant_id`` 保留但固定
``local_default``（桌面端只有一个用户）。

图是懒加载的：第一次用到某个 Agent 才 import 并编译，避免启动时把三张图全建一遍。
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from backend.core.exceptions import AgentExecutionError, PipelineError
from backend.core.logger import get_logger
from backend.core.retry import with_retry

logger = get_logger(__name__)


class ExecutionMode(str, Enum):
    SINGLE = 'single'
    PIPELINE = 'pipeline'
    CLARIFY = 'clarify'


class AgentType(str, Enum):
    WRITING = 'writing'
    STYLE_QA = 'style_qa'
    CONSISTENCY = 'consistency'


# Agent 类型 → (模块路径, 构建函数名)，用于懒加载
_GRAPH_BUILDERS: dict[AgentType, tuple[str, str]] = {
    AgentType.WRITING: ('backend.agents.writing.graph', 'build_writing_graph'),
    AgentType.STYLE_QA: ('backend.agents.style_qa.graph', 'build_style_qa_graph'),
    AgentType.CONSISTENCY: ('backend.agents.consistency.graph', 'build_consistency_graph'),
}


class AgentRequest(BaseModel):
    """所有 Agent 请求的统一入参。"""

    user_id: str = Field(default='local', description='发起请求的用户')
    tenant_id: str = Field(default='local_default', description='租户（桌面端固定）')
    session_id: str = Field(..., description='会话 ID，用于拼接 thread_id')
    agent_type: AgentType = Field(..., description='目标 Agent')
    user_message: str = Field(default='', description='用户输入的原始文本')
    context: dict[str, Any] = Field(default_factory=dict, description='附加上下文')
    pipeline_mode: bool = Field(default=False, description='是否强制走串联')

    @property
    def thread_id(self) -> str:
        return f'flora_{self.user_id}_session_{self.session_id}'


class AgentResponse(BaseModel):
    """所有 Agent 响应的统一出参。"""

    success: bool
    agent_type: AgentType
    content: str = ''
    structured: dict[str, Any] | None = None
    fallback_used: bool = False
    error_msg: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PipelineResult(BaseModel):
    steps: list[AgentResponse] = Field(default_factory=list)
    combined: dict[str, Any] = Field(default_factory=dict)


class Orchestrator:
    """Agent 编排服务。"""

    def __init__(self) -> None:
        self._agent_graphs: dict[AgentType, Any] = {}
        # Pipeline 定义：写完之后自动审一遍
        self._pipelines: dict[str, list[AgentType]] = {
            'write_and_review': [AgentType.WRITING, AgentType.CONSISTENCY],
            'style_pass': [AgentType.WRITING, AgentType.STYLE_QA],
        }
        logger.info('orchestrator.initialized')

    # ── 图管理 ────────────────────────────────────────────

    def register(self, agent_type: AgentType, graph: Any) -> None:
        """注入已编译的图。生产环境由 _get_agent_graph 懒加载，测试用它注入假图。"""
        self._agent_graphs[agent_type] = graph

    def _get_agent_graph(self, agent_type: AgentType) -> Any:
        if agent_type in self._agent_graphs:
            return self._agent_graphs[agent_type]

        spec = _GRAPH_BUILDERS.get(agent_type)
        if spec is None:
            raise AgentExecutionError(f'未知 Agent 类型: {agent_type}')

        module_path, builder_name = spec
        try:
            module = __import__(module_path, fromlist=[builder_name])
            builder = getattr(module, builder_name)
        except ImportError as exc:
            raise AgentExecutionError(f'Agent 图尚未接入: {agent_type.value}') from exc

        graph = builder()
        self._agent_graphs[agent_type] = graph
        logger.info('orchestrator.graph_loaded', agent_type=agent_type.value)
        return graph

    # ── 入口 ──────────────────────────────────────────────

    async def handle(self, request: AgentRequest) -> AgentResponse:
        logger.info(
            'orchestrator.handle_start',
            agent_type=request.agent_type.value,
            pipeline_mode=request.pipeline_mode,
            session=request.session_id,
        )
        try:
            if request.pipeline_mode:
                pipeline = await self._run_pipeline(request)
                return self._aggregate_pipeline(pipeline, request)
            return await self._run_single_agent(request)
        except Exception as exc:  # 兜底：任何异常都转成失败响应
            logger.error(
                'orchestrator.handle_failed',
                agent_type=request.agent_type.value,
                error=str(exc),
                exc_info=True,
            )
            return AgentResponse(
                success=False,
                agent_type=request.agent_type,
                content='系统处理请求时遇到问题，请稍后再试。',
                error_msg=str(exc),
            )

    async def _run_single_agent(self, request: AgentRequest) -> AgentResponse:
        graph = self._get_agent_graph(request.agent_type)

        initial_state: dict[str, Any] = {
            'session_id': request.session_id,
            'user_id': request.user_id,
            'tenant_id': request.tenant_id,
            'user_message': request.user_message,
            'messages': [],
            **request.context,
        }
        config = {'configurable': {'thread_id': request.thread_id}}

        @with_retry(agent_type=request.agent_type.value)
        async def _invoke() -> Any:
            return await graph.ainvoke(initial_state, config=config)

        result_state = await _invoke()
        if not isinstance(result_state, dict):
            result_state = {'final_content': str(result_state)}

        content = result_state.get('final_content') or result_state.get('content') or ''
        if not content:
            messages = result_state.get('messages') or []
            if messages:
                last = messages[-1]
                content = getattr(last, 'text', None) or getattr(last, 'content', '') or ''

        return AgentResponse(
            success=True,
            agent_type=request.agent_type,
            content=str(content),
            structured=result_state.get('structured_output'),
            fallback_used=bool(result_state.get('fallback_used', False)),
            metadata={
                'record_id': result_state.get('record_id'),
                'token_budget': result_state.get('token_budget'),
                'style_rewrite_status': result_state.get('style_rewrite_status'),
            },
        )

    async def _run_pipeline(self, request: AgentRequest) -> PipelineResult:
        pipeline_key = request.context.get('pipeline_key', 'write_and_review')
        if pipeline_key not in self._pipelines:
            raise PipelineError(f'未知 Pipeline 类型: {pipeline_key}')

        result = PipelineResult()
        current_context = dict(request.context)

        for index, agent_type in enumerate(self._pipelines[pipeline_key]):
            step_request = AgentRequest(
                user_id=request.user_id,
                tenant_id=request.tenant_id,
                session_id=f'{request.session_id}_step{index}',
                agent_type=agent_type,
                user_message=request.user_message,
                context=current_context,
                pipeline_mode=False,  # 防止递归
            )
            step_response = await self._run_single_agent(step_request)
            result.steps.append(step_response)

            if not step_response.success:
                logger.warning(
                    'orchestrator.pipeline_step_failed',
                    step=index + 1,
                    agent_type=agent_type.value,
                )
                break

            if step_response.structured:
                current_context[f'{agent_type.value}_result'] = step_response.structured
            # 写作结果要能传给后面的审查/问答
            if agent_type == AgentType.WRITING:
                if step_response.metadata.get('record_id'):
                    current_context['record_id'] = step_response.metadata['record_id']
                current_context['chapter_text'] = step_response.content

        return result

    def _aggregate_pipeline(
        self,
        pipeline_result: PipelineResult,
        request: AgentRequest,
    ) -> AgentResponse:
        combined: dict[str, Any] = {}
        contents: list[str] = []
        any_success = False

        for index, step in enumerate(pipeline_result.steps):
            combined[f'step_{index + 1}'] = {
                'agent_type': step.agent_type.value,
                'success': step.success,
                'structured': step.structured,
            }
            if step.success:
                any_success = True
                if step.content:
                    contents.append(step.content)

        return AgentResponse(
            success=any_success,
            agent_type=request.agent_type,
            content='\n\n---\n\n'.join(contents),
            structured=combined,
            fallback_used=any(step.fallback_used for step in pipeline_result.steps),
        )


_orchestrator_instance: Orchestrator | None = None


def get_orchestrator() -> Orchestrator:
    global _orchestrator_instance
    if _orchestrator_instance is None:
        _orchestrator_instance = Orchestrator()
    return _orchestrator_instance


def reset_orchestrator() -> None:
    """测试用：清掉单例与已缓存的图。"""
    global _orchestrator_instance
    _orchestrator_instance = None
