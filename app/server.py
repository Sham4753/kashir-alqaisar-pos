import os, sys, json, shutil, threading, urllib.request, hashlib, hmac, base64, secrets, tempfile, subprocess, socket, uuid, re
from datetime import datetime
from flask import Flask, request, jsonify, send_from_directory, send_file, session, redirect, Response
from io import BytesIO
VENDOR_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vendor')
if VENDOR_PATH not in sys.path:
    sys.path.insert(0, VENDOR_PATH)
try:
    import qrcode
    from qrcode.image.svg import SvgPathImage
except ImportError:
    qrcode = None
    SvgPathImage = None

# ========== إعدادات التحديث ==========
GITHUB_USER = "Sham4753"
GITHUB_REPO = "shamjb-updates"
GITHUB_BRANCH = "main"
BASE_URL = f"https://raw.githubusercontent.com/{GITHUB_USER}/{GITHUB_REPO}/{GITHUB_BRANCH}"
CURRENT_VERSION = "3.2.0"

# قائمة ملفات الواجهة القابلة للتحديث عن بعد (بدون الحاجة لإعادة بناء exe).
# ملاحظة مهمة: server.py نفسه مو بهاي القائمة عمداً - هو مبني جوا الـ exe بواسطة Nuitka،
# فتحديثه عن بعد مستحيل تقنياً بدون إعادة بناء exe جديد ونقله يدوياً لكل جهاز.
UPDATABLE_FILES = [
    "index.html", "menu_manager.html", "debts.html", "employees.html",
    "raw_materials.html", "analytics.html", "orders_list.html",
    "settings.html", "printer_settings.html", "kitchen.html", "tables.html", "customers.html", "qr_menu.html", "manager_ops.html", "expenses.html", "mobile.html", "setup.html", "tailwind.css"
]


def version_tuple(v):
    """تحويل رقم الإصدار إلى tuple للمقارنة الصحيحة"""
    return tuple(int(x) for x in v.strip().split('.'))

def check_for_updates():
    """يتحقق من نسخة جديدة على GitHub، ولو موجودة يحمّل كل ملفات الواجهة المحدّثة
    (بدون server.py - هذا محدود تقنياً بطبيعة تعليب Nuitka، يحتاج إعادة بناء exe يدوياً).
    يُستدعى تلقائياً عند بدء التشغيل، وكمان متاح يدوياً عبر /api/check-update?apply=1"""
    result = {"ok": False, "current": CURRENT_VERSION, "latest": None, "updated_files": [], "error": None}
    try:
        with urllib.request.urlopen(f"{BASE_URL}/version.txt", timeout=6) as f:
            latest = f.read().decode().strip()
        result["latest"] = latest
        if version_tuple(latest) <= version_tuple(CURRENT_VERSION):
            result["ok"] = True
            return result
        # في تحديث أحدث - نزّل كل ملفات الواجهة المعروفة وحدة وحدة (فشل ملف واحد ما يوقف الباقي)
        for fname in UPDATABLE_FILES:
            try:
                url = f"{BASE_URL}/{fname}"
                dest = os.path.join(APP_PATH, fname)
                tmp = dest + ".tmp"
                urllib.request.urlretrieve(url, tmp)
                shutil.move(tmp, dest)
                result["updated_files"].append(fname)
            except Exception as fe:
                with open(os.path.join(APP_PATH, "update.log"), "a", encoding="utf-8") as log:
                    log.write(f"{datetime.now()}: فشل تحديث {fname} - {fe}\n")
        with open(os.path.join(APP_PATH, "update.log"), "a", encoding="utf-8") as log:
            log.write(f"{datetime.now()}: تحديث لواجهة v{latest} - ملفات محدّثة: {', '.join(result['updated_files'])}\n")
        result["ok"] = True
        return result
    except Exception as e:
        result["error"] = str(e)
        try:
            with open(os.path.join(APP_PATH, "update.log"), "a", encoding="utf-8") as log:
                log.write(f"{datetime.now()}: تعذر التحقق من التحديث - {e}\n")
        except Exception:
            pass
        return result

# ========== مسارات ==========
# تحديد مسار التشغيل
if getattr(sys, 'frozen', False):
    APP_PATH = os.path.dirname(os.path.abspath(sys.argv[0]))
    EXTERNAL_PATH = APP_PATH
else:
    APP_PATH = os.path.dirname(os.path.abspath(sys.argv[0]))
    EXTERNAL_PATH = APP_PATH

BASE_DIR = EXTERNAL_PATH


def choose_vault_dir():
    """يختار مجلد بيانات قابلًا للكتابة دون صلاحيات مدير على Windows، مع الحفاظ على المسار القديم إن أمكن."""
    if sys.platform == 'win32':
        candidates = [r'C:\ShamJB_Vault']
        local_app_data = os.environ.get('LOCALAPPDATA')
        user_profile = os.environ.get('USERPROFILE')
        if local_app_data:
            candidates.append(os.path.join(local_app_data, 'ShamJB_Vault'))
        if user_profile:
            candidates.append(os.path.join(user_profile, 'Documents', 'ShamJB_Vault'))
    else:
        candidates = [os.path.join(os.path.expanduser('~'), 'Documents', 'ShamJB_Vault')]

    for candidate in candidates:
        try:
            os.makedirs(candidate, exist_ok=True)
            probe = os.path.join(candidate, '.write_test')
            with open(probe, 'w', encoding='utf-8') as f:
                f.write('ok')
            os.remove(probe)
            return candidate
        except Exception:
            continue

    fallback = os.path.join(BASE_DIR, 'data_vault')
    os.makedirs(fallback, exist_ok=True)
    return fallback


VAULT_DIR = choose_vault_dir()
DATA_FILE = os.path.join(VAULT_DIR, 'data.json')
BACKUP_DIR = os.path.join(VAULT_DIR, 'backups')
FLASH_BACKUP = os.path.join(BASE_DIR, 'data_backup.json')
FACTORY_FILE = os.path.join(BASE_DIR, 'factory_data.json')

os.makedirs(VAULT_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)

if not os.path.exists(DATA_FILE):
    if os.path.exists(FLASH_BACKUP):
        shutil.copy(FLASH_BACKUP, DATA_FILE)
    else:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump({"menu": {}, "orders": [], "shifts": [], "log": [], "settings": {"currency": "SYP"}}, f, ensure_ascii=False, indent=2)

app = Flask(__name__, static_folder=BASE_DIR, static_url_path='')
# جلسات محلية قصيرة العمر؛ لا تُقرأ من JavaScript ولا تُرسل لمواقع أخرى.
app.secret_key = os.urandom(32)
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax')
DATA_LOCK = threading.RLock()
PASSWORD_ITERATIONS = 260_000
MAX_ORDER_QTY = 100

def migrate_legacy_users(data):
    """يحوّل المستخدمين الموجودين في النسخ القديمة إلى settings.users مع تشفير كلمة المرور."""
    settings = data.setdefault('settings', {})
    if 'users' in settings:
        return False
    legacy_users = data.get('users', [])
    if not legacy_users:
        return False
    migrated = []
    for user in legacy_users:
        if not isinstance(user, dict) or not user.get('username'):
            continue
        password_hash = user.get('password_hash')
        if not password_hash and 'password' in user:
            password_hash = hash_password(user.get('password', ''))
        if not password_hash:
            continue
        migrated.append({
            'id': user.get('id', len(migrated) + 1),
            'username': user.get('username', ''),
            'password_hash': password_hash,
            'role': user.get('role', 'cashier')
        })
    if not migrated:
        return False
    settings['users'] = migrated
    return True


def ensure_inventory(data):
    """ينشئ رصيدًا أوليًا للنسخ القديمة التي تحتوي موادًا خامًا بلا قسم inventory."""
    if 'inventory' in data:
        return False
    inventory = []
    for material in data.get('materials', []):
        inventory.append({
            'id': material.get('id', len(inventory) + 1),
            'name': material.get('name', ''),
            'unit': material.get('unit', ''),
            'stock': material.get('quantity', 0) or 0,
            'low_stock_threshold': 0
        })
    data['inventory'] = inventory
    return True


def atomic_write_json(path, data):
    """يكتب JSON ذرياً حتى لا تُتلف الفاتورة أو انقطاع الكهرباء ملف البيانات."""
    directory = os.path.dirname(path) or '.'
    fd, temp_path = tempfile.mkstemp(prefix='.kashir_', suffix='.tmp', dir=directory)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def load():
    with DATA_LOCK:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        changed = ensure_ids(data)
        if migrate_legacy_users(data):
            changed = True
        if ensure_inventory(data):
            changed = True
        if changed:
            atomic_write_json(DATA_FILE, data)
        return data


def save(data):
    with DATA_LOCK:
        atomic_write_json(DATA_FILE, data)
        try:
            atomic_write_json(FLASH_BACKUP, data)
        except OSError:
            pass


def backup():
    with DATA_LOCK:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        shutil.copy2(DATA_FILE, os.path.join(BACKUP_DIR, f'backup_{ts}.json'))
        backups = sorted(os.listdir(BACKUP_DIR))
        for old in backups[:-30]:
            os.remove(os.path.join(BACKUP_DIR, old))

def ensure_ids(data):
    """يضمن أن كل سجل بالقوائم (موظفين/ديون/مواد) عنده id فريد.
    مهم لأن سجلات قديمة كانت تُضاف بدون id قبل التحديث الحالي."""
    changed = False
    for key in ('employees', 'debts', 'materials'):
        items = data.get(key, [])
        existing_ids = [i['id'] for i in items if isinstance(i, dict) and 'id' in i]
        next_id = (max(existing_ids) if existing_ids else 0) + 1
        for item in items:
            if 'id' not in item:
                item['id'] = next_id
                next_id += 1
                changed = True
    return changed

def hash_password(pw):
    """تخزين كلمة المرور بمشتق PBKDF2 مع ملح فريد بدلاً من SHA-256 سريع وغير مملّح."""
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac('sha256', (pw or '').encode('utf-8'), salt, PASSWORD_ITERATIONS)
    return 'pbkdf2_sha256${}${}${}'.format(
        PASSWORD_ITERATIONS,
        base64.urlsafe_b64encode(salt).decode('ascii'),
        base64.urlsafe_b64encode(digest).decode('ascii')
    )


def verify_password(stored_hash, password):
    stored_hash = str(stored_hash or '')
    if stored_hash.startswith('pbkdf2_sha256$'):
        try:
            _, iterations, salt_b64, digest_b64 = stored_hash.split('$', 3)
            salt = base64.urlsafe_b64decode(salt_b64.encode('ascii'))
            expected = base64.urlsafe_b64decode(digest_b64.encode('ascii'))
            actual = hashlib.pbkdf2_hmac('sha256', (password or '').encode('utf-8'), salt, int(iterations))
            return hmac.compare_digest(actual, expected)
        except (ValueError, TypeError, base64.binascii.Error):
            return False
    # توافق آمن مؤقتاً مع النسخ القديمة، وتُرقّى التجزئة فور تسجيل الدخول الناجح.
    legacy = hashlib.sha256((password or '').encode('utf-8')).hexdigest()
    return hmac.compare_digest(stored_hash, legacy)

def currency_snapshot(data, payload=None):
    settings = data.get('settings', {})
    payload = payload or {}
    currency = payload.get('currency') or settings.get('currency', 'SYP')
    if currency not in ('SYP', 'USD', 'EUR'):
        currency = 'SYP'
    try:
        rate = float(payload.get('exchange_rate') or (1 if currency == 'SYP' else settings.get('usd_rate' if currency == 'USD' else 'eur_rate', 0)) or 0)
    except (TypeError, ValueError):
        rate = 0
    return {'currency': currency, 'exchange_rate': rate}

def next_order_id(data):
    """يولّد رقم فاتورة جديد، ويصفّر العداد تلقائياً + يؤرشف طلبات الأمس أول ما يبدأ يوم جديد.
    يُستخدم من كل مكان بالكود بيُنشئ طلب (POST /api/orders و تسديد الديون) لضمان عدم تعارض الأرقام."""
    today = datetime.now().strftime('%Y-%m-%d')
    last_date = data.get('settings', {}).get('last_order_date')
    if last_date != today:
        if data.get('orders'):
            shift_id = last_date or today
            for o in data['orders']:
                o['shift_id'] = shift_id
            data.setdefault('orders_archive', []).extend(data['orders'])
            data['orders'] = []
        data['order_counter'] = 0
        data.setdefault('settings', {})['last_order_date'] = today
    data['order_counter'] = data.get('order_counter', 0) + 1
    return f"ORD-{data['order_counter']:04d}"

def commercial_setup_complete(data=None):
    """يحافظ على توافق النسخ القديمة ويكشف فقط قوالب البيع غير المهيأة."""
    data = data or load()
    settings = data.get('settings', {})
    commercial = settings.get('commercial', {})
    if commercial.get('setup_completed'):
        return True
    # النسخ القديمة التي تحتوي مطعمًا ومستخدمين تعتبر مهيأة ولا يعاد ضبطها.
    return bool(settings.get('restaurant', {}).get('name') and settings.get('users'))

def write_local_license(data):
    settings = data.setdefault('settings', {})
    commercial = settings.setdefault('commercial', {})
    license_data = {
        'product': 'Kashir Al-Qaisar', 'edition': 'Standalone Restaurant',
        'license_id': commercial.get('license_id'), 'instance_id': commercial.get('instance_id'),
        'restaurant_name': settings.get('restaurant', {}).get('name', ''),
        'owner_name': commercial.get('owner_name', ''), 'issued_at': commercial.get('created_at', ''),
        'status': 'active', 'offline': True
    }
    with open(os.path.join(VAULT_DIR, 'license.json'), 'w', encoding='utf-8') as f:
        json.dump(license_data, f, ensure_ascii=False, indent=2)

@app.route('/')
def index():
    if not commercial_setup_complete():
        return redirect('/setup.html')
    return send_from_directory(BASE_DIR, 'welcome.html')

@app.route('/welcome.html')
def welcome_page():
    if not commercial_setup_complete():
        return redirect('/setup.html')
    return send_from_directory(BASE_DIR, 'welcome.html')


@app.route('/api/setup/status', methods=['GET'])
def setup_status():
    data = load(); settings = data.get('settings', {}); commercial = settings.get('commercial', {})
    return jsonify({'setup_completed': commercial_setup_complete(data), 'is_commercial_template': not commercial_setup_complete(data),
                    'restaurant_name': settings.get('restaurant', {}).get('name', ''),
                    'license_id': commercial.get('license_id', '')})

@app.route('/api/setup/initialize', methods=['POST'])
def setup_initialize():
    data = load()
    if commercial_setup_complete(data):
        return jsonify({'ok': False, 'error': 'هذه النسخة مهيأة مسبقًا. استخدم الإعدادات لتعديل بيانات المطعم.'}), 409
    payload = request.get_json(silent=True) or {}
    restaurant_name = str(payload.get('restaurant_name', '')).strip()
    manager_username = str(payload.get('manager_username', '')).strip()
    manager_password = str(payload.get('manager_password', ''))
    if not restaurant_name or not manager_username or len(manager_password) < 8:
        return jsonify({'ok': False, 'error': 'اسم المطعم واسم المدير وكلمة مرور من 8 أحرف على الأقل مطلوبة'}), 400
    settings = data.setdefault('settings', {})
    settings['restaurant'] = {'name': restaurant_name, 'phone': str(payload.get('phone', '')).strip(), 'address': str(payload.get('address', '')).strip()}
    settings['currency'] = payload.get('currency', 'SYP') if payload.get('currency') in ('SYP', 'USD', 'EUR') else 'SYP'
    settings['users'] = [{'id': 1, 'username': manager_username, 'password_hash': hash_password(manager_password), 'role': 'manager'}]
    settings['commercial'] = {'setup_completed': True, 'vendor_master': False, 'instance_id': str(uuid.uuid4()),
                              'license_id': str(payload.get('license_id', '')).strip() or 'QAISAR-' + uuid.uuid4().hex[:10].upper(),
                              'owner_name': str(payload.get('owner_name', '')).strip(), 'created_at': datetime.now().isoformat()}
    save(data); backup(); write_local_license(data)
    # تصبح نسخة المصنع الخاصة بالعميل بعد التهيئة، حتى لا تعيد الضبط بيانات مطعم آخر.
    atomic_write_json(FACTORY_FILE, data)
    atomic_write_json(FLASH_BACKUP, data)
    return jsonify({'ok': True, 'license_id': settings['commercial']['license_id']})

