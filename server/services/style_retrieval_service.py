"""Explainable local Style-first scoring and content-leakage protection."""

from __future__ import annotations

import re

from services.style_feature_service import STYLE_FEATURE_IDS


STYLE_WEIGHT = 0.72
SCENE_WEIGHT = 0.12
SEMANTIC_WEIGHT = 0.10
LEXICAL_WEIGHT = 0.06
LEAKAGE_WEIGHT = 0.45
STYLE_Z_CLIP = 5.0

FEATURE_GROUPS = {
    "rhythm": tuple(feature_id for feature_id in STYLE_FEATURE_IDS if feature_id.startswith("rhythm.")),
    "punctuation": tuple(
        feature_id for feature_id in STYLE_FEATURE_IDS if feature_id.startswith("punctuation.")
    ),
    "function_word": tuple(
        feature_id for feature_id in STYLE_FEATURE_IDS
        if feature_id.startswith("function.") or feature_id.startswith("syntax.")
    ),
}
GROUP_WEIGHTS = {
    "rhythm": 0.32,
    "function_word": 0.28,
    "punctuation": 0.20,
    "signature": 0.20,
}

SCENE_BROAD = {
    "dialogue": "dynamic", "action": "dynamic",
    "psychology": "reflective", "environment": "reflective",
    "transition": "narrative", "narration": "narrative",
}
MODE_ALIASES = {"description": "environment", "exposition": "narration"}

CONTENT_GRAM_SIZE = 8
LONG_MATCH_BASE = 12
LONG_MATCH_FULL_PENALTY = 36
COMMON_CONTENT_WORDS = frozenset({
    "的", "了", "着", "过", "是", "在", "和", "与", "而", "也", "都", "就",
    "不", "没", "一个", "这个", "那个", "他们", "她们", "我们",
})

STYLE_REASON_FEATURES = {
    "rhythm.sentence_length.mean": "平均句长",
    "rhythm.sentence_length.cv": "句长变化",
    "rhythm.short_sentence_ratio": "短句比例",
    "rhythm.paragraph_length.mean": "段落长度",
    "punctuation.comma_period_ratio": "逗号/句号节奏",
    "punctuation.quote_coverage_ratio": "引号覆盖习惯",
    "function.contrast_per_kchar": "转折习惯",
    "function.causal_per_kchar": "因果连接习惯",
    "function.time_progression_per_kchar": "时间推进习惯",
    "function.first_person_pronoun_per_kchar": "第一人称习惯",
    "function.third_person_pronoun_per_kchar": "第三人称习惯",
}


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def _round(value: float) -> float:
    return round(float(value), 6)


def _normalized_content(text: str) -> str:
    return "".join(char.lower() for char in text or "" if char.isalnum())


def _ngrams(text: str, size: int) -> set[str]:
    if len(text) < size:
        return set()
    return {text[index:index + size] for index in range(len(text) - size + 1)}


def _ngram_containment(left: str, right: str, size: int = CONTENT_GRAM_SIZE) -> float:
    left_grams, right_grams = _ngrams(left, size), _ngrams(right, size)
    if not left_grams or not right_grams:
        return 0.0
    return len(left_grams & right_grams) / min(len(left_grams), len(right_grams))


def _ngram_jaccard(left: str, right: str, size: int = CONTENT_GRAM_SIZE) -> float:
    left_grams, right_grams = _ngrams(left, size), _ngrams(right, size)
    union = left_grams | right_grams
    return len(left_grams & right_grams) / len(union) if union else 0.0


def _has_common_substring(left: str, right: str, size: int) -> bool:
    if size <= 0 or len(left) < size or len(right) < size:
        return False
    grams = _ngrams(left, size)
    return any(right[index:index + size] in grams for index in range(len(right) - size + 1))


