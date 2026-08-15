import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / 'server'
sys.path.insert(0, str(SERVER))
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from app import create_app  # noqa: E402
from database import db  # noqa: E402
from database.models import StyleChunk, StyleCorpus  # noqa: E402
from services.style_index_progress import (  # noqa: E402
    clear_index_progress_for_tests,
    get_index_progress,
)
import services.style_rag_service as style_rag_service  # noqa: E402


class BatchBackend:
    backend_id = 'local:test'
    model_id = 'test/model'
    model_version = 'test-v1'
    dimension = 2

    def __init__(self):
        self.batch_sizes = []

    def embed_batch(self, texts):
        texts = list(texts)
        self.batch_sizes.append(len(texts))
        return [[1.0, 0.0] for _text in texts]


def _add_corpus(chunk_count):
    corpus = StyleCorpus(name='batch-test', chunk_count=chunk_count, index_status='imported')
    db.session.add(corpus)
    db.session.flush()
    for index in range(chunk_count):
        db.session.add(StyleChunk(
            corpus_id=corpus.id,
            content=f'第{index}个用于批量向量化的中文片段。',
            content_hash=f'batch-{index}',
            source_order=index,
        ))
    db.session.commit()
    return corpus.id


def test_index_corpus_uses_bounded_batches_and_reports_exact_progress(monkeypatch):
    backend = BatchBackend()
    monkeypatch.setattr(
        style_rag_service, 'create_embedding_backend', lambda *args, **kwargs: backend,
    )
    app = create_app('production')
    with app.app_context():
        corpus_id = _add_corpus(35)
        progress = []

        count = style_rag_service.index_corpus(
            corpus_id,
            backend='local',
            progress_callback=lambda completed, total: progress.append((completed, total)),
        )

        assert count == 35
        assert backend.batch_sizes == [16, 16, 3]
        assert progress == [(0, 35), (16, 35), (32, 35), (35, 35)]
        corpus = db.session.get(StyleCorpus, corpus_id)
        assert corpus.index_status == 'indexed'


def test_index_progress_api_reaches_completed_state(monkeypatch):
    backend = BatchBackend()
    monkeypatch.setattr(
        style_rag_service, 'create_embedding_backend', lambda *args, **kwargs: backend,
    )
    clear_index_progress_for_tests()
    app = create_app('production')
    with app.app_context():
        corpus_id = _add_corpus(3)
    client = app.test_client()

    response = client.post(
        f'/api/style-corpora/{corpus_id}/index',
        json={'backend': 'local'},
    )
    progress_response = client.get(f'/api/style-corpora/{corpus_id}/index-progress')

    assert response.status_code == 200
    progress = progress_response.get_json()['data']
    assert progress['status'] == 'completed'
    assert progress['completed'] == progress['total'] == 3
    assert progress['percent'] == 100.0
    assert get_index_progress(corpus_id)['estimated_remaining_seconds'] == 0.0
