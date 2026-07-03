# tests/test_z_dashboard.py  （重命名后，确保最后执行）
def login(client):
    resp = client.post('/login', data={
        'username': 'admin',
        'password': 'admin123'
    }, follow_redirects=True)
    assert resp.status_code == 200
    assert '售后订单数据' in resp.text

def test_summary(client):
    login(client)
    resp = client.get('/api/dashboard/summary')
    assert resp.status_code == 200
    data = resp.get_json()
    assert 'total_orders' in data

def test_source_distribution(client):
    login(client)
    resp = client.get('/api/dashboard/source-distribution')
    assert resp.status_code == 200

def test_top_goods(client):
    login(client)
    resp = client.get('/api/dashboard/top-goods')
    assert resp.status_code == 200

def test_health(client):
    login(client)
    resp = client.get('/health')
    assert resp.status_code == 200
    assert resp.get_json()['status'] == 'running'

def test_export_goods_distribution(client):
    login(client)
    resp = client.get('/api/dashboard/export/goods-distribution')
    assert resp.status_code == 200
    assert 'text/csv' in resp.content_type

def test_monthly_orders(client):
    login(client)
    resp = client.get('/api/dashboard/monthly-orders')
    assert resp.status_code == 200

def test_goods_distribution(client):
    login(client)
    resp = client.get('/api/dashboard/goods-distribution')
    assert resp.status_code == 200

def test_order_trend(client):
    login(client)
    resp = client.get('/api/order-trend')
    assert resp.status_code == 200

def test_source_tables(client):
    login(client)
    resp = client.get('/api/source-tables')
    assert resp.status_code == 200

def test_stats(client):
    login(client)
    resp = client.get('/api/stats')
    assert resp.status_code == 200

def test_export_chart_monthly(client):
    login(client)
    resp = client.get('/api/dashboard/export/monthly')
    assert resp.status_code == 200
    assert 'text/csv' in resp.content_type

def test_export_chart_source(client):
    login(client)
    resp = client.get('/api/dashboard/export/source')
    assert resp.status_code == 200

def test_export_chart_top_goods(client):
    login(client)
    resp = client.get('/api/dashboard/export/top-goods')
    assert resp.status_code == 200

def test_export_chart_top_sets(client):
    login(client)
    resp = client.get('/api/dashboard/export/top-sets')
    assert resp.status_code == 200

def test_export_invalid_chart_type(client):
    login(client)
    resp = client.get('/api/dashboard/export/invalid')
    assert resp.status_code == 400

def test_trend_with_source(client):
    login(client)
    resp = client.get('/api/order-trend?source=阿里旺旺')
    assert resp.status_code == 200
#增加带日期和来源的组合筛选测试，导出所有图表类型。
def test_summary_with_date_range(client):
    login(client)
    resp = client.get('/api/dashboard/summary?start_date=2023-01-01&end_date=2023-12-31')
    assert resp.status_code == 200

def test_export_chart_top_goods(client):
    login(client)
    resp = client.get('/api/dashboard/export/top-goods')
    assert resp.status_code == 200