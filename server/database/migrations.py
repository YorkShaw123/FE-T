"""无需额外迁移框架的幂等 SQLite 轻量迁移。"""


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
            embedding_dim INTEGER NOT NULL DEFAULT 0,
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
            source_order INTEGER NOT NULL DEFAULT 0,
            char_count INTEGER NOT NULL DEFAULT 0,
            scene_type VARCHAR(50) NOT NULL DEFAULT 'mixed',
            pacing VARCHAR(30) NOT NULL DEFAULT 'medium',
            pov VARCHAR(80) DEFAULT '',
            emotion VARCHAR(200) DEFAULT '',
            dialogue_ratio FLOAT NOT NULL DEFAULT 0.0,
            embedding_blob BLOB,
            embedding_model VARCHAR(100) DEFAULT '',
            embedding_dim INTEGER NOT NULL DEFAULT 0,
            is_enabled BOOLEAN NOT NULL DEFAULT 1,
            created_at DATETIME,
            FOREIGN KEY (corpus_id) REFERENCES style_corpora(id) ON DELETE CASCADE
        )
        """
    ))
    db.session.execute(db.text(
        'CREATE INDEX IF NOT EXISTS ix_style_chunks_corpus '
        'ON style_chunks (corpus_id, source_order)'
    ))
    db.session.execute(db.text(
        'CREATE INDEX IF NOT EXISTS ix_style_chunks_scene '
        'ON style_chunks (corpus_id, scene_type, pacing, is_enabled)'
    ))
    # FTS5 全文索引（BM25 词汇级检索）；trigram tokenizer 对中文友好。
    # 依赖 Python 内置 SQLite 的 FTS5 支持（官方 Python 3.11+ 默认开启）。
    db.session.execute(db.text(
        "CREATE VIRTUAL TABLE IF NOT EXISTS style_chunks_fts "
        "USING fts5(content, tokenize='trigram', content_rowid='id')"
    ))
    # 只在主表与 FTS 的行数/rowid 校验不一致时重建，兼顾异常修复与启动速度。
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
