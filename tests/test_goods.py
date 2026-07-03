import io
import pandas as pd
from db import get_db_connection

def login(client, username='admin', password='admin123'):
    """手动登录并验证成功"""
    resp = client.post('/login', data={
        'username': username,
        'password': password
    }, follow_redirects=True)
    assert resp.status_code == 200
    # 确认登录成功（页面包含关键词）
    assert '售后订单数据' in resp.text or '订单列表' in resp.text, f"登录失败: {resp.text[:200]}"

def test_add_goods(client):
    login(client)
    resp = client.post('/api/goods-add', data={
        'goods_name': '测试商品1',
        'extend_code': 'TC001'
    })
    assert resp.status_code == 200
    assert resp.json['success'] is True

    # 验证数据库
    with get_db_connection() as conn:
        goods = conn.execute("SELECT * FROM goods_lib WHERE goods_name='测试商品1'").fetchone()
        assert goods is not None

def test_add_duplicate_goods(client):
    login(client)
    client.post('/api/goods-add', data={'goods_name': '重复品', 'extend_code': '001'})
    resp = client.post('/api/goods-add', data={'goods_name': '重复品', 'extend_code': '002'})
    assert resp.status_code == 200
    assert resp.json['success'] is False

def test_delete_goods(client):
    login(client)
    client.post('/api/goods-add', data={'goods_name': '待删品', 'extend_code': 'D001'})
    with get_db_connection() as conn:
        row = conn.execute("SELECT id FROM goods_lib WHERE goods_name='待删品'").fetchone()
        assert row is not None, "商品添加失败"
        gid = row['id']
    resp = client.post('/api/goods-del', json={'id': gid})
    assert resp.status_code == 200
    assert resp.json['success'] is True

def test_batch_delete_goods(client):
    login(client)
    client.post('/api/goods-add', data={'goods_name': '批删1'})
    client.post('/api/goods-add', data={'goods_name': '批删2'})
    with get_db_connection() as conn:
        rows = conn.execute("SELECT id FROM goods_lib WHERE goods_name IN ('批删1','批删2')").fetchall()
        assert len(rows) == 2, f"添加失败，只有{len(rows)}条"
        ids = [row['id'] for row in rows]
    resp = client.post('/api/goods-del-batch', json={'ids': ids})
    assert resp.status_code == 200
    assert resp.json['success'] is True

def test_import_goods_excel(client):
    login(client)
    df = pd.DataFrame({'商品名称': ['导入商品1', '导入商品2'], '商品编码': ['IM01', 'IM02']})
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    output.seek(0)
    resp = client.post('/api/goods-import', data={'file': (output, 'test.xlsx')}, content_type='multipart/form-data')
    assert resp.status_code == 200
    assert resp.json['success'] is True
    assert resp.json['inserted'] == 2

def test_import_goods_overwrite(client):
    login(client)
    client.post('/api/goods-add', data={'goods_name': '覆盖品', 'extend_code': 'OLD'})
    df = pd.DataFrame({'商品名称': ['覆盖品'], '商品编码': ['NEW']})
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    output.seek(0)
    resp = client.post('/api/goods-import', data={'file': (output, 'over.xlsx'), 'overwrite': 'true'}, content_type='multipart/form-data')
    assert resp.status_code == 200
    assert resp.json['success'] is True
    assert resp.json['updated'] == 1

def test_goods_match(client):
    login(client)
    client.post('/api/goods-add', data={'goods_name': '苹果', 'extend_code': 'AP'})
    resp = client.get('/api/goods-match?kw=苹果')
    assert resp.status_code == 200
    data = resp.get_json()
    assert any(item['name'] == '苹果' for item in data)

# 边界测试
def test_add_goods_missing_name(client):
    login(client)
    resp = client.post('/api/goods-add', data={'extend_code': 'X'})
    assert resp.status_code == 200
    assert resp.json['success'] is False

def test_batch_delete_goods_empty(client):
    login(client)
    resp = client.post('/api/goods-del-batch', json={'ids': []})
    assert resp.status_code == 200
    assert resp.json['success'] is False

def test_import_invalid_file(client):
    login(client)
    resp = client.post('/api/goods-import', data={'file': (io.BytesIO(b"fake"), 'test.txt')}, content_type='multipart/form-data')
    assert resp.status_code == 200
    assert resp.json['success'] is False

def test_import_preview_missing_name(client):
    login(client)
    df = pd.DataFrame({'编码': ['001']})
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    output.seek(0)
    resp = client.post('/api/goods-import-preview', data={'file': (output, 'test.xlsx')}, content_type='multipart/form-data')
    assert resp.status_code == 200
    assert resp.json['success'] is False
#导入Excel异常处理（文件读取失败）、删除商品不存在、商品汇总页面带关键字筛选、导出商品汇总等。
def test_goods_summary_with_keyword(client):
    login(client)
    resp = client.get('/goods-summary?keyword=测试')
    assert resp.status_code == 200

def test_delete_nonexistent_goods(client):
    login(client)
    resp = client.post('/api/goods-del', json={'id': 9999})
    assert resp.status_code == 200
    assert resp.json['success'] == True  # SQL成功但无实际行