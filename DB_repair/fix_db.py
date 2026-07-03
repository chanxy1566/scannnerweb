import sqlite3
import re
from datetime import datetime

DB_PATH = "scan_data.db"
SCI_PATTERN = re.compile(r'^[+-]?\d+\.?\d*[eE][+-]?\d+$')

# 待修复的表和字段
FIX_LIST = [
    ("query_results", ["extend_code", "order_code"]),
    ("goods_detail", ["order_code", "extend_code"]),
    ("set_detail", ["order_code", "extend_code"]),
    ("order_codes", ["order_code"])
]

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
conn.execute("BEGIN TRANSACTION")  # 事务保护，出错可回滚

fix_log = []
total_fixed = 0
total_skip = 0

print("===== 开始修复科学计数数据 =====")

for table, cols in FIX_LIST:
    for col in cols:
        cur.execute(f"SELECT id, {col} FROM {table}")
        rows = cur.fetchall()
        
        for row_id, bad_val in rows:
            if bad_val is None:
                continue
            bad_str = str(bad_val).strip()
            
            # 不是科学计数 → 跳过
            if not SCI_PATTERN.match(bad_str):
                continue
            
            try:
                # 科学计数还原为完整数字字符串
                num = float(bad_str)
                # 纯整数单号，转整数再转字符串（去掉小数点）
                if num.is_integer():
                    new_val = str(int(num))
                else:
                    new_val = str(num)
                
                # 二次校验：修复后不能再是科学计数
                if SCI_PATTERN.match(new_val):
                    fix_log.append(f"[{table}] id:{row_id} 修复失败，仍为科学计数 | 原值:{bad_str}")
                    total_skip += 1
                    continue
                
                # 执行更新
                cur.execute(f"UPDATE {table} SET {col} = ? WHERE id = ?", (new_val, row_id))
                fix_log.append(f"[{table}] id:{row_id} 修复成功 | {bad_str} → {new_val}")
                total_fixed += 1
            
            except Exception as e:
                fix_log.append(f"[{table}] id:{row_id} 异常 | 原值:{bad_str} | 错误:{str(e)}")
                total_skip += 1

# 提交事务
conn.commit()
conn.close()

# 保存修复日志
log_name = f"数据库修复日志_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
with open(log_name, "w", encoding="utf-8") as f:
    f.write("\n".join(fix_log))

print("===== 修复完成 =====")
print(f"✅ 成功修复条数：{total_fixed}")
print(f"⚠️  跳过/失败条数：{total_skip}")
print(f"📄 详细日志已保存：{log_name}")
print("\n建议：重新运行【查询脚本】验证是否还有异常数据")