"""P2 公共层测试：三层兜底、编排器、Token 预算。

三者都刻意做成"不碰网络就能验"的形态：编排器通过 register() 注入假图，
重试用零延迟，预算纯函数。
"""

from __future__ import annotations

import pytest

from backend.core.exceptions import AgentExecutionError, InvalidInputError, LLMAPIError
from backend.core.orchestrator import (
    AgentRequest,
    AgentResponse,
    AgentType,
    Orchestrator,
)
from backend.core.retry import with_retry
from backend.core.token_budget import (
    build_deai_rewrite_instruction,
    build_style_reference_rewrite_instruction,
    calculate_token_budget,
    estimate_tokens,
    format_budget_error,
    get_model_context_window,
)


# ── Token 预算 ───────────────────────────────────────────

def test_estimate_tokens_cjk_vs_ascii():
    assert estimate_tokens('') == 0
    cjk = estimate_tokens('这是一段中文文本')
    ascii_text = estimate_tokens('this is a plain english sentence')
    assert cjk > 0 and ascii_text > 0
    # 同样长度的中文应比英文占用更多 token
    assert estimate_tokens('中' * 100) > estimate_tokens('a' * 100)


def test_context_window_lookup():
    assert get_model_context_window('deepseek', 'deepseek-v4-pro') == 1048576
    assert get_model_context_window('deepseek', 'nope') > 0


def test_budget_safe_for_small_prompt():
    budget = calculate_token_budget('短提示词', 'deepseek', 'deepseek-v4-pro')
    assert budget['status'] == 'safe'
    assert budget['blocking_phase'] is None
    assert budget['phases']['primary']['status'] == 'safe'


def test_budget_over_when_prompt_too_long():
    huge = '字' * 3_000_000
    budget = calculate_token_budget(huge, 'deepseek', 'deepseek-v4-pro')
    assert budget['status'] == 'over'
    assert budget['blocking_phase'] == 'primary'
    message = format_budget_error(budget)
    assert '超出模型限制' in message
    assert '初稿生成' in message


def test_budget_counts_postprocess_phases():
    modest = '字' * 200_000
    budget = calculate_token_budget(
        modest,
        'deepseek',
        'deepseek-v4-pro',
        deai_enabled=True,
        style_reference_enabled=True,
    )
    assert set(budget['phases']) == {'primary', 'deai', 'style_reference'}


def test_rewrite_instructions_carry_reference_text():
    text = build_style_reference_rewrite_instruction(['片段一', '片段二'])
    assert '<style_references>' in text
    assert '【参考片段 1】' in text and '【参考片段 2】' in text
    assert '不得复制' in text

    deai = build_deai_rewrite_instruction('自定义去味要求')
    assert '自定义去味要求' in deai
    assert '不得改变剧情' in deai


# ── 三层兜底 ─────────────────────────────────────────────

async def test_retry_passes_through_on_success():
    calls = {'n': 0}

    @with_retry(agent_type='writing', delays=(0, 0), timeout=5)
    async def ok():
        calls['n'] += 1
        return '成功'

    assert await ok() == '成功'
    assert calls['n'] == 1


async def test_retry_recovers_after_transient_failure():
    calls = {'n': 0}

    @with_retry(agent_type='writing', delays=(0, 0), timeout=5)
    async def flaky():
        calls['n'] += 1
        if calls['n'] < 3:
            raise LLMAPIError('网络抖动')
        return '第三次成功'

    assert await flaky() == '第三次成功'
    assert calls['n'] == 3


async def test_non_retryable_is_not_retried():
    calls = {'n': 0}

    @with_retry(agent_type='writing', delays=(0, 0), timeout=5)
    async def bad_input():
        calls['n'] += 1
        raise InvalidInputError('请输入API密钥')

    with pytest.raises(InvalidInputError):
        await bad_input()
    assert calls['n'] == 1


async def test_all_attempts_fail_uses_agent_fallback():
    @with_retry(agent_type='writing', delays=(0, 0), timeout=5)
    async def always_fail():
        raise LLMAPIError('一直失败')

    result = await always_fail()
    assert result['fallback_used'] is True
    assert result['system_fallback'] is False
    assert '未能完成' in result['content']


async def test_unknown_agent_type_falls_to_system_level():
    @with_retry(agent_type='unknown_agent', delays=(0, 0), timeout=5)
    async def always_fail():
        raise LLMAPIError('一直失败')

    result = await always_fail()
    assert result['system_fallback'] is True
    assert '暂时不可用' in result['content']


