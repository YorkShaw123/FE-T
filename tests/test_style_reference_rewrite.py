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
from database import db  # noqa: E402
from database.models import GenerationRecord, PromptTemplate  # noqa: E402
from services import generation_service  # noqa: E402
from services.token_budget import calculate_token_budget  # noqa: E402
from routes.support.generation_request import GenerationRequest  # noqa: E402


class FakeClient:
    def __init__(self, contents):
        self.contents = iter(contents)
        self.calls = []

    def generate(self, **kwargs):
        self.calls.append(kwargs)
        result = next(self.contents)
        if isinstance(result, dict):
            return result
        return {'content': result, 'reasoning_content': ''}


@pytest.fixture
def app():
    return create_app('production')


def run_sync(client, *, style_reference=False, deai=False, corpus_ids=()):
    return generation_service._generate_sync_flow(
        client, 'deepseek-v4-pro', [{'role': 'user', 'content': '写一个故事'}],
        False, 'high', 0, {}, deai, '', '写一个故事', [], '测试', 'deepseek',
        'smart', '{}', {'selected_excerpts': []}, 'dialogue', style_reference,
        corpus_ids, '',
    )


def test_disabled_mode_does_not_retrieve_or_add_llm_call(app, monkeypatch):
    monkeypatch.setattr(
        generation_service,
        'hybrid_search_style',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('不应检索')),
    )
    with app.app_context():
        client = FakeClient(['初稿'])
        result = run_sync(client)

        assert len(client.calls) == 1
        assert result['final_content'] == '初稿'
        assert result['style_rewrite_status'] == 'disabled'


def test_empty_story_falls_back_to_reasoning_text(app):
    with app.app_context():
        client = FakeClient([{
            'content': '\u200b\n---',
            'reasoning_content': '雨停以后，她终于推开了那扇门。',
        }])
        result = run_sync(client)

        assert result['first_content'] == '雨停以后，她终于推开了那扇门。'
        assert result['final_content'] == '雨停以后，她终于推开了那扇门。'
        assert result['reasoning_fallback'] is True


def test_enabled_without_corpus_safely_skips(app):
    with app.app_context():
        client = FakeClient(['初稿'])
        result = run_sync(client, style_reference=True)

        assert len(client.calls) == 1
        assert result['style_rewrite_status'] == 'no_corpus_selected'
        assert result['final_content'] == '初稿'


def test_style_reference_retrieves_after_draft_and_rewrites_once(app, monkeypatch):
    queries = []

    def search(query_text, **kwargs):
        queries.append((query_text, kwargs))
        return ([{
            'id': 9, 'corpus_id': 3, 'corpus_name': '作者语料',
            'content': '雨在旧瓦上缓慢地响。', 'scene_type': 'dialogue',
            'char_count': 10, 'score': 0.91, 'reasons': ['节奏接近'],
        }], {'mode': 'style_rag'})

    monkeypatch.setattr(generation_service, 'hybrid_search_style', search)
    with app.app_context():
        client = FakeClient(['初稿', '风格参考终稿'])
        result = run_sync(client, style_reference=True, corpus_ids=(3,))
        record = GenerationRecord.query.one()

        assert queries[0][0] == '初稿'
        assert queries[0][1]['corpus_ids'] == (3,)
        assert len(client.calls) == 2
        instruction = client.calls[1]['messages'][-1]['content']
        for phrase in ('剧情', '事实', '人物', '世界观', '只允许调整', '不得复制', '雨在旧瓦'):
            assert phrase in instruction
        assert result['style_reference_content'] == '风格参考终稿'
        assert result['final_content'] == '风格参考终稿'
        assert record.style_rewrite_content == '风格参考终稿'
        assert record.style_rewrite_count == 1


