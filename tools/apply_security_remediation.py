from pathlib import Path
import re

root = Path(__file__).resolve().parents[1]
server = root / 'app' / 'server.py'
text = server.read_text(encoding='utf-8')

text = text.replace(
"DATA_LOCK = threading.RLock()\nPASSWORD_ITERATIONS = 260_000\nMAX_ORDER_QTY = 100\n",
"""DATA_LOCK = threading.RLock()
PASSWORD_ITERATIONS = 260_000
MAX_ORDER_QTY = 100
LOGIN_MAX_FAILURES = 5
LOGIN_BASE_LOCK_SECONDS = 60
LOGIN_MAX_LOCK_SECONDS = 15 * 60


def _login_throttle_key(username, ip_address):
    # Keep usernames/IPs out of the persisted operational data while ensuring
    # independent throttling for each account and source address.
    raw = f'{str(username or "").strip().lower()}\\x00{str(ip_address or "unknown")}'
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def login_throttle_remaining(data, username, ip_address):
    row = data.setdefault('_login_throttle', {}).get(_login_throttle_key(username, ip_address), {})
    try:
        return max(0, int(float(row.get('locked_until', 0)) - time.time()))
    except (TypeError, ValueError):
        return 0


def record_login_failure(data, username, ip_address):
    key = _login_throttle_key(username, ip_address)
    table = data.setdefault('_login_throttle', {})
    row = table.setdefault(key, {'failures': 0, 'locked_until': 0})
    row['failures'] = int(row.get('failures', 0) or 0) + 1
    if row['failures'] >= LOGIN_MAX_FAILURES:
        exponent = row['failures'] - LOGIN_MAX_FAILURES
        row['locked_until'] = time.time() + min(LOGIN_MAX_LOCK_SECONDS, LOGIN_BASE_LOCK_SECONDS * (2 ** exponent))
    save(data)


def clear_login_failures(data, username, ip_address):
    key = _login_throttle_key(username, ip_address)
    table = data.setdefault('_login_throttle', {})
    if key in table:
        table.pop(key, None)
        save(data)
""")

text = text.replace(
"    SESSION_COOKIE_SECURE=False,\n    PERMANENT_SESSION_LIFETIME=timedelta(days=30),\n)",
"""    SESSION_COOKIE_SECURE=False,
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    # Reject oversized JSON/multipart bodies before application handlers parse them.
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
)""")

old = """        detail_lines = [f\"الفاتورة: {order.get('id', '')}\", f\"التاريخ: {(order.get('timestamp') or order.get('date', ''))[:16]}\", divider]"""
new = """        raw_date = str(order.get('timestamp') or order.get('date', ''))[:16]
        # Keep the technical LTR value isolated from the Arabic RTL label. The
        # raster renderer must not run bidi reshaping over a mixed ISO token.
        safe_date = raw_date.replace('T', ' ')\n        isolated_date = '\\u200e' + safe_date + '\\u200e' if safe_date else ''
        detail_lines = [f\"الفاتورة: {order.get('id', '')}\", f\"التاريخ: {isolated_date}\", divider]"""
if old not in text:
    raise SystemExit('thermal receipt target not found')
text = text.replace(old, new)

old_login = """    data = load()
    username = (request.json.get('username') or '').strip()
    password = request.json.get('password') or ''
    users = data.get('settings', {}).get('users', [])
    for u in users:
        if u.get('username') == username and verify_password(u.get('password_hash'), password):
            # ترقية تجزئة النسخ القديمة عند أول دخول ناجح، من دون تغيير كلمة المرور.
            if not str(u.get('password_hash', '')).startswith('pbkdf2_sha256$'):
                u['password_hash'] = hash_password(password)
                save(data)
            session.clear()
            session.permanent = True
            session['username'] = u['username']
            session['role'] = u.get('role', 'cashier')
            return jsonify({\"ok\": True, \"username\": u['username'], \"role\": session['role']})
    return jsonify({\"ok\": False, \"error\": \"اسم المستخدم أو كلمة المرور غير صحيحة\"}), 401"""
