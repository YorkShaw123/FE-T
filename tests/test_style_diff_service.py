import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = PROJECT_ROOT / 'server'
sys.path.insert(0, str(SERVER_DIR))
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from services.style_diff_service import analyze_style_diff  # noqa: E402
from services.style_feature_service import (  # noqa: E402
    STYLE_FEATURE_VERSION,
    analyze_style_features,
)


def feature_stats(median, scale, p25, p75, reliability=1.0):
    return {
        'median': median,
        'p25': p25,
        'p75': p75,
        'reliability': reliability,
        'normalization': {'center': median, 'scale': scale},
    }


def profile(features, confidence=1.0, **extra):
    return {
        'feature_version': STYLE_FEATURE_VERSION,
        'confidence': confidence,
        'features': features,
        **extra,
    }


def test_text_close_to_profile_reports_no_difference():
    text = ('这是一个长度比较稳定的普通叙述句子，用来模拟作者日常的行文节奏。' * 3 + '。') * 20
    raw = analyze_style_features(text)['features']
    features = {
        feature_id: feature_stats(value, max(1.0, abs(value) * 0.2), value - 1, value + 1)
        for feature_id, value in raw.items()
        if isinstance(value, (int, float))
    }

    result = analyze_style_diff(text, profile(features))

    assert result['difference_count'] == 0
    assert result['differences'] == []


def test_deliberately_short_sentences_report_length_problems():
    text = '走。停。看。等。' * 160
    features = {
        'rhythm.sentence_length.mean': feature_stats(28.0, 4.0, 22.0, 34.0),
        'rhythm.short_sentence_ratio': feature_stats(0.12, 0.1, 0.05, 0.22),
    }

    result = analyze_style_diff(text, profile(features))
    by_id = {item['feature_id']: item for item in result['differences']}

    assert 'rhythm.sentence_length.mean' in by_id
    assert 'rhythm.short_sentence_ratio' in by_id
    assert by_id['rhythm.sentence_length.mean']['normalized_deviation'] < 0
    assert '偏短' in by_id['rhythm.sentence_length.mean']['human_message']
    assert by_id['rhythm.short_sentence_ratio']['normalized_deviation'] > 0
    assert '合并' in by_id['rhythm.short_sentence_ratio']['rewrite_instruction']


def test_low_reliability_or_short_text_does_not_force_a_conclusion():
    low_reliability = profile({
        'rhythm.sentence_length.mean': feature_stats(40.0, 2.0, 35.0, 45.0, reliability=0.1),
    })
    reliable = profile({
        'rhythm.sentence_length.mean': feature_stats(40.0, 2.0, 35.0, 45.0),
    })
    low_profile_confidence = profile({
        'rhythm.sentence_length.mean': feature_stats(40.0, 2.0, 35.0, 45.0),
    }, confidence=0.2)

    assert analyze_style_diff('走。' * 300, low_reliability)['differences'] == []
    assert analyze_style_diff('走。' * 300, low_profile_confidence)['differences'] == []
    assert analyze_style_diff('走。停。', reliable)['differences'] == []


def test_scene_profile_is_primary_and_global_profile_is_reported_for_context():
    global_stats = feature_stats(40.0, 5.0, 35.0, 45.0)
    scene_stats = feature_stats(20.0, 3.0, 16.0, 24.0)
    author = profile(
        {'rhythm.sentence_length.mean': global_stats},
        mode_profiles={
            'dialogue': profile({'rhythm.sentence_length.mean': scene_stats}),
        },
        broad_profiles={},
    )

    result = analyze_style_diff('走。停。看。等。' * 160, author, scene_type='dialogue')
    difference = result['differences'][0]

    assert result['target_source'] == 'mode'
    assert difference['target_median'] == 20.0
    assert difference['global_median'] == 40.0


def test_output_is_capped_and_deterministic():
    text = '走。停。看。等。' * 160
    raw = analyze_style_features(text)['features']
    features = {
        feature_id: feature_stats(float(value) + 30.0, 1.0, float(value) + 25.0, float(value) + 35.0)
        for feature_id, value in raw.items()
        if isinstance(value, (int, float))
    }

    first = analyze_style_diff(text, profile(features), max_differences=5)
    second = analyze_style_diff(text, profile(features), max_differences=5)

    assert first == second
    assert first['difference_count'] == 5