def test_style_reference_uses_latest_naturalized_text(app, monkeypatch):
    queries = []

    def search(query_text, **_kwargs):
        queries.append(query_text)
        return ([{'id': 1, 'corpus_id': 2, 'content': '参考片段'}], {'mode': 'style_rag'})

    monkeypatch.setattr(generation_service, 'hybrid_search_style', search)
    with app.app_context():
        client = FakeClient(['初稿', '自然化稿', '风格参考终稿'])
        result = run_sync(client, style_reference=True, deai=True, corpus_ids=(2,))

        assert queries == ['自然化稿']
        assert len(client.calls) == 3
        assert result['final_content'] == '风格参考终稿'


def test_token_budget_includes_style_reference_phase():
    normal = calculate_token_budget('短提示', 'deepseek', 'deepseek-v4-pro')
    enabled = calculate_token_budget(
        '短提示', 'deepseek', 'deepseek-v4-pro', style_reference_enabled=True
    )

    assert 'style_reference' not in normal['phases']
    assert enabled['phases']['style_reference']['input_tokens'] > normal['phases']['primary']['input_tokens']


def test_preview_keeps_corpus_out_of_initial_style_card_prompt(monkeypatch):
    captured = []

    def build(**kwargs):
        captured.append(kwargs)
        return ([{'role': 'user', 'content': '仅含 Style Card 的初稿提示'}], {})

    monkeypatch.setattr(generation_service, '_build_smart_style_messages', build)
    template = SimpleNamespace(
        is_active=True, category='example', content='范例', id=1,
    )
    preview = generation_service.get_assembled_preview(
        [template], style_mode='smart', style_corpus_ids=(7,),
        style_reference_enabled=True,
    )
    initial_only = generation_service.get_assembled_preview(
        [template], style_mode='smart', style_corpus_ids=(7,),
        style_reference_enabled=False,
    )

    assert captured[0]['style_corpus_ids'] == ()
    assert preview['initial_prompt'].endswith('仅含 Style Card 的初稿提示')
    assert preview['assembled_prompt'] == preview['initial_prompt']
    assert '<style_references>' not in preview['assembled_prompt']
    assert preview['style_reference_plan']['dynamic'] is True
    assert preview['style_reference_plan']['corpus_ids'] == [7]
    assert (
        preview['token_budget']['phases']['primary']['input_tokens']
        == initial_only['token_budget']['phases']['primary']['input_tokens']
    )


def test_actual_smart_draft_does_not_retrieve_style_corpus(app, monkeypatch):
    captured = []
    client = FakeClient(['初稿'])

    class ClientFactory:
        @staticmethod
        def validate_model(_provider, _model):
            return True

        def __new__(cls, **_kwargs):
            return client

    def build(**kwargs):
        captured.append(kwargs)
        return ([{'role': 'user', 'content': 'Style Card 初稿提示'}], {})

    monkeypatch.setattr(generation_service, 'LLMClient', ClientFactory)
    monkeypatch.setattr(generation_service, '_build_smart_style_messages', build)
    template = SimpleNamespace(
        is_active=True, category='example', content='范例', id=1,
    )
    with app.app_context():
        result = generation_service.generate_article(
            [template], 'test-key', style_mode='smart',
            style_corpus_ids=(7,), style_reference_enabled=False,
        )

    assert captured[0]['style_corpus_ids'] == ()
    assert len(client.calls) == 1
    assert client.calls[0]['messages'][-1]['content'] == 'Style Card 初稿提示'
    assert result['final_content'] == '初稿'


def test_legacy_strict_field_maps_to_new_style_reference_switch(monkeypatch):
    monkeypatch.setattr(GenerationRequest, 'load_templates', lambda _self: [])
    request = GenerationRequest.from_mapping({'strict_style_rewrite_enabled': True})

    assert request.style_reference_enabled is True
    assert request.generation_kwargs(stream=False)['style_reference_enabled'] is True


