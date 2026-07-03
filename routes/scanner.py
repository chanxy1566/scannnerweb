# routes/scanner.py
from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
from db import get_db_connection
from utils import write_required, make_excel_response
from utils import write_required, make_excel_response, admin_required
import re
from datetime import datetime, timedelta
import pandas as pd
from io import BytesIO
import json
import os
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

scanner_bp = Blueprint('scanner', __name__)

MIN_ORDER_CODE_LENGTH = 6

def normalize_code(code):
    code = code.strip().upper()
    if code.endswith('.0'):
        code = code[:-2]
    return code

# ===================== 扫码页面 =====================
@scanner_bp.route('/scanner')
@login_required
def scanner_page():
    return render_template('scanner.html')

# ===================== 统计 =====================
@scanner_bp.route('/api/scanner/stats')
@login_required
def scanner_stats():
    today = datetime.now().strftime('%Y-%m-%d')
    month_start = datetime.now().strftime('%Y-%m') + '-01'
    with get_db_connection() as conn:
        today_count = conn.execute(
            "SELECT COUNT(DISTINCT code) FROM scan_records WHERE date(scan_time)=?", (today,)
        ).fetchone()[0]
        month_count = conn.execute(
            "SELECT COUNT(DISTINCT code) FROM scan_records WHERE date(scan_time)>=?", (month_start,)
        ).fetchone()[0]
        all_count = conn.execute("SELECT COUNT(DISTINCT code) FROM scan_records").fetchone()[0]
    return jsonify({'today': today_count, 'month': month_count, 'total': all_count})

# ===================== 扫码录入 =====================
@scanner_bp.route('/api/scanner/scan', methods=['POST'])
@login_required
@write_required
def scanner_scan():
    code = request.form.get('code', '').strip()
    code = normalize_code(process_order_code(code))   # 先去除 -1-1-
    if len(code) < MIN_ORDER_CODE_LENGTH:
        return jsonify({'success': False, 'msg': '无效单号'})

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with get_db_connection() as conn:
        exists = conn.execute(
            "SELECT id FROM scan_records WHERE code=?", (code,)
        ).fetchone()
        if exists:
            return jsonify({'success': False, 'msg': '重复扫码', 'repeat': True})
        conn.execute(
            "INSERT INTO scan_records (code, scan_time, log_file) VALUES (?,?,?)",
            (code, now, 'web')
        )
        conn.commit()
    return jsonify({'success': True, 'msg': f'扫码成功：{code}', 'code': code})

# ===================== 删除今日扫码 =====================
@scanner_bp.route('/api/scanner/delete/<code>', methods=['DELETE'])
@login_required
@write_required
def scanner_delete(code):
    code = normalize_code(code)
    today_start = datetime.now().strftime('%Y-%m-%d 00:00:00')
    with get_db_connection() as conn:
        conn.execute(
            "DELETE FROM scan_records WHERE code=? AND scan_time >= ?",
            (code, today_start)
        )
        conn.commit()
    return jsonify({'success': True, 'msg': f'已删除 {code}'})

# ===================== 今日扫码列表 =====================
@scanner_bp.route('/api/scanner/today')
@login_required
def scanner_today():
    today_start = datetime.now().strftime('%Y-%m-%d 00:00:00')
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT code, scan_time FROM scan_records WHERE scan_time >= ? ORDER BY scan_time DESC",
            (today_start,)
        ).fetchall()
    data = [{'code': row['code'], 'time': row['scan_time']} for row in rows]
    return jsonify(data)

# ===================== 历史查询 =====================
@scanner_bp.route('/api/scanner/query')
@login_required
def scanner_query():
    code = request.args.get('code', '').strip()
    date = request.args.get('date', '').strip()
    where = "WHERE 1=1"
    params = []
    if code:
        where += " AND code LIKE ?"
        params.append(f'%{normalize_code(code)}%')
    if date:
        where += " AND date(scan_time) = ?"
        params.append(date)
    with get_db_connection() as conn:
        rows = conn.execute(
            f"SELECT code, scan_time, log_file FROM scan_records {where} ORDER BY scan_time DESC LIMIT 100",
            params
        ).fetchall()
    data = [{'code': row['code'], 'time': row['scan_time'], 'source': row['log_file'] or 'web'} for row in rows]
    return jsonify(data)

