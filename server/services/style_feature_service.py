"""纯本地、无副作用的中文 Style Feature V1 提取器。"""

from __future__ import annotations

import math
import re
import statistics
import unicodedata


STYLE_FEATURE_VERSION = 2  # Style Feature V1.1 machine schema version
OUTPUT_DECIMAL_PLACES = 6

SHORT_SENTENCE_MAX = 12
LONG_SENTENCE_MIN = 30
VERY_LONG_SENTENCE_MIN = 50

MIN_SENTENCES_MEAN = 5
MIN_SENTENCES_MEDIAN = 7
MIN_SENTENCES_DISTRIBUTION = 10
MIN_SENTENCES_ADJACENT = 6
MIN_PARAGRAPHS_MEAN = 3
MIN_PARAGRAPHS_DISTRIBUTION = 5
MIN_CHARS_PUNCTUATION = 300
MIN_PERIODS_FOR_RATIO = 3
MIN_CHARS_FUNCTION = 500
MIN_CHARS_SYNTAX = 800

ASCII_ABBREVIATIONS = frozenset({
    "dr", "etc", "e.g", "i.e", "jr", "mr", "mrs", "ms", "prof", "sr", "st", "vs",
})

ELLIPSIS_TOKEN = "\ue000"
DASH_TOKEN = "\ue001"

ELLIPSIS_RE = re.compile(r"(?:[…⋯]+|(?<![0-9])[.．]{3,}(?![0-9]))")
DASH_RE = re.compile(r"(?:[—–―]+|-{2,})")
TERMINATOR_RUN_RE = re.compile(r"[。！？!?]+")

COMMA_MARKS = frozenset("，,")
SEMICOLON_MARKS = frozenset("；;")
COLON_MARKS = frozenset("：:")
QUESTION_MARKS = frozenset("？?")
EXCLAMATION_MARKS = frozenset("！!")
CLOSING_MARKS = frozenset("”’」』)]）】〕")
MODAL_FOLLOW_MARKS = frozenset("，,。！？!?；;：:…⋯—–―)]）】〕”’」』\"")

QUOTE_PAIRS = {
    "“": "”",
    "‘": "’",
    "「": "」",
    "『": "』",
}
PAREN_PAIRS = {
    "（": "）",
    "(": ")",
    "[": "]",
    "【": "】",
    "〔": "〕",
}

FUNCTION_WORDS = {
    "negation": (
        "没有", "不是", "不能", "不会", "不要", "并非", "未曾",
        "不", "没", "无", "未", "勿", "别", "莫", "非",
    ),
    "contrast": ("但是", "然而", "可是", "不过", "反而", "尽管", "虽然", "但", "却", "只是"),
    "causal": ("因为", "因此", "所以", "因而", "由于", "故而", "从而", "于是"),
    "conditional": ("如果", "要是", "只要", "除非", "假如", "倘若", "一旦", "若是"),
    "time_progression": (
        "与此同时", "片刻后", "不久后", "随后", "然后", "接着", "继而", "后来", "转眼", "次日", "翌日",
    ),
    "hedge": ("似乎", "仿佛", "好像", "大概", "或许", "也许", "可能", "约莫", "隐约", "隐隐"),
    "degree_adverb": ("非常", "极其", "十分", "相当", "格外", "尤其", "有些", "很", "太", "极", "更", "最", "颇", "稍", "略"),
    "modal_particle": ("罢了", "吗", "呢", "吧", "啊", "呀", "嘛", "哦", "啦", "呗"),
    "first_person_pronoun": ("我们", "咱们", "俺们", "咱", "俺", "我"),
    "third_person_pronoun": ("他们", "她们", "它们", "他", "她", "它"),
}

# V1.1 keeps these lightweight proxies local and deterministic while excluding
# common lexical uses demonstrated to dominate real-corpus counts.
FUNCTION_CHAR_EXCLUSIONS = {
    "di": (
        "地方", "地面", "土地", "天地", "境地", "当地", "地上", "地下",
        "大地", "陆地", "地步", "地位", "地板", "地址", "地域", "地带",
        "地形", "目的地",
    ),
    "de_complement": (
        "得到", "获得", "取得", "觉得", "值得", "不得", "记得", "懂得",
        "显得", "免得", "省得", "难得",
    ),
    "le": ("了解", "了然", "了结", "了却", "了望"),
    "zhe": (
        "着火", "着急", "着凉", "着迷", "着陆", "着手", "着重", "着实",
        "执着", "沉着", "衣着",
    ),
    "guo": (
        "经过", "过程", "不过", "过于", "过分", "过去", "过来", "过往",
        "过后", "过度", "过错",
    ),
}


