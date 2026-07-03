# routes/goods.py
from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
from db import get_db_connection
from utils import (
    write_required, log_action, validate_excel_file,
    make_excel_response, get_export_time_str, build_date_filter
)
import logging
import pandas as pd
import os
import uuid

goods_bp = Blueprint('goods', __name__)

# ===================== 商品汇总 =====================
@goods_bp.route('/goods-summary')
def goods_summary():
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    keyword = request.args.get('keyword', '').strip()
    page = request.args.get('page', 1, type=int)
    per_page = 40
    with get_db_connection() as conn:
        date_where = ""
        date_params = []
        if start_date:
            date_where += " AND date(qr.order_time) >= ?"
            date_params.append(start_date)
        if end_date:
            date_where += " AND date(qr.order_time) <= ?"
            date_params.append(end_date)
        keyword_where = ""
        if keyword:
            keyword_where = " AND gd.cleaned_goods LIKE ?"
            date_params.append(f'%{keyword}%')
        count_sql = f"""
            SELECT COUNT(DISTINCT gd.cleaned_goods)
            FROM goods_detail gd
            JOIN query_results qr ON gd.order_code = qr.order_code
            WHERE 1=1 {date_where} {keyword_where}
        """
        total_items = conn.execute(count_sql, date_params).fetchone()[0]
        total_pages = (total_items + per_page - 1) // per_page
        offset = (page - 1) * per_page
        data_sql = f"""
            SELECT gd.cleaned_goods, CAST(SUM(gd.final_quantity) AS INTEGER) AS total
            FROM goods_detail gd
            JOIN query_results qr ON gd.order_code = qr.order_code
            WHERE 1=1 {date_where} {keyword_where}
            GROUP BY gd.cleaned_goods
            ORDER BY total DESC
            LIMIT ? OFFSET ?
        """
        items = conn.execute(data_sql, date_params + [per_page, offset]).fetchall()

    return render_template("goods_summary.html", items=items, start_date=start_date,
                           end_date=end_date, keyword=keyword, page=page, total_pages=total_pages)

@goods_bp.route('/export_goods_summary')
@login_required
def export_goods_summary():
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    time_str = get_export_time_str(start_date, end_date)
    with get_db_connection() as conn:
        where_clauses = ["1=1"]
        params = []
        if start_date:
            where_clauses.append("date(qr.order_time) >= ?")
            params.append(start_date)
        if end_date:
            where_clauses.append("date(qr.order_time) <= ?")
            params.append(end_date)
        valid_sql = f"SELECT DISTINCT order_code FROM query_results qr WHERE {' AND '.join(where_clauses)}"
        data_sql = f"SELECT gd.cleaned_goods AS goods, SUM(gd.final_quantity) AS total FROM goods_detail gd WHERE gd.order_code IN ({valid_sql}) GROUP BY gd.cleaned_goods ORDER BY total DESC"
        items = conn.execute(data_sql, params).fetchall()
    df = pd.DataFrame([dict(row) for row in items])
    filename = f"商品汇总_{time_str}.xlsx"
    return make_excel_response(df, filename)

# ===================== 商品档案管理 =====================
@goods_bp.route('/goods-lib')
def goods_lib():
    return render_template('goods_lib.html')

@goods_bp.route('/api/goods-lib')
def api_goods_lib():
    with get_db_connection() as conn:
        goods = conn.execute("SELECT id, goods_name, extend_code FROM goods_lib ORDER BY id ASC").fetchall()
    return jsonify([dict(g) for g in goods])

@goods_bp.route('/api/goods-import', methods=['POST'])
@login_required
@write_required
def api_goods_import():
    file = request.files.get('file')
    overwrite = request.form.get('overwrite', 'false') == 'true'
    if not file or file.filename == '':
        return jsonify({"success": False, "msg": "未上传文件"})
    valid, err = validate_excel_file(file)
    if not valid:
        return jsonify({"success": False, "msg": err})
    if not file.filename.lower().endswith(('.xls', '.xlsx')):
        return jsonify({"success": False, "msg": "仅支持 Excel 文件"})
    file.seek(0, os.SEEK_END)
    if file.tell() > 5 * 1024 * 1024:
        return jsonify({"success": False, "msg": "文件大小不能超过 5MB"})
    file.seek(0)
    try:
        df = pd.read_excel(file)
        name_col = code_col = None
        for c in df.columns:
            if "商品名称" in str(c):
                name_col = c
            if "商品编码" in str(c):
                code_col = c
        if not name_col:
            return jsonify({"success": False, "msg": "未找到【商品名称】列"})

        inserted = 0
        skipped = 0
        updated = 0
        failed = 0
        with get_db_connection() as conn:
            for _, row in df.iterrows():
                gname = str(row[name_col]).strip()
                gcode = str(row[code_col]).strip() if code_col else ""
                if not gname or gname == "nan":
                    failed += 1
                    continue
                try:
                    exists = conn.execute("SELECT id FROM goods_lib WHERE goods_name = ?", (gname,)).fetchone()
                    if exists:
                        if overwrite:
                            conn.execute("UPDATE goods_lib SET extend_code = ? WHERE id = ?", (gcode, exists['id']))
                            updated += 1
                        else:
                            skipped += 1
                    else:
                        conn.execute("INSERT INTO goods_lib (goods_name, extend_code) VALUES (?, ?)", (gname, gcode))
                        inserted += 1
                except Exception:
                    failed += 1
            conn.commit()
            cache = current_app.extensions.get('cache')
            if cache:
                cache.clear()
        log_action("导入商品档案", f"成功: {inserted}, 跳过: {skipped}, 失败: {failed}")
        return jsonify({
            "success": True,
            "msg": f"导入完成：成功 {inserted} 条，跳过 {skipped} 条，失败 {failed} 条",
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
            "failed": failed
        })
    except Exception as e:
        logging.exception("商品档案导入失败")
        return jsonify({"success": False, "msg": f"导入失败：{str(e)}"})

