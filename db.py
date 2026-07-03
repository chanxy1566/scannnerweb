# db.py
import sqlite3
import logging
from flask_bcrypt import Bcrypt
from flask_caching import Cache

# 全局扩展实例（在 app.py 中通过 init_app 初始化）
bcrypt = Bcrypt()
cache = Cache()

DB_PATH = 'scan_data.db'

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn

def init_db():
    with get_db_connection() as conn:
        # 核心业务表
        conn.execute('''
            CREATE TABLE IF NOT EXISTS query_results (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_code TEXT,
                extend_code TEXT,
                original_goods TEXT,
                original_quantity REAL,
                source_table TEXT,
                order_time TEXT,
                extend_col1 TEXT DEFAULT '',
                extend_col2 TEXT DEFAULT '',
                extend_col1_name TEXT DEFAULT '',
                extend_col2_name TEXT DEFAULT ''
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS goods_detail (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_code TEXT,
                split_goods TEXT,
                extend_code TEXT,
                original_quantity REAL,
                final_quantity REAL,
                cleaned_goods TEXT,
                source_table TEXT,
                original_goods TEXT DEFAULT '',
                multiplier REAL DEFAULT 1,
                order_time TEXT DEFAULT ''
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS set_detail (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_code TEXT,
                extend_code TEXT,
                set_name TEXT,
                set_quantity REAL,
                source_table TEXT,
                order_time TEXT
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS goods_lib (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                goods_name TEXT NOT NULL UNIQUE,
                extend_code TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # 套装档案表
        conn.execute('''
            CREATE TABLE IF NOT EXISTS goods_set_lib (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                set_name TEXT NOT NULL UNIQUE,
                set_code TEXT DEFAULT '',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # 操作日志表
        conn.execute('''
            CREATE TABLE IF NOT EXISTS operation_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                action TEXT NOT NULL,
                details TEXT,
                username TEXT DEFAULT '',
                ip_address TEXT DEFAULT ''
            )
        ''')
        # 登录尝试表
        conn.execute('''
            CREATE TABLE IF NOT EXISTS login_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                identifier TEXT NOT NULL,
                attempt_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # 用户表
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL,
                role TEXT DEFAULT 'viewer',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        # scan_records
        conn.execute('''
            CREATE TABLE IF NOT EXISTS scan_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                code TEXT NOT NULL,
                scan_time DATETIME NOT NULL,
                log_file TEXT
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS order_codes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_code TEXT UNIQUE NOT NULL,
                source_file TEXT,
                import_date DATE,
                order_time DATE
            )
        ''')
        conn.execute("CREATE INDEX IF NOT EXISTS idx_scan_code ON scan_records(code)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_scan_time ON scan_records(scan_time)")

        # ========== 补列逻辑（兼容旧表） ==========
        # goods_detail 补列
        existing_gd = {row[1] for row in conn.execute("PRAGMA table_info(goods_detail)")}
        for col, col_def in {
            'original_goods': 'TEXT DEFAULT ""',
            'multiplier': 'REAL DEFAULT 1',
            'order_time': 'TEXT DEFAULT ""'
        }.items():
            if col not in existing_gd:
                conn.execute(f"ALTER TABLE goods_detail ADD COLUMN {col} {col_def}")

        # query_results 补列
        existing_qr = {row[1] for row in conn.execute("PRAGMA table_info(query_results)")}
        for col, col_def in {
            'extend_col1': 'TEXT DEFAULT ""',
            'extend_col1_name': 'TEXT DEFAULT ""',
            'extend_col2_name': 'TEXT DEFAULT ""'
        }.items():
            if col not in existing_qr:
                conn.execute(f"ALTER TABLE query_results ADD COLUMN {col} {col_def}")

        # set_detail 补列
        existing_sd = {row[1] for row in conn.execute("PRAGMA table_info(set_detail)")}
        for col, col_def in {
            'extend_code': 'TEXT',
            'source_table': 'TEXT'
        }.items():
            if col not in existing_sd:
                conn.execute(f"ALTER TABLE set_detail ADD COLUMN {col} {col_def}")

        # operation_log 补列
        existing_log = {row[1] for row in conn.execute("PRAGMA table_info(operation_log)")}
        for col, col_def in {'username': 'TEXT DEFAULT ""', 'ip_address': 'TEXT DEFAULT ""'}.items():
            if col not in existing_log:
                conn.execute(f"ALTER TABLE operation_log ADD COLUMN {col} {col_def}")

        # users 补列
        existing_users = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
        if 'role' not in existing_users:
            conn.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'viewer'")

        # goods_set_lib 补列（extras 用于 JSON 扩展）
        existing_set = {row[1] for row in conn.execute("PRAGMA table_info(goods_set_lib)")}
        if 'extras' not in existing_set:
            conn.execute("ALTER TABLE goods_set_lib ADD COLUMN extras TEXT DEFAULT '{}'")

        # 创建默认管理员
        admin = conn.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
        if not admin:
            hashed_pw = bcrypt.generate_password_hash('admin123').decode('utf-8')
            conn.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)",
                         ('admin', hashed_pw, 'admin'))

        # 索引
        conn.execute('CREATE INDEX IF NOT EXISTS idx_qr_order_time ON query_results(order_time)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_qr_order_code ON query_results(order_code)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_gd_order_code ON goods_detail(order_code)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_gd_cleaned_goods ON goods_detail(cleaned_goods)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_sd_set_name ON set_detail(set_name)')
        conn.execute('CREATE INDEX IF NOT EXISTS idx_attempts_id_time ON login_attempts(identifier, attempt_time)')