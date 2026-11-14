"""P0 工程地基测试。

验证四件事：
1. FastAPI 应用能装起来，``/api/health`` 与 ``/api/v1/health`` 双轨可达；
2. 数据库连接串指向隔离目录，且健康检查真的跑通；
3. 错误响应形状与迁移前的 Flask 版本一致（``{"success": false, "error": ...}``）；
4. 提供方目录原样迁出，8 家提供方与迁移前一致。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.config import LLM_PROVIDERS, Settings, get_settings
from backend.core.exceptions import (
    GenerationError,
    LLMAPIError,
    error_payload,
    to_user_message,
)
from backend.main import create_app


@pytest.fixture()
def client(tmp_path, monkeypatch):
    """每个用例用独立的数据目录，避免碰到真实用户库。"""
    monkeypatch.setenv('FLORA_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('FLORA_MODELS_DIR', str(tmp_path / 'models'))
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


def test_health_both_paths(client):
    for path in ('/api/health', '/api/v1/health'):
        response = client.get(path)
        assert response.status_code == 200
        body = response.json()
        assert body['success'] is True
        assert body['data']['status'] == 'ok'
        assert body['data']['database'] == 'ok'


def test_security_headers_present(client):
    response = client.get('/api/health')
    assert response.headers['X-Content-Type-Options'] == 'nosniff'
    assert response.headers['X-Frame-Options'] == 'DENY'
    assert response.headers['Referrer-Policy'] == 'no-referrer'


def test_unknown_path_uses_unified_error_shape(client):
    response = client.get('/api/does-not-exist')
    assert response.status_code == 404
    body = response.json()
    assert body['success'] is False
    assert body['error'] == '请求的内容不存在。'


def test_validation_error_is_400_not_422(client):
    @client.app.post('/api/_probe_validation')
    async def _probe(payload: dict) -> dict:  # pragma: no cover - 仅用于触发校验
        return payload

    response = client.post('/api/_probe_validation', json=[1, 2, 3])
    assert response.status_code == 400
    assert response.json()['success'] is False


def test_settings_isolate_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv('FLORA_DATA_DIR', str(tmp_path / 'isolated'))
    get_settings.cache_clear()
    settings = get_settings()
    assert settings.resolved_data_dir == (tmp_path / 'isolated').resolve()
    assert settings.database_url.startswith('sqlite+aiosqlite:///')
    assert settings.database_path.name == 'flora.db'
    get_settings.cache_clear()


def test_settings_defaults_to_user_profile(monkeypatch):
    monkeypatch.delenv('FLORA_DATA_DIR', raising=False)
    get_settings.cache_clear()
    settings = Settings(data_dir='')
    assert '.flora-editor' in str(settings.resolved_data_dir)
    get_settings.cache_clear()


def test_provider_catalog_migrated_verbatim():
    assert len(LLM_PROVIDERS) == 8
    assert set(LLM_PROVIDERS) == {
        'deepseek', 'openai', 'siliconflow', 'moonshot',
        'qwen', 'zhipu', 'gemini', 'xai',
    }
    deepseek = LLM_PROVIDERS['deepseek']
    assert deepseek['base_url'] == 'https://api.deepseek.com'
    assert [model['id'] for model in deepseek['models']] == [
        'deepseek-v4-flash',
        'deepseek-v4-pro',
    ]


def test_exception_mapping_keeps_legacy_semantics():
    # 旧代码 raise GenerationError('请输入API密钥') 仍然映射成 400 + 原话
    exc = GenerationError('请输入API密钥')
    assert exc.status_code == 400
    payload = error_payload(exc)
    assert payload == {'success': False, 'error': '请输入API密钥'}

    llm_exc = LLMAPIError('上游超时')
    assert llm_exc.status_code == 502
    assert to_user_message(llm_exc) == '模型服务暂时不可用，请稍后重试。'


def test_index_page_served(client):
    response = client.get('/')
    assert response.status_code == 200
    assert '雨生编辑器' in response.text