async def test_timeout_is_treated_as_retryable():
    import asyncio

    calls = {'n': 0}

    @with_retry(agent_type='style_qa', delays=(0, 0), timeout=0.05)
    async def slow():
        calls['n'] += 1
        await asyncio.sleep(0.2)

    result = await slow()
    assert calls['n'] == 3
    assert result['fallback_used'] is True


# ── 编排器 ───────────────────────────────────────────────

class FakeGraph:
    """最小可用的假图：记录输入 State，返回预设结果。"""

    def __init__(self, result: dict, seen: list | None = None):
        self.result = result
        self.seen = seen if seen is not None else []

    async def ainvoke(self, state, config=None):
        self.seen.append(state)
        return dict(self.result)


def _request(agent_type=AgentType.WRITING, **kwargs) -> AgentRequest:
    payload = {
        'session_id': 'sess-1',
        'agent_type': agent_type,
        'user_message': '写一段',
    }
    payload.update(kwargs)
    return AgentRequest(**payload)


async def test_single_agent_dispatch():
    orchestrator = Orchestrator()
    graph = FakeGraph({'final_content': '这是初稿', 'record_id': 42})
    orchestrator.register(AgentType.WRITING, graph)

    response = await orchestrator.handle(_request())

    assert isinstance(response, AgentResponse)
    assert response.success is True
    assert response.content == '这是初稿'
    assert response.metadata['record_id'] == 42
    # 入参被正确翻译进 State
    state = graph.seen[0]
    assert state['user_message'] == '写一段'
    assert state['session_id'] == 'sess-1'
    assert state['tenant_id'] == 'local_default'


async def test_thread_id_shape():
    assert _request().thread_id == 'flora_local_session_sess-1'


async def test_missing_graph_reports_not_wired(monkeypatch):
    """构建失败要给出可读错误，而不是 ImportError 冒泡到接口层。

    用一个不存在的模块路径来验证，不依赖"某张图还没写"这种临时状态。
    """
    from backend.core import orchestrator as orchestrator_module

    orchestrator = Orchestrator()
    monkeypatch.setitem(
        orchestrator_module._GRAPH_BUILDERS,
        AgentType.CONSISTENCY,
        ('backend.agents.not_implemented_yet', 'build_consistency_graph'),
    )
    with pytest.raises(AgentExecutionError, match='Agent 图尚未接入'):
        orchestrator._get_agent_graph(AgentType.CONSISTENCY)


async def test_style_qa_graph_is_wired():
    """风格问答图已接入，应该能被懒加载并缓存。"""
    orchestrator = Orchestrator()
    graph = orchestrator._get_agent_graph(AgentType.STYLE_QA)
    assert graph is not None
    assert orchestrator._get_agent_graph(AgentType.STYLE_QA) is graph


async def test_fallback_flag_propagates():
    orchestrator = Orchestrator()
    orchestrator.register(
        AgentType.WRITING,
        FakeGraph({'final_content': '降级内容', 'fallback_used': True}),
    )
    response = await orchestrator.handle(_request())
    assert response.fallback_used is True


async def test_pipeline_passes_context_between_agents():
    orchestrator = Orchestrator()
    review_graph = FakeGraph({'final_content': '审查报告'})

    orchestrator.register(
        AgentType.WRITING,
        FakeGraph({'final_content': '第一章正文', 'record_id': 7}),
    )
    orchestrator.register(AgentType.CONSISTENCY, review_graph)

    response = await orchestrator.handle(_request(
        pipeline_mode=True,
        context={'pipeline_key': 'write_and_review'},
    ))

    assert response.success is True
    assert '第一章正文' in response.content and '审查报告' in response.content
    assert set(response.structured) == {'step_1', 'step_2'}

    # 后一步拿到了前一步的正文与记录 id
    review_state = review_graph.seen[0]
    assert review_state['chapter_text'] == '第一章正文'
    assert review_state['record_id'] == 7


async def test_pipeline_unknown_key_returns_failure():
    orchestrator = Orchestrator()
    orchestrator.register(AgentType.WRITING, FakeGraph({'final_content': 'x'}))
    response = await orchestrator.handle(_request(
        pipeline_mode=True,
        context={'pipeline_key': '不存在的流程'},
    ))
    assert response.success is False
    assert '未知 Pipeline 类型' in (response.error_msg or '')
