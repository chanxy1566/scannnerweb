# tests/test_backup.py
import os
import tempfile
import pytest
import logging
from db import get_db_connection
from backup import backup_database, clean_old_logs, clean_login_attempts
from config import Config
import backup as backup_module
import shutil

TEST_DB = 'test_scan_data.db'

def test_clean_old_logs(app):
    with app.app_context():
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO operation_log (timestamp, action, details) VALUES ('2000-01-01', 'old', 'test')"
            )
            conn.commit()
        clean_old_logs()
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT * FROM operation_log WHERE timestamp='2000-01-01'"
            ).fetchone()
            assert row is None

def test_clean_login_attempts(app):
    with app.app_context():
        with get_db_connection() as conn:
            conn.execute(
                "INSERT INTO login_attempts (identifier, attempt_time) VALUES ('test_user', '2000-01-01 00:00:00')"
            )
            conn.commit()
        clean_login_attempts()
        with get_db_connection() as conn:
            row = conn.execute(
                "SELECT * FROM login_attempts WHERE identifier='test_user'"
            ).fetchone()
            assert row is None

def test_backup_creates_file(app, caplog):
    """测试数据库备份，使用临时目录并检查日志"""
    original_db_path = backup_module.DB_PATH
    original_backup_dir = backup_module.BACKUP_DIR
    original_config_backup = Config.BACKUP_DIR

    test_db_abs = os.path.abspath(TEST_DB)
    if not os.path.exists(test_db_abs):
        import sqlite3
        conn = sqlite3.connect(test_db_abs)
        conn.close()

    backup_module.DB_PATH = test_db_abs
    tmp_dir = tempfile.mkdtemp()
    backup_module.BACKUP_DIR = tmp_dir
    Config.BACKUP_DIR = tmp_dir

    try:
        with app.app_context():
            with caplog.at_level(logging.INFO):
                backup_database()
            assert "数据库备份失败" not in caplog.text
            files = os.listdir(tmp_dir)
            assert any(f.endswith('.db') for f in files), f"备份目录为空: {files}, 日志: {caplog.text}"
    finally:
        backup_module.DB_PATH = original_db_path
        backup_module.BACKUP_DIR = original_backup_dir
        Config.BACKUP_DIR = original_config_backup
        shutil.rmtree(tmp_dir, ignore_errors=True)