def _compile_longest_match_pattern(words: tuple[str, ...]) -> re.Pattern:
    ordered = sorted(set(words), key=lambda value: (-len(value), value))
    return re.compile("|".join(re.escape(word) for word in ordered))


FUNCTION_WORD_PATTERNS = {
    name: _compile_longest_match_pattern(words)
    for name, words in FUNCTION_WORDS.items()
}

RHYTHM_FEATURE_IDS = (
    "rhythm.sentence_length.mean",
    "rhythm.sentence_length.median",
    "rhythm.sentence_length.std",
    "rhythm.sentence_length.cv",
    "rhythm.sentence_length.p25",
    "rhythm.sentence_length.p75",
    "rhythm.short_sentence_ratio",
    "rhythm.long_sentence_ratio",
    "rhythm.very_long_sentence_ratio",
    "rhythm.adjacent_length_delta",
    "rhythm.paragraph_length.mean",
    "rhythm.paragraph_length.cv",
    "rhythm.single_sentence_paragraph_ratio",
    "rhythm.sentences_per_paragraph.mean",
)

PUNCTUATION_FEATURE_IDS = (
    "punctuation.total_per_kchar",
    "punctuation.comma_per_kchar",
    "punctuation.period_per_kchar",
    "punctuation.comma_period_ratio",
    "punctuation.semicolon_per_kchar",
    "punctuation.colon_per_kchar",
    "punctuation.question_per_kchar",
    "punctuation.exclamation_per_kchar",
    "punctuation.ellipsis_per_kchar",
    "punctuation.dash_per_kchar",
    "punctuation.parentheses_per_kchar",
    "punctuation.quote_coverage_ratio",
)

FUNCTION_FEATURE_IDS = (
    "function.de_per_kchar",
    "function.di_per_kchar",
    "function.de_complement_per_kchar",
    "function.le_per_kchar",
    "function.zhe_per_kchar",
    "function.guo_per_kchar",
    "function.negation_per_kchar",
    "function.contrast_per_kchar",
    "function.causal_per_kchar",
    "function.conditional_per_kchar",
    "function.time_progression_per_kchar",
    "function.hedge_per_kchar",
    "function.degree_adverb_per_kchar",
    "function.modal_particle_per_kchar",
    "function.first_person_pronoun_per_kchar",
    "function.third_person_pronoun_per_kchar",
    "syntax.ba_marker_per_kchar",
    "syntax.bei_marker_per_kchar",
)

STYLE_FEATURE_IDS = RHYTHM_FEATURE_IDS + PUNCTUATION_FEATURE_IDS + FUNCTION_FEATURE_IDS


def _round(value: float | int | None) -> float | int | None:
    if value is None or isinstance(value, int):
        return value
    return round(value, OUTPUT_DECIMAL_PLACES)


def _is_valid_char(char: str) -> bool:
    category = unicodedata.category(char)
    return category.startswith("L") or category == "Nd"


def _valid_char_count(text: str) -> int:
    return sum(_is_valid_char(char) for char in text)


def count_valid_characters(text: str) -> int:
    """按 Style Feature V1 口径统计有效字符，供窗口服务复用。"""
    if not isinstance(text, str):
        raise TypeError("text 必须是字符串")
    return _valid_char_count(text)


def _normalize_text(text: str) -> str:
    if text.startswith("\ufeff"):
        text = text[1:]
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = []
    for line in text.split("\n"):
        normalized = " ".join(line.replace("\u3000", " ").replace("\xa0", " ").split())
        lines.append(normalized.strip())
    return "\n".join(lines)


def _logical_text(text: str) -> str:
    text = ELLIPSIS_RE.sub(ELLIPSIS_TOKEN, text)
    return DASH_RE.sub(DASH_TOKEN, text)


def _is_ascii_alnum(char: str) -> bool:
    return char.isascii() and char.isalnum()


def _ascii_token_before(text: str, index: int) -> str:
    start = index
    while start > 0 and (text[start - 1].isascii() and (text[start - 1].isalpha() or text[start - 1] == ".")):
        start -= 1
    return text[start:index].lower()


