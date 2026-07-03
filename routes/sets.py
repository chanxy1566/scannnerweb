# routes/sets.py
from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
from db import get_db_connection
from utils import (
    write_required, log_action, validate_excel_file,
    make_excel_response, get_export_time_str
)
import pandas as pd
import logging
import os
import uuid
import json
from datetime import datetime

sets_bp = Blueprint('sets', __name__)

@sets_bp.route('/set-summary')
def set_summary():
    page = request.args.get('page', 1, type=int)
    per_page = 13
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    keyword = request.args.get('keyword', '').strip()
    with get_db_connection() as conn:
        date_filter = ""
        params = []
        if start_date:
            date_filter += " AND date(sd.order_time) >= ?"
            params.append(start_date)
        if end_date:
            date_filter += " AND date(sd.order_time) <= ?"
            params.append(end_date)
        keyword_filter = ""
        if keyword:
            keyword_filter = " AND sd.set_name LIKE ?"
            params.append(f'%{keyword}%')
        count_sql = f"SELECT COUNT(*) AS total FROM (SELECT sd.set_name FROM set_detail sd WHERE sd.set_name IS NOT NULL AND sd.set_name != '' {date_filter} {keyword_filter} GROUP BY sd.set_name) t"
        total = conn.execute(count_sql, params).fetchone()['total']
        total_pages = (total + per_page - 1) // per_page
        offset = (page - 1) * per_page
        data_sql = f"SELECT sd.set_name, CAST(SUM(sd.set_quantity) AS INTEGER) AS total_sets FROM set_detail sd WHERE sd.set_name IS NOT NULL AND sd.set_name != '' {date_filter} {keyword_filter} GROUP BY sd.set_name ORDER BY total_sets DESC LIMIT ? OFFSET ?"
        items = conn.execute(data_sql, params + [per_page, offset]).fetchall()
    return render_template("set_summary.html", items=items, page=page,
                           total_pages=total_pages, start_date=start_date,
                           end_date=end_date, keyword=keyword)

@sets_bp.route('/export_set_summary')
@login_required
def export_set_summary():
    start_date = request.args.get('start_date', '')
    end_date = request.args.get('end_date', '')
    time_str = get_export_time_str(start_date, end_date)
    with get_db_connection() as conn:
        date_filter = ""
        params = []
        if start_date:
            date_filter += " AND date(order_time) >= ?"
            params.append(start_date)
        if end_date:
            date_filter += " AND date(order_time) <= ?"
            params.append(end_date)
        data_sql = f"SELECT set_name, CAST(SUM(set_quantity) AS INTEGER) AS total FROM set_detail WHERE set_name IS NOT NULL AND set_name != '' {date_filter} GROUP BY set_name ORDER BY total DESC"
        items = conn.execute(data_sql, params).fetchall()
    df = pd.DataFrame([dict(row) for row in items])
    filename = f"套装汇总_{time_str}.xlsx"
    return make_excel_response(df, filename)

@sets_bp.route('/goods-set-lib')
def goods_set_lib_page():
    return render_template('goods_set_lib.html')

from flask import make_response

@sets_bp.route('/api/goods-set-lib')
def api_goods_set_lib():
    with get_db_connection() as conn:
        extra_cols = get_extra_columns()
        cols = ['id', 'set_name', 'set_code'] + extra_cols + ['extras']
        sql = f"SELECT {', '.join(cols)} FROM goods_set_lib ORDER BY id ASC"
        data = conn.execute(sql).fetchall()
    resp = make_response(jsonify([dict(row) for row in data]))
    # 禁止浏览器缓存JSON数据
    resp.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    resp.headers['Pragma'] = 'no-cache'
    resp.headers['Expires'] = '0'
    return resp

