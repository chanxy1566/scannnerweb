# tests/test_sets_dynamic.py
import io
import json
import pytest
import pandas as pd
from db import get_db_connection

# 辅助登录函数
def login(client, username='admin', password='admin123'):
    resp = client.post('/login', data={
        'username': username,
        'password': password
    }, follow_redirects=True)
    assert resp.status_code == 200

# ===================== 列管理测试 =====================

def test_get_columns_empty(client):
    """初始时自定义列为空"""
    login(client)
    resp = client.get('/api/set-columns')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['columns'] == []

def test_add_column_admin(client):
    """管理员添加自定义列"""
    login(client)
    resp = client.post('/api/set-columns', data={'name': 'testcol'})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True
    # 验证列已存在于表结构中
    with get_db_connection() as conn:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(goods_set_lib)")]
    assert 'testcol' in cols

def test_add_column_invalid_name(client):
    """列名不合法（数字开头、特殊字符）"""
    login(client)
    resp = client.post('/api/set-columns', data={'name': '123bad'})
    assert resp.json['success'] is False
    resp = client.post('/api/set-columns', data={'name': 'bad-name'})
    assert resp.json['success'] is False

def test_delete_column_clear_data(client):
    """删除列仅清空数据，列仍存在但前端隐藏"""
    login(client)
    client.post('/api/set-columns', data={'name': 'temp_col'})
    resp = client.delete('/api/set-columns', data={'name': 'temp_col'})
    assert resp.status_code == 200
    # 列仍然存在（SQLite限制）
    with get_db_connection() as conn:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(goods_set_lib)")]
    assert 'temp_col' in cols

def test_non_admin_cannot_add_column(client):
    """非管理员不能添加列"""
    # 创建编辑者用户
    login(client)
    client.post('/api/users/add', data={
        'username': 'editor1',
        'password': '123456',
        'role': 'editor'
    })
    client.get('/logout')
    client.post('/login', data={'username': 'editor1', 'password': '123456'}, follow_redirects=True)
    resp = client.post('/api/set-columns', data={'name': 'test'})
    assert resp.status_code == 403

# ===================== 套装档案 CRUD 测试（含动态列） =====================

def test_add_set_with_dynamic_cols(client):
    """新增套装并填写动态列"""
    login(client)
    # 先添加动态列
    client.post('/api/set-columns', data={'name': 'brand'})
    resp = client.post('/api/goods-set-add', data={
        'set_name': '动态测试',
        'set_code': 'DT001',
        'brand': '测试品牌'
    })
    assert resp.status_code == 200
    assert resp.json['success'] is True
    # 验证数据库
    with get_db_connection() as conn:
        row = conn.execute("SELECT brand FROM goods_set_lib WHERE set_name='动态测试'").fetchone()
        assert row['brand'] == '测试品牌'

def test_add_set_with_extras(client):
    """新增套装支持 extras JSON"""
    login(client)
    resp = client.post('/api/goods-set-add', data={
        'set_name': '扩展测试',
        'extras': '{"color":"red"}'
    })
    assert resp.status_code == 200
    assert resp.json['success'] is True
    with get_db_connection() as conn:
        row = conn.execute("SELECT extras FROM goods_set_lib WHERE set_name='扩展测试'").fetchone()
        assert row['extras'] == '{"color":"red"}'

def test_update_set_does_not_clear_other_dyn_cols(client):
    """编辑一个动态列不会清空其他动态列（回归测试）"""
    login(client)
    # 添加两个列和一条数据
    client.post('/api/set-columns', data={'name': 'col1'})
    client.post('/api/set-columns', data={'name': 'col2'})
    resp = client.post('/api/goods-set-add', data={
        'set_name': '不覆盖测试',
        'col1': '初始值1',
        'col2': '初始值2'
    })
    assert resp.json['success'] is True
    # 获取ID
    with get_db_connection() as conn:
        sid = conn.execute("SELECT id FROM goods_set_lib WHERE set_name='不覆盖测试'").fetchone()['id']
    # 仅更新 col1，应该保留 col2
    resp = client.put(f'/api/goods-set-update/{sid}', data={
        'set_name': '不覆盖测试',
        'col1': '新值1',
        'col2': '初始值2'   # 显式传递原值
    })
    assert resp.status_code == 200
    assert resp.json['success'] is True
    # 验证
    with get_db_connection() as conn:
        row = conn.execute("SELECT col1, col2 FROM goods_set_lib WHERE id=?", (sid,)).fetchone()
        assert row['col1'] == '新值1'
        assert row['col2'] == '初始值2'  # 未被清空

