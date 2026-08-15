import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = PROJECT_ROOT / 'server'
sys.path.insert(0, str(SERVER_DIR))
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from services.embedding_backends import (  # noqa: E402
    EmbeddingBackendUnavailable,
    LocalEmbeddingBackend,
    clear_embedding_session_cache,
    create_embedding_backend,
)
from app import create_app  # noqa: E402
from database import db  # noqa: E402
from database.models import StyleChunk, StyleCorpus  # noqa: E402
import services.style_rag_service as style_rag_service  # noqa: E402


class _Input:
    def __init__(self, name):
        self.name = name


class SemanticFakeSession:
    """只验证 ONNX adapter 的输入、batch、pooling 与相似度契约。"""

    created = 0

    def __init__(self, _path):
        type(self).created += 1

    def get_inputs(self):
        return [_Input('input_ids'), _Input('attention_mask'), _Input('token_type_ids')]

    def run(self, _outputs, feeds):
        ids = feeds['input_ids']
        result = np.zeros((ids.shape[0], ids.shape[1], 4), dtype=np.float32)
        for row, token_ids in enumerate(ids):
            result[row, 0, 0] = np.count_nonzero(np.isin(token_ids, [5, 6, 7]))
            result[row, 0, 1] = np.count_nonzero(np.isin(token_ids, [8, 9, 10]))
            result[row, 0, 2] = 0.2
            result[row, 0, 3] = 0.1
        return [result]


@pytest.fixture
def local_model(tmp_path):
    model_dir = tmp_path / 'model'
    model_dir.mkdir()
    (model_dir / 'model.onnx').write_bytes(b'fake')
    (model_dir / 'vocab.txt').write_text(
        '\n'.join(['[PAD]', '[UNK]', '[CLS]', '[SEP]', '[MASK]', '雨', '夜', '街', '厨', '房', '菜']),
        encoding='utf-8',
    )
    (model_dir / 'manifest.json').write_text(json.dumps({
        'model_id': 'test/semantic-zh',
        'model_version': 'test-v1',
        'dimension': 4,
        'max_tokens': 32,
        'model_file': 'model.onnx',
        'vocab_file': 'vocab.txt',
        'query_instruction': '雨夜',
    }), encoding='utf-8')
    clear_embedding_session_cache()
    SemanticFakeSession.created = 0
    return model_dir


def test_local_backend_batches_and_reuses_session(local_model):
    first = LocalEmbeddingBackend(local_model, session_factory=SemanticFakeSession)
    second = LocalEmbeddingBackend(local_model, session_factory=SemanticFakeSession)
    vectors = first.embed_batch(['雨夜街', '厨房菜'])

    assert len(vectors) == 2
    assert all(len(vector) == 4 for vector in vectors)
    assert SemanticFakeSession.created == 1
    assert second.signature == first.signature


def test_same_scene_is_more_similar_than_unrelated_scene(local_model):
    backend = LocalEmbeddingBackend(local_model, session_factory=SemanticFakeSession)
    query = np.asarray(backend.embed_text('雨夜街', is_query=True))
    same_scene, unrelated = map(np.asarray, backend.embed_batch(['夜雨街', '厨房做菜']))

    assert float(query @ same_scene) > float(query @ unrelated)


def test_missing_local_model_is_an_expected_unavailable_state(tmp_path):
    with pytest.raises(EmbeddingBackendUnavailable, match='模型缺失'):
        create_embedding_backend('local', model_dir=tmp_path / 'missing')


def test_output_dimension_mismatch_is_rejected(local_model):
    manifest_path = local_model / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest['dimension'] = 5
    manifest_path.write_text(json.dumps(manifest), encoding='utf-8')
    clear_embedding_session_cache()
    backend = LocalEmbeddingBackend(local_model, session_factory=SemanticFakeSession)

    with pytest.raises(Exception, match='输出维度异常'):
        backend.embed_text('雨夜')


def test_index_persists_complete_backend_signature(monkeypatch):
    class FakeBackend:
        backend_id = 'local:test'
        model_id = 'test/model'
        model_version = 'sha256:abc'
        dimension = 2

        def embed_batch(self, texts):
            return [[1.0, float(index)] for index, _text in enumerate(texts)]

    monkeypatch.setattr(style_rag_service, 'create_embedding_backend', lambda *args, **kwargs: FakeBackend())
    app = create_app('production')
    with app.app_context():
        corpus = StyleCorpus(name='signature-test', index_status='imported')
        db.session.add(corpus)
        db.session.flush()
        db.session.add(StyleChunk(
            corpus_id=corpus.id, content='雨夜街道。', content_hash='x', source_order=0,
        ))
        db.session.commit()

        assert style_rag_service.index_corpus(corpus.id, backend='local') == 1
        chunk = StyleChunk.query.filter_by(corpus_id=corpus.id).one()
        assert (corpus.embedding_backend, corpus.embedding_model,
                corpus.embedding_model_version, corpus.embedding_dim) == (
                    'local:test', 'test/model', 'sha256:abc', 2,
                )
        assert (chunk.embedding_backend, chunk.embedding_model,
                chunk.embedding_model_version, chunk.embedding_dim) == (
                    'local:test', 'test/model', 'sha256:abc', 2,
                )