def _longest_common_substring_length(left: str, right: str) -> int:
    low, high, best = 1, min(len(left), len(right)), 0
    while low <= high:
        middle = (low + high) // 2
        if _has_common_substring(left, right, middle):
            best = middle
            low = middle + 1
        else:
            high = middle - 1
    return best


def _content_terms(text: str) -> set[str]:
    terms = set()
    for token in re.findall(r"[\u3400-\u9fffA-Za-z0-9]{2,}", text or ""):
        if token in COMMON_CONTENT_WORDS:
            continue
        if len(token) <= 6:
            terms.add(token.lower())
        else:
            terms.update(token[index:index + 4].lower() for index in range(len(token) - 3))
    return terms


def content_leakage_metrics(query_text: str, candidate_text: str) -> dict:
    """Return explainable overlap signals without treating punctuation as content."""
    query = _normalized_content(query_text)
    candidate = _normalized_content(candidate_text)
    ngram_overlap = _ngram_containment(query, candidate)
    longest = (
        _longest_common_substring_length(query, candidate)
        if _has_common_substring(query, candidate, LONG_MATCH_BASE)
        else 0
    )
    long_match_score = _clip01(
        (longest - LONG_MATCH_BASE) / (LONG_MATCH_FULL_PENALTY - LONG_MATCH_BASE)
    ) if longest >= LONG_MATCH_BASE else 0.0
    query_terms, candidate_terms = _content_terms(query_text), _content_terms(candidate_text)
    term_union = query_terms | candidate_terms
    keyword_overlap = len(query_terms & candidate_terms) / len(term_union) if term_union else 0.0
    penalty = 0.50 * long_match_score + 0.35 * ngram_overlap + 0.15 * keyword_overlap
    return {
        "content_overlap_penalty": _round(_clip01(penalty)),
        "ngram_overlap": _round(ngram_overlap),
        "keyword_overlap": _round(keyword_overlap),
        "longest_common_substring": longest,
    }


def content_diversity_similarity(left: str, right: str) -> float:
    """Local fallback similarity for MMR when embeddings are unavailable."""
    return _ngram_jaccard(_normalized_content(left), _normalized_content(right))


def _group_similarity(raw_features: dict, profile_features: dict, feature_ids: tuple[str, ...]):
    weighted_sum = 0.0
    weight_sum = 0.0
    used = 0
    for feature_id in feature_ids:
        value = raw_features.get(feature_id)
        stats = profile_features.get(feature_id) or {}
        normalization = stats.get("normalization")
        reliability = float(stats.get("reliability") or 0.0)
        if value is None or not normalization or reliability <= 0:
            continue
        scale = max(float(normalization["scale"]), 1e-9)
        z_score = abs(float(value) - float(normalization["center"])) / scale
        similarity = max(0.0, 1.0 - min(STYLE_Z_CLIP, z_score) / STYLE_Z_CLIP)
        weighted_sum += similarity * reliability
        weight_sum += reliability
        used += 1
    return (weighted_sum / weight_sum if weight_sum else 0.0), used