@app.route('/api/license', methods=['GET'])
def local_license():
    path = os.path.join(VAULT_DIR, 'license.json')
    if not os.path.exists(path):
        return jsonify({'ok': False, 'error': 'لا يوجد ترخيص محلي بعد'}), 404
    with open(path, encoding='utf-8') as f:
        return jsonify(json.load(f))

@app.route('/api/menu', methods=['GET'])
def get_menu():
    return jsonify(load().get('menu', {}))

@app.route('/api/category', methods=['POST'])
def add_category():
    data = load()
    cat = request.json.get('name', '').strip()
    if cat and cat not in data['menu']:
        data['menu'][cat] = []
    save(data); backup()
    return jsonify({"ok": True})

@app.route('/api/category/<name>', methods=['DELETE'])
def delete_category(name):
    data = load()
    if name in data['menu']:
        del data['menu'][name]
    save(data); backup()
    return jsonify({"ok": True})

@app.route('/api/category/<name>/rename', methods=['POST'])
def rename_category(name):
    """إعادة تسمية قسم مع الحفاظ على كل منتجاته (بدل حذفه وإنشاء واحد فاضي بالخطأ)"""
    data = load()
    new_name = request.json.get('name', '').strip()
    if not new_name:
        return jsonify({"ok": False, "error": "الاسم الجديد فارغ"})
    if name not in data['menu']:
        return jsonify({"ok": False, "error": "القسم غير موجود"})
    if new_name != name and new_name in data['menu']:
        return jsonify({"ok": False, "error": "يوجد قسم بهذا الاسم مسبقاً"})
    data['menu'][new_name] = data['menu'].pop(name)
    save(data); backup()
    return jsonify({"ok": True})

@app.route('/api/product', methods=['POST'])
def add_product():
    data = load()
    cat = request.json.get('category')
    payload = request.get_json(silent=True) or {}
    barcode = str(payload.get('barcode', '') or '').strip()
    if barcode and any(str(x.get('barcode', '')) == barcode for items in data['menu'].values() for x in items):
        return jsonify({'ok': False, 'error': 'الباركود مستخدم لمنتج آخر'}), 409
    p = {"id": payload.get('id'), "name": payload.get('name'), "price": payload.get('price'),
         "image": payload.get('image', ''), "barcode": barcode,
         "modifiers": payload.get('modifiers', []), "combo_items": payload.get('combo_items', []),
         "kitchen_station": payload.get('kitchen_station', 'main'), "offer_id": payload.get('offer_id')}
    if cat in data['menu']:
        data['menu'][cat].append(p)
    save(data); backup()
    return jsonify({"ok": True})

@app.route('/api/product/<int:pid>', methods=['PUT'])
def update_product(pid):
    """تعديل منتج بمعرّفه - يبحث بكل الأقسام حتى يجد المنتج فعلاً (كان قبلاً يتفحص أول منتج فقط بأول قسم ثم يرجع)."""
    data = load()
    for cat in data['menu']:
        for p in data['menu'][cat]:
            if p['id'] == pid:
                payload = request.get_json(silent=True) or {}
                barcode = str(payload.get('barcode', p.get('barcode', '')) or '').strip()
                if barcode and any(str(x.get('barcode', '')) == barcode and x is not p for items in data['menu'].values() for x in items):
                    return jsonify({'ok': False, 'error': 'الباركود مستخدم لمنتج آخر'}), 409
                p['name'] = payload.get('name', p['name'])
                p['price'] = payload.get('price', p['price'])
                p['barcode'] = barcode
                if 'image' in payload:
                    p['image'] = payload.get('image', '')
                for key in ('modifiers', 'combo_items', 'kitchen_station', 'offer_id'):
                    if key in payload:
                        p[key] = payload.get(key)
                save(data); backup()
                return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "المنتج غير موجود"}), 404

@app.route('/api/product/<int:pid>', methods=['DELETE'])
def delete_product(pid):
    """حذف منتج بمعرّفه - نفس إصلاح البحث بكل الأقسام بدل التوقف عند أول منتج فقط."""
    data = load()
    for cat in data['menu']:
        for p in data['menu'][cat]:
            if p['id'] == pid:
                data['menu'][cat].remove(p)
                save(data); backup()
                return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "المنتج غير موجود"}), 404

@app.route('/api/barcode/<barcode>', methods=['GET'])
def get_product_by_barcode(barcode):
    """يبحث عن منتج بالباركود لإضافته مباشرة إلى السلة."""
    wanted = str(barcode or '').strip()
    data = load()
    for category, products in data.get('menu', {}).items():
        for product in products:
            if str(product.get('barcode', '')).strip() == wanted and wanted:
                return jsonify({'ok': True, 'category': category, 'product': product})
    return jsonify({'ok': False, 'error': 'الباركود غير مرتبط بأي منتج'}), 404


@app.route('/api/product/<int:pid>/recipe', methods=['GET'])
def get_product_recipe(pid):
    """وصفة المنتج: قائمة المواد الخام وكمّياتها اللي تدخل بصنع وحدة واحدة منه.
    تُستخدم لخصم المخزون تلقائياً عند البيع، ولحساب تكلفة/هامش ربح كل منتج."""
    data = load()
    for cat in data['menu']:
        for p in data['menu'][cat]:
            if p['id'] == pid:
                return jsonify(p.get('recipe', []))
    return jsonify({"ok": False, "error": "المنتج غير موجود"}), 404

@app.route('/api/product/<int:pid>/recipe', methods=['POST'])
def set_product_recipe(pid):
    """حفظ وصفة المنتج - يستقبل [{material: اسم_المادة, qty: الكمية_لوحدة_واحدة}, ...]"""
    data = load()
    for cat in data['menu']:
        for p in data['menu'][cat]:
            if p['id'] == pid:
                p['recipe'] = request.json.get('recipe', [])
                save(data); backup()
                return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "المنتج غير موجود"}), 404


def material_avg_cost(data, material_name):
    """متوسط سعر شراء الوحدة الواحدة من مادة معيّنة، محسوب من كل سجل مشترياتها
    (مجموع كل المبالغ المدفوعة ÷ مجموع كل الكمّيات المشتراة). يرجع None لو ما في سجل شراء أصلاً."""
    total_qty = 0
    total_paid = 0
    for m in data.get('materials', []):
        if m.get('name') == material_name:
            total_qty += m.get('quantity', 0) or 0
            total_paid += m.get('price', 0) or 0
    if total_qty <= 0:
        return None
    return total_paid / total_qty

def compute_product_cost(data, product):
    """تكلفة صنع وحدة واحدة من المنتج بناءً على وصفته. يرجع None لو ما في وصفة،
    أو لو في مادة بالوصفة بدون أي سجل شراء (تكلفتها غير معروفة)."""
    recipe = product.get('recipe', [])
    if not recipe:
        return None
    total_cost = 0
    for ing in recipe:
        avg = material_avg_cost(data, ing.get('material', ''))
        if avg is None:
            return None
        total_cost += avg * (ing.get('qty', 0) or 0)
    return total_cost

@app.route('/api/product/<int:pid>/cost', methods=['GET'])
def get_product_cost(pid):
    """تكلفة وهامش ربح منتج واحد."""
    data = load()
    for cat in data['menu']:
        for p in data['menu'][cat]:
            if p['id'] == pid:
                cost = compute_product_cost(data, p)
                if cost is None:
                    return jsonify({"ok": True, "has_recipe": bool(p.get('recipe')), "cost": None,
                                     "profit": None, "margin_pct": None})
                price = p.get('price', 0)
                profit = price - cost
                margin_pct = round((profit / price * 100), 1) if price > 0 else None
                return jsonify({"ok": True, "has_recipe": True, "cost": round(cost, 2),
                                 "profit": round(profit, 2), "margin_pct": margin_pct})
    return jsonify({"ok": False, "error": "المنتج غير موجود"}), 404

@app.route('/api/menu/profitability', methods=['GET'])
def menu_profitability():
    """تقرير ربحية كل منتجات المنيو دفعة وحدة - للاستخدام بصفحة التحليلات أو إدارة المنيو."""
    data = load()
    rows = []
    for cat, prods in data.get('menu', {}).items():
        for p in prods:
            cost = compute_product_cost(data, p)
            price = p.get('price', 0)
            row = {"category": cat, "name": p.get('name', ''), "price": price, "cost": None,
                   "profit": None, "margin_pct": None}
            if cost is not None:
                profit = price - cost
                row["cost"] = round(cost, 2)
                row["profit"] = round(profit, 2)
                row["margin_pct"] = round((profit / price * 100), 1) if price > 0 else None
            rows.append(row)
    return jsonify(rows)

def consume_inventory_for_order(data, items):
    """يخصم من المخزون حسب وصفة كل صنف مُباع × الكمية. الأصناف اللي ما إلها وصفة محددة تُتجاهل بصمت
    (يسمح بالعمل تدريجياً بدون ما يجبرك تحدد وصفة لكل شي فوراً)."""
    item_recipes = {}
    for cat, prods in data.get('menu', {}).items():
        for p in prods:
            if p.get('recipe'):
                item_recipes[p.get('id')] = p['recipe']
                item_recipes.setdefault(p.get('name', ''), p['recipe'])
    for i in items:
        name = i.get('name', '')
        qty_sold = i.get('quantity', i.get('qty', 1))
        recipe = item_recipes.get(i.get('product_id', i.get('id'))) or item_recipes.get(name)
        if not recipe:
            continue
        for ing in recipe:
            sync_inventory_consume(data, ing.get('material', ''), (ing.get('qty', 0) or 0) * qty_sold)

def as_money(value, default=None):
    try:
        amount = round(float(value), 2)
        return amount if amount >= 0 else default
    except (TypeError, ValueError):
        return default


def approved_order_items(data, raw_items):
    """يبني أصناف الفاتورة من منيو الخادم، فلا يعتمد السعر أو الاسم أو الكمية القادمة من المتصفح."""
    if not isinstance(raw_items, list) or not raw_items or len(raw_items) > 100:
        return None, 'يجب أن تحتوي الفاتورة على أصناف صالحة (بحد أقصى 100 سطر)'
    products_by_id = {}
    products_by_name = {}
    for products in data.get('menu', {}).values():
        for product in products:
            if not isinstance(product, dict):
                continue
            pid = product.get('id')
            if isinstance(pid, int):
                products_by_id[pid] = product
            name = str(product.get('name', '')).strip()
            if name:
                products_by_name.setdefault(name, []).append(product)

    approved = []
    for item in raw_items:
        if not isinstance(item, dict):
            return None, 'يوجد صنف غير صالح في الفاتورة'
        product = None
        try:
            product = products_by_id.get(int(item.get('product_id', item.get('id'))))
        except (TypeError, ValueError):
            pass
        if product is None:
            candidates = products_by_name.get(str(item.get('name', '')).strip(), [])
            if len(candidates) == 1:
                product = candidates[0]
        if product is None:
            return None, 'أحد الأصناف لم يعد موجوداً في المنيو؛ حدّث السلة ثم أعد المحاولة'
        try:
            qty_value = float(item.get('quantity', item.get('qty', 1)))
            qty = int(qty_value)
        except (TypeError, ValueError):
            return None, 'كمية أحد الأصناف غير صالحة'
        if qty_value != qty or not 1 <= qty <= MAX_ORDER_QTY:
            return None, f'كمية كل صنف يجب أن تكون عدداً صحيحاً بين 1 و{MAX_ORDER_QTY}'
        price = as_money(product.get('price'))
        if price is None:
            return None, 'سعر أحد الأصناف في المنيو غير صالح'
        modifiers = item.get('modifiers', [])
        if not isinstance(modifiers, list):
            modifiers = []
        allowed_modifiers = {str(x) for x in product.get('modifiers', []) if isinstance(x, str)}
        modifiers = [str(x)[:80] for x in modifiers if str(x) in allowed_modifiers][:10]
        approved.append({'product_id': product.get('id'), 'name': str(product.get('name', '')).strip(),
                         'price': price, 'quantity': qty, 'modifiers': modifiers})
    return approved, None


def normalize_payment(total, payload):
    payment = str(payload.get('payment', 'نقدي') or 'نقدي')
    if payment not in {'نقدي', 'بطاقة', 'مختلط'}:
        return None, 'طريقة الدفع غير صالحة'
    if payment == 'نقدي':
        return {'payment': payment, 'cash_amount': total, 'card_amount': 0}, None
    if payment == 'بطاقة':
        return {'payment': payment, 'cash_amount': 0, 'card_amount': total}, None
    cash = as_money(payload.get('cash_amount'))
    card = as_money(payload.get('card_amount'))
    if cash is None or card is None or abs((cash + card) - total) > 0.01:
        return None, 'مبالغ الدفع المختلط يجب أن تساوي إجمالي الفاتورة'
    return {'payment': payment, 'cash_amount': cash, 'card_amount': card}, None


@app.route('/api/orders', methods=['GET', 'POST'])
def orders():
    data = load()
    if request.method == 'POST':
        payload = request.get_json(silent=True) or {}
        items, item_error = approved_order_items(data, payload.get('items'))
        if item_error:
            return jsonify({'ok': False, 'error': item_error}), 400
        subtotal = round(sum(item['price'] * item['quantity'] for item in items), 2)
        discount_pct = as_money(payload.get('discount_pct', 0), 0)
        discount_amount = as_money(payload.get('discount_amount', 0), 0)
        if discount_pct is None or discount_pct > 100 or discount_amount is None:
            return jsonify({'ok': False, 'error': 'قيمة الخصم غير صالحة'}), 400
        after_percent = round(subtotal * (1 - discount_pct / 100), 2)
        if discount_amount > after_percent:
            return jsonify({'ok': False, 'error': 'الخصم أكبر من إجمالي الفاتورة'}), 400
        total = round(after_percent - discount_amount, 2)
        payment_data, payment_error = normalize_payment(total, payload)
        if payment_error:
            return jsonify({'ok': False, 'error': payment_error}), 400
        order_type = str(payload.get('type', 'سفري') or 'سفري')
        if order_type not in {'سفري', 'صالة', 'ديليفري'}:
            return jsonify({'ok': False, 'error': 'نوع الطلب غير صالح'}), 400
        o = {
            'id': next_order_id(data), 'timestamp': datetime.now().isoformat(), 'items': items,
            'subtotal': subtotal, 'discount_pct': discount_pct, 'discount_amount': discount_amount,
            'total': total, 'type': order_type, 'note': str(payload.get('note', ''))[:500],
            'customer': str(payload.get('customer', ''))[:120], 'table': str(payload.get('table', ''))[:60],
            'cashier_name': session.get('username', 'غير محدد'), **payment_data
        }
        snap = currency_snapshot(data, payload)
        o['currency'] = snap['currency']; o['exchange_rate'] = snap['exchange_rate']
        data.setdefault('orders', []).append(o)
        consume_inventory_for_order(data, o['items'])
        save(data); backup()
        return jsonify({'ok': True, 'id': o['id'], 'total': total})
    all_orders = data.get('orders', []) + data.get('orders_archive', [])
    date_from = request.args.get('from', '').strip()
    date_to = request.args.get('to', '').strip()
    if date_from:
        all_orders = [o for o in all_orders if o.get('timestamp', o.get('date', ''))[:10] >= date_from]
    if date_to:
        all_orders = [o for o in all_orders if o.get('timestamp', o.get('date', ''))[:10] <= date_to]
    return jsonify(all_orders)

