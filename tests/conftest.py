# tests/conftest.py
import os
import pytest
from app import create_app
from db import get_db_connection, init_db

TEST_DB = 'test_scan_data.db'

@pytest.fixture(scope='function')
def app():
    app = create_app()
    app.config.update({
        'TESTING': True,
        'DB_PATH': TEST_DB,
        'WTF_CSRF_ENABLED': False,
    })
    import db
    db.DB_PATH = TEST_DB
    with app.app_context():
        init_db()
    yield app
    try:
        os.remove(TEST_DB)
    except OSError:
        pass

@pytest.fixture(scope='function')
def client(app):
    return app.test_client()

@pytest.fixture(autouse=True)
def clean_tables(app):
    with app.app_context():
        with get_db_connection() as conn:
            conn.execute("DELETE FROM goods_detail")
            conn.execute("DELETE FROM set_detail")
            conn.execute("DELETE FROM query_results")
            conn.execute("DELETE FROM goods_lib")
            conn.execute("DELETE FROM goods_set_lib")
            conn.execute("DELETE FROM login_attempts")
            conn.execute("DELETE FROM operation_log")
            conn.execute("DELETE FROM scan_records")
            conn.execute("DELETE FROM order_codes")
            conn.commit()