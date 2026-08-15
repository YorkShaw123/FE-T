"""受限 Style Signature：只学习功能结构与标点，不学习内容字符 n-gram。"""
from __future__ import annotations

import json
import math
import re
from collections import Counter
from collections.abc import Iterable

from services.style_feature_service import FUNCTION_WORDS, count_valid_characters


STYLE_SIGNATURE_VERSION = 1
SIGNATURE_MAX_DIMENSIONS = 192
SIGNATURE_MAX_PATTERN_TOKENS = 3
SIGNATURE_MIN_TOTAL_COUNT = 3
SIGNATURE_MIN_DOCUMENT_RATIO = 0.03
SIGNATURE_UBIQUITOUS_MIN_WINDOWS = 8
SIGNATURE_UBIQUITOUS_RATIO = 0.95

PUNCTUATION_TOKENS = frozenset("，。；：？！、（）“”‘’") | {"……", "——"}
STRUCTURAL_ONLY_ATOMS = frozenset({"时候"})
EXTRA_FUNCTION_ATOMS = frozenset({
    "的", "地", "得", "了", "着", "过", "是", "把", "被", "并", "而", "也", "又", "才",
    "便", "就", "仍", "还", "于是", "那么", "其实", "原来", "后来", "甚至", "况且",
})
FUNCTION_ATOMS = frozenset(
    word for words in FUNCTION_WORDS.values() for word in words
) | EXTRA_FUNCTION_ATOMS
PRONOUN_ATOMS = frozenset(
    FUNCTION_WORDS["first_person_pronoun"] + FUNCTION_WORDS["third_person_pronoun"]
)
ALL_ATOMS = FUNCTION_ATOMS | STRUCTURAL_ONLY_ATOMS | PUNCTUATION_TOKENS
_ATOM_PATTERN = re.compile(
    "|".join(re.escape(token) for token in sorted(ALL_ATOMS, key=lambda item: (-len(item), item)))
)


def normalize_signature_text(text: str) -> str:
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"(?:…\s*){2,}|\.{6,}", "……", text)
    return re.sub(r"(?:—\s*){2,}|-{2,}", "——", text)


def _token_runs(text: str):
    """只连接原文中相邻的允许 token；任何内容字符都会中断结构。"""
    matches = list(_ATOM_PATTERN.finditer(normalize_signature_text(text)))
    run = []
    previous_end = None
    for match in matches:
        if previous_end is not None and match.start() != previous_end:
            if run:
                yield run
            run = []
        run.append(match.group(0))
        previous_end = match.end()
    if run:
        yield run


def extract_signature_patterns(text: str) -> Counter:
    """返回允许模式的频次；键为 token tuple，绝不包含未知内容 token。"""
    counts = Counter()
    for run in _token_runs(text):
        for start in range(len(run)):
            token = run[start]
            if token not in STRUCTURAL_ONLY_ATOMS:
                counts[(token,)] += 1
            for size in range(2, SIGNATURE_MAX_PATTERN_TOKENS + 1):
                pattern = tuple(run[start:start + size])
                if len(pattern) != size:
                    break
                if any(item in FUNCTION_ATOMS or item in PRONOUN_ATOMS for item in pattern):
                    counts[pattern] += 1
    return counts


def build_signature_vocabulary(window_texts: Iterable[str]) -> list[dict]:
    """从 corpus windows 构造确定性词表，过滤稀疏及近乎恒定模式。"""
    total_windows = 0
    total_counts = Counter()
    document_counts = Counter()
    for text in window_texts:
        total_windows += 1
        counts = extract_signature_patterns(text)
        total_counts.update(counts)
        document_counts.update(counts.keys())
    if not total_windows:
        return []
    minimum_documents = max(2, math.ceil(total_windows * SIGNATURE_MIN_DOCUMENT_RATIO))
    candidates = []
    for pattern, count in total_counts.items():
        documents = document_counts[pattern]
        ratio = documents / total_windows
        if count < SIGNATURE_MIN_TOTAL_COUNT or documents < minimum_documents:
            continue
        if total_windows >= SIGNATURE_UBIQUITOUS_MIN_WINDOWS and documents == total_windows:
            continue
        if total_windows >= 20 and ratio >= SIGNATURE_UBIQUITOUS_RATIO:
            continue
        information = ratio * (1.0 - ratio) * math.log1p(count)
        candidates.append((information, len(pattern), "".join(pattern), pattern, count, documents))
    candidates.sort(key=lambda item: (-item[0], -item[1], item[2]))
    vocabulary = []
    for index, (_, _, display, pattern, count, documents) in enumerate(
        candidates[:SIGNATURE_MAX_DIMENSIONS]
    ):
        vocabulary.append({
            "id": f"signature.{index:03d}",
            "pattern": display,
            "tokens": list(pattern),
            "total_count": count,
            "document_count": documents,
            "document_ratio": round(documents / total_windows, 6),
        })
    return vocabulary


def vectorize_signature(text: str, vocabulary: list[dict]) -> dict[str, float]:
    counts = extract_signature_patterns(text)
    valid_chars = count_valid_characters(text)
    if valid_chars <= 0:
        return {entry["id"]: 0.0 for entry in vocabulary}
    scale = 1000.0 / valid_chars
    return {
        entry["id"]: round(counts[tuple(entry["tokens"])] * scale, 6)
        for entry in vocabulary
    }


def signature_payload(text: str, vocabulary: list[dict]) -> str:
    return json.dumps({
        "signature_version": STYLE_SIGNATURE_VERSION,
        "values": vectorize_signature(text, vocabulary),
    }, ensure_ascii=False, sort_keys=True)
