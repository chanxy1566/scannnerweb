# backup.py
import os
import shutil
import logging
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from db import get_db_connection      # 数据库连接
from config import Config             # 配置文件，获取 DB_PATH, BACKUP_DIR 等

DB_PATH = Config.DB_PATH
BACKUP_DIR = Config.BACKUP_DIR

# 创建备份目录
if not os.path.exists(BACKUP_DIR):
    os.makedirs(BACKUP_DIR)

def backup_database():
    """备份数据库到 BACKUP_DIR，文件名带时间戳"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(BACKUP_DIR, f"scan_data_{timestamp}.db")
    try:
        shutil.copy2(DB_PATH, backup_file)
        logging.info(f"数据库备份成功：{backup_file}")
    except Exception as e:
        logging.error(f"数据库备份失败：{e}")

def clean_old_logs():
    """删除 90 天前的操作日志"""
    cutoff = (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
    try:
        with get_db_connection() as conn:
            deleted = conn.execute(
                "DELETE FROM operation_log WHERE date(timestamp) < ?",
                (cutoff,)
            ).rowcount
            conn.commit()
            if deleted > 0:
                logging.info(f"清理操作日志：删除了 {deleted} 条 90 天前的记录")
    except Exception as e:
        logging.error(f"清理操作日志失败：{e}")

def clean_login_attempts():
    """定期清理过期的登录失败记录（超过 LOCKOUT_TIME 的）"""
    from utils import LOCKOUT_TIME        # 避免循环导入，在函数内导入
    cutoff = (datetime.now() - LOCKOUT_TIME).strftime('%Y-%m-%d %H:%M:%S')
    try:
        with get_db_connection() as conn:
            deleted = conn.execute(
                "DELETE FROM login_attempts WHERE attempt_time < ?",
                (cutoff,)
            ).rowcount
            conn.commit()
            if deleted > 0:
                logging.info(f"清理登录失败记录：删除了 {deleted} 条过期数据")
    except Exception as e:
        logging.error(f"清理登录失败记录失败：{e}")

def start_scheduler():
    """启动定时任务调度器"""
    scheduler = BackgroundScheduler()
    # 每天 20:00 备份数据库
    scheduler.add_job(backup_database, 'cron', hour=20, minute=0)
    # 每天 3:00 清理 90 天前的操作日志
    scheduler.add_job(clean_old_logs, 'cron', hour=3, minute=0)
    # 每 30 分钟清理过期的登录尝试记录
    scheduler.add_job(clean_login_attempts, 'interval', minutes=30)
    scheduler.start()
    logging.info("定时任务调度器已启动（备份、日志清理、登录尝试清理）")
    return scheduler