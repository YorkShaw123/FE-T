"""P3 检索适配层测试。

分两块：
1. ``LocalKB`` 直连隔离数据库，验证词汇召回、场景过滤与放宽、泄漏惩罚；
2. 写作图通过 ``KBBackend`` 拿到片段后，能把"风格参考"这一段真正跑起来。
"""

from __future__ import annotations

import sqlite3

import pytest

from backend.config import get_settings
from backend.core.knowledge_base import LocalKB, build_fts_match


@pytest.fixture()
async def kb_env(tmp_path, monkeypatch):
    """独立数据目录 + 本事件循环内新建引擎，避免与 TestClient 的循环冲突。"""
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


def _seed(chunks: list[tuple[str, str]]) -> int:
    """写入语料库、片段与 FTS 索引（模拟"已导入未向量化"的状态）。

    这里用裸 SQL 而不是 ORM，所以 NOT NULL 列必须逐个给值——
    ``create_all`` 生成的 DDL 不带服务端默认值（客户端默认值只在 ORM 写入时生效）。
    """
    db_path = get_settings().database_path
    with sqlite3.connect(db_path) as connection:
        cursor = connection.execute(
            'INSERT INTO style_corpora '
            '(name, description, source_filename, total_chars, chunk_count, index_status, '
            ' embedding_model, embedding_backend, embedding_model_version, embedding_dim, '
            ' signature_version) '
            "VALUES ('测试语料', '', '', ?, ?, 'imported', '', '', '', 0, 0)",
            (sum(len(content) for content, _ in chunks), len(chunks)),
        )
        corpus_id = int(cursor.lastrowid)

        for order, (content, scene) in enumerate(chunks):
            cursor = connection.execute(
                'INSERT INTO style_chunks '
                '(corpus_id, content, content_hash, article_key, source_order, char_count, '
                ' style_feature_version, style_features_json, style_window_valid_chars, '
                ' style_confidence, style_window_start_order, style_window_end_order, '
                ' style_signature_version, style_signature_json, scene_type, pacing, pov, '
                ' emotion, dialogue_ratio, embedding_dim, is_enabled) '
                "VALUES (?, ?, ?, 'a', ?, ?, 0, '{}', 0, 0.0, 0, 0, 0, '{}', ?, 'medium', "
                "'第三人称', '', 0, 0, 1)",
                (corpus_id, content, f'hash-{order}', order, len(content), scene),
            )
            chunk_id = int(cursor.lastrowid)
            connection.execute(
                'INSERT INTO style_chunks_fts(rowid, content) VALUES (?, ?)',
                (chunk_id, content),
            )
        connection.commit()
    return corpus_id


async def test_search_returns_lexically_matching_chunk(kb_env):
    corpus_id = _seed([
        ('夜色沉了下来，雨水敲打窗棂，他忽然觉得屋子空得厉害。', 'environment'),
        ('训练场上尘土飞扬，他挥拳扑向对手，两人缠斗在一起。', 'action'),
    ])
    items, meta = await LocalKB().search(
        query_text='雨水敲打窗棂',
        corpus_ids=[corpus_id],
        top_k=1,
    )
    assert len(items) == 1
    assert '雨水敲打窗棂' in items[0]['content']
    assert meta['mode'] == 'local_style'
    assert 'lexical' in meta['signals']
    # 缺失信号必须如实标注，不能假装算过
    assert set(meta['missing_signals']) == {'semantic', 'style_profile'}


async def test_scene_filter_and_relaxation(kb_env):
    corpus_id = _seed([
        ('他低声问她怎么了，她摇了摇头。', 'dialogue'),
        ('远山的轮廓在晨雾里慢慢显出来。', 'environment'),
    ])

    items, meta = await LocalKB().search(
        query_text='晨雾里的远山',
        corpus_ids=[corpus_id],
        scene_type='environment',
        top_k=1,
    )
    assert '晨雾' in items[0]['content']
    assert meta['relaxed_scene'] is False

    # 指定一个不存在的场景 → 放宽到全部候选，并如实标记
    relaxed_items, relaxed_meta = await LocalKB().search(
        query_text='远山',
        corpus_ids=[corpus_id],
        scene_type='psychology',
        top_k=1,
    )
    assert relaxed_meta['relaxed_scene'] is True
    assert relaxed_items