# ===================== 匹配订单详情 =====================
@scanner_bp.route('/api/scanner/match/<code>')
@login_required
def scanner_match(code):
    code = normalize_code(code)
    with get_db_connection() as conn:
        orders = conn.execute(
            "SELECT * FROM query_results WHERE order_code LIKE ?",
            (f'%{code}%',)
        ).fetchall()
        details = conn.execute(
            "SELECT * FROM goods_detail WHERE order_code LIKE ?",
            (f'%{code}%',)
        ).fetchall()
    return jsonify({
        'orders': [dict(row) for row in orders],
        'details': [dict(row) for row in details]
    })

# ===================== 批量查询 + 导出 =====================
@scanner_bp.route('/api/scanner/batch-query', methods=['POST'])
@login_required
def scanner_batch_query():
    date = request.form.get('date', '').strip()
    if not date:
        return jsonify({'success': False, 'msg': '请选择日期'})
    with get_db_connection() as conn:
        codes = conn.execute(
            "SELECT DISTINCT code FROM scan_records WHERE date(scan_time)=?",
            (date,)
        ).fetchall()
    if not codes:
        return jsonify({'success': False, 'msg': '该日期无扫码记录'})
    code_list = [row['code'] for row in codes]
    placeholders = ','.join(['?']*len(code_list))
    with get_db_connection() as conn:
        orders = conn.execute(
            f"SELECT * FROM query_results WHERE order_code IN ({placeholders})",
            code_list
        ).fetchall()
        details = conn.execute(
            f"SELECT * FROM goods_detail WHERE order_code IN ({placeholders})",
            code_list
        ).fetchall()
        sets = conn.execute(
            f"SELECT * FROM set_detail WHERE order_code IN ({placeholders})",
            code_list
        ).fetchall()

    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        if orders:
            pd.DataFrame([dict(r) for r in orders]).to_excel(writer, sheet_name='查询结果', index=False)
        if details:
            pd.DataFrame([dict(r) for r in details]).to_excel(writer, sheet_name='商品明细', index=False)
        if sets:
            pd.DataFrame([dict(r) for r in sets]).to_excel(writer, sheet_name='套装明细', index=False)
        # 如果所有工作表都为空，至少添加一个空工作表
        if not (orders or details or sets):
            pd.DataFrame().to_excel(writer, sheet_name='无匹配数据', index=False)
    output.seek(0)
    resp = current_app.make_response(output.read())
    resp.headers["Content-Type"] = "application/vnd.ms-excel"
    filename = f"{date}_订单匹配.xlsx"
    resp.headers["Content-Disposition"] = f"attachment; filename*=utf-8''{quote(filename)}"
    return resp

# ===================== 今日记录分页 =====================
@scanner_bp.route('/api/scanner/today-page')
@login_required
def scanner_today_page():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    offset = (page - 1) * per_page
    today_start = datetime.now().strftime('%Y-%m-%d 00:00:00')
    with get_db_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(DISTINCT code) FROM scan_records WHERE scan_time >= ?", (today_start,)
        ).fetchone()[0]
        rows = conn.execute(
            "SELECT code, scan_time FROM scan_records WHERE scan_time >= ? ORDER BY scan_time DESC LIMIT ? OFFSET ?",
            (today_start, per_page, offset)
        ).fetchall()
    data = [{'code': row['code'], 'time': row['scan_time']} for row in rows]
    total_pages = (count + per_page - 1) // per_page
    return jsonify({'data': data, 'page': page, 'total_pages': total_pages, 'total': count})