def _is_ascii_abbreviation(text: str, index: int) -> bool:
    token = _ascii_token_before(text, index)
    if token in ASCII_ABBREVIATIONS:
        return True
    parts = token.split(".")
    return len(parts) > 1 and all(len(part) == 1 and part.isalpha() for part in parts)


def _is_terminal_period(text: str, index: int) -> bool:
    if text[index] != ".":
        return False
    previous = text[index - 1] if index else ""
    following = text[index + 1] if index + 1 < len(text) else ""
    if previous and following and _is_ascii_alnum(previous) and _is_ascii_alnum(following):
        return False
    if _is_ascii_abbreviation(text, index):
        return False
    cursor = index + 1
    while cursor < len(text) and text[cursor] in CLOSING_MARKS:
        cursor += 1
    return cursor == len(text) or text[cursor].isspace()


def _sentence_lengths(paragraphs: list[str]) -> tuple[list[int], list[int]]:
    sentence_lengths = []
    sentence_counts_by_paragraph = []
    for paragraph in paragraphs:
        logical = _logical_text(paragraph)
        current_length = 0
        paragraph_sentence_count = 0
        index = 0
        while index < len(logical):
            char = logical[index]
            if _is_valid_char(char):
                current_length += 1
                index += 1
                continue
            if char in "。！？!?":
                match = TERMINATOR_RUN_RE.match(logical, index)
                index = match.end() if match else index + 1
                if current_length:
                    sentence_lengths.append(current_length)
                    paragraph_sentence_count += 1
                    current_length = 0
                continue
            if char == ELLIPSIS_TOKEN or _is_terminal_period(logical, index):
                if current_length:
                    sentence_lengths.append(current_length)
                    paragraph_sentence_count += 1
                    current_length = 0
            index += 1
        if current_length >= 2:
            sentence_lengths.append(current_length)
            paragraph_sentence_count += 1
        sentence_counts_by_paragraph.append(paragraph_sentence_count)
    return sentence_lengths, sentence_counts_by_paragraph


def _percentile(values: list[int], probability: float) -> float:
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    fraction = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * fraction


def _rate(count: int, valid_chars: int, minimum: int) -> float | None:
    if valid_chars < minimum:
        return None
    return count / valid_chars * 1000


def _count_word_group(text: str, group: str) -> int:
    return sum(1 for _ in FUNCTION_WORD_PATTERNS[group].finditer(text))


def _is_modal_position(text: str, end: int) -> bool:
    cursor = end
    while cursor < len(text) and (text[cursor].isspace() or text[cursor] in CLOSING_MARKS):
        cursor += 1
    return cursor == len(text) or text[cursor] in MODAL_FOLLOW_MARKS


def _count_modal_particles(text: str) -> int:
    return sum(
        _is_modal_position(text, match.end())
        for match in FUNCTION_WORD_PATTERNS["modal_particle"].finditer(text)
    )


def _paired_intervals(text: str) -> tuple[list[tuple[int, int]], int]:
    intervals = []
    stack = []
    reverse = {closing: opening for opening, closing in QUOTE_PAIRS.items()}
    quote_mark_count = 0
    for index, char in enumerate(text):
        if char == '"':
            quote_mark_count += 1
            if stack and stack[-1][0] == char:
                _, opening_index = stack.pop()
                intervals.append((opening_index + 1, index))
            else:
                stack.append((char, index))
        elif char in QUOTE_PAIRS:
            quote_mark_count += 1
            stack.append((char, index))
        elif char in reverse:
            quote_mark_count += 1
            opening = reverse[char]
            if stack and stack[-1][0] == opening:
                _, opening_index = stack.pop()
                intervals.append((opening_index + 1, index))
    return intervals, quote_mark_count


def _quote_coverage(text: str, valid_chars: int) -> float:
    intervals, _ = _paired_intervals(text)
    if not intervals or not valid_chars:
        return 0.0
    covered = bytearray(len(text))
    for start, end in intervals:
        covered[start:end] = b"\x01" * (end - start)
    count = sum(bool(covered[index]) and _is_valid_char(char) for index, char in enumerate(text))
    return count / valid_chars


def _count_parentheses(text: str) -> int:
    matched = 0
    unmatched_closing = 0
    stack = []
    reverse = {closing: opening for opening, closing in PAREN_PAIRS.items()}
    for char in text:
        if char in PAREN_PAIRS:
            stack.append(char)
        elif char in reverse:
            opening = reverse[char]
            if stack and stack[-1] == opening:
                stack.pop()
                matched += 1
            else:
                unmatched_closing += 1
    return matched + unmatched_closing + len(stack)


