"""P3 一致性审查图测试。

四维并行 + Reducer 合并是这张图的关键：四个检查节点同时往 findings 里写，
必须靠 ``operator.add`` 合并而不是互相覆盖。这里的用例专门验证这一点。
"""

from __future__ import annotations

import json

import pytest

from backend.agents.consistency.graph import build_consistency_graph


class _Msg:
    def __init__(self, content: str):
        self.content = content


@pytest.fixture()
def fake_review(monkeypatch):
    """按 system 提示词分派：实体抽取返回固定 JSON，各维度返回各自的问题。"""
    state = {'dimensions': {}, 'calls': []}

    async def fake_call(agent_state, system_prompt, user_prompt):
        state['calls'].append(user_prompt)
        if '信息抽取器' in system_prompt:
            return json.dumps(
                {'people': ['雨生'], 'places': ['青瓦小院'], 'items': ['小葫芦']},
                ensure_ascii=False,
            )
        if '人物性格' in user_prompt:
            payload = {'findings': [{
                'code': 'char-1', 'quote': '他大声训斥', 'problem': '雨生不会训斥他人',
                'suggestion': '改成他低头躲开', 'severity': 'major',
            }]}
            state['dimensions']['character'] = True
            return json.dumps(payload, ensure_ascii=False)
        if '时间顺序' in user_prompt:
            payload = {'findings': [{
                'code': 'time-1', 'quote': '', 'problem': '先下雨后许愿，因果颠倒',
                'suggestion': '调换顺序', 'severity': 'blocker',
            }]}
            state['dimensions']['timeline'] = True
            return json.dumps(payload, ensure_ascii=False)
        if '伏笔' in user_prompt:
            # 故意重复 character 那条，验证去重
            payload = {'findings': [
                {'code': 'f-1', 'quote': '', 'problem': '葫芦的来历没有交代',
                 'suggestion': '补一句来历', 'severity': 'minor'},
                {'code': 'char-1', 'quote': '他大声训斥', 'problem': '雨生不会训斥他人',
                 'suggestion': '改成他低头躲开', 'severity': 'major'},
            ]}
            state['dimensions']['foreshadow'] = True
            return json.dumps(payload, ensure_ascii=False)
        return json.dumps({'findings': []}, ensure_ascii=False)

    monkeypatch.setattr('backend.agents.consistency.nodes._call_model', fake_call)
    return state


def _state(**overrides):
    base = {
        'chapter_text': (
            '他大声训斥了来求雨的百姓。雨声很密，像有人在屋顶上撒豆子。'
            '她站在窗边，没有回头。他没有立刻回答，风从门缝里钻进来。'
        ),
        'api_key': 'sk-test',
        'template_ids': [],
    }
    base.update(overrides)
    return base


async def test_parallel_dimensions_are_merged(fake_review):
    """三个模型维度 + 一个本地维度都要出现在结果里，且重复项被去掉。"""
    graph = build_consistency_graph()
    result = await graph.ainvoke(_state())

    problems = [item['problem'] for item in result['findings']]
    assert '雨生不会训斥他人' in problems
    assert '先下雨后许愿，因果颠倒' in problems
    assert '葫芦的来历没有交代' in problems
    # 重复的那条只保留一次
    assert problems.count('雨生不会训斥他人') == 1

    # 三个模型维度都被真正调用过（并行而不是短路）
    assert set(fake_review['dimensions']) == {'character', 'timeline', 'foreshadow'}


async def test_severity_count_and_report(fake_review):
    graph = build_consistency_graph()
    result = await graph.ainvoke(_state())

    counts = result['severity_count']
    assert counts['blocker'] == 1
    assert counts['major'] == 1
    assert counts['minor'] >= 0
    assert '# 一致性审查报告' in result['report']
    assert '时间线' in result['report']


async def test_no_api_key_only_runs_local_check(monkeypatch):
    """没有 Key 时不该调模型，但仍要跑文风漂移并如实说明。"""
    called = {'n': 0}

    async def boom(*args, **kwargs):
        called['n'] += 1
        raise AssertionError('没有 Key 时不应调用模型')

    monkeypatch.setattr('backend.agents.consistency.nodes._call_model', boom)

    graph = build_consistency_graph()
    result = await graph.ainvoke(_state(api_key='', chapter_text='短句。短句。短句。'))

    assert called['n'] == 0
    assert '未提供 API Key' in result['report']


async def test_style_drift_detected_locally():
    """范例是长句、正文是短句，应该报出句长漂移。直接测节点，绕开数据库装载。"""
    from backend.agents.consistency.nodes import check_style_drift_node, style_metrics

    long_example = (
        '他推开门，屋子里很冷。雨声很密，像有人在屋顶上撒豆子。'
        '她站在窗边，没有回头，只问了一句：你要走了吗。'
    ) * 3
    short_chapter = '他开门。屋里亮着。桌上有纸。窗外下雨。' * 6

    chapter_metrics = style_metrics(short_chapter)
    example_metrics = style_metrics(long_example)
    assert chapter_metrics and example_metrics
    assert chapter_metrics['rhythm.sentence_length.mean'] < example_metrics[
        'rhythm.sentence_length.mean'
    ]

    result = await check_style_drift_node({
        'chapter_text': short_chapter,
        'setting_snapshot': {'example': [{'content': long_example}]},
    })
    drifts = [item for item in result['findings'] if item['dimension'] == 'style_drift']
    assert drifts
    assert '平均句长' in drifts[0]['problem']


async def test_style_drift_silent_without_examples():
    from backend.agents.consistency.nodes import check_style_drift_node

    result = await check_style_drift_node({
        'chapter_text': '他开门。屋里亮着。',
        'setting_snapshot': {'character': [{'content': '人物设定'}]},
    })
    assert result['findings'] == []


async def test_report_lists_nothing_when_clean(monkeypatch):
    async def clean_call(agent_state, system_prompt, user_prompt):
        if '信息抽取器' in system_prompt:
            return '{"people":[],"places":[],"items":[]}'
        return '{"findings":[]}'

    monkeypatch.setattr('backend.agents.consistency.nodes._call_model', clean_call)

    graph = build_consistency_graph()
    result = await graph.ainvoke(_state())
    assert '没有发现明显冲突' in result['report']
    assert result['severity_count'] == {'blocker': 0, 'major': 0, 'minor': 0}
