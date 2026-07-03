# app.py
from flask import Flask, request, jsonify, redirect, url_for
from flask_login import LoginManager, current_user
from flasgger import Swagger
from flask_wtf.csrf import CSRFProtect
from config import Config
from db import init_db, bcrypt, cache
from models import User
from backup import start_scheduler
import logging
import os
import io

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    # 初始化扩展
    bcrypt.init_app(app)
    csrf = CSRFProtect(app)
    login_manager = LoginManager(app)
    login_manager.login_view = 'auth.login_page'
    swagger = Swagger(app)
    cache.init_app(app)

    # 用户加载
    @login_manager.user_loader
    def load_user(user_id):
        return User.get(user_id)

    # 注册蓝图
    from routes.auth import auth_bp
    from routes.orders import orders_bp
    from routes.goods import goods_bp
    from routes.sets import sets_bp
    from routes.dashboard import dashboard_bp
    from routes.logs import logs_bp
    from routes.scanner import scanner_bp

    app.register_blueprint(auth_bp, url_prefix='')
    app.register_blueprint(orders_bp, url_prefix='')
    app.register_blueprint(goods_bp, url_prefix='')
    app.register_blueprint(sets_bp, url_prefix='')
    app.register_blueprint(dashboard_bp, url_prefix='')
    app.register_blueprint(logs_bp, url_prefix='')
    app.register_blueprint(scanner_bp, url_prefix='')

    # 启动全局键盘监听（仅非测试环境）
    if not app.config.get('TESTING'):
        from keyboard_listener import keyboard_listener
        keyboard_listener.start()
        import atexit
        atexit.register(keyboard_listener.stop)

    # 创建线程池
    import concurrent.futures
    app.executor = concurrent.futures.ThreadPoolExecutor(max_workers=3)

    # 全局登录检查
    @app.before_request
    def require_login():
        allowed_prefixes = ['/static', '/login', '/logout', '/apidocs', '/flasgger_static', '/health']
        if any(request.path.startswith(p) for p in allowed_prefixes):
            return None
        if not current_user.is_authenticated:
            if request.path.startswith('/api/'):
                return jsonify({"error": "Unauthorized"}), 401
            return redirect(url_for('auth.login_page', next=request.url))

    # 健康检查
    @app.route('/health')
    def health_check():
        try:
            from db import get_db_connection
            with get_db_connection() as conn:
                conn.execute("SELECT 1")
            db_status = "ok"
        except Exception as e:
            db_status = f"error: {e}"
        return jsonify({"status": "running", "database": db_status})

    # 初始化数据库
    with app.app_context():
        init_db()

    # 启动定时任务
    if not app.config.get('TESTING'):
        start_scheduler()

    # 仅在非测试环境下加载 Excel 缓存
    if not app.config.get('TESTING'):
        import threading
        from routes.scanner import load_excel_data
        threading.Thread(target=load_excel_data, daemon=True).start()

    return app

# 创建模块级别的 app 对象，供 waitress 导入
app = create_app()

# 修复日志乱码（控制台输出 UTF-8）
logging.basicConfig(level=logging.INFO)
root_logger = logging.getLogger()
for handler in root_logger.handlers:
    if isinstance(handler, logging.StreamHandler) and hasattr(handler.stream, 'buffer'):
        handler.stream = io.TextIOWrapper(handler.stream.buffer, encoding='utf-8')

if __name__ == '__main__':
    from waitress import serve
    logging.info("启动生产服务器（waitress）...")
    serve(app, host='0.0.0.0', port=5001)