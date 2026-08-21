import os
import sys
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = PROJECT_ROOT / "server"
sys.path.insert(0, str(SERVER_DIR))

# 必须在导入 app/config 前设置，确保测试只使用内存数据库。
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from app import create_app  # noqa: E402


def test_health_endpoint_reports_local_web_mode():
    client = create_app("production").test_client()

    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.get_json() == {
        "status": "ok",
        "app": "雨生编辑器",
        "mode": "web",
    }


def test_web_port_guard_rejects_a_second_live_server():
    """真实占用一个回环端口，重复开发服务必须在创建应用前失败。"""
    import socket
    import app as app_module

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen(1)
        port = listener.getsockname()[1]

        with pytest.raises(RuntimeError, match='已被占用'):
            app_module._ensure_web_port_available('127.0.0.1', port)


def test_workspace_runtime_response_uses_style_card_and_style_reference_labels():
    """通过 Flask 实际渲染页面验证用户看到的新节点语义。"""
    html = create_app('production').test_client().get('/').get_data(as_text=True)
    style_card_node = html.split('data-step="2"', 1)[1].split('data-step="3"', 1)[0]
    style_reference_node = html.split('data-step="6"', 1)[1].split('data-step="7"', 1)[0]

    assert '<strong>风格卡</strong>' in style_card_node
    assert '<strong>风格参考</strong>' in style_reference_node
    assert '文风参考' not in style_card_node
    assert '文风校正' not in style_reference_node


def test_shutdown_endpoint_is_disabled_in_web_mode():
    response = create_app("production").test_client().post("/api/system/shutdown")

    assert response.status_code == 404
    assert response.get_json()["success"] is False


def test_shutdown_endpoint_schedules_exit_in_desktop_mode(monkeypatch):
    import app as app_module

    scheduled = []
    monkeypatch.setattr(app_module, "_resolve_run_mode", lambda: "desktop")
    monkeypatch.setattr(app_module, "_schedule_desktop_exit", lambda: scheduled.append(True))

    response = create_app("production").test_client().post("/api/system/shutdown")

    assert response.status_code == 200
    assert response.get_json() == {"success": True}
    assert scheduled == [True]


def test_community_prompt_entry_opens_fixed_url(monkeypatch):
    import app as app_module

    opened = []
    monkeypatch.setattr(
        app_module,
        '_open_community_prompts',
        lambda: opened.append(app_module.COMMUNITY_PROMPTS_URL) or True,
    )

    response = create_app('production').test_client().post(
        '/api/system/open-community-prompts',
    )

    assert response.status_code == 200
    assert response.get_json() == {
        'success': True,
        'data': {'url': 'https://www.aishort.top/community-prompts'},
    }
    assert opened == ['https://www.aishort.top/community-prompts']


def test_help_links_open_only_server_allowlisted_urls(monkeypatch):
    import app as app_module

    opened = []
    monkeypatch.setattr(
        app_module,
        '_open_external_url',
        lambda url: opened.append(url) or True,
    )
    client = create_app('production').test_client()

    response = client.post('/api/system/open-help-link/deepseek')
    unknown = client.post('/api/system/open-help-link/not-allowed')

    assert response.status_code == 200
    assert response.get_json()['data']['url'] == 'https://api-docs.deepseek.com/'
    assert unknown.status_code == 404
    assert opened == ['https://api-docs.deepseek.com/']


def test_starter_templates_are_seeded_once_and_remain_deleted():
    from database import db
    from database.models import ProjectSetting, PromptTemplate
    from database.starter_templates import (
        STARTER_TEMPLATES_SETTING_KEY,
        ensure_starter_templates,
    )

    app = create_app('production')
    with app.app_context():
        templates = PromptTemplate.query.order_by(PromptTemplate.sort_order).all()
        assert [(item.category, item.name) for item in templates] == [
            ('character', '示例人物：推云童子雨生'),
            ('plot', '示例剧情：雨落万物生'),
        ]
        assert all(item.is_active and not item.is_sample for item in templates)
        assert ProjectSetting.get_value(STARTER_TEMPLATES_SETTING_KEY) == '1'

        PromptTemplate.query.delete()
        db.session.commit()

        assert ensure_starter_templates() is False
        assert PromptTemplate.query.count() == 0