@sets_bp.route('/api/goods-set-import', methods=['POST'])
@login_required
@write_required
def api_goods_set_import():
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
        df = pd.read_excel(file, dtype=str)
        name_col = code_col = None
        for col in df.columns:
            if "商品名称" in str(col):
                name_col = col
            if "商品编码" in str(col):
                code_col = col
        if not name_col:
            return jsonify({"success": False, "msg": "Excel中未找到「商品名称」列"})

        inserted = 0
        updated = 0
        skipped = 0
        failed = 0
        with get_db_connection() as conn:
            for _, row in df.iterrows():
                set_name = str(row[name_col]).strip()
                set_code = str(row[code_col]).strip() if code_col else ""
                if not set_name or set_name == "nan":
                    failed += 1
                    continue
                try:
                    exists = conn.execute("SELECT id FROM goods_set_lib WHERE set_name = ?", (set_name,)).fetchone()
                    if exists:
                        if overwrite:
                            conn.execute("UPDATE goods_set_lib SET set_code = ? WHERE id = ?", (set_code, exists['id']))
                            updated += 1
                        else:
                            skipped += 1
                    else:
                        conn.execute("INSERT INTO goods_set_lib (set_name, set_code) VALUES (?, ?)", (set_name, set_code))
                        inserted += 1
                except Exception:
                    failed += 1
            conn.commit()
            cache = current_app.extensions.get('cache')
            if cache:
                cache.clear()
        log_action("导入套装档案", f"覆盖模式: {overwrite}, 新增: {inserted}, 更新: {updated}, 跳过: {skipped}, 失败: {failed}")
        return jsonify({
            "success": True,
            "msg": f"导入完成：新增 {inserted} 条，更新 {updated} 条，跳过 {skipped} 条，失败 {failed} 条",
            "inserted": inserted,
            "updated": updated,
            "skipped": skipped,
            "failed": failed
        })
    except Exception as e:
        logging.exception("套装导入失败")
        return jsonify({"success": False, "msg": f"导入失败：{str(e)}"})

@sets_bp.route('/api/goods-set-add', methods=['POST'])
@login_required
@write_required
def api_goods_set_add():
    set_name = request.form.get('set_name', '').strip()
    set_code = request.form.get('set_code', '').strip()
    extras = request.form.get('extras', '{}').strip()   # ← 恢复这一行

    if not set_name:
        return jsonify({"success": False, "msg": "套装名称不能为空"})
    
    # 验证 extras JSON
    try:
        json.loads(extras)
    except:
        extras = '{}'
    
    # 收集动态列值
    extra_cols = get_extra_columns()
    extra_values = {}
    for col in extra_cols:
        extra_values[col] = request.form.get(col, '').strip()
    
    try:
        with get_db_connection() as conn:
            exists = conn.execute("SELECT 1 FROM goods_set_lib WHERE set_name = ?", (set_name,)).fetchone()
            if exists:
                return jsonify({"success": False, "msg": "该套装已存在"})
            
            columns = ['set_name', 'set_code'] + list(extra_values.keys()) + ['extras']
            placeholders = ', '.join(['?'] * len(columns))
            values = [set_name, set_code] + list(extra_values.values()) + [extras]
            conn.execute(f"INSERT INTO goods_set_lib ({', '.join(columns)}) VALUES ({placeholders})", values)
            conn.commit()
            
            cache = current_app.extensions.get('cache')
            if cache: cache.clear()
        log_action("新增套装", f"名称: {set_name}")
        return jsonify({"success": True, "msg": "套装添加成功"})
    except Exception as e:
        logging.exception("新增套装失败")
        return jsonify({"success": False, "msg": str(e)})
@sets_bp.route('/api/goods-set-delete', methods=['POST'])
@login_required
@write_required
def api_goods_set_delete():
    data = request.get_json()
    set_id = data.get('id')
    if not set_id:
        return jsonify({"success": False, "msg": "缺少套装ID"})
    with get_db_connection() as conn:
        conn.execute("DELETE FROM goods_set_lib WHERE id = ?", (set_id,))
        conn.commit()
        cache = current_app.extensions.get('cache')
        if cache:
            cache.clear()
    log_action("删除套装", f"套装ID: {set_id}")
    return jsonify({"success": True, "msg": "删除成功"})

