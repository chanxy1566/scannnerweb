# routes/dashboard.py
from flask import Blueprint, render_template, request, jsonify, current_app, make_response
from flask_login import login_required
from db import get_db_connection, cache
from utils import make_cache_key, make_excel_response, build_date_filter
from datetime import datetime
import pandas as pd
from io import BytesIO
from urllib.parse import quote
import pandas as pd
import logging
dashboard_bp = Blueprint('dashboard', __name__)

# ===================== 仪表盘页面 =====================
@dashboard_bp.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

# ===================== 订单趋势 =====================
@dashboard_bp.route('/api/order-trend')
##@cache.cached(timeout=300, key_prefix=make_cache_key)
def api_order_trend():
    start_date = request.args.get('start_date', '').strip()
    end_date = request.args.get('end_date', '').strip()
    source = request.args.get('source', '').strip()
    if not start_date:
        start_date = (datetime.now() - pd.Timedelta(days=13)).strftime('%Y-%m-%d')
    if not end_date:
        end_date = datetime.now().strftime('%Y-%m-%d')

    dates = []
    counts = []
    current = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')
    while current <= end:
        day_str = current.strftime('%Y-%m-%d')
        dates.append(day_str)
        with get_db_connection() as conn:
            query = "SELECT COUNT(*) FROM query_results WHERE date(order_time) = ?"
            params = [day_str]
            if source:
                query += " AND source_table = ?"
                params.append(source)
            count = conn.execute(query, params).fetchone()[0]
        counts.append(count)
        current += pd.Timedelta(days=1)
    return jsonify({"dates": dates, "counts": counts})

# ===================== 仪表盘核心摘要 =====================
@dashboard_bp.route('/api/dashboard/summary')
##@cache.cached(timeout=300, key_prefix=make_cache_key)
def dashboard_summary():
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    source = request.args.get('source', '').strip()
    
    order_filter = "SELECT order_code FROM query_results WHERE 1=1"
    params = []
    if start_date:
        order_filter += " AND date(order_time) >= ?"
        params.append(start_date)
    if end_date:
        order_filter += " AND date(order_time) <= ?"
        params.append(end_date)
    if source:
        order_filter += " AND source_table = ?"
        params.append(source)

    with get_db_connection() as conn:
        total_orders = conn.execute(f"SELECT COUNT(*) FROM ({order_filter})", params).fetchone()[0]
        total_details = conn.execute(f"SELECT COUNT(*) FROM goods_detail WHERE order_code IN ({order_filter})", params).fetchone()[0]
        total_sets = conn.execute(f"SELECT COUNT(*) FROM set_detail WHERE order_code IN ({order_filter})", params).fetchone()[0]
        goods_kinds = conn.execute(f"SELECT COUNT(DISTINCT cleaned_goods) FROM goods_detail WHERE order_code IN ({order_filter})", params).fetchone()[0]
        set_kinds = conn.execute(f"SELECT COUNT(DISTINCT set_name) FROM set_detail WHERE order_code IN ({order_filter}) AND set_name IS NOT NULL AND set_name != ''", params).fetchone()[0]

    return jsonify({
        "total_orders": total_orders,
        "total_details": total_details,
        "total_sets": total_sets,
        "goods_kinds": goods_kinds,
        "set_kinds": set_kinds
    })

# ===================== 数据来源分布 =====================
@dashboard_bp.route('/api/dashboard/source-distribution')
#@cache.cached(timeout=300, key_prefix=make_cache_key)
def dashboard_source_distribution():
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    params = []
    date_filter = ""
    if start_date:
        date_filter += " AND date(qr.order_time) >= ?"
        params.append(start_date)
    if end_date:
        date_filter += " AND date(qr.order_time) <= ?"
        params.append(end_date)
    with get_db_connection() as conn:
        rows = conn.execute(
            f"SELECT source_table, COUNT(*) AS count FROM query_results qr WHERE 1=1 {date_filter} GROUP BY source_table ORDER BY count DESC",
            params
        ).fetchall()
    labels = [row['source_table'] or '未知' for row in rows]
    counts = [row['count'] for row in rows]
    return jsonify({"labels": labels, "counts": counts})

# ===================== Top 商品 =====================
@dashboard_bp.route('/api/dashboard/top-goods')
#@cache.cached(timeout=300, key_prefix=make_cache_key)
def dashboard_top_goods():
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    source = request.args.get('source', '').strip()
    order_filter = "SELECT order_code FROM query_results WHERE 1=1"
    params = []
    if start_date:
        order_filter += " AND date(order_time) >= ?"
        params.append(start_date)
    if end_date:
        order_filter += " AND date(order_time) <= ?"
        params.append(end_date)
    if source:
        order_filter += " AND source_table = ?"
        params.append(source)
    with get_db_connection() as conn:
        rows = conn.execute(
            f"SELECT cleaned_goods, CAST(SUM(final_quantity) AS INTEGER) AS total FROM goods_detail WHERE order_code IN ({order_filter}) GROUP BY cleaned_goods ORDER BY total DESC LIMIT 10",
            params
        ).fetchall()
    labels = [row['cleaned_goods'] or '未知' for row in rows]
    totals = [row['total'] for row in rows]
    return jsonify({"labels": labels, "totals": totals})

