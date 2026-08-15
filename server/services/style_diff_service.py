"""Generated text → local Style Analysis → small, explainable Style Diff."""
from __future__ import annotations

import math

from services.author_style_profile_service import resolve_mode_profile
from services.style_feature_service import STYLE_FEATURE_VERSION, analyze_style_features


DEFAULT_MAX_DIFFERENCES = 6
MIN_MAX_DIFFERENCES = 1
MAX_MAX_DIFFERENCES = 8
MIN_ABSOLUTE_DEVIATION = 1.5
HIGH_DEVIATION = 2.5
CRITICAL_DEVIATION = 4.0
DEVIATION_CLIP = 5.0
MIN_EVIDENCE_CONFIDENCE = 0.35
FULL_TEXT_CONFIDENCE_CHARS = 1200
MAX_PER_CORRELATED_CLUSTER = 2

FEATURE_LABELS = {
    "rhythm.sentence_length.mean": "平均句长",
    "rhythm.sentence_length.median": "句长中位数",
    "rhythm.sentence_length.std": "句长波动",
    "rhythm.sentence_length.cv": "句长变异程度",
    "rhythm.sentence_length.p25": "较短句长度",
    "rhythm.sentence_length.p75": "较长句长度",
    "rhythm.short_sentence_ratio": "短句比例",
    "rhythm.long_sentence_ratio": "长句比例",
    "rhythm.very_long_sentence_ratio": "超长句比例",
    "rhythm.adjacent_length_delta": "相邻句长变化",
    "rhythm.paragraph_length.mean": "平均段落长度",
    "rhythm.paragraph_length.cv": "段落长度波动",
    "rhythm.single_sentence_paragraph_ratio": "单句成段比例",
    "rhythm.sentences_per_paragraph.mean": "每段平均句数",
    "punctuation.total_per_kchar": "总标点密度",
    "punctuation.comma_per_kchar": "逗号密度",
    "punctuation.period_per_kchar": "句号密度",
    "punctuation.comma_period_ratio": "逗号/句号比",
    "punctuation.semicolon_per_kchar": "分号密度",
    "punctuation.colon_per_kchar": "冒号密度",
    "punctuation.question_per_kchar": "问号密度",
    "punctuation.exclamation_per_kchar": "感叹号密度",
    "punctuation.ellipsis_per_kchar": "省略号密度",
    "punctuation.dash_per_kchar": "破折号密度",
    "punctuation.parentheses_per_kchar": "括号密度",
    "punctuation.quote_coverage_ratio": "引号覆盖率",
    "function.de_per_kchar": "“的”使用频率",
    "function.di_per_kchar": "“地”使用频率",
    "function.de_complement_per_kchar": "“得”使用频率",
    "function.le_per_kchar": "“了”使用频率",
    "function.zhe_per_kchar": "“着”使用频率",
    "function.guo_per_kchar": "“过”使用频率",
    "function.negation_per_kchar": "否定结构频率",
    "function.contrast_per_kchar": "转折结构频率",
    "function.causal_per_kchar": "因果结构频率",
    "function.conditional_per_kchar": "条件结构频率",
    "function.time_progression_per_kchar": "时间推进结构频率",
    "function.hedge_per_kchar": "推测/模糊词频率",
    "function.degree_adverb_per_kchar": "程度副词频率",
    "function.modal_particle_per_kchar": "语气词频率",
    "function.first_person_pronoun_per_kchar": "第一人称代词频率",
    "function.third_person_pronoun_per_kchar": "第三人称代词频率",
    "syntax.ba_marker_per_kchar": "把字结构频率",
    "syntax.bei_marker_per_kchar": "被字结构频率",
}

FEATURE_IMPORTANCE = {
    "rhythm.sentence_length.mean": 1.0,
    "rhythm.sentence_length.median": 0.9,
    "rhythm.short_sentence_ratio": 1.0,
    "rhythm.long_sentence_ratio": 0.9,
    "rhythm.very_long_sentence_ratio": 0.8,
    "rhythm.paragraph_length.mean": 0.9,
    "punctuation.comma_period_ratio": 1.0,
    "punctuation.comma_per_kchar": 0.9,
    "punctuation.period_per_kchar": 0.9,
}