# ===================== 批量导入测试单号（文件或文本） =====================
@scanner_bp.route('/api/scanner/import-codes', methods=['POST'])
@login_required
@write_required
def scanner_import_codes():
    file = request.files.get('file')
    text = request.form.get('text', '').strip()
    codes_raw = []
    if file:
        content = file.read().decode('utf-8', errors='ignore')
        codes_raw = re.findall(r'[a-zA-Z0-9]+', content)  # 提取所有数字字母组合
    elif text:
        codes_raw = re.findall(r'[a-zA-Z0-9]+', text)
    else:
        return jsonify({'success': False, 'msg': '请上传文件或粘贴文本'})

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    new_codes = []
    skipped = 0
    with get_db_connection() as conn:
        for raw in codes_raw:
            code = normalize_code(process_order_code(raw))
            if len(code) < MIN_ORDER_CODE_LENGTH:
                continue
            exists = conn.execute("SELECT id FROM scan_records WHERE code=?", (code,)).fetchone()
            if exists:
                skipped += 1
                continue
            if code not in new_codes:
                new_codes.append(code)
        for code in new_codes:
            conn.execute(
                "INSERT INTO scan_records (code, scan_time, log_file) VALUES (?,?,?)",
                (code, now, 'web_batch')
            )
        conn.commit()
    return jsonify({
        'success': True,
        'msg': f'导入完成：新增 {len(new_codes)} 个，跳过 {skipped} 个重复',
        'inserted': len(new_codes),
        'skipped': skipped
    })

# ===================== 每日扫码趋势（用于图表） =====================
@scanner_bp.route('/api/scanner/daily-trend')
@login_required
def scanner_daily_trend():
    days = request.args.get('days', 7, type=int)
    if days > 30:
        days = 30
    start = (datetime.now() - timedelta(days=days-1)).strftime('%Y-%m-%d')
    with get_db_connection() as conn:
        rows = conn.execute("""
            SELECT date(scan_time) as day, COUNT(DISTINCT code) as cnt
            FROM scan_records
            WHERE date(scan_time) >= ?
            GROUP BY day
            ORDER BY day
        """, (start,)).fetchall()
    return jsonify({
        'days': [row['day'] for row in rows],
        'counts': [row['cnt'] for row in rows]
    })

# ===================== Excel 缓存（全局） =====================
excel_rows = []              # 存储所有 Excel 行数据
excel_lock = threading.Lock()  # 保护缓存的读写
excel_ready = False
last_excel_mtime = 0
EXCEL_FILE = os.path.join("resources", "3.xlsx")

# 标准化商品名称（与客户端逻辑一致）
SCENT_NAME_MAP = {
    "北国": "北国雪松", "假日": "假日海风", "秘境": "秘境森林",
    "清风": "清风白茶", "清樱": "清樱未央"
}
CX06_PREFIX_LIST = ["CX-06PRO", "CX06-PRO", "CX-06", "CXT-06", "CX06"]

def standardize_product_name(name):
    # 复制原客户端的 standardize_product_name 函数逻辑（完整版）
    if pd.isna(name) or not name:
        return ""
    temp = str(name).strip()
    original = temp
    is_cx = False
    prefix = None
    for p in CX06_PREFIX_LIST:
        if p.upper() in original.upper():
            prefix = p
            is_cx = True
            break
    items = re.split(r"[\/\+，,]", temp)
    final = []
    for item in items:
        item = item.strip()
        if not item:
            continue
        if "礼袋" in item:
            final.append(item)
            continue
        for k, v in SCENT_NAME_MAP.items():
            if k in item and v not in item:
                item = item.replace(k, v)
        if is_cx and prefix:
            has_p = any(pp.upper() in item.upper() for pp in CX06_PREFIX_LIST)
            if not has_p:
                if item.startswith("("):
                    item = f"{prefix}{item}"
                else:
                    item = f"{prefix}-{item}"
        final.append(item)
    temp = "，".join(final)
    res = temp.upper()
    # 简化的标准名称映射（可根据需要扩展）
    if "CX-02PRO" in res or "CX-02水枪PRO" in res: return "CX-02PRO"
    if any(k in res for k in ["10M水管", "10M单水管", "水管10米", "10M"]): return "CXS-10M"
    if any(k in res for k in ["15M水管", "15M单水管", "水管15米", "15M"]): return "CXS-15M"
    if any(k in res for k in ["20M水管", "20M单水管", "水管20米", "20M"]): return "CXS-20M"
    if any(k in res for k in ["30M水管", "30M单水管", "水管30米", "30M"]): return "CXS-30M"
    if any(k in res for k in ["40M水管", "40M单水管", "水管40米", "40M"]): return "CXS-40M"
    if any(k in res for k in ["7.5M水管", "7.5M单水管", "水管7.5米", "7.5M"]): return "CXS-7.5M"
    if "万能接口" in res or "万接" in res: return "CXS-万能接口"
    if "MJ" in res or "毛巾" in res: return "CX-MJ"
    if "LC-15" in res: return "LC-15"
    if "DB-50" in res or "DB50" in res: return "DB-50"
    if "太阳能板" in res: return "太阳能充电板"
    if "三代水枪" in res: return "SQ-01伸缩水枪"
    elif "二代水枪" in res: return "CX-02PRO"
    elif "一代水枪" in res: return "CXS-水枪"
    if "四代火山机器" in res: return "CX-06PRO火山版"
    elif "四代雪山机器" in res: return "CX-06PRO雪山版"
    return temp