@goods_bp.route('/api/goods-add', methods=['POST'])
@login_required
@write_required
def api_goods_add():
    name = request.form.get('goods_name','').strip()
    code = request.form.get('extend_code','').strip()
    if not name:
        return jsonify({"success": False, "msg": "商品名称不能为空"})
    try:
        with get_db_connection() as conn:
            exists = conn.execute("SELECT 1 FROM goods_lib WHERE goods_name = ?", (name,)).fetchone()
            if exists:
                return jsonify({"success": False, "msg": "该商品已存在"})
            conn.execute("INSERT INTO goods_lib (goods_name, extend_code) VALUES (?, ?)", (name, code))
            conn.commit()
            cache = current_app.extensions.get('cache')
            if cache:
                cache.clear()
        log_action("新增商品", f"名称: {name}")
        return jsonify({"success": True, "msg": "添加成功"})
    except Exception as e:
        logging.exception("添加商品失败")
        return jsonify({"success": False, "msg": f"添加失败：{str(e)}"})

@goods_bp.route('/api/goods-del', methods=['POST'])
@login_required
@write_required
def api_goods_del():
    data = request.get_json()
    gid = data.get('id')
    with get_db_connection() as conn:
        conn.execute("DELETE FROM goods_lib WHERE id = ?", (gid,))
        conn.commit()
        cache = current_app.extensions.get('cache')
        if cache:
            cache.clear()
    log_action("删除商品", f"商品ID: {gid}")
    return jsonify({"success": True, "msg": "删除成功"})

@goods_bp.route('/api/goods-del-batch', methods=['POST'])
@login_required
@write_required
def api_goods_del_batch():
    data = request.get_json()
    ids = data.get('ids', [])
    if not ids:
        return jsonify({"success": False, "msg": "请选择商品"})
    with get_db_connection() as conn:
        for gid in ids:
            conn.execute("DELETE FROM goods_lib WHERE id = ?", (gid,))
        conn.commit()
        cache = current_app.extensions.get('cache')
        if cache:
            cache.clear()
    log_action("批量删除商品", f"商品ID: {ids}")
    return jsonify({"success": True, "msg": f"成功删除 {len(ids)} 个商品"})

@goods_bp.route('/api/goods-import-preview', methods=['POST'])
@login_required
def api_goods_import_preview():
    file = request.files.get('file')
    if not file or file.filename == '':
        return jsonify({"success": False, "msg": "未上传文件"})
    valid, err = validate_excel_file(file)
    if not valid:
        return jsonify({"success": False, "msg": err})
    if not file.filename.lower().endswith(('.xls', '.xlsx')):
        return jsonify({"success": False, "msg": "仅支持 Excel 文件"})
    file.seek(0, os.SEEK_END)
    if file.tell() > 5 * 1024 * 1024:
        return jsonify({"success": False, "msg": "文件大小不能超过 5MB"})
    file.seek(0)
    try:
        df = pd.read_excel(file)
        name_col = code_col = None
        for c in df.columns:
            if "商品名称" in str(c):
                name_col = c
            if "商品编码" in str(c):
                code_col = c
        if not name_col:
            return jsonify({"success": False, "msg": "未找到【商品名称】列"})

        preview_df = df.head(5)
        columns = preview_df.columns.tolist()
        rows = preview_df.values.tolist()

        statuses = []
        with get_db_connection() as conn:
            for _, row in preview_df.iterrows():
                gname = str(row[name_col]).strip()
                if gname and gname != "nan":
                    exists = conn.execute("SELECT 1 FROM goods_lib WHERE goods_name = ?", (gname,)).fetchone()
                    statuses.append('skip' if exists else 'new')
                else:
                    statuses.append('invalid')

        return jsonify({
            "success": True,
            "columns": columns,
            "rows": rows,
            "total_rows": len(df),
            "statuses": statuses
        })
    except Exception as e:
        logging.exception("预览商品 Excel 失败")
        return jsonify({"success": False, "msg": f"预览失败：{str(e)}"})

