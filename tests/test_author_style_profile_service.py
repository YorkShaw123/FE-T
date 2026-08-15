import json
import os
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = PROJECT_ROOT / "server"
sys.path.insert(0, str(SERVER_DIR))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from app import create_app  # noqa: E402
from database import db  # noqa: E402
from database.migrations import apply_sqlite_migrations  # noqa: E402
from database.models import AuthorStyleProfile, StyleChunk, StyleCorpus  # noqa: E402
from services.author_style_profile_service import (  # noqa: E402
    AuthorStyleProfileError,
    _feature_statistics,
    build_author_style_profile,
    get_author_style_profile,
    normalize_style_features,
    merge_target_profiles,
    resolve_mode_profile,
)
from services.style_feature_service import STYLE_FEATURE_IDS, STYLE_FEATURE_VERSION  # noqa: E402
from services.style_signature_service import STYLE_SIGNATURE_VERSION  # noqa: E402


@pytest.fixture
def app():
    return create_app("production")


def add_chunk(
    corpus_id, order, value, *, version=STYLE_FEATURE_VERSION, confidence=0.8,
    valid_chars=1000, scene_type="narration", content=None, embedding_blob=None,
):
    features = {feature_id: None for feature_id in STYLE_FEATURE_IDS}
    features["rhythm.sentence_length.mean"] = value
    payload = {
        "style_feature_version": version,
        "statistics": {"valid_char_count": valid_chars},
        "features": features,
    }
    db.session.add(StyleChunk(
        corpus_id=corpus_id,
        content=content or f"样本{order}",
        content_hash=f"hash-{corpus_id}-{order}",
        article_key=f"article-{corpus_id}",
        source_order=order,
        char_count=3,
        style_feature_version=version,
        style_features_json=json.dumps(payload),
        style_window_valid_chars=valid_chars,
        style_confidence=confidence,
        scene_type=scene_type,
        embedding_blob=embedding_blob,
    ))


def test_build_profile_persists_robust_statistics_and_normalizer(app):
    with app.app_context():
        corpus = StyleCorpus(name="author-profile")
        db.session.add(corpus)
        db.session.flush()
        for order, value in enumerate((1.0, 2.0, 3.0, 100.0)):
            add_chunk(corpus.id, order, value)
        db.session.commit()

        record = build_author_style_profile(corpus.id)
        profile = json.loads(record.profile_json)
        stats = profile["features"]["rhythm.sentence_length.mean"]

        assert record.feature_version == STYLE_FEATURE_VERSION
        assert record.sample_count == 4
        assert record.valid_char_count == 4000
        assert stats["median"] == 2.5
        assert stats["mad"] == 1.0
        assert stats["p05"] == pytest.approx(1.15)
        assert stats["p25"] == pytest.approx(1.75)
        assert stats["p75"] == pytest.approx(27.25)
        assert stats["p95"] == pytest.approx(85.45)
        assert stats["normalization"]["scale"] == pytest.approx(1.4826)
        assert profile["profile_type"] == "author_style_statistics"
        assert profile["style_signature"]["signature_version"] == STYLE_SIGNATURE_VERSION
        assert corpus.signature_version == STYLE_SIGNATURE_VERSION
        assert all(
            chunk.style_signature_version == STYLE_SIGNATURE_VERSION
            for chunk in StyleChunk.query.filter_by(corpus_id=corpus.id)
        )
        assert set(profile["features"]) == set(STYLE_FEATURE_IDS)
        assert len(profile["robust_normalized_vector"]) == len(STYLE_FEATURE_IDS)
        assert normalize_style_features(
            {"rhythm.sentence_length.mean": 1000}, profile
        )["rhythm.sentence_length.mean"] == 5.0


def test_mad_zero_uses_iqr_then_epsilon():
    from services.author_style_profile_service import _feature_statistics

    iqr_stats = _feature_statistics([0.0, 0.0, 0.0, 10.0], 4)
    constant_stats = _feature_statistics([2.0, 2.0, 2.0], 3)

    assert iqr_stats["normalization"]["scale_source"] == "iqr"
    assert iqr_stats["normalization"]["scale"] > 0
    assert constant_stats["normalization"]["scale_source"] == "epsilon"
    assert constant_stats["normalization"]["scale"] == pytest.approx(1e-9)


