"""幂等迁移：把旧库补齐到当前模型，重复执行不改变现有数据。

对照课件 3.2 与旧实现 ``server/database/migrations.py``：
- 建表用 ``CREATE TABLE IF NOT EXISTS``（由 ``Base.metadata.create_all`` 生成）；
- 加列前先查 ``PRAGMA table_info``，只加缺失的列；
- 禁止 DROP / TRUNCATE 等破坏性语句（旧库里的 ``is_pinned`` 是唯一例外，
  它属于历史遗留的同义列，按旧实现的规则处理）。

SQLite 不支持 ``ADD COLUMN IF NOT EXISTS``，所以"先查再加"是这里唯一可靠的写法。
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.logger import get_logger
from backend.db import session_scope
from backend.db.models import Base

logger = get_logger(__name__)


# (表, 列, 列定义) —— 与旧实现逐条对应
_COLUMN_PATCHES: tuple[tuple[str, str, str], ...] = (
    ('prompt_templates', 'style_strength', "VARCHAR(20) NOT NULL DEFAULT 'light'"),
    ('prompt_templates', 'is_sample', 'BOOLEAN NOT NULL DEFAULT 0'),
    ('generation_records', 'edited_content', "TEXT DEFAULT ''"),
    ('generation_records', 'edit_history', "TEXT DEFAULT '[]'"),
    ('generation_records', 'style_mode', "VARCHAR(30) NOT NULL DEFAULT 'legacy'"),
    ('generation_records', 'style_profile_snapshot', "TEXT DEFAULT '[]'"),
    ('generation_records', 'style_rewrite_content', "TEXT DEFAULT ''"),
    ('generation_records', 'style_diff_json', "TEXT DEFAULT '{}'"),
    ('generation_records', 'style_rewrite_enabled', 'BOOLEAN NOT NULL DEFAULT 0'),
    ('generation_records', 'style_rewrite_applied', 'BOOLEAN NOT NULL DEFAULT 0'),
    ('generation_records', 'style_rewrite_count', 'INTEGER NOT NULL DEFAULT 0'),
    ('style_chunks', 'article_key', "VARCHAR(64) NOT NULL DEFAULT ''"),
    ('style_chunks', 'style_feature_version', 'INTEGER NOT NULL DEFAULT 0'),
    ('style_chunks', 'style_features_json', "TEXT NOT NULL DEFAULT '{}'"),
    ('style_chunks', 'style_window_valid_chars', 'INTEGER NOT NULL DEFAULT 0'),
    ('style_chunks', 'style_confidence', 'FLOAT NOT NULL DEFAULT 0.0'),
    ('style_chunks', 'style_window_start_order', 'INTEGER NOT NULL DEFAULT 0'),
    ('style_chunks', 'style_window_end_order', 'INTEGER NOT NULL DEFAULT 0'),
    ('style_chunks', 'embedding_backend', "VARCHAR(50) DEFAULT ''"),
    ('style_chunks', 'embedding_model_version', "VARCHAR(100) DEFAULT ''"),
    ('style_chunks', 'style_signature_version', 'INTEGER NOT NULL DEFAULT 0'),
    ('style_chunks', 'style_signature_json', "TEXT NOT NULL DEFAULT '{}'"),
    ('style_corpora', 'embedding_backend', "VARCHAR(50) DEFAULT ''"),
    ('style_corpora', 'embedding_model_version', "VARCHAR(100) DEFAULT ''"),
    ('style_corpora', 'signature_version', 'INTEGER NOT NULL DEFAULT 0'),
)

_INDEXES: tuple[str, ...] = (
    'CREATE INDEX IF NOT EXISTS ix_prompt_templates_category_active '
    'ON prompt_templates (category, is_active, sort_order)',
    'CREATE INDEX IF NOT EXISTS ix_generation_records_created '
    'ON generation_records (created_at DESC)',
    'CREATE INDEX IF NOT EXISTS ix_style_profiles_source_hash '
    'ON style_profiles (source_hash)',
    'CREATE INDEX IF NOT EXISTS ix_style_excerpts_profile_scene '
    'ON style_excerpts (style_profile_id, scene_type, is_enabled, source_order)',
    'CREATE INDEX IF NOT EXISTS ix_style_chunks_corpus '
    'ON style_chunks (corpus_id, source_order)',
    'CREATE INDEX IF NOT EXISTS ix_style_chunks_article '
    'ON style_chunks (corpus_id, article_key, source_order)',
    'CREATE INDEX IF NOT EXISTS ix_style_chunks_scene '
    'ON style_chunks (corpus_id, scene_type, pacing, is_enabled)',
    'CREATE UNIQUE INDEX IF NOT EXISTS ix_author_style_profiles_corpus '
    'ON author_style_profiles (corpus_id)',
    'CREATE INDEX IF NOT EXISTS ix_author_style_profiles_version '
    'ON author_style_profiles (feature_version)',
)


async def _table_columns(session: AsyncSession, table: str) -> set[str]:
    # 表名只来自本模块常量，不接受用户输入。
    rows = (await session.execute(text(f'PRAGMA table_info({table})'))).fetchall()
    return {row[1] for row in rows}


async def _apply_column_patches(session: AsyncSession) -> int:
    applied = 0
    cache: dict[str, set[str]] = {}
    for table, column, definition in _COLUMN_PATCHES:
        if table not in cache:
            cache[table] = await _table_columns(session, table)
        if column in cache[table]:
            continue
        await session.execute(text(f'ALTER TABLE {table} ADD COLUMN {column} {definition}'))
        cache[table].add(column)
        applied += 1
        logger.debug('db.column_added', table=table, column=column)
    return applied


async def _fix_legacy_pinned(session: AsyncSession) -> None:
    """历史遗留：is_pinned 与 pinned 同义，保留 pinned。"""
    columns = await _table_columns(session, 'generation_records')
    if 'is_pinned' in columns and 'pinned' not in columns:
        await session.execute(
            text('ALTER TABLE generation_records RENAME COLUMN is_pinned TO pinned')
        )
        logger.info('db.pinned_column_renamed')
    elif 'is_pinned' in columns and 'pinned' in columns:
        await session.execute(text('ALTER TABLE generation_records DROP COLUMN is_pinned'))
        logger.info('db.pinned_column_dropped')


async def _normalize_sample_flag(session: AsyncSession) -> None:
    """旧版"系统示例"降级为普通可编辑模板（与旧实现一致）。"""
    await session.execute(text('UPDATE prompt_templates SET is_sample = 0 WHERE is_sample != 0'))


async def _ensure_fts(session: AsyncSession) -> bool:
    """FTS5 全文索引（中文用 trigram 分词）；不可用则跳过，不影响纯 Style 检索。"""
    try:
        await session.execute(text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS style_chunks_fts "
            "USING fts5(content, tokenize='trigram', content_rowid='id')"
        ))
    except OperationalError as exc:
        logger.warning('db.fts_unavailable', error=str(exc))
        return False

    chunk_stats = (await session.execute(text(
        'SELECT COUNT(*), COALESCE(SUM(id), 0) FROM style_chunks'
    ))).one()
    fts_stats = (await session.execute(text(
        'SELECT COUNT(*), COALESCE(SUM(rowid), 0) FROM style_chunks_fts'
    ))).one()
    if tuple(chunk_stats) != tuple(fts_stats):
        # 行数或 rowid 和不一致说明索引与主表脱节，重建一次
        await session.execute(text('DELETE FROM style_chunks_fts'))
        await session.execute(text(
            'INSERT INTO style_chunks_fts(rowid, content) SELECT id, content FROM style_chunks'
        ))
        logger.info('db.fts_rebuilt')
    return True


def _create_all(sync_session) -> None:
    """``AsyncSession.run_sync`` 传进来的是同步 Session，需要取出连接再建表。"""
    Base.metadata.create_all(sync_session.connection(), checkfirst=True)


async def run_migrations() -> dict[str, int | bool]:
    """启动时执行；返回概要，便于日志与测试断言。"""
    async with session_scope() as session:
        await session.run_sync(_create_all)
        await _fix_legacy_pinned(session)
        columns_added = await _apply_column_patches(session)
        await _normalize_sample_flag(session)
        for statement in _INDEXES:
            await session.execute(text(statement))
        fts_ready = await _ensure_fts(session)

    summary = {'columns_added': columns_added, 'fts_ready': fts_ready, 'indexes': len(_INDEXES)}
    logger.info('db.migrations_done', **summary)
    return summary
