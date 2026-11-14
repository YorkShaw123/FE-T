"""P1 Style Card 与参考片段路由测试。

模型调用被替换成固定返回值，所以整条链路（校验 → 落库 → 片段管理）
都能在离线状态下验证；这里不关心模型说什么，只关心系统怎么处理它。
"""

from __future__ import annotations

import json

import pytest

EXAMPLE_TEXT = '这是一段用于测试的范例文章，用来验证风格分析与片段切分。' * 20


def _card(summary: str = '短句叙事，留白偏多') -> dict:
    return {
        'summary': summary,
        'narration': {'person': '第三人称', 'distance': '贴近', 'tense': '过去', 'pov_rules': []},
        'rhythm': {'sentence_pattern': '短句为主', 'paragraph_pattern': '段落短', 'transition_style': '留白'},
        'language': {'register': '口语', 'imagery': '具体', 'rhetoric_frequency': '低',
                     'preferred_behaviors': []},
        'dialogue': {'ratio': '中等', 'length': '短', 'subtext': '多', 'tag_style': '少'},
        'description_balance': {'action': '多', 'dialogue': '中', 'psychology': '少', 'environment': '少'},
        'avoid': ['然而', '此外'],
        'checkable_rules': [
            {'id': 'r1', 'rule': '不要使用“然而”', 'priority': 'hard'},
            {'rule': '每段不超过四句', 'priority': 'medium'},
        ],
    }


@pytest.fixture()
def fake_model(monkeypatch):
    """替换模型调用：默认返回合法 Style Card，可切换成坏数据。"""
    calls: list[dict] = []
    state = {'mode': 'card', 'payload': _card()}

    async def fake_call(**kwargs):
        calls.append(kwargs)
        if state['mode'] == 'card':
            return {'content': json.dumps(state['payload'], ensure_ascii=False), 'reasoning_content': ''}
        if state['mode'] == 'items':
            return {'content': json.dumps(state['payload'], ensure_ascii=False), 'reasoning_content': ''}
        return {'content': '这不是 JSON', 'reasoning_content': ''}

    monkeypatch.setattr('backend.services.style_profile_service._call_model', fake_call)
    monkeypatch.setattr('backend.services.style_excerpt_service._call_model', fake_call)
    state['calls'] = calls
    return state


def _create_example_template(client) -> int:
    response = client.post('/api/v1/templates', json={
        'name': '测试范例',
        'category': 'example',
        'content': EXAMPLE_TEXT,
        'style_strength': 'medium',
    })
    assert response.status_code == 201
    return response.json()['data']['id']


def _analyze(client, template_id: int):
    return client.post(f'/api/v1/style/{template_id}/analyze', json={
        'api_key': 'sk-test',
        'provider': 'deepseek',
        'model': 'deepseek-v4-flash',
    })


def test_profile_missing_shape(api_client):
    template_id = _create_example_template(api_client)
    body = api_client.get(f'/api/v1/style/{template_id}').json()
    assert body['data'] == {
        'template_id': template_id,
        'analysis_status': 'missing',
        'is_stale': False,
        'card': None,
        'is_primary': False,
    }


def test_profile_unknown_template_returns_404(api_client):
    response = api_client.get('/api/v1/style/9999')
    assert response.status_code == 404
    assert response.json() == {'success': False, 'error': '模板不存在'}


def test_analyze_success(api_client, fake_model):
    template_id = _create_example_template(api_client)
    response = _analyze(api_client, template_id)
    assert response.status_code == 200
    data = response.json()['data']
    assert data['analysis_status'] == 'ready'
    assert data['card']['summary'] == '短句叙事，留白偏多'
    assert data['card']['schema_version'] == 1
    assert data['card']['checkable_rules'][0]['priority'] == 'hard'
    # 未写 priority 的规则会被补成 medium
    assert data['card']['checkable_rules'][1]['priority'] == 'medium'
    assert fake_model['calls'][0]['agent_type'] == 'style_card'


def test_analyze_requires_example_category(api_client, fake_model):
    response = api_client.post('/api/v1/templates', json={
        'name': '人物模板', 'category': 'character', 'content': '人物设定',
    })
    template_id = response.json()['data']['id']
    result = _analyze(api_client, template_id)
    assert result.status_code == 400
    assert result.json()['error'] == '只有范例文章模板可以生成 Style Card'


def test_analyze_requires_api_key(api_client, fake_model):
    template_id = _create_example_template(api_client)
    result = api_client.post(f'/api/v1/style/{template_id}/analyze', json={'api_key': ''})
    assert result.status_code == 400
    assert result.json()['error'] == '请先输入 API 密钥'