@sets_bp.route('/api/goods-set-del-batch', methods=['POST'])
@login_required
@write_required
def api_goods_set_del_batch():
    data = request.get_json()
    ids = data.get('ids', [])
    if not ids:
        return jsonify({"success": False, "msg": "请选择套装"})
    with get_db_connection() as conn:
        for sid in ids:
            conn.execute("DELETE FROM goods_set_lib WHERE id = ?", (sid,))
        conn.commit()
        cache = current_app.extensions.get('cache')
        if cache:
            cache.clear()
    log_action("批量删除套装", f"套装ID: {ids}")
    return jsonify({"success": True, "msg": f"成功删除 {len(ids)} 个套装"})

@sets_bp.route('/api/set-match')
def set_match():
    kw = request.args.get('kw', '').strip()
    if not kw:
        return jsonify([])
    with get_db_connection() as conn:
        res = conn.execute("SELECT set_name FROM goods_set_lib WHERE set_name LIKE ? LIMIT 10", (f'%{kw}%',)).fetchall()
    return jsonify([{"name": r["set_name"]} for r in res])

# ===================== 异步导入功能 =====================
set_task_states = {}  # 如果已有 goods 的 set_task_states，这里需改名避免冲突：set_set_task_states

@sets_bp.route('/api/goods-set-import-async', methods=['POST'])
@login_required
@write_required
def api_goods_set_import_async():
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

    task_id = str(uuid.uuid4())
    file_content = file.read()
    set_task_states[task_id] = {'state': 'PENDING', 'result': None, 'progress': 0}

    app = current_app._get_current_object()
    executor = current_app.executor

    future = executor.submit(
        _do_set_import,
        task_id, file_content, file.filename, overwrite, app, set_task_states  # 传入 set_task_states
    )

    def callback(f):
        try:
            set_task_states[task_id]['state'] = 'SUCCESS'
            set_task_states[task_id]['result'] = f.result()
        except Exception as e:
            set_task_states[task_id]['state'] = 'FAILURE'
            set_task_states[task_id]['result'] = str(e)

    future.add_done_callback(callback)

    return jsonify({"success": True, "task_id": task_id})

@sets_bp.route('/api/goods-set-import-status/<task_id>')
@login_required
def api_goods_set_import_status(task_id):
    state_data = set_task_states.get(task_id, {'state': 'NOT_FOUND', 'progress': 0})
    return jsonify(state_data)

def _do_set_import(task_id, file_content, filename, overwrite, app, set_task_states):
    from io import BytesIO
    with app.app_context():
        try:
            df = pd.read_excel(BytesIO(file_content), dtype=str)
            total_rows = len(df)
            set_task_states[task_id] = {'state': 'RUNNING', 'progress': 0}

            name_col = code_col = None
            for col in df.columns:
                if "商品名称" in str(col):
                    name_col = col
                if "商品编码" in str(col):
                    code_col = col
            if not name_col:
                return {'success': False, 'msg': 'Excel中未找到「商品名称」列'}

            inserted = 0
            updated = 0
            skipped = 0
            failed = 0
            with get_db_connection() as conn:
                for idx, row in df.iterrows():
                    set_name = str(row[name_col]).strip()
                    set_code = str(row[code_col]).strip() if code_col else ""
                    if not set_name or set_name == "nan":
                        failed += 1
                    else:
                        try:
                            exists = conn.execute("SELECT id FROM goods_set_lib WHERE set_name = ?", (set_name,)).fetchone()
                            if exists:
                                if overwrite:
                                    conn.execute("UPDATE goods_set_lib SET set_code = ? WHERE id = ?", (set_code, exists['id']))
                                    updated += 1
                                else:
                                    skipped += 1
                            else:
                                conn.execute("INSERT INTO goods_set_lib (set_name, set_code) VALUES (?, ?)", (set_name, set_code))
                                inserted += 1
                        except Exception:
                            failed += 1

                    progress = int((idx + 1) / total_rows * 99)
                    set_task_states[task_id]['progress'] = progress

                conn.commit()
                cache_instance = app.extensions.get('cache')
                if cache_instance:
                    cache_instance.clear()

            set_task_states[task_id]['progress'] = 100
            log_action("导入套装档案（异步）", f"新增: {inserted}, 更新: {updated}, 跳过: {skipped}, 失败: {failed}")
            return {
                'success': True,
                'msg': f'导入完成：新增 {inserted} 条，更新 {updated} 条，跳过 {skipped} 条，失败 {failed} 条',
                'inserted': inserted, 'updated': updated, 'skipped': skipped, 'failed': failed
            }
        except Exception as e:
            logging.exception("异步导入套装失败")
            set_task_states[task_id] = {'state': 'FAILURE', 'progress': 0, 'result': str(e)}
            return {'success': False, 'msg': f'导入失败：{str(e)}'}
        
