"""P1 记录路由 + 模型工厂测试。

记录没有创建接口（生成时由写作链路写入），所以这里直接用 sqlite3 往隔离库里
插一条记录，再走 HTTP 接口，避免用异步引擎在测试里绕两个事件循环。

模型工厂全部离线验证：只检查构造出来的参数形状，不发任何网络请求。
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import pytest
from langchain_openai import ChatOpenAI

from backend.adapters.llm_openai_compat import (
    build_chat_model,
    normalize_sampling,
    thinking_kwargs,
)
from backend.config import get_settings
from backend.core.llm_factory import LLMFactory


def _seed_record(title: str, *, pinned: bool = False, content: str = '正文') -> int:
    db_path = get_settings().database_path
    stamp = datetime.now(timezone.utc).isoformat(sep=' ')
    with sqlite3.connect(db_path) as connection:
        cursor = connection.execute(
            'INSERT INTO generation_records '
            '(title, content, model_used, pinned, style_rewrite_enabled, '
            ' style_rewrite_applied, style_rewrite_count, style_mode, created_at) '
            'VALUES (?, ?, ?, ?, 0, 0, 0, ?, ?)',
            (title, content, 'deepseek-v4-flash', 1 if pinned else 0, 'legacy', stamp),
        )
        return int(cursor.lastrowid)


def _seed_many(count: int, prefix: str = '记录') -> list[int]:
    ids = [_seed_record(f'{prefix}{index}') for index in range(count)]
    # 用 pinned 打乱顺序，验证列表的排序规则
    if ids:
        db_path = get_settings().database_path
        with sqlite3.connect(db_path) as connection:
            connection.execute(
                'UPDATE generation_records SET pinned = 1 WHERE id = ?', (ids[0],)
            )
    return ids


def test_list_records_pagination_and_order(api_client):
    ids = _seed_many(3)
    body = api_client.get('/api/v1/records?per_page=2').json()
    assert body['success'] is True
    data = body['data']
    assert data['total'] == 3
    assert data['pages'] == 2
    assert data['current_page'] == 1
    assert len(data['items']) == 2
    assert data['items'][0]['id'] == ids[0]  # 置顶排最前
    assert 'content_preview' in data['items'][0]


def test_per_page_is_clamped(api_client):
    _seed_many(2)
    assert api_client.get('/api/v1/records?per_page=999').json()['data']['items']
    clamped = api_client.get('/api/v1/records?per_page=999').json()['data']
    assert clamped['pages'] == 1


def test_get_single_record(api_client):
    record_id = _seed_record('单独读取', content='这是正文内容')
    body = api_client.get(f'/api/v1/records/{record_id}').json()
    assert body['data']['title'] == '单独读取'
    assert body['data']['final_content'] == '这是正文内容'
    assert body['data']['pinned'] in (False, 0)

    missing = api_client.get('/api/v1/records/9999')
    assert missing.status_code == 404
    assert missing.json() == {'success': False, 'error': '记录不存在'}


def test_update_record_fields(api_client):
    record_id = _seed_record('待修改')
    body = api_client.put(
        f'/api/v1/records/{record_id}',
        json={'title': '改过标题', 'rating': 5, 'pinned': True, 'notes': '备注'},
    ).json()
    assert body['success'] is True
    assert body['data']['title'] == '改过标题'
    assert body['data']['rating'] == 5
    assert body['data']['pinned'] is True


def test_update_rejects_unknown_field(api_client):
    record_id = _seed_record('待修改')
    response = api_client.put(
        f'/api/v1/records/{record_id}', json={'model_used': 'hack'}
    )
    assert response.status_code == 400
    assert '不允许更新字段' in response.json()['error']


def test_delete_record_and_all(api_client):
    ids = _seed_many(2)
    assert api_client.delete(f'/api/v1/records/{ids[0]}').json() == {'success': True}
    assert api_client.delete('/api/v1/records').json() == {'success': True, 'deleted': True}
    assert api_client.get('/api/v1/records').json()['data']['total'] == 0


def test_legacy_record_paths(api_client):
    record_id = _seed_record('旧路径')
    assert api_client.get(f'/api/generation/records/{record_id}').json()['success'] is True
    assert api_client.get('/api/generation/records').json()['data']['total'] == 1


# ── 模型工厂 ─────────────────────────────────────────────

def test_normalize_sampling_filters_unsupported():
    filtered, dropped = normalize_sampling(
        {'temperature': 0.8, 'frequency_penalty': 0.5, 'unknown': 1}, 'deepseek'
    )
    # deepseek 支持 temperature，不支持 frequency_penalty
    assert filtered == {'temperature': 0.8}
    assert dropped == ['frequency_penalty']


def test_normalize_sampling_drops_out_of_range():
    filtered, dropped = normalize_sampling({'temperature': 9}, 'deepseek')
    assert filtered == {}
    assert dropped == ['temperature']


def test_thinking_kwargs_deepseek():
    enabled = thinking_kwargs('deepseek', 'deepseek-v4-pro', True, 'max')
    assert enabled['extra_body'] == {'thinking': {'type': 'enabled'}}
    assert enabled['reasoning_effort'] == 'max'

    disabled = thinking_kwargs('deepseek', 'deepseek-v4-pro', False, 'high')
    assert disabled['extra_body'] == {'thinking': {'type': 'disabled'}}
    assert 'reasoning_effort' not in disabled


def test_always_thinking_model_cannot_be_disabled():
    kwargs = thinking_kwargs('zhipu', 'glm-4.7', False, 'high')
    assert kwargs['extra_body'] == {'thinking': {'type': 'disabled'}}


def test_build_chat_model_strips_sampling_when_thinking():
    model, dropped = build_chat_model(
        'deepseek',
        'deepseek-v4-pro',
        api_key='sk-test',
        thinking_enabled=True,
        sampling={'temperature': 1.2, 'top_p': 0.9},
    )
    assert isinstance(model, ChatOpenAI)
    # 思考模式下 temperature/top_p 不生效，协议边界处剔除
    assert model.temperature is None
    assert model.extra_body == {'thinking': {'type': 'enabled'}}
    assert dropped == []


def test_build_chat_model_keeps_sampling_when_not_thinking():
    model, dropped = build_chat_model(
        'deepseek',
        'deepseek-v4-flash',
        api_key='sk-test',
        thinking_enabled=False,
        sampling={'temperature': 0.6, 'bogus': 1},
    )
    assert model.temperature == pytest.approx(0.6)
    assert dropped == []


def test_factory_route_validation():
    provider, model = LLMFactory.resolve_route('writing')
    assert (provider, model) == ('deepseek', 'deepseek-v4-pro')

    with pytest.raises(ValueError, match='不支持的模型提供商'):
        LLMFactory.resolve_route('writing', provider='nope')

    with pytest.raises(ValueError, match='不属于提供方'):
        LLMFactory.resolve_route('writing', provider='openai', model='deepseek-v4-pro')


def test_factory_caches_by_key_fingerprint():
    LLMFactory.clear_cache()
    first, _ = LLMFactory.get_llm('writing', api_key='sk-aaa')
    second, _ = LLMFactory.get_llm('writing', api_key='sk-aaa')
    third, _ = LLMFactory.get_llm('writing', api_key='sk-bbb')
    assert first is second
    assert first is not third
    LLMFactory.clear_cache()


def test_factory_requires_api_key():
    with pytest.raises(ValueError, match='缺少 API Key'):
        LLMFactory.get_llm('writing', api_key='')