def test_generate_stream_http_executes_draft_deai_then_rag_reference(app, monkeypatch):
    """运行真实 Flask/SSE 路由，验证三次模型调用与 RAG 的实际执行顺序。"""
    outputs = iter(('初稿运行态', '自然化运行态', '风格参考终稿运行态'))
    calls = []
    retrieval_queries = []

    class StreamingClient:
        @staticmethod
        def validate_model(_provider, _model):
            return True

        def __init__(self, **_kwargs):
            pass

        def configure_generation_params(self, params, **_kwargs):
            calls.append(params)
            return params

        def generate_stream_aggregated(self, _params):
            content = next(outputs)
            yield {'type': 'content', 'data': content}
            yield {'type': 'done', 'result': {'finish_reason': 'stop'}}

    def retrieve(query_text, **kwargs):
        retrieval_queries.append((query_text, kwargs))
        return ([{
            'id': 11,
            'corpus_id': 42,
            'corpus_name': '运行态作者语料',
            'content': '雨丝斜斜地落在旧瓦上。',
            'scene_type': 'narration',
            'score': 0.93,
        }], {'mode': 'style_rag'})

    monkeypatch.setattr(generation_service, 'LLMClient', StreamingClient)
    monkeypatch.setattr(generation_service, 'hybrid_search_style', retrieve)

    with app.app_context():
        db.session.query(GenerationRecord).delete()
        db.session.query(PromptTemplate).delete()
        template = PromptTemplate(
            name='运行态剧情模板', category='plot', content='写一段雨夜归家的故事。',
            variables='[]', is_active=True,
        )
        db.session.add(template)
        db.session.commit()
        template_id = template.id

    response = app.test_client().post(
        '/api/generation/generate-stream',
        json={
            'api_key': 'test-key',
            'provider': 'deepseek',
            'model': 'deepseek-v4-pro',
            'template_ids': [template_id],
            'deai_enabled': True,
            'deai_prompt': '让语言自然一些。',
            'style_reference_enabled': True,
            'style_corpus_ids': [42],
        },
    )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert body.index('初稿运行态') < body.index('deai_start')
    assert body.index('自然化运行态') < body.index('style_reference_retrieving')
    assert body.index('style_reference_retrieving') < body.index('style_reference_start')
    assert body.index('style_reference_start') < body.index('风格参考终稿运行态')
    assert body.index('风格参考终稿运行态') < body.index('event: complete')
    assert '"reference_count": 1' in body
    assert retrieval_queries[0][0] == '自然化运行态'
    assert retrieval_queries[0][1]['corpus_ids'] == (42,)
    assert len(calls) == 3
    assert '雨丝斜斜地落在旧瓦上。' not in str(calls[0]['messages'])
    assert '雨丝斜斜地落在旧瓦上。' not in str(calls[1]['messages'])
    assert '雨丝斜斜地落在旧瓦上。' in str(calls[2]['messages'])
    assert '"final_content": "风格参考终稿运行态"' in body


def test_preview_http_never_executes_rag_retrieval(app, monkeypatch):
    """右栏预览只组装说明和预算，不能加载百万字语料检索。"""
    monkeypatch.setattr(
        generation_service,
        'hybrid_search_style',
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError('预览不应检索 RAG')),
    )
    with app.app_context():
        db.session.query(PromptTemplate).delete()
        template = PromptTemplate(
            name='预览模板', category='plot', content='只组装初稿提示词。',
            variables='[]', is_active=True,
        )
        db.session.add(template)
        db.session.commit()
        template_id = template.id

    response = app.test_client().post(
        '/api/generation/preview-prompt',
        json={
            'template_ids': [template_id],
            'style_reference_enabled': True,
            'style_corpus_ids': [42],
        },
    )

    payload = response.get_json()
    assert response.status_code == 200
    assert payload['success'] is True
    assert '<style_references>' not in payload['data']['assembled_prompt']
    assert payload['data']['style_reference_plan'] == {
        'dynamic': True,
        'corpus_ids': [42],
        'message': '初稿完成后，系统将以最新正文检索所选语料库，把真实命中的 3～5 个片段写入第二次模型请求。',
    }
    assert 'style_reference' in payload['data']['token_budget']['phases']
