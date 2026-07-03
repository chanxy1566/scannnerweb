from db import get_db_connection

def login(client, username='admin', password='admin123'):
    resp = client.post('/login', data={
        'username': username,
        'password': password
    }, follow_redirects=True)
    assert resp.status_code == 200

def test_operation_log_page(client):
    login(client)
    resp = client.get('/operation-log')
    assert resp.status_code == 200
    assert '操作日志' in resp.text

def test_api_operation_log_empty(client):
    login(client)
    resp = client.get('/api/operation-log')
    assert resp.status_code == 200
    data = resp.get_json()
    # 登录会产生一条日志，所以至少1条
    assert data['total'] >= 1

def test_api_operation_log_with_data(client):
    login(client)
    # 插入两条额外日志
    with get_db_connection() as conn:
        conn.execute("INSERT INTO operation_log (action, details, username, ip_address) VALUES (?,?,?,?)",
                     ('测试操作', '详情1', 'admin', '127.0.0.1'))
        conn.execute("INSERT INTO operation_log (action, details, username, ip_address) VALUES (?,?,?,?)",
                     ('测试操作2', '详情2', 'admin', '127.0.0.2'))
        conn.commit()
    resp = client.get('/api/operation-log')
    assert resp.status_code == 200
    data = resp.get_json()
    assert data['total'] >= 3
    actions = [log['action'] for log in data['logs']]
    assert '测试操作' in actions

def test_export_operation_log(client):
    login(client)
    resp = client.get('/export_operation_log')
    assert resp.status_code == 200
    assert resp.content_type == 'application/vnd.ms-excel'

def test_operation_log_with_filters(client):
    login(client)
    resp = client.get('/api/operation-log?start_date=2020-01-01&end_date=2030-01-01&keyword=测试&username=admin')
    assert resp.status_code == 200
    assert resp.get_json()['total'] >= 0

def test_operation_log_role_filter(client):
    login(client)
    resp = client.get('/api/operation-log?role=admin')
    assert resp.status_code == 200

def test_export_logs_with_role(client):
    login(client)
    resp = client.get('/export_operation_log?role=admin')
    assert resp.status_code == 200