# routes/auth.py
from flask import Blueprint, render_template, request, redirect, url_for, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from db import get_db_connection, bcrypt
from models import User
from utils import (
    is_locked_out, record_failed_attempt, reset_attempts,
    admin_required, log_action
)

auth_bp = Blueprint('auth', __name__)

# ===================== 登录/登出 =====================
@auth_bp.route('/login', methods=['GET', 'POST'])
def login_page():
    if current_user.is_authenticated:
        return redirect('/')
    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        identifier = request.remote_addr   # 以 IP 作为锁定标识

        if is_locked_out(identifier):
            error = '登录失败次数过多，请10分钟后再试'
            return render_template('login.html', error=error)

        with get_db_connection() as conn:
            user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if user and bcrypt.check_password_hash(user['password'], password):
            reset_attempts(identifier)
            login_user(User(user['id'], user['username'], user['role']))
            log_action("用户登录", f"用户: {username}")
            return redirect(request.args.get('next') or '/')
        else:
            record_failed_attempt(identifier)
            error = '用户名或密码错误'
    return render_template('login.html', error=error)

@auth_bp.route('/logout')
@login_required
def logout():
    log_action("用户登出", f"用户: {current_user.username}")
    logout_user()
    return redirect('/login')

# ===================== 用户管理（仅管理员） =====================
@auth_bp.route('/users')
@login_required
@admin_required
def users_manage():
    return render_template('users.html')

@auth_bp.route('/api/users')
@login_required
@admin_required
def api_users():
    with get_db_connection() as conn:
        users = conn.execute("SELECT id, username, role, created_at FROM users ORDER BY id").fetchall()
    return jsonify([dict(u) for u in users])

@auth_bp.route('/api/users/add', methods=['POST'])
@login_required
@admin_required
def api_user_add():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '').strip()
    role = request.form.get('role', 'viewer').strip()
    if not username or not password:
        return jsonify({"success": False, "msg": "用户名和密码不能为空"})
    if len(password) < 6:
        return jsonify({"success": False, "msg": "密码至少6位"})
    with get_db_connection() as conn:
        exists = conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone()
        if exists:
            return jsonify({"success": False, "msg": "用户名已存在"})
        hashed = bcrypt.generate_password_hash(password).decode('utf-8')
        conn.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", (username, hashed, role))
        conn.commit()
    log_action("新增用户", f"管理员创建用户: {username}")
    return jsonify({"success": True, "msg": "用户创建成功"})

@auth_bp.route('/api/users/del', methods=['POST'])
@login_required
@admin_required
def api_user_del():
    uid = request.get_json().get('id')
    if not uid:
        return jsonify({"success": False, "msg": "缺少用户ID"})
    # 不允许删除自己
    if str(uid) == str(current_user.id):
        return jsonify({"success": False, "msg": "不能删除自己"})
    with get_db_connection() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (uid,))
        conn.commit()
    log_action("删除用户", f"用户ID: {uid}")
    return jsonify({"success": True, "msg": "用户已删除"})

@auth_bp.route('/api/users/set-password', methods=['POST'])
@login_required
@admin_required
def api_user_set_password():
    """管理员强制设置用户密码（无需旧密码）"""
    data = request.get_json()
    uid = data.get('id')
    new_pw = data.get('password', '').strip()
    if not uid or not new_pw:
        return jsonify({"success": False, "msg": "参数不完整"})
    if len(new_pw) < 6:
        return jsonify({"success": False, "msg": "密码至少6位"})
    hashed = bcrypt.generate_password_hash(new_pw).decode('utf-8')
    with get_db_connection() as conn:
        conn.execute("UPDATE users SET password = ? WHERE id = ?", (hashed, uid))
        conn.commit()
    log_action("设置用户密码", f"管理员修改了用户ID {uid} 的密码")
    return jsonify({"success": True, "msg": "密码已更新"})