def check_manager_password(data, req_json):
    """يتحقق من كلمة مرور مستخدم مسجّل - يُستخدم لحماية أي عملية حساسة (إلغاء طلب، تعديل طلب).
    لو ما في مستخدمين مسجّلين بالنظام أصلاً، يسمح بالعملية بدون كلمة مرور (سلوك تدريجي)."""
    users = data.get('settings', {}).get('users', [])
    if not users:
        return True, None
    username = (req_json.get('username') or '').strip() if req_json else ''
    password = (req_json.get('password') or '') if req_json else ''
    valid = any(
        u.get('username') == username and verify_password(u.get('password_hash'), password)
        for u in users
    )
    if not valid:
        return False, (jsonify({"ok": False, "error": "كلمة المرور غير صحيحة - العملية تحتاج صلاحية"}), 401)
    return True, None

def build_item_recipes(data):
    """خريطة اسم_المنتج -> وصفته، من المنيو الحالي."""
    item_recipes = {}
    for cat, prods in data.get('menu', {}).items():
        for p in prods:
            if p.get('recipe'):
                item_recipes[p.get('id')] = p['recipe']
                item_recipes.setdefault(p.get('name', ''), p['recipe'])
    return item_recipes

@app.route('/api/orders/<order_id>/void', methods=['POST'])
def void_order(order_id):
    """إلغاء طلب مع سبب مسجّل (بدل ما يختفي بدون أي أثر). يبقى بالسجل لكن يُستبعد من المبيعات بالتحليلات،
    ويرجّع المخزون المستهلك منه إذا كان له وصفة.
    محمي بكلمة مرور: لو في مستخدمين مسجّلين بالنظام، لازم تحقق ناجح قبل الإلغاء - لمنع أي كاشير
    من إلغاء طلب مدفوع فعلياً لإخفاء سرقة."""
    data = load()
    ok, err = check_manager_password(data, request.json)
    if not ok:
        return err
    reason = request.json.get('reason', '') if request.json else ''
    for lst_name in ('orders', 'orders_archive'):
        for o in data.get(lst_name, []):
            if str(o.get('id')) == str(order_id):
                if o.get('voided'):
                    return jsonify({"ok": False, "error": "الطلب ملغى مسبقاً"})
                o['voided'] = True
                o['void_reason'] = reason
                o['void_date'] = datetime.now().isoformat()
                # إرجاع المخزون المستهلك من هذا الطلب (عكس consume_inventory_for_order)
                item_recipes = build_item_recipes(data)
                for i in o.get('items', []):
                    recipe = item_recipes.get(i.get('product_id', i.get('id'))) or item_recipes.get(i.get('name', ''))
                    if not recipe:
                        continue
                    qty_sold = i.get('quantity', i.get('qty', 1))
                    for ing in recipe:
                        sync_inventory_add(data, ing.get('material', ''), '', (ing.get('qty', 0) or 0) * qty_sold)
                save(data); backup()
                return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "الطلب غير موجود"}), 404

@app.route('/api/orders/<order_id>/edit-items', methods=['POST'])
def edit_order_items(order_id):
    """تعديل أصناف طلب قائم (حذف صنف، أو تغيير كميته) بدل إلغاء الطلب كامل.
    محمي بنفس حماية كلمة مرور الإلغاء. يضبط المخزون تلقائياً بالفرق بين القديم والجديد،
    ويعيد حساب الإجمالي، ويسجّل تاريخ التعديل والسبب بالطلب نفسه (بدون ما يمسح الأثر الأصلي)."""
    data = load()
    ok, err = check_manager_password(data, request.json)
    if not ok:
        return err
    new_items = request.json.get('items') if request.json else None
    reason = request.json.get('reason', '') if request.json else ''
    if new_items is None:
        return jsonify({"ok": False, "error": "ما في قائمة أصناف جديدة"}), 400

    for lst_name in ('orders', 'orders_archive'):
        for o in data.get(lst_name, []):
            if str(o.get('id')) == str(order_id):
                if o.get('voided'):
                    return jsonify({"ok": False, "error": "الطلب ملغى، ما فيك تعدّله"}), 400

                item_recipes = build_item_recipes(data)
                old_items = o.get('items', [])
                old_qty_by_name = {}
                for i in old_items:
                    old_qty_by_name[i.get('name', '')] = old_qty_by_name.get(i.get('name', ''), 0) + i.get('quantity', i.get('qty', 1))
                new_qty_by_name = {}
                for i in new_items:
                    new_qty_by_name[i.get('name', '')] = new_qty_by_name.get(i.get('name', ''), 0) + i.get('quantity', i.get('qty', 1))

                # ضبط المخزون بالفرق (نقص الكمية = رجّع للمخزون، زيادة الكمية = خصم إضافي)
                all_names = set(old_qty_by_name) | set(new_qty_by_name)
                for name in all_names:
                    diff = old_qty_by_name.get(name, 0) - new_qty_by_name.get(name, 0)  # موجب = نقص بالطلب
                    recipe = item_recipes.get(name)
                    if not recipe or diff == 0:
                        continue
                    for ing in recipe:
                        qty_change = (ing.get('qty', 0) or 0) * diff
                        if qty_change > 0:
                            sync_inventory_add(data, ing.get('material', ''), '', qty_change)
                        else:
                            sync_inventory_consume(data, ing.get('material', ''), -qty_change)

                # سجل تعديل (بدون فقدان الطلب الأصلي - للمراجعة لاحقاً)
                edit_history = o.setdefault('edit_history', [])
                edit_history.append({
                    "date": datetime.now().isoformat(), "reason": reason,
                    "old_items": old_items, "old_total": o.get('total', 0)
                })
                o['items'] = new_items
                new_total = sum((i.get('price', 0) or 0) * i.get('quantity', i.get('qty', 1)) for i in new_items)
                o['total'] = new_total
                # لو طريقة الدفع كانت واحدة (نقدي أو بطاقة بالكامل)، عدّل المبلغ تلقائياً معها
                if o.get('payment') == 'نقدي':
                    o['cash_amount'] = new_total
                elif o.get('payment') == 'بطاقة':
                    o['card_amount'] = new_total
                # لو "مختلط"، نسيب المبالغ متل ما هي - يحتاج مراجعة يدوية من المدير لأنه ما فينا نخمّن التقسيم الجديد
                o['edited'] = True
                save(data); backup()
                return jsonify({"ok": True, "new_total": new_total})
    return jsonify({"ok": False, "error": "الطلب غير موجود"}), 404


def close_shift():
    data = load()
    today = datetime.now().strftime('%Y-%m-%d')
    today_orders = [o for o in data['orders'] if o['timestamp'].startswith(today)]
    total = sum(o.get('total', 0) for o in today_orders)
    shift = {"date": today, "time": datetime.now().isoformat(), "orders": len(today_orders), "total": total}
    data['shifts'].append(shift)
    save(data); backup()
    return jsonify(shift)

@app.route('/api/backup', methods=['POST'])
def force_backup():
    backup()
    return jsonify({"ok": True})

@app.route('/api/backup/download', methods=['GET'])
def download_backup():
    data = load(); stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    export_path = os.path.join(BACKUP_DIR, f'kashir_alqaisar_{stamp}.json')
    with open(export_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return send_file(export_path, as_attachment=True, download_name=f'Kashir_AlQaisar_Backup_{stamp}.json', mimetype='application/json')

@app.route('/api/version', methods=['GET'])
def version():
    return jsonify({"current": CURRENT_VERSION, "check_url": f"{BASE_URL}/version.txt"})

def local_network_addresses():
    """يعيد عناوين IPv4 الخاصة بالشبكة المحلية، دون إرسال أي بيانات للخارج."""
    addresses = []
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = item[4][0]
            if not ip.startswith('127.') and ip not in addresses:
                addresses.append(ip)
    except OSError:
        pass
    return addresses

@app.route('/api/network/info', methods=['GET'])
def network_info():
    port = int(os.environ.get('QAISAR_PORT', '8080'))
    enabled = os.environ.get('QAISAR_LAN') == '1'
    urls = [f'http://{ip}:{port}/mobile.html' for ip in local_network_addresses()] if enabled else []
    return jsonify({'lan_enabled': enabled, 'port': port, 'urls': urls, 'mobile_path': '/mobile.html'})

@app.route('/api/network/qr.svg', methods=['GET'])
def network_qr_svg():
    """رمز QR محلي لفتح بوابة الجوال؛ لا يرسل الرابط أو البيانات إلى أي خدمة خارجية."""
    info = network_info().get_json()
    if not info.get('lan_enabled'):
        return jsonify({'ok': False, 'error': 'فعّل وضع الشبكة المحلية أولًا عبر Start_LAN_Mode.bat'}), 409
    if not info.get('urls'):
        return jsonify({'ok': False, 'error': 'لم يتم العثور على عنوان شبكة محلية. تأكد من اتصال الكمبيوتر بـ Wi‑Fi أو كابل الشبكة.'}), 503
    if not qrcode or not SvgPathImage:
        return jsonify({'ok': False, 'error': 'مولد QR غير متاح في هذه النسخة'}), 503
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=4)
    qr.add_data(info['urls'][0]); qr.make(fit=True)
    image = qr.make_image(image_factory=SvgPathImage)
    out = BytesIO(); image.save(out)
    return Response(out.getvalue(), mimetype='image/svg+xml', headers={'Cache-Control': 'no-store'})

def start_flask():
    # افتراضيًا محلي فقط. فعّل QAISAR_LAN=1 للوصول من الجوالات داخل شبكة المطعم فقط.
    host = '0.0.0.0' if os.environ.get('QAISAR_LAN') == '1' else '127.0.0.1'
    print(' LAN mode:', 'enabled' if host == '0.0.0.0' else 'local only')
    for ip in (local_network_addresses() if host == '0.0.0.0' else []):
        print(f' Mobile URL: http://{ip}:{os.environ.get("QAISAR_PORT", "8080")}/mobile.html')
    app.run(host=host, port=int(os.environ.get('QAISAR_PORT', '8080')), debug=False, threaded=False)





@app.route('/api/reload-menu', methods=['POST'])
def reload_menu():
    """تهيئة المنيو - استيراد المنيو من نسخة الفلاش (data_backup.json) للخزنة المحلية،
    مفيدة لو صار فرق بين الجهاز والفلاش أو أول تشغيل على جهاز جديد."""
    try:
        if os.path.exists(FLASH_BACKUP):
            with open(FLASH_BACKUP, 'r', encoding='utf-8') as f:
                flash_data = json.load(f)
            local_data = load()
            local_data['menu'] = flash_data.get('menu', {})
            save(local_data)
            backup()
            return jsonify({"ok": True, "message": "تم تهيئة المنيو من نسخة الفلاش"})
        return jsonify({"ok": False, "error": "data_backup.json غير موجود بمجلد التطبيق"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)})

@app.route('/api/debts', methods=['GET'])
def get_debts():
    data = load()
    return jsonify(data.get('debts', []))

@app.route('/api/debts', methods=['POST'])
def add_debt():
    data = load()
    if 'debts' not in data:
        data['debts'] = []
    new_id = (max([d['id'] for d in data['debts']], default=0)) + 1
    payload = request.get_json(silent=True) or {}
    try: amount = round(float(payload.get('amount', 0)), 2)
    except (TypeError, ValueError): amount = 0
    if not payload.get('name') or amount <= 0:
        return jsonify({'ok': False, 'error': 'اسم العميل والمبلغ مطلوبان'}), 400
    snap = currency_snapshot(data, payload)
    data['debts'].append({
        'id': new_id, 'name': payload.get('name'), 'amount': amount, 'paid': 0,
        'currency': snap['currency'], 'exchange_rate': snap['exchange_rate'],
        'payments': [], 'note': payload.get('note', ''),
        'date': datetime.now().strftime('%Y-%m-%d')
    })
    save(data)
    backup()
    return jsonify({"ok": True, "id": new_id})

@app.route('/api/debts/<int:did>', methods=['PUT'])
def update_debt(did):
    data = load()
    for d in data.get('debts', []):
        if d['id'] == did:
            payload = request.get_json(silent=True) or {}
            d['name'] = payload.get('name', d['name'])
            try: new_amount = round(float(payload.get('amount', d['amount'])), 2)
            except (TypeError, ValueError): new_amount = d['amount']
            if new_amount < (d.get('paid', 0) or 0) or new_amount <= 0:
                return jsonify({'ok': False, 'error': 'المبلغ لا يمكن أن يكون أقل من المدفوع'}), 400
            d['amount'] = new_amount
            d['note'] = payload.get('note', d.get('note', ''))
            save(data); backup()
            return jsonify({"ok": True})
    return jsonify({"ok": False}), 404

@app.route('/api/debts/<int:did>/pay', methods=['POST'])
def pay_debt(did):
    """تسجيل دفعة على دين - تُسجَّل تلقائياً كدخل بالكاشير (تظهر بالمبيعات والتحليلات).
    تدعم اختيار طريقة الدفع (نقدي/بطاقة) بدل تثبيتها نقدي دائماً."""
    data = load()
    for d in data.get('debts', []):
        if d['id'] == did:
            payload = request.get_json(silent=True) or {}
            try: amount = round(float(payload.get('amount', 0)), 2)
            except (TypeError, ValueError): amount = 0
            method = payload.get('method', 'نقدي')
            if method not in ('نقدي', 'بطاقة'):
                method = 'نقدي'
            remaining_before = round(float(d.get('amount', 0)) - float(d.get('paid', 0) or 0), 2)
            if amount <= 0 or amount > remaining_before:
                return jsonify({'ok': False, 'error': 'مبلغ الدفعة غير صالح أو أكبر من المتبقي'}), 400
            d['paid'] = round(d.get('paid', 0) + amount, 2)
            snap = currency_snapshot(data, d)
            payment = {'amount': amount, 'method': method, 'date': datetime.now().isoformat(), 'currency': snap['currency'], 'exchange_rate': snap['exchange_rate']}
            d.setdefault('payments', []).append(payment)
            payment_order = {
                'id': next_order_id(data),
                'items': [{'name': f"تسديد دين: {d['name']}", 'price': amount, 'quantity': 1}],
                'total': amount,
                'type': 'تسديد دين',
                'note': d.get('note', ''),
                'payment': method,
                'cash_amount': amount if method == 'نقدي' else 0,
                'card_amount': amount if method == 'بطاقة' else 0,
                'currency': snap['currency'], 'exchange_rate': snap['exchange_rate'],
                'date': datetime.now().isoformat(),
                'timestamp': datetime.now().isoformat()
            }
            data.setdefault('orders', []).append(payment_order)
            save(data); backup()
            return jsonify({"ok": True, "paid": d['paid'], "remaining": d['amount'] - d['paid']})
    return jsonify({"ok": False}), 404

@app.route('/api/debts/<int:did>', methods=['DELETE'])
def delete_debt(did):
    data = load()
    data['debts'] = [d for d in data.get('debts', []) if d['id'] != did]
    save(data)
    backup()
    return jsonify({"ok": True})

