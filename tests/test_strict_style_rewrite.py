import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = PROJECT_ROOT / 'server'
sys.path.insert(0, str(SERVER_DIR))
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from app import create_app  # noqa: E402
from database.models import GenerationRecord  # noqa: E402
from services import generation_service  # noqa: E402
from services.token_budget import calculate_token_budget  # noqa: E402


class FakeClient:
    def __init__(self, contents):
        self.contents = iter(contents)
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        return {'content': next(self.contents), 'reasoning_content': ''}


@pytest.fixture
def app():
    return create_app('production')


def run_sync(client, *, strict=False, deai=False, prepare=None):
    original_prepare = generation_service._prepare_strict_style_rewrite
    if prepare is not None:
        generation_service._prepare_strict_style_rewrite = prepare
    try:
        return generation_service._generate_sync_flow(
            client, 'deepseek-v4-pro', [{'role': 'user', 'content': '写一个故事'}],
            False, 'high', deai, '', '写一个故事', [], {}, '测试', 'deepseek',
            'smart', '{}', {'selected_excerpts': [{'corpus_id': 1}]},
            'dialogue', strict,
        )
    finally:
        generation_service._prepare_strict_style_rewrite = original_prepare


def test_disabled_mode_does_not_analyze_or_add_llm_call(app):
    def unexpected_prepare(*_args):
        raise AssertionError('disabled mode must not run Style Diff')

    with app.app_context():
        client = FakeClient(['初稿'])
        result = run_sync(client, strict=False, prepare=unexpected_prepare)

        assert len(client.calls) == 1
        assert result['final_content'] == '初稿'
        assert result['style_rewrite_status'] == 'disabled'


def test_close_diff_skips_rewrite_call(app):
    def close_prepare(*_args):
        return {'difference_count': 0, 'differences': []}, None, 'already_close'

    with app.app_context():
        client = FakeClient(['已经接近目标的稿件'])
        result = run_sync(client, strict=True, prepare=close_prepare)

        assert len(client.calls) == 1
        assert result['style_rewrite_content'] == ''
        assert result['style_rewrite_status'] == 'already_close'


def test_significant_diff_rewrites_exactly_once_and_persists_final(app):
    rewrite_messages = [
        {'role': 'user', 'content': '原要求'},
        {'role': 'assistant', 'content': '初稿'},
        {'role': 'user', 'content': '只调整节奏'},
    ]

    def significant_prepare(*_args):
        return {'difference_count': 1, 'differences': [{'feature_id': 'x'}]}, rewrite_messages, 'ready'

    with app.app_context():
        client = FakeClient(['初稿', '严格文风终稿'])
        result = run_sync(client, strict=True, prepare=significant_prepare)
        record = GenerationRecord.query.one()

        assert len(client.calls) == 2
        assert client.calls[1]['messages'] == rewrite_messages
        assert client.calls[1]['thinking_enabled'] is False
        assert result['final_content'] == '严格文风终稿'
        assert record.style_rewrite_content == '严格文风终稿'
        assert record.style_rewrite_count == 1
        assert record.to_dict()['final_content'] == '严格文风终稿'


def test_diff_uses_latest_deai_draft_and_still_rewrites_only_once(app):
    analyzed = []

    def prepare(draft, *_args):
        analyzed.append(draft)
        return {'difference_count': 1}, [{'role': 'user', 'content': 'rewrite'}], 'ready'

    with app.app_context():
        client = FakeClient(['初稿', '去AI味稿', '严格终稿'])
        result = run_sync(client, strict=True, deai=True, prepare=prepare)

        assert analyzed == ['去AI味稿']
        assert len(client.calls) == 3
        assert result['final_content'] == '严格终稿'


def test_rewrite_prompt_contains_preservation_diff_and_anti_copy_rules(monkeypatch):
    profile_record = SimpleNamespace(profile_json=json.dumps({'feature_version': 2}))
    monkeypatch.setattr(
        generation_service, 'get_author_style_profile', lambda _corpus_id: (profile_record, False)
    )
    monkeypatch.setattr(
        generation_service,
        'analyze_style_diff',
        lambda *_args, **_kwargs: {
            'difference_count': 1,
            'differences': [{
                'human_message': '平均句长明显偏短',
                'rewrite_instruction': '合并相邻短句',
            }],
        },
    )
    original_messages = [{'role': 'user', 'content': '<reference_examples>参考片段</reference_examples>'}]

    diff, messages, status = generation_service._prepare_strict_style_rewrite(
        '草稿', original_messages,
        {'selected_excerpts': [{'corpus_id': 7}], 'resolved_scene_type': 'dialogue'},
        'auto',
    )
    instruction = messages[-1]['content']

    assert status == 'ready'
    assert diff['target_corpus_id'] == 7
    assert messages[:1] == original_messages
    assert messages[-2] == {'role': 'assistant', 'content': '草稿'}
    for phrase in ('剧情', '事实', '人物', '世界观', '用户要求', '只允许调整',
                   '平均句长明显偏短', '合并相邻短句', '不得复制', '独特表达'):
        assert phrase in instruction


def test_token_budget_includes_optional_style_rewrite_phase():
    normal = calculate_token_budget('短提示', 'deepseek', 'deepseek-v4-pro')
    strict = calculate_token_budget(
        '短提示', 'deepseek', 'deepseek-v4-pro', strict_style_rewrite_enabled=True
    )

    assert 'style_rewrite' not in normal['phases']
    assert strict['phases']['style_rewrite']['input_tokens'] > strict['phases']['primary']['input_tokens']
