"""P2 收尾测试：局部编辑、文件解析、统一入口。

局部编辑与意图路由都把模型替换成假实现；文件解析用真实的 TXT 字节验证
编码回退与大小限制；统一入口验证"规则前置拦截不花 Token"这条约定。
"""

from __future__ import annotations

import json

import pytest


class FakeMessage:
    def __init__(self, content: str):
        self.content = content
        self.additional_kwargs = {}
        self.response_metadata = {}


class FakeModel:
    def __init__(self, text: str):
        self.text = text
        self.seen: list = []

    async def ainvoke(self, messages):
        self.seen.append(messages)
        return FakeMessage(self.text)


@pytest.fixture()
def fake_edit_model(monkeypatch):
    """替换局部编辑的模型接缝（LLMFactory 的类方法）。"""
    holder = {'model': FakeModel('改写后的文字')}

    def fake_get_llm(agent_type, **kwargs):
        holder['kwargs'] = kwargs
        return holder['model'], []

    monkeypatch.setattr(
        'backend.services.editing_service.LLMFactory.get_llm', fake_get_llm
    )
    return holder


# ── 局部编辑 ─────────────────────────────────────────────

def test_transform_rewrite(api_client, fake_edit_model):
    response = api_client.post('/api/v1/writing/transform', json={
        'api_key': 'sk-test',
        'text': '他觉得有点冷。',
        'operation': 'rewrite',
        'instruction': '更克制一点',
        'surrounding_context': '冬天的夜里。',
        'provider': 'deepseek',
        'model': 'deepseek-v4-flash',
    })
    assert response.status_code == 200
    assert response.json()['data']['content'] == '改写后的文字'

    # 提示词里应带上任务、上下文与附加要求
    messages = fake_edit_model['model'].seen[0]
    user_content = messages[-1].content
    assert '重新表达所选原文' in user_content
    assert '冬天的夜里。' in user_content
    assert '更克制一点' in user_content


def test_transform_validation(api_client, fake_edit_model):
    cases = [
        ({'text': '内容', 'operation': 'nope'}, '不支持的局部处理方式'),
        ({'text': '   ', 'operation': 'rewrite'}, '请先选择需要处理的文字'),
        ({'text': '字' * 12001, 'operation': 'rewrite'}, '单次处理的选中文字不能超过12000字'),
        ({'text': '内容', 'operation': 'rewrite', 'api_key': ''}, '请输入API密钥'),
        (
            {'text': '内容', 'operation': 'rewrite', 'provider': 'openai',
             'model': 'deepseek-v4-flash'},
            '所选模型与提供商不匹配',
        ),
    ]
    for overrides, expected in cases:
        body = {'api_key': 'sk-test', 'text': '内容', 'operation': 'rewrite',
                'provider': 'deepseek', 'model': 'deepseek-v4-flash'}
        body.update(overrides)
        response = api_client.post('/api/v1/writing/transform', json=body)
        assert response.status_code == 400, overrides
        assert response.json()['error'] == expected


# ── 文件解析 ─────────────────────────────────────────────

def test_extract_text_utf8(api_client):
    content = '这是前置文章的正文。'.encode('utf-8')
    response = api_client.post(
        '/api/v1/writing/extract-text',
        files={'file': ('chapter.txt', content, 'text/plain')},
    )
    assert response.status_code == 200
    data = response.json()['data']
    assert data['text'] == '这是前置文章的正文。'
    assert data['char_count'] == len('这是前置文章的正文。')
    assert data['filename'] == 'chapter.txt'


def test_extract_text_gb18030_fallback(api_client):
    content = '中文编码测试'.encode('gb18030')
    response = api_client.post(
        '/api/v1/writing/extract-text',
        files={'file': ('gbk.txt', content, 'text/plain')},
    )
    assert response.status_code == 200
    assert response.json()['data']['text'] == '中文编码测试'


def test_extract_text_rejects_unsupported_extension(api_client):
    response = api_client.post(
        '/api/v1/writing/extract-text',
        files={'file': ('a.pdf', b'%PDF-1.4', 'application/pdf')},
    )
    assert response.status_code == 400
    assert response.json()['error'] == '仅支持 .txt、.doc、.docx 文件'