@app.route('/api/orders/archive', methods=['POST'])
def archive_orders():
    """أرشفة الطلبات بدل تصفيرها"""
    data = load()
    if 'orders_archive' not in data:
        data['orders_archive'] = []
    shift_id = datetime.now().strftime('%Y%m%d_%H%M')
    for o in data.get('orders', []):
        o['shift_id'] = shift_id
    data['orders_archive'].extend(data['orders'])
    data['orders'] = []
    # تصفير عداد الطلبات
    data['order_counter'] = 0
    data.setdefault('settings', {})['last_order_date'] = datetime.now().strftime('%Y-%m-%d')
    save(data)
    backup()
    return jsonify({"ok": True, "shift_id": shift_id, "next_id": "ORD-0001"})


@app.route('/api/expenses', methods=['GET', 'POST'])
def expenses_api():
    data = load()
    if request.method == 'GET':
        date_from = request.args.get('from', '').strip()
        date_to = request.args.get('to', '').strip()
        rows = data.get('expenses', [])
        if date_from: rows = [x for x in rows if x.get('date', '')[:10] >= date_from]
        if date_to: rows = [x for x in rows if x.get('date', '')[:10] <= date_to]
        return jsonify(rows)
    payload = request.get_json(silent=True) or {}
    try: amount = round(float(payload.get('amount', 0)), 2)
    except (TypeError, ValueError): amount = 0
    if amount <= 0 or not payload.get('note'):
        return jsonify({'ok': False, 'error': 'الوصف والمبلغ مطلوبان'}), 400
    snap = currency_snapshot(data, payload)
    rows = data.setdefault('expenses', [])
    expense = {'id': max([x.get('id', 0) for x in rows if isinstance(x, dict)], default=0) + 1,
               'amount': amount, 'currency': snap['currency'], 'exchange_rate': snap['exchange_rate'],
               'category': payload.get('category', 'عام'), 'note': str(payload.get('note'))[:200],
               'payment': payload.get('payment', 'نقدي'), 'date': payload.get('date') or datetime.now().isoformat(),
               'created_by': session.get('username', 'نظام محلي')}
    rows.append(expense); save(data); backup()
    return jsonify({'ok': True, 'expense': expense})

@app.route('/api/expenses/<int:eid>', methods=['DELETE'])
def delete_expense(eid):
    data = load(); rows = data.get('expenses', [])
    target = next((x for x in rows if x.get('id') == eid and not x.get('material_id')), None)
    if not target: return jsonify({'ok': False, 'error': 'المصروف غير موجود'}), 404
    target['voided'] = True; target['voided_at'] = datetime.now().isoformat(); target['voided_by'] = session.get('username', 'نظام محلي')
    save(data); backup(); return jsonify({'ok': True})

@app.route('/api/employees', methods=['GET'])
def get_employees():
    data = load()
    return jsonify(data.get('employees', []))

@app.route('/api/employees', methods=['POST'])
def add_employee():
    data = load()
    if 'employees' not in data:
        data['employees'] = []
    new_id = (max([e['id'] for e in data['employees']], default=0)) + 1
    advance = request.json.get('advance', 0)
    data['employees'].append({
        'id': new_id,
        'name': request.json.get('name'),
        'salary': request.json.get('salary'),
        'advance': advance,
        'start_date': request.json.get('start_date', datetime.now().strftime('%Y-%m-%d'))
    })
    # السلفة تُخصم فوراً من الكاشير كمصروف
    if advance:
        data.setdefault('expenses', []).append({
            'employee_id': new_id, 'amount': advance,
            'date': datetime.now().isoformat(), 'note': f"سلفة موظف: {request.json.get('name')}"
        })
    save(data)
    backup()
    return jsonify({"ok": True, "id": new_id})

@app.route('/api/employees/<int:eid>', methods=['PUT'])
def update_employee(eid):
    data = load()
    for e in data.get('employees', []):
        if e['id'] == eid:
            e['name'] = request.json.get('name', e['name'])
            e['salary'] = request.json.get('salary', e['salary'])
            e['advance'] = request.json.get('advance', e['advance'])
            save(data); backup()
            return jsonify({"ok": True})
    return jsonify({"ok": False}), 404

@app.route('/api/employees/<int:eid>/pay-salary', methods=['POST'])
def pay_salary(eid):
    """تسجيل دفع راتب فعلي لموظف - يُسجَّل كمصروف بتاريخ اليوم فيخصم من الكاش بالتحليلات.
    قبل هذا التعديل كان الراتب يُخصم تلقائياً من صافي الربح بكل مرة بدون أي دفعة فعلية مسجّلة."""
    data = load()
    emp = next((e for e in data.get('employees', []) if e['id'] == eid), None)
    if not emp:
        return jsonify({"ok": False, "error": "الموظف غير موجود"}), 404
    amount = request.json.get('amount', emp.get('salary', 0))
    data.setdefault('expenses', []).append({
        'employee_id': eid, 'amount': amount,
        'date': datetime.now().isoformat(), 'note': f"دفع راتب: {emp['name']}"
    })
    save(data); backup()
    return jsonify({"ok": True, "amount": amount})

@app.route('/api/employees/<int:eid>', methods=['DELETE'])
def delete_employee(eid):
    """حذف موظف - ترجع السلفة (تُحذف كمصروف مرتبط)"""
    data = load()
    data['employees'] = [e for e in data.get('employees', []) if e['id'] != eid]
    data['expenses'] = [x for x in data.get('expenses', []) if x.get('employee_id') != eid]
    save(data)
    backup()
    return jsonify({"ok": True})


def supplier_summary(data):
    suppliers = data.get('suppliers', [])
    purchases = data.get('materials', [])
    result = []
    for supplier in suppliers:
        sid = supplier.get('id')
        rows = [m for m in purchases if m.get('supplier_id') == sid]
        total = sum(float(m.get('price', 0) or 0) for m in rows)
        paid = sum(float(m.get('paid_amount', m.get('price', 0)) or 0) for m in rows)
        result.append({**supplier, 'purchase_total': total, 'paid_total': paid, 'due_total': max(0, total - paid), 'purchase_count': len(rows)})
    return result


@app.route('/api/suppliers', methods=['GET'])
def get_suppliers():
    data = load()
    return jsonify(supplier_summary(data))


@app.route('/api/suppliers', methods=['POST'])
def add_supplier():
    data = load()
    payload = request.get_json(silent=True) or {}
    name = (payload.get('name') or '').strip()
    if not name:
        return jsonify({'ok': False, 'error': 'اسم المورد مطلوب'}), 400
    suppliers = data.setdefault('suppliers', [])
    if any(s.get('name') == name for s in suppliers):
        return jsonify({'ok': False, 'error': 'المورد موجود مسبقًا'}), 409
    sid = max([s.get('id', 0) for s in suppliers], default=0) + 1
    suppliers.append({'id': sid, 'name': name, 'phone': (payload.get('phone') or '').strip(), 'notes': (payload.get('notes') or '').strip()})
    save(data); backup()
    return jsonify({'ok': True, 'id': sid})


@app.route('/api/suppliers/<int:sid>', methods=['PUT'])
def update_supplier(sid):
    data = load()
    payload = request.get_json(silent=True) or {}
    for supplier in data.get('suppliers', []):
        if supplier.get('id') == sid:
            name = (payload.get('name', supplier.get('name')) or '').strip()
            if not name:
                return jsonify({'ok': False, 'error': 'اسم المورد مطلوب'}), 400
            supplier.update({'name': name, 'phone': (payload.get('phone', supplier.get('phone', '')) or '').strip(), 'notes': (payload.get('notes', supplier.get('notes', '')) or '').strip()})
            save(data); backup()
            return jsonify({'ok': True})
    return jsonify({'ok': False, 'error': 'المورد غير موجود'}), 404


@app.route('/api/suppliers/<int:sid>', methods=['DELETE'])
def delete_supplier(sid):
    data = load()
    if any(m.get('supplier_id') == sid for m in data.get('materials', [])):
        return jsonify({'ok': False, 'error': 'لا يمكن حذف مورد مرتبط بمشتريات سابقة'}), 409
    before = len(data.get('suppliers', []))
    data['suppliers'] = [s for s in data.get('suppliers', []) if s.get('id') != sid]
    if len(data['suppliers']) == before:
        return jsonify({'ok': False, 'error': 'المورد غير موجود'}), 404
    save(data); backup()
    return jsonify({'ok': True})


@app.route('/api/suppliers/summary', methods=['GET'])
def get_supplier_summary():
    data = load()
    rows = supplier_summary(data)
    return jsonify({'ok': True, 'suppliers': rows, 'total_due': sum(x['due_total'] for x in rows), 'total_purchases': sum(x['purchase_total'] for x in rows)})


@app.route('/api/materials', methods=['GET'])
def get_materials():
    data = load()
    return jsonify(data.get('materials', []))

def sync_inventory_add(data, name, unit, qty):
    """يضيف كمية لرصيد المخزون (يبحث بنفس الاسم، وإلا ينشئ مادة جديدة بالمخزون).
    يُستدعى تلقائياً مع كل عملية شراء مادة خام."""
    name = (name or '').strip()
    if not name:
        return
    inv = data.setdefault('inventory', [])
    for item in inv:
        if item['name'] == name:
            item['stock'] = item.get('stock', 0) + (qty or 0)
            if unit and not item.get('unit'):
                item['unit'] = unit
            return
    new_id = (max([i['id'] for i in inv], default=0)) + 1
    inv.append({'id': new_id, 'name': name, 'unit': unit or '', 'stock': qty or 0, 'low_stock_threshold': 0})

def sync_inventory_consume(data, name, qty):
    """يخصم كمية من رصيد المخزون (تُستدعى عند بيع منتج له وصفة مرتبطة بهذه المادة)."""
    name = (name or '').strip()
    if not name:
        return
    for item in data.get('inventory', []):
        if item['name'] == name:
            item['stock'] = item.get('stock', 0) - (qty or 0)
            return

@app.route('/api/materials', methods=['POST'])
def add_material():
    """شراء مادة خام - تُسجَّل تلقائياً كمصروف يخصم من صافي الربح بالتحليلات، وتُضاف كمّيتها لرصيد المخزون"""
    data = load()
    if 'materials' not in data:
        data['materials'] = []
    new_id = (max([m['id'] for m in data['materials']], default=0)) + 1
    payload = request.get_json(silent=True) or {}
    supplier_id = payload.get('supplier_id')
    try:
        supplier_id = int(supplier_id) if supplier_id not in (None, '', 0, '0') else None
    except (TypeError, ValueError):
        supplier_id = None
    material = {
        'id': new_id,
        'name': payload.get('name', ''),
        'quantity': payload.get('quantity', 0),
        'unit': payload.get('unit', ''),
        'price': payload.get('price', 0),
        'paid_amount': payload.get('paid_amount', payload.get('price', 0)),
        'supplier_id': supplier_id,
        'invoice_no': (payload.get('invoice_no') or '').strip(),
        'notes': (payload.get('notes') or '').strip()
    }
    data['materials'].append(material)
    data.setdefault('expenses', []).append({
        'material_id': new_id, 'amount': material['price'],
        'date': datetime.now().isoformat(), 'note': f"شراء مادة: {material['name']}",
        'supplier_id': supplier_id, 'paid_amount': material['paid_amount'], 'invoice_no': material['invoice_no']
    })
    sync_inventory_add(data, material['name'], material['unit'], material['quantity'])
    save(data); backup()
    return jsonify({"ok": True, "id": new_id})

@app.route('/api/materials/<int:mid>', methods=['PUT'])
def update_material(mid):
    data = load()
    for m in data.get('materials', []):
        if m['id'] == mid:
            old_qty = m.get('quantity', 0)
            old_name = m.get('name', '')
            m['name'] = request.json.get('name', m['name'])
            m['quantity'] = request.json.get('quantity', m['quantity'])
            m['unit'] = request.json.get('unit', m['unit'])
            m['price'] = request.json.get('price', m['price'])
            # مزامنة المصروف المرتبط بهذه المادة
            for e in data.get('expenses', []):
                if e.get('material_id') == mid:
                    e['amount'] = m['price']
            # مزامنة رصيد المخزون: تراجع عن الكمية القديمة وأضف الجديدة (كانت هذي العملية معطّلة بالكامل سابقاً)
            sync_inventory_consume(data, old_name, old_qty)
            sync_inventory_add(data, m['name'], m['unit'], m['quantity'])
            save(data); backup()
            return jsonify({"ok": True})
    return jsonify({"ok": False}), 404

@app.route('/api/materials/<int:mid>', methods=['DELETE'])
def delete_material(mid):
    """حذف مادة - يرجع مبلغها للجرد (يحذف المصروف المرتبط) ويرجع كمّيتها من رصيد المخزون"""
    data = load()
    target = next((m for m in data.get('materials', []) if m['id'] == mid), None)
    if target:
        sync_inventory_consume(data, target.get('name', ''), target.get('quantity', 0))
    data['materials'] = [m for m in data.get('materials', []) if m['id'] != mid]
    data['expenses'] = [e for e in data.get('expenses', []) if e.get('material_id') != mid]
    save(data); backup()
    return jsonify({"ok": True})


def inventory_alerts(data):
    """يعيد المواد النافدة أو الواقعة تحت حد التنبيه مع حالة مفهومة للواجهة."""
    alerts = []
    for item in data.get('inventory', []):
        stock = item.get('stock', 0) or 0
        threshold = item.get('low_stock_threshold', 0) or 0
        status = 'out' if stock <= 0 else ('low' if threshold > 0 and stock <= threshold else 'ok')
        item['status'] = status
        item['low'] = status in ('out', 'low')
        if status != 'ok':
            alerts.append({
                'id': item.get('id'), 'name': item.get('name', ''),
                'stock': stock, 'unit': item.get('unit', ''),
                'threshold': threshold, 'status': status
            })
    return alerts


@app.route('/api/inventory', methods=['GET'])
def get_inventory():
    """رصيد المخزون الحالي لكل مادة خام مع حالة النفاد أو الانخفاض."""
    data = load()
    inventory_alerts(data)
    return jsonify(data.get('inventory', []))


@app.route('/api/inventory/alerts', methods=['GET'])
def get_inventory_alerts():
    """تنبيهات المواد النافدة أو التي وصلت إلى حد إعادة الطلب."""
    data = load()
    alerts = inventory_alerts(data)
    return jsonify({
        'ok': True,
        'alerts': alerts,
        'out_of_stock': sum(1 for x in alerts if x['status'] == 'out'),
        'low_stock': sum(1 for x in alerts if x['status'] == 'low'),
        'count': len(alerts)
    })

@app.route('/api/inventory/<int:iid>/adjust', methods=['POST'])
def adjust_inventory(iid):
    """تصحيح يدوي لرصيد مادة (جرد فعلي، هدر، تلف...) - يُسجَّل كمصروف إذا كان هدر بسعر معروف"""
    data = load()
    for item in data.get('inventory', []):
        if item['id'] == iid:
            new_stock = request.json.get('stock')
            if new_stock is not None:
                item['stock'] = new_stock
            save(data); backup()
            return jsonify({"ok": True})
    return jsonify({"ok": False}), 404

@app.route('/api/inventory/<int:iid>/threshold', methods=['POST'])
def set_inventory_threshold(iid):
    """تحديد الحد الأدنى الذي يظهر عنده تنبيه نفاد مخزون"""
    data = load()
    for item in data.get('inventory', []):
        if item['id'] == iid:
            item['low_stock_threshold'] = request.json.get('threshold', 0)
            save(data); backup()
            return jsonify({"ok": True})
    return jsonify({"ok": False}), 404


@app.route('/api/analytics/categories', methods=['GET'])
def analytics_categories():
    """قائمة الأقسام لتعبئة فلتر التقرير التفصيلي - كانت الواجهة تناديها بدون ما تكون موجودة أصلاً"""
    data = load()
    return jsonify(list(data.get('menu', {}).keys()))