# 从原始客户端移植的 Excel 加载逻辑（简化，去除与界面相关的部分）
COLUMN_MAP = {
    "天猫": (7, 9), "抖店": (7, 9), "视频号": (7, 10),
    "京东旗舰": (7, 10), "汽车店": (7, 10), "快手": (7, 10),
    "拼多多": (7, 10), "换货件": (9, 11), "京东自营": (5, 10),
    "无理件": (5, None), "中通丢件登记": (10, None),
    "仓库错发漏发双面单登记": (10, None), "申通（云仓）丢件登记": (10, None),
    "顺丰丢件登记": (10, None), "客服补偿登记": (None, None)
}
A_COL_MAP = {
    "天猫":1, "抖店":1, "视频号":1, "京东旗舰":1, "汽车店":1, "快手":1,
    "拼多多":1, "换货件":3, "京东自营":1, "无理件":6, "维修件":3, "电商总部":1,
    "中通丢件登记":1, "仓库错发漏发双面单登记":1, "申通（云仓）丢件登记":1,
    "顺丰丢件登记":1, "客服补偿登记":1
}

def load_excel_data():
    """加载 Excel 到全局缓存，线程安全"""
    global excel_rows, excel_ready, last_excel_mtime
    if not os.path.exists(EXCEL_FILE):
        logging.error(f"Excel 文件不存在：{EXCEL_FILE}")
        return False

    try:
        excel = pd.ExcelFile(EXCEL_FILE, engine="openpyxl")
    except:
        try:
            excel = pd.ExcelFile(EXCEL_FILE, engine="xlrd")
        except Exception as e:
            logging.error(f"无法读取 Excel: {e}")
            return False

    new_rows = []
    for sheet in excel.sheet_names:
        try:
            df = pd.read_excel(EXCEL_FILE, sheet_name=sheet, header=None, dtype=str).fillna("")
        except Exception as e:
            logging.warning(f"读取工作表 {sheet} 失败: {e}")
            continue

        # 科学记数法修复
        def clean_cell(x):
            s = str(x).strip()
            if 'e' in s.lower():
                try:
                    num = float(s)
                    if num == int(num):
                        return str(int(num))
                except:
                    pass
            if s.endswith('.0') and s[:-2].isdigit():
                return s[:-2]
            return s
        df = df.apply(lambda col: col.map(clean_cell))

        col_a, col_b = None, None
        for key, val in COLUMN_MAP.items():
            if key in sheet:
                col_a, col_b = val
                break
        a_col_idx = None
        for key, val in A_COL_MAP.items():
            if key in sheet:
                a_col_idx = val
                break

        for _, row in df.iterrows():
            row_list = row.astype(str).tolist()
            raw_text = "".join(row_list).strip()
            # 跳过表头行
            if any(kw in raw_text for kw in ["退货物流单号", "商品编码", "数量"]):
                continue

            goods, qty = "", ""
            if any(key in sheet for key in ["中通丢件登记", "仓库错发漏发双面单登记", "申通（云仓）丢件登记", "顺丰丢件登记"]):
                goods = row_list[3] if len(row_list) > 3 else ""
                qty = row_list[4] if len(row_list) > 4 else ""
            elif "客服补偿登记" in sheet:
                goods = row_list[4] if len(row_list) > 4 else ""
                qty = "1"
            elif "换货件" in sheet:
                goods = row_list[4] if len(row_list) > 4 else ""
                qty = row_list[5] if len(row_list) > 5 else ""
            elif "京东自营" in sheet:
                goods = row_list[3] if len(row_list) > 3 else ""
                qty = row_list[4] if len(row_list) > 4 else ""
            elif "无理件" in sheet:
                goods = row_list[1] if len(row_list) > 1 else ""
                qty = row_list[2] if len(row_list) > 2 else ""
            elif "维修件" in sheet:
                goods = row_list[4] if len(row_list) > 4 else ""
                qty = row_list[5] if len(row_list) > 5 else ""
            else:
                goods = row_list[2] if len(row_list) > 2 else ""
                qty = row_list[3] if len(row_list) > 3 else ""

            c1 = row_list[col_a] if (col_a is not None and col_a < len(row_list)) else ""
            c2 = row_list[col_b] if (col_b is not None and col_b < len(row_list)) else ""
            a_val = row_list[a_col_idx] if (a_col_idx is not None and a_col_idx < len(row_list)) else ""

            new_rows.append({
                "sheet": sheet, "a_val": a_val, "goods": goods, "qty": qty,
                "c1": c1, "c2": c2, "raw_text": raw_text
            })

    with excel_lock:
        excel_rows = new_rows
        excel_ready = True
        last_excel_mtime = os.path.getmtime(EXCEL_FILE)
    logging.info(f"Excel 缓存已更新，共 {len(new_rows)} 行")
    return True

