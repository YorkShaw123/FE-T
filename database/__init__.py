"""
数据库初始化和会话管理
"""
import os
from sqlalchemy import event
from sqlalchemy.engine import Engine
from flask_sqlalchemy import SQLAlchemy
from database.migrations import apply_sqlite_migrations

db = SQLAlchemy()


@event.listens_for(Engine, 'connect')
def configure_sqlite(connection, _record):
    """为本地 SQLite 启用并发友好的参数与外键约束。"""
    if connection.__class__.__module__.startswith('sqlite3'):
        cursor = connection.cursor()
        cursor.execute('PRAGMA foreign_keys=ON')
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.execute('PRAGMA synchronous=NORMAL')
        cursor.execute('PRAGMA busy_timeout=30000')
        cursor.close()


def init_db(app):
    """初始化数据库"""
    # 解析数据库URI，提取文件路径
    db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    if db_uri.startswith('sqlite:///'):
        db_path = db_uri[len('sqlite:///'):]
        # 规范化路径分隔符（Windows兼容）
        db_path = os.path.normpath(db_path)
        data_dir = os.path.dirname(db_path)
        if data_dir and not os.path.exists(data_dir):
            os.makedirs(data_dir, exist_ok=True)
            print(f'[Forestar] 已创建数据目录: {data_dir}')

    db.init_app(app)
    with app.app_context():
        # 导入所有模型，确保表被创建
        from database.models import (  # noqa: F401
            PromptTemplate, GenerationRecord, ProjectSetting, StyleProfile, StyleExcerpt,
        )
        db.create_all()
        apply_sqlite_migrations(db)

        # 首次启动时，如果模板表为空，自动填充预设模板
        if PromptTemplate.query.count() == 0:
            from database.seed import seed_templates
            seed_templates()

    print(f'[Forestar] 数据库已就绪: {db_path}')