def test_multi_corpus_target_uses_one_shared_center_and_scale():
    left = {"sample_count": 4, "valid_char_count": 4000, "confidence": 0.8, "features": {
        "rhythm.sentence_length.mean": _feature_statistics([9.0, 10.0, 10.0, 11.0], 4),
    }}
    right = {"sample_count": 4, "valid_char_count": 4000, "confidence": 0.8, "features": {
        "rhythm.sentence_length.mean": _feature_statistics([29.0, 30.0, 30.0, 31.0], 4),
    }}

    merged = merge_target_profiles([left, right])
    stats = merged["features"]["rhythm.sentence_length.mean"]

    assert stats["median"] == 20.0
    assert stats["normalization"]["scale_source"] == "merged"
    assert stats["normalization"]["scale"] > 1.0
    assert merged["signature"] == {}


def test_overlapping_windows_do_not_inflate_profile_sample_count(app):
    with app.app_context():
        corpus = StyleCorpus(name="overlap-profile")
        db.session.add(corpus)
        db.session.flush()
        for order in range(5):
            add_chunk(corpus.id, order, float(order + 1))
        db.session.flush()
        boundaries = [(0, 1), (0, 2), (1, 3), (2, 4), (3, 4)]
        chunks = StyleChunk.query.filter_by(corpus_id=corpus.id).order_by(StyleChunk.source_order).all()
        for chunk, (start, end) in zip(chunks, boundaries):
            chunk.style_window_start_order = start
            chunk.style_window_end_order = end
        db.session.commit()

        record = build_author_style_profile(corpus.id)

        assert record.sample_count == 2


def test_rebuild_updates_one_row_and_stale_version_is_detected(app):
    with app.app_context():
        corpus = StyleCorpus(name="rebuild-profile")
        db.session.add(corpus)
        db.session.flush()
        add_chunk(corpus.id, 0, 10.0)
        db.session.commit()

        first = build_author_style_profile(corpus.id)
        first_id = first.id
        first.feature_version = STYLE_FEATURE_VERSION - 1
        db.session.commit()
        _, stale = get_author_style_profile(corpus.id)
        assert stale is True

        rebuilt = build_author_style_profile(corpus.id)
        assert rebuilt.id == first_id
        assert AuthorStyleProfile.query.filter_by(corpus_id=corpus.id).count() == 1
        _, stale = get_author_style_profile(corpus.id)
        assert stale is False

        corpus.signature_version = 0
        db.session.commit()
        _, stale = get_author_style_profile(corpus.id)
        assert stale is True


def test_empty_corpus_is_rejected_and_old_version_is_automatically_upgraded(app):
    with app.app_context():
        empty = StyleCorpus(name="empty-profile")
        old = StyleCorpus(name="old-profile")
        db.session.add_all((empty, old))
        db.session.flush()
        add_chunk(
            old.id, 0, 1.0, version=STYLE_FEATURE_VERSION - 1,
            content="甲" * 900, embedding_blob=b"keep-vector",
        )
        db.session.commit()

        with pytest.raises(AuthorStyleProfileError):
            build_author_style_profile(empty.id)
        record = build_author_style_profile(old.id)
        upgraded = StyleChunk.query.filter_by(corpus_id=old.id).one()
        assert record.sample_count == 1
        assert upgraded.style_feature_version == STYLE_FEATURE_VERSION
        assert upgraded.content == "甲" * 900
        assert upgraded.embedding_blob == b"keep-vector"


