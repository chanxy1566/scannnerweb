from flask_login import UserMixin
from db import get_db_connection

class User(UserMixin):
    def __init__(self, user_id, username, role='viewer'):
        self.id = user_id
        self.username = username
        self.role = role

    @staticmethod
    def get(user_id):
        with get_db_connection() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if row:
                return User(row['id'], row['username'], row['role'])
        return None