# ===================== Top 套装 =====================
@dashboard_bp.route('/api/dashboard/top-sets')
#@cache.cached(timeout=300, key_prefix=make_cache_key)
def dashboard_top_sets():
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    source = request.args.get('source', '').strip()
    order_filter = "SELECT order_code FROM query_results WHERE 1=1"
    params = []
    if start_date:
        order_filter += " AND date(order_time) >= ?"
        params.append(start_date)
    if end_date:
        order_filter += " AND date(order_time) <= ?"
        params.append(end_date)
    if source:
        order_filter += " AND source_table = ?"
        params.append(source)
    with get_db_connection() as conn:
        rows = conn.execute(
            f"SELECT set_name, CAST(SUM(set_quantity) AS INTEGER) AS total FROM set_detail WHERE order_code IN ({order_filter}) AND set_name IS NOT NULL AND set_name != '' GROUP BY set_name ORDER BY total DESC LIMIT 10",
            params
        ).fetchall()
    labels = [row['set_name'] for row in rows]
    totals = [row['total'] for row in rows]
    return jsonify({"labels": labels, "totals": totals})

# ===================== 月度订单趋势 =====================
@dashboard_bp.route('/api/dashboard/monthly-orders')
#@cache.cached(timeout=300, key_prefix=make_cache_key)
def dashboard_monthly_orders():
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    source = request.args.get('source', '').strip()
    params = []
    date_filter = ""
    if start_date:
        date_filter += " AND date(qr.order_time) >= ?"
        params.append(start_date)
    if end_date:
        date_filter += " AND date(qr.order_time) <= ?"
        params.append(end_date)
    if source:
        date_filter += " AND qr.source_table = ?"
        params.append(source)
    with get_db_connection() as conn:
        rows = conn.execute(f"""
            SELECT strftime('%Y-%m', qr.order_time) AS month, COUNT(*) AS count
            FROM query_results qr
            WHERE 1=1 {date_filter}
            GROUP BY month
            ORDER BY month
        """, params).fetchall()
    months = [row['month'] for row in rows]
    counts = [row['count'] for row in rows]
    return jsonify({"months": months, "counts": counts})

# ===================== 商品数量区间分布 =====================
@dashboard_bp.route('/api/dashboard/goods-distribution')
#@cache.cached(timeout=300, key_prefix=make_cache_key)
def dashboard_goods_distribution():
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    source = request.args.get('source', '').strip()
    order_filter = "SELECT order_code FROM query_results WHERE 1=1"
    params = []
    if start_date:
        order_filter += " AND date(order_time) >= ?"
        params.append(start_date)
    if end_date:
        order_filter += " AND date(order_time) <= ?"
        params.append(end_date)
    if source:
        order_filter += " AND source_table = ?"
        params.append(source)
    with get_db_connection() as conn:
        rows = conn.execute(f"""
            SELECT cleaned_goods, SUM(final_quantity) AS total
            FROM goods_detail
            WHERE order_code IN ({order_filter})
            GROUP BY cleaned_goods
        """, params).fetchall()
    
    bins = {"1-10": 0, "11-50": 0, "51-100": 0, "101-500": 0, ">500": 0}
    for row in rows:
        total = row['total'] or 0
        if total <= 10:
            bins["1-10"] += 1
        elif total <= 50:
            bins["11-50"] += 1
        elif total <= 100:
            bins["51-100"] += 1
        elif total <= 500:
            bins["101-500"] += 1
        else:
            bins[">500"] += 1
    labels = list(bins.keys())
    counts = list(bins.values())
    return jsonify({"labels": labels, "counts": counts})

# ===================== 统计数据（用于首页卡片） =====================
@dashboard_bp.route('/api/stats')
def api_stats():
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    keyword = request.args.get('keyword', '').strip()

    where_clauses = ["1=1"]
    params = []
    if keyword:
        where_clauses.append("(qr.order_code LIKE ? OR qr.original_goods LIKE ?)")
        params.extend([f'%{keyword}%', f'%{keyword}%'])
    if start_date:
        where_clauses.append("date(qr.order_time) >= ?")
        params.append(start_date)
    if end_date:
        where_clauses.append("date(qr.order_time) <= ?")
        params.append(end_date)
    where_sql = "WHERE " + " AND ".join(where_clauses)

    with get_db_connection() as conn:
        total_orders = conn.execute(
            f"SELECT COUNT(DISTINCT qr.id) FROM query_results qr {where_sql}", params
        ).fetchone()[0]

        order_filter_sql = f"SELECT qr.order_code FROM query_results qr {where_sql}"
        goods_kinds = conn.execute(
            f"SELECT COUNT(DISTINCT gd.cleaned_goods) FROM goods_detail gd WHERE gd.order_code IN ({order_filter_sql})", params
        ).fetchone()[0]

        set_kinds = conn.execute(
            f"SELECT COUNT(DISTINCT sd.set_name) FROM set_detail sd WHERE sd.order_code IN ({order_filter_sql}) AND sd.set_name IS NOT NULL AND sd.set_name != ''", params
        ).fetchone()[0]

        last_op = conn.execute("SELECT MAX(timestamp) FROM operation_log").fetchone()[0]

    return jsonify({
        "total_orders": total_orders,
        "goods_kinds": goods_kinds,
        "set_kinds": set_kinds,
        "last_operation": last_op or "暂无"
    })

