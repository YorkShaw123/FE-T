"""为 Style RAG chunk 构建同文章的本地风格分析窗口。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.style_feature_service import analyze_style_features, count_valid_characters


STYLE_WINDOW_MIN_VALID_CHARS = 800
STYLE_WINDOW_MAX_VALID_CHARS = 1500
STYLE_CONFIDENCE_FULL_VALID_CHARS = 1200
STYLE_CONFIDENCE_VERSION = 1


@dataclass(frozen=True)
class StyleWindowAnalysis:
    """一个 current chunk 对应的分析结果；source 仍指向原 chunk。"""

    source: Any
    article_key: str
    current_order: int
    start_order: int
    end_order: int
    window_text: str
    valid_char_count: int
    features: dict
    confidence: dict


def _source_value(source: Any, name: str):
    if isinstance(source, dict):
        return source[name]
    return getattr(source, name)


def _confidence_from_length(valid_char_count: int) -> dict:
    """返回可扩展的 confidence 结构；V1 仅启用样本长度 factor。"""
    length_score = min(1.0, max(0.0, valid_char_count / STYLE_CONFIDENCE_FULL_VALID_CHARS))
    if length_score >= 0.75:
        level = "high"
    elif length_score >= 0.4:
        level = "medium"
    else:
        level = "low"
    return {
        "version": STYLE_CONFIDENCE_VERSION,
        "score": round(length_score, 6),
        "level": level,
        "factors": {
            "sample_length": {
                "score": round(length_score, 6),
                "weight": 1.0,
                "valid_char_count": valid_char_count,
                "full_confidence_at": STYLE_CONFIDENCE_FULL_VALID_CHARS,
            },
        },
    }


def _select_window(group: list[Any], sizes: list[int], current_index: int) -> list[Any]:
    start = end = current_index
    selected_size = sum(sizes[start:end + 1])

    while selected_size < STYLE_WINDOW_MIN_VALID_CHARS:
        can_expand_left = start > 0
        can_expand_right = end + 1 < len(group)
        if can_expand_left and can_expand_right:
            addition = sizes[start - 1] + sizes[end + 1]
            if selected_size + addition <= STYLE_WINDOW_MAX_VALID_CHARS:
                start -= 1
                end += 1
                selected_size += addition
            elif selected_size + min(sizes[start - 1], sizes[end + 1]) <= STYLE_WINDOW_MAX_VALID_CHARS:
                if sizes[start - 1] <= sizes[end + 1]:
                    start -= 1
                    selected_size += sizes[start]
                else:
                    end += 1
                    selected_size += sizes[end]
            else:
                break
        elif can_expand_left:
            addition = sizes[start - 1]
            if selected_size + addition > STYLE_WINDOW_MAX_VALID_CHARS:
                break
            start -= 1
            selected_size += addition
        elif can_expand_right:
            addition = sizes[end + 1]
            if selected_size + addition > STYLE_WINDOW_MAX_VALID_CHARS:
                break
            end += 1
            selected_size += addition
        else:
            break
    return group[start:end + 1]


def iter_style_window_analyses(chunks: list[Any]):
    """按输入顺序逐个生成窗口分析，避免同时保留全部 window_text。"""
    groups = {}
    for source in chunks:
        article_key = str(_source_value(source, "article_key") or "")
        groups.setdefault(article_key, []).append(source)
    positions = {}
    for group in groups.values():
        group.sort(key=lambda source: _source_value(source, "source_order"))
        sizes = [count_valid_characters(_source_value(source, "content")) for source in group]
        for index, source in enumerate(group):
            positions[id(source)] = (group, sizes, index)

    for source in chunks:
        group, sizes, current_index = positions[id(source)]
        article_key = str(_source_value(source, "article_key") or "")
        selected = _select_window(group, sizes, current_index)
        window_text = "\n\n".join(str(_source_value(item, "content") or "") for item in selected)
        features = analyze_style_features(window_text)
        valid_char_count = features["statistics"]["valid_char_count"]
        yield StyleWindowAnalysis(
            source=source,
            article_key=article_key,
            current_order=int(_source_value(source, "source_order")),
            start_order=int(_source_value(selected[0], "source_order")),
            end_order=int(_source_value(selected[-1], "source_order")),
            window_text=window_text,
            valid_char_count=valid_char_count,
            features=features,
            confidence=_confidence_from_length(valid_char_count),
        )


def build_style_window_analyses(chunks: list[Any]) -> list[StyleWindowAnalysis]:
    """兼容需要列表结果的调用方；大型离线任务应使用迭代接口。"""
    return list(iter_style_window_analyses(chunks))
