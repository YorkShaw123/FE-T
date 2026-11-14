"""跨测试文件共享的 Flask 侧夹具保持在各自文件内；这里只提供新后端用的 ASGI 客户端。

每个用例拿一个全新的数据目录，并在进入应用时跑一遍幂等迁移，
所以测试之间不会互相污染，也不会碰到 ``%USERPROFILE%`` 下的真实用户库。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.config import get_settings
from backend.main import create_app


@pytest.fixture()
def api_client(tmp_path, monkeypatch):
    monkeypatch.setenv('FLORA_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('FLORA_MODELS_DIR', str(tmp_path / 'models'))
    get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as client:
        yield client
    get_settings.cache_clear()


@pytest.fixture()
def api_data_dir(tmp_path, monkeypatch):
    """只准备隔离目录，不建应用（给需要自行控制生命周期的用例）。"""
    data_dir = tmp_path / 'data'
    monkeypatch.setenv('FLORA_DATA_DIR', str(data_dir))
    monkeypatch.setenv('FLORA_MODELS_DIR', str(tmp_path / 'models'))
    get_settings.cache_clear()
    yield data_dir
    get_settings.cache_clear()
