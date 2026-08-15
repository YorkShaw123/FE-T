"""Purely local statistical Author Style Profiles for Style RAG corpora."""

from __future__ import annotations

import json
import math
import statistics
from datetime import datetime, timezone

from database import db
from database.models import AuthorStyleProfile, StyleChunk, StyleCorpus
from services.style_feature_service import STYLE_FEATURE_IDS, STYLE_FEATURE_VERSION
from services.style_signature_service import (
    STYLE_SIGNATURE_VERSION,
    build_signature_vocabulary,
    signature_payload,
)
from services.style_window_service import iter_style_window_analyses


ROBUST_MAD_FACTOR = 1.4826
ROBUST_IQR_FACTOR = 1.349
ROBUST_EPSILON = 1e-9
ROBUST_Z_CLIP = 5.0
RELIABLE_SAMPLE_COUNT = 30
MIN_MODE_SAMPLE_COUNT = 20
REPRESENTATIVE_SAMPLE_LIMIT = 3
AUTHOR_PROFILE_SCHEMA_VERSION = 3

MODE_TO_SCENE = {
    "dialogue": "dialogue",
    "action": "action",
    "psychology": "psychology",
    "description": "environment",
    "transition": "transition",
    "exposition": "narration",
}
SCENE_TO_MODE = {scene: mode for mode, scene in MODE_TO_SCENE.items()}
MODE_TO_BROAD = {
    "dialogue": "dynamic",
    "action": "dynamic",
    "psychology": "reflective",
    "description": "reflective",
    "transition": "narrative",
    "exposition": "narrative",
}
BROAD_TO_SCENES = {
    "dynamic": {"dialogue", "action"},
    "reflective": {"psychology", "environment"},
    "narrative": {"transition", "narration"},
}


class AuthorStyleProfileError(ValueError):
    """The requested corpus cannot produce a current statistical profile."""