class StyleDiffError(ValueError):
    """Style Diff input/profile is invalid or stale."""


def _cluster(feature_id: str) -> str:
    if feature_id in {
        "rhythm.sentence_length.mean", "rhythm.sentence_length.median",
        "rhythm.sentence_length.p25", "rhythm.sentence_length.p75",
    }:
        return "sentence_length_center"
    if feature_id in {
        "rhythm.sentence_length.std", "rhythm.sentence_length.cv",
        "rhythm.adjacent_length_delta",
    }:
        return "sentence_length_variation"
    if feature_id in {
        "rhythm.short_sentence_ratio", "rhythm.long_sentence_ratio",
        "rhythm.very_long_sentence_ratio",
    }:
        return "sentence_length_ratios"
    if feature_id in {
        "punctuation.total_per_kchar", "punctuation.comma_per_kchar",
        "punctuation.period_per_kchar", "punctuation.comma_period_ratio",
    }:
        return "punctuation_core"
    return feature_id


def _severity(absolute_deviation: float) -> str:
    if absolute_deviation >= CRITICAL_DEVIATION:
        return "critical"
    if absolute_deviation >= HIGH_DEVIATION:
        return "high"
    return "moderate"


def _direction_words(feature_id: str, high: bool) -> tuple[str, str]:
    label = FEATURE_LABELS.get(feature_id, feature_id)
    if "sentence_length" in feature_id or feature_id == "rhythm.paragraph_length.mean":
        state = "明显偏长" if high else "明显偏短"
    elif feature_id.endswith(".cv") or feature_id.endswith(".std") or "delta" in feature_id:
        state = "波动明显过大" if high else "波动明显不足"
    else:
        state = "明显偏高" if high else "明显偏低"
    return label, state


def _rewrite_instruction(feature_id: str, high: bool) -> str:
    if feature_id.startswith("rhythm.sentence_length"):
        return (
            "拆分部分复句，减少连续修饰和并列分句。"
            if high else "适度合并相邻短句，用从句或承接成分形成更完整的句子。"
        )
    if feature_id == "rhythm.short_sentence_ratio":
        return "减少连续短句，将语义紧密的句子适度合并。" if high else "在关键动作或转折处增加简短独立句。"
    if feature_id in {"rhythm.long_sentence_ratio", "rhythm.very_long_sentence_ratio"}:
        return "拆开部分长句，每句只保留一个主要推进动作。" if high else "适量加入层次清楚的复句。"
    if feature_id.startswith("rhythm.paragraph") or "paragraph" in feature_id:
        return "缩短过长段落并在叙事转折处换段。" if high else "合并语义连续的碎段，减少无必要换行。"
    if feature_id == "punctuation.comma_period_ratio":
        return "减少逗号串联，适当改用句号收束。" if high else "适当用逗号连接同一语义层次，减少过早断句。"
    if feature_id.startswith("punctuation."):
        label = FEATURE_LABELS.get(feature_id, "该标点")
        return f"减少{label}，只保留有明确节奏作用的位置。" if high else f"在自然语气位置适量增加{label}。"
    label = FEATURE_LABELS.get(feature_id, "该功能结构")
    return f"减少重复使用{label}，用自然句法替换。" if high else f"在语义适合处自然增加{label}，不要机械堆叠。"


def _profile_deviation(value: float, stats: dict) -> float | None:
    normalization = stats.get("normalization") or {}
    center = normalization.get("center")
    scale = normalization.get("scale")
    if center is None or not isinstance(scale, (int, float)) or scale <= 0:
        return None
    return (float(value) - float(center)) / max(float(scale), 1e-9)