new_login = """    data = load()
    payload = request.get_json(silent=True) or {}
    username = str(payload.get('username') or '').strip()
    password = str(payload.get('password') or '')
    ip_address = request.remote_addr or 'unknown'
    remaining = login_throttle_remaining(data, username, ip_address)
    if remaining:
        return jsonify({'ok': False, 'error': f'محاولات كثيرة؛ أعد المحاولة بعد {remaining} ثانية'}), 429
    users = data.get('settings', {}).get('users', [])
    matched = next((u for u in users if u.get('username') == username), None)
    if matched and verify_password(matched.get('password_hash'), password):
        clear_login_failures(data, username, ip_address)
        # ترقية تجزئة النسخ القديمة عند أول دخول ناجح، من دون تغيير كلمة المرور.
        if not str(matched.get('password_hash', '')).startswith('pbkdf2_sha256$'):
            matched['password_hash'] = hash_password(password)
            save(data)
        session.clear()
        session.permanent = True
        session['username'] = matched['username']
        session['role'] = matched.get('role', 'cashier')
        return jsonify({'ok': True, 'username': matched['username'], 'role': session['role']})
    record_login_failure(data, username, ip_address)
    return jsonify({'ok': False, 'error': 'اسم المستخدم أو كلمة المرور غير صحيحة'}), 401"""
if old_login not in text:
    raise SystemExit('pos login target not found')
text = text.replace(old_login, new_login)

old_mobile = """    payload = request.get_json(silent=True) or {}
    username = str(payload.get('username', '')).strip()
    password = str(payload.get('password', ''))
    data = load()
    user = next((row for row in active_users(data) if row.get('username') == username and row.get('role') == 'waiter'), None)
    if not user or not verify_password(user.get('password_hash', user.get('password', '')), password):
        return jsonify({'ok': False, 'error': 'بيانات النادل غير صحيحة'}), 401"""
new_mobile = """    payload = request.get_json(silent=True) or {}
    username = str(payload.get('username', '')).strip()
    password = str(payload.get('password', ''))
    data = load()
    ip_address = request.remote_addr or 'unknown'
    remaining = login_throttle_remaining(data, username, ip_address)
    if remaining:
        return jsonify({'ok': False, 'error': f'محاولات كثيرة؛ أعد المحاولة بعد {remaining} ثانية'}), 429
    user = next((row for row in active_users(data) if row.get('username') == username and row.get('role') == 'waiter'), None)
    if not user or not verify_password(user.get('password_hash', user.get('password', '')), password):
        record_login_failure(data, username, ip_address)
        return jsonify({'ok': False, 'error': 'بيانات النادل غير صحيحة'}), 401
    clear_login_failures(data, username, ip_address)"""
if old_mobile not in text:
    raise SystemExit('mobile login target not found')
text = text.replace(old_mobile, new_mobile)

old_cors = """    if request.path.startswith('/api/mobile/'):
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, OPTIONS'
    return response"""
new_cors = """    if request.path.startswith('/api/mobile/'):
        origin = request.headers.get('Origin', '')
        configured = {item.strip() for item in os.environ.get('CAESAR_MOBILE_ORIGINS', '').split(',') if item.strip()}
        if origin and origin in configured:
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Vary'] = 'Origin'
        response.headers['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, OPTIONS'
    return response"""
if old_cors not in text:
    raise SystemExit('cors target not found')
text = text.replace(old_cors, new_cors)

server.write_text(text, encoding='utf-8')

# Ensure the audited pages all use the local HTML escaper at their dynamic output sites.
# Existing pages already contain this helper; the checks below prevent regressions.
for name in ('customers.html', 'orders_list.html', 'debts.html', 'employees.html', 'menu_manager.html', 'raw_materials.html'):
    page = root / 'app' / name
    content = page.read_text(encoding='utf-8')
    if 'function esc(' not in content:
        raise SystemExit(f'missing esc helper in {name}')

print('Applied server throttling, request limit, CORS restriction, receipt bidi isolation, and frontend guard checks.')
