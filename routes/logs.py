# routes/logs.py
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required
from db import get_db_connection
from utils import make_excel_response, get_export_time_str, log_action
import pandas as pd
import logging
logs_bp = Blueprint('logs', __name__)

@logs_bp.route('/operation-log')
def operation_log_page():
    return render_template('operation_log.html')

@logs_bp.route('/api/operation-log')
def api_operation_log():
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    keyword = request.args.get('keyword', '').strip()
    username = request.args.get('username', '').strip()
    ip_address = request.args.get('ip', '').strip()
    role = request.args.get('role', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 20

    where_clauses = ["1=1"]
    params = []

    if start_date:
        where_clauses.append("date(timestamp) >= ?")
        params.append(start_date)
    if end_date:
        where_clauses.append("date(timestamp) <= ?")
        params.append(end_date)
    if keyword:
        where_clauses.append("(action LIKE ? OR details LIKE ?)")
        params.extend([f'%{keyword}%', f'%{keyword}%'])
    if username:
        where_clauses.append("username LIKE ?")
        params.append(f'%{username}%')
    if ip_address:
        where_clauses.append("ip_address LIKE ?")
        params.append(f'%{ip_address}%')
    if role:
        where_clauses.append("operation_log.username IN (SELECT username FROM users WHERE role = ?)")
        params.append(role)

    where_sql = "WHERE " + " AND ".join(where_clauses)

    with get_db_connection() as conn:
        count_sql = f"SELECT COUNT(*) AS total FROM operation_log {where_sql}"
        total = conn.execute(count_sql, params).fetchone()['total']
        total_pages = (total + per_page - 1) // per_page
        offset = (page - 1) * per_page
        data_sql = f"SELECT * FROM operation_log {where_sql} ORDER BY timestamp DESC LIMIT ? OFFSET ?"
        logs = conn.execute(data_sql, params + [per_page, offset]).fetchall()

    return jsonify({
        "logs": [dict(row) for row in logs],
        "page": page,
        "total_pages": total_pages,
        "total": total
    })

@logs_bp.route('/export_operation_log')
@login_required
def export_operation_log():
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    keyword = request.args.get('keyword', '').strip()
    username = request.args.get('username', '').strip()
    ip_address = request.args.get('ip', '').strip()
    role = request.args.get('role', '').strip()

    where_clauses = ["1=1"]
    params = []
    if start_date:
        where_clauses.append("date(timestamp) >= ?")
        params.append(start_date)
    if end_date:
        where_clauses.append("date(timestamp) <= ?")
        params.append(end_date)
    if keyword:
        where_clauses.append("(action LIKE ? OR details LIKE ?)")
        params.extend([f'%{keyword}%', f'%{keyword}%'])
    if username:
        where_clauses.append("username LIKE ?")
        params.append(f'%{username}%')
    if ip_address:
        where_clauses.append("ip_address LIKE ?")
        params.append(f'%{ip_address}%')
    if role:
        where_clauses.append("operation_log.username IN (SELECT username FROM users WHERE role = ?)")
        params.append(role)

    where_sql = "WHERE " + " AND ".join(where_clauses)

    with get_db_connection() as conn:
        logs = conn.execute(f"SELECT * FROM operation_log {where_sql} ORDER BY timestamp DESC", params).fetchall()

    df = pd.DataFrame([dict(row) for row in logs])
    if not df.empty:
        df = df[['id', 'timestamp', 'username', 'ip_address', 'action', 'details']]
        df.columns = ['ID', '时间', '操作人', 'IP地址', '操作类型', '详情']
    
    time_str = get_export_time_str(start_date, end_date)
    filename = f"操作日志_{time_str}.xlsx"
    return make_excel_response(df, filename)
@logs_bp.route('/api/log-stats')
@login_required
def api_log_stats():
    """返回操作日志统计：最近7天每日操作次数、操作类型分布、操作人排名"""
    with get_db_connection() as conn:
        # 最近7天每日操作次数
        daily = conn.execute("""
            SELECT date(timestamp) AS day, COUNT(*) AS cnt
            FROM operation_log
            WHERE date(timestamp) >= date('now', '-6 days')
            GROUP BY day
            ORDER BY day
        """).fetchall()

        # 操作类型分布
        action_types = conn.execute("""
            SELECT action, COUNT(*) AS cnt
            FROM operation_log
            GROUP BY action
            ORDER BY cnt DESC
            LIMIT 10
        """).fetchall()

        # 操作人排名
        top_users = conn.execute("""
            SELECT username, COUNT(*) AS cnt
            FROM operation_log
            GROUP BY username
            ORDER BY cnt DESC
            LIMIT 10
        """).fetchall()

    return jsonify({
        "daily": [dict(row) for row in daily],
        "action_types": [dict(row) for row in action_types],
        "top_users": [dict(row) for row in top_users]
    })