@sets_bp.route('/api/goods-set-import-preview', methods=['POST'])
@login_required
def api_goods_set_import_preview():
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
        df = pd.read_excel(file, dtype=str)
        name_col = code_col = None
        for col in df.columns:
            if "商品名称" in str(col):
                name_col = col
            if "商品编码" in str(col):
                code_col = col
        if not name_col:
            return jsonify({"success": False, "msg": "Excel中未找到「商品名称」列"})

        preview_df = df.head(5)
        columns = preview_df.columns.tolist()
        rows = preview_df.values.tolist()

        statuses = []
        with get_db_connection() as conn:
            for _, row in preview_df.iterrows():
                set_name = str(row[name_col]).strip()
                if set_name and set_name != "nan":
                    exists = conn.execute("SELECT 1 FROM goods_set_lib WHERE set_name = ?", (set_name,)).fetchone()
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
        logging.exception("预览套装 Excel 失败")
        return jsonify({"success": False, "msg": f"预览失败：{str(e)}"})

# ===================== 动态列管理 =====================
import re
from utils import admin_required

def get_extra_columns():
    """获取 goods_set_lib 表中除基础列外的额外列名"""
    with get_db_connection() as conn:
        existing = [row[1] for row in conn.execute("PRAGMA table_info(goods_set_lib)")]
    base_cols = {'id', 'set_name', 'set_code', 'extras', 'created_at'}
    return [col for col in existing if col not in base_cols]

@sets_bp.route('/api/set-columns', methods=['GET', 'POST', 'DELETE'])
@login_required
@admin_required
def manage_set_columns():
    """管理员管理套装档案的自定义列"""
    if request.method == 'GET':
        return jsonify({'columns': get_extra_columns()})
    
    elif request.method == 'POST':
        col_name = request.form.get('name', '').strip()
        if not col_name:
            return jsonify({'success': False, 'msg': '列名不能为空'})
        # 只允许字母、数字、下划线，且不以数字开头
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', col_name):
            return jsonify({'success': False, 'msg': '列名不合法，只能包含字母数字下划线，且不能以数字开头'})
        with get_db_connection() as conn:
            existing = [row[1] for row in conn.execute("PRAGMA table_info(goods_set_lib)")]
            if col_name in existing:
                return jsonify({'success': False, 'msg': '列已存在'})
            try:
                conn.execute(f"ALTER TABLE goods_set_lib ADD COLUMN {col_name} TEXT DEFAULT ''")
                conn.commit()
                log_action("添加套装自定义列", f"列名: {col_name}")
                return jsonify({'success': True, 'msg': f'列 {col_name} 已添加'})
            except Exception as e:
                logging.exception("添加列失败")
                return jsonify({'success': False, 'msg': f'添加失败：{str(e)}'})
    
    elif request.method == 'DELETE':
        col_name = request.form.get('name', '').strip()
        if not col_name:
            return jsonify({'success': False, 'msg': '列名不能为空'})
        base_cols = {'id', 'set_name', 'set_code', 'extras', 'created_at'}
        if col_name in base_cols:
            return jsonify({'success': False, 'msg': '不能删除基础列'})
        with get_db_connection() as conn:
            existing = [row[1] for row in conn.execute("PRAGMA table_info(goods_set_lib)")]
            if col_name not in existing:
                return jsonify({'success': False, 'msg': '列不存在'})
            # SQLite 不支持直接 DROP COLUMN，这里仅清空该列数据
            conn.execute(f"UPDATE goods_set_lib SET {col_name} = ''")
            conn.commit()
            log_action("清空套装自定义列", f"列名: {col_name}")
            return jsonify({'success': True, 'msg': f'列 {col_name} 已清空（列仍存在，前端可隐藏）'})

