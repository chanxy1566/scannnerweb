# routes/orders.py
from flask import Blueprint, render_template, request, jsonify, redirect, url_for, current_app
from flask_login import login_required, current_user
from db import get_db_connection
from utils import (
    build_date_filter, make_excel_response, get_export_time_str,
    write_required, log_action
)
import pandas as pd
import logging
orders_bp = Blueprint('orders', __name__)

# ===================== 首页（订单列表） =====================
@orders_bp.route('/', methods=['GET'])
def index():
    keyword = request.args.get('keyword', '')
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 12, type=int)
    if per_page not in [12, 24, 48, 96]:
        per_page = 12
    offset = (page - 1) * per_page

    # 排序参数
    sort_by = request.args.get('sort', 'id')
    sort_order = request.args.get('order', 'desc')
    allowed_sorts = ['id', 'order_time', 'original_quantity', 'source_table', 'order_code']
    if sort_by not in allowed_sorts:
        sort_by = 'id'
    if sort_order not in ['asc', 'desc']:
        sort_order = 'desc'

    # 构建 WHERE 条件
    where_clauses = ["1=1"]
    params = []
    if keyword:
        where_clauses.append("(qr.order_code LIKE ? OR qr.original_goods LIKE ?)")
        params.extend([f'%{keyword}%', f'%{keyword}%'])
    date_clauses, date_params = build_date_filter(start_date, end_date, "qr")
    where_clauses.extend(date_clauses)
    params.extend(date_params)
    where_sql = "WHERE " + " AND ".join(where_clauses)

    with get_db_connection() as conn:
        count_sql = f"SELECT COUNT(DISTINCT qr.id) FROM query_results qr {where_sql}"
        total_orders = conn.execute(count_sql, params).fetchone()[0]
        data_sql = f"""SELECT qr.* FROM query_results qr {where_sql}
                       ORDER BY qr.{sort_by} {sort_order}
                       LIMIT ? OFFSET ?"""
        orders = conn.execute(data_sql, params + [per_page, offset]).fetchall()

    total_pages = (total_orders + per_page - 1) // per_page
    return render_template('index.html',
                           orders=orders,
                           keyword=keyword,
                           start_date=start_date,
                           end_date=end_date,
                           page=page,
                           total_pages=total_pages,
                           sort_by=sort_by,
                           sort_order=sort_order,
                           per_page=per_page)

# ===================== 导出订单 =====================
@orders_bp.route('/export_order')
@login_required
def export_order():
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    time_str = get_export_time_str(start_date, end_date)
    clauses = ["1=1"]
    params = []
    date_clauses, date_params = build_date_filter(start_date, end_date)
    clauses.extend(date_clauses)
    params.extend(date_params)
    where_sql = "WHERE " + " AND ".join(clauses)

    with get_db_connection() as conn:
        orders = conn.execute(f"SELECT * FROM query_results qr {where_sql} ORDER BY qr.id DESC", params).fetchall()

    df = pd.DataFrame([dict(row) for row in orders])
    filename = f"售后订单_{time_str}.xlsx"
    return make_excel_response(df, filename)

# ===================== 订单明细页面及API =====================
@orders_bp.route('/detail')
@orders_bp.route('/detail/<order_code>')
def detail(order_code=None):
    if not order_code:
        order_code = request.args.get('order_code', '')
    with get_db_connection() as conn:
        goods = conn.execute(
            "SELECT id, split_goods, extend_code, original_quantity, final_quantity, original_goods, multiplier, order_time FROM goods_detail WHERE order_code = ?",
            (order_code,)
        ).fetchall()
        order_info = conn.execute("SELECT extend_code FROM query_results WHERE order_code = ? LIMIT 1", (order_code,)).fetchone()
        order_extend_code = order_info['extend_code'] if order_info else ''
        default_row = conn.execute(
            "SELECT original_goods, multiplier, order_time FROM goods_detail WHERE order_code = ? ORDER BY id LIMIT 1",
            (order_code,)
        ).fetchone()
        if default_row:
            original_goods = default_row['original_goods'] or ''
            multiplier = default_row['multiplier'] or 1
            order_time = default_row['order_time'] or ''
        else:
            original_goods, multiplier, order_time = '', 1, ''

    return render_template('detail.html',
                           order_code=order_code,
                           goods=goods,
                           order_extend_code=order_extend_code,
                           original_goods=original_goods,
                           multiplier=multiplier,
                           order_time=order_time)

@orders_bp.route('/api/detail/<order_code>')
def api_detail(order_code):
    with get_db_connection() as conn:
        goods = conn.execute(
            "SELECT id, split_goods, extend_code, original_quantity, final_quantity, original_goods, multiplier, order_time FROM goods_detail WHERE order_code = ?",
            (order_code,)
        ).fetchall()
    return jsonify([dict(row) for row in goods])

