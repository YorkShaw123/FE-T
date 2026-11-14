"""P3 风格问答图测试。

四条分支各走一次：精确问题走检索、模糊问题先造假设回答、宽泛问题先拆查询、
无关问题直接答。模型与检索后端都是假的，图本身是真的。
"""

from __future__ import annotations

import sqlite3

import pytest

from backend.config import get_settings
from backend.agents.style_qa.graph import build_style_qa_graph
from backend.agents.style_qa.nodes import (
    CONFIDENCE_THRESHOLD,
    classify_by_rules,
)


@pytest.fixture()
async def qa_env(tmp_path, monkeypatch):
    monkeypatch.setenv('FLORA_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('FLORA_MODELS_DIR', str(tmp_path / 'models'))
    get_settings.cache_clear()

    import backend.db as db_module
    from backend.db import dispose_engine
    from backend.db.migrations import run_migrations

    db_module._engine = None
    db_module._session_factory = None
    await run_migrations()

    yield tmp_path / 'data'

    await dispose_engine()
    get_settings.cache_clear()


class FakeModel:
    """按 system 提示词决定返回什么，够用来区分类/假设/作答。"""

    def __init__(self, answer: str = '这是回答。'):
        self.answer = answer
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        system = messages[0].content if hasattr(messages[0], 'content') else ''

        class _Msg:
            content = ''

        result = _Msg()
        if '问题分类器' in system:
            result.content = 'PRECISE'
        elif '假设性回答' in system or '可能答案' in system:
            result.content = '假设性回答：用短句和留白营造克制感。'
        elif '改写' in system:
            result.content = '短句节奏\n留白处理\n克制情绪'
        else:
            result.content = self.answer
        return result


@pytest.fixture()
def fake_llm(monkeypatch):
    holder = {'model': FakeModel()}
    monkeypatch.setattr(
        'backend.agents.style_qa.nodes._build_model', lambda state: holder['model']
    )
    return holder


@pytest.fixture()
def fake_kb(monkeypatch):
    holder = {'items': [], 'meta': {'mode': 'local_style'}, 'calls': []}

    class StubBackend:
        async def search(self, **kwargs):
            holder['calls'].append(kwargs)
            return holder['items'], holder['meta']

    monkeypatch.setattr(
        'backend.agents.style_qa.nodes.get_kb_backend', lambda: StubBackend()
    )
    return holder


async def _run(graph, state: dict, thread: str = 't1'):
    return await graph.ainvoke(
        state, config={'configurable': {'thread_id': thread}}
    )


def test_classify_rules():
    assert classify_by_rules('你好') == 'GENERAL'
    assert classify_by_rules('这段是不是有点平') == 'VAGUE'
    assert classify_by_rules('我想知道短句怎么写，还有留白怎么处理，同时怎么控制节奏。') == 'BROAD'
    assert classify_by_rules('怎么让对话更有张力？') == 'PRECISE'
    assert classify_by_rules('随便说一句') is None


async def test_high_confidence_uses_rag(qa_env, fake_llm, fake_kb):
    fake_kb['items'] = [{
        'chunk_id': 1, 'content': '夜色沉了下来。', 'score': CONFIDENCE_THRESHOLD + 0.2,
        'source': '测试语料', 'scene_type': 'environment',
    }]
    graph = build_style_qa_graph()
    result = await _run(graph, {
        'user_message': '怎么让对话更有张力？',
        'api_key': 'sk-test',
        'corpus_ids': [1],
    }, thread='high-1')

    assert result['query_type'] == 'PRECISE'
    assert result['answer_mode'] == 'rag'
    assert result['is_high_confidence'] is True
    assert result['sources'] == ['测试语料']
    assert result['messages'][-1]['role'] == 'assistant'


async def test_low_confidence_answers_directly_and_enqueues(qa_env, fake_llm, fake_kb):
    fake_kb['items'] = []
    graph = build_style_qa_graph()
    result = await _run(graph, {
        'user_message': '怎么让对话更有张力？',
        'api_key': 'sk-test',
        'corpus_ids': [1],
    }, thread='low-1')

    assert result['answer_mode'] == 'direct'
    assert result['is_high_confidence'] is False
    assert result['pending_enqueued'] is True

    db_path = get_settings().database_path
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            'SELECT question FROM style_pending_questions'
        ).fetchall()
    assert rows and rows[0][0] == '怎么让对话更有张力？'


async def test_duplicate_pending_is_not_inserted_twice(qa_env, fake_llm, fake_kb):
    fake_kb['items'] = []
    graph = build_style_qa_graph()
    for index, thread in enumerate(('dup-a', 'dup-b')):
        await _run(graph, {
            'user_message': '怎么让对话更有张力？',
            'api_key': 'sk-test',
            'corpus_ids': [1],
        }, thread=thread)

    db_path = get_settings().database_path
    with sqlite3.connect(db_path) as connection:
        count = connection.execute(
            'SELECT COUNT(*) FROM style_pending_questions'
        ).fetchone()[0]
    assert count == 1


async def test_vague_branch_generates_hypothetical_doc(qa_env, fake_llm, fake_kb):
    fake_kb['items'] = []
    graph = build_style_qa_graph()
    result = await _run(graph, {
        'user_message': '这段是不是有点平',
        'api_key': 'sk-test',
    }, thread='vague-1')

    assert result['query_type'] == 'VAGUE'
    assert '假设性回答' in result['hyde_doc']
    # 检索用的是假设回答，不是原问题
    assert fake_kb['calls'][0]['query_text'] == result['hyde_doc']


async def test_broad_branch_rewrites_into_queries(qa_env, fake_llm, fake_kb):
    fake_kb['items'] = []
    graph = build_style_qa_graph()
    result = await _run(graph, {
        'user_message': '我想知道短句怎么写，还有留白怎么处理，同时怎么控制节奏。',
        'api_key': 'sk-test',
    }, thread='broad-1')

    assert result['query_type'] == 'BROAD'
    assert len(result['rewritten_queries']) == 3
    assert '短句节奏' in fake_kb['calls'][0]['query_text']


async def test_general_branch_skips_retrieval(qa_env, fake_llm, fake_kb):
    graph = build_style_qa_graph()
    result = await _run(graph, {
        'user_message': '你能做什么？',
        'api_key': 'sk-test',
    }, thread='general-1')

    assert result['query_type'] == 'GENERAL'
    assert result['answer_mode'] == 'general'
    assert fake_kb['calls'] == []


async def test_no_api_key_still_answers(qa_env, fake_kb):
    """没有 Key 时不该整张图崩掉：分类走规则，检索照常。"""
    fake_kb['items'] = []
    graph = build_style_qa_graph()

    class NoKeyModel:
        async def ainvoke(self, messages):
            class _Msg:
                content = '按经验回答。'
            return _Msg()

    import backend.agents.style_qa.nodes as nodes
    original = nodes._build_model
    nodes._build_model = lambda state: NoKeyModel()
    try:
        result = await _run(graph, {
            'user_message': '随便问一句关于短句的问题',  # 规则判不出类型
            'api_key': '',
        }, thread='nokey-1')
    finally:
        nodes._build_model = original

    assert result['answer']
    assert result['query_type'] == 'PRECISE'