def test_template_editor_exposes_community_prompt_entry():
    html = create_app('production').test_client().get('/').get_data(as_text=True)
    template_js = (SERVER_DIR / 'static' / 'js' / 'templateManager.js').read_text(
        encoding='utf-8',
    )
    editor = html.split('id="template-editor-panel"', 1)[1].split(
        'id="style-card-panel"', 1,
    )[0]

    assert 'id="btn-open-community-prompts"' in editor
    assert '社区提示词 ↗' in editor
    assert "'/api/system/open-community-prompts'" in template_js


def test_preview_toggle_buttons_are_fully_removed():
    """实际渲染的页面不再暴露任何“显示/隐藏预览”按钮。"""
    html = create_app('production').test_client().get('/').get_data(as_text=True)
    template_js = (SERVER_DIR / 'static' / 'js' / 'templateManager.js').read_text(
        encoding='utf-8',
    )
    result_js = (SERVER_DIR / 'static' / 'js' / 'resultEditor.js').read_text(
        encoding='utf-8',
    )

    assert '隐藏预览' not in html
    assert '显示预览' not in html
    assert 'btn-toggle-markdown-preview' not in html + template_js
    assert 'btn-toggle-result-preview' not in html + result_js


def test_cross_origin_write_is_rejected():
    client = create_app("production").test_client()

    response = client.post(
        "/api/templates",
        json={},
        headers={"Origin": "https://example.com"},
    )

    assert response.status_code == 403
    assert response.get_json() == {
        "success": False,
        "error": "拒绝跨站写入请求",
    }


def test_security_headers_are_present():
    client = create_app("production").test_client()

    response = client.get("/api/health")

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"
    assert response.headers["Cache-Control"] == "no-store"


def test_style_rag_routes_are_registered_by_source_app():
    app = create_app("production")
    rules = {rule.rule for rule in app.url_map.iter_rules()}

    assert "/api/style-corpora/search" in rules
    assert "/api/style-corpora/<int:corpus_id>/index" in rules
    assert "/api/style-corpora/<int:corpus_id>/index-progress" in rules


def test_style_rag_management_has_its_own_top_level_tab():
    client = create_app("production").test_client()

    html = client.get("/").get_data(as_text=True)
    workspace = html.split('<section id="tab-workspace"', 1)[1].split(
        '<section id="tab-templates"', 1,
    )[0]
    styles = html.split('<section id="tab-styles"', 1)[1].split(
        '<section id="tab-history"', 1,
    )[0]

    assert 'data-tab="styles">文风管理' in html
    assert styles.index('id="btn-install-embedding-model"') < styles.index('id="btn-refresh-corpora"')
    assert '下载本地 ONNX 语义向量引擎' in styles
    assert 'id="embedding-install-help-modal"' in html
    assert 'id="btn-close-embedding-install-help"' in html
    assert 'id="style-rag-corpora-list"' in workspace
    assert 'id="btn-open-corpus-panel"' in workspace
    assert 'id="style-rag-embedding-key"' not in workspace
    assert 'id="corpus-search-query"' not in workspace
    for element_id in (
        "style-corpus-list", "corpus-new-name", "style-rag-embedding-backend",
        "style-rag-embedding-key", "corpus-search-query", "corpus-search-result",
    ):
        assert f'id="{element_id}"' in styles
        assert html.count(f'id="{element_id}"') == 1


def test_embedding_model_status_endpoint_does_not_start_a_download(monkeypatch):
    import services.embedding_backends as embedding_backends

    expected = {
        'installed': False,
        'runtime_available': True,
        'model_files_ready': False,
        'model_dir': 'D:/models/bge-small-zh-v1.5',
        'model_id': 'BAAI/bge-small-zh-v1.5',
        'model_version': '1.5-onnx-v1',
    }
    monkeypatch.setattr(
        embedding_backends,
        'local_embedding_installation_status',
        lambda: expected,
    )

    response = create_app('production').test_client().get(
        '/api/style-corpora/embedding-model/status',
    )

    assert response.status_code == 200
    assert response.get_json() == {'success': True, 'data': expected}


