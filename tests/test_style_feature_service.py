import math
import os
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = PROJECT_ROOT / "server"
sys.path.insert(0, str(SERVER_DIR))
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from services.style_feature_service import (  # noqa: E402
    STYLE_FEATURE_IDS,
    STYLE_FEATURE_VERSION,
    analyze_style_features,
)


def feature(result, feature_id):
    return result["features"][feature_id]


def padded_text(prefix, minimum_chars=500):
    prefix_chars = analyze_style_features(prefix)["statistics"]["valid_char_count"]
    return prefix + "甲" * (minimum_chars - prefix_chars)


def test_output_contract_contains_44_stable_raw_features():
    result = analyze_style_features("春风吹过小城。")

    assert result["style_feature_version"] == STYLE_FEATURE_VERSION == 1
    assert len(STYLE_FEATURE_IDS) == len(set(STYLE_FEATURE_IDS)) == 44
    assert tuple(result["features"]) == STYLE_FEATURE_IDS
    assert all(value is None or isinstance(value, (int, float)) for value in result["features"].values())
    assert all(value is None or math.isfinite(value) for value in result["features"].values())


def test_normal_chinese_narration_has_exact_sentence_and_punctuation_values():
    text = ("甲" * 30 + "，" + "乙" * 30 + "。") * 5
    result = analyze_style_features(text)

    assert result["statistics"] == {"valid_char_count": 300, "sentence_count": 5, "paragraph_count": 1}
    assert feature(result, "rhythm.sentence_length.mean") == 60.0
    assert feature(result, "punctuation.comma_per_kchar") == pytest.approx(16.666667)
    assert feature(result, "punctuation.period_per_kchar") == pytest.approx(16.666667)
    assert feature(result, "punctuation.comma_period_ratio") == 1.0


def test_many_short_sentences_have_zero_variance_and_full_short_ratio():
    result = analyze_style_features("甲乙。" * 10)

    assert result["statistics"]["sentence_count"] == 10
    assert feature(result, "rhythm.sentence_length.mean") == 2.0
    assert feature(result, "rhythm.sentence_length.median") == 2.0
    assert feature(result, "rhythm.sentence_length.std") == 0.0
    assert feature(result, "rhythm.sentence_length.cv") == 0.0
    assert feature(result, "rhythm.sentence_length.p25") == 2.0
    assert feature(result, "rhythm.sentence_length.p75") == 2.0
    assert feature(result, "rhythm.short_sentence_ratio") == 1.0
    assert feature(result, "rhythm.long_sentence_ratio") == 0.0
    assert feature(result, "rhythm.very_long_sentence_ratio") == 0.0
    assert feature(result, "rhythm.adjacent_length_delta") == 0.0


def test_many_long_sentences_cross_long_and_very_long_thresholds():
    result = analyze_style_features(("长" * 50 + "。") * 10)

    assert feature(result, "rhythm.sentence_length.mean") == 50.0
    assert feature(result, "rhythm.short_sentence_ratio") == 0.0
    assert feature(result, "rhythm.long_sentence_ratio") == 1.0
    assert feature(result, "rhythm.very_long_sentence_ratio") == 1.0


def test_adjacent_sentence_delta_uses_mean_normalized_absolute_change():
    lengths = (2, 4, 6, 8, 10, 12)
    result = analyze_style_features("".join("甲" * length + "。" for length in lengths))

    assert feature(result, "rhythm.sentence_length.mean") == 7.0
    assert feature(result, "rhythm.adjacent_length_delta") == pytest.approx(2 / 7)


def test_paragraph_features_use_nonempty_physical_lines():
    text = "\n\n".join("甲" * 10 + "。" for _ in range(5))
    result = analyze_style_features(text)

    assert result["statistics"]["paragraph_count"] == 5
    assert feature(result, "rhythm.paragraph_length.mean") == 10.0
    assert feature(result, "rhythm.paragraph_length.cv") == 0.0
    assert feature(result, "rhythm.single_sentence_paragraph_ratio") == 1.0
    assert feature(result, "rhythm.sentences_per_paragraph.mean") == 1.0


