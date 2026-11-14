"""P3 语料库路由测试。

覆盖 15 个端点的关键路径：CRUD、导入切片、本地索引、清空、检索测试。
导入与索引的顺序问题（先删 FTS 再删主表）靠"导入两次不炸"来验证。
"""

from __future__ import annotations

SAMPLE_TEXT = (
    '夜色沉了下来，雨水敲打窗棂。他推开门，看见满屋子的灰尘在光柱里浮动。\n\n'
    '她站在窗边，没有回头，只问了一句：你要走了吗。\n\n'
    '他没有立刻回答。风从门缝里钻进来，把桌上的纸吹得哗哗响。\n\n'
    '远处传来狗叫，很快又安静下来。\n\n'
)


def _create(client, name='测试语料'):
    response = client.post('/api/v1/corpora', json={'name': name, 'description': '说明'})
    assert response.status_code == 201, response.text
    return response.json()['data']


def _import(client, corpus_id, text=SAMPLE_TEXT, filename='sample.txt'):
    return client.post(
        f'/api/v1/corpora/{corpus_id}/import',
        files={'file': (filename, text.encode('utf-8'), 'text/plain')},
    )


# ── CRUD ─────────────────────────────────────────────────

def test_corpus_crud(api_client):
    created = _create(api_client)
    assert created['name'] == '测试语料'
    assert created['index_status'] == 'empty'

    listing = api_client.get('/api/v1/corpora').json()['data']
    assert [item['id'] for item in listing] == [created['id']]

    updated = api_client.put(
        f"/api/v1/corpora/{created['id']}", json={'name': '改名后'}
    ).json()['data']
    assert updated['name'] == '改名后'
    assert updated['description'] == '说明'  # 未传的字段保持原值

    assert api_client.delete(f"/api/v1/corpora/{created['id']}").json() == {'success': True}
    assert api_client.get('/api/v1/corpora').json()['data'] == []


def test_create_corpus_requires_name(api_client):
    response = api_client.post('/api/v1/corpora', json={'name': '   '})
    assert response.status_code == 400
    assert response.json()['error'] == '语料库名称不能为空'


def test_get_missing_corpus_returns_404(api_client):
    response = api_client.get('/api/v1/corpora/9999')
    assert response.status_code == 404
    assert response.json()['error'] == '语料库不存在'


# ── 导入与切片 ───────────────────────────────────────────

def test_import_splits_and_tags(api_client):
    corpus = _create(api_client)
    body = _import(api_client, corpus['id']).json()['data']
    assert body['chunk_count'] >= 1
    assert body['total_chars'] == len(SAMPLE_TEXT.strip())
    assert body['corpus']['index_status'] == 'imported'

    chunks = api_client.get(f"/api/v1/corpora/{corpus['id']}/chunks").json()['data']
    assert chunks['total'] == body['chunk_count']
    first = chunks['items'][0]
    assert first['scene_type'] in {
        'dialogue', 'action', 'psychology', 'environment',
        'transition', 'narration', 'mixed',
    }
    assert first['char_count'] > 0


def test_reimport_replaces_chunks_without_fts_conflict(api_client):
    """连续导入两次不应因为 FTS rowid 冲突而失败。"""
    corpus = _create(api_client)
    _import(api_client, corpus['id'])
    second = _import(api_client, corpus['id'])
    assert second.status_code == 200
    chunks = api_client.get(f"/api/v1/corpora/{corpus['id']}/chunks").json()['data']
    assert chunks['total'] == second.json()['data']['chunk_count']


def test_import_rejects_unsupported_file(api_client):
    corpus = _create(api_client)
    response = api_client.post(
        f"/api/v1/corpora/{corpus['id']}/import",
        files={'file': ('a.pdf', b'%PDF', 'application/pdf')},
    )
    assert response.status_code == 400
    assert '仅支持' in response.json()['error']


# ── 索引 ─────────────────────────────────────────────────

def test_index_marks_signature_version(api_client):
    corpus = _create(api_client)
    _import(api_client, corpus['id'])
    body = api_client.post(f"/api/v1/corpora/{corpus['id']}/index").json()['data']
    assert body['indexed_count'] >= 1
    assert body['corpus']['index_status'] == 'indexed'
    assert body['corpus']['signature_version'] == 1
    assert body['corpus']['embedding_backend'] == 'local-feature'
    assert '未生成语义向量' in body['note']

    progress = api_client.get(
        f"/api/v1/corpora/{corpus['id']}/index-progress"
    ).json()['data']
    assert progress['status'] == 'completed'


def test_index_without_chunks_is_rejected(api_client):
    corpus = _create(api_client)
    response = api_client.post(f"/api/v1/corpora/{corpus['id']}/index")
    assert response.status_code == 400
    assert '还没有可索引的片段' in response.json()['error']


def test_clear_resets_corpus(api_client):
    corpus = _create(api_client)
    _import(api_client, corpus['id'])
    assert api_client.post(f"/api/v1/corpora/{corpus['id']}/clear").json() == {'success': True}
    detail = api_client.get(f"/api/v1/corpora/{corpus['id']}").json()['data']
    assert detail['chunk_count'] == 0
    assert detail['index_status'] == 'empty'


# ── 检索测试 ─────────────────────────────────────────────

def test_search_returns_matching_chunk(api_client):
    corpus = _create(api_client)
    _import(api_client, corpus['id'])
    body = api_client.post('/api/v1/corpora/search', json={
        'query_text': '雨水敲打窗棂',
        'corpus_ids': [corpus['id']],
        'top_k': 1,
    }).json()['data']
    assert body['items']
    assert '雨水' in body['items'][0]['content']
    assert 'lexical' in body['meta']['signals']


def test_search_after_delete_returns_empty(api_client):
    corpus = _create(api_client)
    _import(api_client, corpus['id'])
    api_client.delete(f"/api/v1/corpora/{corpus['id']}")
    body = api_client.post('/api/v1/corpora/search', json={
        'query_text': '雨水', 'corpus_ids': [corpus['id']],
    }).json()['data']
    assert body['items'] == []
    assert body['meta']['mode'] == 'empty'


# ── Embedding 配置 ───────────────────────────────────────

def test_embedding_config_and_status(api_client):
    config = api_client.get('/api/v1/corpora/embedding-config').json()['data']
    assert config['model'] == 'BAAI/bge-m3'
    assert config['dimensions'] == 1024
    assert config['local']['model'].endswith('bge-small-zh-v1.5')

    status = api_client.get('/api/v1/corpora/embedding/status').json()['data']
    assert 'installed' in status
    assert 'message' in status

    install = api_client.post('/api/v1/corpora/embedding/install').json()['data']
    assert install['started'] is False

    progress = api_client.get('/api/v1/corpora/embedding/install-progress').json()['data']
    assert progress['status'] == 'manual'


# ── 旧路径 ───────────────────────────────────────────────

def test_legacy_corpus_paths(api_client):
    corpus = _create(api_client)
    legacy = api_client.get('/api/style-corpora').json()
    modern = api_client.get('/api/v1/corpora').json()
    assert legacy == modern

    detail = api_client.get(f"/api/style-corpora/{corpus['id']}").json()
    assert detail['data']['id'] == corpus['id']