def test_embedding_progress_dialog_is_present():
    html = create_app("production").test_client().get("/").get_data(as_text=True)

    for element_id in (
        "embedding-progress-modal",
        "embedding-progress-bar",
        "embedding-progress-percent",
        "embedding-progress-count",
        "embedding-progress-remaining",
        "btn-close-embedding-progress",
    ):
        assert html.count(f'id="{element_id}"') == 1


def test_default_deai_prompt_is_empty():
    response = create_app("production").test_client().get(
        "/api/generation/default-deai-prompt",
    )

    assert response.status_code == 200
    assert response.get_json()["data"] == ""


def test_onboarding_help_controls_are_present_once():
    html = create_app("production").test_client().get("/").get_data(as_text=True)
    onboarding_js = (SERVER_DIR / "static" / "js" / "onboarding.js").read_text(
        encoding="utf-8",
    )

    for element_id in (
        "btn-open-onboarding",
        "onboarding-backdrop",
        "onboarding-dialog",
        "onboarding-title",
        "onboarding-page",
        "onboarding-progress",
        "btn-cancel-onboarding",
        "btn-prev-onboarding",
        "btn-next-onboarding",
    ):
        assert html.count(f'id="{element_id}"') == 1
    assert "陪你把零散想法写成可以继续打磨的文章" in onboarding_js
    assert "04 生成初稿" in onboarding_js
    assert "06 风格参考" in onboarding_js
    assert "推云童子雨生" in onboarding_js
    for link_key in (
        'deepseek', 'openai', 'moonshot', 'qwen', 'zhipu',
        'gemini', 'xai', 'siliconflow', 'aishort',
    ):
        assert f'data-help-link="{link_key}"' in onboarding_js
    assert "{{变量名}}" not in onboarding_js


def test_chinese_product_name_is_used_by_web_and_tauri_build_contracts():
    import json

    html = create_app('production').test_client().get('/').get_data(as_text=True)
    tauri_config = json.loads(
        (PROJECT_ROOT / 'src-tauri' / 'tauri.conf.json').read_text(encoding='utf-8'),
    )
    build_script = (PROJECT_ROOT / 'scripts' / 'build-all.ps1').read_text(
        encoding='utf-8',
    )

    assert '<title>雨生编辑器 - AI文字创作助手</title>' in html
    assert '<h1 class="logo">雨生<span>编辑器</span></h1>' in html
    assert tauri_config['productName'] == '雨生编辑器'
    assert tauri_config['mainBinaryName'] == '雨生编辑器'
    assert tauri_config['app']['windows'][0]['title'].startswith('雨生编辑器')
    assert '$destApp = Join-Path $Root "雨生编辑器.exe"' in build_script


def test_workspace_template_variable_ui_is_fully_removed():
    html = create_app("production").test_client().get("/").get_data(as_text=True)

    for element_id in (
        "workspace-variables-section",
        "btn-open-workspace-variables",
        "workspace-variable-count",
        "workspace-variables-backdrop",
        "workspace-variables-title",
        "workspace-variables-list",
        "btn-close-workspace-variables",
        "btn-finish-workspace-variables",
    ):
        assert f'id="{element_id}"' not in html
    assert '填写模板变量' not in html
    assert '{{变量名}}' not in html