def test_dialogue_quote_coverage_counts_paired_content_and_not_delimiters():
    text = "".join("“" + "甲" * 30 + "。”" for _ in range(10))
    result = analyze_style_features(text)

    assert result["statistics"]["valid_char_count"] == 300
    assert feature(result, "punctuation.quote_coverage_ratio") == 1.0
    assert feature(result, "punctuation.period_per_kchar") == pytest.approx(100 / 3)
    assert feature(result, "punctuation.total_per_kchar") == 100.0


def test_unmatched_quote_does_not_cover_the_rest_of_text():
    result = analyze_style_features("“" + "甲" * 300)

    assert feature(result, "punctuation.quote_coverage_ratio") == 0.0


def test_crossed_quotes_only_cover_correctly_nested_pair():
    text = padded_text("“甲「乙”丙」", 300)
    result = analyze_style_features(text)

    assert feature(result, "punctuation.quote_coverage_ratio") == 0.006667


def test_dash_variants_are_each_one_logical_token():
    text = ("甲" * 30 + "——" + "乙" * 30 + "--") * 5
    result = analyze_style_features(text)

    assert result["statistics"]["valid_char_count"] == 300
    assert feature(result, "punctuation.dash_per_kchar") == pytest.approx(100 / 3)


def test_ellipsis_variants_are_each_one_token_and_sentence_boundary():
    text = ("甲" * 20 + "……" + "乙" * 20 + "..." + "丙" * 20 + "⋯⋯") * 5
    result = analyze_style_features(text)

    assert result["statistics"]["valid_char_count"] == 300
    assert result["statistics"]["sentence_count"] == 15
    assert feature(result, "punctuation.ellipsis_per_kchar") == 50.0


def test_repeated_question_and_exclamation_run_has_one_of_each_token():
    text = ("甲" * 60 + "？！!!!") * 5
    result = analyze_style_features(text)

    assert result["statistics"]["sentence_count"] == 5
    assert feature(result, "punctuation.question_per_kchar") == pytest.approx(16.666667)
    assert feature(result, "punctuation.exclamation_per_kchar") == pytest.approx(16.666667)


def test_all_punctuation_features_have_exact_logical_counts():
    unit = "甲" * 60 + "，。；：？！（）"
    result = analyze_style_features(unit * 5)

    assert feature(result, "punctuation.comma_per_kchar") == pytest.approx(16.666667)
    assert feature(result, "punctuation.period_per_kchar") == pytest.approx(16.666667)
    assert feature(result, "punctuation.semicolon_per_kchar") == pytest.approx(16.666667)
    assert feature(result, "punctuation.colon_per_kchar") == pytest.approx(16.666667)
    assert feature(result, "punctuation.question_per_kchar") == pytest.approx(16.666667)
    assert feature(result, "punctuation.exclamation_per_kchar") == pytest.approx(16.666667)
    assert feature(result, "punctuation.parentheses_per_kchar") == pytest.approx(16.666667)
    assert feature(result, "punctuation.total_per_kchar") == pytest.approx(350 / 3)


def test_crossed_parentheses_are_not_counted_as_two_successful_pairs():
    text = ("甲" * 60 + "([)]。") * 5
    result = analyze_style_features(text)

    assert feature(result, "punctuation.parentheses_per_kchar") == 50.0


def test_first_and_third_person_longest_matching_avoids_double_counting():
    text = "我们我他们他" * 100
    result = analyze_style_features(text)

    assert result["statistics"]["valid_char_count"] == 600
    assert feature(result, "function.first_person_pronoun_per_kchar") == pytest.approx(1000 / 3)
    assert feature(result, "function.third_person_pronoun_per_kchar") == pytest.approx(1000 / 3)


