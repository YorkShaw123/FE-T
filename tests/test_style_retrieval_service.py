import json
import os
import sys
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = PROJECT_ROOT / "server"
sys.path.insert(0, str(SERVER_DIR))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from app import create_app  # noqa: E402
from database import db  # noqa: E402
from database.models import StyleChunk, StyleCorpus  # noqa: E402
import services.style_rag_service as style_rag_service  # noqa: E402
from services.style_feature_service import STYLE_FEATURE_IDS, STYLE_FEATURE_VERSION  # noqa: E402
from services.style_rag_service import (  # noqa: E402
    _bm25_scores,
    _mmr_rerank,
    _mmr_rerank_lazy,
    create_corpus,
    hybrid_search_style,
    import_corpus_text,
)
from services.style_retrieval_service import (  # noqa: E402
    content_leakage_metrics,
    explain_style_feature_matches,
    final_retrieval_score,
    style_similarity_scores,
)


def make_profile(center=10.0, scale=2.0):
    return {
        "confidence": 1.0,
        "features": {
            feature_id: {
                "median": center,
                "reliability": 1.0,
                "normalization": {
                    "center": center,
                    "scale": scale,
                    "scale_source": "mad",
                },
            }
            for feature_id in STYLE_FEATURE_IDS
        },
    }


def test_lazy_mmr_matches_full_similarity_map_with_fewer_pair_lookups():
    candidates = [(index, 1.0 - index * 0.05) for index in range(1, 11)]
    similarity_map = {
        (left, right): (1.0 if left == right else 1.0 / (1 + abs(left - right)))
        for left, _score in candidates
        for right, _score in candidates
    }
    calls = []

    expected = _mmr_rerank(candidates, similarity_map, lambda_=0.7, top_k=3)
    actual = _mmr_rerank_lazy(
        candidates,
        lambda left, right: calls.append((left, right)) or similarity_map[(left, right)],
        lambda_=0.7,
        top_k=3,
    )

    assert actual == expected
    assert len(calls) < len(candidates) ** 2


def make_features(value):
    return {feature_id: value for feature_id in STYLE_FEATURE_IDS}


def rank_case(profile, query, content, feature_value, semantic):
    style = style_similarity_scores(make_features(feature_value), profile)
    leakage = content_leakage_metrics(query, content)
    total = final_retrieval_score(
        style_score=style["style_score"],
        scene_score=0.7,
        semantic_score=semantic,
        lexical_score=1.0 if content == query else 0.0,
        leakage_penalty=leakage["content_overlap_penalty"],
    )
    return {**style, **leakage, "total_score": total, "semantic_score": semantic}


def test_style_first_ranking_a_can_beat_content_near_style_far_b():
    profile = make_profile()
    query = "林舟打开旧仓库寻找蓝色账册，发现封面藏着一行密码。"
    cases = {
        "A": rank_case(profile, query, "雨夜的灯光在窗台边缓慢游移，她没有回头。", 10.0, 0.1),
        "B": rank_case(profile, query, query, 30.0, 1.0),
        "C": rank_case(profile, query, query, 10.0, 1.0),
        "D": rank_case(profile, query, "海风掠过山崖，远处只剩灰白的浪。", 30.0, 0.1),
    }

    assert cases["A"]["style_score"] > cases["B"]["style_score"]
    assert cases["A"]["total_score"] > cases["B"]["total_score"]
    assert cases["C"]["content_overlap_penalty"] > cases["A"]["content_overlap_penalty"]
    assert cases["D"]["style_score"] == 0.0
    for case in cases.values():
        assert {
            "style_score", "rhythm_score", "punctuation_score",
            "function_word_score", "semantic_score", "content_overlap_penalty",
            "confidence", "total_score",
        } <= case.keys()


def test_function_words_and_punctuation_alone_do_not_trigger_leakage():
    metrics = content_leakage_metrics("的，了。在？和！", "的。了，在！和？")

    assert metrics["ngram_overlap"] == 0.0
    assert metrics["longest_common_substring"] < 12
    assert metrics["content_overlap_penalty"] == 0.0


def test_bm25_is_filtered_to_selected_corpus_before_limit():
    app = create_app("production")
    with app.app_context():
        selected = StyleCorpus(name="selected")
        noisy = StyleCorpus(name="noisy")
        db.session.add_all((selected, noisy))
        db.session.flush()
        chunks = [StyleChunk(
            corpus_id=selected.id, content="蓝色账册藏着秘密", content_hash="selected",
            source_order=0,
        )]
        chunks.extend(StyleChunk(
            corpus_id=noisy.id, content=f"蓝色账册藏着秘密{index}", content_hash=f"noisy-{index}",
            source_order=index,
        ) for index in range(70))
        db.session.add_all(chunks)
        db.session.flush()
        for chunk in chunks:
            db.session.execute(db.text(
                "INSERT INTO style_chunks_fts(rowid, content) VALUES (:id, :content)"
            ), {"id": chunk.id, "content": chunk.content})
        db.session.commit()

        scores = _bm25_scores([selected.id], "蓝色账册藏着秘密", limit=60)

        assert set(scores) == {chunks[0].id}


