import json
from db import get_db_connection

def login(client, username='admin', password='admin123'):
    resp = client.post('/login', data={'username':username, 'password':password}, follow_redirects=True)
    assert resp.status_code == 200

def test_order_detail_api(client):
    login(client)
    with get_db_connection() as conn:
        conn.execute("INSERT INTO query_results (id, order_code) VALUES (20, 'API001')")
        conn.execute("INSERT INTO goods_detail (id, order_code, split_goods, final_quantity) VALUES (20, 'API001', '测试商品API', 5)")
        conn.commit()
    resp = client.get('/api/detail/API001')
    assert resp.status_code == 200
    data = resp.get_json()
    assert len(data) == 1
    assert data[0]['split_goods'] == '测试商品API'

def test_update_quantity(client):
    login(client)
    with get_db_connection() as conn:
        conn.execute("INSERT INTO query_results (id, order_code) VALUES (30, 'UP001')")
        conn.execute("INSERT INTO goods_detail (id, order_code, split_goods, final_quantity) VALUES (30, 'UP001', '商品U', 10)")
        conn.commit()
    resp = client.post('/api/update', json=[{'id': 30, 'final_quantity': 25}])
    assert resp.status_code == 200
    assert resp.json['ok'] == True
    with get_db_connection() as conn:
        row = conn.execute("SELECT final_quantity FROM goods_detail WHERE id=30").fetchone()
        assert row['final_quantity'] == 25

def test_delete_order(client):
    login(client)
    with get_db_connection() as conn:
        conn.execute("INSERT INTO query_results (id, order_code) VALUES (40, 'DEL1')")
        conn.execute("INSERT INTO goods_detail (id, order_code) VALUES (40, 'DEL1')")
        conn.commit()
    resp = client.post('/api/deleteOrder', json={'id': 40, 'order_code': 'DEL1'})
    assert resp.status_code == 200
    assert resp.json['success'] == True

def test_export_order(client):
    login(client)
    resp = client.get('/export_order')
    assert resp.status_code == 200
    assert resp.content_type == 'application/vnd.ms-excel'

def test_update_quantity_invalid(client):
    login(client)
    resp = client.post('/api/update', json=[{'id': 1, 'final_quantity': -5}])
    assert resp.status_code == 400

def test_update_multiplier(client):
    login(client)
    with get_db_connection() as conn:
        conn.execute("INSERT INTO query_results (id, order_code) VALUES (100, 'MULT001')")
        conn.execute("INSERT INTO goods_detail (id, order_code, split_goods, final_quantity) VALUES (100, 'MULT001', '倍数商品', 10)")
        conn.commit()
    resp = client.post('/api/updateMultiplier', json={'multiplier': 2, 'ids': [100]})
    assert resp.status_code == 200
    assert resp.json['success'] == True

def test_batch_delete_orders(client):
    login(client)
    with get_db_connection() as conn:
        conn.execute("INSERT INTO query_results (id, order_code) VALUES (200, 'BATCH1')")
        conn.execute("INSERT INTO query_results (id, order_code) VALUES (201, 'BATCH2')")
        conn.commit()
    resp = client.post('/api/deleteOrdersBatch', json={'ids': [200, 201]})
    assert resp.status_code == 200
    assert resp.json['success'] == True

def test_index_page(client):
    login(client)
    resp = client.get('/')
    assert resp.status_code == 200
    assert '售后订单数据' in resp.text

def test_index_invalid_per_page(client):
    login(client)
    resp = client.get('/?per_page=999')
    assert resp.status_code == 200

def test_index_invalid_sort(client):
    login(client)
    resp = client.get('/?sort=invalid_col')
    assert resp.status_code == 200

def test_export_order_bad_date(client):
    login(client)
    resp = client.get('/export_order?start_date=bad-date')
    assert resp.status_code in (200, 400)

def test_add_g_success(client):
    login(client)
    resp = client.post('/add-g', data={
        'order_code': 'TESTADD',
        'g[]': '商品X',
        'ec[]': 'codeX',
        'q[]': '5',
        'orig[]': '原始',
        'mult[]': '1',
        'time[]': '2024-01-01'
    })
    assert resp.status_code == 200
    assert resp.text == 'OK'

def test_add_goods_missing_data(client):
    login(client)
    resp = client.post('/add-g', data={'order_code': 'TEST', 'g[]': '商品'})
    assert resp.status_code == 200  # 已修复不应500
#添加商品时数量无效、批量操作空列表、无效的倍数等边界情况（已部分覆盖），还可测试 api_delete_detail 缺少ID、api_update 传入空列表等。
def test_delete_detail_missing_id(client):
    login(client)
    resp = client.post('/api/deleteDetail', json={})
    assert resp.status_code == 200
    assert resp.json['success'] == False

def test_update_quantity_empty(client):
    login(client)
    resp = client.post('/api/update', json=[])
    assert resp.status_code in (200, 400)