# ===================== 导出仪表盘图表数据 =====================
@dashboard_bp.route('/api/dashboard/export/<chart_type>')
@login_required
def dashboard_export_chart(chart_type):
    # 根据图表类型调用对应的API获取数据
    if chart_type == 'trend':
        data = api_order_trend().get_json()
        df = pd.DataFrame({'日期': data['dates'], '订单数': data['counts']})
    elif chart_type == 'source':
        data = dashboard_source_distribution().get_json()
        df = pd.DataFrame({'数据来源': data['labels'], '数量': data['counts']})
    elif chart_type == 'top-goods':
        data = dashboard_top_goods().get_json()
        df = pd.DataFrame({'商品名称': data['labels'], '总数量': data['totals']})
    elif chart_type == 'top-sets':
        data = dashboard_top_sets().get_json()
        df = pd.DataFrame({'套装名称': data['labels'], '总套数': data['totals']})
    elif chart_type == 'monthly':
        data = dashboard_monthly_orders().get_json()
        df = pd.DataFrame({'月份': data['months'], '订单数': data['counts']})
    elif chart_type == 'goods-distribution':           # ← 新增
        data = dashboard_goods_distribution().get_json()
        df = pd.DataFrame({'区间': data['labels'], '商品种类数': data['counts']})
    else:
        return jsonify({"error": "无效的图表类型"}), 400

    output = BytesIO()
    df.to_csv(output, index=False, encoding='utf-8-sig')
    output.seek(0)
    resp = make_response(output.read())
    resp.headers["Content-Type"] = "text/csv; charset=utf-8-sig"
    resp.headers["Content-Disposition"] = f"attachment;filename*=utf-8''{quote(chart_type)}.csv"
    return resp

# ===================== 数据来源列表 =====================
@dashboard_bp.route('/api/source-tables')
def api_source_tables():
    with get_db_connection() as conn:
        rows = conn.execute("SELECT DISTINCT source_table FROM query_results WHERE source_table IS NOT NULL AND source_table != ''").fetchall()
    tables = [row['source_table'] for row in rows]
    return jsonify(tables)
# ===================== 操作日志可视化 =====================
@dashboard_bp.route('/api/dashboard/log-daily')
@login_required
def dashboard_log_daily():
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    params = []
    where = "WHERE 1=1"
    if start_date:
        where += " AND date(timestamp) >= ?"
        params.append(start_date)
    if end_date:
        where += " AND date(timestamp) <= ?"
        params.append(end_date)
    with get_db_connection() as conn:
        rows = conn.execute(f"""
            SELECT date(timestamp) as day, COUNT(*) as cnt
            FROM operation_log
            {where}
            GROUP BY day
            ORDER BY day
        """, params).fetchall()
    return jsonify({"days": [row['day'] for row in rows], "counts": [row['cnt'] for row in rows]})

@dashboard_bp.route('/api/dashboard/log-action-types')
@login_required
def dashboard_log_action_types():
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    params = []
    where = "WHERE 1=1"
    if start_date:
        where += " AND date(timestamp) >= ?"
        params.append(start_date)
    if end_date:
        where += " AND date(timestamp) <= ?"
        params.append(end_date)
    with get_db_connection() as conn:
        rows = conn.execute(f"""
            SELECT action, COUNT(*) as cnt
            FROM operation_log
            {where}
            GROUP BY action
            ORDER BY cnt DESC
        """, params).fetchall()
    return jsonify({"actions": [row['action'] for row in rows], "counts": [row['cnt'] for row in rows]})
@dashboard_bp.route('/api/dashboard/log-top-users')
@login_required
def dashboard_log_top_users():
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    params = []
    where = "WHERE 1=1"
    if start_date:
        where += " AND date(timestamp) >= ?"
        params.append(start_date)
    if end_date:
        where += " AND date(timestamp) <= ?"
        params.append(end_date)
    with get_db_connection() as conn:
        rows = conn.execute(f"""
            SELECT username, COUNT(*) as cnt
            FROM operation_log
            {where}
            GROUP BY username
            ORDER BY cnt DESC
            LIMIT 10
        """, params).fetchall()
    return jsonify({
        "users": [row['username'] for row in rows],
        "counts": [row['cnt'] for row in rows]
    })