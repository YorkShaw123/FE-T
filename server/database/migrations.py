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
        # 一次性数据迁移：仅将旧版种子模板（内容含变量占位符且属于预设名称）标记为示例模板。
        # 注意：不能按“内容含 {{” 全部标记——用户自建的普通模板同样可能使用变量占位符。
        db.session.execute(db.text(
            "UPDATE prompt_templates SET is_sample = 1 "
            "WHERE content LIKE '%{{%' AND name IN ("
            "'主角性格与身份', '配角设定模板', '世界观基础设定', '故事发生场景', "
            "'章节大纲模板', '主线剧情概要', '写作质量要求', '叙事节奏控制')"
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
    db.session.commit()


def _column_names(db, table_name):
    # table_name 来自本模块常量调用，不接受用户输入。
    rows = db.session.execute(db.text(f'PRAGMA table_info({table_name})')).fetchall()
    return {row[1] for row in rows}