@app.route('/api/analytics/products', methods=['GET'])
def analytics_products():
    """قائمة المنتجات (بقسم معيّن أو كلها) لتعبئة فلتر التقرير التفصيلي - نفس المشكلة، ما كانت موجودة"""
    data = load()
    category = request.args.get('category', '').strip()
    names = []
    for cat, items in data.get('menu', {}).items():
        if category and cat != category:
            continue
        for it in items:
            names.append(it['name'])
    return jsonify(names)

@app.route('/api/analytics', methods=['GET'])
def get_analytics():
    """الجرد المطور - يدعم يومي/شهري/سنوي بالإضافة لتقرير تفصيلي بنطاق تاريخ + قسم + منتج محدد"""
    data = load()
    period = request.args.get('period', 'daily')
    category_filter = request.args.get('category', '').strip()
    product_filter = request.args.get('product', '').strip()
    date_from = request.args.get('from', '').strip()
    date_to = request.args.get('to', '').strip()

    # فلترة الطلبات حسب الفترة
    now = datetime.now()
    all_orders = [o for o in data.get('orders', []) + data.get('orders_archive', []) if not o.get('voided')]

    if period == 'daily':
        orders = [o for o in all_orders if o.get('timestamp', '').startswith(now.strftime('%Y-%m-%d'))]
    elif period == 'monthly':
        orders = [o for o in all_orders if o.get('timestamp', '').startswith(now.strftime('%Y-%m'))]
    elif period == 'yearly':
        orders = [o for o in all_orders if o.get('timestamp', '').startswith(now.strftime('%Y'))]
    elif period == 'custom':
        orders = all_orders
        if date_from:
            orders = [o for o in orders if o.get('timestamp', '')[:10] >= date_from]
        if date_to:
            orders = [o for o in orders if o.get('timestamp', '')[:10] <= date_to]
    else:
        orders = all_orders

    # خريطة منتج -> قسمه (من قائمة الطعام الحالية) لدعم فلتر القسم
    item_category = {}
    for cat, items in data.get('menu', {}).items():
        for it in items:
            item_category[it.get('name', '')] = cat

    # تفصيل مبيعات كل صنف (الكمية + الإجمالي + توزيع حسب التاريخ) عبر كل الطلبات المفلترة بالفترة
    item_sales = {}
    for o in orders:
        odate = o.get('timestamp', '')[:10]
        for i in o.get('items', []):
            name = i.get('name', '')
            qty = i.get('quantity', i.get('qty', 1))
            price = i.get('price', 0)
            entry = item_sales.setdefault(name, {'quantity': 0, 'total': 0, 'dates': {}})
            entry['quantity'] += qty
            entry['total'] += qty * price
            entry['dates'][odate] = entry['dates'].get(odate, 0) + qty

    # تضييق النتائج حسب فلتر القسم/المنتج المختار بالتقرير التفصيلي
    filtered_items = item_sales
    if category_filter or product_filter:
        filtered_items = {}
        for name, entry in item_sales.items():
            if product_filter and name != product_filter:
                continue
            if category_filter and item_category.get(name) != category_filter:
                continue
            filtered_items[name] = entry

    product_sales = [
        {'name': n, 'quantity': e['quantity'], 'total': e['total'], 'dates': e['dates']}
        for n, e in filtered_items.items()
    ]

    # عندما يكون هناك فلتر قسم/منتج، المبيعات والطلبات تُحسب على مستوى الصنف المطابق فقط
    # (مو إجمالي الطلب كامل، لأنه ممكن يحوي أصناف من أقسام تانية)
    if category_filter or product_filter:
        total_sales = sum(e['total'] for e in filtered_items.values())
        total_orders = sum(
            1 for o in orders
            if any(i.get('name', '') in filtered_items for i in o.get('items', []))
        )
    else:
        total_sales = sum(o.get('total', 0) for o in orders)
        total_orders = len(orders)

    # 1. متوسط قيمة الطلب
    avg_order = total_sales / total_orders if total_orders > 0 else 0

    # 2. نسبة/عدد كل نوع طلب
    type_stats = {'سفري': 0, 'صالة': 0, 'ديليفري': 0}
    for o in orders:
        t = o.get('type', 'سفري')
        type_stats[t] = type_stats.get(t, 0) + 1
    type_pct = {k: round(v/total_orders*100, 1) if total_orders > 0 else 0 for k, v in type_stats.items()}

    # 3. أداء الموظفين
    cashier_stats = {}
    for o in orders:
        c = o.get('cashier_name', 'غير معروف')
        if c not in cashier_stats:
            cashier_stats[c] = {'orders': 0, 'sales': 0}
        cashier_stats[c]['orders'] += 1
        cashier_stats[c]['sales'] += o.get('total', 0)

    # 4. صافي الربح
    # المصاريف (سلف الموظفين + شراء المواد الخام) تُصفّى حسب نفس الفترة المختارة تماماً مثل المبيعات،
    # بدل حسابها كاملة دائماً بغض النظر عن الفترة (كان هذا يُنتج صافي ربح خاطئ لليومي/الشهري).
    all_expenses = data.get('expenses', [])
    if period == 'daily':
        period_expenses = [e for e in all_expenses if e.get('date', '').startswith(now.strftime('%Y-%m-%d'))]
    elif period == 'monthly':
        period_expenses = [e for e in all_expenses if e.get('date', '').startswith(now.strftime('%Y-%m'))]
    elif period == 'yearly':
        period_expenses = [e for e in all_expenses if e.get('date', '').startswith(now.strftime('%Y'))]
    elif period == 'custom':
        period_expenses = all_expenses
        if date_from:
            period_expenses = [e for e in period_expenses if e.get('date', '')[:10] >= date_from]
        if date_to:
            period_expenses = [e for e in period_expenses if e.get('date', '')[:10] <= date_to]
    else:
        period_expenses = all_expenses
    total_expenses = sum(e.get('amount', 0) for e in period_expenses)

    # فصل مشتريات المواد عن المصروفات التشغيلية حتى لا تختلط تكلفة المخزون مع الربح التشغيلي.
    purchase_expenses = [e for e in period_expenses if e.get('material_id') is not None]
    purchases_total = sum(e.get('amount', 0) or 0 for e in purchase_expenses)
    purchases_paid = sum(e.get('paid_amount', e.get('amount', 0)) or 0 for e in purchase_expenses)
    other_expenses = total_expenses - purchases_total

    # الرواتب: راتب شهري ثابت، فلا تُخصم بالكامل من تحليل يوم واحد فقط.
    single_day = period == 'daily' or (period == 'custom' and date_from and date_to and date_from == date_to)
    total_salaries = 0 if single_day else sum(e.get('salary', 0) for e in data.get('employees', []))

    # تكلفة البضاعة المباعة: تعتمد على الوصفات ومتوسط سعر شراء المواد، وتُحسب فقط للأصناف ذات التكلفة المعروفة.
    products_by_name = {p.get('name', ''): p for items in data.get('menu', {}).values() for p in items}
    cost_of_goods_sold = 0
    uncosted_products = []
    for name, entry in filtered_items.items():
        product = products_by_name.get(name)
        unit_cost = compute_product_cost(data, product) if product else None
        if unit_cost is None:
            uncosted_products.append(name)
        else:
            cost_of_goods_sold += unit_cost * (entry.get('quantity', 0) or 0)
    gross_profit = total_sales - cost_of_goods_sold
    gross_margin_pct = round((gross_profit / total_sales * 100), 1) if total_sales else 0
    operating_profit = gross_profit - other_expenses - total_salaries
    cash_flow_after_purchases = total_sales - total_expenses - total_salaries
    inventory_value = sum((item.get('stock', 0) or 0) * (material_avg_cost(data, item.get('name', '')) or 0) for item in data.get('inventory', []))
    supplier_rows = supplier_summary(data)
    supplier_due = sum(row.get('due_total', 0) or 0 for row in supplier_rows)
    net_profit = operating_profit

    # 5. الديون المتراكمة (المتبقي غير المسدد فقط، وليس المبلغ الأصلي الكامل)
    total_debts = sum(d.get('amount', 0) - d.get('paid', 0) for d in data.get('debts', []))

    # تفصيل الكاش الفعلي مقابل البطاقة (مهم لجرد الكاش بالدرج مقابل ما يذهب للبنك مباشرة).
    # الطلبات القديمة قبل هذا التحديث ما فيها cash_amount/card_amount فبنرجع لتخمين من حقل payment النصي.
    total_cash = 0
    total_card = 0
    for o in orders:
        if 'cash_amount' in o or 'card_amount' in o:
            total_cash += o.get('cash_amount', 0) or 0
            total_card += o.get('card_amount', 0) or 0
        else:
            pm = o.get('payment', '')
            amt = o.get('total', 0)
            if pm == 'بطاقة':
                total_card += amt
            else:
                total_cash += amt

    # تفاصيل الفواتير: تبقى على مستوى الفاتورة مع أصنافها، وتُرشّح عند اختيار قسم/منتج.
    order_details = []
    for o in orders:
        detail_items = []
        for i in o.get('items', []):
            name = i.get('name', '')
            if product_filter and name != product_filter:
                continue
            if category_filter and item_category.get(name) != category_filter:
                continue
            qty = i.get('quantity', i.get('qty', 1)) or 0
            price = i.get('price', 0) or 0
            detail_items.append({'name': name, 'quantity': qty, 'price': price, 'total': qty * price})
        if not detail_items:
            continue
        original_subtotal = o.get('subtotal')
        if original_subtotal is None:
            original_subtotal = sum((i.get('price', 0) or 0) * (i.get('quantity', i.get('qty', 1)) or 0) for i in o.get('items', []))
        original_total = o.get('total', 0) or 0
        discount_amount = o.get('discount_amount')
        if discount_amount is None:
            discount_amount = max(0, (original_subtotal or 0) - original_total)
        filtered_subtotal = sum(i['total'] for i in detail_items)
        if category_filter or product_filter:
            ratio = (filtered_subtotal / original_subtotal) if original_subtotal else 0
            detail_total = max(0, filtered_subtotal - (discount_amount * ratio))
        else:
            detail_total = original_total
        order_details.append({
            'id': o.get('id', ''),
            'date': o.get('timestamp') or o.get('date', ''),
            'type': o.get('type', 'سفري'),
            'payment': o.get('payment', '') or 'غير محدد',
            'cash_amount': o.get('cash_amount', 0) or 0,
            'card_amount': o.get('card_amount', 0) or 0,
            'customer': o.get('customer', ''),
            'table': o.get('table', ''),
            'cashier_name': o.get('cashier_name', 'غير معروف'),
            'subtotal': round(filtered_subtotal, 2),
            'discount': round(discount_amount if not (category_filter or product_filter) else discount_amount * (filtered_subtotal / original_subtotal if original_subtotal else 0), 2),
            'total': round(detail_total, 2),
            'voided': bool(o.get('voided')),
            'items': detail_items
        })

    # 6/7. أكثر وأقل الأصناف مبيعاً (من كامل الأصناف بالفترة، بدون تأثر بفلتر القسم/المنتج)
    qty_by_item = {n: e['quantity'] for n, e in item_sales.items()}
    slow_items = sorted(qty_by_item.items(), key=lambda x: x[1])[:5]
    top_items = sorted(qty_by_item.items(), key=lambda x: x[1], reverse=True)[:5]

    return jsonify({
        "period": period,
        "total_sales": total_sales,
        "total_orders": total_orders,
        "avg_order": round(avg_order, 2),
        "types": type_stats,
        "type_pct": type_pct,
        "cashier_stats": cashier_stats,
        "total_expenses": total_expenses,
        "total_salaries": total_salaries,
        "purchases_total": purchases_total,
        "purchases_paid": purchases_paid,
        "supplier_due": supplier_due,
        "other_expenses": other_expenses,
        "inventory_value": round(inventory_value, 2),
        "cost_of_goods_sold": round(cost_of_goods_sold, 2),
        "gross_profit": round(gross_profit, 2),
        "gross_margin_pct": gross_margin_pct,
        "operating_profit": round(operating_profit, 2),
        "cash_flow_after_purchases": round(cash_flow_after_purchases, 2),
        "uncosted_products": uncosted_products,
        "net_profit": net_profit,
        "total_debts": total_debts,
        "total_cash": total_cash,
        "total_card": total_card,
        "product_sales": product_sales,
        "order_details": order_details,
        "slow_items": slow_items,
        "top_items": top_items
    })


@app.route('/api/settings/currency', methods=['POST'])
def set_currency():
    """يحدّث عملة العرض العامة بصورة موثوقة من حساب مدير أو مشرف فقط.

    لا تُعاد كتابة عملات الفواتير أو الديون التاريخية؛ كل عملية تحتفظ بلقطة
    عملتها وسعر صرفها، أما الإعداد هنا فيحدد فقط عملة العرض والعمليات الجديدة.
    """
    if not has_role('manager', 'supervisor'):
        return permission_error()
    payload = request.get_json(silent=True) or {}
    currency = payload.get('currency', 'SYP')
    if currency not in ('SYP', 'USD', 'EUR'):
        return jsonify({'ok': False, 'error': 'العملة المختارة غير مدعومة'}), 400

    def valid_rate(value, fallback):
        try:
            rate = float(value if value is not None else fallback)
            return rate if rate >= 0 else fallback
        except (TypeError, ValueError):
            return fallback

    data = load()
    settings = data.setdefault('settings', {})
    settings['currency'] = currency
    settings['usd_rate'] = valid_rate(payload.get('usd_rate'), settings.get('usd_rate', 0))
    settings['eur_rate'] = valid_rate(payload.get('eur_rate'), settings.get('eur_rate', 0))
    settings['currency_updated_at'] = datetime.now().isoformat()
    settings['currency_updated_by'] = session.get('username', '')
    save(data)
    return jsonify({
        'ok': True,
        'currency': settings['currency'],
        'usd_rate': settings['usd_rate'],
        'eur_rate': settings['eur_rate'],
        'updated_at': settings['currency_updated_at']
    })

@app.route('/api/settings/currency', methods=['GET'])
def get_currency():
    data = load()
    settings = data.get('settings', {})
    currency = settings.get('currency', 'SYP')
    if currency not in ('SYP', 'USD', 'EUR'):
        currency = 'SYP'
    return jsonify({
        'currency': currency,
        'usd_rate': settings.get('usd_rate', 0),
        'eur_rate': settings.get('eur_rate', 0),
        'updated_at': settings.get('currency_updated_at', '')
    })


def is_vendor_master(data=None):
    """فقط النسخة الأصلية المعلمة صراحة تستطيع توليد نسخ عملاء."""
    data = data or load()
    return bool(data.get('settings', {}).get('commercial', {}).get('vendor_master'))

@app.route('/api/commercial/status', methods=['GET'])
def commercial_status():
    return jsonify({'can_generate_client_copies': is_vendor_master()})

def sanitize_client_data(data, restaurant_name, license_id):
    """تنظيف بيانات التشغيل من قالب التسليم مع إبقاء المنيو وتهيئة معالج العميل."""
    settings = data.setdefault('settings', {})
    settings['restaurant'] = {}
    settings['users'] = []
    settings['commercial'] = {'setup_completed': False, 'template': True, 'vendor_master': False,
                              'template_restaurant_name': restaurant_name,
                              'preset_license_id': license_id}
    for key in ('orders', 'orders_archive', 'debts', 'customers', 'expenses', 'audit_log', 'shifts', 'gift_cards', 'sync_queue'):
        data[key] = []
    tables = data.get('tables', [])
    if isinstance(tables, dict): tables = list(tables.values())
    if not isinstance(tables, list): tables = []
    for table in tables:
        if isinstance(table, dict):
            table['status'] = 'free'; table.pop('order_id', None)
    data['tables'] = tables
    return data

