import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = PROJECT_ROOT / 'server'
sys.path.insert(0, str(SERVER_DIR))
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from services.style_signature_service import (  # noqa: E402
    STYLE_SIGNATURE_VERSION,
    build_signature_vocabulary,
    extract_signature_patterns,
    vectorize_signature,
)


def test_extracts_only_restricted_function_and_punctuation_patterns():
    counts = extract_signature_patterns('森林里的月光，却没有落下。于是，他似乎是醒了。')

    assert counts[('，', '却')] == 1
    assert counts[('却', '没有')] == 1
    assert counts[('。', '于是')] == 1
    assert counts[('，', '他')] == 1
    assert counts[('似乎', '是')] == 1
    assert all('森林' not in ''.join(pattern) for pattern in counts)
    assert all('月光' not in ''.join(pattern) for pattern in counts)


def test_normalizes_ellipsis_and_dash_without_double_counting():
    counts = extract_signature_patterns('……却没有——只是......却没有--只是')

    assert counts[('……', '却')] == 2
    assert counts[('没有', '——')] == 2


def test_vocabulary_removes_sparse_and_ubiquitous_patterns_deterministically():
    windows = []
    for index in range(8):
        text = '但是。'
        if index < 4:
            text += '，却没有。'
        if index == 0:
            text += '，仿佛。'
        windows.append(text)

    first = build_signature_vocabulary(windows)
    second = build_signature_vocabulary(windows)
    patterns = {entry['pattern'] for entry in first}

    assert first == second
    assert '但是' not in patterns
    assert '，仿佛' not in patterns
    assert '，却' in patterns
    assert len(first) < 128


def test_vector_is_per_thousand_valid_characters_and_version_is_fixed():
    vocabulary = [{
        'id': 'signature.000', 'pattern': '，却', 'tokens': ['，', '却'],
        'total_count': 3, 'document_count': 2, 'document_ratio': 0.5,
    }]
    vector = vectorize_signature('甲，却乙，却丙丁', vocabulary)

    assert STYLE_SIGNATURE_VERSION == 1
    assert vector['signature.000'] == 333.333333
