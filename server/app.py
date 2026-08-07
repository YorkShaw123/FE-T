"""
Forestar Editor - AI文字创作助手
主应用入口
"""
import os
import shutil
import sys

# 路径解析必须先于 config 导入执行，因为 config 的 SQLALCHEMY_DATABASE_URI
# 在类定义时求值（对原始运行方式无影响）：
# - 静态资源（templates/static）：
#     * PyInstaller 打包环境位于解压临时目录 sys._MEIPASS
#     * 源码运行位于项目根目录
# - 用户数据（SQLite 数据库）：Web 版与桌面版统一存放到同一公共目录
#   %USERPROFILE%\.forestar-editor\data，实现两版数据互通；可通过
#   环境变量 FORESTAR_DATA_DIR 覆盖到其他位置
def _resolve_data_dir():
    """解析用户数据目录（Web 版与桌面版共享同一份数据）"""
    if os.environ.get('FORESTAR_DATA_DIR'):
        return os.environ['FORESTAR_DATA_DIR']
    return os.path.join(os.path.expanduser('~'), '.forestar-editor', 'data')


def _resolve_run_mode():
    """解析当前运行模式，固化产品定位：

    - 'desktop'：桌面分发模式（主要产品形态）。后端由 PyInstaller 打包，
      被 Tauri 以 Sidecar 方式拉起并管理生命周期，不面向用户单独启动。
    - 'web'    ：Web 模式（开发调试 / 高级用户自托管入口）。用于日常开发
      调试（免打包热重载），或熟悉 Python/Docker 的用户自行部署。

    判定优先级：环境变量 FORESTAR_RUN_MODE 显式指定 > PyInstaller 打包
    （frozen）视为桌面分发模式 > 默认按 Web 模式处理。
    """
    explicit = os.environ.get('FORESTAR_RUN_MODE', '').strip().lower()
    if explicit:
        return explicit if explicit in ('desktop', 'web') else 'web'
    return 'desktop' if getattr(sys, 'frozen', False) else 'web'


# 项目根目录（server/ 的上级），用于定位 Web 版旧数据目录
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))


def _migrate_legacy_data():
    """首次运行时，把 Web 版旧数据（项目根 data/）迁移到统一数据目录。

    仅当统一目录尚不存在数据库、且项目根 data/ 有旧库时执行；
    迁移采用复制而非移动，保留原目录作为安全备份。
    """
    data_dir = _resolve_data_dir()
    if os.path.exists(os.path.join(data_dir, 'forestar.db')):
        return
    legacy_dir = os.path.join(_PROJECT_ROOT, 'data')
    if not os.path.exists(os.path.join(legacy_dir, 'forestar.db')):
        return
    os.makedirs(data_dir, exist_ok=True)
    for name in ('forestar.db', 'forestar.db-wal', 'forestar.db-shm'):
        src = os.path.join(legacy_dir, name)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(data_dir, name))


if getattr(sys, 'frozen', False):
    _RESOURCE_BASE = sys._MEIPASS
else:
    _RESOURCE_BASE = os.path.abspath(os.path.dirname(__file__))

if not os.environ.get('DATABASE_URL'):
    _db_path = os.path.join(_resolve_data_dir(), 'forestar.db').replace('\\', '/')
    os.environ['DATABASE_URL'] = f'sqlite:///{_db_path}'

from flask import Flask, render_template
from config import config_by_name
from database import init_db
from routes.template_routes import template_bp
from routes.generation_routes import generation_bp
from routes.style_routes import style_bp


def create_app(config_name=None):
    """应用工厂函数"""
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')

    app = Flask(
        __name__,
        template_folder=os.path.join(_RESOURCE_BASE, 'templates'),
        static_folder=os.path.join(_RESOURCE_BASE, 'static'),
    )
    app.config.from_object(config_by_name.get(config_name, config_by_name['default']))

    # 首次运行时迁移 Web 版旧数据到统一数据目录
    _migrate_legacy_data()

    # 初始化数据库
    init_db(app)

    # 注册蓝图
    app.register_blueprint(template_bp)
    app.register_blueprint(generation_bp)
    app.register_blueprint(style_bp)

    # 注册错误处理
    register_error_handlers(app)

    # 注册路由
    @app.route('/')
    def index():
        return render_template('index.html')

    # 健康检查（mode 字段返回当前运行形态，便于前端/运维识别）
    @app.route('/api/health')
    def health():
        return {'status': 'ok', 'app': 'Forestar Editor', 'mode': _resolve_run_mode()}

    return app


def register_error_handlers(app):
    """注册全局错误处理器"""

    @app.errorhandler(404)
    def not_found(error):
        return {'success': False, 'error': '接口不存在'}, 404

    @app.errorhandler(500)
    def server_error(error):
        return {'success': False, 'error': '服务器内部错误'}, 500

    @app.errorhandler(400)
    def bad_request(error):
        return {'success': False, 'error': '请求参数错误'}, 400


if __name__ == '__main__':
    app = create_app()
    # 监听地址默认仅本机；自托管（如 Docker）时通过 FORESTAR_HOST 暴露给局域网/公网
    host = os.environ.get('FORESTAR_HOST', '127.0.0.1')
    port = int(os.environ.get('FORESTAR_PORT', '5000'))
    if _resolve_run_mode() == 'web':
        # Web 模式：开发调试 + 高级用户自托管入口（桌面版为唯一主分发形态）
        print("=" * 60)
        print("  Forestar Editor - AI文字创作助手")
        print("  Web 版（开发调试 / 高级用户自托管入口）")
        print(f"  访问地址: http://{host}:{port}")
        print("  普通用户请运行根目录的 Forestar Editor.exe（桌面版，免环境配置）")
        print("  提示: 可用环境变量 FORESTAR_HOST / FORESTAR_PORT 覆盖监听地址与端口")
        print("=" * 60)
    else:
        # 桌面分发模式：由 Tauri 主程序以 Sidecar 方式拉起，生命周期由其管理
        print(f"[desktop] Forestar 后端已就绪（由主程序管理）: http://{host}:{port}")
    # 打包后禁用 debug/reloader，避免子进程重启导致 Sidecar 管理失控
    debug = os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(host=host, port=port, debug=debug, use_reloader=False)
