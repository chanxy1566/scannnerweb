import pytest
from db import get_db_connection
from utils import is_locked_out, record_failed_attempt, reset_attempts
from datetime import datetime

# 公共登录函数
def login(client, username='admin', password='admin123'):
    resp = client.post('/login', data={
        'username': username,
        'password': password
    }, follow_redirects=True)
    assert resp.status_code == 200

# ===================== 登录测试 =====================
def test_login_success(client):
    resp = client.post('/login', data={
        'username': 'admin',
        'password': 'admin123'
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert '售后订单数据' in resp.text

def test_login_failure(client):
    resp = client.post('/login', data={
        'username': 'admin',
        'password': 'wrong'
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert '用户名或密码错误' in resp.text

# ===================== 锁定逻辑测试 =====================
def test_is_locked_out_logic(app):
    identifier = '127.0.0.1'
    with app.app_context():
        reset_attempts(identifier)
        assert not is_locked_out(identifier)

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with get_db_connection() as conn:
            for _ in range(5):
                conn.execute(
                    "INSERT INTO login_attempts (identifier, attempt_time) VALUES (?, ?)",
                    (identifier, now)
                )
            conn.commit()
        assert is_locked_out(identifier)

        reset_attempts(identifier)
        assert not is_locked_out(identifier)

# ===================== 权限测试 =====================
def test_admin_required(client):
    resp = client.get('/users', follow_redirects=True)
    assert resp.status_code == 200
    assert '请输入账号密码' in resp.text

def test_viewer_cannot_write(client):
    # 管理员登录
    login(client)
    # 清理可能残留的 viewer
    with get_db_connection() as conn:
        conn.execute("DELETE FROM users WHERE username='viewer'")
        conn.commit()
    # 创建 viewer
    resp = client.post('/api/users/add', data={
        'username': 'viewer',
        'password': '123456',
        'role': 'viewer'
    })
    assert resp.json['success'] == True

    # 使用独立客户端登录 viewer
    with client.application.app_context():
        viewer_client = client.application.test_client()
        resp = viewer_client.post('/login', data={'username':'viewer','password':'123456'}, follow_redirects=True)
        assert resp.status_code == 200
        resp = viewer_client.post('/api/update', json=[{'id': 1, 'final_quantity': 10}])
        assert resp.status_code == 403
        assert '需要编辑权限' in resp.json['msg']

# ===================== 用户管理测试 =====================
def test_users_api(client):
    login(client)
    resp = client.get('/api/users')
    assert resp.status_code == 200
    users = resp.get_json()
    assert any(u['username'] == 'admin' for u in users)

def test_add_user_password_too_short(client):
    login(client)
    resp = client.post('/api/users/add', data={
        'username': 'test2',
        'password': '123',
        'role': 'viewer'
    })
    assert resp.json['success'] == False

def test_set_password_missing_param(client):
    login(client)
    resp = client.post('/api/users/set-password', json={})
    assert resp.status_code == 200
    assert resp.json['success'] == False

def test_delete_user_missing_id(client):
    login(client)
    resp = client.post('/api/users/del', json={})
    assert resp.status_code == 200
    assert resp.json['success'] == False

def test_delete_own_user(client):
    login(client)
    with get_db_connection() as conn:
        uid = conn.execute("SELECT id FROM users WHERE username='admin'").fetchone()['id']
    resp = client.post('/api/users/del', json={'id': uid})
    assert resp.json['success'] == False

def test_add_existing_user(client):
    login(client)
    resp = client.post('/api/users/add', data={
        'username': 'admin',
        'password': '123456',
        'role': 'viewer'
    })
    assert resp.json['success'] == False

def test_user_reset_password_success(client):
    login(client)
    # 创建一个用户用于重置
    client.post('/api/users/add', data={'username':'resetuser','password':'123456','role':'viewer'})
    with get_db_connection() as conn:
        uid = conn.execute("SELECT id FROM users WHERE username='resetuser'").fetchone()['id']
    resp = client.post('/api/users/set-password', json={'id': uid, 'password': 'newpass123'})
    assert resp.json['success'] == True

def test_logout(client):
    login(client)
    resp = client.get('/logout', follow_redirects=True)
    assert resp.status_code == 200
    assert '请输入账号密码' in resp.text