def commercial_copy_ignore(directory, names):
    ignored = set()
    for name in names:
        low = name.lower()
        if low in {'__pycache__', 'data_vault', 'deliveries'} or low.endswith(('.pyc', '.log')) or low.startswith(('qa_', 'acceptance_')):
            ignored.add(name)
        if low.endswith('.zip') and ('kashir' in low or 'qaisar' in low):
            ignored.add(name)
    return ignored

@app.route('/api/commercial/create-client-copy', methods=['POST'])
def create_client_copy():
    if not has_role('manager'):
        return permission_error()
    if not is_vendor_master():
        return jsonify({'ok': False, 'error': 'إنشاء نسخ المطاعم متاح للنسخة الأصلية للبائع فقط'}), 403
    payload = request.get_json(silent=True) or {}
    restaurant_name = str(payload.get('restaurant_name', '')).strip()
    owner_name = str(payload.get('owner_name', '')).strip()
    license_id = str(payload.get('license_id', '')).strip() or ('QAISAR-' + uuid.uuid4().hex[:10].upper())
    folder = re.sub(r'[^A-Za-z0-9_-]+', '_', str(payload.get('folder_name', '')).strip())[:60].strip('_')
    if not restaurant_name or not folder:
        return jsonify({'ok': False, 'error': 'اسم المطعم واسم مجلد التسليم مطلوبان'}), 400
    source_root = os.path.dirname(BASE_DIR)
    deliveries = os.path.join(source_root, 'Deliveries')
    target = os.path.abspath(os.path.join(deliveries, folder))
    if os.path.commonpath([target, os.path.abspath(deliveries)]) != os.path.abspath(deliveries):
        return jsonify({'ok': False, 'error': 'اسم مجلد التسليم غير صالح'}), 400
    if os.path.exists(target) or os.path.exists(target + '.zip'):
        return jsonify({'ok': False, 'error': 'يوجد مجلد أو ZIP بهذا الاسم؛ اختر اسمًا مختلفًا'}), 409
    tmp = target + '.creating'
    try:
        os.makedirs(deliveries, exist_ok=True)
        shutil.copytree(source_root, tmp, ignore=commercial_copy_ignore)
        for filename in ('data_backup.json', 'factory_data.json'):
            path = os.path.join(tmp, 'app', filename)
            with open(path, encoding='utf-8') as f: client_data = json.load(f)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(sanitize_client_data(client_data, restaurant_name, license_id), f, ensure_ascii=False, indent=2)
        with open(os.path.join(tmp, 'CLIENT_SETUP.txt'), 'w', encoding='utf-8') as f:
            f.write(f'نسخة مستقلة للمطعم: {restaurant_name}\\nالمالك: {owner_name}\\nرقم الترخيص: {license_id}\\n\\n1. شغّل app\\\\QaisarDesktop.exe.\\n2. أكمل الإعداد الأولي وأنشئ المدير.\\n3. لا تنسخ بيانات هذه النسخة إلى مطعم آخر.\\n')
        os.replace(tmp, target)
        zip_path = shutil.make_archive(target, 'zip', deliveries, folder)
        return jsonify({'ok': True, 'folder': target, 'zip': zip_path, 'license_id': license_id,
                        'message': 'تم إنشاء نسخة مستقلة وZIP نظيفين للمطعم'})
    except Exception as exc:
        shutil.rmtree(tmp, ignore_errors=True)
        return jsonify({'ok': False, 'error': f'تعذر إنشاء النسخة: {exc}'}), 500

@app.route('/api/settings/restaurant', methods=['GET'])
def get_restaurant():
    data = load()
    r = data.get('settings', {}).get('restaurant', {})
    return jsonify({"name": r.get('name', ''), "phone": r.get('phone', ''), "address": r.get('address', '')})

@app.route('/api/settings/restaurant', methods=['POST'])
def set_restaurant():
    data = load()
    if 'settings' not in data:
        data['settings'] = {}
    existing = data['settings'].get('restaurant', {})
    data['settings']['restaurant'] = {
        'name': request.json.get('name', existing.get('name', '')),
        'phone': request.json.get('phone', existing.get('phone', '')),
        'address': request.json.get('address', existing.get('address', ''))
    }
    save(data)
    return jsonify({"ok": True})

@app.route('/api/restaurant/name', methods=['GET'])
def get_restaurant_name():
    """يُستخدم من شاشة الكاشير لعرض اسم المطعم بالهيدر"""
    data = load()
    r = data.get('settings', {}).get('restaurant', {})
    return jsonify({"name": r.get('name', '')})


@app.route('/api/settings/support-info', methods=['GET'])
def get_support_info():
    """معلومات الدعم الفني (بيانات المطوّر) - تُعرض بشاشة الترحيب حتى صاحب المطعم يعرف مين يتواصل معه لو صار عنده مشكلة."""
    data = load()
    s = data.get('settings', {}).get('support_info', {})
    return jsonify({
        "support_phone": s.get('support_phone', ''),
        "whatsapp": s.get('whatsapp', ''),
        "facebook": s.get('facebook', ''),
        "instagram": s.get('instagram', '')
    })

@app.route('/api/settings/support-info', methods=['POST'])
def set_support_info():
    data = load()
    if 'settings' not in data:
        data['settings'] = {}
    existing = data['settings'].get('support_info', {})
    data['settings']['support_info'] = {
        'support_phone': request.json.get('support_phone', existing.get('support_phone', '')),
        'whatsapp': request.json.get('whatsapp', existing.get('whatsapp', '')),
        'facebook': request.json.get('facebook', existing.get('facebook', '')),
        'instagram': request.json.get('instagram', existing.get('instagram', ''))
    }
    save(data)
    return jsonify({"ok": True})


def list_windows_printers():
    """يرجّع أسماء الطابعات المثبتة بويندوز عن طريق PowerShell - بدون أي مكتبة خارجية إضافية
    (يعمل فقط عند التشغيل الفعلي على ويندوز، وليس أثناء التطوير بترمكس/لينكس)."""
    try:
        result = subprocess.run(
            ['powershell', '-NoProfile', '-Command', 'Get-Printer | Select-Object -ExpandProperty Name'],
            capture_output=True, text=True, timeout=8
        )
        return [n.strip() for n in result.stdout.splitlines() if n.strip()]
    except Exception:
        return []

def get_default_windows_printer():
    try:
        result = subprocess.run(
            ['powershell', '-NoProfile', '-Command',
             '(Get-CimInstance -Query "SELECT * FROM Win32_Printer WHERE Default=TRUE").Name'],
            capture_output=True, text=True, timeout=8
        )
        return result.stdout.strip()
    except Exception:
        return ""

def set_default_windows_printer(name):
    """يعيّن الطابعة الافتراضية بويندوز عن طريق أداة printui.dll المدمجة بويندوز (بدون تثبيت أي شيء إضافي)."""
    try:
        subprocess.run(['rundll32', 'printui.dll,PrintUIEntry', '/y', '/n', name], timeout=8, check=True)
        return True
    except Exception:
        return False

def print_text_to_printer(printer_name, text):
    """يرسل نص خام مباشرة لطابعة محددة عن طريق PowerShell (Out-Printer).
    ملاحظة مهمة: هذا المسار مفيد للتأكد من الاتصال بالطابعة (اختبار)، لكنه لا يضمن ترتيب صحيح
    للنص العربي (RTL) على كل طابعة لأنه طباعة نصية خام بدون محرك رسم. الفواتير الفعلية بالكاشير
    تستمر تُطبع عن طريق نافذة المتصفح (HTML) لأنها ترندر العربي صح، وهذا فقط للفحص السريع."""
    try:
        tmp_path = os.path.join(VAULT_DIR, '_print_test.txt')
        with open(tmp_path, 'w', encoding='utf-8') as f:
            f.write(text)
        cmd = f'Get-Content -Path "{tmp_path}" -Encoding UTF8 | Out-Printer -Name "{printer_name}"'
        subprocess.run(['powershell', '-NoProfile', '-Command', cmd], timeout=10, check=True)
        return True
    except Exception:
        return False


@app.route('/api/printer/list', methods=['GET'])
def list_printers_route():
    """اكتشاف الطابعات المتصلة بويندوز مباشرة من صفحة الإعدادات - بدون أي تعديل بالكود."""
    if sys.platform != 'win32':
        return jsonify({"ok": False, "printers": [], "default": "", "error": "هذه الميزة تعمل فقط عند التشغيل الفعلي على ويندوز"})
    return jsonify({"ok": True, "printers": list_windows_printers(), "default": get_default_windows_printer()})

@app.route('/api/printer/select', methods=['POST'])
def select_printer_route():
    """تعيين طابعة كطابعة افتراضية بويندوز + حفظ اسمها بإعدادات النظام."""
    name = (request.json.get('name') or '').strip()
    if not name:
        return jsonify({"ok": False, "error": "اسم الطابعة فارغ"})
    data = load()
    data.setdefault('settings', {}).setdefault('printer', {})['printer_name'] = name
    save(data)
    if sys.platform == 'win32':
        if not set_default_windows_printer(name):
            return jsonify({"ok": False, "error": "تم حفظ الاسم بالإعدادات، لكن تعذر تعيينها كطابعة افتراضية بويندوز"})
    return jsonify({"ok": True})

@app.route('/api/printer/settings', methods=['GET'])
def get_printer_settings():
    data = load()
    p = data.get('settings', {}).get('printer', {})
    return jsonify({
        "paper_width": p.get('paper_width', 80),
        "font_size": p.get('font_size', 'medium'),
        "copies": p.get('copies', 1),
        "footer_text": p.get('footer_text', ''),
        "printer_name": p.get('printer_name', '')
    })

@app.route('/api/printer/settings', methods=['POST'])
def set_printer_settings():
    data = load()
    if 'settings' not in data:
        data['settings'] = {}
    existing = data['settings'].get('printer', {})
    data['settings']['printer'] = {
        'paper_width': request.json.get('paper_width', 80),
        'font_size': request.json.get('font_size', 'medium'),
        'copies': request.json.get('copies', 1),
        'footer_text': request.json.get('footer_text', ''),
        'printer_name': request.json.get('printer_name', existing.get('printer_name', ''))
    }
    save(data)
    return jsonify({"ok": True})

@app.route('/api/printer/test', methods=['POST'])
def test_printer():
    """طباعة تجريبية فعلية: ترسل صفحة اختبار حقيقية للطابعة المختارة وتتأكد من نجاح الاتصال،
    بدل الرد بنجاح وهمي دائماً بغض النظر عن وجود طابعة أصلاً."""
    if sys.platform != 'win32':
        return jsonify({"ok": True, "message": "تشغيل تجريبي (بيئة غير ويندوز) - الاختبار الفعلي متاح فقط عند التشغيل على ويندوز"})
    data = load()
    printer_name = data.get('settings', {}).get('printer', {}).get('printer_name') or get_default_windows_printer()
    if not printer_name:
        return jsonify({"ok": False, "message": "ما في طابعة محددة بعد - اختر طابعة من الإعدادات أولاً"})
    restaurant = data.get('settings', {}).get('restaurant', {}).get('name', 'كاشير القيصر')
    test_text = f"{restaurant}\n{'-'*32}\nPRINTER TEST / طباعة تجريبية\n{datetime.now().strftime('%Y-%m-%d %H:%M')}\n{'-'*32}\nOK\n\n\n"
    ok = print_text_to_printer(printer_name, test_text)
    msg = f"تم إرسال طباعة تجريبية إلى: {printer_name}" if ok else f"تعذر الإرسال للطابعة: {printer_name} - تأكد أنها متصلة وشغالة"
    return jsonify({"ok": ok, "message": msg})


@app.route('/api/settings/users', methods=['GET'])
def get_users():
    # تُستخدم أسماء المستخدمين والأدوار فقط في شاشة اختيار الحساب؛ لا تُرسل كلمة مرور أو تجزئة.
    data = load()
    users = data.get('settings', {}).get('users', [])
    safe = [{"id": u['id'], "username": u['username'], "role": u.get('role', 'cashier')} for u in users]
    return jsonify(safe)

@app.route('/api/settings/users', methods=['POST'])
def add_user():
    if not has_role('manager'):
        return permission_error()
    data = load()
    if 'settings' not in data:
        data['settings'] = {}
    if 'users' not in data['settings']:
        data['settings']['users'] = []
    payload = request.get_json(silent=True) or {}
    username = (payload.get('username') or '').strip()
    password = payload.get('password') or ''
    role = payload.get('role', 'cashier')
    if not username or not password:
        return jsonify({'ok': False, 'error': 'اسم المستخدم وكلمة المرور مطلوبان'}), 400
    if role not in ROLE_LABELS:
        return jsonify({'ok': False, 'error': 'المستوى الوظيفي غير صالح'}), 400
    if any(u.get('username') == username for u in data['settings']['users']):
        return jsonify({'ok': False, 'error': 'اسم المستخدم موجود مسبقًا'}), 409
    new_id = (max([u['id'] for u in data['settings']['users']], default=0)) + 1
    data['settings']['users'].append({
        'id': new_id,
        'username': username,
        'password_hash': hash_password(password),
        'role': role
    })
    save(data)
    return jsonify({"ok": True, "id": new_id})

@app.route('/api/settings/users/<int:uid>', methods=['PUT'])
def update_user(uid):
    if not has_role('manager'):
        return permission_error()
    data = load()
    users = data.get('settings', {}).get('users', [])
    target = next((u for u in users if u.get('id') == uid), None)
    if not target:
        return jsonify({'ok': False, 'error': 'المستخدم غير موجود'}), 404
    payload = request.get_json(silent=True) or {}
    username = (payload.get('username', target.get('username')) or '').strip()
    role = payload.get('role', target.get('role', 'cashier'))
    password = payload.get('password') or ''
    if not username or role not in ROLE_LABELS:
        return jsonify({'ok': False, 'error': 'البيانات أو المستوى غير صالح'}), 400
    if any(u.get('id') != uid and u.get('username') == username for u in users):
        return jsonify({'ok': False, 'error': 'اسم المستخدم موجود مسبقًا'}), 409
    if target.get('role') == 'manager' and role != 'manager' and sum(1 for u in users if u.get('role') == 'manager') <= 1:
        return jsonify({'ok': False, 'error': 'لا يمكن تحويل آخر مدير إلى مستوى آخر'}), 400
    target['username'] = username
    target['role'] = role
    if password:
        target['password_hash'] = hash_password(password)
    save(data)
    return jsonify({'ok': True})


@app.route('/api/settings/users/<int:uid>', methods=['DELETE'])
def delete_user(uid):
    if not has_role('manager'):
        return permission_error()
    data = load()
    users = data.get('settings', {}).get('users', [])
    target = next((u for u in users if u.get('id') == uid), None)
    if not target:
        return jsonify({'ok': False, 'error': 'المستخدم غير موجود'}), 404
    if target.get('username') == session.get('username'):
        return jsonify({'ok': False, 'error': 'لا يمكن حذف المستخدم المسجل حاليًا'}), 400
    if target.get('role') == 'manager' and sum(1 for u in users if u.get('role') == 'manager') <= 1:
        return jsonify({'ok': False, 'error': 'لا يمكن حذف آخر مدير في النظام'}), 400
    data['settings']['users'] = [u for u in users if u.get('id') != uid]
    save(data)
    return jsonify({"ok": True})