def test_analyze_bad_json_marks_error(api_client, fake_model):
    template_id = _create_example_template(api_client)
    fake_model['mode'] = 'broken'
    result = _analyze(api_client, template_id)
    assert result.status_code == 400
    profile = api_client.get(f'/api/v1/style/{template_id}').json()['data']
    assert profile['analysis_status'] == 'error'


def test_save_and_restore_card(api_client, fake_model):
    template_id = _create_example_template(api_client)
    _analyze(api_client, template_id)

    edited = _card('人工改过的摘要')
    saved = api_client.put(f'/api/v1/style/{template_id}', json={'card': edited, 'is_primary': True})
    assert saved.status_code == 200
    assert saved.json()['data']['card']['summary'] == '人工改过的摘要'
    assert saved.json()['data']['is_primary'] is True

    restored = api_client.post(f'/api/v1/style/{template_id}/restore')
    assert restored.status_code == 200
    assert restored.json()['data']['card']['summary'] == '短句叙事，留白偏多'


def test_save_card_without_analysis_is_rejected(api_client, fake_model):
    template_id = _create_example_template(api_client)
    response = api_client.put(f'/api/v1/style/{template_id}', json={'card': _card()})
    assert response.status_code == 400
    assert response.json()['error'] == '请先分析该范例文章'


def test_rebuild_excerpts(api_client, fake_model):
    template_id = _create_example_template(api_client)
    _analyze(api_client, template_id)

    fake_model['mode'] = 'items'
    fake_model['payload'] = {
        'items': [
            {
                'index': 0,
                'scene_type': 'narration',
                'pov': '第三人称',
                'emotion': '平静、克制',
                'pace': 'medium',
                'tags': ['测试', '范例'],
                'functions': ['铺垫'],
            }
        ]
    }
    response = api_client.post(f'/api/v1/style/{template_id}/excerpts/rebuild', json={
        'api_key': 'sk-test',
    })
    assert response.status_code == 200
    data = response.json()['data']
    assert len(data) == 1
    assert data[0]['scene_type'] == 'narration'
    assert data[0]['tags'] == ['测试', '范例']
    assert data[0]['dialogue_ratio'] == 0

    listed = api_client.get(f'/api/v1/style/{template_id}/excerpts').json()['data']
    assert [item['id'] for item in listed] == [data[0]['id']]


def test_rebuild_requires_ready_card(api_client, fake_model):
    template_id = _create_example_template(api_client)
    response = api_client.post(f'/api/v1/style/{template_id}/excerpts/rebuild', json={
        'api_key': 'sk-test',
    })
    assert response.status_code == 400
    assert response.json()['error'] == '请先生成有效的 Style Card'


def test_update_and_delete_excerpt(api_client, fake_model):
    template_id = _create_example_template(api_client)
    _analyze(api_client, template_id)
    fake_model['mode'] = 'items'
    fake_model['payload'] = {'items': [{'index': 0, 'scene_type': 'dialogue', 'pace': 'fast'}]}
    excerpt_id = api_client.post(
        f'/api/v1/style/{template_id}/excerpts/rebuild', json={'api_key': 'sk-test'}
    ).json()['data'][0]['id']

    updated = api_client.put(
        f'/api/v1/style/{template_id}/excerpts/{excerpt_id}',
        json={'scene_type': 'psychology', 'is_pinned': True, 'tags': ['改过']},
    ).json()['data']
    assert updated['scene_type'] == 'psychology'
    assert updated['is_pinned'] is True
    assert updated['tags'] == ['改过']

    assert api_client.delete(
        f'/api/v1/style/{template_id}/excerpts/{excerpt_id}'
    ).json() == {'success': True}
    assert api_client.get(f'/api/v1/style/{template_id}/excerpts').json()['data'] == []


def test_legacy_style_paths(api_client, fake_model):
    template_id = _create_example_template(api_client)
    _analyze(api_client, template_id)
    legacy = api_client.get(f'/api/style-profiles/{template_id}').json()
    modern = api_client.get(f'/api/v1/style/{template_id}').json()
    assert legacy == modern


def test_split_reference_text_regroups_paragraphs():
    from backend.services.style_excerpt_service import split_reference_text

    text = '\n\n'.join(['第一段内容' * 20, '第二段内容' * 20, '第三段内容' * 20])
    chunks = split_reference_text(text)
    assert len(chunks) >= 1
    assert all(len(chunk) <= 1000 for chunk in chunks)
    assert ''.join(chunks).replace('\n', '') == text.replace('\n', '')