def _punctuation_counts(text: str) -> dict[str, int]:
    logical = _logical_text(text)
    terminal_runs = TERMINATOR_RUN_RE.findall(logical)
    question = sum(any(char in QUESTION_MARKS for char in run) for run in terminal_runs)
    exclamation = sum(any(char in EXCLAMATION_MARKS for char in run) for run in terminal_runs)
    period = text.count("。")
    for index, char in enumerate(logical):
        if char == "." and _is_terminal_period(logical, index):
            period += 1
    _, quote_marks = _paired_intervals(text)
    counts = {
        "comma": sum(text.count(mark) for mark in COMMA_MARKS),
        "period": period,
        "semicolon": sum(text.count(mark) for mark in SEMICOLON_MARKS),
        "colon": sum(text.count(mark) for mark in COLON_MARKS),
        "question": question,
        "exclamation": exclamation,
        "ellipsis": logical.count(ELLIPSIS_TOKEN),
        "dash": logical.count(DASH_TOKEN),
        "parentheses": _count_parentheses(text),
        "quotes": quote_marks,
    }
    # Quote coverage already represents dialogue punctuation. Excluding quote
    # marks avoids counting one pair as two extra total-punctuation events.
    counts["total"] = sum(value for name, value in counts.items() if name != "quotes")
    return counts


def _count_char_proxy(text: str, char: str, exclusions: tuple[str, ...] = ()) -> int:
    excluded_positions = set()
    for word in exclusions:
        start = 0
        while True:
            index = text.find(word, start)
            if index < 0:
                break
            excluded_positions.update(
                index + offset for offset, value in enumerate(word) if value == char
            )
            start = index + 1
    return sum(value == char and index not in excluded_positions for index, value in enumerate(text))


def _count_ba_markers(text: str) -> int:
    excluded_previous = frozenset("一两几这那哪每")
    return sum(char == "把" and (index == 0 or text[index - 1] not in excluded_previous) for index, char in enumerate(text))


def _count_bei_markers(text: str) -> int:
    excluded_words = ("被子", "被褥", "被单", "棉被")
    excluded_positions = set()
    for word in excluded_words:
        start = 0
        while True:
            index = text.find(word, start)
            if index < 0:
                break
            excluded_positions.add(index + word.index("被"))
            start = index + len(word)
    return sum(char == "被" and index not in excluded_positions for index, char in enumerate(text))


def _rhythm_features(
    sentence_lengths: list[int], paragraph_lengths: list[int], sentence_counts_by_paragraph: list[int]
) -> dict[str, float | None]:
    sentence_count = len(sentence_lengths)
    paragraph_count = len(paragraph_lengths)
    sentence_mean = statistics.fmean(sentence_lengths) if sentence_lengths else 0.0
    paragraph_mean = statistics.fmean(paragraph_lengths) if paragraph_lengths else 0.0
    features = {feature_id: None for feature_id in RHYTHM_FEATURE_IDS}
    if sentence_count >= MIN_SENTENCES_MEAN:
        features["rhythm.sentence_length.mean"] = sentence_mean
    if sentence_count >= MIN_SENTENCES_MEDIAN:
        features["rhythm.sentence_length.median"] = statistics.median(sentence_lengths)
    if sentence_count >= MIN_SENTENCES_DISTRIBUTION:
        sentence_std = statistics.pstdev(sentence_lengths)
        features.update({
            "rhythm.sentence_length.std": sentence_std,
            "rhythm.sentence_length.cv": sentence_std / sentence_mean if sentence_mean else None,
            "rhythm.sentence_length.p25": _percentile(sentence_lengths, 0.25),
            "rhythm.sentence_length.p75": _percentile(sentence_lengths, 0.75),
            "rhythm.short_sentence_ratio": sum(length <= SHORT_SENTENCE_MAX for length in sentence_lengths) / sentence_count,
            "rhythm.long_sentence_ratio": sum(length >= LONG_SENTENCE_MIN for length in sentence_lengths) / sentence_count,
            "rhythm.very_long_sentence_ratio": sum(length >= VERY_LONG_SENTENCE_MIN for length in sentence_lengths) / sentence_count,
        })
    if sentence_count >= MIN_SENTENCES_ADJACENT and sentence_mean:
        changes = [abs(current - previous) for previous, current in zip(sentence_lengths, sentence_lengths[1:])]
        features["rhythm.adjacent_length_delta"] = statistics.fmean(changes) / sentence_mean
    if paragraph_count >= MIN_PARAGRAPHS_MEAN:
        features["rhythm.paragraph_length.mean"] = paragraph_mean
    if paragraph_count >= MIN_PARAGRAPHS_DISTRIBUTION and paragraph_mean:
        features["rhythm.paragraph_length.cv"] = statistics.pstdev(paragraph_lengths) / paragraph_mean
        features["rhythm.single_sentence_paragraph_ratio"] = (
            sum(count == 1 for count in sentence_counts_by_paragraph) / paragraph_count
        )
    if paragraph_count >= MIN_PARAGRAPHS_MEAN and sentence_count >= MIN_SENTENCES_MEAN:
        features["rhythm.sentences_per_paragraph.mean"] = sentence_count / paragraph_count
    return features


