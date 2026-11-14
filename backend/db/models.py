"""ORM 模型（SQLAlchemy 2.0 声明式，异步可用）。

与旧 ``server/database/models.py`` 一一对应，表名、列名、类型、默认值、
可空性全部保持不变——这是"旧库能直接读"的前提。差别只有三处：

1. 去掉 Flask-SQLAlchemy 的 ``db.Model``，改用 ``DeclarativeBase``；
2. 关系由 ``lazy='dynamic'`` 改为显式查询（服务层直接按 ``parent_id`` 查，
   避免异步语境下隐式 IO）；
3. ``to_dict`` 结果与原实现逐键一致，前端无需改动。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    """统一的 UTC 时间（与旧实现一致）。"""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """所有表的基类。"""


class PromptTemplate(Base):
    """提示词模板。支持版本控制：内容变更时新建版本，旧版本置为非活跃。"""

    __tablename__ = 'prompt_templates'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False, default='constraint')
    content: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default='')
    variables: Mapped[str | None] = mapped_column(Text, default='[]')
    is_active: Mapped[bool | None] = mapped_column(Boolean, default=True)
    style_strength: Mapped[str] = mapped_column(String(20), nullable=False, default='light')
    is_sample: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int | None] = mapped_column(Integer, default=0)
    version: Mapped[int | None] = mapped_column(Integer, default=1)
    parent_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey('prompt_templates.id'), nullable=True
    )
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'name': self.name,
            'category': self.category,
            'content': self.content,
            'description': self.description,
            'is_active': self.is_active,
            'style_strength': self.style_strength or 'light',
            'sort_order': self.sort_order,
            'version': self.version,
            'parent_id': self.parent_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f'<PromptTemplate {self.name} v{self.version}>'


class StyleProfile(Base):
    """范例文章对应的结构化风格卡；与模板版本绑定。"""

    __tablename__ = 'style_profiles'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey('prompt_templates.id', ondelete='CASCADE'),
        nullable=False,
        unique=True,
        index=True,
    )
    template_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    analysis_card_json: Mapped[str] = mapped_column(Text, nullable=False, default='{}')
    card_json: Mapped[str] = mapped_column(Text, nullable=False, default='{}')
    analysis_model: Mapped[str | None] = mapped_column(String(100), default='')
    analysis_status: Mapped[str] = mapped_column(String(30), nullable=False, default='ready')
    error_message: Mapped[str | None] = mapped_column(Text, default='')
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self, current_source_hash: str | None = None) -> dict[str, Any]:
        try:
            card = json.loads(self.card_json or '{}')
        except (TypeError, json.JSONDecodeError):
            card = {}
        return {
            'id': self.id,
            'template_id': self.template_id,
            'template_version': self.template_version,
            'source_hash': self.source_hash,
            'schema_version': self.schema_version,
            'card': card,
            'analysis_model': self.analysis_model,
            'analysis_status': self.analysis_status,
            'error_message': self.error_message,
            'is_primary': self.is_primary,
            'is_stale': bool(current_source_hash and current_source_hash != self.source_hash),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class StyleExcerpt(Base):
    """由范例文章切分得到的可检索风格片段。"""

    __tablename__ = 'style_excerpts'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    style_profile_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey('style_profiles.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    scene_type: Mapped[str] = mapped_column(String(50), nullable=False, default='mixed', index=True)
    pov: Mapped[str | None] = mapped_column(String(80), default='')
    emotion: Mapped[str | None] = mapped_column(String(200), default='')
    dialogue_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    pace: Mapped[str] = mapped_column(String(30), nullable=False, default='medium')
    tags_json: Mapped[str] = mapped_column(Text, nullable=False, default='[]')
    functions_json: Mapped[str] = mapped_column(Text, nullable=False, default='[]')
    analysis_model: Mapped[str | None] = mapped_column(String(100), default='')
    analysis_status: Mapped[str] = mapped_column(String(30), nullable=False, default='ready')
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self) -> dict[str, Any]:
        def load_list(value: str | None) -> list:
            try:
                result = json.loads(value or '[]')
                return result if isinstance(result, list) else []
            except (TypeError, json.JSONDecodeError):
                return []

        return {
            'id': self.id,
            'style_profile_id': self.style_profile_id,
            'content': self.content,
            'char_count': len(self.content or ''),
            'source_order': self.source_order,
            'scene_type': self.scene_type,
            'pov': self.pov,
            'emotion': self.emotion,
            'dialogue_ratio': self.dialogue_ratio,
            'pace': self.pace,
            'tags': load_list(self.tags_json),
            'functions': load_list(self.functions_json),
            'analysis_model': self.analysis_model,
            'analysis_status': self.analysis_status,
            'is_enabled': self.is_enabled,
            'is_pinned': self.is_pinned,
        }


class StyleCorpus(Base):
    """Style RAG 语料库。"""

    __tablename__ = 'style_corpora'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, default='')
    source_filename: Mapped[str | None] = mapped_column(String(300), default='')
    total_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    chunk_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    index_status: Mapped[str] = mapped_column(String(30), nullable=False, default='empty')
    embedding_model: Mapped[str | None] = mapped_column(String(100), default='')
    embedding_backend: Mapped[str | None] = mapped_column(String(50), default='')
    embedding_model_version: Mapped[str | None] = mapped_column(String(100), default='')
    embedding_dim: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    signature_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'name': self.name,
            'description': self.description or '',
            'source_filename': self.source_filename or '',
            'total_chars': self.total_chars,
            'chunk_count': self.chunk_count,
            'index_status': self.index_status,
            'embedding_model': self.embedding_model or '',
            'embedding_backend': self.embedding_backend or '',
            'embedding_model_version': self.embedding_model_version or '',
            'embedding_dim': self.embedding_dim,
            'signature_version': self.signature_version,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class AuthorStyleProfile(Base):
    """从语料 Style Window 聚合的本地统计画像（不是 LLM Style Card）。"""

    __tablename__ = 'author_style_profiles'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    corpus_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey('style_corpora.id', ondelete='CASCADE'),
        nullable=False,
        unique=True,
        index=True,
    )
    feature_version: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    profile_json: Mapped[str] = mapped_column(Text, nullable=False, default='{}')
    sample_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    valid_char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    def to_dict(self, current_feature_version: int | None = None) -> dict[str, Any]:
        try:
            profile = json.loads(self.profile_json or '{}')
        except (TypeError, json.JSONDecodeError):
            profile = {}
        stale = (
            current_feature_version is not None
            and self.feature_version != current_feature_version
        )
        return {
            'id': self.id,
            'corpus_id': self.corpus_id,
            'feature_version': self.feature_version,
            'profile': profile,
            'sample_count': self.sample_count,
            'valid_char_count': self.valid_char_count,
            'confidence': self.confidence,
            'is_stale': stale,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


class StyleChunk(Base):
    """语料库切片：标签元数据 + 可选向量（float32 BLOB）。"""

    __tablename__ = 'style_chunks'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    corpus_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey('style_corpora.id', ondelete='CASCADE'),
        nullable=False,
        index=True,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    article_key: Mapped[str] = mapped_column(String(64), nullable=False, default='', index=True)
    source_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    style_feature_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    style_features_json: Mapped[str] = mapped_column(Text, nullable=False, default='{}')
    style_window_valid_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    style_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    style_window_start_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    style_window_end_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    style_signature_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    style_signature_json: Mapped[str] = mapped_column(Text, nullable=False, default='{}')
    scene_type: Mapped[str] = mapped_column(String(50), nullable=False, default='mixed', index=True)
    pacing: Mapped[str] = mapped_column(String(30), nullable=False, default='medium')
    pov: Mapped[str | None] = mapped_column(String(80), default='')
    emotion: Mapped[str | None] = mapped_column(String(200), default='')
    dialogue_ratio: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    embedding_blob: Mapped[bytes | None] = mapped_column(LargeBinary)
    embedding_model: Mapped[str | None] = mapped_column(String(100), default='')
    embedding_backend: Mapped[str | None] = mapped_column(String(50), default='')
    embedding_model_version: Mapped[str | None] = mapped_column(String(100), default='')
    embedding_dim: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow)

    def to_dict(self, include_content: bool = True) -> dict[str, Any]:
        data = {
            'id': self.id,
            'corpus_id': self.corpus_id,
            'article_key': self.article_key or '',
            'source_order': self.source_order,
            'char_count': self.char_count,
            'style_feature_version': self.style_feature_version,
            'style_window_valid_chars': self.style_window_valid_chars,
            'style_confidence': self.style_confidence,
            'style_window_start_order': self.style_window_start_order,
            'style_window_end_order': self.style_window_end_order,
            'style_signature_version': self.style_signature_version,
            'scene_type': self.scene_type,
            'pacing': self.pacing,
            'pov': self.pov,
            'emotion': self.emotion,
            'dialogue_ratio': self.dialogue_ratio,
            'embedding_model': self.embedding_model or '',
            'embedding_backend': self.embedding_backend or '',
            'embedding_model_version': self.embedding_model_version or '',
            'embedding_dim': self.embedding_dim,
            'is_enabled': self.is_enabled,
        }
        if include_content:
            data['content'] = self.content
        return data


class StylePendingQuestion(Base):
    """语料答不上来的问题，攒起来供用户补语料。

    对应课件"低置信度问题入队"：它不是错误，而是一条待办——
    系统知道自己不懂什么，比假装懂更有用。
    """

    __tablename__ = 'style_pending_questions'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, index=True)
    scene_type: Mapped[str] = mapped_column(String(30), nullable=False, default='auto')
    corpus_ids: Mapped[str] = mapped_column(Text, nullable=False, default='[]')
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow)


class GenerationRecord(Base):
    """生成记录：保存每次生成的四份正文与全部上下文。"""

    __tablename__ = 'generation_records'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False, default='未命名')
    content: Mapped[str | None] = mapped_column(Text, default='')
    deai_content: Mapped[str | None] = mapped_column(Text, default='')
    style_rewrite_content: Mapped[str | None] = mapped_column(Text, default='')
    style_diff_json: Mapped[str | None] = mapped_column(Text, default='{}')
    style_rewrite_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    style_rewrite_applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    style_rewrite_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    edited_content: Mapped[str | None] = mapped_column(Text, default='')
    edit_history: Mapped[str | None] = mapped_column(Text, default='[]')
    model_used: Mapped[str | None] = mapped_column(String(100), default='')
    thinking_enabled: Mapped[bool | None] = mapped_column(Boolean, default=False)
    reasoning_content: Mapped[str | None] = mapped_column(Text, default='')
    assembled_prompt: Mapped[str | None] = mapped_column(Text, default='')
    templates_used: Mapped[str | None] = mapped_column(Text, default='[]')
    variable_values: Mapped[str | None] = mapped_column(Text, default='{}')
    deai_prompt: Mapped[str | None] = mapped_column(Text, default='')
    rating: Mapped[int | None] = mapped_column(Integer, default=0)
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text, default='')
    api_response_raw: Mapped[str | None] = mapped_column(Text, default='')
    style_mode: Mapped[str] = mapped_column(String(30), nullable=False, default='legacy')
    style_profile_snapshot: Mapped[str | None] = mapped_column(Text, default='[]')
    created_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow)

    def _final(self) -> str:
        return self.style_rewrite_content or self.deai_content or self.content or ''

    def to_dict(self) -> dict[str, Any]:
        return {
            'id': self.id,
            'title': self.title,
            'content': self.content,
            'deai_content': self.deai_content,
            'style_rewrite_content': self.style_rewrite_content or '',
            'style_diff_json': self.style_diff_json or '{}',
            'style_rewrite_enabled': bool(self.style_rewrite_enabled),
            'style_rewrite_applied': bool(self.style_rewrite_applied),
            'style_rewrite_count': self.style_rewrite_count or 0,
            'final_content': self._final(),
            'edited_content': self.edited_content,
            'edit_history': self.edit_history,
            'model_used': self.model_used,
            'thinking_enabled': self.thinking_enabled,
            'reasoning_content': self.reasoning_content,
            'assembled_prompt': self.assembled_prompt,
            'templates_used': self.templates_used,
            'deai_prompt': self.deai_prompt,
            'rating': self.rating,
            'pinned': self.pinned,
            'notes': self.notes,
            'style_mode': self.style_mode or 'legacy',
            'style_profile_snapshot': self.style_profile_snapshot or '[]',
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

    def to_brief_dict(self) -> dict[str, Any]:
        final = self._final()
        return {
            'id': self.id,
            'title': self.title,
            'model_used': self.model_used,
            'thinking_enabled': self.thinking_enabled,
            'rating': self.rating,
            'pinned': self.pinned,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'has_deai': bool(self.deai_content),
            'has_style_rewrite': bool(self.style_rewrite_content),
            'has_edited': bool(self.edited_content),
            'content_preview': (final[:200] + '...') if len(final) > 200 else final,
        }

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f'<GenerationRecord {self.title}>'


class ProjectSetting(Base):
    """键值设置（不存 API Key）。"""

    __tablename__ = 'project_settings'

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    value: Mapped[str | None] = mapped_column(Text, default='')
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f'<ProjectSetting {self.key}>'
