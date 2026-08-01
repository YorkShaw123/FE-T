"""
Forestar Editor - AI文字创作助手
主应用入口
"""
import os
from flask import Flask, render_template
from config import config_by_name
from database import init_db
from routes.template_routes import template_bp
from routes.generation_routes import generation_bp


def create_app(config_name=None):
    """应用工厂函数"""
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'development')

    app = Flask(__name__)
    app.config.from_object(config_by_name.get(config_name, config_by_name['default']))

    # 初始化数据库
    init_db(app)

    # 注册蓝图
    app.register_blueprint(template_bp)
    app.register_blueprint(generation_bp)

    # 注册错误处理
    register_error_handlers(app)

    # 注册路由
    @app.route('/')
    def index():
        return render_template('index.html')

    # 健康检查
    @app.route('/api/health')
    def health():
        return {'status': 'ok', 'app': 'Forestar Editor'}

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
    print("=" * 60)
    print("  Forestar Editor - AI文字创作助手")
    print("  访问地址: http://127.0.0.1:5000")
    print("=" * 60)
    app.run(host='127.0.0.1', port=5000, debug=True)