def do_real_query(target_codes):
    """根据单号列表匹配 Excel 缓存，返回 (df_query, df_goods, df_set)"""
    if not excel_ready:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    with excel_lock:
        rows = excel_rows[:]

    selected_rows = []
    for code in target_codes:
        code_upper = code.strip().upper()
        for row_data in rows:
            if code_upper in row_data["raw_text"]:
                selected_rows.append([
                    row_data["a_val"], code, row_data["goods"], row_data["qty"],
                    row_data["sheet"], row_data["c1"], row_data["c2"], "", ""
                ])

    if not selected_rows:
        return pd.DataFrame(), pd.DataFrame(), pd.DataFrame()

    df_raw = pd.DataFrame(selected_rows, columns=["扩展编码","匹配单号","原始商品","原始数量","来源表",
                                                   "扩展列1","扩展列2","扩展列1名称","扩展列2名称"])
    df_raw = df_raw.drop_duplicates(subset=["匹配单号", "扩展编码"])

    # 无理件处理（简化）
    df_normal = df_raw[~df_raw["来源表"].str.contains("无理件", na=False)].copy()
    df_wuli = df_raw[df_raw["来源表"].str.contains("无理件", na=False)].copy()
    normal_codes = set(df_normal["匹配单号"].unique())
    df_wuli_final = df_wuli[~df_wuli["匹配单号"].isin(normal_codes)].copy()
    df_final = pd.concat([df_normal, df_wuli_final], ignore_index=True)

    detail_rows = []
    set_rows = []
    for _, r in df_final.iterrows():
        code = r["匹配单号"]
        goods = str(r["原始商品"]).strip()
        qty_str = str(r["原始数量"]).strip()
        source = r["来源表"]
        extend = r["扩展编码"]
        try:
            qty = float(qty_str)
        except:
            qty = 1.0
        set_rows.append({"匹配单号":code,"扩展编码":extend,"套装名称":goods,"套装数量":qty,"来源表":source})
        if "货不对板" in goods:
            continue
        parts = re.split(r'[\/\+]', goods)
        for part in parts:
            part = part.strip()
            mul = 1.0
            mul_match = re.search(r'\*(\d+\.?\d*)', part)
            if mul_match:
                mul = float(mul_match.group(1))
            final = round(qty * mul, 2)
            clean_part = re.sub(r'\*.*', '', part).strip()
            detail_rows.append({"匹配单号":code,"扩展编码":extend,"原始商品":goods,"拆分商品":clean_part,
                                "原始数量":qty,"倍率":mul,"最终数量":final,"来源表":source})
    df_detail = pd.DataFrame(detail_rows)
    df_set = pd.DataFrame(set_rows)
    if not df_detail.empty:
        df_detail["清洗后商品"] = df_detail["拆分商品"].apply(standardize_product_name)
    return df_final, df_detail, df_set

