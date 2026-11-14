"""P2 写作图与写作路由测试。

模型被替换成假实现，所以整张图（组装 → 预算 → 初稿 → 去味 → 检索 → 改写 →
定稿 → 落库）都能离线跑通，流式与非流式共用同一张图这一设计也被直接验证。
"""

from __future__ import annotations

import json

import pytest


class FakeChunk:
    def __init__(self, content: str, finish: str | None = None):
        self.content = content
        self.additional_kwargs = {}
        self.response_metadata = {'finish_reason': finish} if finish else {}


class FakeModel:
    """按调用顺序依次返回预设文本，并把每次调用切成两段模拟流式。"""

    def __init__(self, texts: list[str]):
        self.texts = list(texts)
        self.calls = 0

    def _next(self) -> str:
        text = self.texts[min(self.calls, len(self.texts) - 1)]
        self.calls += 1
        return text

    async def ainvoke(self, messages):
        return FakeChunk(self._next(), 'stop')

    async def astream(self, messages):
        text = self._next()
        middle = max(1, len(text) // 2)
        for piece in (text[:middle], text[middle:]):
            if piece:
                yield FakeChunk(piece)
        yield FakeChunk('', 'stop')


@pytest.fixture()
def fake_model(monkeypatch):
    """把写作图的模型接缝换成假实现；调用方可以改写 .texts。"""
    state = {'texts': ['初稿正文。', '去味后的正文。', '风格改写后的正文。'], 'model': None}

    def builder(_state):
        if state['model'] is None or state['model'].calls >= len(state['texts']):
            state['model'] = FakeModel(state['texts'])
        return state['model']

    monkeypatch.setattr('backend.agents.writing.nodes._build_model', builder)
    return state


def _create_template(client, *, name='人物', category='character', content='人物：雨生'):
    response = client.post('/api/v1/templates', json={
        'name': name, 'category': category, 'content': content,
    })
    assert response.status_code == 201
    return response.json()['data']['id']


def _payload(template_id: int, **overrides):
    body = {
        'api_key': 'sk-test',
        'provider': 'deepseek',
        'model': 'deepseek-v4-flash',
        'template_ids': [template_id],
        'title': '测试生成',
    }
    body.update(overrides)
    return body


# ── 元信息 ───────────────────────────────────────────────

def test_models_endpoint_shape(api_client):
    body = api_client.get('/api/v1/writing/models').json()
    assert body['success'] is True
    assert 'deepseek' in body['data']
    assert body['data']['deepseek']['models'][0]['id'] == 'deepseek-v4-flash'
    assert 'sampling' in body['data']['deepseek']


def test_categories_and_default_deai_prompt(api_client):
    categories = api_client.get('/api/v1/writing/categories').json()['data']
    assert [item['id'] for item in categories] == [
        'character', 'background', 'plot', 'example', 'constraint',
    ]
    deai = api_client.get('/api/v1/writing/deai-prompt').json()['data']
    assert '去除AI写作风格' in deai


def test_legacy_meta_paths(api_client):
    assert api_client.get('/api/generation/models').json() == api_client.get(
        '/api/v1/writing/models'
    ).json()
    assert api_client.get('/api/generation/categories').json() == api_client.get(
        '/api/v1/writing/categories'
    ).json()


# ── 预览 ─────────────────────────────────────────────────

def test_preview_shape(api_client, fake_model):
    template_id = _create_template(api_client)
    body = api_client.post('/api/v1/writing/preview', json=_payload(template_id)).json()
    data = body['data']
    # 前端读取的键一个不少
    for key in (
        'assembled_prompt', 'messages', 'prompt_mode', 'message_count',
        'template_count', 'char_count', 'token_budget', 'style_mode',
        'style_metadata', 'style_reference_plan',
    ):
        assert key in data, key
    assert '人物：雨生' in data['assembled_prompt']
    assert data['template_count'] == 1
    assert data['token_budget']['status'] == 'safe'


def test_preview_structured_route(api_client, fake_model):
    template_id = _create_template(api_client)
    data = api_client.post('/api/v1/writing/preview', json=_payload(
        template_id, structured_prompt_enabled=True,
    )).json()['data']
    assert data['prompt_mode'] == 'structured'
    assert data['message_count'] >= 3
    assert data['messages'][0]['role'] == 'system'


def test_preview_smart_route_reports_fallback(api_client, fake_model):
    template_id = _create_template(api_client)
    data = api_client.post('/api/v1/writing/preview', json=_payload(
        template_id, style_mode='smart',
    )).json()['data']
    assert data['style_mode'] == 'smart_fallback_legacy'
    assert 'P3' in data['style_metadata']['fallback_reason']


# ── 生成 ─────────────────────────────────────────────────

def test_generate_saves_record_and_returns_payload(api_client, fake_model):
    template_id = _create_template(api_client)
    response = api_client.post('/api/v1/writing/generate', json=_payload(template_id))
    assert response.status_code == 200
    data = response.json()['data']

    assert data['first_content'] == '初稿正文。'
    assert data['final_content'] == '初稿正文。'
    assert data['record_id']

    saved = api_client.get(f"/api/v1/records/{data['record_id']}").json()['data']
    assert saved['content'] == '初稿正文。'
    assert saved['title'] == '测试生成'


def test_generate_requires_template(api_client, fake_model):
    response = api_client.post('/api/v1/writing/generate', json=_payload(1, template_ids=[]))
    assert response.status_code == 400
    assert response.json()['error'] == '请至少启用一个提示词模板'


def test_generate_requires_api_key(api_client, fake_model):
    template_id = _create_template(api_client)
    response = api_client.post('/api/v1/writing/generate', json=_payload(
        template_id, api_key='  ',
    ))
    assert response.status_code == 400
    assert response.json()['error'] == '请输入API密钥'


def test_generate_with_deai_uses_second_pass(api_client, fake_model):
    template_id = _create_template(api_client)
    data = api_client.post('/api/v1/writing/generate', json=_payload(
        template_id, deai_enabled=True, deai_prompt='去掉书面腔',
    )).json()['data']
    assert data['first_content'] == '初稿正文。'
    assert data['deai_content'] == '去味后的正文。'
    assert data['final_content'] == '去味后的正文。'


def test_budget_over_aborts_without_record(api_client, fake_model, monkeypatch):
    from backend.agents.writing import nodes

    def over_budget(*args, **kwargs):
        return {
            'estimated': True,
            'status': 'over',
            'blocking_phase': 'primary',
            'phases': {'primary': {'remaining_tokens': -100, 'context_window': 1000}},
        }

    monkeypatch.setattr(nodes, 'calculate_token_budget', over_budget)
    template_id = _create_template(api_client)

    response = api_client.post('/api/v1/writing/generate', json=_payload(template_id))
    assert response.status_code == 400
    assert '超出模型限制' in response.json()['error']

    # 图在预算处中止，不产生记录
    assert api_client.get('/api/v1/records').json()['data']['total'] == 0


# ── 流式 ─────────────────────────────────────────────────

def test_stream_event_sequence(api_client, fake_model):
    template_id = _create_template(api_client)
    with api_client.stream(
        'POST', '/api/v1/writing/generate-stream', json=_payload(template_id)
    ) as response:
        assert response.status_code == 200
        text = ''.join(response.iter_text())

    events = [
        line.split('event: ')[1].strip()
        for line in text.splitlines()
        if line.startswith('event: ')
    ]
    assert events[0] == 'status'
    assert 'token_budget' in events
    assert 'token' in events
    assert 'complete' in events
    assert events[-1] == 'done'

    complete_line = next(
        line for line in text.splitlines() if line.startswith('data: ') and '"record_id"' in line
    )
    payload = json.loads(complete_line[len('data: '):])
    assert payload['data']['first_content'] == '初稿正文。'
    assert payload['data']['record_id']


def test_stream_tokens_reassemble_to_full_text(api_client, fake_model):
    template_id = _create_template(api_client)
    with api_client.stream(
        'POST', '/api/v1/writing/generate-stream', json=_payload(template_id)
    ) as response:
        text = ''.join(response.iter_text())

    tokens = []
    for line in text.splitlines():
        if not line.startswith('data: '):
            continue
        try:
            payload = json.loads(line[len('data: '):])
        except json.JSONDecodeError:
            continue
        if payload.get('type') == 'token':
            tokens.append(payload.get('data', ''))
    assert ''.join(tokens) == '初稿正文。'