def _percentile(values: list[float], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _round(value: float) -> float:
    return round(float(value), 6)


def _feature_statistics(values: list[float], total_samples: int) -> dict:
    median = statistics.median(values)
    absolute_deviations = [abs(value - median) for value in values]
    mad = statistics.median(absolute_deviations)
    p05 = _percentile(values, 0.05)
    p25 = _percentile(values, 0.25)
    p75 = _percentile(values, 0.75)
    p95 = _percentile(values, 0.95)
    if mad > 0:
        scale = ROBUST_MAD_FACTOR * mad
        scale_source = "mad"
    elif p75 > p25:
        scale = (p75 - p25) / ROBUST_IQR_FACTOR
        scale_source = "iqr"
    else:
        scale = ROBUST_EPSILON
        scale_source = "epsilon"

    available_count = len(values)
    availability_ratio = available_count / total_samples
    sample_reliability = min(1.0, math.sqrt(available_count / RELIABLE_SAMPLE_COUNT))
    reliability = availability_ratio * sample_reliability
    return {
        "available_count": available_count,
        "missing_count": total_samples - available_count,
        "zero_count": sum(value == 0 for value in values),
        "median": _round(median),
        "mad": _round(mad),
        "p05": _round(p05),
        "p25": _round(p25),
        "p75": _round(p75),
        "p95": _round(p95),
        "missing_ratio": _round(1 - availability_ratio),
        "zero_ratio": _round(sum(value == 0 for value in values) / available_count),
        "reliability": _round(reliability),
        "normalization": {
            "center": _round(median),
            "scale": scale if scale_source == "epsilon" else _round(scale),
            "scale_source": scale_source,
            "clip": ROBUST_Z_CLIP,
            "epsilon": ROBUST_EPSILON,
        },
    }


def normalize_style_features(raw_features: dict, profile: dict) -> dict[str, float | None]:
    """Normalize one raw Feature mapping against a profile's robust center/scale."""
    normalized = {}
    feature_stats = profile.get("features", {})
    for feature_id in STYLE_FEATURE_IDS:
        value = raw_features.get(feature_id)
        stats = feature_stats.get(feature_id)
        if value is None or not stats or not stats.get("normalization"):
            normalized[feature_id] = None
            continue
        normalization = stats["normalization"]
        scale = max(float(normalization["scale"]), ROBUST_EPSILON)
        z_score = (float(value) - float(normalization["center"])) / scale
        normalized[feature_id] = _round(max(-ROBUST_Z_CLIP, min(ROBUST_Z_CLIP, z_score)))
    return normalized


def upgrade_corpus_style_features(corpus_id: int, *, commit: bool = True) -> int:
    """Recompute current Feature data in place without changing RAG content or indexes."""
    corpus = db.session.get(StyleCorpus, corpus_id)
    if not corpus:
        raise AuthorStyleProfileError("风格语料库不存在")
    chunks = (
        StyleChunk.query.filter_by(corpus_id=corpus_id)
        .order_by(StyleChunk.article_key, StyleChunk.source_order)
        .all()
    )
    needs_upgrade = False
    for chunk in chunks:
        if chunk.style_feature_version != STYLE_FEATURE_VERSION:
            needs_upgrade = True
            break
        try:
            payload = json.loads(chunk.style_features_json or "{}")
        except (TypeError, json.JSONDecodeError):
            needs_upgrade = True
            break
        if payload.get("style_feature_version") != STYLE_FEATURE_VERSION:
            needs_upgrade = True
            break
    if not needs_upgrade:
        return 0

    upgraded = 0
    for analysis in iter_style_window_analyses(chunks):
        chunk = analysis.source
        if chunk.style_feature_version != STYLE_FEATURE_VERSION:
            upgraded += 1
        chunk.style_feature_version = STYLE_FEATURE_VERSION
        chunk.style_features_json = json.dumps(analysis.features, ensure_ascii=False, sort_keys=True)
        chunk.style_window_valid_chars = analysis.valid_char_count
        chunk.style_confidence = analysis.confidence["score"]
        chunk.style_window_start_order = analysis.start_order
        chunk.style_window_end_order = analysis.end_order
    if commit:
        db.session.commit()
    return upgraded


def _parse_profile_chunks(chunks: list[StyleChunk]):
    parsed = []
    for chunk in chunks:
        try:
            payload = json.loads(chunk.style_features_json or "{}")
        except (TypeError, json.JSONDecodeError):
            continue
        if payload.get("style_feature_version") != STYLE_FEATURE_VERSION:
            continue
        features = payload.get("features")
        if isinstance(features, dict):
            parsed.append((chunk, features))
    return parsed


def _independent_profile_chunks(parsed_chunks):
    """Greedily retain non-overlapping windows so reliability is not inflated."""
    selected = []
    last_end_by_article = {}
    ordered = sorted(
        parsed_chunks,
        key=lambda item: (
            item[0].article_key or "",
            int(item[0].style_window_start_order or 0),
            int(item[0].source_order or 0),
        ),
    )
    for parsed in ordered:
        chunk = parsed[0]
        article_key = chunk.article_key or ""
        start = int(chunk.style_window_start_order)
        end = int(chunk.style_window_end_order)
        if start == 0 and end == 0 and int(chunk.source_order or 0) != 0:
            # Compatibility for manually created/current-version rows that predate
            # persisted window boundaries: treat the chunk itself as the sample.
            start = end = int(chunk.source_order)
        if start <= last_end_by_article.get(article_key, -1):
            continue
        selected.append(parsed)
        last_end_by_article[article_key] = end
    return selected


def _representative_sample_ids(parsed_chunks, feature_stats):
    scored = []
    for chunk, features in parsed_chunks:
        distances = []
        for feature_id, stats in feature_stats.items():
            value = features.get(feature_id)
            normalization = stats.get("normalization")
            if value is None or not normalization or normalization["scale_source"] == "epsilon":
                continue
            scale = max(float(normalization["scale"]), ROBUST_EPSILON)
            distances.append(min(ROBUST_Z_CLIP, abs(float(value) - stats["median"]) / scale))
        distance = statistics.fmean(distances) if distances else math.inf
        scored.append((distance, int(chunk.source_order), int(chunk.id)))
    return [chunk_id for _, _, chunk_id in sorted(scored)[:REPRESENTATIVE_SAMPLE_LIMIT]]


def _aggregate_profile(parsed_chunks) -> dict:
    total_samples = len(parsed_chunks)
    feature_values = {feature_id: [] for feature_id in STYLE_FEATURE_IDS}
    valid_char_count = 0
    confidence_values = []
    signature_values = {}
    for chunk, features in parsed_chunks:
        valid_char_count += max(0, int(chunk.style_window_valid_chars or 0))
        confidence_values.append(max(0.0, min(1.0, float(chunk.style_confidence or 0))))
        if chunk.style_signature_version == STYLE_SIGNATURE_VERSION:
            try:
                signature = json.loads(chunk.style_signature_json or "{}")
            except (TypeError, json.JSONDecodeError):
                signature = {}
            if signature.get("signature_version") == STYLE_SIGNATURE_VERSION:
                for signature_id, value in (signature.get("values") or {}).items():
                    if isinstance(value, (int, float)) and math.isfinite(value):
                        signature_values.setdefault(signature_id, []).append(float(value))
        for feature_id in STYLE_FEATURE_IDS:
            value = features.get(feature_id)
            if isinstance(value, (int, float)) and math.isfinite(value):
                feature_values[feature_id].append(float(value))

    feature_stats = {}
    for feature_id, values in feature_values.items():
        if values:
            feature_stats[feature_id] = _feature_statistics(values, total_samples)
        else:
            feature_stats[feature_id] = {
                "available_count": 0, "missing_count": total_samples, "zero_count": 0,
                "median": None, "mad": None, "p05": None, "p25": None,
                "p75": None, "p95": None, "missing_ratio": 1.0,
                "zero_ratio": None, "reliability": 0.0, "normalization": None,
            }
    mean_reliability = statistics.fmean(
        stats["reliability"] for stats in feature_stats.values()
    ) if feature_stats else 0.0
    mean_window_confidence = statistics.fmean(confidence_values) if confidence_values else 0.0
    signature_stats = {
        signature_id: _feature_statistics(values, total_samples)
        for signature_id, values in sorted(signature_values.items())
    }
    return {
        "sample_count": total_samples,
        "valid_char_count": valid_char_count,
        "confidence": _round(mean_reliability * mean_window_confidence),
        "features": feature_stats,
        "representative_sample_ids": _representative_sample_ids(parsed_chunks, feature_stats),
        "signature": {
            "signature_version": STYLE_SIGNATURE_VERSION,
            "features": signature_stats,
            "dimension": len(signature_stats),
        },
    }


def _rebuild_corpus_signatures(corpus: StyleCorpus, chunks: list[StyleChunk]) -> list[dict]:
    vocabulary = build_signature_vocabulary(
        analysis.window_text for analysis in iter_style_window_analyses(chunks)
    )
    for analysis in iter_style_window_analyses(chunks):
        chunk, text = analysis.source, analysis.window_text
        chunk.style_signature_version = STYLE_SIGNATURE_VERSION
        chunk.style_signature_json = signature_payload(text, vocabulary)
    corpus.signature_version = STYLE_SIGNATURE_VERSION
    return vocabulary


def build_author_style_profile(corpus_id: int) -> AuthorStyleProfile:
    """Rebuild the current-version statistical profile for one StyleCorpus."""
    corpus = db.session.get(StyleCorpus, corpus_id)
    if not corpus:
        raise AuthorStyleProfileError("风格语料库不存在")

    upgraded_count = upgrade_corpus_style_features(corpus_id, commit=False)

    chunks = (
        StyleChunk.query.filter_by(
            corpus_id=corpus_id,
            is_enabled=True,
            style_feature_version=STYLE_FEATURE_VERSION,
        )
        .order_by(StyleChunk.source_order)
        .all()
    )
    parsed_chunks = _independent_profile_chunks(_parse_profile_chunks(chunks))
    if not parsed_chunks:
        raise AuthorStyleProfileError("语料库没有当前 Feature 版本的有效 Style Window")
    signature_vocabulary = _rebuild_corpus_signatures(corpus, chunks)

    global_profile = _aggregate_profile(parsed_chunks)
    scene_groups = {}
    for parsed in parsed_chunks:
        scene_groups.setdefault(parsed[0].scene_type or "mixed", []).append(parsed)
    mode_sample_counts = {
        mode: len(scene_groups.get(scene, [])) for mode, scene in MODE_TO_SCENE.items()
    }
    mode_profiles = {
        mode: _aggregate_profile(scene_groups[scene])
        for mode, scene in MODE_TO_SCENE.items()
        if len(scene_groups.get(scene, [])) >= MIN_MODE_SAMPLE_COUNT
    }
    broad_profiles = {}
    for broad_name, scenes in BROAD_TO_SCENES.items():
        broad_chunks = [parsed for scene in scenes for parsed in scene_groups.get(scene, [])]
        if len(broad_chunks) >= MIN_MODE_SAMPLE_COUNT:
            broad_profiles[broad_name] = _aggregate_profile(broad_chunks)

    facet_profiles = {}
    for dimension in ("pacing", "pov", "emotion"):
        groups = {}
        for parsed in parsed_chunks:
            label = str(getattr(parsed[0], dimension) or "").strip()
            if label:
                groups.setdefault(label, []).append(parsed)
        facet_profiles[dimension] = {
            label: _aggregate_profile(group)
            for label, group in groups.items()
            if len(group) >= MIN_MODE_SAMPLE_COUNT
        }

    profile_payload = {
        "schema_version": AUTHOR_PROFILE_SCHEMA_VERSION,
        "profile_type": "author_style_statistics",
        "feature_version": STYLE_FEATURE_VERSION,
        "sample_count": global_profile["sample_count"],
        "valid_char_count": global_profile["valid_char_count"],
        "confidence": global_profile["confidence"],
        "features": global_profile["features"],
        "representative_sample_ids": global_profile["representative_sample_ids"],
        "feature_order": list(STYLE_FEATURE_IDS),
        "robust_normalized_vector": [
            0.0 if global_profile["features"][feature_id]["normalization"] else None
            for feature_id in STYLE_FEATURE_IDS
        ],
        "style_signature": {
            "signature_version": STYLE_SIGNATURE_VERSION,
            "vocabulary": signature_vocabulary,
            "dimension": len(signature_vocabulary),
        },
        "signature": global_profile["signature"],
        "mode_schema": {
            "mode_to_scene": MODE_TO_SCENE,
            "mode_to_broad": MODE_TO_BROAD,
            "minimum_sample_count": MIN_MODE_SAMPLE_COUNT,
        },
        "mode_sample_counts": mode_sample_counts,
        "mode_profiles": mode_profiles,
        "broad_profiles": broad_profiles,
        "facet_profiles": facet_profiles,
        "upgraded_chunk_count": upgraded_count,
        "normalization_note": "The stored center vector normalizes to zero; use normalization parameters for target vectors.",
    }

    record = AuthorStyleProfile.query.filter_by(corpus_id=corpus_id).first()
    if not record:
        record = AuthorStyleProfile(corpus_id=corpus_id, feature_version=STYLE_FEATURE_VERSION)
        db.session.add(record)
    record.feature_version = STYLE_FEATURE_VERSION
    record.profile_json = json.dumps(profile_payload, ensure_ascii=False, sort_keys=True)
    record.sample_count = global_profile["sample_count"]
    record.valid_char_count = global_profile["valid_char_count"]
    record.confidence = global_profile["confidence"]
    record.updated_at = datetime.now(timezone.utc)
    db.session.commit()
    return record


def get_author_style_profile(corpus_id: int) -> tuple[AuthorStyleProfile | None, bool]:
    """Return the stored profile and whether its Feature version is stale."""
    record = AuthorStyleProfile.query.filter_by(corpus_id=corpus_id).first()
    if not record:
        return None, False
    stale = record.feature_version != STYLE_FEATURE_VERSION
    try:
        payload = json.loads(record.profile_json or "{}")
    except (TypeError, json.JSONDecodeError):
        payload = {}
    stale = stale or payload.get("schema_version") != AUTHOR_PROFILE_SCHEMA_VERSION
    corpus = db.session.get(StyleCorpus, corpus_id)
    stale = stale or payload.get("style_signature", {}).get(
        "signature_version"
    ) != STYLE_SIGNATURE_VERSION
    stale = stale or bool(corpus and corpus.signature_version != STYLE_SIGNATURE_VERSION)
    return record, stale


def resolve_mode_profile(profile: dict, requested_mode: str | None) -> dict:
    """Resolve an exact mode, then its broad category, then the global profile."""
    requested = str(requested_mode or "").strip().lower()
    canonical = SCENE_TO_MODE.get(requested, requested)
    if canonical in profile.get("mode_profiles", {}):
        return {
            "source": "mode",
            "requested_mode": requested,
            "resolved_mode": canonical,
            "profile": profile["mode_profiles"][canonical],
        }
    broad = MODE_TO_BROAD.get(canonical)
    if broad and broad in profile.get("broad_profiles", {}):
        return {
            "source": "broad",
            "requested_mode": requested,
            "resolved_mode": broad,
            "profile": profile["broad_profiles"][broad],
        }
    return {
        "source": "global",
        "requested_mode": requested,
        "resolved_mode": "global",
        "profile": {
            key: profile[key]
            for key in (
                "sample_count", "valid_char_count", "confidence", "features",
                "representative_sample_ids", "signature",
            )
            if key in profile
        },
    }


def merge_target_profiles(target_profiles: list[dict]) -> dict:
    """Build one comparable Dense-Feature target for a multi-corpus search."""
    if not target_profiles:
        return {"sample_count": 0, "valid_char_count": 0, "confidence": 0.0, "features": {}}
    if len(target_profiles) == 1:
        return target_profiles[0]

    merged_features = {}
    for feature_id in STYLE_FEATURE_IDS:
        stats_items = [
            profile.get("features", {}).get(feature_id) or {}
            for profile in target_profiles
        ]
        stats_items = [item for item in stats_items if item.get("median") is not None]
        if not stats_items:
            continue
        centers = [float(item["median"]) for item in stats_items]
        center = statistics.median(centers)
        between_mad = statistics.median(abs(value - center) for value in centers)
        between_scale = ROBUST_MAD_FACTOR * between_mad
        within_scales = [
            float(item["normalization"]["scale"])
            for item in stats_items
            if item.get("normalization")
            and item["normalization"].get("scale_source") != "epsilon"
        ]
        scale = max(
            statistics.median(within_scales) if within_scales else 0.0,
            between_scale,
            ROBUST_EPSILON,
        )
        reliability = statistics.fmean(float(item.get("reliability") or 0.0) for item in stats_items)
        merged_features[feature_id] = {
            "median": _round(center),
            "p25": _round(statistics.median(float(item["p25"]) for item in stats_items)),
            "p75": _round(statistics.median(float(item["p75"]) for item in stats_items)),
            "reliability": _round(reliability),
            "normalization": {
                "center": _round(center),
                "scale": _round(scale) if scale > ROBUST_EPSILON else ROBUST_EPSILON,
                "scale_source": "merged",
                "clip": ROBUST_Z_CLIP,
                "epsilon": ROBUST_EPSILON,
            },
        }
    return {
        "sample_count": sum(int(profile.get("sample_count") or 0) for profile in target_profiles),
        "valid_char_count": sum(int(profile.get("valid_char_count") or 0) for profile in target_profiles),
        "confidence": _round(statistics.fmean(float(profile.get("confidence") or 0.0) for profile in target_profiles)),
        "features": merged_features,
        # Corpus-specific Signature vocabularies are not comparable across corpora.
        "signature": {},
    }
