import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = PROJECT_ROOT / "server"
sys.path.insert(0, str(SERVER_DIR))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from app import create_app  # noqa: E402
from database import db  # noqa: E402
from database.models import StyleChunk  # noqa: E402
from services.style_feature_service import STYLE_FEATURE_VERSION  # noqa: E402
from services.style_rag_service import create_corpus, import_corpus_text, split_corpus_text  # noqa: E402
from services.style_window_service import build_style_window_analyses  # noqa: E402
import services.style_window_service as style_window_service  # noqa: E402


@dataclass
class FakeChunk:
    article_key: str
    source_order: int
    content: str


def make_chunk(order, size=400, article="article-a", char="甲"):
    return FakeChunk(article_key=article, source_order=order, content=char * size)


def test_single_chunk_article_uses_only_current_chunk():
    chunk = make_chunk(0)
    analysis = build_style_window_analyses([chunk])[0]

    assert analysis.source is chunk
    assert analysis.window_text == chunk.content
    assert analysis.start_order == analysis.end_order == 0
    assert analysis.valid_char_count == 400
    assert analysis.confidence == {
        "version": 1,
        "score": 0.333333,
        "level": "low",
        "factors": {
            "sample_length": {
                "score": 0.333333,
                "weight": 1.0,
                "valid_char_count": 400,
                "full_confidence_at": 1200,
            },
        },
    }


def test_two_chunk_article_degrades_to_available_neighbor():
    first, second = make_chunk(0), make_chunk(1, char="乙")
    analyses = build_style_window_analyses([first, second])

    assert analyses[0].window_text == f"{first.content}\n\n{second.content}"
    assert analyses[1].window_text == f"{first.content}\n\n{second.content}"
    assert [(item.start_order, item.end_order) for item in analyses] == [(0, 1), (0, 1)]
    assert all(item.valid_char_count == 800 for item in analyses)


def test_middle_chunk_is_between_previous_and_next_chunks():
    chunks = [make_chunk(0, char="甲"), make_chunk(1, char="乙"), make_chunk(2, char="丙")]
    middle = build_style_window_analyses(chunks)[1]

    assert middle.window_text == "\n\n".join(chunk.content for chunk in chunks)
    assert middle.window_text.index(chunks[0].content) < middle.window_text.index(chunks[1].content)
    assert middle.window_text.index(chunks[1].content) < middle.window_text.index(chunks[2].content)
    assert (middle.start_order, middle.current_order, middle.end_order) == (0, 1, 2)
    assert middle.valid_char_count == 1200
    assert middle.confidence["score"] == 1.0


def test_first_chunk_of_multi_chunk_article_only_uses_forward_context():
    chunks = [make_chunk(index, char=char) for index, char in enumerate("甲乙丙")]
    first = build_style_window_analyses(chunks)[0]

    assert (first.start_order, first.current_order, first.end_order) == (0, 0, 1)
    assert first.window_text == f"{chunks[0].content}\n\n{chunks[1].content}"


def test_last_chunk_of_multi_chunk_article_only_uses_backward_context():
    chunks = [make_chunk(index, char=char) for index, char in enumerate("甲乙丙")]
    last = build_style_window_analyses(chunks)[-1]

    assert (last.start_order, last.current_order, last.end_order) == (1, 2, 2)
    assert last.window_text == f"{chunks[1].content}\n\n{chunks[2].content}"


def test_short_neighbors_expand_outward_without_exceeding_target_maximum():
    chunks = [make_chunk(index, size=250, char=char) for index, char in enumerate("甲乙丙丁戊")]
    middle = build_style_window_analyses(chunks)[2]

    assert 800 <= middle.valid_char_count <= 1500
    assert middle.start_order == 0
    assert middle.end_order == 4
    assert middle.window_text.split("\n\n")[2] == chunks[2].content


def test_windows_never_cross_article_key_even_with_same_source_order():
    article_a = [make_chunk(0, size=300, article="a", char="甲"), make_chunk(1, size=300, article="a", char="乙")]
    article_b = [make_chunk(0, size=300, article="b", char="丙"), make_chunk(1, size=300, article="b", char="丁")]
    analyses = build_style_window_analyses([article_a[0], article_b[0], article_a[1], article_b[1]])

    for analysis in analyses:
        other_chars = "丙丁" if analysis.article_key == "a" else "甲乙"
        assert not any(char in analysis.window_text for char in other_chars)
        assert analysis.valid_char_count == 600


def test_building_windows_does_not_modify_current_chunk_content():
    chunks = [make_chunk(index, char=char) for index, char in enumerate("甲乙丙")]
    original_contents = [chunk.content for chunk in chunks]

    build_style_window_analyses(chunks)

    assert [chunk.content for chunk in chunks] == original_contents


def test_chunk_sizes_are_computed_once_per_article(monkeypatch):
    chunks = [make_chunk(index, size=250) for index in range(40)]
    calls = 0
    original = style_window_service.count_valid_characters

    def counted(text):
        nonlocal calls
        calls += 1
        return original(text)

    monkeypatch.setattr(style_window_service, "count_valid_characters", counted)
    analyses = list(style_window_service.iter_style_window_analyses(chunks))

    assert len(analyses) == len(chunks)
    assert calls == len(chunks)


def test_import_persists_window_features_without_changing_rag_chunks():
    app = create_app("production")
    paragraphs = [char * 500 for char in "甲乙丙"]
    text = "\n\n".join(paragraphs)
    expected_chunks = split_corpus_text(text)

    with app.app_context():
        corpus = create_corpus("style-window-test")
        assert import_corpus_text(corpus.id, text, filename="article.txt") == 3
        chunks = StyleChunk.query.filter_by(corpus_id=corpus.id).order_by(StyleChunk.source_order).all()

        assert [chunk.content for chunk in chunks] == expected_chunks
        assert len({chunk.article_key for chunk in chunks}) == 1
        assert [chunk.style_window_valid_chars for chunk in chunks] == [1000, 1500, 1000]
        assert [(chunk.style_window_start_order, chunk.style_window_end_order) for chunk in chunks] == [
            (0, 1), (0, 2), (1, 2),
        ]
        assert all(chunk.style_feature_version == STYLE_FEATURE_VERSION for chunk in chunks)
        assert all(0 < chunk.style_confidence <= 1 for chunk in chunks)
        for chunk in chunks:
            payload = json.loads(chunk.style_features_json)
            assert payload["style_feature_version"] == STYLE_FEATURE_VERSION
            assert payload["statistics"]["valid_char_count"] == chunk.style_window_valid_chars


def test_style_chunk_schema_contains_migrated_window_columns():
    app = create_app("production")
    expected = {
        "article_key",
        "style_feature_version",
        "style_features_json",
        "style_window_valid_chars",
        "style_confidence",
        "style_window_start_order",
        "style_window_end_order",
    }

    with app.app_context():
        columns = {row[1] for row in db.session.execute(db.text("PRAGMA table_info(style_chunks)"))}

    assert expected <= columns
