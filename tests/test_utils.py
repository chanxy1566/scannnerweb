# tests/test_utils.py
from utils import validate_excel_file, sanitize_data
from io import BytesIO

def test_validate_excel_file_valid():
    # 模拟一个有效的 xlsx 文件头（PK..）
    fake_xlsx = BytesIO(b"PK\x03\x04")
    fake_xlsx.filename = "test.xlsx"
    valid, msg = validate_excel_file(fake_xlsx)
    assert valid

def test_validate_excel_file_invalid():
    fake_txt = BytesIO(b"not an excel file")
    fake_txt.filename = "test.txt"
    valid, msg = validate_excel_file(fake_txt)
    assert not valid

def test_sanitize_data():
    data = {'password': 'secret', 'username': 'alice'}
    result = sanitize_data(data)
    assert result['password'] == '***'
    assert result['username'] == 'alice'