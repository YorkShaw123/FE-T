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
        "app": "Forestar Editor",
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
