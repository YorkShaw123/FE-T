"""工作模式预设接口骨架测试。"""
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = PROJECT_ROOT / "server"
sys.path.insert(0, str(SERVER_DIR))

os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from app import create_app  # noqa: E402


def _client():
    return create_app("production").test_client()


def test_list_modes_returns_preset_skeleton():
    resp = _client().get("/api/modes")
    assert resp.status_code == 200
    modes = resp.get_json()["data"]["modes"]
    ids = [m["id"] for m in modes]
    assert "novel" in ids
    assert "marketing" in ids
    # 每个模式都应携带名称、描述、分类与输出规格
    for mode in modes:
        assert mode["name"]
        assert mode["description"]
        assert isinstance(mode["categories"], list)
        assert isinstance(mode["output_spec"], dict)
        assert mode["enabled"] in (True, False)


def test_marketing_mode_is_planned_skeleton():
    resp = _client().get("/api/modes/marketing")
    assert resp.status_code == 200
    mode = resp.get_json()["data"]
    assert mode["enabled"] is False
    assert "copy_article" in mode["categories"]
    assert mode["output_spec"]["title_required"] is True


def test_unknown_mode_returns_404():
    assert _client().get("/api/modes/nope").status_code == 404


def test_generate_placeholder_returns_501():
    resp = _client().post("/api/modes/novel/generate")
    assert resp.status_code == 501
    body = resp.get_json()
    assert body["success"] is False
    assert "尚未实现" in body["error"]
