import os
import sys
from pathlib import Path


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
        "app": "Flora Editor",
        "mode": "web",
    }


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


def test_workspace_variables_use_button_and_modal():
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
        assert html.count(f'id="{element_id}"') == 1
    sidebar = html.split('<aside class="panel panel-left">', 1)[1].split('</aside>', 1)[0]
    assert 'id="workspace-variables-list"' not in sidebar


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
    assert 'id="btn-preview-prompt-flow"' not in workspace
    generation_node = workspace.split('data-step="4"', 1)[1].split('data-step="5"', 1)[0]
    assert 'class="flow-generate-launcher canvas-generate-launcher"' in html
    assert generation_node.count('id="btn-generate"') == 0
    assert html.count('id="btn-generate"') == 1


def test_style_retrieval_debugger_is_collapsed_by_default():
    html = create_app("production").test_client().get("/").get_data(as_text=True)
    details_tag = html.split('<details id="corpus-search-details"', 1)[1].split('>', 1)[0]

    assert " open" not in details_tag