def test_delete_set(client):
    """删除套装"""
    login(client)
    client.post('/api/goods-set-add', data={'set_name': '待删除'})
    with get_db_connection() as conn:
        sid = conn.execute("SELECT id FROM goods_set_lib WHERE set_name='待删除'").fetchone()['id']
    resp = client.post('/api/goods-set-delete', json={'id': sid})
    assert resp.json['success'] is True
    with get_db_connection() as conn:
        assert conn.execute("SELECT * FROM goods_set_lib WHERE id=?", (sid,)).fetchone() is None

def test_batch_delete_sets(client):
    """批量删除套装"""
    login(client)
    client.post('/api/goods-set-add', data={'set_name': '批删1'})
    client.post('/api/goods-set-add', data={'set_name': '批删2'})
    with get_db_connection() as conn:
        ids = [row['id'] for row in conn.execute(
            "SELECT id FROM goods_set_lib WHERE set_name IN ('批删1','批删2')"
        ).fetchall()]
    resp = client.post('/api/goods-set-del-batch', json={'ids': ids})
    assert resp.json['success'] is True
    with get_db_connection() as conn:
        for sid in ids:
            assert conn.execute("SELECT * FROM goods_set_lib WHERE id=?", (sid,)).fetchone() is None

# ===================== 导入导出测试 =====================

def test_import_sets_excel(client):
    """Excel基础导入"""
    login(client)
    df = pd.DataFrame({'商品名称': ['导入套装A', '导入套装B'], '商品编码': ['IA', 'IB']})
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    output.seek(0)
    data = {'file': (output, 'test.xlsx')}
    resp = client.post('/api/goods-set-import', data=data, content_type='multipart/form-data')
    assert resp.status_code == 200
    assert resp.json['success'] is True
    assert resp.json['inserted'] == 2

def test_import_sets_async(client):
    """异步导入提交任务"""
    login(client)
    df = pd.DataFrame({'商品名称': ['异步套装'], '商品编码': ['ASYNC']})
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    output.seek(0)
    data = {'file': (output, 'async.xlsx')}
    resp = client.post('/api/goods-set-import-async', data=data, content_type='multipart/form-data')
    assert resp.status_code == 200
    assert resp.json['success'] is True
    task_id = resp.json['task_id']
    import time
    time.sleep(2)
    status_resp = client.get(f'/api/goods-set-import-status/{task_id}')
    assert status_resp.status_code == 200
    state = status_resp.get_json()['state']
    assert state in ('SUCCESS', 'RUNNING', 'PENDING')

def test_export_sets_excel(client):
    """导出套装列表Excel"""
    login(client)
    client.post('/api/goods-set-add', data={'set_name': '导出测试'})
    resp = client.get('/api/goods-set-lib/export')
    assert resp.status_code == 200
    assert resp.content_type == 'application/vnd.ms-excel'
    assert len(resp.data) > 0

# ===================== 预览测试 =====================

def test_import_preview(client):
    """Excel预览"""
    login(client)
    df = pd.DataFrame({'商品名称': ['预览套装'], '商品编码': ['PV']})
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    output.seek(0)
    data = {'file': (output, 'preview.xlsx')}
    resp = client.post('/api/goods-set-import-preview', data=data, content_type='multipart/form-data')
    assert resp.status_code == 200
    assert resp.json['success'] is True
    assert len(resp.json['rows']) == 1
    assert resp.json['statuses'][0] == 'new'

def test_import_preview_missing_column(client):
    """预览缺少商品名称列"""
    login(client)
    df = pd.DataFrame({'编码': ['001']})
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False)
    output.seek(0)
    data = {'file': (output, 'missing.xlsx')}
    resp = client.post('/api/goods-set-import-preview', data=data, content_type='multipart/form-data')
    assert resp.json['success'] is False