def test_author_profile_migration_is_idempotent_and_separate_from_style_cards(app):
    with app.app_context():
        apply_sqlite_migrations(db)
        apply_sqlite_migrations(db)
        tables = {
            row[0] for row in db.session.execute(db.text(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ))
        }
        columns = {
            row[1] for row in db.session.execute(db.text(
                "PRAGMA table_info(author_style_profiles)"
            ))
        }

        assert "author_style_profiles" in tables
        assert "style_profiles" in tables
        corpus_columns = {
            row[1] for row in db.session.execute(db.text("PRAGMA table_info(style_corpora)"))
        }
        chunk_columns = {
            row[1] for row in db.session.execute(db.text("PRAGMA table_info(style_chunks)"))
        }

        assert {"corpus_id", "feature_version", "profile_json", "sample_count", "valid_char_count", "confidence"} <= columns
        assert "signature_version" in corpus_columns
        assert {"style_signature_version", "style_signature_json"} <= chunk_columns


def test_sufficient_scene_builds_mode_profile_with_representatives(app):
    with app.app_context():
        corpus = StyleCorpus(name="dialogue-mode")
        db.session.add(corpus)
        db.session.flush()
        for order in range(20):
            add_chunk(corpus.id, order, float(order + 1), scene_type="dialogue")
        db.session.commit()

        record = build_author_style_profile(corpus.id)
        profile = json.loads(record.profile_json)
        dialogue = profile["mode_profiles"]["dialogue"]

        assert dialogue["sample_count"] == 20
        assert dialogue["features"]["rhythm.sentence_length.mean"]["median"] == 10.5
        assert dialogue["features"]["rhythm.sentence_length.mean"]["mad"] == 5.0
        assert len(dialogue["representative_sample_ids"]) == 3
        assert resolve_mode_profile(profile, "dialogue")["source"] == "mode"


def test_profile_aggregates_corpus_signature_statistics(app):
    with app.app_context():
        corpus = StyleCorpus(name='signature-profile')
        db.session.add(corpus)
        db.session.flush()
        for order in range(20):
            ending = '，却没有。' if order < 10 else '，只是。'
            add_chunk(
                corpus.id, order, 10.0,
                content=('甲' if order < 10 else '乙') * 390 + ending,
            )
        db.session.commit()

        profile = json.loads(build_author_style_profile(corpus.id).profile_json)
        vocabulary = profile['style_signature']['vocabulary']
        signature_stats = profile['signature']['features']

        assert 0 < len(vocabulary) < 128
        assert set(signature_stats) == {entry['id'] for entry in vocabulary}
        assert all(
            {'median', 'mad', 'p05', 'p25', 'p75', 'p95', 'reliability'} <= stats.keys()
            for stats in signature_stats.values()
        )


def test_insufficient_scene_falls_back_to_sufficient_broad_profile(app):
    with app.app_context():
        corpus = StyleCorpus(name="broad-fallback")
        db.session.add(corpus)
        db.session.flush()
        for order in range(5):
            add_chunk(corpus.id, order, 10.0, scene_type="dialogue")
        for order in range(5, 20):
            add_chunk(corpus.id, order, 20.0, scene_type="action")
        db.session.commit()

        profile = json.loads(build_author_style_profile(corpus.id).profile_json)
        resolved = resolve_mode_profile(profile, "dialogue")

        assert profile["mode_sample_counts"]["dialogue"] == 5
        assert "dialogue" not in profile["mode_profiles"]
        assert resolved["source"] == "broad"
        assert resolved["resolved_mode"] == "dynamic"
        assert resolved["profile"]["sample_count"] == 20


def test_unknown_or_unsupported_scene_falls_back_to_global(app):
    with app.app_context():
        corpus = StyleCorpus(name="global-fallback")
        db.session.add(corpus)
        db.session.flush()
        for order in range(6):
            add_chunk(corpus.id, order, float(order), scene_type="mixed")
        db.session.commit()

        profile = json.loads(build_author_style_profile(corpus.id).profile_json)
        unknown = resolve_mode_profile(profile, "weather-report")
        description = resolve_mode_profile(profile, "environment")

        assert unknown["source"] == "global"
        assert description["source"] == "global"
        assert unknown["profile"]["sample_count"] == 6
        assert unknown["profile"]["features"] == profile["features"]