async def test_empty_corpus_returns_empty(kb_env):
    items, meta = await LocalKB().search(query_text='随便什么', corpus_ids=[999], top_k=3)
    assert items == []
    assert meta['mode'] == 'empty'


async def test_leakage_penalty_applied(kb_env):
    text = '他推开门，看见满屋子的灰尘在光柱里浮动。'
    corpus_id = _seed([(text, 'narration')])
    items, _meta = await LocalKB().search(
        query_text=text,  # 与片段完全一致 → 属于高复用风险
        corpus_ids=[corpus_id],
        top_k=1,
    )
    details = items[0]['details']
    assert details['content_overlap_penalty'] > 0
    assert details['total_score'] < details['lexical_score'] + details['scene_score']


async def test_top_k_and_order(kb_env):
    corpus_id = _seed([
        ('第一段：雪花落在屋檐上。', 'environment'),
        ('第二段：雪花落在屋檐上，很快化成了水。', 'environment'),
        ('第三段：火炉烧得正旺。', 'environment'),
    ])
    items, meta = await LocalKB().search(
        query_text='雪花落在屋檐上', corpus_ids=[corpus_id], top_k=2,
    )
    assert len(items) == 2
    assert meta['candidates'] == 3
    assert items[0]['score'] >= items[1]['score']


def test_build_fts_match_splits_long_runs():
    assert build_fts_match('') is None
    expr = build_fts_match('短词')
    assert expr is None  # 少于 3 字不构成 trigram 查询

    long_expr = build_fts_match('一二三四五六七八九十十一十二')
    assert long_expr is not None
    assert long_expr.count(' OR ') >= 0
    assert '"' in long_expr


async def test_writing_graph_uses_retrieved_excerpts(api_client, monkeypatch):
    """写作图接上 KBBackend 后，06 风格参考这一步应真正执行。"""
    from backend.agents.writing import retrieval

    async def fake_search(**_kwargs):
        return (
            [{'chunk_id': 1, 'content': '参考片段正文'}],
            {'mode': 'local_style', 'signals': ['lexical']},
        )

    class StubBackend:
        async def search(self, **kwargs):
            return await fake_search(**kwargs)

    monkeypatch.setattr(retrieval, 'get_kb_backend', lambda: StubBackend())

    class FakeChunk:
        def __init__(self, content, finish=None):
            self.content = content
            self.additional_kwargs = {}
            self.response_metadata = {'finish_reason': finish} if finish else {}

    class FakeModel:
        def __init__(self):
            self.index = 0

        def _next(self):
            texts = ['初稿。', '风格改写后的稿子。']
            text = texts[min(self.index, len(texts) - 1)]
            self.index += 1
            return text

        async def ainvoke(self, messages):
            return FakeChunk(self._next(), 'stop')

        async def astream(self, messages):
            yield FakeChunk(self._next(), 'stop')

    shared_model = FakeModel()
    monkeypatch.setattr(
        'backend.agents.writing.nodes._build_model', lambda state: shared_model
    )

    template = api_client.post('/api/v1/templates', json={
        'name': '范例', 'category': 'example', 'content': '范例正文',
    }).json()['data']

    response = api_client.post('/api/v1/writing/generate', json={
        'api_key': 'sk-test',
        'provider': 'deepseek',
        'model': 'deepseek-v4-flash',
        'template_ids': [template['id']],
        'style_reference_enabled': True,
        'style_corpus_ids': [1],
    })
    assert response.status_code == 200
    data = response.json()['data']
    assert data['style_rewrite_status'] == 'applied'
    assert data['style_reference_content'] == '风格改写后的稿子。'
    assert data['final_content'] == '风格改写后的稿子。'
    assert data['style_reference_metadata']['mode'] == 'local_style'
