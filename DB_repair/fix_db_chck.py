import sqlite3
import re

DB_PATH = "scan_data.db"
# 科学计数法正则
SCI_PATTERN = re.compile(r'^[+-]?\d+\.?\d*[eE][+-]?\d+$')

# 待检查的表和字段
CHECK_LIST = [
    ("query_results", ["extend_code", "order_code"]),
    ("goods_detail", ["order_code", "extend_code"]),
    ("set_detail", ["order_code", "extend_code"]),
    ("order_codes", ["order_code"])
]

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()

total_bad = 0
bad_detail = []

print("===== 科学计数坏数据统计 =====")

for table, cols in CHECK_LIST:
    for col in cols:
        cur.execute(f"SELECT id, {col} FROM {table}")
        all_rows = cur.fetchall()
        bad_rows = []
        
        for row_id, val in all_rows:
            if val is None:
                continue
            val_str = str(val).strip()
            # 匹配科学计数格式
            if SCI_PATTERN.match(val_str):
                bad_rows.append((row_id, val_str))
        
        cnt = len(bad_rows)
        total_bad += cnt
        if cnt > 0:
            bad_detail.append(f"【{table}】字段 {col}：共 {cnt} 条异常")
            print(f"\n{table}.{col} 异常数据样例(前10条)：")
            for idx, (rid, v) in enumerate(bad_rows[:10]):
                print(f"id:{rid}  原值:{v}")

print("\n=====================================")
if total_bad == 0:
    print("✅ 未检测到科学计数格式数据，无需修复")
else:
    print(f"❌ 总计异常数据：{total_bad} 条")
    for item in bad_detail:
        print(item)

conn.close()