@orders_bp.route('/export_detail')
@login_required
def export_detail():
    order_code = request.args.get('order_code', '')
    with get_db_connection() as conn:
        goods = conn.execute(
            "SELECT id, order_code, split_goods, extend_code, original_quantity, final_quantity, cleaned_goods, source_table, original_goods, multiplier, order_time FROM goods_detail WHERE order_code = ?",
            (order_code,)
        ).fetchall()
    df = pd.DataFrame([dict(row) for row in goods])
    filename = f"订单明细_{order_code}.xlsx"
    return make_excel_response(df, filename)

# ===================== 添加商品页面及提交 =====================
@orders_bp.route('/add')
def add_page():
    order_code = request.args.get('order_code', '')
    return render_template('add.html', order_code=order_code)

@orders_bp.route('/add-g', methods=['POST'])
@login_required
@write_required
def add_g():
    order_code = request.form.get('order_code', '').strip()
    goods_list = request.form.getlist('g[]')
    code_list = request.form.getlist('ec[]')
    qty_list = request.form.getlist('q[]')
    orig_list = request.form.getlist('orig[]')
    mult_list = request.form.getlist('mult[]')
    time_list = request.form.getlist('time[]')

    if not order_code:
        return "订单号不能为空", 400

    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            for g, ec, q, orig, mult, otime in zip(goods_list, code_list, qty_list,
                                                   orig_list, mult_list, time_list):
                g = g.strip()
                ec = ec.strip()
                try:
                    q = int(q)
                except:
                    return f"无效的数量：{q}", 400
                if q < 1:
                    continue
                orig = orig.strip() if orig else ''
                try:
                    mult = float(mult) if mult else 1.0
                except:
                    mult = 1.0
                otime = otime.strip() if otime else ''

                existing = conn.execute(
                    "SELECT id FROM goods_detail WHERE order_code = ? AND split_goods = ? AND extend_code = ?",
                    (order_code, g, ec)
                ).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE goods_detail SET original_quantity = original_quantity + ?, final_quantity = final_quantity + ? WHERE id = ?",
                        (q, q, existing['id'])
                    )
                else:
                    cur.execute(
                        "INSERT INTO goods_detail (order_code, split_goods, extend_code, original_quantity, final_quantity, cleaned_goods, source_table, original_goods, multiplier, order_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (order_code, g, ec, q, q, g, "手动添加", orig, mult, otime)
                    )
            conn.commit()
            # 清除缓存
            cache = current_app.extensions.get('cache')
            if cache:
                cache.clear()
         # 安全获取最后一条商品信息
        last_g = g if 'g' in dir() else '无'
        last_ec = ec if 'ec' in dir() else ''
        last_q = q if 'q' in dir() else 0
        log_action("添加商品明细", f"订单: {order_code}, 商品: {last_g}, 编码: {last_ec}, 数量: {last_q}")
        return "OK", 200
    except Exception as e:
        logging.exception("添加商品错误")
        return f"失败：{e}", 500

@orders_bp.route('/add-goods', methods=['POST'])
@login_required
@write_required
def add_goods():
    order_code = request.form.get('order_code', '').strip()
    goods_names = request.form.getlist('std_name[]')
    quantities = request.form.getlist('quantity[]')
    if not order_code or not goods_names:
        return "参数错误", 400
    with get_db_connection() as conn:
        cur = conn.cursor()
        for g, q_str in zip(goods_names, quantities):
            try:
                q = int(q_str)
                if q < 1:
                    continue
            except:
                continue
            g = g.strip()
            sample = conn.execute(
                "SELECT extend_code, source_table, original_goods, multiplier, order_time FROM goods_detail WHERE cleaned_goods = ? LIMIT 1",
                (g,)).fetchone()
            extend_code = sample["extend_code"] if sample else "无编码"
            source_table = sample["source_table"] if sample else "手动添加"
            orig = sample["original_goods"] if sample else ""
            mult = sample["multiplier"] if sample else 1.0
            otime = sample["order_time"] if sample else ""
            cur.execute(
                "INSERT INTO goods_detail (order_code, split_goods, extend_code, original_quantity, final_quantity, cleaned_goods, source_table, original_goods, multiplier, order_time) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (order_code, g, extend_code, q, q, g, source_table, orig, mult, otime)
            )
        conn.commit()
        cache = current_app.extensions.get('cache')
        if cache:
            cache.clear()
    log_action("表单添加商品", f"订单: {order_code}")
    return redirect(url_for('orders.detail', order_code=order_code))