@goods_bp.route('/api/goods-match', methods=['GET'])
def goods_match():
    kw = request.args.get('kw', '').strip()
    if not kw:
        return jsonify([])
    try:
        with get_db_connection() as conn:
            res = conn.execute("SELECT goods_name FROM goods_lib WHERE goods_name LIKE ? LIMIT 10", (f'%{kw}%',)).fetchall()
        return jsonify([{"name": r["goods_name"]} for r in res])
    except Exception as e:
        logging.exception("商品联想错误")
        return jsonify([])

# ===================== 异步导入功能 =====================
# 存储任务状态的内存字典（生产环境可改用 Redis）
task_states = {}

@goods_bp.route('/api/goods-import-async', methods=['POST'])
@login_required
@write_required
def api_goods_import_async():
    file = request.files.get('file')
    overwrite = request.form.get('overwrite', 'false') == 'true'
    if not file or file.filename == '':
        return jsonify({"success": False, "msg": "未上传文件"})
    valid, err = validate_excel_file(file)
    if not valid:
        return jsonify({"success": False, "msg": err})
    if not file.filename.lower().endswith(('.xls', '.xlsx')):
        return jsonify({"success": False, "msg": "仅支持 Excel 文件"})
    file.seek(0, os.SEEK_END)
    if file.tell() > 5 * 1024 * 1024:
        return jsonify({"success": False, "msg": "文件大小不能超过 5MB"})
    file.seek(0)

    # 生成任务ID，将文件内容暂存
    task_id = str(uuid.uuid4())
    file_content = file.read()
    task_states[task_id] = {'state': 'PENDING', 'result': None}

    # 获取真实的 app 对象（不能直接使用代理，线程池需要实际对象）
    app = current_app._get_current_object()
    executor = current_app.executor

    future = executor.submit(
        _do_goods_import,
        task_id, file_content, file.filename, overwrite, app,task_states
    )

    def callback(f):
        try:
            task_states[task_id]['state'] = 'SUCCESS'
            task_states[task_id]['result'] = f.result()
        except Exception as e:
            task_states[task_id]['state'] = 'FAILURE'
            task_states[task_id]['result'] = str(e)

    future.add_done_callback(callback)

    return jsonify({"success": True, "task_id": task_id})

@goods_bp.route('/api/goods-import-status/<task_id>')
@login_required
def api_goods_import_status(task_id):
    state_data = task_states.get(task_id, {'state': 'NOT_FOUND'})
    return jsonify(state_data)

def _do_goods_import(task_id, file_content, filename, overwrite, app, task_states):
    from io import BytesIO
    with app.app_context():
        try:
            df = pd.read_excel(BytesIO(file_content))
            total_rows = len(df)
            # 更新任务状态为 RUNNING，progress 起始为 0
            task_states[task_id] = {'state': 'RUNNING', 'progress': 0}

            name_col = code_col = None
            for c in df.columns:
                if "商品名称" in str(c):
                    name_col = c
                if "商品编码" in str(c):
                    code_col = c
            if not name_col:
                return {'success': False, 'msg': '未找到【商品名称】列'}

            inserted = 0
            skipped = 0
            updated = 0
            failed = 0
            with get_db_connection() as conn:
                for idx, row in df.iterrows():
                    gname = str(row[name_col]).strip()
                    gcode = str(row[code_col]).strip() if code_col else ""
                    if not gname or gname == "nan":
                        failed += 1
                    else:
                        try:
                            exists = conn.execute("SELECT id FROM goods_lib WHERE goods_name = ?", (gname,)).fetchone()
                            if exists:
                                if overwrite:
                                    conn.execute("UPDATE goods_lib SET extend_code = ? WHERE id = ?", (gcode, exists['id']))
                                    updated += 1
                                else:
                                    skipped += 1
                            else:
                                conn.execute("INSERT INTO goods_lib (goods_name, extend_code) VALUES (?, ?)", (gname, gcode))
                                inserted += 1
                        except Exception:
                            failed += 1

                    # 更新进度（0-99，完成后设为100）
                    progress = int((idx + 1) / total_rows * 99)
                    task_states[task_id]['progress'] = progress

                conn.commit()
                cache_instance = app.extensions.get('cache')
                if cache_instance:
                    cache_instance.clear()

            task_states[task_id]['progress'] = 100
            log_action("导入商品档案（异步）", f"成功: {inserted}, 更新: {updated}, 跳过: {skipped}, 失败: {failed}")
            return {
                'success': True,
                'msg': f'导入完成：新增 {inserted} 条，更新 {updated} 条，跳过 {skipped} 条，失败 {failed} 条',
                'inserted': inserted, 'updated': updated, 'skipped': skipped, 'failed': failed
            }
        except Exception as e:
            logging.exception("异步导入商品失败")
            task_states[task_id] = {'state': 'FAILURE', 'progress': 0, 'result': str(e)}
            return {'success': False, 'msg': f'导入失败：{str(e)}'}