def test_import_and_search_degrade_when_fts_is_unavailable(monkeypatch):
    app = create_app("production")
    with app.app_context():
        monkeypatch.setattr(style_rag_service, "_fts_available", lambda: False)
        corpus = create_corpus("no-fts")

        assert import_corpus_text(corpus.id, "这是纯本地文风样本。" * 80) > 0
        items, meta = hybrid_search_style(
            "另一个故事的开头。", corpus_ids=[corpus.id], top_k=1,
        )

        assert len(items) == 1
        assert meta["bm25_enabled"] is False


def test_signature_is_a_versioned_style_subscore():
    profile = make_profile()
    profile['signature'] = {
        'signature_version': 1,
        'features': {
            'signature.000': {
                'reliability': 1.0,
                'normalization': {'center': 2.0, 'scale': 1.0},
            },
        },
    }
    close = style_similarity_scores(
        make_features(10.0), profile, {'signature.000': 2.0}, signature_version=1,
    )
    far = style_similarity_scores(
        make_features(10.0), profile, {'signature.000': 12.0}, signature_version=1,
    )
    incompatible = style_similarity_scores(
        make_features(10.0), profile, {'signature.000': 2.0}, signature_version=2,
    )

    assert close['signature_score'] == 1.0
    assert close['style_score'] > far['style_score']
    assert incompatible['signature_score'] == 0.0
    assert incompatible['signature_version_compatible'] is False


def test_hybrid_search_returns_explainable_style_scores_without_embedding():
    app = create_app("production")
    with app.app_context():
        corpus = StyleCorpus(name="retrieval-explain")
        db.session.add(corpus)
        db.session.flush()
        features = make_features(10.0)
        payload = json.dumps({
            "style_feature_version": STYLE_FEATURE_VERSION,
            "statistics": {"valid_char_count": 1000},
            "features": features,
        })
        for order in range(20):
            db.session.add(StyleChunk(
                corpus_id=corpus.id,
                content=f"不同主题的参考片段{order}，风格保持平稳。",
                content_hash=f"retrieval-{order}",
                article_key="retrieval-article",
                source_order=order,
                char_count=20,
                style_feature_version=STYLE_FEATURE_VERSION,
                style_features_json=payload,
                style_window_valid_chars=1000,
                style_confidence=0.9,
                scene_type="narration",
            ))
        db.session.commit()

        items, meta = hybrid_search_style(
            "用另一个故事测试文风检索。",
            corpus_ids=[corpus.id],
            top_k=3,
        )

        assert len(items) == 3
        assert meta["ranking_mode"] == "style_first"
        assert meta["vector_enabled"] is False
        assert meta["query_scene_type"] == "mixed"
        assert meta["effective_scene_type"] == "mixed"
        assert len(meta["profile_summaries"]) == 1
        summary = meta["profile_summaries"][0]
        assert summary["corpus_id"] == corpus.id
        assert summary["sample_count"] == 20
        assert summary["scene_profile"]["source"] == "global"
        for item in items:
            assert {
                "style_score", "rhythm_score", "punctuation_score",
                "function_word_score", "scene_score", "semantic_score",
                "content_overlap_penalty", "confidence", "ranking_explanation",
            } <= item.keys()
            assert item["semantic_score"] is None
            assert 1 <= len(item["debug_reasons"]) <= 5
            assert len(item["ranking_explanation"]["feature_reasons"]) <= 4


def test_debug_feature_reasons_are_limited_ranked_and_explainable():
    raw = make_features(10.0)
    target = make_profile(10.0)
    target["features"]["function.contrast_per_kchar"]["normalization"] = {
        "center": 0.0, "scale": 1.0,
    }
    raw["function.contrast_per_kchar"] = 4.0

    reasons = explain_style_feature_matches(raw, target, max_reasons=4)

    assert len(reasons) == 4
    assert reasons[0]["normalized_deviation"] == 0.0
    assert reasons[0]["message"].startswith("✓")
    assert all({
        "feature_id", "message", "normalized_deviation",
        "candidate_value", "target_median", "reliability",
    } <= item.keys() for item in reasons)


def test_missing_local_model_degrades_to_style_only(monkeypatch, tmp_path):
    monkeypatch.setenv('FLORA_MODELS_DIR', str(tmp_path / 'missing-models'))
    app = create_app('production')
    with app.app_context():
        corpus = StyleCorpus(name='missing-local-model')
        db.session.add(corpus)
        db.session.flush()
        payload = json.dumps({
            'style_feature_version': STYLE_FEATURE_VERSION,
            'statistics': {'valid_char_count': 1000},
            'features': make_features(10.0),
        })
        for order in range(20):
            db.session.add(StyleChunk(
                corpus_id=corpus.id,
                content=f'本地模型缺失时仍可检索的片段{order}。',
                content_hash=f'missing-{order}', article_key='missing', source_order=order,
                style_feature_version=STYLE_FEATURE_VERSION, style_features_json=payload,
                style_window_valid_chars=1000, style_confidence=0.9,
                embedding_blob=np.asarray([1.0, 0.0], dtype=np.float32).tobytes(),
                embedding_backend='local:onnxruntime-cpu',
                embedding_model='BAAI/bge-small-zh-v1.5',
                embedding_model_version='1.5-onnx-v1', embedding_dim=2,
            ))
        db.session.commit()

        items, meta = hybrid_search_style('雨夜街道', corpus_ids=[corpus.id], top_k=2)

        assert len(items) == 2
        assert meta['vector_enabled'] is False
        assert '模型缺失' in meta['embedding_fallback_reason']
        assert all(item['semantic_score'] is None for item in items)