def import_query_results(df_query, df_goods, df_set):
    """将匹配结果导入数据库，返回 (qry_cnt, gds_cnt, set_cnt)"""
    if df_query.empty and df_goods.empty and df_set.empty:
        return 0, 0, 0

    with get_db_connection() as conn:
        cur = conn.cursor()

# 1. 建立订单时间映射：优先 order_codes，其次 scan_records 最早扫码时间
        all_order_codes = set()
        for df in [df_query, df_goods, df_set]:
            if not df.empty and "匹配单号" in df.columns:
                all_order_codes.update(df["匹配单号"].astype(str).str.strip())

        order_time_map = {}
        if all_order_codes:
            placeholders = ','.join(['?'] * len(all_order_codes))
            # 从 order_codes 获取
            cur.execute(
                f"SELECT order_code, order_time FROM order_codes WHERE order_code IN ({placeholders})",
                tuple(all_order_codes)
            )
            for oc, ot in cur.fetchall():
                if ot:  # 只有非空才覆盖
                    order_time_map[oc] = ot

            # 对于未获取到时间的单号，从 scan_records 取最早扫码时间
            missing_codes = all_order_codes - set(order_time_map.keys())
            if missing_codes:
                missing_placeholders = ','.join(['?'] * len(missing_codes))
                cur.execute(
                    f"SELECT code, MIN(scan_time) as first_time FROM scan_records WHERE code IN ({missing_placeholders}) GROUP BY code",
                    tuple(missing_codes)
                )
                for code, first_time in cur.fetchall():
                    if first_time:
                        order_time_map[code] = first_time  # 使用扫码时间

        # 2. 导入 query_results
        qry_rows = []
        for _, row in df_query.iterrows():
            order_code = str(row.get("匹配单号", "")).strip()
            qry_rows.append((
                str(row.get("扩展编码", "")),
                order_code,
                str(row.get("原始商品", "")),
                str(row.get("原始数量", "")),
                str(row.get("来源表", "")),
                str(row.get("扩展列1", "")),
                str(row.get("扩展列2", "")),
                str(row.get("扩展列1名称", "")),  # 对应 extend_col1_name
                str(row.get("扩展列2名称", "")),  # 对应 extend_col2_name
                order_time_map.get(order_code, None)  # order_time
            ))

        if qry_rows:
            cur.executemany('''INSERT OR IGNORE INTO query_results 
                (extend_code, order_code, original_goods, original_quantity, source_table,
                 extend_col1, extend_col2, extend_col1_name, extend_col2_name, order_time)
                VALUES (?,?,?,?,?,?,?,?,?,?)''', qry_rows)
            qry_cnt = cur.rowcount
        else:
            qry_cnt = 0

        # 3. 导入 goods_detail
        gds_rows = []
        for _, row in df_goods.iterrows():
            order_code = str(row.get("匹配单号", "")).strip()
            gds_rows.append((
                order_code,
                str(row.get("扩展编码", "")),
                str(row.get("原始商品", "")),
                str(row.get("拆分商品", "")),
                float(row.get("原始数量", 1)),
                float(row.get("倍率", 1)),
                float(row.get("最终数量", 0)),
                str(row.get("来源表", "")),
                str(row.get("清洗后商品", "")),
                order_time_map.get(order_code, None)  # order_time
            ))

        if gds_rows:
            cur.executemany('''INSERT OR IGNORE INTO goods_detail 
                (order_code, extend_code, original_goods, split_goods, original_quantity,
                 multiplier, final_quantity, source_table, cleaned_goods, order_time)
                VALUES (?,?,?,?,?,?,?,?,?,?)''', gds_rows)
            gds_cnt = cur.rowcount
        else:
            gds_cnt = 0

        # 4. 导入 set_detail
        set_rows = []
        for _, row in df_set.iterrows():
            order_code = str(row.get("匹配单号", "")).strip()
            set_rows.append((
                order_code,
                str(row.get("扩展编码", "")),
                str(row.get("套装名称", "")),
                float(row.get("套装数量", 0)),
                str(row.get("来源表", "")),
                order_time_map.get(order_code, None)  # order_time
            ))

        if set_rows:
            cur.executemany('''INSERT OR IGNORE INTO set_detail 
                (order_code, extend_code, set_name, set_quantity, source_table, order_time)
                VALUES (?,?,?,?,?,?)''', set_rows)
            set_cnt = cur.rowcount
        else:
            set_cnt = 0

        conn.commit()
    return qry_cnt, gds_cnt, set_cnt

