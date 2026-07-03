import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', os.urandom(24))
    DB_PATH = os.environ.get('DB_PATH', 'scan_data.db')
    BACKUP_DIR = 'backups'
    CACHE_TYPE = 'SimpleCache'
    CACHE_DEFAULT_TIMEOUT = 300
    WTF_CSRF_ENABLED = True
    SWAGGER = {
        'title': '售后订单管理系统 API',
        'version': '1.0.0',
        'description': '售后订单管理系统的后端接口文档',
        'uiversion': 3
    }