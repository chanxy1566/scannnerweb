# utils.py
from functools import wraps
from datetime import datetime, timedelta
from flask import request, jsonify, make_response
from flask_login import current_user
from db import get_db_connection          # 数据库连接
from io import BytesIO
import pandas as pd
from urllib.parse import quote
import logging
import filetype

# ===================== 工具函数 =====================
def build_date_filter(start_date, end_date, table_alias="", field="order_time"):
    clauses = []
    params = []
    prefix = f"{table_alias}." if table_alias else ""
    if start_date:
        clauses.append(f"date({prefix}{field}) >= ?")
        params.append(start_date)
    if end_date:
        clauses.append(f"date({prefix}{field}) <= ?")
        params.append(end_date)
    return clauses, params

def make_excel_response(df, filename):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='data', index=False)
    output.seek(0)
    resp = make_response(output.read())
    resp.headers["Content-Type"] = "application/vnd.ms-excel"
    resp.headers["Content-Disposition"] = f"attachment;filename*=utf-8''{quote(filename)}"
    return resp

# ===================== 文件类型校验 =====================
ALLOWED_MIME = {
    'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',  # .xlsx
    'application/vnd.ms-excel',  # .xls
}

def validate_excel_file(file):
    """更宽松的 Excel 文件校验，扩展名或文件头任一匹配即放行"""
    # 1. 检查扩展名（简单有效）
    filename = file.filename
    if filename and '.' in filename:
        ext = filename.rsplit('.', 1)[-1].lower()
        if ext in ('xls', 'xlsx'):
            return True, None

    # 2. 再试文件头魔数
    try:
        header = file.read(261)
        file.seek(0)
        kind = filetype.guess(header)
        if kind and kind.mime in ALLOWED_MIME:
            return True, None
    except Exception:
        file.seek(0)

    return False, "不支持的文件类型，仅允许上传 Excel 文件"

# ===================== 登录失败限制（数据库持久化） =====================
MAX_ATTEMPTS = 5
LOCKOUT_TIME = timedelta(minutes=10)

def is_locked_out(identifier):
    cutoff = (datetime.now() - LOCKOUT_TIME).strftime('%Y-%m-%d %H:%M:%S')
    with get_db_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM login_attempts WHERE identifier = ? AND attempt_time > ?",
            (identifier, cutoff)
        ).fetchone()[0]
    return count >= MAX_ATTEMPTS

def record_failed_attempt(identifier):
    with get_db_connection() as conn:
        conn.execute("INSERT INTO login_attempts (identifier) VALUES (?)", (identifier,))
        conn.commit()

def reset_attempts(identifier):
    with get_db_connection() as conn:
        conn.execute("DELETE FROM login_attempts WHERE identifier = ?", (identifier,))
        conn.commit()

# 导出时间字符串
def get_export_time_str(start_date, end_date):
    if not start_date and not end_date:
        return "全部时间"
    try:
        s_dt = datetime.strptime(start_date, '%Y-%m-%d') if start_date else None
        e_dt = datetime.strptime(end_date, '%Y-%m-%d') if end_date else None
        s_str = f"{s_dt.month}月{s_dt.day}日" if s_dt else "开始"
        e_str = f"{e_dt.month}月{e_dt.day}日" if e_dt else "结束"
        return s_str if s_str == e_str else f"{s_str}-{e_str}"
    except:
        return "全部时间"

# 操作日志记录（自动获取当前用户和IP）
def log_action(action, details=""):
    try:
        # 尝试获取当前用户，不存在则用默认值
        try:
            username = current_user.username if current_user.is_authenticated else '未登录'
        except (RuntimeError, AttributeError):
            username = '系统'  # 后台任务

        # 尝试获取 IP，不存在则用默认值
        try:
            ip_address = request.remote_addr or ''
        except (RuntimeError, AttributeError):
            ip_address = '后台任务'

        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO operation_log (action, details, username, ip_address) VALUES (?, ?, ?, ?)",
                (action, details, username, ip_address)
            )
            conn.commit()
    except Exception as e:
        logging.error(f"记录操作日志失败：{e}")

# 权限装饰器
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            return jsonify({"success": False, "msg": "需要管理员权限"}), 403
        return f(*args, **kwargs)
    return decorated

def write_required(f):
    """要求登录，且角色为 admin 或 editor"""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated:
            return jsonify({"success": False, "msg": "请先登录"}), 401
        if current_user.role not in ['admin', 'editor']:
            return jsonify({"success": False, "msg": "需要编辑权限"}), 403
        return f(*args, **kwargs)
    return decorated

# 缓存键生成
def make_cache_key():
    return request.url

# 数据脱敏
SENSITIVE_KEYS = {'password', 'csrf_token', 'token'}
def sanitize_data(data):
    if isinstance(data, dict):
        return {k: ('***' if k in SENSITIVE_KEYS else v) for k, v in data.items()}
    return data