@app.route('/api/auth/verify', methods=['POST'])
def verify_user():
    """تحقق عام من بيانات مستخدم، للاستعمالات الإدارية المحددة فقط."""
    data = load()
    payload = request.get_json(silent=True) or {}
    username = (payload.get('username') or '').strip()
    password = payload.get('password') or ''
    users = data.get('settings', {}).get('users', [])
    for u in users:
        if u.get('username') == username and verify_password(u.get('password_hash'), password):
            return jsonify({"ok": True, "username": u['username'], "role": u.get('role', 'cashier')})
    return jsonify({"ok": False, "error": "اسم المستخدم أو كلمة المرور غير صحيحة"}), 401


@app.route('/api/auth/verify-current', methods=['POST'])
def verify_current_user():
    """يفتح قفل الشاشة فقط عندما تُدخل كلمة مرور الكاشير/المستخدم المسجل حاليًا."""
    username = session.get('username')
    if not username:
        return jsonify({'ok': False, 'error': 'سجّل الدخول أولاً'}), 401
    payload = request.get_json(silent=True) or {}
    password = payload.get('password') or ''
    data = load()
    user = next((u for u in data.get('settings', {}).get('users', []) if u.get('username') == username), None)
    if not user or not verify_password(user.get('password_hash'), password):
        return jsonify({'ok': False, 'error': 'رمز كاشير غير صحيح'}), 401
    if not str(user.get('password_hash', '')).startswith('pbkdf2_sha256$'):
        user['password_hash'] = hash_password(password)
        save(data)
    return jsonify({'ok': True, 'username': username, 'role': user.get('role', 'cashier')})


ROLE_PAGE_ACCESS = {
    'index.html': {'cashier', 'supervisor', 'manager'},
    'settings.html': {'manager'},
    'printer_settings.html': {'manager', 'supervisor'},
    'menu_manager.html': {'manager', 'supervisor'},
    'employees.html': {'manager'},
    'raw_materials.html': {'manager', 'supervisor'},
    'analytics.html': {'manager', 'supervisor'},
    'orders_list.html': {'manager', 'supervisor'},
    'kitchen.html': {'manager', 'supervisor', 'cashier'},
    'tables.html': {'manager', 'supervisor', 'cashier'},
    'customers.html': {'manager', 'supervisor'},
    'manager_ops.html': {'manager'},
    'expenses.html': {'manager'},
}

ROLE_LABELS = {'cashier': 'كاشير', 'supervisor': 'مشرف', 'manager': 'مدير'}


def has_role(*allowed):
    """يتحقق من جلسة المستخدم؛ العمليات الحساسة لا تعتمد على إخفاء الزر في الواجهة."""
    users = load().get('settings', {}).get('users', [])
    return not users or session.get('role') in allowed


def permission_error():
    return jsonify({'ok': False, 'error': 'ليس لديك صلاحية لتنفيذ هذه العملية'}), 403


PUBLIC_API_PATHS = {
    '/api/setup/status', '/api/setup/initialize', '/api/network/info',
    '/api/restaurant/name', '/api/settings/support-info', '/api/settings/users',
    '/api/auth/login', '/api/auth/logout', '/api/auth/me', '/api/auth/verify',
}
CASHIER_READ_PREFIXES = (
    '/api/menu', '/api/barcode/', '/api/settings/currency', '/api/restaurant/name',
    '/api/inventory/alerts', '/api/printer/settings', '/api/kitchen/orders',
    '/api/tables', '/api/dine-in/', '/api/shifts/current',
)


def active_users(data=None):
    data = data or load()
    return data.get('settings', {}).get('users', [])


def manager_session_required():
    users = active_users()
    return bool(users) and session.get('role') == 'manager'


def authenticated_roles(*roles):
    return session.get('role') in roles


@app.before_request
def enforce_api_access():
    """يفرض الإعداد الأولي والجلسة والصلاحية على الواجهة البرمجية، وليس على الأزرار فقط."""
    if not request.path.startswith('/api/'):
        return None
    data = load()
    path = request.path
    method = request.method

    # لا يمكن البيع أو مشاهدة بيانات مطعم قبل إنشاء هوية المطعم والمدير الأول.
    if not commercial_setup_complete(data):
        if path not in {'/api/setup/status', '/api/setup/initialize', '/api/network/info'}:
            return jsonify({'ok': False, 'error': 'يجب إكمال الإعداد الأولي للمطعم أولاً'}), 423
        return None

    # بيانات شاشة الترحيب وتسجيل الدخول فقط. قائمة المستخدمين لا تتضمن كلمة مرور أو تجزئتها.
    if path in PUBLIC_API_PATHS:
        return None
    if path == '/api/qr/menu':
        if os.environ.get('QAISAR_LAN') != '1':
            return jsonify({'ok': False, 'error': 'القائمة الرقمية العامة متاحة فقط عند تفعيل وضع الشبكة المحلية'}), 403
        return None

    role = session.get('role')
    if role not in ROLE_LABELS:
        return jsonify({'ok': False, 'error': 'سجّل الدخول أولاً'}), 401

    # عمليات البيع والمطبخ متاحة للأدوار التشغيلية، أما التعديل المالي والإداري فمدير فقط.
    if method in {'POST', 'PUT', 'DELETE'}:
        if (method, path) == ('POST', '/api/auth/verify-current'):
            return None
        if (method, path) == ('POST', '/api/orders'):
            return None
        if re.fullmatch(r'/api/dine-in/sessions(?:/[^/]+)?(?:/(?:move|close))?', path):
            return None
        if method == 'POST' and re.fullmatch(r'/api/kitchen/orders/[^/]+/status', path):
            return None
        if method == 'POST' and path == '/api/loyalty/redeem':
            return None
        if role != 'manager':
            return permission_error()
        return None

    if path.startswith(CASHIER_READ_PREFIXES):
        return None
    if role not in {'manager', 'supervisor'}:
        return permission_error()
    return None


@app.after_request
def audit_successful_mutation(response):
    """يسجل العمليات الناجحة مع المستخدم والمسار وسبب العملية دون حفظ كلمات المرور."""
    if (response.status_code < 400 and request.path.startswith('/api/')
            and request.method in {'POST', 'PUT', 'DELETE'}
            and request.path not in {'/api/auth/login', '/api/auth/logout', '/api/auth/verify', '/api/setup/initialize'}):
        try:
            data = load()
            payload = request.get_json(silent=True) or {}
            data.setdefault('audit_log', []).append({
                'timestamp': datetime.now().isoformat(),
                'username': session.get('username', 'نظام محلي'),
                'role': session.get('role', 'manager'),
                'action': request.method,
                'path': request.path,
                'reason': str(payload.get('reason') or payload.get('notes') or '')[:300],
                'status': response.status_code
            })
            data['audit_log'] = data['audit_log'][-500:]
            save(data)
        except Exception:
            pass
    return response


@app.route('/api/admin/audit-log', methods=['GET'])
def get_audit_log():
    if not manager_session_required():
        return permission_error()
    data = load()
    return jsonify(list(reversed(data.get('audit_log', [])))[:500])

@app.route('/api/auth/login', methods=['POST'])
def auth_login():
    """تسجيل دخول فعلي يحفظ الجلسة - يُستخدم لفتح الصفحات المخصصة للمدير فقط."""
    data = load()
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
            session['username'] = u['username']
            session['role'] = u.get('role', 'cashier')
            return jsonify({"ok": True, "username": u['username'], "role": session['role']})
    return jsonify({"ok": False, "error": "اسم المستخدم أو كلمة المرور غير صحيحة"}), 401

@app.route('/api/auth/logout', methods=['POST'])
def auth_logout():
    session.clear()
    return jsonify({"ok": True})

@app.route('/api/auth/me', methods=['GET'])
def auth_me():
    return jsonify({"username": session.get('username'), "role": session.get('role')})

def role_page_or_login(filename):
    """يحمي صفحة حسب المستوى الوظيفي المطلوب لها."""
    data = load()
    users = data.get('settings', {}).get('users', [])
    allowed = ROLE_PAGE_ACCESS.get(filename, {'manager'})
    if users and session.get('role') not in allowed:
        return redirect(f'/login.html?next={filename}')
    return send_from_directory(BASE_DIR, filename)

for _page in ROLE_PAGE_ACCESS:
    app.add_url_rule(f'/{_page}', endpoint=f'protected_{_page}',
                      view_func=lambda filename=_page: role_page_or_login(filename))


@app.route('/api/settings/lock', methods=['GET'])
def get_lock():
    data = load()
    l = data.get('settings', {}).get('lock', {})
    return jsonify({"enabled": l.get('enabled', False), "timeout": l.get('timeout', 5)})

@app.route('/api/settings/lock', methods=['POST'])
def set_lock():
    if not has_role('manager'):
        return permission_error()
    data = load()
    if 'settings' not in data:
        data['settings'] = {}
    data['settings']['lock'] = {
        'enabled': request.json.get('enabled', False),
        'timeout': request.json.get('timeout', 5)
    }
    save(data)
    return jsonify({"ok": True})


@app.route('/api/settings/backups', methods=['GET'])
def list_backups():
    try:
        files = sorted(os.listdir(BACKUP_DIR), reverse=True)
        return jsonify(files[:30])
    except Exception:
        return jsonify([])

@app.route('/api/settings/backup', methods=['POST'])
def create_backup_endpoint():
    backup()
    return jsonify({"ok": True})