def analyze_style_diff(
    text: str,
    author_profile: dict,
    scene_type: str | None = None,
    max_differences: int = DEFAULT_MAX_DIFFERENCES,
) -> dict:
    """Analyze without changing text; return only high-confidence, actionable differences."""
    if not isinstance(author_profile, dict) or not author_profile.get("features"):
        raise StyleDiffError("Author Style Profile 无效或缺少全局 Feature")
    profile_version = author_profile.get("feature_version")
    if profile_version is not None and profile_version != STYLE_FEATURE_VERSION:
        raise StyleDiffError("Author Style Profile 的 Feature 版本已失效，请先重建")
    max_differences = max(
        MIN_MAX_DIFFERENCES, min(MAX_MAX_DIFFERENCES, int(max_differences))
    )
    generated = analyze_style_features(text or "")
    generated_features = generated.get("features") or {}
    valid_chars = int(generated.get("statistics", {}).get("valid_char_count") or 0)
    text_confidence = min(1.0, valid_chars / FULL_TEXT_CONFIDENCE_CHARS)
    resolution = resolve_mode_profile(author_profile, scene_type)
    target_profile = resolution["profile"]
    target_features = target_profile.get("features") or {}
    global_features = author_profile.get("features") or {}
    profile_confidence = max(0.0, min(1.0, float(target_profile.get("confidence") or 0.0)))

    candidates = []
    for feature_id, stats in target_features.items():
        value = generated_features.get(feature_id)
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            continue
        deviation = _profile_deviation(float(value), stats)
        if deviation is None or abs(deviation) < MIN_ABSOLUTE_DEVIATION:
            continue
        p25, p75 = stats.get("p25"), stats.get("p75")
        if p25 is None or p75 is None or float(p25) <= float(value) <= float(p75):
            continue
        reliability = max(0.0, min(1.0, float(stats.get("reliability") or 0.0)))
        evidence_confidence = reliability * profile_confidence * text_confidence
        if evidence_confidence < MIN_EVIDENCE_CONFIDENCE:
            continue
        clipped = max(-DEVIATION_CLIP, min(DEVIATION_CLIP, deviation))
        importance = FEATURE_IMPORTANCE.get(feature_id, 0.7)
        priority = abs(clipped) * importance * evidence_confidence
        high = clipped > 0
        label, state = _direction_words(feature_id, high)
        global_stats = global_features.get(feature_id) or {}
        global_deviation = _profile_deviation(float(value), global_stats)
        candidates.append((priority, feature_id, {
            "feature_id": feature_id,
            "generated_value": round(float(value), 6),
            "target_median": stats.get("median"),
            "target_range": [p25, p75],
            "normalized_deviation": round(clipped, 6),
            "severity": _severity(abs(deviation)),
            "human_message": f"{label}{state}。",
            "rewrite_instruction": _rewrite_instruction(feature_id, high),
            "target_source": resolution["source"],
            "target_mode": resolution["resolved_mode"],
            "global_median": global_stats.get("median"),
            "global_normalized_deviation": (
                round(max(-DEVIATION_CLIP, min(DEVIATION_CLIP, global_deviation)), 6)
                if global_deviation is not None else None
            ),
            "sample_reliability": round(reliability, 6),
            "style_confidence": round(profile_confidence, 6),
            "evidence_confidence": round(evidence_confidence, 6),
        }))

    candidates.sort(key=lambda item: (-item[0], item[1]))
    differences = []
    cluster_counts = {}
    for _priority, feature_id, difference in candidates:
        cluster = _cluster(feature_id)
        if cluster_counts.get(cluster, 0) >= MAX_PER_CORRELATED_CLUSTER:
            continue
        differences.append(difference)
        cluster_counts[cluster] = cluster_counts.get(cluster, 0) + 1
        if len(differences) >= max_differences:
            break
    return {
        "style_feature_version": STYLE_FEATURE_VERSION,
        "generated_valid_char_count": valid_chars,
        "generated_style_confidence": round(text_confidence, 6),
        "target_source": resolution["source"],
        "target_mode": resolution["resolved_mode"],
        "difference_count": len(differences),
        "differences": differences,
    }