@sets_bp.route('/api/goods-set-update/<int:set_id>', methods=['PUT'])
@login_required
@write_required
def api_goods_set_update(set_id):
    # 基础字段
    set_name = request.form.get('set_name', '').strip()
    set_code = request.form.get('set_code', '').strip()
    extras = request.form.get('extras', '{}').strip()

    if not set_name:
        return jsonify({"success": False, "msg": "套装名称不能为空"})

    # 验证 extras JSON
    if extras:
        try:
            json.loads(extras)
        except (json.JSONDecodeError, ValueError):
            extras = '{}'
    else:
        extras = '{}'

    # 收集动态列的值
    extra_cols = get_extra_columns()
    extra_values = {}
    for col in extra_cols:
        extra_values[col] = request.form.get(col, '').strip()

    # 打印接收到的参数，便于调试（生产环境可删除）
    logging.info(f"更新套装 ID={set_id}, 接收参数: {dict(request.form)}")
    logging.info(f"动态列: {extra_values}")

    try:
        with get_db_connection() as conn:
            # 检查名称冲突
            conflict = conn.execute(
                "SELECT id FROM goods_set_lib WHERE set_name = ? AND id != ?",
                (set_name, set_id)
            ).fetchone()
            if conflict:
                return jsonify({"success": False, "msg": "该套装名称已存在"})

            # 动态构建 UPDATE 语句
            set_parts = ['set_name = ?', 'set_code = ?', 'extras = ?']
            values = [set_name, set_code, extras]
            for col in extra_cols:
                set_parts.append(f"{col} = ?")
                values.append(extra_values[col])
            values.append(set_id)

            sql = f"UPDATE goods_set_lib SET {', '.join(set_parts)} WHERE id = ?"
            conn.execute(sql, values)
            changes = conn.execute("SELECT changes()").fetchone()[0]
            if changes == 0:
                # 回滚，并返回错误信息
                conn.rollback()
                return jsonify({"success": False, "msg": "更新失败，可能记录不存在或列名错误"})
            else:
                conn.commit()
            # 清除缓存
            cache = current_app.extensions.get('cache')
            if cache:
                cache.clear()

        log_action("更新套装", f"ID: {set_id}, 名称: {set_name}")
        return jsonify({"success": True, "msg": "套装更新成功"})
    except Exception as e:
        logging.exception("更新套装失败")
        return jsonify({"success": False, "msg": str(e)})
    

@sets_bp.route('/api/goods-set-lib/export')
@login_required
def export_goods_set_lib():
    keyword = request.args.get('keyword', '').strip()
    with get_db_connection() as conn:
        extra_cols = get_extra_columns()        # 获取所有自定义列
        cols = ['id', 'set_name', 'set_code'] + extra_cols + ['extras']
        where = ""
        params = []
        if keyword:
            where = " WHERE set_name LIKE ?"
            params.append(f'%{keyword}%')
        sql = f"SELECT {', '.join(cols)} FROM goods_set_lib {where} ORDER BY id ASC"
        data = conn.execute(sql, params).fetchall()
    df = pd.DataFrame([dict(row) for row in data])
    filename = f"套装档案_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return make_excel_response(df, filename)