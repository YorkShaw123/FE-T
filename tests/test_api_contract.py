"""功能对齐契约：旧后端的 59 个端点必须在新后端全部可达。

清单来自 1.0.2 时 Flask 应用的 url_map 实际导出。删除旧 ``server/`` 之后，
这份测试成为唯一锁住 API 面积的守卫：新增端点不受限，但**这 59 个一个都不能少**。

探测方式用 PATCH：Starlette 对"路径存在但方法不允许"返回 405，对"路径不存在"返回 404。
所以 PATCH 拿到 405 就说明该路径仍然挂在路由表上，而且不需要构造真实请求、
不会产生副作用（关闭后端那条除外，单独跳过）。
"""

from __future__ import annotations

import pytest

# (旧方法, 旧路径) —— 路径参数统一写成 {id}
LEGACY_ENDPOINTS: tuple[tuple[str, str], ...] = (
    ('GET', '/'),
    ('GET', '/api/health'),
    # 生成与记录（13）
    ('GET', '/api/generation/models'),
    ('GET', '/api/generation/categories'),
    ('GET', '/api/generation/default-deai-prompt'),
    ('POST', '/api/generation/preview-prompt'),
    ('POST', '/api/generation/extract-text'),
    ('POST', '/api/generation/transform-text'),
    ('POST', '/api/generation/generate'),
    ('POST', '/api/generation/generate-stream'),
    ('GET', '/api/generation/records'),
    ('GET', '/api/generation/records/1'),
    ('PUT', '/api/generation/records/1'),
    ('DELETE', '/api/generation/records/1'),
    ('DELETE', '/api/generation/records'),
    # 模板（13）
    ('GET', '/api/templates'),
    ('GET', '/api/templates/grouped'),
    ('POST', '/api/templates'),
    ('GET', '/api/templates/1'),
    ('PUT', '/api/templates/1'),
    ('DELETE', '/api/templates/1'),
    ('DELETE', '/api/templates/all'),
    ('POST', '/api/templates/1/toggle'),
    ('GET', '/api/templates/1/versions'),
    ('POST', '/api/templates/1/restore/1'),
    ('POST', '/api/templates/starter'),
    ('POST', '/api/templates/export'),
    ('POST', '/api/templates/import'),
    # 文风语料库（15）
    ('GET', '/api/style-corpora'),
    ('POST', '/api/style-corpora'),
    ('GET', '/api/style-corpora/1'),
    ('PUT', '/api/style-corpora/1'),
    ('DELETE', '/api/style-corpora/1'),
    ('GET', '/api/style-corpora/1/chunks'),
    ('POST', '/api/style-corpora/1/import'),
    ('POST', '/api/style-corpora/1/index'),
    ('GET', '/api/style-corpora/1/index-progress'),
    ('POST', '/api/style-corpora/1/clear'),
    ('GET', '/api/style-corpora/embedding-config'),
    ('GET', '/api/style-corpora/embedding-model/status'),
    ('POST', '/api/style-corpora/embedding-model/install'),
    ('GET', '/api/style-corpora/embedding-model/install-progress'),
    ('POST', '/api/style-corpora/search'),
    # Style Card 与片段（9）
    ('GET', '/api/style-profiles/1'),
    ('PUT', '/api/style-profiles/1'),
    ('POST', '/api/style-profiles/1/analyze'),
    ('POST', '/api/style-profiles/1/refresh'),
    ('POST', '/api/style-profiles/1/restore'),
    ('GET', '/api/style-profiles/1/excerpts'),
    ('POST', '/api/style-profiles/1/excerpts/rebuild'),
    ('PUT', '/api/style-profiles/1/excerpts/1'),
    ('DELETE', '/api/style-profiles/1/excerpts/1'),
    # 工作模式（3）
    ('GET', '/api/modes'),
    ('GET', '/api/modes/novel'),
    ('POST', '/api/modes/novel/generate'),
    # 系统（4）
    ('POST', '/api/system/deepseek-api-key'),
    ('POST', '/api/system/open-community-prompts'),
    ('POST', '/api/system/open-help-link/deepseek'),
    ('POST', '/api/system/shutdown'),
)

# 这些路径不能真跑：会关掉后端
SIDE_EFFECT_PATHS = {'/api/system/shutdown', '/'}


def test_contract_covers_all_legacy_endpoints():
    assert len(LEGACY_ENDPOINTS) == 59


@pytest.mark.parametrize(('method', 'path'), LEGACY_ENDPOINTS)
def test_legacy_path_still_routed(api_client, method, path):
    """PATCH 探测：405 表示路径仍在路由表，404 表示已经丢了。"""
    if path in SIDE_EFFECT_PATHS:
        pytest.skip('该路径探测有副作用，由专门的用例覆盖')
    response = api_client.patch(path)
    assert response.status_code == 405, f'{method} {path} 已不在路由表（{response.status_code}）'


def test_index_page_and_static_assets(api_client):
    """首页与静态资源已从 server/ 搬到 web/，必须仍然可用。"""
    index = api_client.get('/')
    assert index.status_code == 200
    assert '雨生编辑器' in index.text

    css = api_client.get('/static/css/style.css')
    assert css.status_code == 200
    assert 'body' in css.text


def test_system_endpoints_are_functional(api_client):
    health_link = api_client.post('/api/system/open-help-link/deepseek')
    assert health_link.status_code == 200
    assert health_link.json()['data']['url'].startswith('https://')

    missing = api_client.post('/api/system/open-help-link/不存在')
    assert missing.status_code == 404

    key = api_client.post('/api/system/deepseek-api-key')
    assert key.status_code == 200
    assert 'found' in key.json()['data']
