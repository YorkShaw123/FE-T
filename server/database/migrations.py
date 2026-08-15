"""无需额外迁移框架的幂等 SQLite 轻量迁移。"""

from sqlalchemy.exc import OperationalError


def apply_sqlite_migrations(db):
    """补齐旧数据库字段和索引；重复执行不会改变现有数据。"""
    template_columns = _column_names(db, 'prompt_templates')
    if 'style_strength' not in template_columns:
        db.session.execute(db.text(
            "ALTER TABLE prompt_templates "
            "ADD COLUMN style_strength VARCHAR(20) NOT NULL DEFAULT 'light'"
        ))
    if 'is_sample' not in template_columns:
        db.session.execute(db.text(
            "ALTER TABLE prompt_templates "
            "ADD COLUMN is_sample BOOLEAN NOT NULL DEFAULT 0"
        ))
    # 示例模板功能已移除：保留兼容字段以避免破坏性重建 SQLite 表，
    # 并将历史示例无损转换为可编辑的普通模板。
    db.session.execute(db.text(
        "UPDATE prompt_templates SET is_sample = 0 WHERE is_sample != 0"
    ))

    record_columns = _column_names(db, 'generation_records')
    if 'edited_content' not in record_columns:
        db.session.execute(db.text(
            "ALTER TABLE generation_records ADD COLUMN edited_content TEXT DEFAULT ''"
        ))
    if 'edit_history' not in record_columns:
        db.session.execute(db.text(
            "ALTER TABLE generation_records ADD COLUMN edit_history TEXT DEFAULT '[]'"
        ))
    if 'style_mode' not in record_columns:
        db.session.execute(db.text(
            "ALTER TABLE generation_records "
            "ADD COLUMN style_mode VARCHAR(30) NOT NULL DEFAULT 'legacy'"
        ))
    if 'style_profile_snapshot' not in record_columns:
        db.session.execute(db.text(
            "ALTER TABLE generation_records "
            "ADD COLUMN style_profile_snapshot TEXT DEFAULT '[]'"
        ))
    generation_record_additions = {
        'style_rewrite_content': "TEXT DEFAULT ''",
        'style_diff_json': "TEXT DEFAULT '{}'",
        'style_rewrite_enabled': 'BOOLEAN NOT NULL DEFAULT 0',
        'style_rewrite_applied': 'BOOLEAN NOT NULL DEFAULT 0',
        'style_rewrite_count': 'INTEGER NOT NULL DEFAULT 0',
    }
    for column_name, definition in generation_record_additions.items():
        if column_name not in record_columns:
            db.session.execute(db.text(
                f'ALTER TABLE generation_records ADD COLUMN {column_name} {definition}'
            ))
    # 清理旧字段：若同时存在 is_pinned 与 pinned，保留 pinned
    if 'is_pinned' in record_columns and 'pinned' not in record_columns:
        db.session.execute(db.text(
            "ALTER TABLE generation_records RENAME COLUMN is_pinned TO pinned"
        ))
    elif 'is_pinned' in record_columns and 'pinned' in record_columns:
        db.session.execute(db.text(
            "ALTER TABLE generation_records DROP COLUMN is_pinned"
        ))
    if 'pinned' not in record_columns:
        db.session.execute(db.text(
            "ALTER TABLE generation_records ADD COLUMN pinned BOOLEAN NOT NULL DEFAULT 0"
        ))

    db.session.execute(db.text(
        'CREATE INDEX IF NOT EXISTS ix_prompt_templates_category_active '
        'ON prompt_templates (category, is_active, sort_order)'
    ))
    db.session.execute(db.text(
        'CREATE INDEX IF NOT EXISTS ix_generation_records_created '
        'ON generation_records (created_at DESC)'
    ))
    db.session.execute(db.text(
        'CREATE INDEX IF NOT EXISTS ix_style_profiles_source_hash '
        'ON style_profiles (source_hash)'
    ))
    db.session.execute(db.text(
        'CREATE INDEX IF NOT EXISTS ix_style_excerpts_profile_scene '
        'ON style_excerpts (style_profile_id, scene_type, is_enabled, source_order)'
    ))

    # ---- Style RAG：海量风格语料库（独立于单篇范例 Style Card）----
    db.session.execute(db.text(
        """
        CREATE TABLE IF NOT EXISTS style_corpora (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            source_filename TEXT DEFAULT '',
            total_chars INTEGER NOT NULL DEFAULT 0,
            chunk_count INTEGER NOT NULL DEFAULT 0,
            index_status VARCHAR(30) NOT NULL DEFAULT 'empty',
            embedding_model VARCHAR(100) DEFAULT '',
            embedding_backend VARCHAR(50) DEFAULT '',
            embedding_model_version VARCHAR(100) DEFAULT '',
            embedding_dim INTEGER NOT NULL DEFAULT 0,
            signature_version INTEGER NOT NULL DEFAULT 0,
            created_at DATETIME,
            updated_at DATETIME
        )
        """
    ))
    db.session.execute(db.text(
        """
        CREATE TABLE IF NOT EXISTS style_chunks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            corpus_id INTEGER NOT NULL,
            content TEXT NOT NULL,
            content_hash VARCHAR(64) NOT NULL,
            article_key VARCHAR(64) NOT NULL DEFAULT '',
            source_order INTEGER NOT NULL DEFAULT 0,
            char_count INTEGER NOT NULL DEFAULT 0,
            style_feature_version INTEGER NOT NULL DEFAULT 0,
            style_features_json TEXT NOT NULL DEFAULT '{}',
            style_window_valid_chars INTEGER NOT NULL DEFAULT 0,
            style_confidence FLOAT NOT NULL DEFAULT 0.0,
            style_window_start_order INTEGER NOT NULL DEFAULT 0,
            style_window_end_order INTEGER NOT NULL DEFAULT 0,
            style_signature_version INTEGER NOT NULL DEFAULT 0,
            style_signature_json TEXT NOT NULL DEFAULT '{}',
            scene_type VARCHAR(50) NOT NULL DEFAULT 'mixed',
            pacing VARCHAR(30) NOT NULL DEFAULT 'medium',
            pov VARCHAR(80) DEFAULT '',
            emotion VARCHAR(200) DEFAULT '',
            dialogue_ratio FLOAT NOT NULL DEFAULT 0.0,
            embedding_blob BLOB,
            embedding_model VARCHAR(100) DEFAULT '',
            embedding_backend VARCHAR(50) DEFAULT '',
            embedding_model_version VARCHAR(100) DEFAULT '',
            embedding_dim INTEGER NOT NULL DEFAULT 0,
            is_enabled BOOLEAN NOT NULL DEFAULT 1,
            created_at DATETIME,
            FOREIGN KEY (corpus_id) REFERENCES style_corpora(id) ON DELETE CASCADE
        )
        """
    ))
    db.session.execute(db.text(
        """
        CREATE TABLE IF NOT EXISTS author_style_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            corpus_id INTEGER NOT NULL UNIQUE,
            feature_version INTEGER NOT NULL,
            profile_json TEXT NOT NULL DEFAULT '{}',
            sample_count INTEGER NOT NULL DEFAULT 0,
            valid_char_count INTEGER NOT NULL DEFAULT 0,
            confidence FLOAT NOT NULL DEFAULT 0.0,
            created_at DATETIME,
            updated_at DATETIME,
            FOREIGN KEY (corpus_id) REFERENCES style_corpora(id) ON DELETE CASCADE
        )
        """
    ))
    chunk_columns = _column_names(db, 'style_chunks')
    style_chunk_columns = {
        'article_key': "VARCHAR(64) NOT NULL DEFAULT ''",
        'style_feature_version': 'INTEGER NOT NULL DEFAULT 0',
        'style_features_json': "TEXT NOT NULL DEFAULT '{}'",
        'style_window_valid_chars': 'INTEGER NOT NULL DEFAULT 0',
        'style_confidence': 'FLOAT NOT NULL DEFAULT 0.0',
        'style_window_start_order': 'INTEGER NOT NULL DEFAULT 0',
        'style_window_end_order': 'INTEGER NOT NULL DEFAULT 0',
        'embedding_backend': "VARCHAR(50) DEFAULT ''",
        'embedding_model_version': "VARCHAR(100) DEFAULT ''",
        'style_signature_version': 'INTEGER NOT NULL DEFAULT 0',
        'style_signature_json': "TEXT NOT NULL DEFAULT '{}'",
    }
    for column_name, definition in style_chunk_columns.items():
        if column_name not in chunk_columns:
            db.session.execute(db.text(
                f'ALTER TABLE style_chunks ADD COLUMN {column_name} {definition}'
            ))
    corpus_columns = _column_names(db, 'style_corpora')
    corpus_embedding_columns = {
        'embedding_backend': "VARCHAR(50) DEFAULT ''",
        'embedding_model_version': "VARCHAR(100) DEFAULT ''",
        'signature_version': 'INTEGER NOT NULL DEFAULT 0',
    }
    for column_name, definition in corpus_embedding_columns.items():
        if column_name not in corpus_columns:
            db.session.execute(db.text(
                f'ALTER TABLE style_corpora ADD COLUMN {column_name} {definition}'
            ))
    db.session.execute(db.text(
        'CREATE INDEX IF NOT EXISTS ix_style_chunks_corpus '
        'ON style_chunks (corpus_id, source_order)'
    ))
    db.session.execute(db.text(
        'CREATE INDEX IF NOT EXISTS ix_style_chunks_article '
        'ON style_chunks (corpus_id, article_key, source_order)'
    ))
    db.session.execute(db.text(
        'CREATE INDEX IF NOT EXISTS ix_style_chunks_scene '
        'ON style_chunks (corpus_id, scene_type, pacing, is_enabled)'
    ))
    db.session.execute(db.text(
        'CREATE UNIQUE INDEX IF NOT EXISTS ix_author_style_profiles_corpus '
        'ON author_style_profiles (corpus_id)'
    ))
    db.session.execute(db.text(
        'CREATE INDEX IF NOT EXISTS ix_author_style_profiles_version '
        'ON author_style_profiles (feature_version)'
    ))
    # FTS5 全文索引（BM25 词汇级检索）；trigram tokenizer 对中文友好。
    # 依赖 Python 内置 SQLite 的 FTS5 支持（官方 Python 3.11+ 默认开启）。
    fts_available = _ensure_style_chunks_fts(db)
    # 只在主表与 FTS 的行数/rowid 校验不一致时重建，兼顾异常修复与启动速度。
    if fts_available:
        chunk_stats = db.session.execute(db.text(
            "SELECT COUNT(*), COALESCE(SUM(id), 0) FROM style_chunks"
        )).one()
        fts_stats = db.session.execute(db.text(
            "SELECT COUNT(*), COALESCE(SUM(rowid), 0) FROM style_chunks_fts"
        )).one()
        if tuple(chunk_stats) != tuple(fts_stats):
            db.session.execute(db.text("DELETE FROM style_chunks_fts"))
            db.session.execute(db.text(
                "INSERT INTO style_chunks_fts(rowid, content) "
                "SELECT id, content FROM style_chunks"
            ))
    db.session.commit()


def _column_names(db, table_name):
    # table_name 来自本模块常量调用，不接受用户输入。
    rows = db.session.execute(db.text(f'PRAGMA table_info({table_name})')).fetchall()
    return {row[1] for row in rows}


def _ensure_style_chunks_fts(db):
    """Prefer Chinese trigram FTS; degrade to no BM25 if FTS5 is unavailable."""
    try:
        db.session.execute(db.text(
            "CREATE VIRTUAL TABLE IF NOT EXISTS style_chunks_fts "
            "USING fts5(content, tokenize='trigram', content_rowid='id')"
        ))
    except OperationalError:
        # Some system SQLite builds omit FTS5 or the trigram tokenizer. The
        # Dense Style Engine remains fully usable without this optional signal.
        return False
    return True