def _punctuation_features(text: str, valid_chars: int) -> dict[str, float | None]:
    features = {feature_id: None for feature_id in PUNCTUATION_FEATURE_IDS}
    if valid_chars < MIN_CHARS_PUNCTUATION:
        return features
    counts = _punctuation_counts(text)
    for name in ("total", "comma", "period", "semicolon", "colon", "question", "exclamation", "ellipsis", "dash", "parentheses"):
        features[f"punctuation.{name}_per_kchar"] = _rate(counts[name], valid_chars, MIN_CHARS_PUNCTUATION)
    if counts["period"] >= MIN_PERIODS_FOR_RATIO:
        features["punctuation.comma_period_ratio"] = counts["comma"] / counts["period"]
    features["punctuation.quote_coverage_ratio"] = _quote_coverage(text, valid_chars)
    return features


def _function_features(text: str, valid_chars: int) -> dict[str, float | None]:
    features = {feature_id: None for feature_id in FUNCTION_FEATURE_IDS}
    if valid_chars >= MIN_CHARS_FUNCTION:
        proxy_chars = {
            "de": "的", "di": "地", "de_complement": "得",
            "le": "了", "zhe": "着", "guo": "过",
        }
        raw_counts = {
            name: _count_char_proxy(text, char, FUNCTION_CHAR_EXCLUSIONS.get(name, ()))
            for name, char in proxy_chars.items()
        }
        for name in ("negation", "contrast", "causal", "conditional", "time_progression", "hedge", "degree_adverb"):
            raw_counts[name] = _count_word_group(text, name)
        raw_counts["modal_particle"] = _count_modal_particles(text)
        raw_counts["first_person_pronoun"] = _count_word_group(text, "first_person_pronoun")
        raw_counts["third_person_pronoun"] = _count_word_group(text, "third_person_pronoun")
        for name, count in raw_counts.items():
            features[f"function.{name}_per_kchar"] = _rate(count, valid_chars, MIN_CHARS_FUNCTION)
    if valid_chars >= MIN_CHARS_SYNTAX:
        features["syntax.ba_marker_per_kchar"] = _rate(_count_ba_markers(text), valid_chars, MIN_CHARS_SYNTAX)
        features["syntax.bei_marker_per_kchar"] = _rate(_count_bei_markers(text), valid_chars, MIN_CHARS_SYNTAX)
    return features


def analyze_style_features(text: str) -> dict:
    """提取 Style Feature V1.1 raw 数值，不访问网络、数据库或其他业务服务。"""
    if not isinstance(text, str):
        raise TypeError("text 必须是字符串")

    normalized_text = _normalize_text(text)
    paragraphs = [line for line in normalized_text.split("\n") if line]
    valid_chars = _valid_char_count(normalized_text)
    paragraph_lengths = [_valid_char_count(paragraph) for paragraph in paragraphs]
    sentence_lengths, sentence_counts_by_paragraph = _sentence_lengths(paragraphs)

    features = {feature_id: None for feature_id in STYLE_FEATURE_IDS}
    features.update(_rhythm_features(sentence_lengths, paragraph_lengths, sentence_counts_by_paragraph))
    features.update(_punctuation_features(normalized_text, valid_chars))
    features.update(_function_features(normalized_text, valid_chars))

    return {
        "style_feature_version": STYLE_FEATURE_VERSION,
        "statistics": {
            "valid_char_count": valid_chars,
            "sentence_count": len(sentence_lengths),
            "paragraph_count": len(paragraphs),
        },
        "features": {feature_id: _round(features[feature_id]) for feature_id in STYLE_FEATURE_IDS},
    }