def test_workspace_exposes_ordered_generation_flow_and_token_summary():
    html = create_app("production").test_client().get("/").get_data(as_text=True)
    workspace = html.split('<section id="tab-workspace"', 1)[1].split(
        '<section id="tab-templates"', 1,
    )[0]

    positions = [workspace.index(f'data-step="{step}"') for step in range(1, 8)]
    assert positions == sorted(positions)
    assert workspace.count('id="workflow-connections"') == 1
    assert workspace.count('id="workflow-node-backdrop"') == 1
    assert workspace.count('id="workflow-node-modal"') == 1
    assert workspace.count('id="workflow-node-modal-body"') == 1
    assert workspace.count('id="workspace-token-summary"') == 1
    assert workspace.count('id="prompt-preview-loading"') == 1
    assert workspace.count('id="continue-hint"') == 1
    assert workspace.count('id="btn-continue-generate"') == 1
    assert 'id="btn-preview-prompt-flow"' not in workspace
    generation_node = workspace.split('data-step="4"', 1)[1].split('data-step="5"', 1)[0]
    style_card_node = workspace.split('data-step="2"', 1)[1].split('data-step="3"', 1)[0]
    style_reference_node = workspace.split('data-step="6"', 1)[1].split('data-step="7"', 1)[0]
    assert 'class="flow-generate-launcher canvas-generate-launcher"' in html
    assert generation_node.count('id="btn-generate"') == 0
    assert html.count('id="btn-generate"') == 1
    assert 'id="style-rag-control"' not in style_card_node
    assert 'id="style-reference-enabled"' in style_reference_node
    assert 'id="style-rag-control"' in style_reference_node
    assert 'id="strict-style-rewrite-enabled"' not in workspace


def test_generation_status_stays_in_draft_and_final_nodes():
    html = create_app("production").test_client().get("/").get_data(as_text=True)
    generation_js = (SERVER_DIR / "static" / "js" / "generation.js").read_text(
        encoding="utf-8",
    )
    generation_service = (SERVER_DIR / "services" / "generation_service.py").read_text(
        encoding="utf-8",
    )
    stylesheet = (SERVER_DIR / "static" / "css" / "style.css").read_text(
        encoding="utf-8",
    )
    draft = html.split('data-step="4"', 1)[1].split('data-step="5"', 1)[0]
    final = html.split('data-step="7"', 1)[1].split(
        'class="flow-generate-launcher', 1,
    )[0]

    assert '调用当前选择的大模型 API' in draft
    assert 'id="draft-node-status" class="flow-node-status flow-node-status-busy"' in draft
    assert 'id="final-node-status"' not in draft
    assert 'id="style-reference-enabled"' in html
    assert 'id="style-rewrite-content-section"' in final
    assert 'id="final-node-status" class="flow-node-status flow-node-status-busy"' in final
    assert 'id="draft-node-status"' not in final
    assert html.count('class="flow-node-status flow-node-status-busy"') == 2
    assert html.count('aria-live="polite">正在生成</small>') == 2
    assert 'id="loading-overlay"' not in html
    assert 'id="postprocess-loading-overlay"' not in html
    assert "await fetchPromptPreview()" not in generation_js
    assert "type === 'token_budget'" in generation_js
    assert "data === 'prompt_preparing'" in generation_js
    assert "data === 'postprocess_start'" in generation_js
    assert "data === 'style_reference_start'" in generation_js
    assert "'data': 'postprocess_start'" in generation_service
    assert "setFlowPhase('postprocess')" in generation_js
    assert 'body[data-flow-phase="draft"] #draft-node-status' in stylesheet
    assert 'body[data-flow-phase="postprocess"] #final-node-status' in stylesheet
    assert '#draft-node-status .flow-node-status-idle' not in stylesheet


def test_generate_stream_connects_before_slow_prompt_and_rag_preparation(monkeypatch):
    """回归：RAG/Prompt 准备不能阻塞 SSE 建连和画布状态显示。"""
    import routes.generation_routes as generation_routes

    generate_calls = []
    monkeypatch.setattr(
        generation_routes,
        "generate_article",
        lambda **kwargs: generate_calls.append(kwargs) or iter(()),
    )
    response = create_app("production").test_client().post(
        "/api/generation/generate-stream",
        json={
            "api_key": "test-key",
            "provider": "deepseek",
            "model": "deepseek-v4-pro",
            "style_mode": "smart",
            "style_corpus_ids": [1],
        },
        buffered=False,
    )

    first_event = next(response.response).decode("utf-8")
    assert response.status_code == 200
    assert "prompt_preparing" in first_event
    assert generate_calls == []
    response.close()


