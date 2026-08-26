"""本机 DeepSeek API Key 读取功能测试。"""
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_DIR = PROJECT_ROOT / "server"
sys.path.insert(0, str(SERVER_DIR))

from services.local_api_key import find_local_deepseek_key, mask_key  # noqa: E402


def test_find_key_from_env_var(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-test-1234567890")
    key, source = find_local_deepseek_key()
    assert key == "sk-test-1234567890"
    assert "环境变量" in source


def test_dash_env_var_name_supported(monkeypatch):
    monkeypatch.setenv("DEEPSEEK-API-KEY", "sk-dash-key-abcdef")
    key, _ = find_local_deepseek_key()
    assert key == "sk-dash-key-abcdef"


def test_env_var_wins_over_file(monkeypatch, tmp_path):
    key_file = tmp_path / "key.txt"
    key_file.write_text("sk-file-key-abcdef\n", encoding="utf-8")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-env-key-abcdef")
    monkeypatch.setenv("FLORA_DEEPSEEK_KEY_FILE", str(key_file))
    key, source = find_local_deepseek_key()
    assert key == "sk-env-key-abcdef"
    assert "环境变量" in source


def test_find_key_from_explicit_file(monkeypatch, tmp_path):
    key_file = tmp_path / "key.txt"
    key_file.write_text("sk-file-key-abcdef\n", encoding="utf-8")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK-API-KEY", raising=False)
    monkeypatch.setenv("FLORA_DEEPSEEK_KEY_FILE", str(key_file))
    key, source = find_local_deepseek_key()
    assert key == "sk-file-key-abcdef"
    assert str(key_file) in source


def test_find_key_from_env_file_style(monkeypatch, tmp_path):
    key_file = tmp_path / "key.txt"
    key_file.write_text(
        '# comment\nDEEPSEEK_API_KEY="sk-dotenv-key-abcdef"\n',
        encoding="utf-8",
    )
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK-API-KEY", raising=False)
    monkeypatch.setenv("FLORA_DEEPSEEK_KEY_FILE", str(key_file))
    key, _ = find_local_deepseek_key()
    assert key == "sk-dotenv-key-abcdef"


def test_quoted_plain_file_key_is_cleaned(monkeypatch, tmp_path):
    key_file = tmp_path / "key.txt"
    key_file.write_text("'sk-quoted-key-abcdef'\n", encoding="utf-8")
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK-API-KEY", raising=False)
    monkeypatch.setenv("FLORA_DEEPSEEK_KEY_FILE", str(key_file))
    key, _ = find_local_deepseek_key()
    assert key == "sk-quoted-key-abcdef"


def test_not_found_returns_none(monkeypatch, tmp_path):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK-API-KEY", raising=False)
    monkeypatch.delenv("FLORA_DEEPSEEK_KEY_FILE", raising=False)
    monkeypatch.setattr(
        "services.local_api_key._candidate_paths",
        lambda: [tmp_path / "nope.txt"],
    )
    key, source = find_local_deepseek_key()
    assert key is None
    assert source is None


def test_mask_key():
    assert mask_key("sk-1234567890abcd") == "sk-1******abcd"
    assert mask_key("short") == "*****"
    assert mask_key("") == ""


# ---------------- 路由层测试 ----------------

def _make_client():
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    from app import create_app  # noqa: F401
    return create_app("production").test_client()


def test_route_returns_key_from_env(monkeypatch):
    monkeypatch.setenv("DEEPSEEK_API_KEY", "sk-route-key-abcdef")
    resp = _make_client().post("/api/system/deepseek-api-key")
    data = resp.get_json()
    assert resp.status_code == 200
    assert data["found"] is True
    assert data["key"] == "sk-route-key-abcdef"
    assert data["masked"].startswith("sk-")
    assert "****" in data["masked"]
    assert "环境变量" in data["source"]


def test_route_404_when_no_key(monkeypatch, tmp_path):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("DEEPSEEK-API-KEY", raising=False)
    monkeypatch.delenv("FLORA_DEEPSEEK_KEY_FILE", raising=False)
    monkeypatch.setattr(
        "services.local_api_key._candidate_paths",
        lambda: [tmp_path / "nope.txt"],
    )
    resp = _make_client().post("/api/system/deepseek-api-key")
    assert resp.status_code == 404
    assert resp.get_json()["found"] is False


def test_route_rejects_cross_origin(monkeypatch, tmp_path):
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("FLORA_DEEPSEEK_KEY_FILE", raising=False)
    monkeypatch.setattr(
        "services.local_api_key._candidate_paths",
        lambda: [tmp_path / "nope.txt"],
    )
    resp = _make_client().post(
        "/api/system/deepseek-api-key",
        headers={"Origin": "https://evil.example.com"},
    )
    assert resp.status_code == 403
