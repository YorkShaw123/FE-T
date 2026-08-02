"""无需额外迁移框架的幂等 SQLite 轻量迁移。"""


def apply_sqlite_migrations(db):
    """补齐旧数据库字段和索引；重复执行不会改变现有数据。"""
    template_columns = _column_names(db, 'prompt_templates')
    if 'style_strength' not in template_columns:
        db.session.execute(db.text(
            "ALTER TABLE prompt_templates "
            "ADD COLUMN style_strength VARCHAR(20) NOT NULL DEFAULT 'light'"
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
    if 'is_pinned' not in record_columns:
        db.session.execute(db.text(
            "ALTER TABLE generation_records "
            "ADD COLUMN is_pinned BOOLEAN NOT NULL DEFAULT 0"
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
    db.session.commit()


def _column_names(db, table_name):
    # table_name 来自本模块常量调用，不接受用户输入。
    rows = db.session.execute(db.text(f'PRAGMA table_info({table_name})')).fetchall()
    return {row[1] for row in rows}