def test_generate_stream_releases_operation_when_preparation_fails(monkeypatch):
    """Prompt/RAG 准备异常必须结束状态流并释放全局模型操作锁。"""
    import routes.generation_routes as generation_routes

    lifecycle = []
    monkeypatch.setattr(
        generation_routes, "acquire_model_operation", lambda: lifecycle.append("acquire"),
    )
    monkeypatch.setattr(
        generation_routes, "release_model_operation", lambda: lifecycle.append("release"),
    )

    def fail_generation(**_kwargs):
        raise RuntimeError("preparation failed")

    monkeypatch.setattr(generation_routes, "generate_article", fail_generation)
    response = create_app("production").test_client().post(
        "/api/generation/generate-stream",
        json={
            "api_key": "test-key",
            "provider": "deepseek",
            "model": "deepseek-v4-pro",
        },
    )

    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert "event: error" in body
    assert lifecycle == ["acquire", "release"]


def test_unread_reminder_css_js_class_contract():
    """JS 与 CSS 之间 has-unread-result 类名契约检查。"""
    generation_js = (SERVER_DIR / "static" / "js" / "generation.js").read_text(
        encoding="utf-8",
    )
    workflow_js = (SERVER_DIR / "static" / "js" / "workflowCanvas.js").read_text(
        encoding="utf-8",
    )
    stylesheet = (SERVER_DIR / "static" / "css" / "style.css").read_text(
        encoding="utf-8",
    )

    # 类名契约:JS 增加与清除、CSS 定义样式,三处拼写必须一致（04 初稿与 07 最终成稿均使用同一类名）
    assert "classList.add('has-unread-result')" in generation_js
    assert "classList.remove('has-unread-result')" in workflow_js
    assert ".flow-node.has-unread-result" in stylesheet
    assert "@keyframes result-ready-pulse" in stylesheet


def test_workflow_draft_and_final_nodes_have_separate_result_contracts():
    html = create_app("production").test_client().get("/").get_data(as_text=True)
    generation_js = (SERVER_DIR / "static" / "js" / "generation.js").read_text(
        encoding="utf-8",
    )
    workflow_js = (SERVER_DIR / "static" / "js" / "workflowCanvas.js").read_text(
        encoding="utf-8",
    )

    draft = html.split('data-step="4"', 1)[1].split('data-step="5"', 1)[0]
    final = html.split('data-step="7"', 1)[1].split(
        'class="flow-generate-launcher', 1,
    )[0]
    assert 'id="first-content"' in draft
    assert 'id="final-content"' not in draft
    assert 'id="btn-open-draft-editor"' in draft
    assert 'id="btn-copy-draft"' in draft
    assert 'id="btn-download-draft"' in draft
    assert 'id="final-content"' in final
    assert 'id="first-content"' not in final
    assert 'id="btn-open-result-editor"' in final
    assert "serverFinalContent" in generation_js
    assert "postProcessEnabled" in generation_js
    assert "flora:workflow-input-change" in workflow_js


def test_advanced_panel_matches_help_modal_and_exposes_provider_note():
    html = create_app("production").test_client().get("/").get_data(as_text=True)

    assert html.index('id="btn-open-onboarding"') < html.index('id="btn-open-advanced"')
    assert 'id="advanced-params-backdrop" class="onboarding-backdrop"' in html
    assert 'id="advanced-params-dialog" class="onboarding-dialog"' in html
    assert 'id="advanced-provider-note"' in html


def test_models_api_exposes_provider_specific_sampling_capabilities():
    response = create_app("production").test_client().get("/api/generation/models")
    providers = response.get_json()["data"]

    deepseek = providers["deepseek"]["sampling"]
    assert deepseek["parameters"]["max_tokens"]["supported"] is True
    assert deepseek["parameters"]["frequency_penalty"]["supported"] is False
    assert "思考模式" in deepseek["note"]


def test_tauri_window_high_resolution_icon_asset_exists():
    # 只保留资源存在性检查(set_icon 源码细节由 cargo check 保证)
    assert (PROJECT_ROOT / "src-tauri" / "icons" / "icon.png").is_file()


def test_style_retrieval_debugger_is_collapsed_by_default():
    html = create_app("production").test_client().get("/").get_data(as_text=True)
    details_tag = html.split('<details id="corpus-search-details"', 1)[1].split('>', 1)[0]

    assert " open" not in details_tag
