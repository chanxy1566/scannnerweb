import io
import json
from datetime import datetime, timedelta
from db import get_db_connection
import os
import shutil
import pandas as pd
# 辅助函数：手动登录
def login(client, username='admin', password='admin123'):
    resp = client.post('/login', data={
        'username': username,
        'password': password
    }, follow_redirects=True)
    assert resp.status_code == 200

# ===================== 页面访问 =====================
def test_scanner_page(client):
    login(client)
    resp = client.get('/scanner')
    assert resp.status_code == 200
    assert '扫码管理' in resp.text

# ===================== 统计 =====================
def test_scanner_stats(client):
    login(client)
    # 初始统计应为0
    resp = client.get('/api/scanner/stats')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['today'] == 0
    assert data['month'] == 0
    assert data['total'] == 0

# ===================== 扫码录入 =====================
def test_scanner_scan_success(client):
    login(client)
    resp = client.post('/api/scanner/scan', data={'code': 'TEST001'})
    assert resp.status_code == 200
    assert resp.json['success'] == True
    assert 'TEST001' in resp.json['msg']
    # 验证数据库
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM scan_records WHERE code='TEST001'").fetchone()
        assert row is not None

def test_scanner_scan_duplicate(client):
    login(client)
    client.post('/api/scanner/scan', data={'code': 'TEST001'})
    resp = client.post('/api/scanner/scan', data={'code': 'TEST001'})
    assert resp.status_code == 200
    assert resp.json['success'] == False
    assert '重复' in resp.json['msg']

def test_scanner_scan_short_code(client):
    login(client)
    resp = client.post('/api/scanner/scan', data={'code': 'ABC'})  # 少于6位
    assert resp.status_code == 200
    assert resp.json['success'] == False
    assert '无效单号' in resp.json['msg']

# ===================== 删除 =====================
def test_scanner_delete(client):
    login(client)
    # 先添加一条
    client.post('/api/scanner/scan', data={'code': 'DEL001'})
    # 删除
    resp = client.delete('/api/scanner/delete/DEL001')
    assert resp.status_code == 200
    assert resp.json['success'] == True
    # 确认已删除
    with get_db_connection() as conn:
        row = conn.execute("SELECT * FROM scan_records WHERE code='DEL001' AND scan_time >= date('now')").fetchone()
        assert row is None

# ===================== 今日记录分页 =====================
def test_scanner_today_page(client):
    login(client)
    # 添加两条记录
    client.post('/api/scanner/scan', data={'code': 'PAGE001'})
    client.post('/api/scanner/scan', data={'code': 'PAGE002'})
    resp = client.get('/api/scanner/today-page?page=1&per_page=10')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['total'] >= 2
    assert len(data['data']) == 2

# ===================== 历史查询 =====================
def test_scanner_query(client):
    login(client)
    # 插入一条指定日期的记录（需要使用datetime.now()，但测试中不好控制，直接查询已存在的）
    client.post('/api/scanner/scan', data={'code': 'QUERY001'})
    resp = client.get('/api/scanner/query?code=QUERY001')
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) > 0
    assert data[0]['code'] == 'QUERY001'

# ===================== 批量导入 =====================
def test_scanner_import_codes_text(client):
    login(client)
    resp = client.post('/api/scanner/import-codes', data={'text': 'IMPORT001\nIMPORT002'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] == True
    assert data['inserted'] == 2

def test_scanner_import_codes_file(client):
    login(client)
    # 创建虚拟文件
    file_content = b"FILE001\nFILE002\n"
    data = {'file': (io.BytesIO(file_content), 'test.txt')}
    resp = client.post('/api/scanner/import-codes', data=data, content_type='multipart/form-data')
    assert resp.status_code == 200
    assert resp.json['success'] == True
    assert resp.json['inserted'] >= 1  # 可能因格式而有差异，但至少有一个

# ===================== 批量导出匹配订单（需有 query_results 数据） =====================
def test_scanner_batch_query(client):
    login(client)
    # 先插入扫码记录和 query_results 数据
    client.post('/api/scanner/scan', data={'code': 'ORDER123'})
    with get_db_connection() as conn:
        conn.execute("INSERT INTO query_results (order_code, original_goods) VALUES ('ORDER123', '测试商品')")
        conn.commit()
    resp = client.post('/api/scanner/batch-query', data={'date': datetime.now().strftime('%Y-%m-%d')})
    assert resp.status_code == 200
    assert resp.content_type == 'application/vnd.ms-excel'

# ===================== 刷新 Excel 缓存 =====================
def test_scanner_refresh_excel(client, tmp_path):
    login(client)
    # 创建临时 resources 目录
    resources_dir = tmp_path / "resources"
    resources_dir.mkdir()
    # 生成一个简单的 Excel 文件
    df = pd.DataFrame({'商品名称': ['测试商品'], '商品编码': ['001']})
    file_path = resources_dir / "3.xlsx"
    df.to_excel(file_path, index=False, engine='openpyxl')

    # 临时修改模块中的 EXCEL_FILE 变量指向临时文件
    from routes.scanner import EXCEL_FILE
    original_path = EXCEL_FILE
    import routes.scanner as scanner_module
    scanner_module.EXCEL_FILE = str(file_path)

# ===================== 同步日志（无日志目录） =====================
def test_scanner_sync_logs_no_dir(client):
    login(client)
    # 确保 scan_logs 目录不存在
    import shutil, os
    if os.path.exists('scan_logs'):
        shutil.rmtree('scan_logs')
    resp = client.post('/api/scanner/sync-logs')
    assert resp.status_code == 200
    assert resp.json['success'] == False
    assert '不存在' in resp.json['msg']

# ===================== 全月匹配导入（暂无数据） =====================
def test_scanner_monthly_import_empty(client):
    login(client)
    resp = client.post('/api/scanner/monthly-match-import')
    assert resp.status_code == 200
    assert resp.json['success'] == False
    assert '无扫描记录' in resp.json['msg']

# ===================== 权限验证 =====================
def test_scanner_viewer_cannot_scan(client):
    # 创建 viewer 并登录
    login(client)
    client.post('/api/users/add', data={'username':'v','password':'123456','role':'viewer'})
    client.get('/logout')
    # viewer 登录
    client.post('/login', data={'username':'v','password':'123456'}, follow_redirects=True)
    resp = client.post('/api/scanner/scan', data={'code': 'TESTV'})
    assert resp.status_code == 403   # write_required 拒绝  