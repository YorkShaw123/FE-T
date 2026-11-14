"""全项目唯一的配置中心。

对照课件 3.3 节：用 pydantic-settings 的 BaseSettings 统一读取环境变量与
``.env.local``，类型不对在启动时就会报错，而不是等到某次模型调用才炸。

与旧 ``server/config.py`` 的关系：
- 静态目录数据（提供方、模型、模板分类、提示词）原样迁到 ``provider_catalog.py``，
  这里只做再导出，保证调用方仍然可以 ``from backend.config import LLM_PROVIDERS``；
- 运行期参数（端口、数据目录、超时、预算阈值）改为 Settings 字段，
  环境变量名保持 ``FLORA_*`` 不变，老用户与老脚本无需改动。
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from backend.provider_catalog import (
    CHAT_MESSAGE_OVERHEAD_TOKENS,
    DEFAULT_CONTEXT_WINDOW,
    DEFAULT_DEAI_PROMPT,
    EMBEDDING_BATCH_SIZE,
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    EMBEDDING_PROVIDER,
    EXPORT_FORMATS,
    GENERATION_SYSTEM_PROMPT,
    LLM_PROVIDERS,
    PREVIOUS_ARTICLE_COMPRESS_PROMPT,
    PREVIOUS_ARTICLE_COMPRESS_THRESHOLD,
    PREVIOUS_ARTICLE_SUMMARY_LENGTH,
    STYLE_CORPUS_MAX_CHUNKS,
    STYLE_SEARCH_MAX_CANDIDATES,
    TEMPLATE_CATEGORIES,
    TOKEN_BUDGET_SAFETY_TOKENS,
    TOKEN_BUDGET_WARNING_RATIO,
    TOKEN_ESTIMATE_SAFETY_FACTOR,
)

__all__ = [
    'CHAT_MESSAGE_OVERHEAD_TOKENS',
    'DEFAULT_CONTEXT_WINDOW',
    'DEFAULT_DEAI_PROMPT',
    'EMBEDDING_BATCH_SIZE',
    'EMBEDDING_DIMENSIONS',
    'EMBEDDING_MODEL',
    'EMBEDDING_PROVIDER',
    'EXPORT_FORMATS',
    'GENERATION_SYSTEM_PROMPT',
    'LLM_PROVIDERS',
    'PREVIOUS_ARTICLE_COMPRESS_PROMPT',
    'PREVIOUS_ARTICLE_COMPRESS_THRESHOLD',
    'PREVIOUS_ARTICLE_SUMMARY_LENGTH',
    'STYLE_CORPUS_MAX_CHUNKS',
    'STYLE_SEARCH_MAX_CANDIDATES',
    'TEMPLATE_CATEGORIES',
    'TOKEN_BUDGET_SAFETY_TOKENS',
    'TOKEN_BUDGET_WARNING_RATIO',
    'TOKEN_ESTIMATE_SAFETY_FACTOR',
    'PROJECT_ROOT',
    'Settings',
    'get_settings',
    'get_provider_config',
    'list_provider_ids',
]

# 项目根目录（backend/ 的上级），用于定位静态资源与旧数据
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# .env.local 放在项目根目录，桌面端与开发环境共用
_ENV_FILE = PROJECT_ROOT / '.env.local'


class Settings(BaseSettings):
    """运行期配置。

    字段名小写，环境变量以 ``FLORA_`` 为前缀且大小写不敏感，
    例如 ``FLORA_PORT`` → ``port``，``FLORA_DATA_DIR`` → ``data_dir``。
    """

    model_config = SettingsConfigDict(
        env_prefix='FLORA_',
        env_file=str(_ENV_FILE),
        env_file_encoding='utf-8',
        case_sensitive=False,
        extra='ignore',
    )

    # ── 应用基础 ──────────────────────────────────────
    app_name: str = '雨生编辑器'
    app_env: str = 'local'
    host: str = '127.0.0.1'
    port: int = 5000
    log_level: str = 'INFO'
    debug: bool = False

    # ── 数据与模型目录（空则使用用户目录默认值）────────
    data_dir: str = ''
    models_dir: str = ''

    # ── 上传与调用限制 ─────────────────────────────────
    max_content_length: int = 20 * 1024 * 1024
    llm_timeout_seconds: int = 180
    llm_max_retries: int = 2
    default_max_tokens: int = 8192

    # ── 本地会话令牌（替代课件 JWT 的多租户场景）────────
    token_secret: str = ''
    token_ttl_minutes: int = 1440

    def _home(self, name: str) -> Path:
        return Path(os.path.expanduser('~')) / name

    @property
    def resolved_data_dir(self) -> Path:
        """数据目录：显式配置 > 用户目录默认值。"""
        if self.data_dir:
            return Path(self.data_dir).expanduser().resolve()
        return (self._home('.flora-editor') / 'data').resolve()

    @property
    def resolved_models_dir(self) -> Path:
        if self.models_dir:
            return Path(self.models_dir).expanduser().resolve()
        return (self._home('.flora-editor') / 'models').resolve()

    @property
    def database_path(self) -> Path:
        return self.resolved_data_dir / 'flora.db'

    @property
    def database_url(self) -> str:
        """SQLAlchemy 异步连接串（aiosqlite 驱动，路径统一成正斜杠）。"""
        return f"sqlite+aiosqlite:///{self.database_path.as_posix()}"

    @property
    def web_dir(self) -> Path:
        """前端资源目录（项目根 web/，服务化后与后端解耦）。"""
        return PROJECT_ROOT / 'web'

    @property
    def static_dir(self) -> Path:
        return self.web_dir / 'static'

    @property
    def templates_dir(self) -> Path:
        return self.web_dir


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """全局唯一配置实例（与课件 3.3 的 lru_cache 写法一致）。"""
    return Settings()


def list_provider_ids() -> list[str]:
    return list(LLM_PROVIDERS.keys())


def get_provider_config(provider_id: str) -> dict[str, Any]:
    return LLM_PROVIDERS.get(provider_id, {})


def find_model(provider_id: str, model_id: str) -> dict[str, Any] | None:
    """在提供方配置里查一个模型，找不到返回 None。"""
    for model in get_provider_config(provider_id).get('models', []):
        if model.get('id') == model_id:
            return model
    return None