def test_function_word_dictionary_and_literal_particles_have_exact_rates():
    prefix = "的地得了着过没有但是因为如果随后似乎非常吧。我他"
    text = padded_text(prefix, 500)
    result = analyze_style_features(text)

    expected_once = (
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
    )
    assert result["statistics"]["valid_char_count"] == 500
    for feature_id in expected_once:
        expected = 4.0 if feature_id == "function.negation_per_kchar" else 2.0
        assert feature(result, feature_id) == expected


def test_modal_particle_only_counts_at_clause_or_sentence_end():
    text = padded_text("吧台不是语气词，他说好吧。你来吗？", 500)
    result = analyze_style_features(text)

    assert feature(result, "function.modal_particle_per_kchar") == 4.0


def test_ba_and_bei_proxy_exclusions_are_applied():
    text = padded_text("我把书放下。一把刀。每把伞。他被风吹倒。被子、被褥、被单和棉被。", 800)
    result = analyze_style_features(text)

    assert feature(result, "syntax.ba_marker_per_kchar") == 1.25
    assert feature(result, "syntax.bei_marker_per_kchar") == 1.25


def test_empty_text_returns_all_missing_features_and_zero_statistics():
    result = analyze_style_features("")

    assert result["statistics"] == {"valid_char_count": 0, "sentence_count": 0, "paragraph_count": 0}
    assert all(value is None for value in result["features"].values())


def test_crlf_and_lf_have_identical_features():
    crlf = "甲乙。\r\n\r\n丙丁。\r\n戊己。"
    lf = crlf.replace("\r\n", "\n")

    assert analyze_style_features(crlf) == analyze_style_features(lf)


def test_very_short_text_keeps_statistics_but_returns_missing_features():
    result = analyze_style_features("甲。")

    assert result["statistics"] == {"valid_char_count": 1, "sentence_count": 1, "paragraph_count": 1}
    assert all(value is None for value in result["features"].values())


def test_punctuation_only_text_has_no_sentence_and_no_available_features():
    result = analyze_style_features("？！……——（）。")

    assert result["statistics"] == {"valid_char_count": 0, "sentence_count": 0, "paragraph_count": 1}
    assert all(value is None for value in result["features"].values())


def test_mixed_chinese_english_and_digits_count_each_letter_or_digit():
    result = analyze_style_features("中文ABC123。")

    assert result["statistics"] == {"valid_char_count": 8, "sentence_count": 1, "paragraph_count": 1}
    assert feature(result, "rhythm.sentence_length.mean") is None


def test_decimal_and_domain_dots_do_not_split_sentences():
    result = analyze_style_features("版本A1.2访问a.com。" * 5)

    assert result["statistics"]["sentence_count"] == 5


def test_english_abbreviation_dot_does_not_split_sentence():
    result = analyze_style_features("Dr. Smith继续前进。" * 30)

    assert result["statistics"]["sentence_count"] == 30


def test_six_dot_ellipsis_is_one_token_and_one_sentence_boundary():
    text = ("甲" * 30 + "......" + "乙" * 30 + "。") * 5
    result = analyze_style_features(text)

    assert result["statistics"]["valid_char_count"] == 300
    assert result["statistics"]["sentence_count"] == 10
    assert feature(result, "punctuation.ellipsis_per_kchar") == pytest.approx(16.666667)
    assert feature(result, "punctuation.period_per_kchar") == pytest.approx(16.666667)


def test_period_inside_quotes_closes_sentence_before_following_narration():
    result = analyze_style_features("他说：“走。”然后离开。" * 5)

    assert result["statistics"]["sentence_count"] == 10


def test_feature_schema_matches_frozen_document_ids():
    document = (PROJECT_ROOT / "docs" / "style-engine" / "STYLE_FEATURE_V1.md").read_text(encoding="utf-8")

    for feature_id in STYLE_FEATURE_IDS:
        assert f"`{feature_id}`" in document
    assert document.count("| `rhythm.") == 14
    assert document.count("| `punctuation.") == 12
    assert document.count("| `function.") + document.count("| `syntax.") == 18


def test_non_string_input_is_rejected():
    with pytest.raises(TypeError, match="text 必须是字符串"):
        analyze_style_features(None)