# ===================== 修改/删除明细 =====================
@orders_bp.route('/api/update', methods=['POST'])
@login_required
@write_required
def api_update():
    data = request.get_json()
    with get_db_connection() as conn:
        if isinstance(data, list):
            for item in data:
                qty = item.get('final_quantity')
                if not isinstance(qty, (int, float)) or qty < 0:
                    return jsonify({"ok": False, "msg": "数量无效"}), 400
                conn.execute("UPDATE goods_detail SET final_quantity = ? WHERE id = ?",
                             (qty, item['id']))
        else:
            qty = data.get('final_quantity')
            if not isinstance(qty, (int, float)) or qty < 0:
                return jsonify({"ok": False, "msg": "数量无效"}), 400
            conn.execute("UPDATE goods_detail SET final_quantity = ? WHERE id = ?",
                         (qty, data['id']))
        conn.commit()
        cache = current_app.extensions.get('cache')
        if cache:
            cache.clear()
    log_action("修改数量", f"更新行数: {len(data) if isinstance(data, list) else 1}")
    return jsonify({"ok": True})

@orders_bp.route('/api/deleteDetail', methods=['POST'])
@login_required
@write_required
def api_delete_detail():
    data = request.get_json()
    detail_id = data.get('id')
    if not detail_id:
        return jsonify({"success": False, "msg": "缺少明细ID"})
    try:
        with get_db_connection() as conn:
            conn.execute("DELETE FROM goods_detail WHERE id = ?", (detail_id,))
            conn.commit()
            cache = current_app.extensions.get('cache')
            if cache:
                cache.clear()
        log_action("删除明细", f"明细ID: {detail_id}")
        return jsonify({"success": True, "msg": "删除成功"})
    except Exception as e:
        logging.exception("删除明细失败")
        return jsonify({"success": False, "msg": f"删除失败：{str(e)}"})

@orders_bp.route('/api/deleteOrder', methods=['POST'])
@login_required
@write_required
def api_delete_order():
    data = request.get_json()
    order_id = data.get('id')
    order_code = data.get('order_code')
    if not order_id or not order_code:
        return jsonify({"success": False, "msg": "参数不完整"})
    try:
        with get_db_connection() as conn:
            conn.execute("BEGIN")
            conn.execute("DELETE FROM query_results WHERE id = ?", (order_id,))
            conn.execute("DELETE FROM goods_detail WHERE order_code = ?", (order_code,))
            conn.execute("DELETE FROM set_detail WHERE order_code = ?", (order_code,))
            conn.commit()
            cache = current_app.extensions.get('cache')
            if cache:
                cache.clear()
        log_action("删除整单", f"订单ID: {order_id}, 订单号: {order_code}")
        return jsonify({"success": True, "msg": "订单及关联数据已全部删除"})
    except Exception as e:
        logging.exception("删除整单失败")
        return jsonify({"success": False, "msg": f"删除失败：{str(e)}"})

@orders_bp.route('/api/deleteOrdersBatch', methods=['POST'])
@login_required
@write_required
def api_delete_orders_batch():
    data = request.get_json()
    ids = data.get('ids', [])
    if not ids:
        return jsonify({"success": False, "msg": "请选择要删除的订单"})
    try:
        with get_db_connection() as conn:
            conn.execute("BEGIN")
            for oid in ids:
                order = conn.execute("SELECT order_code FROM query_results WHERE id = ?", (oid,)).fetchone()
                if not order:
                    continue
                order_code = order['order_code']
                conn.execute("DELETE FROM query_results WHERE id = ?", (oid,))
                conn.execute("DELETE FROM goods_detail WHERE order_code = ?", (order_code,))
                conn.execute("DELETE FROM set_detail WHERE order_code = ?", (order_code,))
            conn.commit()
            cache = current_app.extensions.get('cache')
            if cache:
                cache.clear()
        log_action("批量删除订单", f"订单ID: {ids}")
        return jsonify({"success": True, "msg": f"成功删除 {len(ids)} 个订单"})
    except Exception as e:
        logging.exception("批量删除订单失败")
        return jsonify({"success": False, "msg": str(e)})

@orders_bp.route('/api/updateMultiplier', methods=['POST'])
@login_required
@write_required
def api_update_multiplier():
    data = request.get_json()
    multiplier = data.get('multiplier')
    ids = data.get('ids', [])
    if not isinstance(multiplier, (int, float)) or multiplier <= 0:
        return jsonify({"success": False, "msg": "倍数无效"})
    if not ids:
        return jsonify({"success": False, "msg": "没有选择明细"})
    try:
        with get_db_connection() as conn:
            for detail_id in ids:
                conn.execute(
                    "UPDATE goods_detail SET final_quantity = ROUND(final_quantity * ?, 0) WHERE id = ?",
                    (multiplier, detail_id)
                )
            conn.commit()
            cache = current_app.extensions.get('cache')
            if cache:
                cache.clear()
        log_action("批量乘以倍数", f"明细ID: {ids}, 倍数: {multiplier}")
        return jsonify({"success": True, "msg": f"成功将 {len(ids)} 条明细乘以 {multiplier}"})
    except Exception as e:
        logging.exception("乘以倍数失败")
        return jsonify({"success": False, "msg": f"操作失败：{str(e)}"})