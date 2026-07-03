@echo off
echo 开始自动同步数据库
python E:\scanner_results\WEB+Query6.13_search_delate\DB_repair\fix_db_chck.py
echo 开始自动修复脏数据
python E:\scanner_results\WEB+Query6.13_search_delate\DB_repair\fix_db.py
echo 同步修复完成
pause