def style_similarity_scores(
    raw_features: dict,
    target_profile: dict,
    raw_signature: dict | None = None,
    signature_version: int | None = None,
) -> dict:
    """Score Dense Features plus a version-compatible restricted Signature."""
    profile_features = target_profile.get("features", {})
    group_scores = {}
    used_counts = {}
    for group_name, feature_ids in FEATURE_GROUPS.items():
        score, used = _group_similarity(raw_features, profile_features, feature_ids)
        group_scores[group_name] = score
        used_counts[group_name] = used
    signature_profile = target_profile.get("signature") or {}
    signature_features = signature_profile.get("features") or {}
    compatible_signature = (
        raw_signature is not None
        and signature_version is not None
        and signature_version == signature_profile.get("signature_version")
    )
    if compatible_signature:
        signature_score, signature_used = _group_similarity(
            raw_signature, signature_features, tuple(sorted(signature_features)),
        )
    else:
        signature_score, signature_used = 0.0, 0
    group_scores["signature"] = signature_score
    used_counts["signature"] = signature_used
    available_groups = [name for name, used in used_counts.items() if used]
    denominator = sum(GROUP_WEIGHTS[name] for name in available_groups)
    style_score = (
        sum(group_scores[name] * GROUP_WEIGHTS[name] for name in available_groups) / denominator
        if denominator else 0.0
    )
    total_possible = len(STYLE_FEATURE_IDS) + (
        len(signature_features) if compatible_signature else 0
    )
    coverage = sum(used_counts.values()) / max(1, total_possible)
    confidence = _clip01(float(target_profile.get("confidence") or 0.0) * coverage)
    return {
        "style_score": _round(style_score),
        "rhythm_score": _round(group_scores["rhythm"]),
        "punctuation_score": _round(group_scores["punctuation"]),
        "function_word_score": _round(group_scores["function_word"]),
        "signature_score": _round(group_scores["signature"]),
        "signature_version_compatible": compatible_signature,
        "confidence": _round(confidence),
        "feature_counts": used_counts,
    }


def explain_style_feature_matches(
    raw_features: dict, target_profile: dict, max_reasons: int = 4,
) -> list[dict]:
    """Return a small deterministic set of useful matches/differences for debugger UI."""
    candidates = []
    profile_features = target_profile.get("features", {})
    for feature_id, label in STYLE_REASON_FEATURES.items():
        value = raw_features.get(feature_id)
        stats = profile_features.get(feature_id) or {}
        normalization = stats.get("normalization") or {}
        reliability = float(stats.get("reliability") or 0.0)
        if value is None or not normalization or reliability <= 0:
            continue
        center = float(normalization.get("center") or 0.0)
        scale = max(float(normalization.get("scale") or 0.0), 1e-9)
        deviation = abs(float(value) - center) / scale
        if deviation <= 0.5:
            level, message = "strong", f"✓ {label}高度接近"
        elif deviation <= 1.25:
            level, message = "close", f"✓ {label}接近"
        else:
            level, message = "different", f"△ {label}略有差异"
        median = stats.get("median")
        candidates.append({
            "feature_id": feature_id,
            "label": label,
            "level": level,
            "message": message,
            "normalized_deviation": _round(deviation),
            "candidate_value": _round(value),
            "target_median": _round(center if median is None else median),
            "reliability": _round(reliability),
        })

    close = sorted(
        (item for item in candidates if item["level"] != "different"),
        key=lambda item: (item["normalized_deviation"], item["feature_id"]),
    )[:max_reasons]
    if len(close) < max_reasons:
        different = sorted(
            (item for item in candidates if item["level"] == "different"),
            key=lambda item: (-item["reliability"], item["normalized_deviation"], item["feature_id"]),
        )[:max_reasons - len(close)]
        close.extend(different)
    return close


def scene_similarity(candidate_scene: str, requested_scene: str | None) -> float:
    if not requested_scene:
        return 0.7
    requested = MODE_ALIASES.get(requested_scene, requested_scene)
    if candidate_scene == requested:
        return 1.0
    if SCENE_BROAD.get(candidate_scene) == SCENE_BROAD.get(requested) and SCENE_BROAD.get(requested):
        return 0.6
    if candidate_scene == "mixed":
        return 0.35
    return 0.0


def final_retrieval_score(
    *, style_score: float, scene_score: float, semantic_score: float | None,
    lexical_score: float, leakage_penalty: float,
) -> float:
    semantic = _clip01(semantic_score) if semantic_score is not None else 0.0
    score = (
        STYLE_WEIGHT * _clip01(style_score)
        + SCENE_WEIGHT * _clip01(scene_score)
        + SEMANTIC_WEIGHT * semantic
        + LEXICAL_WEIGHT * _clip01(lexical_score)
        - LEAKAGE_WEIGHT * _clip01(leakage_penalty)
    )
    return _round(_clip01(score))
