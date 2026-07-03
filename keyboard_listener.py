# keyboard_listener.py
import time
import threading
import logging
from pynput import keyboard
from db import get_db_connection
from datetime import datetime

MIN_ORDER_CODE_LENGTH = 6
MAX_CODE_LENGTH = 200
SCAN_INTERVAL = 0.1  # 150ms内无新键视为扫码结束

class KeyboardListener:
    def __init__(self):
        self.buffer = []
        self.last_time = time.time()
        self.listener = None
        self.running = False
        self._lock = threading.Lock()

    def _on_press(self, key):
        try:
            if key == keyboard.Key.enter:
                with self._lock:
                    code = ''.join(self.buffer).strip()
                    self.buffer = []
                if code:
                    self._process_code(code)
            elif hasattr(key, 'char') and key.char and key.char.isprintable():
                with self._lock:
                    if time.time() - self.last_time > SCAN_INTERVAL:
                        self.buffer = []
                    self.last_time = time.time()
                    if len(self.buffer) < MAX_CODE_LENGTH:
                        self.buffer.append(key.char)
        except Exception as e:
            logging.error(f"键盘监听异常: {e}")

    def _normalize_code(self, code):
        code = code.strip().upper()
        if code.endswith('.0'):
            code = code[:-2]
        return code

    def _process_code(self, raw_code):
        from routes.scanner import process_order_code   # 或者直接定义相同的函数
        code = self._normalize_code(process_order_code(raw_code))
        if len(code) < MIN_ORDER_CODE_LENGTH:
            return
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        try:
            with get_db_connection() as conn:
                # 检查重复
                exists = conn.execute("SELECT id FROM scan_records WHERE code = ?", (code,)).fetchone()
                if exists:
                    logging.info(f"🔁 重复扫码: {code}")
                    return
                conn.execute(
                    "INSERT INTO scan_records (code, scan_time, log_file) VALUES (?, ?, ?)",
                    (code, now, 'server_listener')
                )
                conn.commit()
            logging.info(f"✅ 扫码成功: {code}")
        except Exception as e:
            logging.error(f"数据库写入失败: {e}")

    def start(self):
        if self.running:
            return
        self.listener = keyboard.Listener(on_press=self._on_press)
        self.listener.daemon = True
        self.listener.start()
        self.running = True
        logging.info("全局键盘监听已启动（扫码枪模式）")

    def stop(self):
        if self.listener and self.listener.is_alive():
            self.listener.stop()
            self.running = False
            logging.info("全局键盘监听已停止")

# 全局单例
keyboard_listener = KeyboardListener()