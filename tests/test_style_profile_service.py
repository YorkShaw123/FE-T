import json
import os
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = PROJECT_ROOT / 'server'
sys.path.insert(0, str(SERVER_DIR))
os.environ['DATABASE_URL'] = 'sqlite:///:memory:'

from app import create_app  # noqa: E402
from database import db  # noqa: E402
from database.models import PromptTemplate, StyleExcerpt, StyleProfile  # noqa: E402
from services.errors import GenerationError  # noqa: E402
from services import style_profile_service  # noqa: E402


@pytest.fixture
def app():
    return create_app('production')


def _template(name='style-card-test', content=None):
    template = PromptTemplate(
        name=name,
        category='example',
        content=content or ('雨落在长街上。她没有回头。' * 12),
    )
    db.session.add(template)
    db.session.commit()
    return template


def _card(summary='克制的第三人称叙事'):
    return {
        'summary': summary,
        'narration': {'person': '第三人称'},
        'rhythm': {'sentence_pattern': '长短句交替'},
        'language': {'preferred_behaviors': ['少解释']},
        'dialogue': {'ratio': '低'},
        'description_balance': {'action': '中'},
        'avoid': ['空泛总结'],
        'checkable_rules': [{'rule': '段尾避免总结', 'priority': 'high'}],
    }


class _FakeClient:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error

    def generate(self, **_kwargs):
        if self.error:
            raise self.error
        return self.response


def _patch_client(monkeypatch, *, response=None, error=None):
    monkeypatch.setattr(
        style_profile_service,
        'LLMClient',
        lambda **_kwargs: _FakeClient(response=response, error=error),
    )


def test_analysis_accepts_json_returned_in_reasoning_field(app, monkeypatch):
    with app.app_context():
        template = _template(name='reasoning-json')
        _patch_client(monkeypatch, response={
            'content': '',
            'reasoning_content': json.dumps(_card(), ensure_ascii=False),
        })

        profile = style_profile_service.analyze_style_profile(
            template.id, 'test-key', 'deepseek', 'deepseek-v4-pro',
        )
        stored = json.loads(profile.card_json)

        assert profile.analysis_status == 'ready'
        assert stored['summary'] == '克制的第三人称叙事'
        assert stored['narration']['person'] == '第三人称'
        assert stored['narration']['distance'] == ''
        assert stored['language']['preferred_behaviors'] == ['少解释']


def test_reanalysis_invalidates_excerpts_when_source_changed(app, monkeypatch):
    with app.app_context():
        template = _template(name='source-change')
        old_source_hash = style_profile_service.style_source_hash(template.content)
        profile = StyleProfile(
            template_id=template.id,
            template_version=template.version,
            source_hash=old_source_hash,
            card_json=json.dumps(_card(), ensure_ascii=False),
            analysis_card_json=json.dumps(_card(), ensure_ascii=False),
            analysis_status='ready',
        )
        db.session.add(profile)
        db.session.flush()
        db.session.add(StyleExcerpt(
            style_profile_id=profile.id,
            content='旧参考片段',
            content_hash='old-excerpt',
            source_order=0,
        ))
        template.content = '新的范例正文。' * 30
        db.session.commit()
        _patch_client(monkeypatch, response={
            'content': json.dumps(_card('新风格'), ensure_ascii=False),
            'reasoning_content': '',
        })

        style_profile_service.analyze_style_profile(
            template.id, 'test-key', 'deepseek', 'deepseek-v4-pro',
        )

        assert StyleExcerpt.query.filter_by(style_profile_id=profile.id).count() == 0
        assert profile.source_hash != old_source_hash


def test_failed_reanalysis_keeps_last_successful_card_usable(app, monkeypatch):
    with app.app_context():
        template = _template(name='retry-failure')
        old_card = json.dumps(_card('上次成功结果'), ensure_ascii=False)
        profile = StyleProfile(
            template_id=template.id,
            template_version=template.version,
            source_hash=style_profile_service.style_source_hash(template.content),
            card_json=old_card,
            analysis_card_json=old_card,
            analysis_status='ready',
        )
        db.session.add(profile)
        db.session.commit()
        _patch_client(monkeypatch, error=RuntimeError('temporary upstream failure'))

        with pytest.raises(GenerationError):
            style_profile_service.analyze_style_profile(
                template.id, 'test-key', 'deepseek', 'deepseek-v4-pro',
            )

        db.session.refresh(profile)
        assert profile.analysis_status == 'ready'
        assert json.loads(profile.card_json)['summary'] == '上次成功结果'
        assert profile.error_message


def test_first_analysis_failure_is_reported_as_error(app, monkeypatch):
    with app.app_context():
        template = _template(name='first-failure')
        _patch_client(monkeypatch, error=RuntimeError('temporary upstream failure'))

        with pytest.raises(GenerationError):
            style_profile_service.analyze_style_profile(
                template.id, 'test-key', 'deepseek', 'deepseek-v4-pro',
            )

        profile = StyleProfile.query.filter_by(template_id=template.id).one()
        assert profile.analysis_status == 'error'
        assert json.loads(profile.card_json) == {}


def test_schema_rejects_nested_array_with_wrong_type():
    card = _card()
    card['language']['preferred_behaviors'] = '不应是字符串'

    with pytest.raises(GenerationError, match='language.preferred_behaviors 必须是数组'):
        style_profile_service.validate_style_card(card)


def test_schema_fills_known_defaults_without_dropping_legacy_extensions():
    card = _card()
    card['legacy_extension'] = {'custom_rule': '保留'}

    normalized = style_profile_service.validate_style_card(card)

    assert normalized['narration']['distance'] == ''
    assert normalized['legacy_extension'] == {'custom_rule': '保留'}


def test_restore_corrupt_analysis_card_returns_domain_error(app):
    with app.app_context():
        template = _template(name='corrupt-restore')
        profile = StyleProfile(
            template_id=template.id,
            template_version=template.version,
            source_hash=style_profile_service.style_source_hash(template.content),
            card_json=json.dumps(_card(), ensure_ascii=False),
            analysis_card_json='{broken',
            analysis_status='ready',
        )
        db.session.add(profile)
        db.session.commit()

        with pytest.raises(GenerationError, match='自动分析结果已损坏'):
            style_profile_service.restore_analysis_card(template.id)