# ===================== 异步任务辅助 =====================
executor = ThreadPoolExecutor(max_workers=2)

# ===================== 刷新 Excel 缓存 =====================
@scanner_bp.route('/api/scanner/refresh-excel', methods=['POST'])
@login_required
@write_required
def refresh_excel_cache():   # ✅ 正确的刷新函数
    success = load_excel_data()
    if success:
        return jsonify({'success': True, 'msg': 'Excel 缓存已刷新'})
    else:
        return jsonify({'success': False, 'msg': 'Excel 缓存刷新失败'})


@scanner_bp.route('/api/scanner/batch_match', methods=['POST'])
@login_required
@write_required
def batch_match():
    date = request.form.get('date', '').strip()
    if not date:
        return jsonify({'success': False, 'msg': '请选择日期'})

    with get_db_connection() as conn:
        codes = [row['code'] for row in conn.execute(
            "SELECT DISTINCT code FROM scan_records WHERE date(scan_time)=?", (date,)
        ).fetchall()]
    if not codes:
        return jsonify({'success': False, 'msg': '该日期无扫描记录'})

    # 直接在线程外检查匹配结果？但 do_real_query 依赖 Excel 缓存，可以在这里调用一次（如果缓存已加载）
    # 为了保持异步，还是在线程中执行，但让 generate_excel 处理无数据的情况。
    def generate_excel():
        df_q, df_g, df_s = do_real_query(codes)
        if df_q.empty and df_g.empty and df_s.empty:
            return None  # 无匹配数据
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            if not df_q.empty:
                df_q.to_excel(writer, sheet_name='查询结果', index=False)
            if not df_g.empty:
                df_g.to_excel(writer, sheet_name='商品明细', index=False)
            if not df_s.empty:
                df_s.to_excel(writer, sheet_name='套装明细', index=False)
        output.seek(0)
        return output

    future = executor.submit(generate_excel)
    try:
        output = future.result(timeout=60)
    except Exception as e:
        logging.exception("批量匹配生成失败")
        return jsonify({'success': False, 'msg': f'生成失败：{str(e)}'})

    if output is None:
        return jsonify({'success': False, 'msg': '未匹配到任何订单数据'})

    resp = current_app.make_response(output.read())
    resp.headers["Content-Type"] = "application/vnd.ms-excel"
    filename = f"{date}_订单匹配.xlsx"
    resp.headers["Content-Disposition"] = f"attachment; filename*=utf-8''{quote(filename)}"
    return resp