@app.route('/api/settings/factory-reset', methods=['POST'])
def factory_reset_endpoint():
    """يعيد بيانات النظام إلى النسخة المرجعية بعد تأكيد صريح، مع حفظ نسخة قبل الحذف."""
    if not has_role('manager'):
        return permission_error()
    data = load()
    users = data.get('settings', {}).get('users', [])
    if users and session.get('role') != 'manager':
        return jsonify({"ok": False, "error": "هذه العملية متاحة للمدير فقط"}), 403

    payload = request.get_json(silent=True) or {}
    if payload.get('confirmation') != 'RESET':
        return jsonify({"ok": False, "error": "تأكيد غير صالح"}), 400
    if not os.path.exists(FACTORY_FILE):
        return jsonify({"ok": False, "error": "ملف نسخة المصنع غير موجود"}), 500

    try:
        backup()
        with open(FACTORY_FILE, 'r', encoding='utf-8') as f:
            factory_data = json.load(f)
        atomic_write_json(DATA_FILE, factory_data)
        atomic_write_json(FLASH_BACKUP, factory_data)
        return jsonify({"ok": True, "message": "تمت إعادة ضبط المصنع، وحُفظت نسخة احتياطية من البيانات السابقة"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route('/api/check-update', methods=['GET'])
def check_update_route():
    """يتحقق فعلياً من GitHub لو في نسخة أحدث، ولو موجودة يحمّل ملفات الواجهة المحدّثة تلقائياً.
    استدعاء يدوي بس (مش تلقائي عند كل تشغيل) حتى ما يبطئ الإقلاع أو يفشل لو ما في إنترنت،
    بما إنه النظام مصمم يشتغل أوفلاين بالأساس. اضغط زر 'تحقق من التحديثات' بالإعدادات لما يكون عندك نت."""
    result = check_for_updates()
    return jsonify(result)


@app.route('/api/order/<order_id>', methods=['GET'])
def get_order(order_id):
    """البحث عن فاتورة برقمها"""
    data = load()
    all_orders = data.get('orders', []) + data.get('orders_archive', [])
    for o in all_orders:
        if o.get('id') == order_id:
            return jsonify(o)
    return jsonify({"error": "الفاتورة غير موجودة"}), 404



# ========== ميزات كاشير القيصر المتقدمة ==========
def _store(data, key, default=None):
    if key not in data:
        data[key] = [] if default is None else default
    return data[key]

def _today_orders(data):
    today = datetime.now().strftime('%Y-%m-%d')
    return [o for o in data.get('orders', []) + data.get('orders_archive', [])
            if (o.get('timestamp') or o.get('date', '')).startswith(today) and not o.get('voided')]

@app.route('/api/shifts', methods=['GET'])
def list_shifts():
    data = load()
    return jsonify(data.get('shifts', []))

@app.route('/api/shifts/current', methods=['GET'])
def current_shift():
    orders = _today_orders(load())
    return jsonify({'date': datetime.now().strftime('%Y-%m-%d'), 'orders': len(orders),
                    'sales': round(sum(o.get('total', 0) or 0 for o in orders), 2),
                    'cash': round(sum(o.get('cash_amount', o.get('total', 0) if o.get('payment') != 'بطاقة' else 0) or 0 for o in orders), 2),
                    'card': round(sum(o.get('card_amount', o.get('total', 0) if o.get('payment') == 'بطاقة' else 0) or 0 for o in orders), 2)})

@app.route('/api/shifts/close', methods=['POST'])
def close_shift_secure():
    if not has_role('manager'):
        return permission_error()
    data = load(); orders = _today_orders(data); payload = request.get_json(silent=True) or {}
    expected_cash = round(sum(o.get('cash_amount', o.get('total', 0) if o.get('payment') != 'بطاقة' else 0) or 0 for o in orders), 2)
    actual_cash = payload.get('actual_cash')
    shift = {'id': len(data.get('shifts', [])) + 1, 'date': datetime.now().strftime('%Y-%m-%d'),
             'time': datetime.now().isoformat(), 'orders': len(orders),
             'sales': round(sum(o.get('total', 0) or 0 for o in orders), 2),
             'expected_cash': expected_cash, 'actual_cash': actual_cash,
             'difference': round(float(actual_cash) - expected_cash, 2) if actual_cash is not None else None,
             'closed_by': session.get('username', 'manager'), 'reason': str(payload.get('reason', ''))[:300]}
    _store(data, 'shifts').append(shift); save(data); backup()
    return jsonify({'ok': True, 'shift': shift})

@app.route('/api/offers', methods=['GET', 'POST'])
def offers_api():
    data = load()
    if request.method == 'GET': return jsonify(data.get('offers', []))
    payload = request.get_json(silent=True) or {}
    offer = {'id': len(data.get('offers', [])) + 1, 'name': payload.get('name', ''), 'type': payload.get('type', 'percent'),
             'value': float(payload.get('value', 0) or 0), 'product_names': payload.get('product_names', []),
             'active': bool(payload.get('active', True)), 'starts_at': payload.get('starts_at', ''), 'ends_at': payload.get('ends_at', '')}
    if not offer['name'] or offer['value'] < 0: return jsonify({'ok': False, 'error': 'بيانات العرض غير صالحة'}), 400
    _store(data, 'offers').append(offer); save(data); backup(); return jsonify({'ok': True, 'offer': offer})

@app.route('/api/modifiers', methods=['GET', 'POST'])
def modifiers_api():
    data = load()
    if request.method == 'GET': return jsonify(data.get('modifiers', []))
    payload = request.get_json(silent=True) or {}
    mod = {'id': len(data.get('modifiers', [])) + 1, 'name': payload.get('name', ''), 'options': payload.get('options', [])}
    if not mod['name']: return jsonify({'ok': False, 'error': 'اسم الإضافة مطلوب'}), 400
    _store(data, 'modifiers').append(mod); save(data); backup(); return jsonify({'ok': True, 'modifier': mod})

@app.route('/api/orders/<order_id>/split', methods=['POST'])
def split_order(order_id):
    data = load(); payload = request.get_json(silent=True) or {}; item_indexes = payload.get('item_indexes', [])
    for o in data.get('orders', []):
        if str(o.get('id')) == str(order_id):
            if o.get('voided') or not item_indexes: return jsonify({'ok': False, 'error': 'لا يمكن تقسيم الفاتورة بهذه البيانات'}), 400
            moved = [o.get('items', [])[i] for i in item_indexes if isinstance(i, int) and 0 <= i < len(o.get('items', []))]
            if not moved: return jsonify({'ok': False, 'error': 'الأصناف غير موجودة'}), 400
            remaining = [x for i, x in enumerate(o.get('items', [])) if i not in item_indexes]
            new_order = dict(o); new_order['id'] = next_order_id(data); new_order['items'] = moved; new_order['total'] = round(sum((x.get('price', 0) or 0) * (x.get('quantity', x.get('qty', 1)) or 0) for x in moved), 2); new_order['split_from'] = o.get('id'); new_order['timestamp'] = datetime.now().isoformat()
            o['items'] = remaining; o['total'] = round(sum((x.get('price', 0) or 0) * (x.get('quantity', x.get('qty', 1)) or 0) for x in remaining), 2); o['split_into'] = new_order['id']; data['orders'].append(new_order); save(data); backup(); return jsonify({'ok': True, 'new_order': new_order})
    return jsonify({'ok': False, 'error': 'الطلب غير موجود'}), 404

DINE_IN_STATUSES = {'open', 'closed', 'cancelled'}
KITCHEN_STATUSES = {'new', 'preparing', 'ready', 'served'}


def normalize_tables(data):
    """يحافظ على توافق الطاولات القديمة ويضمن حقول إدارة الصالة الجديدة."""
    tables = data.get('tables', [])
    if isinstance(tables, dict):
        tables = [{'id': str(k), 'name': 'طاولة ' + str(k),
                   'status': ('busy' if isinstance(v, dict) and v.get('status') == 'open' else 'free'),
                   'items': (v.get('items', []) if isinstance(v, dict) else [])}
                  for k, v in tables.items()]
    if not isinstance(tables, list):
        tables = []
    for table in tables:
        if not isinstance(table, dict):
            continue
        table['id'] = str(table.get('id', ''))
        table['name'] = str(table.get('name') or ('طاولة ' + table['id']))[:80]
        table['status'] = table.get('status') if table.get('status') in {'free', 'busy', 'reserved'} else 'free'
        table['seats'] = max(1, min(30, int(table.get('seats', 4) or 4)))
        table['zone'] = str(table.get('zone', 'الصالة'))[:80]
    data['tables'] = tables
    return tables


def find_table(data, table_id):
    for table in normalize_tables(data):
        if str(table.get('id')) == str(table_id):
            return table
    return None


def find_dine_in_session(data, session_id):
    for session_row in data.get('dine_in_sessions', []):
        if str(session_row.get('id')) == str(session_id):
            return session_row
    return None


def dine_in_totals(data, payload):
    items, item_error = approved_order_items(data, payload.get('items'))
    if item_error:
        return None, item_error
    if not items:
        return None, 'أضف صنفاً واحداً على الأقل إلى طلب الطاولة'
    subtotal = round(sum(item['price'] * item['quantity'] for item in items), 2)
    discount_pct = as_money(payload.get('discount_pct', 0), 0)
    discount_amount = as_money(payload.get('discount_amount', 0), 0)
    if discount_pct is None or not 0 <= discount_pct <= 100 or discount_amount is None:
        return None, 'قيمة الخصم غير صالحة'
    after_percent = round(subtotal * (1 - discount_pct / 100), 2)
    if discount_amount > after_percent:
        return None, 'الخصم أكبر من إجمالي الطلب'
    return {
        'items': items,
        'subtotal': subtotal,
        'discount_pct': discount_pct,
        'discount_amount': discount_amount,
        'total': round(after_percent - discount_amount, 2)
    }, None


def dine_in_session_view(session_row):
    return {
        'id': session_row.get('id'), 'table_id': session_row.get('table_id'), 'table_name': session_row.get('table_name'),
        'status': session_row.get('status'), 'items': session_row.get('items', []), 'subtotal': session_row.get('subtotal', 0),
        'discount_pct': session_row.get('discount_pct', 0), 'discount_amount': session_row.get('discount_amount', 0),
        'total': session_row.get('total', 0), 'note': session_row.get('note', ''), 'customer': session_row.get('customer', ''),
        'kitchen_status': session_row.get('kitchen_status', 'new'), 'opened_by': session_row.get('opened_by', ''),
        'created_at': session_row.get('created_at', ''), 'updated_at': session_row.get('updated_at', '')
    }


@app.route('/api/dine-in/sessions', methods=['GET', 'POST'])
def dine_in_sessions():
    data = load()
    normalize_tables(data)
    sessions = data.setdefault('dine_in_sessions', [])
    if request.method == 'GET':
        rows = [dine_in_session_view(row) for row in sessions if row.get('status') == 'open']
        return jsonify(sorted(rows, key=lambda row: row.get('created_at', ''), reverse=True))

    payload = request.get_json(silent=True) or {}
    table = find_table(data, payload.get('table_id'))
    if not table:
        return jsonify({'ok': False, 'error': 'اختر طاولة صالحة'}), 404
    if table.get('status') == 'busy' or table.get('active_session_id'):
        return jsonify({'ok': False, 'error': 'هذه الطاولة مرتبطة بطلب مفتوح بالفعل'}), 409
    totals, error = dine_in_totals(data, payload)
    if error:
        return jsonify({'ok': False, 'error': error}), 400
    now = datetime.now().isoformat()
    session_row = {
        'id': 'DINE-' + uuid.uuid4().hex[:10].upper(), 'status': 'open',
        'table_id': str(table['id']), 'table_name': table['name'], **totals,
        'note': str(payload.get('note', ''))[:500], 'customer': str(payload.get('customer', ''))[:120],
        'kitchen_status': 'new', 'opened_by': session.get('username', 'غير محدد'),
        'created_at': now, 'updated_at': now
    }
    sessions.append(session_row)
    table['status'] = 'busy'; table['active_session_id'] = session_row['id']
    table['active_since'] = now
    save(data); backup()
    return jsonify({'ok': True, 'session': dine_in_session_view(session_row)}), 201


@app.route('/api/dine-in/sessions/<session_id>', methods=['GET', 'PUT'])
def dine_in_session_detail(session_id):
    data = load()
    session_row = find_dine_in_session(data, session_id)
    if not session_row:
        return jsonify({'ok': False, 'error': 'طلب الصالة غير موجود'}), 404
    if request.method == 'GET':
        return jsonify({'ok': True, 'session': dine_in_session_view(session_row)})
    if session_row.get('status') != 'open':
        return jsonify({'ok': False, 'error': 'لا يمكن تعديل طلب مغلق'}), 409
    payload = request.get_json(silent=True) or {}
    totals, error = dine_in_totals(data, payload)
    if error:
        return jsonify({'ok': False, 'error': error}), 400
    session_row.update(totals)
    session_row['note'] = str(payload.get('note', ''))[:500]
    session_row['customer'] = str(payload.get('customer', ''))[:120]
    session_row['updated_at'] = datetime.now().isoformat()
    session_row['updated_by'] = session.get('username', 'غير محدد')
    save(data); backup()
    return jsonify({'ok': True, 'session': dine_in_session_view(session_row)})


@app.route('/api/dine-in/sessions/<session_id>/move', methods=['POST'])
def move_dine_in_session(session_id):
    data = load()
    session_row = find_dine_in_session(data, session_id)
    if not session_row or session_row.get('status') != 'open':
        return jsonify({'ok': False, 'error': 'طلب الصالة المفتوح غير موجود'}), 404
    payload = request.get_json(silent=True) or {}
    destination = find_table(data, payload.get('table_id'))
    if not destination:
        return jsonify({'ok': False, 'error': 'اختر طاولة وجهة صالحة'}), 404
    if destination.get('status') == 'busy' or destination.get('active_session_id'):
        return jsonify({'ok': False, 'error': 'طاولة الوجهة مشغولة'}), 409
    origin = find_table(data, session_row.get('table_id'))
    if origin:
        origin['status'] = 'free'; origin.pop('active_session_id', None); origin.pop('active_since', None)
    destination['status'] = 'busy'; destination['active_session_id'] = session_row['id']; destination['active_since'] = datetime.now().isoformat()
    session_row['table_id'] = str(destination['id']); session_row['table_name'] = destination['name']
    session_row['updated_at'] = datetime.now().isoformat(); session_row['moved_by'] = session.get('username', 'غير محدد')
    save(data); backup()
    return jsonify({'ok': True, 'session': dine_in_session_view(session_row)})


@app.route('/api/dine-in/sessions/<session_id>/close', methods=['POST'])
def close_dine_in_session(session_id):
    data = load()
    session_row = find_dine_in_session(data, session_id)
    if not session_row or session_row.get('status') != 'open':
        return jsonify({'ok': False, 'error': 'طلب الصالة المفتوح غير موجود'}), 404
    payload = request.get_json(silent=True) or {}
    payment_data, payment_error = normalize_payment(session_row.get('total', 0), payload)
    if payment_error:
        return jsonify({'ok': False, 'error': payment_error}), 400
    now = datetime.now().isoformat()
    order = {
        'id': next_order_id(data), 'timestamp': now, 'items': session_row['items'],
        'subtotal': session_row['subtotal'], 'discount_pct': session_row['discount_pct'], 'discount_amount': session_row['discount_amount'],
        'total': session_row['total'], 'type': 'صالة', 'note': session_row.get('note', ''),
        'customer': session_row.get('customer', ''), 'table': session_row.get('table_name', ''),
        'table_id': session_row.get('table_id'), 'cashier_name': session.get('username', 'غير محدد'),
        'kitchen_status': session_row.get('kitchen_status', 'new'), 'dine_in_session_id': session_row['id'], **payment_data
    }
    snap = currency_snapshot(data, payload)
    order['currency'] = snap['currency']; order['exchange_rate'] = snap['exchange_rate']
    data.setdefault('orders', []).append(order)
    consume_inventory_for_order(data, order['items'])
    session_row['status'] = 'closed'; session_row['closed_at'] = now; session_row['closed_order_id'] = order['id']
    table = find_table(data, session_row.get('table_id'))
    if table:
        table['status'] = 'free'; table.pop('active_session_id', None); table.pop('active_since', None)
    save(data); backup()
    return jsonify({'ok': True, 'id': order['id'], 'total': order['total'], 'order': order})


@app.route('/api/kitchen/orders', methods=['GET'])
def kitchen_orders():
    data = load()
    paid_orders = [o for o in data.get('orders', []) if not o.get('voided') and o.get('kitchen_status', 'new') != 'served']
    open_sessions = []
    for session_row in data.get('dine_in_sessions', []):
        if session_row.get('status') == 'open' and session_row.get('kitchen_status', 'new') != 'served':
            kitchen_row = dict(session_row)
            kitchen_row['id'] = 'SESSION-' + str(session_row['id'])
            kitchen_row['type'] = 'صالة'
            kitchen_row['table'] = session_row.get('table_name', '')
            kitchen_row['is_dine_in_session'] = True
            open_sessions.append(kitchen_row)
    return jsonify(paid_orders + open_sessions)


@app.route('/api/kitchen/orders/<order_id>/status', methods=['POST'])
def kitchen_status(order_id):
    data = load(); payload = request.get_json(silent=True) or {}; status = payload.get('status', 'new')
    if status not in KITCHEN_STATUSES:
        return jsonify({'ok': False, 'error': 'حالة غير صالحة'}), 400
    if str(order_id).startswith('SESSION-'):
        session_row = find_dine_in_session(data, str(order_id)[8:])
        if session_row and session_row.get('status') == 'open':
            session_row['kitchen_status'] = status; session_row['updated_at'] = datetime.now().isoformat(); save(data)
            return jsonify({'ok': True, 'status': status, 'dine_in_session': True})
    for order in data.get('orders', []):
        if str(order.get('id')) == str(order_id):
            order['kitchen_status'] = status; save(data); return jsonify({'ok': True, 'status': status})
    return jsonify({'ok': False, 'error': 'الطلب غير موجود'}), 404


@app.route('/api/tables', methods=['GET', 'POST'])
def tables_api():
    data = load()
    tables = normalize_tables(data)
    if request.method == 'GET':
        sessions = {str(row.get('id')): row for row in data.get('dine_in_sessions', []) if row.get('status') == 'open'}
        rows = []
        for table in tables:
            row = dict(table)
            session_row = sessions.get(str(table.get('active_session_id', '')))
            if session_row:
                row['active_session'] = dine_in_session_view(session_row)
                row['status'] = 'busy'
            rows.append(row)
        return jsonify(rows)
    payload = request.get_json(silent=True) or {}
    name = str(payload.get('name', '')).strip()[:80]
    if not name:
        return jsonify({'ok': False, 'error': 'اسم الطاولة مطلوب'}), 400
    if any(table.get('name', '').strip() == name for table in tables):
        return jsonify({'ok': False, 'error': 'اسم الطاولة مستخدم بالفعل'}), 409
    next_id = max([int(table.get('id', 0)) for table in tables if str(table.get('id', '')).isdigit()] or [0]) + 1
    table = {'id': str(next_id), 'name': name, 'status': 'free',
             'seats': max(1, min(30, int(payload.get('seats', 4) or 4))),
             'zone': str(payload.get('zone', 'الصالة'))[:80]}
    tables.append(table); data['tables'] = tables; save(data); backup()
    return jsonify({'ok': True, 'table': table}), 201

@app.route('/api/customers', methods=['GET', 'POST'])
def customers_api():
    data = load()
    if request.method == 'GET': return jsonify(data.get('customers', []))
    payload = request.get_json(silent=True) or {}; customer = {'id': len(data.get('customers', [])) + 1, 'name': payload.get('name', ''), 'phone': payload.get('phone', ''), 'points': 0, 'created_at': datetime.now().isoformat()}
    if not customer['name']: return jsonify({'ok': False, 'error': 'اسم العميل مطلوب'}), 400
    _store(data, 'customers').append(customer); save(data); return jsonify({'ok': True, 'customer': customer})

@app.route('/api/loyalty/redeem', methods=['POST'])
def loyalty_redeem():
    data = load(); payload = request.get_json(silent=True) or {}; cid = payload.get('customer_id'); points = int(payload.get('points', 0) or 0)
    for c in data.get('customers', []):
        if c.get('id') == cid:
            if points <= 0 or c.get('points', 0) < points: return jsonify({'ok': False, 'error': 'رصيد النقاط غير كافٍ'}), 400
            c['points'] -= points; save(data); return jsonify({'ok': True, 'remaining': c['points']})
    return jsonify({'ok': False, 'error': 'العميل غير موجود'}), 404

@app.route('/api/gift-cards', methods=['GET', 'POST'])
def gift_cards_api():
    data = load()
    if request.method == 'GET': return jsonify(data.get('gift_cards', []))
    payload = request.get_json(silent=True) or {}; code = payload.get('code', '').strip(); balance = float(payload.get('balance', 0) or 0)
    if not code or balance <= 0: return jsonify({'ok': False, 'error': 'بيانات البطاقة غير صالحة'}), 400
    card = {'code': code, 'balance': balance, 'created_at': datetime.now().isoformat()}; _store(data, 'gift_cards').append(card); save(data); return jsonify({'ok': True, 'card': card})

@app.route('/api/qr/menu', methods=['GET'])
def qr_menu():
    data = load(); return jsonify({'restaurant': data.get('settings', {}).get('restaurant', {}), 'menu': data.get('menu', {})})

@app.route('/api/sync/status', methods=['GET'])
def sync_status():
    data = load(); return jsonify({'mode': 'local', 'online': False, 'pending': len(data.get('sync_queue', [])), 'last_sync': data.get('settings', {}).get('last_sync')})

if __name__ == '__main__':
    print('='*50)
    print('كاشير القيصر')
    print(f' Version: {CURRENT_VERSION}')
    print(f'  Vault: {VAULT_DIR}')
    print('='*50)

    # فحص التحديثات
    updated = False  # Disabled
    if updated:
        print(' تم التحديث! يرجى إعادة التشغيل.')

    import webbrowser
   # webbrowser.open('http://127.0.0.1:8080')

    # flask_thread removed
    start_flask()
