"""P1 模板与工作模式路由测试。

覆盖点：
1. 十三个模板端点在 ``/api/v1/templates/*`` 与旧 ``/api/templates/*`` 双轨可达；
2. 版本控制语义（改内容生成新版本、旧版本非活跃、可恢复）；
3. 导出两种格式、导入去重、示例模板补齐；
4. 错误形状与旧 Flask 版本一致（404 模板不存在、400 名称为空）；
5. 工作模式列表与占位生成接口返回 501。
"""

from __future__ import annotations

import json

TEMPLATE_PAYLOAD = {
    'name': '测试人物',
    'category': 'character',
    'content': '人物姓名：测试\n性格：谨慎',
    'description': '用于路由测试',
    'style_strength': 'light',
}


def _create(client, payload=None):
    body = dict(TEMPLATE_PAYLOAD)
    if payload:
        body.update(payload)
    response = client.post('/api/v1/templates', json=body)
    assert response.status_code == 201, response.text
    return response.json()['data']


def test_create_and_get_template(api_client):
    created = _create(api_client)
    assert created['name'] == '测试人物'
    assert created['version'] == 1
    assert created['is_active'] is True

    fetched = api_client.get(f"/api/v1/templates/{created['id']}")
    assert fetched.status_code == 200
    assert fetched.json()['data']['content'].startswith('人物姓名：测试')


def test_list_and_grouped(api_client):
    first = _create(api_client)
    second = _create(api_client, {'name': '测试剧情', 'category': 'plot', 'content': '剧情梗概'})

    listing = api_client.get('/api/v1/templates')
    assert listing.status_code == 200
    ids = {item['id'] for item in listing.json()['data']}
    assert {first['id'], second['id']} <= ids

    grouped = api_client.get('/api/v1/templates/grouped')
    assert grouped.status_code == 200
    data = grouped.json()['data']
    assert set(data) == {'character', 'background', 'plot', 'example', 'constraint'}
    assert any(item['id'] == first['id'] for item in data['character'])
    assert any(item['id'] == second['id'] for item in data['plot'])


def test_update_content_creates_new_version(api_client):
    created = _create(api_client)
    updated = api_client.put(
        f"/api/v1/templates/{created['id']}",
        json={'content': '人物姓名：测试\n性格：谨慎、寡言'},
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body['is_new_version'] is True
    assert body['data']['version'] == 2
    assert body['data']['parent_id'] == created['id']

    # 列表里只保留最新版：原 id 不再出现，新 id 出现
    listing = api_client.get('/api/v1/templates').json()['data']
    listed_ids = {item['id'] for item in listing}
    assert body['data']['id'] in listed_ids
    assert created['id'] not in listed_ids

    history = api_client.get(f"/api/v1/templates/{created['id']}/versions").json()['data']
    assert {item['version'] for item in history} == {1, 2}


def test_update_metadata_does_not_create_version(api_client):
    created = _create(api_client)
    updated = api_client.put(
        f"/api/v1/templates/{created['id']}",
        json={'description': '只改说明'},
    ).json()
    assert updated['is_new_version'] is False
    assert updated['data']['version'] == 1


def test_restore_version(api_client):
    created = _create(api_client)
    second = api_client.put(
        f"/api/v1/templates/{created['id']}",
        json={'content': '第二版内容'},
    ).json()['data']

    restored = api_client.post(
        f"/api/v1/templates/{second['id']}/versions/{created['id']}/restore"
    )
    assert restored.status_code == 200
    body = restored.json()['data']
    assert body['version'] == 3
    assert body['content'] == TEMPLATE_PAYLOAD['content']


def test_toggle_and_delete(api_client):
    created = _create(api_client)
    toggled = api_client.post(f"/api/v1/templates/{created['id']}/toggle").json()['data']
    assert toggled['is_active'] is False

    assert api_client.delete(f"/api/v1/templates/{created['id']}").json() == {'success': True}
    assert api_client.get(f"/api/v1/templates/{created['id']}").status_code == 404


def test_delete_all(api_client):
    _create(api_client)
    assert api_client.delete('/api/v1/templates').json() == {'success': True, 'deleted': True}
    assert api_client.get('/api/v1/templates').json()['data'] == []


def test_export_json_and_markdown(api_client):
    _create(api_client)

    json_export = api_client.post('/api/v1/templates/export', json={'format': 'json'})
    assert json_export.status_code == 200
    assert json_export.headers['content-type'].startswith('application/json')
    payload = json.loads(json_export.text)
    assert payload['version'] == '1.0'
    names = [item['name'] for item in payload['templates']]
    assert '测试人物' in names

    markdown = api_client.post('/api/v1/templates/export', json={'format': 'markdown'})
    assert markdown.status_code == 200
    assert '## 人物设定' in markdown.text
    assert '### 测试人物' in markdown.text


def test_import_skips_duplicates(api_client):
    _create(api_client)
    payload = {
        'templates': [
            {
                'name': TEMPLATE_PAYLOAD['name'],
                'category': TEMPLATE_PAYLOAD['category'],
                'content': TEMPLATE_PAYLOAD['content'],
            },
            {'name': '新增模板', 'category': 'constraint', 'content': '约束内容'},
        ]
    }
    response = api_client.post('/api/v1/templates/import', json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body['imported'] == 1
    assert body['skipped'] == 1


def test_starter_templates_seeded_on_first_boot(api_client):
    listing = api_client.get('/api/v1/templates').json()['data']
    names = {item['name'] for item in listing}
    assert '示例人物：雨生' in names
    assert '示例剧情：草木知春' in names


def test_starter_endpoint_is_idempotent(api_client):
    first = api_client.post('/api/v1/templates/starter').json()
    second = api_client.post('/api/v1/templates/starter').json()
    assert first['created'] == 0  # 启动时已写入
    assert second['created'] == 0


def test_error_shapes(api_client):
    missing = api_client.get('/api/v1/templates/9999')
    assert missing.status_code == 404
    assert missing.json() == {'success': False, 'error': '模板不存在'}

    empty_name = api_client.post('/api/v1/templates', json={'name': '  ', 'content': 'x'})
    assert empty_name.status_code == 400
    assert empty_name.json() == {'success': False, 'error': '模板名称不能为空'}


def test_legacy_paths_still_work(api_client):
    """迁移期旧路径必须是同一份实现，而不是复制品。"""
    created = _create(api_client)
    legacy_list = api_client.get('/api/templates').json()
    v1_list = api_client.get('/api/v1/templates').json()
    assert legacy_list == v1_list

    legacy_one = api_client.get(f"/api/templates/{created['id']}").json()
    assert legacy_one['data']['id'] == created['id']

    legacy_versions = api_client.get(f"/api/templates/{created['id']}/versions").json()
    assert legacy_versions['success'] is True


def test_modes_endpoints(api_client):
    listing = api_client.get('/api/v1/modes').json()
    assert listing['success'] is True
    ids = [item['id'] for item in listing['data']['modes']]
    assert ids == ['novel', 'marketing']

    novel = api_client.get('/api/v1/modes/novel').json()['data']
    assert novel['name'] == '小说创作'
    assert novel['enabled'] is True
    assert isinstance(novel['categories'], list)

    assert api_client.get('/api/v1/modes/unknown').status_code == 404

    placeholder = api_client.post('/api/v1/modes/novel/generate', json={})
    assert placeholder.status_code == 501
    assert '尚未实现' in placeholder.json()['error']

    # 旧路径同样可达
    assert api_client.get('/api/modes').json() == listing