# ===================== 一键全月匹配导入 =====================
@scanner_bp.route('/api/scanner/monthly-match-import', methods=['POST'])
@login_required
@write_required
def monthly_match_import():
    month_start = datetime.now().strftime('%Y-%m') + '-01'
    with get_db_connection() as conn:
        codes = [row['code'] for row in conn.execute(
            "SELECT DISTINCT code FROM scan_records WHERE date(scan_time)>=?", (month_start,)
        ).fetchall()]
    if not codes:
        return jsonify({'success': False, 'msg': '当月无扫描记录'})

    def _import():
        df_q, df_g, df_s = do_real_query(codes)
        return import_query_results(df_q, df_g, df_s)

    future = executor.submit(_import)
    try:
        qry, gds, sts = future.result(timeout=120)
    except Exception as e:
        logging.exception("全月导入失败")
        return jsonify({'success': False, 'msg': f'导入异常：{str(e)}'})

    return jsonify({
        'success': True,
        'msg': f'导入完成：查询结果 {qry} 条，商品明细 {gds} 条，套装明细 {sts} 条',
        'qry': qry, 'gds': gds, 'sts': sts
    })
# ===================== 从日志文件同步单号到数据库 =====================
@scanner_bp.route('/api/scanner/sync-logs', methods=['POST'])
@login_required
@write_required
def sync_logs():
    """遍历 scan_logs 目录下的所有日志文件，将有效单号写入 scan_records"""
    log_folder = "scan_logs"
    if not os.path.exists(log_folder):
        return jsonify({'success': False, 'msg': '日志目录不存在'})

    log_pattern = r'\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*([0-9a-zA-Z]+)\s*\|\s*今日已扫：\s*\d+'
    total = 0
    new_count = 0
    skipped = 0
    errors = 0

    with get_db_connection() as conn:
        for filename in os.listdir(log_folder):
            if not filename.startswith("scan_log_") or not filename.endswith(".txt"):
                continue
            filepath = os.path.join(log_folder, filename)
            try:
                with open(filepath, 'r', encoding='utf-8') as f:
                    for line in f:
                        m = re.match(log_pattern, line.strip())
                        if not m:
                            continue
                        raw_code = m.group(2).strip()
                        code = normalize_code(process_order_code(raw_code))
                        if len(code) < MIN_ORDER_CODE_LENGTH:
                            continue
                        scan_time = m.group(1)
                        total += 1
                        exists = conn.execute(
                            "SELECT id FROM scan_records WHERE code = ?", (code,)
                        ).fetchone()
                        if exists:
                            skipped += 1
                        else:
                            try:
                                conn.execute(
                                    "INSERT INTO scan_records (code, scan_time, log_file) VALUES (?, ?, ?)",
                                    (code, scan_time, filepath)
                                )
                                new_count += 1
                            except Exception:
                                errors += 1
            except Exception as e:
                logging.error(f"读取日志文件 {filename} 出错: {e}")
                errors += 1
        conn.commit()

    return jsonify({
        'success': True,
        'msg': f'同步完成：总单号 {total} 个，新增 {new_count} 个，跳过 {skipped} 个重复，错误 {errors} 个',
        'total': total,
        'new': new_count,
        'skipped': skipped,
        'errors': errors
    })
def process_order_code(code):
    return code.replace("-1-1-", "").strip()

@scanner_bp.route('/api/scanner/fix-order-time', methods=['POST'])
@login_required
@admin_required
def fix_order_time():
    """批量修复缺失的 order_time，用扫描时间填充"""
    with get_db_connection() as conn:
        cur = conn.cursor()
        tables = ['query_results', 'goods_detail', 'set_detail']
        total = 0
        for table in tables:
            cur.execute(f"""
                UPDATE {table}
                SET order_time = (
                    SELECT MIN(scan_time)
                    FROM scan_records
                    WHERE scan_records.code = {table}.order_code
                )
                WHERE order_time IS NULL OR order_time = ''
            """)
            total += cur.rowcount
        conn.commit()
    return jsonify({'success': True, 'msg': f'已修复 {total} 条记录'})
# ===================== 服务启动时自动加载 Excel（可选） =====================
# 在 create_app 中调用 load_excel_data()
# 注意：需要确保 Excel 文件存在，否则后台任务会报错。