def test_extract_text_rejects_oversize(api_client):
    big = b'a' * (10 * 1024 * 1024 + 1)
    response = api_client.post(
        '/api/v1/writing/extract-text',
        files={'file': ('big.txt', big, 'text/plain')},
    )
    assert response.status_code == 413
    assert '10 MB' in response.json()['error']


def test_extract_text_rejects_empty(api_client):
    response = api_client.post(
        '/api/v1/writing/extract-text',
        files={'file': ('empty.txt', b'   ', 'text/plain')},
    )
    assert response.status_code == 400
    assert response.json()['error'] == '文件中没有可读取的文本内容'


# ── 统一入口 ─────────────────────────────────────────────

def _events(response_text: str) -> list[tuple[str, dict]]:
    events: list[tuple[str, dict]] = []
    current = None
    for line in response_text.splitlines():
        if line.startswith('event: '):
            current = line[len('event: '):].strip()
        elif line.startswith('data: ') and current:
            try:
                events.append((current, json.loads(line[len('data: '):])))
            except json.JSONDecodeError:
                events.append((current, {}))
            current = None
    return events


def test_pre_filter_never_calls_model(api_client, monkeypatch):
    called = {'n': 0}

    async def boom(*args, **kwargs):
        called['n'] += 1
        raise AssertionError('前置拦截命中时不应调用模型')

    monkeypatch.setattr('backend.api.v1.chat.llm_route', boom)
    with api_client.stream('POST', '/api/v1/chat/stream', json={
        'session_id': 's1', 'message': '你好',
    }) as response:
        text = ''.join(response.iter_text())

    events = _events(text)
    assert events[0][0] == 'token'
    assert '写作助手' in events[0][1]['data']
    assert called['n'] == 0


def test_rule_route_detects_writing_and_consistency(api_client):
    with api_client.stream('POST', '/api/v1/chat/stream', json={
        'session_id': 's1', 'message': '帮我检查这段有没有前后矛盾',
    }) as response:
        text = ''.join(response.iter_text())
    events = _events(text)
    decision = next(item for item in events if item[0] == 'routing_decision')
    assert decision[1]['agent_type'] == 'consistency'
    guidance = next(item for item in events if item[0] == 'guidance')
    assert '一致性审查' in guidance[1]['message']


def test_chat_writing_without_payload_gives_guidance(api_client):
    with api_client.stream('POST', '/api/v1/chat/stream', json={
        'session_id': 's1', 'message': '帮我写一段开头',
    }) as response:
        text = ''.join(response.iter_text())
    events = _events(text)
    decision = next(item for item in events if item[0] == 'routing_decision')
    assert decision[1]['agent_type'] == 'writing'
    guidance = next(item for item in events if item[0] == 'guidance')
    assert 'API Key' in guidance[1]['message']


def test_chat_writing_dispatches_to_graph(api_client, monkeypatch):
    """带完整写作参数的对话应真正跑图并出正文。"""
    template = api_client.post('/api/v1/templates', json={
        'name': '人物', 'category': 'character', 'content': '人物：雨生',
    }).json()['data']

    class FakeChunk:
        def __init__(self, content, finish=None):
            self.content = content
            self.additional_kwargs = {}
            self.response_metadata = {'finish_reason': finish} if finish else {}

    class StreamingModel:
        async def astream(self, messages):
            yield FakeChunk('开')
            yield FakeChunk('头')
            yield FakeChunk('', 'stop')

        async def ainvoke(self, messages):
            return FakeChunk('开头', 'stop')

    monkeypatch.setattr(
        'backend.agents.writing.nodes._build_model', lambda state: StreamingModel()
    )

    with api_client.stream('POST', '/api/v1/chat/stream', json={
        'session_id': 's1',
        'message': '帮我写一段开头',
        'context': {'payload': {
            'api_key': 'sk-test',
            'provider': 'deepseek',
            'model': 'deepseek-v4-flash',
            'template_ids': [template['id']],
        }},
    }) as response:
        text = ''.join(response.iter_text())

    events = _events(text)
    kinds = [name for name, _ in events]
    assert 'routing_decision' in kinds
    assert 'token' in kinds
    assert 'complete' in kinds
    complete = next(payload for name, payload in events if name == 'complete')
    assert complete['data']['final_content'] == '开头'
