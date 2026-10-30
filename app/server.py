import os, sys, json, shutil, threading, hashlib, hmac, base64, secrets, tempfile, subprocess, socket, uuid, re, traceback, time, platform, sqlite3, queue, math
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import zipfile
import binascii
from xml.sax.saxutils import escape as xml_escape
from PIL import Image, ImageDraw, ImageFont
import arabic_reshaper
from bidi.algorithm import get_display
# ضمان العثور على ملفات التطبيق عند تشغيل Python المضمّن بوضع isolated على Windows.
APP_SOURCE_PATH = os.path.dirname(os.path.abspath(__file__))
if APP_SOURCE_PATH not in sys.path:
    sys.path.insert(0, APP_SOURCE_PATH)
from flask import Flask, request, jsonify, send_from_directory, send_file, session, redirect, Response
from io import BytesIO
from permissions import (
    CASHIER_READ_PREFIXES,
    DAILY_OPERATION_WRITE_PATTERNS,
    PUBLIC_API_PATHS,
    ROLE_LABELS,
    ROLE_PAGE_ACCESS,
    allowed_roles_for_request,
    is_daily_operational_write,
    page_allowed,
)

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_RIGHT, TA_CENTER
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib import colors
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False

VENDOR_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'vendor')
if VENDOR_PATH not in sys.path:
    sys.path.insert(0, VENDOR_PATH)
try:
    import qrcode
    from qrcode.image.svg import SvgPathImage
except ImportError:
    qrcode = None
    SvgPathImage = None

CURRENT_VERSION = "4.0.0"

# Stable HMAC contract shared with the owner-only generate_license.py utility.
#
# ترتيب تحميل مفتاح الترخيص: ملف مورّد محلي أو متغير بيئة فقط. لا يوجد سر
# افتراضي داخل الخادم؛ غياب السر يجعل التحقق يفشل بدلاً من قبول مفتاح منشور.
_LICENSE_SECRET_FILENAMES = ('.license_secret', 'license.secret')


def _license_secret_search_dirs():
    app_dir = os.path.dirname(os.path.abspath(__file__))
    dirs = [app_dir, os.path.dirname(app_dir)]
    exe_dir = os.path.dirname(os.path.abspath(sys.argv[0])) if getattr(sys, 'frozen', False) else None
    if exe_dir:
        dirs.append(exe_dir)
    if getattr(sys, 'frozen', False):
        dirs.append(os.path.dirname(sys.executable))
    return dirs


def load_license_secret():
    """يحمّل سر HMAC من ملف مورّد أو متغير بيئة، وإلا يعيد فراغًا."""
    for directory in _license_secret_search_dirs():
        for filename in _LICENSE_SECRET_FILENAMES:
            try:
                path = os.path.join(directory, filename)
                if os.path.isfile(path):
                    with open(path, 'r', encoding='utf-8') as f:
                        value = f.read().strip()
                    if value:
                        return value
            except OSError:
                continue
    return os.environ.get('CAESAR_LICENSE_SECRET', '').strip()


LICENSE_SECRET = load_license_secret().encode('utf-8')
LICENSE_ALGORITHM = 'HMAC-SHA256'

_LICENSE_FILE_FILENAMES = ('.license', 'license.txt')


def load_shipped_license():
    """يقرأ رقم/مفتاح ترخيص مُجهَّز مسبقاً من ملف .license بجانب البرنامج
    (JSON بمفاتيح license_id/license_key، أو سطرين LICENSE_ID=/LICENSE_KEY=)
    لتسهيل النشر المسبق عند التوزيع للعميل. هذا لا يُفعّل الترخيص تلقائياً؛
    فقط يُستخدم لتعبئة شاشة الإعداد مسبقاً، ويبقى verify_license() هو الحارس
    الوحيد الذي يقرر قبول أي ترخيص فعلياً. أي عطل بقراءة الملف يُتجاهل بصمت."""
    for directory in _license_secret_search_dirs():
        for filename in _LICENSE_FILE_FILENAMES:
            path = os.path.join(directory, filename)
            try:
                if not os.path.isfile(path):
                    continue
                with open(path, 'r', encoding='utf-8') as f:
                    content = f.read().strip()
                if not content:
                    continue
                license_id = license_key = ''
                try:
                    parsed = json.loads(content)
                    license_id = str(parsed.get('license_id', '')).strip().upper()
                    license_key = str(parsed.get('license_key', '')).strip().upper()
                except (ValueError, AttributeError):
                    for line in content.splitlines():
                        if '=' not in line:
                            continue
                        key, _, value = line.partition('=')
                        key = key.strip().upper(); value = value.strip().upper()
                        if key == 'LICENSE_ID':
                            license_id = value
                        elif key == 'LICENSE_KEY':
                            license_key = value
                if license_id and license_key:
                    return {'license_id': license_id, 'license_key': license_key}
            except OSError:
                continue
    return None

def version_tuple(v):
    """تحويل رقم الإصدار إلى tuple للمقارنة الصحيحة"""
    return tuple(int(x) for x in v.strip().split('.'))

def check_for_updates():
    """يعيد حالة الإصدار المحلية فقط؛ لا ينفذ أي اتصال خارجي."""
    return {"ok": True, "offline": True, "current": CURRENT_VERSION, "latest": CURRENT_VERSION, "updated_files": [], "error": None}
# ========== مسارات ==========
# تحديد مسار التشغيل
if getattr(sys, 'frozen', False):
    # PyInstaller One-File extracts bundled static assets to _MEIPASS.
    # User data remains in the writable CAESAR_Vault selected below.
    APP_PATH = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(sys.argv[0])))
    EXTERNAL_PATH = os.path.join(APP_PATH, 'app') if os.path.isdir(os.path.join(APP_PATH, 'app')) else APP_PATH
else:
    APP_PATH = os.path.dirname(os.path.abspath(__file__))
    EXTERNAL_PATH = APP_PATH

BASE_DIR = EXTERNAL_PATH


def choose_vault_dir():
    """يختار مجلد بيانات قابلًا للكتابة دون صلاحيات مدير على Windows، مع الحفاظ على المسار القديم إن أمكن."""
    # تستعمل الاختبارات هذا المتغير قبل استيراد الخادم كي لا تلامس إطلاقاً
    # مخزن المطعم التشغيلي. وهو مفيد أيضاً للنشر المُدار الذي يحدد مخزنه صراحةً.
    configured = os.environ.get('CAESAR_VAULT_DIR', '').strip()
    if configured:
        os.makedirs(configured, exist_ok=True)
        return configured
    if sys.platform == 'win32':
        candidates = [r'C:\CAESAR_Vault']
        local_app_data = os.environ.get('LOCALAPPDATA')
        user_profile = os.environ.get('USERPROFILE')
        if local_app_data:
            candidates.append(os.path.join(local_app_data, 'CAESAR_Vault'))
        if user_profile:
            candidates.append(os.path.join(user_profile, 'Documents', 'CAESAR_Vault'))
    else:
        candidates = [os.path.join(os.path.expanduser('~'), 'Documents', 'CAESAR_Vault')]

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
DATABASE_FILE = os.path.join(VAULT_DIR, 'caesar.sqlite3')
BACKUP_DIR = os.path.join(VAULT_DIR, 'backups')
FLASH_BACKUP = os.path.join(VAULT_DIR, 'data_backup.json')
FACTORY_FILE = os.path.join(BASE_DIR, 'factory_data.json')

# Structured order storage is maintained alongside the legacy JSON snapshot during
# the migration window. The operational database remains inside VAULT_DIR.
STRUCTURED_SCHEMA_VERSION = 1

FEATURE_DEFAULTS = {
    'kitchen': True,
    'tables': True,
    'delivery': True,
    'customers': True,
    'mobile': True,
    'reports': True,
}

def get_feature_flags(data=None):
    settings = (data or load()).setdefault('settings', {})
    stored = settings.get('features', {})
    return {key: bool(stored.get(key, default)) for key, default in FEATURE_DEFAULTS.items()}

def feature_is_enabled(data, key):
    return get_feature_flags(data).get(key, True)

os.makedirs(VAULT_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)

if not os.path.exists(DATA_FILE):
    if os.path.exists(FLASH_BACKUP):
        shutil.copy(FLASH_BACKUP, DATA_FILE)
    elif os.path.exists(FACTORY_FILE):
        shutil.copy(FACTORY_FILE, DATA_FILE)
    else:
        with open(DATA_FILE, 'w', encoding='utf-8') as f:
            json.dump({"menu": {}, "orders": [], "shifts": [], "log": [], "settings": {"currency": "SYP"}}, f, ensure_ascii=False, indent=2)


def _structured_table_sql(table_name, items_table_name):
    return f"""
    CREATE TABLE IF NOT EXISTS {table_name} (
        id TEXT PRIMARY KEY,
        timestamp TEXT NOT NULL,
        status TEXT,
        voided INTEGER NOT NULL DEFAULT 0,
        total REAL NOT NULL DEFAULT 0,
        subtotal REAL,
        discount_amount REAL,
        payment TEXT,
        cash_amount REAL,
        card_amount REAL,
        customer TEXT,
        table_no TEXT,
        order_type TEXT,
        cashier_name TEXT,
        note TEXT,
        payload TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_{table_name}_timestamp ON {table_name}(timestamp);
    CREATE INDEX IF NOT EXISTS idx_{table_name}_status_ts ON {table_name}(status, timestamp);
    CREATE TABLE IF NOT EXISTS {items_table_name} (
        order_id TEXT NOT NULL REFERENCES {table_name}(id) ON DELETE CASCADE,
        item_index INTEGER NOT NULL,
        name TEXT,
        qty REAL NOT NULL DEFAULT 0,
        price REAL NOT NULL DEFAULT 0,
        modifiers TEXT,
        payload TEXT,
        PRIMARY KEY (order_id, item_index)
    );
    CREATE INDEX IF NOT EXISTS idx_{items_table_name}_order ON {items_table_name}(order_id);
    """


def _ensure_structured_schema(conn):
    conn.executescript(_structured_table_sql('orders', 'order_items'))
    conn.execute('CREATE TABLE IF NOT EXISTS migration_state (name TEXT PRIMARY KEY, version INTEGER NOT NULL, completed_at TEXT NOT NULL, source_count INTEGER NOT NULL)')


def db_connect():
    """يفتح قاعدة SQLite التشغيلية مع WAL وقيود سلامة مناسبة للتزامن."""
    # اشتقاق المسار من VAULT_DIR يمنع بقاء الاتصال على قاعدة النسخة الأصلية
    # عند تبديل خزنة التشغيل (والاختبارات المعزولة) بعد استيراد الوحدة.
    database_file = os.path.join(VAULT_DIR, 'caesar.sqlite3')
    conn = sqlite3.connect(database_file, timeout=15, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=15000')
    conn.execute('CREATE TABLE IF NOT EXISTS app_state (id INTEGER PRIMARY KEY CHECK (id = 1), payload TEXT NOT NULL, updated_at TEXT NOT NULL)')
    _ensure_structured_schema(conn)
    return conn


def _order_row_values(order):
    stamp = str(order.get('timestamp') or order.get('date') or '')
    return (
        str(order.get('id') or uuid.uuid4().hex), stamp,
        str(order.get('status') or order.get('kitchen_status') or ''),
        1 if order.get('voided') else 0,
        float(order.get('total', 0) or 0),
        float(order.get('subtotal', 0) or 0) if order.get('subtotal') is not None else None,
        float(order.get('discount_amount', 0) or 0) if order.get('discount_amount') is not None else None,
        str(order.get('payment') or ''),
        float(order.get('cash_amount', 0) or 0) if order.get('cash_amount') is not None else None,
        float(order.get('card_amount', 0) or 0) if order.get('card_amount') is not None else None,
        str(order.get('customer') or ''), str(order.get('table') or order.get('table_no') or ''),
        str(order.get('type') or ''), str(order.get('cashier_name') or ''),
        str(order.get('note') or ''), json.dumps(order, ensure_ascii=False, separators=(',', ':')),
        datetime.now().isoformat()
    )


def _write_order_rows(conn, orders, orders_table='orders', items_table='order_items', prune=True):
    seen = set()
    for order in orders:
        if not isinstance(order, dict):
            continue
        order_id = str(order.get('id') or uuid.uuid4().hex)
        order['id'] = order_id
        seen.add(order_id)
        conn.execute(f"""INSERT INTO {orders_table}
            (id, timestamp, status, voided, total, subtotal, discount_amount, payment,
             cash_amount, card_amount, customer, table_no, order_type, cashier_name, note, payload, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET timestamp=excluded.timestamp, status=excluded.status,
              voided=excluded.voided, total=excluded.total, subtotal=excluded.subtotal,
              discount_amount=excluded.discount_amount, payment=excluded.payment,
              cash_amount=excluded.cash_amount, card_amount=excluded.card_amount,
              customer=excluded.customer, table_no=excluded.table_no, order_type=excluded.order_type,
              cashier_name=excluded.cashier_name, note=excluded.note, payload=excluded.payload,
              updated_at=excluded.updated_at""", _order_row_values(order))
        conn.execute(f'DELETE FROM {items_table} WHERE order_id=?', (order_id,))
        for index, item in enumerate(order.get('items', []) or []):
            if not isinstance(item, dict):
                continue
            conn.execute(f"""INSERT INTO {items_table}
                (order_id, item_index, name, qty, price, modifiers, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?)""", (
                    order_id, index, str(item.get('name') or ''),
                    float(item.get('quantity', item.get('qty', 0)) or 0),
                    float(item.get('price', 0) or 0),
                    json.dumps(item.get('modifiers', ''), ensure_ascii=False),
                    json.dumps(item, ensure_ascii=False, separators=(',', ':'))))
    if prune and seen:
        marks = ','.join('?' for _ in seen)
        conn.execute(f'DELETE FROM {orders_table} WHERE id NOT IN ({marks})', tuple(seen))
        conn.execute(f'DELETE FROM {items_table} WHERE order_id NOT IN ({marks})', tuple(seen))
    elif prune:
        conn.execute(f'DELETE FROM {items_table}')
        conn.execute(f'DELETE FROM {orders_table}')
    return len(seen)


def _compact_state_snapshot(data):
    """يفصل الأرشيف التاريخي عن لقطات JSON لتقليل كلفة كل حفظ.
    تبقى الفواتير الحية والبيانات التشغيلية، بينما مصدر الأرشيف الساخن هو SQLite."""
    snapshot = dict(data)
    snapshot['orders_archive'] = []
    snapshot.pop('_pending_order_sync_ids', None)
    return snapshot


def _hydrate_structured_archive(conn, data):
    """يعيد الفواتير الساخنة من SQLite إلى الذاكرة دون كتابتها إلى JSON."""
    live_ids = {str(order.get('id')) for order in data.get('orders', []) if isinstance(order, dict) and order.get('id')}
    rows = conn.execute('SELECT id, payload FROM orders ORDER BY timestamp, id').fetchall()
    archive = []
    for row in rows:
        if str(row['id']) in live_ids:
            continue
        try:
            order = json.loads(row['payload'])
        except (TypeError, ValueError):
            continue
        if isinstance(order, dict):
            archive.append(order)
    data['orders_archive'] = archive
    return data


def migrate_orders_to_structured(conn, payload):
    """يرحّل كل الفواتير إلى جداول مؤقتة ثم يستبدلها بعد تطابق العدد.
    العملية قابلة للإعادة ولا تحذف data.json أو app_state عند الفشل."""
    orders = [o for o in payload.get('orders', []) + payload.get('orders_archive', []) if isinstance(o, dict)]
    # SQLite يجعل id مفتاحاً أساسياً؛ أصلح التكرار قبل الإدراج حتى لا تسقط
    # عملية الاستعادة/الترقية كلها بسبب فاتورتين قديمتين تحملان الرقم نفسه.
    seen_ids = set()
    for order in orders:
        order_id = str(order.get('id') or uuid.uuid4().hex)
        if order_id in seen_ids:
            order['duplicate_id_repaired_from'] = str(order.get('id') or '')
            order_id = f'{order_id}-DUP-{uuid.uuid4().hex[:8].upper()}'
            order['id'] = order_id
        seen_ids.add(order_id)
    existing = conn.execute('SELECT version FROM migration_state WHERE name=?', ('orders',)).fetchone()
    if existing and int(existing['version']) >= STRUCTURED_SCHEMA_VERSION:
        return False
    conn.executescript('DROP TABLE IF EXISTS order_items_migration; DROP TABLE IF EXISTS orders_migration;')
    conn.executescript(_structured_table_sql('orders_migration', 'order_items_migration'))
    conn.execute('BEGIN IMMEDIATE')
    try:
        conn.execute('DELETE FROM order_items_migration')
        conn.execute('DELETE FROM orders_migration')
        count = _write_order_rows(conn, orders, 'orders_migration', 'order_items_migration')
        if count != len({str(o.get('id')) for o in orders if o.get('id') is not None}):
            raise RuntimeError('structured migration count mismatch')
        conn.execute('DELETE FROM order_items')
        conn.execute('DELETE FROM orders')
        conn.execute('INSERT INTO orders SELECT * FROM orders_migration')
        conn.execute('INSERT INTO order_items SELECT * FROM order_items_migration')
        conn.execute('DROP TABLE order_items_migration')
        conn.execute('DROP TABLE orders_migration')
        conn.execute('INSERT OR REPLACE INTO migration_state(name, version, completed_at, source_count) VALUES(?, ?, ?, ?)',
                     ('orders', STRUCTURED_SCHEMA_VERSION, datetime.now().isoformat(), count))
        conn.execute('COMMIT')
        return True
    except Exception:
        conn.execute('ROLLBACK')
        raise


def sync_structured_orders(conn, payload):
    """مزامنة تفاضلية خلال فترة الانتقال دون إعادة كتابة كامل الأرشيف."""
    orders = [o for o in payload.get('orders', []) + payload.get('orders_archive', []) if isinstance(o, dict)]
    current = {}
    for order in orders:
        order_id = str(order.get('id') or uuid.uuid4().hex)
        order['id'] = order_id
        current[order_id] = order
    existing_rows = conn.execute('SELECT id, payload FROM orders').fetchall()
    existing = {str(row['id']): row['payload'] for row in existing_rows}
    changed = []
    for order_id, order in current.items():
        payload_text = json.dumps(order, ensure_ascii=False, separators=(',', ':'))
        if existing.get(order_id) != payload_text:
            changed.append(order)
    deleted = set(existing) - set(current)
    conn.execute('BEGIN IMMEDIATE')
    try:
        if changed:
            _write_order_rows(conn, changed, prune=False)
        if deleted:
            marks = ','.join('?' for _ in deleted)
            conn.execute(f'DELETE FROM orders WHERE id IN ({marks})', tuple(deleted))
        conn.execute('COMMIT')
    except Exception:
        conn.execute('ROLLBACK')
        raise


def init_database():
    """ينشئ SQLite ويرحّل data.json القديم دون حذف النسخة الأصلية."""
    conn = db_connect()
    try:
        if conn.execute('SELECT 1 FROM app_state WHERE id=1').fetchone() is None:
            try:
                with open(DATA_FILE, 'r', encoding='utf-8') as handle:
                    payload = json.load(handle)
            except (OSError, ValueError):
                payload = {"menu": {}, "orders": [], "shifts": [], "log": [], "settings": {"currency": "SYP"}}
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('INSERT INTO app_state(id, payload, updated_at) VALUES(1, ?, ?)',
                         (json.dumps(payload, ensure_ascii=False), datetime.now().isoformat()))
            conn.execute('COMMIT')
        row = conn.execute('SELECT payload FROM app_state WHERE id=1').fetchone()
        payload = json.loads(row['payload']) if row else {}
        migrate_orders_to_structured(conn, payload)
        compact_payload = _compact_state_snapshot(payload)
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('UPDATE app_state SET payload=?, updated_at=? WHERE id=1',
                     (json.dumps(compact_payload, ensure_ascii=False, separators=(',', ':')), datetime.now().isoformat()))
        conn.execute('COMMIT')
    finally:
        conn.close()


init_database()

LOG_DIR = os.path.join(VAULT_DIR, 'logs')
os.makedirs(LOG_DIR, exist_ok=True)

COLD_ARCHIVE_DIR = os.path.join(VAULT_DIR, 'archive_cold')
os.makedirs(COLD_ARCHIVE_DIR, exist_ok=True)
# يبقى آخر 120 يومًا (~4 أشهر) من الفواتير المؤرشفة داخل data.json الحيّ؛ الأقدم
# يُنقل تلقائيًا لملفات شهرية باردة بمجلد archive_cold/ حتى لا يتضخم ملف البيانات
# الأساسي عبر السنين ويُبطئ كل عملية قراءة/كتابة (معادل عملي لـ VACUUM بقواعد
# البيانات التقليدية). لا شيء يُحذف نهائياً — فقط يُنقل، ويبقى قابلاً للاسترجاع.
ARCHIVE_RETENTION_DAYS = 30
HELD_ORDER_MAX_AGE_HOURS = 48
# استقرار طويل الأمد: بدون هذا الحد، طلب معلّق يُنسى (جهاز أُغلق قبل الاسترجاع،
# نهاية وردية بلا استرجاع...) يبقى للأبد بـ data.json وقد يتراكم بمئات السجلات
# مع الوقت. يُحذف تلقائياً عبر prune_stale_held_orders() لأنه سلة غير مكتملة
# بلا قيمة محاسبية أصلاً - على عكس orders/orders_archive التي لا تُحذف إطلاقاً.


def prune_stale_held_orders(data, max_age_hours=HELD_ORDER_MAX_AGE_HOURS):
    held = data.get('held_orders', [])
    if not held:
        return False
    cutoff = datetime.now() - timedelta(hours=max_age_hours)
    kept, changed = [], False
    for row in held:
        try:
            held_at = datetime.fromisoformat(str(row.get('held_at', '')))
        except ValueError:
            kept.append(row); continue
        if held_at >= cutoff:
            kept.append(row)
        else:
            changed = True
    if changed:
        data['held_orders'] = kept
    return changed


import logging
from logging.handlers import RotatingFileHandler

error_logger = logging.getLogger('caesar_errors')
error_logger.setLevel(logging.ERROR)
_log_handler = RotatingFileHandler(
    os.path.join(LOG_DIR, 'error.log'), maxBytes=2 * 1024 * 1024, backupCount=5, encoding='utf-8'
)
# ملف السجل بحد أقصى 2 ميجابايت، وآخر 5 نسخ محفوظة (10 ميجا كحد أقصى إجمالي) — لا يتراكم بلا حدود أبداً.
_log_handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))
error_logger.addHandler(_log_handler)
# In a PyInstaller OneFolder deployment, mirror the same traceback beside the
# executable so the operator can retrieve it without knowing the vault path.
# This is intentionally best-effort: a read-only install must not stop the POS.
try:
    _runtime_log_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _runtime_log_handler = RotatingFileHandler(
        os.path.join(_runtime_log_dir, 'caesar_server_error.log'),
        maxBytes=2 * 1024 * 1024, backupCount=3, encoding='utf-8'
    )
    _runtime_log_handler.setFormatter(logging.Formatter('%(asctime)s | %(levelname)s | %(message)s'))
    error_logger.addHandler(_runtime_log_handler)
except (OSError, ValueError):
    pass
# إسكات لوغ Werkzeug الافتراضي (سطر لكل طلب) عن الطرفية — سجل الأخطاء الحقيقية فقط هو المهم هنا.
logging.getLogger('werkzeug').setLevel(logging.ERROR)

app = Flask(__name__, static_folder=BASE_DIR, static_url_path='')
# جلسات محلية قصيرة العمر؛ لا تُقرأ من JavaScript ولا تُرسل لمواقع أخرى.
# مفتاح التوقيع يُنشأ مرة واحدة ويُحفظ بمجلد البيانات (مو عشوائي بكل إقلاع) —
# سابقاً كان app.secret_key = os.urandom(32) يتغيّر مع كل تشغيل، فيسجّل خروج
# كل المستخدمين المسجّلين تلقائياً عند أي إعادة تشغيل (انقطاع كهرباء، تحديث...).
SECRET_KEY_FILE = os.path.join(VAULT_DIR, '.session_secret')
try:
    with open(SECRET_KEY_FILE, 'rb') as f:
        app.secret_key = f.read()
    if len(app.secret_key) != 32:
        raise ValueError('invalid key length')
except (OSError, ValueError):
    app.secret_key = os.urandom(32)
    with open(SECRET_KEY_FILE, 'wb') as f:
        f.write(app.secret_key)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_SECURE=False,
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    # Reject oversized JSON/multipart bodies before application handlers parse them.
    MAX_CONTENT_LENGTH=2 * 1024 * 1024,
)


@app.errorhandler(Exception)
def handle_unexpected_error(error):
    """سياسة عدم الانهيار: أي خطأ غير متوقع بأي مسار API يُسجَّل بالتفصيل
    (بما فيها تتبّع الاستدعاء الكامل) بملف logs/error.log، ويستمر الخادم
    بالعمل طبيعياً لبقية الطلبات — بدل صفحة خطأ خام أو توقف صامت لا يترك أثراً."""
    from werkzeug.exceptions import HTTPException
    if isinstance(error, HTTPException) and error.code != 500:
        # أخطاء HTTP العادية (404 صفحة غير موجودة، 405 طريقة غير مسموحة...) ليست أعطالاً
        # حقيقية بالكود، فلا داعي لتسجيلها بسجل الأخطاء — نمررها بردّها الافتراضي فقط.
        # أما InternalServerError (500) فيجب أن يمر عبر مسار التسجيل أدناه؛ وإلا
        # سيعرض Werkzeug صفحة عامة ويخفي السبب الحقيقي عن سجل CAESAR.
        return error
    error_logger.error(
        'خطأ غير متوقع | %s %s | من: %s\n%s',
        request.method, request.path, request.remote_addr,
        traceback.format_exc()
    )
    if request.path.startswith('/api/'):
        return jsonify({'ok': False, 'error': 'حدث خطأ غير متوقع بالخادم. تم تسجيله وسيستمر البرنامج بالعمل.'}), 500
    return 'حدث خطأ غير متوقع. راجع سجل الأخطاء داخل مجلد logs.', 500
DATA_LOCK = threading.RLock()
PASSWORD_ITERATIONS = 260_000
MAX_ORDER_QTY = 100
LOGIN_MAX_FAILURES = 5
LOGIN_BASE_LOCK_SECONDS = 60
LOGIN_MAX_LOCK_SECONDS = 15 * 60


def _login_throttle_key(username, ip_address):
    # Keep usernames/IPs out of the persisted operational data while ensuring
    # independent throttling for each account and source address.
    raw = f'{str(username or "").strip().lower()}\x00{str(ip_address or "unknown")}'
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def login_throttle_remaining(data, username, ip_address):
    row = data.setdefault('_login_throttle', {}).get(_login_throttle_key(username, ip_address), {})
    try:
        return max(0, int(float(row.get('locked_until', 0)) - time.time()))
    except (TypeError, ValueError):
        return 0


def login_throttle_error(data, username, ip_address):
    """يعيد رد القفل الموحد، أو None إن كان إدخال كلمة المرور مسموحاً."""
    remaining = login_throttle_remaining(data, username, ip_address)
    if remaining:
        return jsonify({'ok': False, 'error': f'محاولات كثيرة؛ أعد المحاولة بعد {remaining} ثانية'}), 429
    return None


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


def migrate_printer_settings(data):
    """يكمل إعدادات الطباعة الناقصة في النسخ القديمة بعد ترحيل SQLite.

    بعض النسخ القديمة خزّنت اسم الطابعة فقط، بينما لم تكن أعلام الطباعة
    التلقائية موجودة أصلًا. تركها مفقودة يجعل ``bool(None)`` يعطّل الطباعة
    بصمت. نضيف القيم الافتراضية فقط عند غياب المفتاح، ونحافظ على ``False``
    الذي اختاره المدير صراحةً.
    """
    settings = data.setdefault('settings', {})
    printer = settings.setdefault('printer', {})
    changed = False
    defaults = {
        'connection_mode': 'windows',
        'printer_transport': 'auto',
        'printer_family': 'auto',
        'printer_timeout': 5,
        'printer_retry_count': 1,
        'network_port': 9100,
        'auto_print_receipt': True,
        'auto_print_kitchen': True,
    }
    for key, value in defaults.items():
        if key not in printer:
            printer[key] = value
            changed = True
    return changed


def atomic_write_json(path, data):
    """يكتب JSON ذرياً حتى لا تُتلف الفاتورة أو انقطاع الكهرباء ملف البيانات."""
    directory = os.path.dirname(path) or '.'
    fd, temp_path = tempfile.mkstemp(prefix='.caesar_', suffix='.tmp', dir=directory)
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


def _order_stamp(order):
    return str(order.get('timestamp') or order.get('date') or '')


def _order_month_key(order):
    stamp = _order_stamp(order)
    return stamp[:7] if len(stamp) >= 7 else 'unknown'


def _cold_archive_path(month_key):
    safe = month_key if month_key and month_key != 'unknown' else 'unknown'
    return os.path.join(COLD_ARCHIVE_DIR, f'orders_{safe}.json')


def compact_old_archive(data, retention_days=ARCHIVE_RETENTION_DAYS):
    """ينقل فواتير orders_archive الأقدم من retention_days إلى ملفات شهرية باردة
    خارج data.json الحيّ. آمن تماماً: لا يلمس data['orders'] (الطلبات المفتوحة/
    الحيّة الحالية) إطلاقاً، ولا يحذف أي فاتورة — فقط ينقلها لمكان بارد قابل
    للاسترجاع عبر load_cold_orders()/find_order_anywhere(). يُستدعى تلقائياً بعد
    كل عملية 'تصفير عداد'، وكذلك دورياً (مرة يومياً كحد أقصى) من load() كشبكة
    أمان حتى لو لم يُستخدم زر التصفير مطلقاً."""
    archive = data.get('orders_archive', [])
    if not archive:
        return False
    cutoff = (datetime.now() - timedelta(days=retention_days)).strftime('%Y-%m-%d')
    keep, to_move = [], []
    for o in archive:
        stamp = _order_stamp(o)[:10]
        (to_move if stamp and stamp < cutoff else keep).append(o)
    if not to_move:
        return False
    by_month = {}
    for o in to_move:
        by_month.setdefault(_order_month_key(o), []).append(o)
    for month_key, orders in by_month.items():
        path = _cold_archive_path(month_key)
        existing = []
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
            except (OSError, ValueError):
                existing = []
        existing_ids = {str(o.get('id')) for o in existing}
        merged = existing + [o for o in orders if str(o.get('id')) not in existing_ids]
        atomic_write_json(path, merged)
    data.setdefault('_pending_order_sync_ids', []).extend(str(o.get('id')) for o in to_move if o.get('id'))
    data['orders_archive'] = keep
    return True


def list_cold_months():
    try:
        names = os.listdir(COLD_ARCHIVE_DIR)
    except OSError:
        return []
    return sorted(n[len('orders_'):-len('.json')] for n in names if n.startswith('orders_') and n.endswith('.json'))


def load_cold_orders(date_from='', date_to=''):
    """يحمّل فواتير الأرشيف البارد (أقدم من فترة الاحتفاظ) عند الحاجة فقط — تقارير
    بمدى تاريخي قديم، أو إعادة طباعة/بحث عن فاتورة قديمة. لا تُستخدم إطلاقاً بمسار
    العمليات اليومية العادي (إنشاء/تعديل فاتورة) حتى لا تؤثر على سرعته."""
    months = list_cold_months()
    if date_from or date_to:
        months = [m for m in months if m == 'unknown' or
                  ((not date_from or m >= date_from[:7]) and (not date_to or m <= date_to[:7]))]
    result = []
    for m in months:
        try:
            with open(_cold_archive_path(m), 'r', encoding='utf-8') as f:
                result.extend(json.load(f))
        except (OSError, ValueError):
            continue
    return result


def find_order_anywhere(data, order_id):
    """يبحث عن فاتورة بمعرفها بالطلبات الحيّة/المؤرشفة، وإن لم يجدها يفتّش
    بالأرشيف البارد كخطوة أخيرة نادرة (فواتير أقدم من ~4 أشهر)."""
    order = next((row for row in data.get('orders', []) + data.get('orders_archive', [])
                  if str(row.get('id')) == str(order_id) and not row.get('voided')), None)
    if order:
        return order
    return next((row for row in load_cold_orders()
                 if str(row.get('id')) == str(order_id) and not row.get('voided')), None)


def load():
    """تحميل الحالة مع إبقاء json.loads خارج DATA_LOCK دون قراءة قديمة.

    تُقرأ الحمولة الخام وإصدارها تحت القفل، ثم تُفك خارج القفل. بعد ذلك يعاد
    أخذ القفل والتحقق من الإصدار؛ إذا سبقتنا كتابة متزامنة تعاد الدورة، وإذا
    تطابق الإصدار تُطبّق الصيانة والحفظ داخل القفل نفسه لمنع clobber لبيانات أحدث.
    """
    while True:
        with DATA_LOCK:
            conn = db_connect()
            try:
                row = conn.execute('SELECT payload, updated_at FROM app_state WHERE id=1').fetchone()
                if row:
                    raw_payload = row['payload']
                    snapshot_version = row['updated_at']
                else:
                    try:
                        with open(DATA_FILE, 'r', encoding='utf-8') as handle:
                            raw_payload = handle.read()
                    except OSError:
                        raw_payload = '{}'
                    snapshot_version = None
            finally:
                conn.close()

        try:
            data = json.loads(raw_payload)
        except (TypeError, ValueError):
            data = {}

        with DATA_LOCK:
            conn = db_connect()
            try:
                current = conn.execute('SELECT updated_at FROM app_state WHERE id=1').fetchone()
                current_version = current['updated_at'] if current else None
                if snapshot_version is not None and current_version != snapshot_version:
                    continue
                if snapshot_version is None and current is not None:
                    continue
                if snapshot_version is None:
                    conn.execute('BEGIN IMMEDIATE')
                    conn.execute('INSERT OR IGNORE INTO app_state(id, payload, updated_at) VALUES(1, ?, ?)',
                                 (json.dumps(data, ensure_ascii=False), datetime.now().isoformat()))
                    conn.execute('COMMIT')
                _hydrate_structured_archive(conn, data)
            finally:
                conn.close()

            changed = ensure_ids(data)
            if migrate_legacy_users(data):
                changed = True
            if ensure_inventory(data):
                changed = True
            if migrate_printer_settings(data):
                changed = True
            maint = data.setdefault('_maintenance', {})
            today = datetime.now().strftime('%Y-%m-%d')
            if maint.get('last_compaction') != today:
                # شبكة أمان يومية: تنقل فواتير الأرشيف القديمة لملفات باردة حتى لو
                # لم يُستخدم زر 'تصفير العداد' إطلاقاً — تُفحص مرة واحدة كحد أقصى
                # باليوم (وليس بكل طلب) حتى لا تُبطئ المسار الحرج للتطبيق.
                if compact_old_archive(data):
                    changed = True
                if prune_stale_held_orders(data):
                    changed = True
                maint['last_compaction'] = today
                changed = True
            if changed:
                _save_database(data)
            return data


def load_snapshot_only():
    """يقرأ الحالة المختصرة من SQLite مع fallback آمن لملف JSON القديم.

    هذا مهم عند أول تشغيل/الترقية وقبل أن تُنشئ ``load()`` صف الحالة في
    SQLite، كما يحافظ على عزل اختبارات النسخ القديمة التي تجهّز DATA_FILE
    مباشرةً.
    """
    conn = db_connect()
    try:
        row = conn.execute('SELECT payload FROM app_state WHERE id=1').fetchone()
        raw = row['payload'] if row else None
    finally:
        conn.close()
    if raw is None and os.path.exists(DATA_FILE):
        try:
            raw = Path(DATA_FILE).read_text(encoding='utf-8')
        except OSError:
            raw = '{}'
    raw = raw or '{}'
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}


def _save_database(data, changed_order_ids=None):
    pending_ids = data.pop('_pending_order_sync_ids', [])
    changed_order_ids = {str(value) for value in list(changed_order_ids or []) + list(pending_ids) if value}
    payload = json.dumps(_compact_state_snapshot(data), ensure_ascii=False, separators=(',', ':'))
    conn = db_connect()
    try:
        conn.execute('BEGIN IMMEDIATE')
        conn.execute('UPDATE app_state SET payload=?, updated_at=? WHERE id=1',
                     (payload, datetime.now().isoformat()))
        # Keep the legacy-compatible snapshot and structured orders in one
        # transaction. The incremental helper is called inline so a checkout
        # does not rewrite the entire historical order archive.
        order_map = {}
        if changed_order_ids:
            remaining = set(changed_order_ids)
            for order in data.get('orders', []) + data.get('orders_archive', []):
                if not isinstance(order, dict) or not order.get('id'):
                    continue
                order_id = str(order['id'])
                if order_id in remaining:
                    order_map[order_id] = order
                    remaining.remove(order_id)
                    if not remaining:
                        break
        changed = [order_map[order_id] for order_id in changed_order_ids if order_id in order_map]
        if changed:
            _write_order_rows(conn, changed, prune=False)
        deleted = changed_order_ids - set(order_map)
        if deleted:
            marks = ','.join('?' for _ in deleted)
            conn.execute(f'DELETE FROM orders WHERE id IN ({marks})', tuple(deleted))
        conn.execute('COMMIT')
    except Exception:
        try:
            conn.execute('ROLLBACK')
        except sqlite3.Error:
            pass
        raise
    finally:
        conn.close()
    # يبقى ملف JSON المتوافق نسخة كاملة وحديثة للاسترداد عند فقد SQLite، وليس
    # لقطة مضغوطة راكدة تخلو من الأرشيف الساخن.
    try:
        atomic_write_json(DATA_FILE, data)
    except OSError:
        error_logger.error('فشل تحديث DATA_FILE الكامل بعد حفظ SQLite إلى %s', DATA_FILE, exc_info=True)


def save(data, changed_order_ids=None):
    with DATA_LOCK:
        _save_database(data, changed_order_ids)
        try:
            atomic_write_json(FLASH_BACKUP, _compact_state_snapshot(data))
        except OSError:
            error_logger.error('فشلت النسخة الاحتياطية الفورية (FLASH_BACKUP) إلى %s', FLASH_BACKUP, exc_info=True)


_last_backup_at = 0.0
_last_backup_date = ''
BACKUP_FORMAT_VERSION = 2
DAILY_BACKUP_RETENTION_DAYS = 90


def build_backup_bundle(data=None):
    """ينشئ نسخة قابلة للاستعادة تشمل الحالة الساخنة والأرشيف البارد."""
    state = data if data is not None else load()
    state_copy = json.loads(json.dumps(state, ensure_ascii=False))
    cold = {}
    for month in list_cold_months():
        try:
            with open(_cold_archive_path(month), 'r', encoding='utf-8') as handle:
                rows = json.load(handle)
        except (OSError, ValueError) as exc:
            raise ValueError(f'تعذر تضمين الأرشيف البارد للشهر {month}') from exc
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError(f'أرشيف الشهر {month} غير صالح')
        cold[month] = rows
    return {
        'format_version': BACKUP_FORMAT_VERSION,
        'created_at': datetime.now().isoformat(),
        'state': state_copy,
        'archive_cold': cold,
    }


def _prune_backup_family(prefix, keep):
    try:
        files = sorted(name for name in os.listdir(BACKUP_DIR)
                       if name.startswith(prefix) and name.endswith('.json'))
    except OSError:
        return
    for old in files[:-keep]:
        try:
            os.remove(os.path.join(BACKUP_DIR, old))
        except OSError:
            error_logger.warning('تعذر تقليم النسخة الاحتياطية %s', old, exc_info=True)


def backup(force=False):
    """يأخذ لقطة احتياطية مؤرشفة من data.json. ملاحظة مهمة: هذا منفصل تماماً عن
    save() — كل عملية تُحفظ فوراً وبأمان عبر save() (كتابة ذرية + نسخة فلاش
    فورية) بغض النظر عن هذه الدالة؛ هذه فقط تلتقط "صورة تاريخية" إضافية بمجلد
    backups/ يمكن الرجوع إليها لاحقاً. لتفادي نسخ الملف بالكامل عشرات المرات
    خلال ثوانٍ (مثلاً عند إضافة عدة أصناف متتالية لنفس الطلب)، لا تُنشئ لقطة
    جديدة إن كان آخر لقطة أُخذت قبل أقل من 20 ثانية — إلا إذا force=True
    (يُستخدم بزر "نسخة احتياطية الآن" اليدوي بالإعدادات) أو إذا تغيّر التاريخ
    منذ آخر لقطة (ضمان نسخة واحدة على الأقل يومياً حتى بيوم هادئ قليل العمليات)."""
    global _last_backup_at, _last_backup_date
    with DATA_LOCK:
        now = time.monotonic()
        today = datetime.now().strftime('%Y-%m-%d')
        day_changed = today != _last_backup_date
        if not force and not day_changed and (now - _last_backup_at) < 20:
            return
        _last_backup_at = now
        _last_backup_date = today
        ts = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        bundle = build_backup_bundle()
        atomic_write_json(os.path.join(BACKUP_DIR, f'backup_{ts}.json'), bundle)
        # اليومية منفصلة عن حد النسخ السريعة؛ يحدّثها آخر حفظ ناجح في اليوم.
        atomic_write_json(os.path.join(BACKUP_DIR, f'daily_{today}.json'), bundle)
        _prune_backup_family('backup_', 30)
        _prune_backup_family('daily_', DAILY_BACKUP_RETENTION_DAYS)

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
    # إصلاح نسخ قديمة أُنشئت بعد تصفير العداد: لا نسمح بمعرّفين متساويين
    # لأن SQLite والأرشيف والتقارير تتعامل مع رقم الفاتورة كمعرّف فريد.
    seen_order_ids = set()
    for bucket in ('orders', 'orders_archive'):
        for order in data.get(bucket, []):
            if not isinstance(order, dict):
                continue
            original = str(order.get('id') or '')
            if not original:
                order['id'] = uuid.uuid4().hex
                changed = True
            elif original in seen_order_ids:
                order['id'] = f'{original}-DUP-{uuid.uuid4().hex[:8].upper()}'
                order['duplicate_id_repaired_from'] = original
                changed = True
            seen_order_ids.add(str(order['id']))
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
    raw_rate = payload.get('exchange_rate') or (1 if currency == 'SYP' else settings.get('usd_rate' if currency == 'USD' else 'eur_rate', 0)) or 0
    try:
        rate = float(raw_rate)
        if not math.isfinite(rate) or rate < 0:
            rate = 0
    except (TypeError, ValueError):
        rate = 0
    return {'currency': currency, 'exchange_rate': rate}


def amount_in_base(data, amount, currency='SYP', exchange_rate=None):
    """تحويل مبلغ مدخل إلى الليرة السورية؛ سعر الصرف هو عدد الليرات لكل وحدة أجنبية."""
    try:
        value = Decimal(str(amount))
        if not value.is_finite():
            return None
        code = currency if currency in ('SYP', 'USD', 'EUR') else 'SYP'
        if code == 'SYP':
            return float(value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
        snap = currency_snapshot(data, {'currency': code, 'exchange_rate': exchange_rate})
        rate = Decimal(str(snap['exchange_rate']))
        if not rate.is_finite() or rate <= 0:
            return None
        return float((value * rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    except (InvalidOperation, TypeError, ValueError):
        return None


def expense_amount_base(data, expense):
    """قيمة المصروف بالليرة، مع دعم السجلات القديمة التي لم تخزن المبلغ المحول."""
    if 'amount_base' in expense and expense.get('amount_base') is not None:
        return round_money(expense.get('amount_base'))
    # مشتريات المواد ورواتب/سلف الموظفين كانت تحفظ دائماً بعملة الأساس.
    if expense.get('material_id') is not None or expense.get('employee_id') is not None:
        return round_money(expense.get('amount', 0))
    return amount_in_base(data, expense.get('amount', 0), expense.get('currency', 'SYP'), expense.get('exchange_rate'))

def next_order_id(data):
    """يولّد رقم فاتورة لا يتكرر بعد الأرشفة أو إعادة التشغيل."""
    today = datetime.now().strftime('%Y-%m-%d')
    last_date = data.get('settings', {}).get('last_order_date')
    if last_date != today:
        if data.get('orders'):
            shift_id = last_date or today
            data.setdefault('_pending_order_sync_ids', []).extend(str(o.get('id')) for o in data['orders'] if o.get('id'))
            for o in data['orders']:
                o['shift_id'] = shift_id
            data.setdefault('orders_archive', []).extend(data['orders'])
            data['orders'] = []
        data.setdefault('settings', {})['last_order_date'] = today
    used_numbers = set()
    used_ids = set()
    for row in data.get('orders', []) + data.get('orders_archive', []):
        if not isinstance(row, dict):
            continue
        order_id = str(row.get('id', ''))
        used_ids.add(order_id)
        if order_id.startswith('ORD-'):
            try:
                used_numbers.add(int(order_id[4:]))
            except ValueError:
                pass
    counter = max(int(data.get('order_counter', 0) or 0), max(used_numbers, default=0)) + 1
    while f"ORD-{counter:04d}" in used_ids:
        counter += 1
    data['order_counter'] = counter
    return f"ORD-{counter:04d}"

def commercial_setup_complete(data=None):
    """يحافظ على توافق النسخ القديمة ويكشف فقط قوالب البيع غير المهيأة."""
    data = data or load()
    settings = data.get('settings', {})
    commercial = settings.get('commercial', {})
    if commercial.get('setup_completed'):
        return True
    # النسخ القديمة التي تحتوي مطعمًا ومستخدمين تعتبر مهيأة ولا يعاد ضبطها.
    return bool(settings.get('restaurant', {}).get('name') and settings.get('users'))


def normalize_machine_id(value):
    return re.sub(r'[^A-Za-z0-9:_-]', '', str(value or '').strip()).upper()


def local_machine_id():
    """Stable offline identifier used by the owner key generator."""
    raw = '|'.join([
        platform.system(), platform.machine(), os.environ.get('COMPUTERNAME', ''),
        os.environ.get('HOSTNAME', ''), str(uuid.getnode()),
    ])
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:24].upper()


def license_number_for(machine_id):
    machine_id = normalize_machine_id(machine_id)
    return 'CAESAR-' + hashlib.sha256(machine_id.encode('utf-8')).hexdigest()[:12].upper()


def license_key_for(machine_id, number=None, secret=None):
    machine_id = normalize_machine_id(machine_id)
    number = (number or license_number_for(machine_id)).strip().upper()
    payload = f'{machine_id}|{number}'.encode('utf-8')
    digest = hmac.new(secret or LICENSE_SECRET, payload, hashlib.sha256).hexdigest().upper()
    return '-'.join(digest[i:i + 8] for i in range(0, 32, 8))


def verify_license(machine_id, number, key):
    """يتحقق من الترخيص بالسر المورّد المحمّل فقط، ويفشل مغلقًا عند غيابه."""
    if not LICENSE_SECRET:
        return False
    expected_number = license_number_for(machine_id)
    if not hmac.compare_digest(str(number or '').strip().upper(), expected_number):
        return False
    submitted_key = str(key or '').strip().upper()
    return hmac.compare_digest(submitted_key, license_key_for(machine_id, expected_number))


def installation_license_valid(data):
    """يتحقق من الترخيص المسجل في كل تشغيل وطلب، لا في شاشة الإعداد فقط."""
    commercial = data.get('settings', {}).get('commercial', {})
    if not commercial.get('setup_completed'):
        return True
    current_machine = local_machine_id()
    stored_machine = normalize_machine_id(commercial.get('machine_id', ''))
    number = commercial.get('license_id', '')
    key = commercial.get('license_key', '')
    return bool(stored_machine and stored_machine == current_machine and verify_license(current_machine, number, key))

def write_local_license(data):
    settings = data.setdefault('settings', {})
    commercial = settings.setdefault('commercial', {})
    license_data = {
        'product': 'CAESAR Al-CAESAR', 'edition': 'Standalone Restaurant',
        'license_id': commercial.get('license_id'), 'license_key': commercial.get('license_key', ''),
        'machine_id': commercial.get('machine_id', ''), 'algorithm': LICENSE_ALGORITHM,
        'instance_id': commercial.get('instance_id'),
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
    response = {'setup_completed': commercial_setup_complete(data), 'is_commercial_template': not commercial_setup_complete(data),
                    'restaurant_name': settings.get('restaurant', {}).get('name', ''),
                    'license_id': commercial.get('license_id', ''), 'machine_id': local_machine_id(),
                    'license_required': not commercial_setup_complete(data)}
    if not commercial_setup_complete(data):
        shipped = load_shipped_license()
        if shipped and verify_license(local_machine_id(), shipped['license_id'], shipped['license_key']):
            response['shipped_license'] = shipped
    return jsonify(response)

@app.route('/api/setup/initialize', methods=['POST'])
def setup_initialize():
    data = load()
    if commercial_setup_complete(data):
        return jsonify({'ok': False, 'error': 'هذه النسخة مهيأة مسبقًا. استخدم الإعدادات لتعديل بيانات المطعم.'}), 409
    payload = request.get_json(silent=True) or {}
    restaurant_name = str(payload.get('restaurant_name', '')).strip()
    manager_username = str(payload.get('manager_username', '')).strip()
    manager_password = str(payload.get('manager_password', ''))
    license_id = str(payload.get('license_id', '')).strip().upper()
    license_key = str(payload.get('license_key', '')).strip().upper()
    if not restaurant_name or not manager_username or len(manager_password) < 8:
        return jsonify({'ok': False, 'error': 'اسم المطعم واسم المدير وكلمة مرور من 8 أحرف على الأقل مطلوبة'}), 400
    if not license_id or not license_key or not verify_license(local_machine_id(), license_id, license_key):
        return jsonify({'ok': False, 'error': 'رقم الترخيص أو مفتاح الترخيص غير صالحين لهذا الجهاز'}), 403
    settings = data.setdefault('settings', {})
    settings['restaurant'] = {'name': restaurant_name, 'phone': str(payload.get('phone', '')).strip(), 'address': str(payload.get('address', '')).strip()}
    settings['currency'] = payload.get('currency', 'SYP') if payload.get('currency') in ('SYP', 'USD', 'EUR') else 'SYP'
    settings['users'] = [{'id': 1, 'username': manager_username, 'password_hash': hash_password(manager_password), 'role': 'manager'}]
    settings['commercial'] = {'setup_completed': True, 'vendor_master': False, 'instance_id': str(uuid.uuid4()),
                              'machine_id': local_machine_id(), 'license_id': license_id, 'license_key': license_key,
                              'owner_name': str(payload.get('owner_name', '')).strip(), 'created_at': datetime.now().isoformat()}
    save(data); backup(); write_local_license(data)
    # يبقى قالب المصنع نظيفًا داخل المصدر، بينما تحفظ بيانات العميل في الخزنة المحلية فقط.
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
    station = str(payload.get('kitchen_station', 'main') or 'main')
    if station not in KITCHEN_STATION_LABELS:
        return jsonify({'ok': False, 'error': 'محطة المطبخ غير صالحة'}), 400
    p = {"id": payload.get('id'), "name": payload.get('name'), "price": payload.get('price'),
          "image": payload.get('image', ''), "barcode": barcode,
         "modifiers": sanitize_modifier_options(payload.get('modifiers', [])), "combo_items": payload.get('combo_items', []),
         "kitchen_station": station, "offer_id": payload.get('offer_id')}
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
                if 'modifiers' in payload:
                    p['modifiers'] = sanitize_modifier_options(payload.get('modifiers', []))
                if 'kitchen_station' in payload:
                    station = str(payload.get('kitchen_station') or 'main')
                    if station not in KITCHEN_STATION_LABELS:
                        return jsonify({'ok': False, 'error': 'محطة المطبخ غير صالحة'}), 400
                    p['kitchen_station'] = station
                for key in ('combo_items', 'offer_id'):
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


def compute_product_cost_as_of(data, product, sold_at):
    """تكلفة استدراكية للفواتير القديمة من مشتريات مؤرخة حتى تاريخ البيع فقط.

    لا تُخمّن عند غياب تاريخ شراء أو تاريخ بيع؛ عندئذٍ تصنّف التكلفة غير معروفة
    بدلاً من إدخال مشتريات مستقبلية في ربح فترة سابقة.
    """
    recipe = product.get('recipe', []) if product else []
    sold_date = str(sold_at or '')[:10]
    if not recipe or len(sold_date) != 10:
        return None
    total_cost = 0.0
    for ingredient in recipe:
        name = ingredient.get('material', '')
        rows = [row for row in data.get('materials', []) if row.get('name') == name]
        if not rows or any(len(str(row.get('date') or row.get('timestamp') or '')[:10]) != 10 for row in rows):
            return None
        eligible = [row for row in rows if str(row.get('date') or row.get('timestamp'))[:10] <= sold_date]
        total_qty = sum(float(row.get('quantity', 0) or 0) for row in eligible)
        total_paid = sum(float(row.get('price', 0) or 0) for row in eligible)
        if total_qty <= 0:
            return None
        total_cost += (total_paid / total_qty) * float(ingredient.get('qty', 0) or 0)
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

def consume_inventory_for_order(data, items, order_id=''):
    """يخصم من المخزون حسب وصفة كل صنف مُباع، ويسجل الحركة بمرجع الفاتورة والكاشير قيصر."""
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
            used_qty = (ing.get('qty', 0) or 0) * qty_sold
            material_name = ing.get('material', '')
            sync_inventory_consume(data, material_name, used_qty)
            record_inventory_movement(data, material_name, -used_qty, 'sale_consumption',
                                      reference_type='order', reference_id=order_id,
                                      note='استهلاك وصفة عند بيع: ' + str(name))

def round_money(value):
    try:
        amount = Decimal(str(value if value is not None else 0))
        if not amount.is_finite():
            return 0.0
        return float(amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    except (InvalidOperation, TypeError, ValueError):
        return 0.0


def sum_money(values):
    total = Decimal('0')
    try:
        for value in values:
            amount = Decimal(str(value if value is not None else 0))
            if amount.is_finite():
                total += amount
        return float(total.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    except (InvalidOperation, TypeError, ValueError):
        return round_money(float(total))


def as_money(value, default=None):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite():
            return default
        amount = amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        return float(amount) if amount >= 0 else default
    except (InvalidOperation, TypeError, ValueError):
        return default


KITCHEN_STATION_LABELS = {
    'main': 'المطبخ الرئيسي', 'grill': 'الشواية', 'drinks': 'المشروبات',
    'fryer': 'المقالي', 'dessert': 'الحلويات',
}


def sanitize_modifier_options(raw_options):
    """ينظم خيارات الإضافة المسموحة ويمتنع عن قبول السعر القادم من شاشة الكاشير قيصر."""
    if not isinstance(raw_options, list):
        return []
    result, seen = [], set()
    for item in raw_options[:20]:
        name = str(item.get('name', '') if isinstance(item, dict) else item).strip()[:80]
        price = as_money(item.get('price', 0) if isinstance(item, dict) else 0, 0)
        if not name or name in seen or price is None:
            continue
        seen.add(name)
        result.append({'name': name, 'price': price})
    return result


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
        base_price = as_money(product.get('price'))
        if base_price is None:
            return None, 'سعر أحد الأصناف في المنيو غير صالح'
        catalog = {row['name']: row for row in sanitize_modifier_options(product.get('modifiers', []))}
        requested = item.get('modifiers', [])
        if not isinstance(requested, list):
            requested = []
        modifier_names = []
        for raw_modifier in requested[:10]:
            name = str(raw_modifier.get('name', '') if isinstance(raw_modifier, dict) else raw_modifier).strip()
            if name in catalog and name not in modifier_names:
                modifier_names.append(name)
        modifiers = [catalog[name] for name in modifier_names]
        modifier_total = sum_money(row['price'] for row in modifiers)
        station = str(product.get('kitchen_station', 'main') or 'main')
        if station not in KITCHEN_STATION_LABELS:
            station = 'main'
        unit_cost = compute_product_cost(data, product)
        approved.append({'product_id': product.get('id'), 'name': str(product.get('name', '')).strip(),
                         'base_price': base_price, 'modifier_total': modifier_total,
                         'price': sum_money((base_price, modifier_total)), 'quantity': qty,
                         'unit_cost_snapshot': round(float(unit_cost), 4) if unit_cost is not None else None,
                         'modifiers': modifiers, 'kitchen_station': station})
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
    if cash is None or card is None or round_money(cash + card) != round_money(total):
        return None, 'مبالغ الدفع المختلط يجب أن تساوي إجمالي الفاتورة'
    return {'payment': payment, 'cash_amount': cash, 'card_amount': card}, None


DEFAULT_MANAGER_APPROVAL_POLICY = {
    'discount_percent_limit': 10.0,
    'discount_amount_limit': 0.0,
    'require_void_refund': True,
}


def manager_approval_policy(data):
    raw = data.get('settings', {}).get('manager_approval_policy', {})
    raw = raw if isinstance(raw, dict) else {}
    percent_limit = as_money(raw.get('discount_percent_limit'), DEFAULT_MANAGER_APPROVAL_POLICY['discount_percent_limit'])
    amount_limit = as_money(raw.get('discount_amount_limit'), DEFAULT_MANAGER_APPROVAL_POLICY['discount_amount_limit'])
    return {
        'discount_percent_limit': min(100, max(0, percent_limit if percent_limit is not None else 10.0)),
        'discount_amount_limit': max(0, amount_limit if amount_limit is not None else 0.0),
        'require_void_refund': bool(raw.get('require_void_refund', True)),
    }


def effective_discount_pct(subtotal, discount_total):
    """النسبة الفعلية للخصم (نسبة + مبلغ ثابت معاً) كي لا يتجاوز الخصم الثابت حد موافقة المدير."""
    try:
        sub = Decimal(str(subtotal or 0)); disc = Decimal(str(discount_total or 0))
        if sub <= 0:
            return 0.0
        return float((disc / sub * 100).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))
    except (InvalidOperation, TypeError, ValueError):
        return 0.0


def manager_approval_required(data, discount_pct=0, discount_amount=0):
    policy = manager_approval_policy(data)
    return ((discount_pct > policy['discount_percent_limit']) or
            (policy['discount_amount_limit'] > 0 and discount_amount > policy['discount_amount_limit'])), policy


def verify_manager_approval(data, payload, action, amount=0, reference_id=''):
    """يتحقق من اعتماد مدير حقيقي ولا يخزن كلمة المرور، ثم يجهز سجلًا موجزًا للعملية."""
    approval = payload.get('manager_approval', {}) if isinstance(payload, dict) else {}
    approval = approval if isinstance(approval, dict) else {}
    users = active_users(data)
    if not users:
        return {'action': action, 'approved_by': 'مدير النظام المحلي', 'approved_at': datetime.now().isoformat(),
                'amount': round(float(amount or 0), 2), 'reference_id': str(reference_id)}, None
    if session.get('role') == 'manager' and not approval:
        username = session.get('username', 'مدير')
    else:
        username = str(approval.get('username', '')).strip()
        password = str(approval.get('password', ''))
        ip_address = request.remote_addr or 'unknown'
        throttled = login_throttle_error(data, username, ip_address)
        if throttled:
            return None, throttled
        manager = next((u for u in users if u.get('username') == username and u.get('role') == 'manager'), None)
        if not manager or not verify_password(manager.get('password_hash'), password):
            record_login_failure(data, username, ip_address)
            return None, (jsonify({'ok': False, 'approval_required': True,
                                   'error': 'هذه العملية تحتاج موافقة مدير وكلمة مرور صحيحة'}), 403)
        clear_login_failures(data, username, ip_address)
    record = {'id': uuid.uuid4().hex[:12], 'action': action, 'approved_by': username,
              'approved_at': datetime.now().isoformat(), 'amount': round(float(amount or 0), 2),
              'reference_id': str(reference_id)}
    data.setdefault('manager_approvals', []).append(record)
    data['manager_approvals'] = data['manager_approvals'][-500:]
    return record, None


def _structured_orders_page(date_from='', date_to='', limit=None, offset=0, include_voided=False):
    """يقرأ صفحة الفواتير مباشرة من SQLite دون تحميل الأرشيف إلى الذاكرة.
    الطلبات الملغاة تبقى محفوظة للتدقيق، لكنها لا تظهر في قائمة الطلبات
    التشغيلية إلا عند طلبها صراحةً عبر include_voided.
    """
    clauses, params = [], []
    if not include_voided:
        clauses.append('voided = 0')
    if date_from:
        clauses.append('substr(timestamp, 1, 10) >= ?'); params.append(date_from)
    if date_to:
        clauses.append('substr(timestamp, 1, 10) <= ?'); params.append(date_to)
    where = (' WHERE ' + ' AND '.join(clauses)) if clauses else ''
    conn = db_connect()
    try:
        total = conn.execute(f'SELECT COUNT(*) FROM orders{where}', tuple(params)).fetchone()[0]
        query = f'SELECT payload FROM orders{where} ORDER BY timestamp DESC, id DESC'
        query_params = list(params)
        if limit is not None:
            query += ' LIMIT ? OFFSET ?'; query_params.extend([limit, offset])
        rows = conn.execute(query, tuple(query_params)).fetchall()
        result = []
        for row in rows:
            try:
                value = json.loads(row['payload'])
            except (TypeError, ValueError):
                continue
            if isinstance(value, dict):
                result.append(value)
        return result, total
    finally:
        conn.close()


@app.route('/api/settings/manager-approvals', methods=['GET', 'POST'])
def manager_approval_settings():
    if not has_role('manager'):
        return permission_error()
    data = load()
    if request.method == 'GET':
        return jsonify({'ok': True, 'policy': manager_approval_policy(data),
                        'approvals': list(reversed(data.get('manager_approvals', [])))[:80]})
    payload = request.get_json(silent=True) or {}
    percent_limit = as_money(payload.get('discount_percent_limit'))
    amount_limit = as_money(payload.get('discount_amount_limit'))
    if percent_limit is None or amount_limit is None or not 0 <= percent_limit <= 100 or amount_limit < 0:
        return jsonify({'ok': False, 'error': 'حدود الموافقة غير صالحة'}), 400
    data.setdefault('settings', {})['manager_approval_policy'] = {
        'discount_percent_limit': percent_limit, 'discount_amount_limit': amount_limit,
        'require_void_refund': True,
    }
    save(data); backup()
    return jsonify({'ok': True, 'policy': manager_approval_policy(data)})


@app.route('/api/orders', methods=['GET', 'POST'])
def orders():
    if request.method == 'GET':
        date_from = request.args.get('from', '').strip()
        date_to = request.args.get('to', '').strip()
        scope = request.args.get('scope', '').strip().lower()
        if scope == 'today':
            today = datetime.now().strftime('%Y-%m-%d')
            date_from = date_to = today
        elif scope not in {'', 'today'}:
            return jsonify({'ok': False, 'error': 'نطاق طلبات غير صالح'}), 400
        limit_raw = request.args.get('limit', '').strip()
        offset_raw = request.args.get('offset', '0').strip()
        try:
            limit = max(1, min(int(limit_raw), 200)) if limit_raw else None
            offset = max(0, int(offset_raw or 0))
        except ValueError:
            return jsonify({'ok': False, 'error': 'limit أو offset غير صالح'}), 400
        include_voided = request.args.get('include_voided', '').strip().lower() in {'1', 'true', 'yes'}
        page, total = _structured_orders_page(date_from, date_to, limit, offset, include_voided)
        if limit is not None:
            return jsonify({'orders': page, 'total': total, 'offset': offset,
                            'limit': limit, 'has_more': offset + len(page) < total,
                            'scope': scope or 'all', 'from': date_from or None, 'to': date_to or None})
        return jsonify(page)

    data = load()
    if request.method == 'POST':
        payload = request.get_json(silent=True) or {}
        items, item_error = approved_order_items(data, payload.get('items'))
        if item_error:
            return jsonify({'ok': False, 'error': item_error}), 400
        subtotal = sum_money(item['price'] * item['quantity'] for item in items)
        discount_pct = as_money(payload.get('discount_pct', 0), 0)
        discount_amount = as_money(payload.get('discount_amount', 0), 0)
        if discount_pct is None or discount_pct > 100 or discount_amount is None:
            return jsonify({'ok': False, 'error': 'قيمة الخصم غير صالحة'}), 400
        after_percent = round_money(subtotal * (1 - discount_pct / 100))
        if discount_amount > after_percent:
            return jsonify({'ok': False, 'error': 'الخصم أكبر من إجمالي الفاتورة'}), 400
        total = round_money(after_percent - discount_amount)
        total_discount = round_money(subtotal - total)
        approval_record = None
        needs_approval, approval_policy = manager_approval_required(data, max(discount_pct, effective_discount_pct(subtotal, total_discount)), total_discount)
        if needs_approval:
            approval_record, approval_error = verify_manager_approval(data, payload, 'خصم فاتورة', total_discount)
            if approval_error:
                return approval_error
        payment_data, payment_error = normalize_payment(total, payload)
        if payment_error:
            return jsonify({'ok': False, 'error': payment_error}), 400
        order_type = str(payload.get('type', 'سفري') or 'سفري')
        if order_type not in {'سفري', 'صالة', 'ديليفري'}:
            return jsonify({'ok': False, 'error': 'نوع الطلب غير صالح'}), 400
        kitchen_release = str(payload.get('kitchen_release', 'now') or 'now')
        if kitchen_release not in {'now', 'later'}:
            return jsonify({'ok': False, 'error': 'خيار إطلاق المطبخ غير صالح'}), 400
        o = {
            'id': next_order_id(data), 'timestamp': datetime.now().isoformat(), 'items': items,
            'subtotal': subtotal, 'discount_pct': discount_pct, 'discount_amount': discount_amount,
            'discount_total': total_discount,
            'total': total, 'type': order_type, 'note': str(payload.get('note', ''))[:500],
            'customer': str(payload.get('customer', ''))[:120], 'table': str(payload.get('table', ''))[:60],
            'cashier_name': session.get('username', 'غير محدد'),
            'kitchen_status': 'held' if kitchen_release == 'later' else 'new', 'kitchen_release': kitchen_release,
            **payment_data
        }
        if approval_record:
            approval_record['reference_id'] = o['id']; o['manager_approval'] = approval_record
        if order_type == 'ديليفري':
            o['delivery_status'] = 'pending'
        snap = currency_snapshot(data, payload)
        o['currency'] = snap['currency']; o['exchange_rate'] = snap['exchange_rate']
        data.setdefault('orders', []).append(o)
        if payment_data.get('cash_amount', 0):
            record_cash_movement(data, 'in', payment_data['cash_amount'], 'مبيعات كاشير قيصر',
                                 channel='cash', reference_type='order', reference_id=o['id'],
                                 note='فاتورة ' + str(o['id']))
        if payment_data.get('card_amount', 0):
            record_cash_movement(data, 'in', payment_data['card_amount'], 'مبيعات كاشير قيصر',
                                 channel='card', reference_type='order', reference_id=o['id'],
                                 note='فاتورة ' + str(o['id']))
        consume_inventory_for_order(data, o['items'], o['id'])
        # حاجز متانة: لا يجوز أن يصل إيصال أو نبضة درج إلى العتاد قبل أن
        # تصبح الفاتورة نفسها قابلة للاسترجاع من SQLite والنسخ الاحتياطي.
        save(data, [o['id']]); backup()
        receipt_print = queue_thermal_print(data, o, 'receipt')
        kitchen_print = queue_thermal_print(data, o, 'kitchen') if kitchen_release == 'now' else {
            'ok': True, 'status': 'deferred', 'message': 'تذكرة المطبخ مؤجلة حتى إطلاق الطلب'}
        o['print_status'] = {'receipt': receipt_print, 'kitchen': kitchen_print}
        drawer_result = maybe_auto_open_cash_drawer(data, o, payment_data.get('cash_amount', 0))
        if drawer_result:
            o['cash_drawer_status'] = drawer_result
        save(data, [o['id']]); backup()
        return jsonify({'ok': True, 'id': o['id'], 'total': total, 'print': {'receipt': receipt_print, 'kitchen': kitchen_print}, 'drawer': drawer_result})
    include_voided = request.args.get('include_voided', '').strip().lower() in {'1', 'true', 'yes'}
    all_orders = data.get('orders', []) + data.get('orders_archive', [])
    if not include_voided:
        all_orders = [o for o in all_orders if not o.get('voided')]
    date_from = request.args.get('from', '').strip()
    date_to = request.args.get('to', '').strip()
    scope = request.args.get('scope', '').strip().lower()
    if scope == 'today':
        today = datetime.now().strftime('%Y-%m-%d')
        date_from = date_to = today
    elif scope not in {'', 'today'}:
        return jsonify({'ok': False, 'error': 'نطاق طلبات غير صالح'}), 400
    if date_from:
        all_orders = [o for o in all_orders if o.get('timestamp', o.get('date', ''))[:10] >= date_from]
    if date_to:
        all_orders = [o for o in all_orders if o.get('timestamp', o.get('date', ''))[:10] <= date_to]
    limit_raw = request.args.get('limit', '').strip()
    offset_raw = request.args.get('offset', '0').strip()
    if limit_raw:
        try:
            limit = max(1, min(int(limit_raw), 200))
            offset = max(0, int(offset_raw or 0))
        except ValueError:
            return jsonify({'ok': False, 'error': 'limit أو offset غير صالح'}), 400
        total = len(all_orders)
        page = all_orders[offset:offset + limit]
        return jsonify({'orders': page, 'total': total, 'offset': offset,
                        'limit': limit, 'has_more': offset + len(page) < total,
                        'scope': scope or 'all', 'from': date_from or None, 'to': date_to or None})
    return jsonify(all_orders)


def sanitize_held_items(raw_items):
    """ينظّف قائمة أصناف الطلب المعلّق القادمة من الواجهة (سلة خام، بلا تحقق مخزون بعد).
    يُعاد التحقق الكامل من المخزون والأسعار عند تحويل الطلب المعلّق فعلياً إلى فاتورة."""
    items = []
    if not isinstance(raw_items, list):
        return items, 'صيغة الأصناف غير صالحة'
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        quantity = as_money(raw.get('quantity', 1), 0) or 0
        if quantity <= 0:
            continue
        price = as_money(raw.get('price', 0), 0) or 0
        items.append({
            'id': raw.get('id'), 'name': str(raw.get('name', ''))[:120],
            'price': price, 'quantity': quantity, 'category': str(raw.get('category', ''))[:60],
        })
    if not items:
        return items, 'لا يمكن تعليق طلب فارغ'
    return items, None


@app.route('/api/held-orders', methods=['GET', 'POST'])
def held_orders():
    """تعليق واسترجاع الطلبات: يسمح للكاشير بحفظ سلة غير مكتملة على الخادم
    (بدلاً من التخزين المحلي فقط بالمتصفح) واسترجاعها لاحقاً من أي جهاز على نفس الشبكة."""
    data = load()
    if request.method == 'POST':
        payload = request.get_json(silent=True) or {}
        items, item_error = sanitize_held_items(payload.get('items'))
        if item_error:
            return jsonify({'ok': False, 'error': item_error}), 400
        order_type = str(payload.get('type', 'سفري') or 'سفري')
        if order_type not in {'سفري', 'صالة', 'ديليفري'}:
            order_type = 'سفري'
        payment = str(payload.get('payment', 'نقدي') or 'نقدي')
        subtotal = round(sum(item['price'] * item['quantity'] for item in items), 2)
        record = {
            'id': 'HOLD-' + uuid.uuid4().hex[:8].upper(), 'held_at': datetime.now().isoformat(),
            'items': items, 'type': order_type, 'payment': payment, 'subtotal': subtotal,
            'note': str(payload.get('note', ''))[:500], 'customer': str(payload.get('customer', ''))[:120],
            'table': str(payload.get('table', ''))[:60], 'label': str(payload.get('label', ''))[:80],
            'cashier_name': session.get('username', 'غير محدد'),
        }
        data.setdefault('held_orders', []).append(record)
        save(data); backup()
        return jsonify({'ok': True, 'id': record['id'], 'held_order': record})
    held = sorted(data.get('held_orders', []), key=lambda h: h.get('held_at', ''), reverse=True)
    return jsonify({'ok': True, 'held_orders': held})


@app.route('/api/held-orders/<hold_id>', methods=['DELETE'])
def delete_held_order(hold_id):
    """يحذف طلباً معلّقاً - يُستدعى عند استرجاعه إلى السلة الحالية أو عند إلغائه يدوياً."""
    data = load()
    held = data.get('held_orders', [])
    remaining = [h for h in held if h.get('id') != hold_id]
    if len(remaining) == len(held):
        return jsonify({'ok': False, 'error': 'الطلب المعلّق غير موجود'}), 404
    data['held_orders'] = remaining
    save(data); backup()
    return jsonify({'ok': True})


def check_manager_password(data, req_json):
    """يتحقق من كلمة مرور مدير مسجّل - يُستخدم لحماية أي عملية حساسة (إلغاء طلب، تعديل طلب).
    لو ما في مستخدمين مسجّلين بالنظام أصلاً، يسمح بالعملية بدون كلمة مرور (سلوك تدريجي)."""
    users = active_users(data)
    if not users:
        return True, None
    username = (req_json.get('username') or '').strip() if req_json else ''
    password = (req_json.get('password') or '') if req_json else ''
    ip_address = request.remote_addr or 'unknown'
    throttled = login_throttle_error(data, username, ip_address)
    if throttled:
        return False, throttled
    valid = any(
        u.get('username') == username
        and u.get('role', 'cashier') == 'manager'
        and verify_password(u.get('password_hash', u.get('password', '')), password)
        for u in users
    )
    if not valid:
        record_login_failure(data, username, ip_address)
        return False, (jsonify({"ok": False, "error": "كلمة مرور المدير غير صحيحة - العملية تحتاج موافقة مدير"}), 401)
    clear_login_failures(data, username, ip_address)
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
    محمي بكلمة مرور: لو في مستخدمين مسجّلين بالنظام، لازم تحقق ناجح قبل الإلغاء - لمنع أي كاشير قيصر
    من إلغاء طلب مدفوع فعلياً لإخفاء سرقة."""
    data = load()
    payload = request.get_json(silent=True) or {}
    approval_record, approval_error = verify_manager_approval(data, payload, 'إلغاء واسترجاع فاتورة', reference_id=order_id)
    if approval_error:
        return approval_error
    reason = payload.get('reason', '')
    for lst_name in ('orders', 'orders_archive'):
        for o in data.get(lst_name, []):
            if str(o.get('id')) == str(order_id):
                if o.get('voided'):
                    return jsonify({"ok": False, "error": "الطلب ملغى مسبقاً"})
                o['voided'] = True
                o['void_reason'] = reason
                o['void_date'] = datetime.now().isoformat()
                approval_record['reference_id'] = o.get('id'); o['void_manager_approval'] = approval_record
                # إرجاع المخزون المستهلك من هذا الطلب مع سجل تدقيقي للحركة العكسية.
                item_recipes = build_item_recipes(data)
                for i in o.get('items', []):
                    recipe = item_recipes.get(i.get('product_id', i.get('id'))) or item_recipes.get(i.get('name', ''))
                    if not recipe:
                        continue
                    qty_sold = i.get('quantity', i.get('qty', 1))
                    for ing in recipe:
                        returned_qty = (ing.get('qty', 0) or 0) * qty_sold
                        material_name = ing.get('material', '')
                        sync_inventory_add(data, material_name, '', returned_qty)
                        record_inventory_movement(data, material_name, returned_qty, 'void_return',
                                                  reference_type='void_order', reference_id=o.get('id'),
                                                  note='إرجاع من إلغاء فاتورة: ' + str(o.get('id')))
                # عكس المقبوضات لأن إلغاء الطلب يعني رد قيمة الفاتورة من الحساب الذي استلمها.
                if o.get('cash_amount', 0):
                    record_cash_movement(data, 'out', o.get('cash_amount'), 'استرجاع فاتورة ملغاة',
                                         channel='cash', reference_type='void_order', reference_id=o.get('id'),
                                         note='إلغاء فاتورة ' + str(o.get('id')))
                if o.get('card_amount', 0):
                    record_cash_movement(data, 'out', o.get('card_amount'), 'استرجاع فاتورة ملغاة',
                                         channel='card', reference_type='void_order', reference_id=o.get('id'),
                                         note='إلغاء فاتورة ' + str(o.get('id')))
                # يظل الأرشيف الساخن خارج لقطة JSON المختصرة، لذلك يجب تمرير
                # المعرّف كي تصل علامة voided إلى صف SQLite أيضاً.
                save(data, [o['id']]); backup()
                return jsonify({"ok": True})
    return jsonify({"ok": False, "error": "الطلب غير موجود"}), 404

def _is_debt_receipt_order(order):
    return order.get('type') == 'تسديد دين' or order.get('accounting_type') == 'debt_payment'


def _read_cold_order_archives():
    archives = []
    for month in list_cold_months():
        path = _cold_archive_path(month)
        with open(path, 'r', encoding='utf-8') as handle:
            rows = json.load(handle)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError('أحد ملفات أرشيف الطلبات غير صالح؛ أُوقف التنظيف لحماية البيانات')
        archives.append((path, rows))
    return archives


def _save_pre_cleanup_order_backup(data, cold_archives):
    backup_dir = os.path.join(VAULT_DIR, 'order_cleanup_backups')
    os.makedirs(backup_dir, exist_ok=True)
    snapshot = dict(data)
    snapshot['orders_archive'] = list(data.get('orders_archive', [])) + [
        row for _path, rows in cold_archives for row in rows
    ]
    snapshot.pop('_pending_order_sync_ids', None)
    snapshot['_order_cleanup_backup'] = {
        'created_at': datetime.now().isoformat(),
        'purpose': 'نسخة استرجاع قبل حذف فواتير الاختبار',
    }
    filename = 'orders_before_cleanup_' + datetime.now().strftime('%Y%m%d_%H%M%S_%f') + '.json'
    atomic_write_json(os.path.join(backup_dir, filename), snapshot)
    return filename


def _restore_inventory_for_hard_deleted_order(data, order):
    """يعيد استهلاك المخزون المسجل للبيع؛ الطلب الملغى سبق أن أعاد مخزونه."""
    if order.get('voided'):
        return
    order_id = str(order.get('id', ''))
    movements = [row for row in data.get('inventory_movements', [])
                 if str(row.get('reference_id', '')) == order_id
                 and row.get('reference_type') == 'order'
                 and row.get('type') == 'sale_consumption']
    if movements:
        for movement in movements:
            try:
                quantity = float(movement.get('quantity', 0) or 0)
            except (TypeError, ValueError):
                continue
            if quantity < 0:
                sync_inventory_add(data, movement.get('material', ''), movement.get('unit', ''), -quantity)
        return
    # توافق مع الفواتير القديمة التي سبقت دفتر حركات المخزون.
    recipes = build_item_recipes(data)
    for item in order.get('items', []) or []:
        recipe = recipes.get(item.get('product_id', item.get('id'))) or recipes.get(item.get('name', ''))
        if not recipe:
            continue
        try:
            sold = float(item.get('quantity', item.get('qty', 1)) or 0)
        except (TypeError, ValueError):
            continue
        for ingredient in recipe:
            try:
                quantity = float(ingredient.get('qty', 0) or 0) * sold
            except (TypeError, ValueError):
                continue
            sync_inventory_add(data, ingredient.get('material', ''), '', quantity)


def _remove_order_operational_records(data, order_ids):
    ids = {str(value) for value in order_ids}
    if not ids:
        return
    for key in ('cash_movements', 'cashbook'):
        if isinstance(data.get(key), list):
            data[key] = [row for row in data[key]
                         if str(row.get('reference_id', row.get('order_id', ''))) not in ids]
    if isinstance(data.get('inventory_movements'), list):
        data['inventory_movements'] = [row for row in data['inventory_movements']
                                       if str(row.get('reference_id', row.get('order_id', ''))) not in ids]
    if isinstance(data.get('kitchen_prep_log'), list):
        data['kitchen_prep_log'] = [row for row in data['kitchen_prep_log']
                                    if str(row.get('order_id', '')) not in ids]
    if isinstance(data.get('dine_in_sessions'), list):
        data['dine_in_sessions'] = [row for row in data['dine_in_sessions']
                                    if str(row.get('closed_order_id', '')) not in ids]


def _rewrite_cold_archives_without_orders(cold_archives, order_ids):
    ids = {str(value) for value in order_ids}
    changed_paths = []
    try:
        for path, rows in cold_archives:
            remaining = [row for row in rows if str(row.get('id', '')) not in ids]
            if len(remaining) == len(rows):
                continue
            if remaining:
                atomic_write_json(path, remaining)
            else:
                os.remove(path)
            changed_paths.append((path, rows))
    except OSError:
        for path, rows in changed_paths:
            try:
                atomic_write_json(path, rows)
            except OSError:
                pass
        raise


def _hard_delete_sales_orders(data, orders_to_delete, cold_archives, reset_counter=False):
    unique_orders = {}
    for order in orders_to_delete:
        if order.get('id'):
            unique_orders.setdefault(str(order['id']), order)
    orders_to_delete = list(unique_orders.values())
    order_ids = set(unique_orders)
    if not order_ids:
        return 0
    for order in orders_to_delete:
        _restore_inventory_for_hard_deleted_order(data, order)
    _remove_order_operational_records(data, order_ids)
    data['orders'] = [row for row in data.get('orders', []) if str(row.get('id', '')) not in order_ids]
    data['orders_archive'] = [row for row in data.get('orders_archive', []) if str(row.get('id', '')) not in order_ids]
    remaining_cold = [row for _path, rows in cold_archives for row in rows if str(row.get('id', '')) not in order_ids]
    if reset_counter and not (data['orders'] or data['orders_archive'] or remaining_cold):
        data['order_counter'] = 0
        data.setdefault('settings', {})['last_order_date'] = datetime.now().strftime('%Y-%m-%d')
    _rewrite_cold_archives_without_orders(cold_archives, order_ids)
    try:
        save(data, sorted(order_ids))
    except Exception:
        for path, rows in cold_archives:
            try:
                atomic_write_json(path, rows)
            except OSError:
                error_logger.error('تعذر استعادة ملف أرشيف الطلبات بعد فشل حذف الفواتير: %s', path, exc_info=True)
        raise
    try:
        backup(force=True)
    except Exception:
        error_logger.error('نجح حذف فواتير الاختبار لكن تعذر أخذ نسخة تلقائية بعد التنظيف', exc_info=True)
    return len(order_ids)


@app.route('/api/orders/<order_id>', methods=['DELETE'])
def hard_delete_order(order_id):
    """يحذف فاتورة بيع من السجلات التشغيلية؛ لا يُستخدم بدلاً من الإلغاء المحاسبي."""
    if not has_role('manager'):
        return permission_error()
    payload = request.get_json(silent=True) or {}
    if payload.get('confirmation') != 'DELETE ' + str(order_id):
        return jsonify({'ok': False, 'error': 'اكتب تأكيد الحذف المطلوب أولاً'}), 400
    data = load()
    try:
        cold_archives = _read_cold_order_archives()
    except (OSError, ValueError, json.JSONDecodeError):
        return jsonify({'ok': False, 'error': 'تعذر قراءة أرشيف الطلبات بأمان؛ لم يُحذف شيء'}), 500
    all_orders = data.get('orders', []) + data.get('orders_archive', []) + [
        row for _path, rows in cold_archives for row in rows
    ]
    order = next((row for row in all_orders if str(row.get('id', '')) == str(order_id)), None)
    if not order:
        return jsonify({'ok': False, 'error': 'الطلب غير موجود'}), 404
    if _is_debt_receipt_order(order):
        return jsonify({'ok': False, 'error': 'لا يمكن حذف تحصيل دين كفاتورة بيع؛ صحح سجل الدين من صفحة الديون'}), 409
    approval, approval_error = verify_manager_approval(data, payload, 'حذف نهائي لفاتورة بيع', reference_id=order_id)
    if approval_error:
        return approval_error
    approval['reference_id'] = str(order_id)
    try:
        backup_name = _save_pre_cleanup_order_backup(data, cold_archives)
        deleted = _hard_delete_sales_orders(data, [order], cold_archives)
    except Exception:
        error_logger.error('فشل الحذف النهائي للفاتورة %s', order_id, exc_info=True)
        return jsonify({'ok': False, 'error': 'تعذر حفظ الحذف أو تحديث الأرشيف؛ راجع النسخة الاحتياطية'}), 500
    return jsonify({'ok': True, 'deleted_orders': deleted, 'recovery_backup': backup_name})


@app.route('/api/orders', methods=['DELETE'])
def purge_test_orders():
    """ينظف فواتير البيع التجريبية ويبقي المنيو والإعدادات وسجلات الديون."""
    if not has_role('manager'):
        return permission_error()
    payload = request.get_json(silent=True) or {}
    if payload.get('confirmation') != 'DELETE_ALL_TEST_ORDERS':
        return jsonify({'ok': False, 'error': 'تأكيد التنظيف غير صحيح'}), 400
    data = load()
    try:
        cold_archives = _read_cold_order_archives()
    except (OSError, ValueError, json.JSONDecodeError):
        return jsonify({'ok': False, 'error': 'تعذر قراءة أرشيف الطلبات بأمان؛ لم يُحذف شيء'}), 500
    all_orders = data.get('orders', []) + data.get('orders_archive', []) + [
        row for _path, rows in cold_archives for row in rows
    ]
    sales_orders = [row for row in all_orders if not _is_debt_receipt_order(row)]
    if not sales_orders:
        return jsonify({'ok': True, 'deleted_orders': 0, 'recovery_backup': None})
    approval, approval_error = verify_manager_approval(data, payload, 'تنظيف فواتير البيع التجريبية')
    if approval_error:
        return approval_error
    approval['reference_id'] = 'all-test-sales-orders'
    try:
        backup_name = _save_pre_cleanup_order_backup(data, cold_archives)
        deleted = _hard_delete_sales_orders(data, sales_orders, cold_archives, reset_counter=True)
    except Exception:
        error_logger.error('فشل تنظيف فواتير البيع التجريبية', exc_info=True)
        return jsonify({'ok': False, 'error': 'تعذر حفظ التنظيف أو تحديث الأرشيف؛ راجع النسخة الاحتياطية'}), 500
    return jsonify({'ok': True, 'deleted_orders': deleted, 'recovery_backup': backup_name})

@app.route('/api/orders/<order_id>/edit-items', methods=['POST'])
def edit_order_items(order_id):
    """يعدّل أصناف الفاتورة بأسعار المنيو، ويضبط الخصم والتحصيل والمخزون بسجلات عكسية."""
    data = load()
    payload = request.get_json(silent=True) or {}
    ok, err = check_manager_password(data, payload)
    if not ok:
        return err
    new_items_raw = payload.get('items')
    reason = str(payload.get('reason', '') or '')[:240]
    if not isinstance(new_items_raw, list) or not new_items_raw:
        return jsonify({'ok': False, 'error': 'يجب أن تبقى الفاتورة محتوية على صنف واحد صالح على الأقل'}), 400

    for list_name in ('orders', 'orders_archive'):
        for order in data.get(list_name, []):
            if str(order.get('id')) != str(order_id):
                continue
            if order.get('voided'):
                return jsonify({'ok': False, 'error': 'الطلب ملغى، ما فيك تعدّله'}), 400
            items, item_error = approved_order_items(data, new_items_raw)
            if item_error:
                return jsonify({'ok': False, 'error': item_error}), 400

            subtotal = sum_money(item['price'] * item['quantity'] for item in items)
            discount_pct = as_money(order.get('discount_pct', 0), 0)
            fixed_discount = as_money(order.get('discount_amount', 0), 0)
            if discount_pct is None or discount_pct > 100 or fixed_discount is None:
                return jsonify({'ok': False, 'error': 'بيانات الخصم القديمة غير صالحة؛ أصلحها قبل تعديل الفاتورة'}), 400
            after_percent = round_money(subtotal * (1 - discount_pct / 100))
            if fixed_discount > after_percent:
                return jsonify({'ok': False, 'error': 'الخصم المحفوظ أكبر من إجمالي الأصناف الجديدة'}), 400
            new_total = round_money(after_percent - fixed_discount)
            total_discount = round_money(subtotal - new_total)

            old_total = round_money(order.get('total', 0))
            payment = order.get('payment', 'نقدي')
            if 'cash_amount' in order or 'card_amount' in order:
                old_cash = round_money(order.get('cash_amount', 0))
                old_card = round_money(order.get('card_amount', 0))
            elif payment == 'بطاقة':
                old_cash, old_card = 0.0, old_total
            elif payment == 'مختلط':
                return jsonify({'ok': False, 'error': 'لا يمكن تعديل فاتورة مختلطة قديمة بلا تقسيمة نقد/بطاقة محفوظة'}), 400
            else:
                old_cash, old_card = old_total, 0.0
            if round_money(old_cash + old_card) != old_total:
                return jsonify({'ok': False, 'error': 'تقسيمة الدفع الحالية لا تطابق إجمالي الفاتورة؛ سوّها قبل التعديل'}), 409
            if payment == 'نقدي':
                new_cash, new_card = new_total, 0.0
            elif payment == 'بطاقة':
                new_cash, new_card = 0.0, new_total
            elif payment == 'مختلط':
                if old_total <= 0:
                    return jsonify({'ok': False, 'error': 'لا يمكن تحديد توزيع الدفع الجديد لفاتورة مختلطة بإجمالي صفري'}), 409
                cash_ratio = old_cash / old_total
                new_cash = round_money(new_total * cash_ratio)
                new_card = round_money(new_total - new_cash)
            else:
                return jsonify({'ok': False, 'error': 'طريقة الدفع المسجلة غير صالحة'}), 400

            def item_key(item):
                pid = item.get('product_id', item.get('id'))
                return ('id', str(pid)) if pid not in (None, '') else ('name', str(item.get('name', '')).strip())

            old_qty, new_qty = {}, {}
            for item in order.get('items', []):
                key = item_key(item)
                old_qty[key] = old_qty.get(key, 0) + (item.get('quantity', item.get('qty', 1)) or 0)
            for item in items:
                key = item_key(item)
                new_qty[key] = new_qty.get(key, 0) + item['quantity']
            recipes = build_item_recipes(data)
            for key in set(old_qty) | set(new_qty):
                difference = old_qty.get(key, 0) - new_qty.get(key, 0)
                recipe = recipes.get(int(key[1])) if key[0] == 'id' and key[1].isdigit() else recipes.get(key[1])
                if not recipe or not difference:
                    continue
                for ingredient in recipe:
                    quantity_change = (ingredient.get('qty', 0) or 0) * difference
                    material = ingredient.get('material', '')
                    if quantity_change > 0:
                        sync_inventory_add(data, material, '', quantity_change)
                    elif quantity_change < 0:
                        sync_inventory_consume(data, material, -quantity_change)
                    if quantity_change:
                        record_inventory_movement(data, material, quantity_change, 'order_edit_adjustment',
                                                  reference_type='order_edit', reference_id=order_id,
                                                  note='تسوية مخزون بعد تعديل فاتورة ' + str(order_id))

            edit_history = order.setdefault('edit_history', [])
            edit_history.append({'date': datetime.now().isoformat(), 'reason': reason,
                                 'old_items': order.get('items', []), 'old_subtotal': order.get('subtotal'),
                                 'old_total': old_total, 'old_cash_amount': old_cash, 'old_card_amount': old_card})
            order.update({'items': items, 'subtotal': subtotal, 'discount_pct': discount_pct,
                          'discount_amount': fixed_discount, 'discount_total': total_discount,
                          'total': new_total, 'cash_amount': new_cash, 'card_amount': new_card,
                          'edited': True, 'last_edit_reason': reason, 'last_edited_at': datetime.now().isoformat()})

            # فروق التحصيل تسجل كسطور جديدة ولا تمحو أثر القبض الأصلي.
            for channel, old_amount, new_amount in (('cash', old_cash, new_cash), ('card', old_card, new_card)):
                delta = round_money(new_amount - old_amount)
                if delta:
                    record_cash_movement(data, 'in' if delta > 0 else 'out', abs(delta), 'تسوية تعديل فاتورة',
                                         channel=channel, reference_type='order_edit', reference_id=order_id,
                                         note='فرق تحصيل بعد تعديل الفاتورة', currency='SYP', exchange_rate=1,
                                         base_amount=abs(delta))
            save(data, [order_id]); backup()
            return jsonify({'ok': True, 'new_total': new_total, 'cash_amount': new_cash, 'card_amount': new_card})
    return jsonify({'ok': False, 'error': 'الطلب غير موجود'}), 404


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
    backup(force=True)
    return jsonify({"ok": True})


def safe_backup_export(value):
    """ينشئ نسخة قابلة للتنزيل من دون تجزئات كلمات المرور أو مفاتيح الترخيص.

    لا نعدّل ``data`` في الذاكرة: قد تكون النسخة المفتوحة نفسها مستخدمة في طلب
    آخر أو تحتوي قيماً لازمة للتحقق المحلي من الترخيص.
    """
    if isinstance(value, dict):
        return {
            key: safe_backup_export(item)
            for key, item in value.items()
            if key not in {'password_hash', 'license_key'}
        }
    if isinstance(value, list):
        return [safe_backup_export(item) for item in value]
    return value


@app.route('/api/backup/download', methods=['GET'])
def download_backup():
    data = safe_backup_export(build_backup_bundle())
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    payload = BytesIO(json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8'))
    return send_file(payload, as_attachment=True, download_name=f'CAESAR_POS_Backup_{stamp}.json', mimetype='application/json')


def validate_backup_bundle(bundle):
    if not isinstance(bundle, dict) or int(bundle.get('format_version', 0) or 0) != BACKUP_FORMAT_VERSION:
        return None, 'صيغة النسخة الاحتياطية غير مدعومة'
    state = bundle.get('state')
    cold = bundle.get('archive_cold')
    if not isinstance(state, dict) or not isinstance(cold, dict):
        return None, 'محتوى النسخة الاحتياطية غير صالح'
    if not isinstance(state.get('orders', []), list) or not isinstance(state.get('orders_archive', []), list):
        return None, 'بيانات فواتير النسخة الاحتياطية غير صالحة'
    if any(not isinstance(key, str) or not re.fullmatch(r'\d{4}-\d{2}|unknown', key)
           or not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows)
           for key, rows in cold.items()):
        return None, 'الأرشيف البارد في النسخة الاحتياطية غير صالح'
    return json.loads(json.dumps(bundle, ensure_ascii=False)), None


def _preserve_current_restore_credentials(restored, current):
    """يحافظ على التجزئات والمفتاح المحلي عند استعادة تنزيل مُنقّى."""
    current_users = {str(row.get('username')): row for row in active_users(current) if isinstance(row, dict)}
    for user in restored.get('settings', {}).get('users', []) or []:
        existing = current_users.get(str(user.get('username')))
        if isinstance(user, dict) and existing and not user.get('password_hash') and existing.get('password_hash'):
            user['password_hash'] = existing['password_hash']
    current_commercial = current.get('settings', {}).get('commercial', {})
    commercial = restored.setdefault('settings', {}).setdefault('commercial', {})
    for key in ('license_key', 'license_id', 'machine_id'):
        if key not in commercial and key in current_commercial:
            commercial[key] = current_commercial[key]


@app.route('/api/backup/restore', methods=['POST'])
def restore_backup():
    payload = request.get_json(silent=True) or {}
    if payload.get('confirmation') != 'RESTORE':
        return jsonify({'ok': False, 'error': 'اكتب RESTORE لتأكيد الاستعادة'}), 400
    bundle, error = validate_backup_bundle(payload.get('backup'))
    if error:
        return jsonify({'ok': False, 'error': error}), 400
    current = load()
    _preserve_current_restore_credentials(bundle['state'], current)
    # لا نكمل إن تعذر إنشاء نقطة أمان كاملة قبل لمس الحالة الحالية.
    backup(force=True)
    restored = bundle['state']
    restored.setdefault('orders', [])
    restored.setdefault('orders_archive', [])
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    staging = os.path.join(BACKUP_DIR, f'.restore_cold_{timestamp}')
    os.makedirs(staging, exist_ok=False)
    for month, rows in bundle['archive_cold'].items():
        atomic_write_json(os.path.join(staging, f'orders_{month}.json'), rows)

    previous_cold = os.path.join(BACKUP_DIR, f'archive_cold_pre_restore_{timestamp}')
    with DATA_LOCK:
        moved_old = False
        try:
            if os.path.isdir(COLD_ARCHIVE_DIR):
                os.replace(COLD_ARCHIVE_DIR, previous_cold)
                moved_old = True
            os.replace(staging, COLD_ARCHIVE_DIR)
            conn = db_connect()
            try:
                conn.execute('BEGIN IMMEDIATE')
                conn.execute('DELETE FROM order_items')
                conn.execute('DELETE FROM orders')
                _write_order_rows(conn, restored['orders'] + restored['orders_archive'], prune=False)
                compact = json.dumps(_compact_state_snapshot(restored), ensure_ascii=False, separators=(',', ':'))
                conn.execute('UPDATE app_state SET payload=?, updated_at=? WHERE id=1', (compact, datetime.now().isoformat()))
                integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
                if integrity != 'ok':
                    raise RuntimeError('فشل فحص سلامة SQLite بعد الاستعادة')
                conn.execute('COMMIT')
            except Exception:
                conn.execute('ROLLBACK')
                raise
            finally:
                conn.close()
            atomic_write_json(DATA_FILE, restored)
        except Exception as exc:
            if moved_old and os.path.isdir(previous_cold):
                failed_cold = os.path.join(BACKUP_DIR, f'archive_cold_failed_restore_{timestamp}')
                if os.path.isdir(COLD_ARCHIVE_DIR):
                    os.replace(COLD_ARCHIVE_DIR, failed_cold)
                os.replace(previous_cold, COLD_ARCHIVE_DIR)
            return jsonify({'ok': False, 'error': f'تعذرت الاستعادة بأمان: {str(exc)[:180]}'}), 500
    return jsonify({'ok': True, 'message': 'تمت الاستعادة بعد إنشاء نسخة أمان مسبقة',
                    'safety_archive': os.path.basename(previous_cold) if moved_old else None})

@app.route('/api/version', methods=['GET'])
def version():
    return jsonify({"current": CURRENT_VERSION, "offline": True, "check_url": None})

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
    port = int(os.environ.get('CAESAR_PORT', '8080'))
    enabled = os.environ.get('CAESAR_LAN') == '1'
    addresses = local_network_addresses()
    urls = [f'http://{ip}:{port}/mobile.html' for ip in addresses] if enabled else []
    waiter_base_urls = [f'http://{ip}:{port}' for ip in addresses] if enabled else []
    return jsonify({'lan_enabled': enabled, 'port': port, 'urls': urls, 'waiter_base_urls': waiter_base_urls,
                    'primary_ip': addresses[0] if enabled and addresses else '', 'mobile_path': '/mobile.html'})

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


@app.route('/api/network/waiter-qr.svg', methods=['GET'])
def waiter_connection_qr_svg():
    """يرمز عنوان الخادم المحلي فقط لتطبيق النادل؛ لا يحمل كلمة مرور أو رمز جلسة."""
    info = network_info().get_json()
    if not info.get('lan_enabled'):
        return jsonify({'ok': False, 'error': 'فعّل وضع الشبكة المحلية أولًا عبر Start_LAN_Mode.bat'}), 409
    if not info.get('waiter_base_urls'):
        return jsonify({'ok': False, 'error': 'لم يتم العثور على عنوان شبكة محلية. تأكد من اتصال الكمبيوتر بالشبكة.'}), 503
    if not qrcode or not SvgPathImage:
        return jsonify({'ok': False, 'error': 'مولد QR غير متاح في هذه النسخة'}), 503
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=4)
    qr.add_data('CAESAR_WAITER_V1|' + info['waiter_base_urls'][0]); qr.make(fit=True)
    image = qr.make_image(image_factory=SvgPathImage)
    out = BytesIO(); image.save(out)
    return Response(out.getvalue(), mimetype='image/svg+xml', headers={'Cache-Control': 'no-store'})

def start_flask():
    # افتراضيًا محلي فقط. فعّل CAESAR_LAN=1 للوصول من الجوالات داخل شبكة المطعم فقط.
    host = '0.0.0.0' if os.environ.get('CAESAR_LAN') == '1' else '127.0.0.1'
    startup_data = load()
    if commercial_setup_complete(startup_data) and not installation_license_valid(startup_data):
        print(' LICENSE: invalid machine binding; API requests will remain locked until reactivation')
    print(' LAN mode:', 'enabled' if host == '0.0.0.0' else 'local only')
    for ip in (local_network_addresses() if host == '0.0.0.0' else []):
        print(f' Mobile URL: http://{ip}:{os.environ.get("CAESAR_PORT", "8080")}/mobile.html')
    port = int(os.environ.get('CAESAR_PORT', '8080'))
    # The desktop launcher owns the UI window. The server must never open a
    # browser by itself, otherwise Start.bat and the server create two windows.
    #
    # threaded=True (تحسين أداء حرج): الطباعة الحرارية (submit_network_raw_print/
    # submit_silent_windows_print) تنتظر حتى 8-10 ثوانٍ عند تعطّل الطابعة أو
    # الشبكة، وكانت تُشغَّل بشكل متزامن قبل هذا التعديل. مع threaded=False كان
    # طلب طباعة واحد يجمّد الخادم بالكامل لثوانٍ، فتتجمّد كل الشاشات الأخرى معه
    # (شاشة المطبخ، شاشة الانتظار، أي كاشير آخر على نفس الشبكة) حتى لو لم تكن
    # هي من تطبع. تفعيل threaded=True يجعل كل طلب يُعالَج بخيط مستقل فلا يوقف
    # طلب بطيء بقية النظام - وهذا آمن هنا لأن كل قراءة/كتابة لـ data.json تمر
    # عبر load()/save()/backup() المحميّة بالكامل بـ DATA_LOCK (threading.RLock)،
    # فلا يوجد أي تعارض أو تلف بيانات محتمل بين الخيوط.
    try:
        from waitress import serve
    except ImportError:
        # تطوير/تشغيل قديم بلا dependency؛ يبقى fallback واضحًا بدل فشل الإقلاع.
        print(' WARNING: waitress غير مثبت؛ سيتم استخدام خادم Flask الاحتياطي')
        app.run(host=host, port=port, debug=False, threaded=True)
    else:
        print(' HTTP server: Waitress (8 threads)')
        serve(app, host=host, port=port, threads=8)





@app.route('/api/reload-menu', methods=['POST'])
def reload_menu():
    """تهيئة المنيو من لقطة البيانات المحلية المحفوظة في الخزنة."""
    try:
        if os.path.exists(FLASH_BACKUP):
            with open(FLASH_BACKUP, 'r', encoding='utf-8') as f:
                flash_data = json.load(f)
            local_data = load()
            local_data['menu'] = flash_data.get('menu', {})
            save(local_data)
            backup()
            return jsonify({"ok": True, "message": "تمت تهيئة المنيو من اللقطة المحلية"})
        return jsonify({"ok": False, "error": "لا توجد لقطة بيانات محلية لاستيراد المنيو"})
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
    amount = as_money(payload.get('amount'), 0)
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
            new_amount = as_money(payload.get('amount', d['amount']), None)
            if new_amount is None or new_amount < as_money(d.get('paid', 0), 0) or new_amount <= 0:
                return jsonify({'ok': False, 'error': 'المبلغ لا يمكن أن يكون أقل من المدفوع'}), 400
            d['amount'] = new_amount
            d['note'] = payload.get('note', d.get('note', ''))
            save(data); backup()
            return jsonify({"ok": True})
    return jsonify({"ok": False}), 404

@app.route('/api/debts/<int:did>/pay', methods=['POST'])
def pay_debt(did):
    """تسجيل دفعة على دين - تُسجَّل تلقائياً كدخل بالكاشير قيصر (تظهر بالمبيعات والتحليلات).
    تدعم اختيار طريقة الدفع (نقدي/بطاقة) بدل تثبيتها نقدي دائماً."""
    data = load()
    for d in data.get('debts', []):
        if d['id'] == did:
            payload = request.get_json(silent=True) or {}
            amount = as_money(payload.get('amount'), 0)
            method = payload.get('method', 'نقدي')
            if method not in ('نقدي', 'بطاقة'):
                method = 'نقدي'
            remaining_before = round_money(as_money(d.get('amount'), 0) - as_money(d.get('paid'), 0))
            if amount <= 0 or amount > remaining_before:
                return jsonify({'ok': False, 'error': 'مبلغ الدفعة غير صالح أو أكبر من المتبقي'}), 400
            d['paid'] = round_money(as_money(d.get('paid'), 0) + amount)
            snap = currency_snapshot(data, d)
            payment = {'amount': amount, 'method': method, 'date': datetime.now().isoformat(), 'currency': snap['currency'], 'exchange_rate': snap['exchange_rate']}
            d.setdefault('payments', []).append(payment)
            payment_order = {
                'id': next_order_id(data),
                'items': [{'name': f"تسديد دين: {d['name']}", 'price': amount, 'quantity': 1}],
                'total': amount,
                'type': 'تسديد دين',
                'note': d.get('note', ''),
                'payment': method, 'accounting_type': 'debt_payment', 'debt_id': did,
                'cash_amount': amount if method == 'نقدي' else 0,
                'card_amount': amount if method == 'بطاقة' else 0,
                'cashier_name': session.get('username', 'غير محدد'),
                'currency': snap['currency'], 'exchange_rate': snap['exchange_rate'],
                'date': datetime.now().isoformat(),
                'timestamp': datetime.now().isoformat()
            }
            data.setdefault('orders', []).append(payment_order)
            payment_base_amount = amount_in_base(data, amount, snap['currency'], snap['exchange_rate'])
            if payment_base_amount is None:
                return jsonify({'ok': False, 'error': 'سعر صرف الدين غير صالح'}), 400
            record_cash_movement(data, 'in', amount, 'تحصيل دين',
                                 channel='card' if method == 'بطاقة' else 'cash',
                                 reference_type='debt_payment', reference_id=payment_order['id'],
                                 note='تسديد دين: ' + str(d.get('name', '')),
                                 currency=snap['currency'], exchange_rate=snap['exchange_rate'],
                                 base_amount=payment_base_amount)
            save(data, [payment_order['id']]); backup()
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
    moved_order_ids = [str(o.get('id')) for o in data['orders'] if o.get('id')]
    data['orders_archive'].extend(data['orders'])
    data['orders'] = []
    data.setdefault('_pending_order_sync_ids', []).extend(moved_order_ids)
    compact_old_archive(data)
    # يمكن تصفير عداد الوردية للعرض، لكن next_order_id يعيد البناء من كل
    # الفواتير الحية والمؤرشفة، لذلك لا يؤدي ذلك إلى إعادة استخدام رقم قديم.
    data['order_counter'] = 0
    data.setdefault('settings', {})['last_order_date'] = datetime.now().strftime('%Y-%m-%d')
    save(data)
    backup()
    used_numbers = []
    for row in data.get('orders_archive', []):
        value = str(row.get('id', '')) if isinstance(row, dict) else ''
        if value.startswith('ORD-'):
            try:
                used_numbers.append(int(value[4:]))
            except ValueError:
                pass
    next_number = max(used_numbers, default=0) + 1
    return jsonify({"ok": True, "shift_id": shift_id, "next_id": f"ORD-{next_number:04d}"})


@app.route('/api/shifts/reset-counter', methods=['POST'])
def reset_counter_after_close():
    """يؤرشف فواتير الوردية ويعيد عداد الفواتير إلى صفر بشكل صريح."""
    payload = request.get_json(silent=True) or {}
    if payload.get('confirmation') != 'RESET_COUNTER':
        return jsonify({'ok': False, 'error': 'اكتب RESET_COUNTER لتأكيد تصفير العداد'}), 400
    response = archive_orders()
    if isinstance(response, tuple):
        return response
    body = response.get_json() if hasattr(response, 'get_json') else {}
    body['counter'] = 0
    body['paper_cut'] = cut_paper_to_printer(load().get('settings', {}).get('printer', {}))
    return jsonify(body)


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
    amount = as_money(payload.get('amount'), 0)
    if amount <= 0 or not payload.get('note'):
        return jsonify({'ok': False, 'error': 'الوصف والمبلغ مطلوبان'}), 400
    snap = currency_snapshot(data, payload)
    base_amount = amount_in_base(data, amount, snap['currency'], snap['exchange_rate'])
    if amount <= 0 or base_amount is None:
        return jsonify({'ok': False, 'error': 'مبلغ المصروف أو سعر الصرف غير صالح'}), 400
    rows = data.setdefault('expenses', [])
    expense = {'id': max([x.get('id', 0) for x in rows if isinstance(x, dict)], default=0) + 1,
               'amount': amount, 'amount_base': base_amount, 'currency': snap['currency'], 'exchange_rate': snap['exchange_rate'],
               'category': payload.get('category', 'عام'), 'note': str(payload.get('note'))[:200],
               'payment': payload.get('payment', 'نقدي'), 'date': payload.get('date') or datetime.now().isoformat(),
               'created_by': session.get('username', 'نظام محلي')}
    rows.append(expense)
    record_cash_movement(data, 'out', amount, 'مصروف تشغيلي',
                         channel='card' if expense['payment'] == 'بطاقة' else 'cash',
                         reference_type='expense', reference_id=expense['id'],
                         note=expense['note'], currency=expense['currency'], exchange_rate=expense['exchange_rate'],
                         base_amount=base_amount)
    save(data); backup()
    return jsonify({'ok': True, 'expense': expense})

@app.route('/api/expenses/<int:eid>', methods=['DELETE'])
def delete_expense(eid):
    data = load(); rows = data.get('expenses', [])
    target = next((x for x in rows if x.get('id') == eid and not x.get('material_id') and not x.get('voided')), None)
    if not target: return jsonify({'ok': False, 'error': 'المصروف غير موجود'}), 404
    target['voided'] = True; target['voided_at'] = datetime.now().isoformat(); target['voided_by'] = session.get('username', 'نظام محلي')
    record_cash_movement(data, 'in', target.get('amount', 0), 'عكس مصروف ملغى',
                         channel='card' if target.get('payment') == 'بطاقة' else 'cash',
                         reference_type='expense_void', reference_id=eid,
                         note='عكس المصروف: ' + str(target.get('note', '')),
                         currency=target.get('currency'), exchange_rate=target.get('exchange_rate'),
                         base_amount=expense_amount_base(data, target))
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
    # السلفة تُخصم فوراً من الكاشير قيصر كمصروف
    if advance:
        advance_amount = positive_amount(advance, 0) or 0
        data.setdefault('expenses', []).append({
            'employee_id': new_id, 'amount': advance_amount, 'amount_base': advance_amount, 'currency': 'SYP', 'exchange_rate': 1,
            'date': datetime.now().isoformat(), 'note': f"سلفة موظف: {request.json.get('name')}", 'category': 'سلفة موظف',
            'payment': 'نقدي', 'created_by': session.get('username', 'نظام محلي')
        })
        record_cash_movement(data, 'out', advance_amount, 'سلفة موظف', reference_type='employee_advance', reference_id=new_id, note=f"سلفة موظف: {request.json.get('name')}")
    save(data)
    backup()
    return jsonify({"ok": True, "id": new_id})

@app.route('/api/employees/<int:eid>', methods=['PUT'])
def update_employee(eid):
    if not has_role('manager'):
        return permission_error()
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
    amount = positive_amount(request.json.get('amount', emp.get('salary', 0)))
    if amount is None:
        return jsonify({'ok': False, 'error': 'مبلغ الراتب يجب أن يكون أكبر من صفر'}), 400
    timestamp = datetime.now().isoformat()
    data.setdefault('expenses', []).append({
        'employee_id': eid, 'amount': amount, 'amount_base': amount, 'currency': 'SYP', 'exchange_rate': 1,
        'date': timestamp, 'note': f"دفع راتب: {emp['name']}", 'category': 'رواتب', 'payment': 'نقدي',
        'created_by': session.get('username', 'نظام محلي')
    })
    record_cash_movement(data, 'out', amount, 'رواتب', reference_type='salary_payment', reference_id=eid, note=f"راتب الموظف: {emp['name']}")
    save(data); backup()
    return jsonify({"ok": True, "amount": amount})

@app.route('/api/employees/<int:eid>/advance', methods=['POST'])
def add_employee_advance(eid):
    if not has_role('cashier', 'supervisor', 'manager'):
        return permission_error()
    data = load(); emp = next((e for e in data.get('employees', []) if e.get('id') == eid), None)
    if not emp:
        return jsonify({'ok': False, 'error': 'الموظف غير موجود'}), 404
    payload = request.get_json(silent=True) or {}; amount = positive_amount(payload.get('amount'))
    if amount is None:
        return jsonify({'ok': False, 'error': 'مبلغ السلفة يجب أن يكون أكبر من صفر'}), 400
    emp['advance'] = round(float(emp.get('advance', 0) or 0) + amount, 2)
    timestamp = datetime.now().isoformat()
    data.setdefault('expenses', []).append({'employee_id': eid, 'amount': amount, 'amount_base': amount, 'currency': 'SYP', 'exchange_rate': 1, 'date': timestamp, 'note': f"سلفة موظف: {emp.get('name', '')}", 'category': 'سلفة موظف', 'payment': 'نقدي', 'created_by': session.get('username', 'نظام محلي')})
    record_cash_movement(data, 'out', amount, 'سلفة موظف', reference_type='employee_advance', reference_id=eid, note=f"سلفة موظف: {emp.get('name', '')}")
    save(data); backup(); return jsonify({'ok': True, 'amount': amount, 'advance_total': emp['advance']})

@app.route('/api/employees/<int:eid>', methods=['DELETE'])
def delete_employee(eid):
    if not has_role('manager'):
        return permission_error()
    """حذف موظف - ترجع السلفة (تُحذف كمصروف مرتبط)"""
    data = load()
    data['employees'] = [e for e in data.get('employees', []) if e['id'] != eid]
    data['expenses'] = [x for x in data.get('expenses', []) if x.get('employee_id') != eid]
    save(data)
    backup()
    return jsonify({"ok": True})


def attendance_rows(data, date_from='', date_to=''):
    employees = {str(row.get('id')): row.get('name', '') for row in data.get('employees', [])}
    rows = []
    for entry in data.get('attendance', []):
        stamp = str(entry.get('clock_in', entry.get('date', '')))
        if date_from and stamp[:10] < date_from:
            continue
        if date_to and stamp[:10] > date_to:
            continue
        row = dict(entry); row['employee_name'] = employees.get(str(entry.get('employee_id')), 'موظف محذوف')
        if row.get('clock_in') and row.get('clock_out'):
            try:
                row['minutes'] = max(0, int((datetime.fromisoformat(row['clock_out']) - datetime.fromisoformat(row['clock_in'])).total_seconds() // 60))
            except (TypeError, ValueError):
                row['minutes'] = 0
        else:
            row['minutes'] = None
        rows.append(row)
    return sorted(rows, key=lambda row: row.get('clock_in', ''), reverse=True)


@app.route('/api/attendance', methods=['GET'])
def list_attendance():
    if not has_role('cashier', 'manager', 'supervisor'):
        return permission_error()
    data = load()
    return jsonify(attendance_rows(data, request.args.get('from', '').strip(), request.args.get('to', '').strip())[:300])


@app.route('/api/attendance/clock', methods=['POST'])
def clock_employee():
    if not has_role('cashier', 'manager', 'supervisor'):
        return permission_error()
    data = load(); payload = request.get_json(silent=True) or {}
    try:
        employee_id = int(payload.get('employee_id'))
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'اختر موظفًا صالحًا'}), 400
    if not any(int(row.get('id', -1)) == employee_id for row in data.get('employees', [])):
        return jsonify({'ok': False, 'error': 'الموظف غير موجود'}), 404
    action = str(payload.get('action', 'in') or 'in')
    if action not in {'in', 'out'}:
        return jsonify({'ok': False, 'error': 'إجراء الدوام غير صالح'}), 400
    open_row = next((row for row in reversed(data.get('attendance', [])) if int(row.get('employee_id', -1)) == employee_id and not row.get('clock_out')), None)
    now = datetime.now().isoformat()
    if action == 'in':
        if open_row:
            return jsonify({'ok': False, 'error': 'للموظف تسجيل دخول مفتوح بالفعل'}), 409
        entry = {'id': uuid.uuid4().hex[:12], 'employee_id': employee_id, 'clock_in': now, 'clock_out': '', 'recorded_by': session.get('username', 'unknown')}
        data.setdefault('attendance', []).append(entry)
    else:
        if not open_row:
            return jsonify({'ok': False, 'error': 'لا يوجد تسجيل دخول مفتوح لهذا الموظف'}), 409
        open_row['clock_out'] = now; open_row['closed_by'] = session.get('username', 'unknown'); entry = open_row
    data['attendance'] = data.get('attendance', [])[-1000:]
    save(data); backup()
    return jsonify({'ok': True, 'entry': entry})


def positive_amount(value, default=None):
    amount = as_money(value, default)
    return amount if amount is not None and amount > 0 else default
def inventory_item_by_name(data, name):
    normalized = str(name or '').strip()
    return next((item for item in data.get('inventory', []) if item.get('name', '').strip() == normalized), None)
def inventory_alerts(data):
    """يعيد المواد النافدة أو التي وصلت إلى حد إعادة الطلب.

    الصفر في حد التنبيه يعني عدم تفعيل تنبيه الانخفاض، مع إبقاء تنبيه
    النفاد فعالًا دائمًا. تدعم القراءة مفاتيح المخزون الحالية والمفاتيح
    القديمة حتى لا تتعطل النسخ المرحّلة من data.json.
    """
    alerts = []
    for item in data.get('inventory', []):
        if not isinstance(item, dict):
            continue
        try:
            stock = float(item.get('stock', item.get('quantity', 0)) or 0)
            threshold = float(item.get(
                'low_stock_threshold',
                item.get('reorder_point', item.get('min_stock', 0)),
            ) or 0)
        except (TypeError, ValueError):
            continue
        if stock <= 0:
            status = 'out'
        elif threshold > 0 and stock <= threshold:
            status = 'low'
        else:
            continue
        alerts.append({
            'id': item.get('id'),
            'name': str(item.get('name', '')).strip(),
            'unit': str(item.get('unit', '')).strip(),
            'stock': round(stock, 4),
            'quantity': round(stock, 4),
            'threshold': round(max(0, threshold), 4),
            'status': status,
        })
    return alerts
def record_inventory_movement(data, material_name, quantity, movement_type, *, unit='', reference_type='', reference_id='', note=''):
    """دفتر حركات لا يعدّل الرصيد؛ تسجّل الدوال الأخرى الرصيد ثم نستدعيه للتدقيق."""
    amount = float(quantity or 0)
    if not material_name or not amount:
        return None
    item = inventory_item_by_name(data, material_name)
    movements = data.setdefault('inventory_movements', [])
    movement = {
        'id': max([int(row.get('id', 0) or 0) for row in movements if isinstance(row, dict)] or [0]) + 1,
        'timestamp': datetime.now().isoformat(), 'material': str(material_name).strip(), 'quantity': round(amount, 4),
        'unit': unit or (item.get('unit', '') if item else ''), 'type': movement_type,
        'balance_after': round(float(item.get('stock', 0) or 0), 4) if item else None,
        'reference_type': reference_type, 'reference_id': str(reference_id or ''), 'note': str(note or '')[:240],
        'created_by': session.get('username', 'نظام محلي')
    }
    movements.append(movement)
    return movement


def record_cash_movement(data, direction, amount, category, *, channel='cash', reference_type='', reference_id='', supplier_id=None, note='', currency=None, exchange_rate=None, base_amount=None):
    """سجل تدفق نقدي مستقل عن مصروف الربح والخسارة لمنع عدّ شراء المورد مرتين."""
    amount = positive_amount(amount)
    base_amount = positive_amount(base_amount if base_amount is not None else amount)
    if direction not in {'in', 'out'} or amount is None or base_amount is None or channel not in {'cash', 'card'}:
        return None
    snap = currency_snapshot(data, {'currency': currency} if currency else {'currency': 'SYP', 'exchange_rate': 1})
    movements = data.setdefault('cash_movements', [])
    movement = {
        'id': max([int(row.get('id', 0) or 0) for row in movements if isinstance(row, dict)] or [0]) + 1,
        'timestamp': datetime.now().isoformat(), 'direction': direction, 'channel': channel, 'amount': amount,
        'amount_base': round_money(base_amount),
        'currency': snap['currency'], 'exchange_rate': exchange_rate if exchange_rate is not None else snap['exchange_rate'],
        'category': category, 'reference_type': reference_type, 'reference_id': str(reference_id or ''),
        'supplier_id': supplier_id, 'note': str(note or '')[:240], 'created_by': session.get('username', 'نظام محلي')
    }
    movements.append(movement)
    return movement


def cash_movement_amount_base(data, movement):
    if movement.get('amount_base') is not None:
        return round_money(movement.get('amount_base'))
    # السجلات اليدوية القديمة فقط كانت تحفظ amount بعملة أجنبية؛ بقية الحركات قيمها بعملة الأساس.
    if movement.get('reference_type') in {'expense', 'expense_void'}:
        return amount_in_base(data, movement.get('amount', 0), movement.get('currency', 'SYP'), movement.get('exchange_rate')) or 0
    return round_money(movement.get('amount', 0))


def normalized_cash_movement(data, movement):
    row = dict(movement)
    is_foreign_expense = movement.get('reference_type') in {'expense', 'expense_void'}
    row['original_amount'] = movement.get('original_amount', movement.get('amount', 0) if is_foreign_expense else cash_movement_amount_base(data, movement))
    row['original_currency'] = movement.get('original_currency', movement.get('currency', 'SYP') if is_foreign_expense else 'SYP')
    row['amount'] = cash_movement_amount_base(data, movement)
    row['amount_base'] = row['amount']
    row['currency'] = 'SYP'
    row['exchange_rate'] = 1
    return row


def financial_cash_movements(data, period=None, date_from='', date_to=''):
    movements = list(data.get('cash_movements', []))
    if not movements:
        movements = list(data.get('cashbook', []))
    seen_debt_receipts = {(str(m.get('reference_id')), m.get('reference_type')) for m in movements}
    # أضف تحصيلات الديون التاريخية التي كانت تحفظ كطلب فقط، بما فيها الأرشيف البارد عند نطاق التقرير.
    cold_from, cold_to = date_from, date_to
    now = datetime.now()
    if not cold_from and not cold_to and period == 'daily':
        cold_from = cold_to = now.strftime('%Y-%m-%d')
    elif not cold_from and not cold_to and period == 'monthly':
        cold_from, cold_to = now.strftime('%Y-%m-01'), now.strftime('%Y-%m-%d')
    elif not cold_from and not cold_to and period == 'yearly':
        cold_from, cold_to = now.strftime('%Y-01-01'), now.strftime('%Y-%m-%d')
    legacy_orders = data.get('orders', []) + data.get('orders_archive', []) + load_cold_orders(cold_from, cold_to)
    for order in legacy_orders:
        if order.get('type') != 'تسديد دين' and order.get('accounting_type') != 'debt_payment':
            continue
        order_id = str(order.get('id', ''))
        if (order_id, 'debt_payment') in seen_debt_receipts:
            continue
        timestamp = order.get('timestamp', order.get('date', ''))
        for channel, amount in (('cash', order.get('cash_amount', order.get('total', 0) if order.get('payment') != 'بطاقة' else 0)),
                                ('card', order.get('card_amount', order.get('total', 0) if order.get('payment') == 'بطاقة' else 0))):
            if amount:
                movements.append({'timestamp': timestamp, 'direction': 'in', 'channel': channel,
                                  'amount': amount, 'amount_base': amount, 'reference_type': 'legacy_debt_payment',
                                  'reference_id': order_id, 'category': 'تحصيل دين'})
    return movements


def supplier_payment_rows(data, supplier_id):
    return [row for row in data.get('supplier_payments', []) if row.get('supplier_id') == supplier_id and not row.get('voided')]


def supplier_summary(data):
    suppliers = data.get('suppliers', [])
    purchases = data.get('materials', [])
    result = []
    for supplier in suppliers:
        sid = supplier.get('id')
        rows = [m for m in purchases if m.get('supplier_id') == sid and not m.get('voided')]
        purchase_total = sum_money(m.get('price', 0) or 0 for m in rows)
        purchase_paid = sum_money(m.get('paid_amount', m.get('price', 0)) or 0 for m in rows)
        later_payments = supplier_payment_rows(data, sid)
        later_paid = sum_money(row.get('amount', 0) or 0 for row in later_payments)
        paid_total = sum_money((purchase_paid, later_paid))
        result.append({**supplier, 'purchase_total': purchase_total, 'paid_at_purchase': purchase_paid,
                       'later_paid': later_paid, 'paid_total': paid_total,
                       'due_total': max(0, round_money(purchase_total - paid_total)),
                       'purchase_count': len(rows), 'payment_count': len(later_payments)})
    return result


def supplier_by_id(data, supplier_id):
    return next((row for row in data.get('suppliers', []) if row.get('id') == supplier_id), None)


@app.route('/api/suppliers', methods=['GET'])
def get_suppliers():
    data = load()
    return jsonify(supplier_summary(data))


@app.route('/api/suppliers', methods=['POST'])
def add_supplier():
    if not has_role('manager'):
        return permission_error()
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
    if not has_role('manager'):
        return permission_error()
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
    if not has_role('manager'):
        return permission_error()
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


@app.route('/api/suppliers/<int:sid>/payments', methods=['GET', 'POST'])
def supplier_payments(sid):
    data = load()
    supplier = supplier_by_id(data, sid)
    if not supplier:
        return jsonify({'ok': False, 'error': 'المورد غير موجود'}), 404
    if request.method == 'GET':
        return jsonify({'ok': True, 'payments': supplier_payment_rows(data, sid)})

    payload = request.get_json(silent=True) or {}
    amount = positive_amount(payload.get('amount'))
    payment_method = str(payload.get('payment', 'نقدي') or 'نقدي')
    if amount is None or payment_method not in {'نقدي', 'بطاقة'}:
        return jsonify({'ok': False, 'error': 'مبلغ وطريقة دفع صحيحتان مطلوبان'}), 400
    summary = next((row for row in supplier_summary(data) if row.get('id') == sid), None)
    due = float(summary.get('due_total', 0) or 0) if summary else 0
    if amount > round_money(due):
        return jsonify({'ok': False, 'error': 'دفعة المورد أكبر من الرصيد المستحق'}), 400
    payments = data.setdefault('supplier_payments', [])
    payment = {
        'id': max([int(row.get('id', 0) or 0) for row in payments if isinstance(row, dict)] or [0]) + 1,
        'supplier_id': sid, 'amount': amount, 'payment': payment_method,
        'reference_no': str(payload.get('reference_no', '') or '')[:100],
        'note': str(payload.get('note', '') or '')[:240], 'date': datetime.now().isoformat(),
        'created_by': session.get('username', 'نظام محلي')
    }
    payments.append(payment)
    record_cash_movement(data, 'out', amount, 'دفعة مورد',
                         channel='card' if payment_method == 'بطاقة' else 'cash',
                         reference_type='supplier_payment', reference_id=payment['id'], supplier_id=sid,
                         note='دفعة للمورد: ' + supplier.get('name', ''))
    save(data); backup()
    return jsonify({'ok': True, 'payment': payment, 'remaining_due': max(0, round_money(due - amount))}), 201


@app.route('/api/inventory/movements', methods=['GET'])
def inventory_movements_api():
    data = load()
    rows = list(data.get('inventory_movements', []))
    material = str(request.args.get('material', '') or '').strip()
    if material:
        rows = [row for row in rows if row.get('material') == material]
    limit = min(max(int(request.args.get('limit', 100) or 100), 1), 500)
    return jsonify({'ok': True, 'movements': sorted(rows, key=lambda row: row.get('timestamp', ''), reverse=True)[:limit]})


@app.route('/api/cashbook/summary', methods=['GET'])
def cashbook_summary_api():
    data = load()
    date_from = str(request.args.get('from', '') or '').strip()
    date_to = str(request.args.get('to', '') or '').strip()
    rows = [row for row in financial_cash_movements(data, date_from=date_from, date_to=date_to) if (not date_from or row.get('timestamp', '')[:10] >= date_from)
            and (not date_to or row.get('timestamp', '')[:10] <= date_to)]
    cash_in = sum_money(cash_movement_amount_base(data, row) for row in rows if row.get('channel') == 'cash' and row.get('direction') == 'in')
    cash_out = sum_money(cash_movement_amount_base(data, row) for row in rows if row.get('channel') == 'cash' and row.get('direction') == 'out')
    card_in = sum_money(cash_movement_amount_base(data, row) for row in rows if row.get('channel') == 'card' and row.get('direction') == 'in')
    card_out = sum_money(cash_movement_amount_base(data, row) for row in rows if row.get('channel') == 'card' and row.get('direction') == 'out')
    return jsonify({'ok': True, 'cash_in': cash_in, 'cash_out': cash_out, 'cash_balance': round(cash_in - cash_out, 2),
                    'card_in': card_in, 'card_out': card_out, 'card_balance': round(card_in - card_out, 2),
                    'movements': [normalized_cash_movement(data, row) for row in sorted(rows, key=lambda row: row.get('timestamp', ''), reverse=True)[:100]]})


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
    """شراء مادة خام: يحدّث الرصيد، يسجل تكلفة الشراء، ويضيف تدفق الصندوق للجزء المدفوع فقط."""
    data = load()
    payload = request.get_json(silent=True) or {}
    name = str(payload.get('name', '') or '').strip()[:120]
    unit = str(payload.get('unit', '') or '').strip()[:30]
    quantity = positive_amount(payload.get('quantity'))
    price = positive_amount(payload.get('price'))
    paid_amount = as_money(payload.get('paid_amount', price), None)
    payment_method = str(payload.get('payment', 'نقدي') or 'نقدي')
    if not name or not unit or quantity is None or price is None or paid_amount is None or paid_amount > price or payment_method not in {'نقدي', 'بطاقة'}:
        return jsonify({'ok': False, 'error': 'اسم المادة والوحدة والكمية وقيمة شراء ومدفوع وطريقة دفع صحيحة مطلوبة'}), 400
    supplier_id = payload.get('supplier_id')
    try:
        supplier_id = int(supplier_id) if supplier_id not in (None, '', 0, '0') else None
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': 'المورد المختار غير صالح'}), 400
    if supplier_id is not None and not supplier_by_id(data, supplier_id):
        return jsonify({'ok': False, 'error': 'المورد المختار غير موجود'}), 404
    materials = data.setdefault('materials', [])
    new_id = max([int(m.get('id', 0) or 0) for m in materials if isinstance(m, dict)] or [0]) + 1
    material = {
        'id': new_id, 'name': name, 'quantity': quantity, 'unit': unit, 'price': price,
        'paid_amount': paid_amount, 'supplier_id': supplier_id,
        'invoice_no': str(payload.get('invoice_no', '') or '').strip()[:100],
        'notes': str(payload.get('notes', '') or '').strip()[:240], 'payment': payment_method,
        'date': datetime.now().isoformat(), 'created_by': session.get('username', 'نظام محلي')
    }
    materials.append(material)
    data.setdefault('expenses', []).append({
        'material_id': new_id, 'amount': price, 'amount_base': price, 'date': material['date'], 'note': f"شراء مادة: {name}",
        'supplier_id': supplier_id, 'paid_amount': paid_amount, 'paid_amount_base': paid_amount,
        'payment': payment_method, 'invoice_no': material['invoice_no'],
        'created_by': session.get('username', 'نظام محلي')
    })
    sync_inventory_add(data, name, unit, quantity)
    record_inventory_movement(data, name, quantity, 'purchase', unit=unit,
                              reference_type='material_purchase', reference_id=new_id,
                              note=('فاتورة مورد: ' + material['invoice_no']) if material['invoice_no'] else 'شراء مادة خام')
    if paid_amount:
        record_cash_movement(data, 'out', paid_amount, 'شراء مواد خام',
                             channel='card' if payment_method == 'بطاقة' else 'cash',
                             reference_type='material_purchase', reference_id=new_id, supplier_id=supplier_id,
                             note='شراء: ' + name)
    save(data); backup()
    return jsonify({"ok": True, "id": new_id, "due_amount": round(price - paid_amount, 2)})

@app.route('/api/materials/<int:mid>', methods=['PUT'])
def update_material(mid):
    if not has_role('manager'): return permission_error()
    data=load(); target=next((m for m in data.get('materials',[]) if m.get('id')==mid),None)
    if not target: return jsonify({"ok":False,"error":"المادة غير موجودة"}),404
    payload=request.get_json(silent=True) or {}; old_name=str(target.get('name','')); old_qty=float(target.get('quantity',0) or 0)
    old_price=float(target.get('price',0) or 0); old_paid=float(target.get('paid_amount',old_price) or 0)
    name=str(payload.get('name',old_name) or '').strip()[:120]; unit=str(payload.get('unit',target.get('unit','')) or '').strip()[:30]
    quantity=positive_amount(payload.get('quantity',old_qty)); price=positive_amount(payload.get('price',old_price))
    if not name or not unit or quantity is None or price is None or price < old_paid:
        return jsonify({'ok':False,'error':'بيانات المادة غير صالحة؛ لا يمكن جعل قيمة الشراء أقل من المدفوع'}),400
    target.update({'name':name,'quantity':quantity,'unit':unit,'price':price,'paid_amount':round(old_paid,2)})
    for e in data.get('expenses',[]):
        if e.get('material_id')==mid and not e.get('voided'):
            e.update({'amount':price,'amount_base':price,'paid_amount':round(old_paid,2),'paid_amount_base':round(old_paid,2),'note':f'شراء مادة: {name}'})
    if old_name != name or old_qty != float(quantity):
        sync_inventory_consume(data,old_name,old_qty); sync_inventory_add(data,name,unit,quantity)
        delta=round(float(quantity)-old_qty,4)
        if delta: record_inventory_movement(data,name,delta,'adjustment',unit=unit,reference_type='material_edit',reference_id=mid,note='تسوية كمية مادة خام بعد التعديل')
    save(data); backup(); return jsonify({"ok":True,"material":target,"due_amount":round(price-old_paid,2)})

@app.route('/api/materials/<int:mid>', methods=['DELETE'])
def delete_material(mid):
    if not has_role('manager'): return permission_error()
    data=load(); target=next((m for m in data.get('materials',[]) if m.get('id')==mid),None)
    if not target: return jsonify({"ok":False,"error":"المادة غير موجودة"}),404
    name=str(target.get('name','')); quantity=float(target.get('quantity',0) or 0); paid=float(target.get('paid_amount',target.get('price',0)) or 0)
    sync_inventory_consume(data,name,quantity)
    if quantity: record_inventory_movement(data,name,-quantity,'void',unit=target.get('unit',''),reference_type='material_void',reference_id=mid,note='عكس شراء مادة ملغى')
    for e in data.setdefault('expenses',[]):
        if e.get('material_id')==mid and not e.get('voided'):
            e['voided']=True; e['voided_at']=datetime.now().isoformat(); e['voided_by']=session.get('username','نظام محلي')
    if paid: record_cash_movement(data,'in',paid,'عكس شراء مواد خام ملغى',channel='card' if target.get('payment')=='بطاقة' else 'cash',reference_type='material_void',reference_id=mid,note='عكس شراء: '+name)
    data['materials']=[m for m in data.get('materials',[]) if m.get('id')!=mid]; save(data); backup(); return jsonify({"ok":True,"voided":True})
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
    """تصحيح جرد فعلي مع تسجيل فرق الرصيد والسبب في دفتر الحركات."""
    data = load(); payload = request.get_json(silent=True) or {}
    new_stock = as_money(payload.get('stock'), None)
    if new_stock is None:
        return jsonify({'ok': False, 'error': 'الرصيد الجديد يجب أن يكون رقماً صفراً أو موجباً'}), 400
    for item in data.get('inventory', []):
        if item['id'] == iid:
            old_stock = float(item.get('stock', 0) or 0)
            item['stock'] = new_stock
            difference = round(new_stock - old_stock, 4)
            if difference:
                record_inventory_movement(data, item.get('name', ''), difference, 'adjustment', unit=item.get('unit', ''),
                                          reference_type='inventory_adjustment', reference_id=iid,
                                          note=str(payload.get('reason', 'تصحيح جرد فعلي') or 'تصحيح جرد فعلي'))
            save(data); backup()
            return jsonify({"ok": True, 'stock': new_stock, 'difference': difference})
    return jsonify({"ok": False, 'error': 'المادة غير موجودة'}), 404

@app.route('/api/inventory/<int:iid>/threshold', methods=['POST'])
def set_inventory_threshold(iid):
    """تحديد الحد الأدنى الذي يظهر عنده تنبيه نفاد مخزون"""
    data = load(); payload = request.get_json(silent=True) or {}
    threshold = as_money(payload.get('threshold', 0), None)
    if threshold is None:
        return jsonify({'ok': False, 'error': 'حد التنبيه يجب أن يكون رقماً صفراً أو موجباً'}), 400
    for item in data.get('inventory', []):
        if item['id'] == iid:
            item['low_stock_threshold'] = threshold
            save(data); backup()
            return jsonify({"ok": True, 'threshold': threshold})
    return jsonify({"ok": False, 'error': 'المادة غير موجودة'}), 404


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
    now = datetime.now()
    period = request.args.get('period', 'daily')
    category_filter = request.args.get('category', '').strip()
    product_filter = request.args.get('product', '').strip()
    cashier_filter = request.args.get('cashier', '').strip()
    date_from = request.args.get('from', '').strip()
    date_to = request.args.get('to', '').strip()

    # فلترة الطلبات حسب الفترة (يشمل الأرشيف البارد تلقائياً عند الحاجة)
    orders = _report_period_orders(data, period, date_from, date_to)

    if cashier_filter:
        orders = [o for o in orders if o.get('cashier_name', '') == cashier_filter]

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
            qty = i.get('quantity', i.get('qty', 1)) or 0
            price = i.get('price', 0) or 0
            order_subtotal = o.get('subtotal')
            if order_subtotal is None:
                order_subtotal = sum_money((row.get('price', 0) or 0) * (row.get('quantity', row.get('qty', 1)) or 0) for row in o.get('items', []))
            order_total = round_money(o.get('total', 0))
            net_factor = order_total / order_subtotal if order_subtotal else 0
            item_total = qty * price * net_factor
            entry = item_sales.setdefault(name, {'quantity': 0, 'total': 0, 'cost_total': 0, 'uncosted': False, 'dates': {}})
            entry['quantity'] += qty
            entry['total'] += item_total
            entry['dates'][odate] = entry['dates'].get(odate, 0) + qty
            product = next((row for products in data.get('menu', {}).values() for row in products
                            if str(row.get('id')) == str(i.get('product_id', i.get('id')))), None)
            if product is None:
                matches = [row for products in data.get('menu', {}).values() for row in products if row.get('name') == name]
                product = matches[0] if len(matches) == 1 else None
            unit_cost = i.get('unit_cost_snapshot') if 'unit_cost_snapshot' in i else compute_product_cost_as_of(
                data, product, o.get('timestamp') or o.get('date'))
            if unit_cost is None:
                entry['uncosted'] = True
            else:
                entry['cost_total'] += float(unit_cost) * qty

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

    # عند اختيار منتج/قسم توزع الخصومات على أصناف الطلب بنسبة قيمة كل صنف.
    def order_matches_filter(order):
        return not (category_filter or product_filter) or any(
            item.get('name', '') in filtered_items for item in order.get('items', []))

    def selected_order_total(order):
        if not (category_filter or product_filter):
            return round_money(order.get('total', 0))
        gross = sum((item.get('price', 0) or 0) * (item.get('quantity', item.get('qty', 1)) or 0)
                    for item in order.get('items', []) if item.get('name', '') in filtered_items)
        subtotal = order.get('subtotal')
        if subtotal is None:
            subtotal = sum_money((item.get('price', 0) or 0) * (item.get('quantity', item.get('qty', 1)) or 0)
                                 for item in order.get('items', []))
        return round_money(gross * round_money(order.get('total', 0)) / subtotal) if subtotal else 0.0

    selected_orders = [order for order in orders if order_matches_filter(order)]
    total_sales = sum_money(selected_order_total(order) for order in selected_orders)
    total_orders = len(selected_orders)

    # 1. متوسط قيمة الطلب
    avg_order = total_sales / total_orders if total_orders > 0 else 0

    # 2. نسبة/عدد كل نوع طلب
    type_stats = {'سفري': 0, 'صالة': 0, 'ديليفري': 0}
    for o in selected_orders:
        t = o.get('type', 'سفري')
        type_stats[t] = type_stats.get(t, 0) + 1
    type_pct = {k: round(v/total_orders*100, 1) if total_orders > 0 else 0 for k, v in type_stats.items()}

    # 3. أداء الموظفين
    cashier_stats = {}
    for o in selected_orders:
        c = o.get('cashier_name', 'غير معروف')
        if c not in cashier_stats:
            cashier_stats[c] = {'orders': 0, 'sales': 0}
        cashier_stats[c]['orders'] += 1
        cashier_stats[c]['sales'] += selected_order_total(o)

    # 4. صافي الربح
    # المصاريف (سلف الموظفين + شراء المواد الخام) تُصفّى حسب نفس الفترة المختارة تماماً مثل المبيعات،
    # بدل حسابها كاملة دائماً بغض النظر عن الفترة (كان هذا يُنتج صافي ربح خاطئ لليومي/الشهري).
    all_expenses = [e for e in data.get('expenses', []) if isinstance(e, dict) and not e.get('voided')]
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
    expense_base = {id(e): (expense_amount_base(data, e) or 0) for e in period_expenses}
    total_expenses = sum_money(expense_base.values())

    # فصل مشتريات المواد عن المصروفات التشغيلية حتى لا تختلط تكلفة المخزون مع الربح التشغيلي.
    purchase_expenses = [e for e in period_expenses if e.get('material_id') is not None]
    purchases_total = sum_money(expense_base[id(e)] for e in purchase_expenses)
    purchases_paid = sum_money(e.get('paid_amount_base', e.get('paid_amount', e.get('amount', 0))) or 0 for e in purchase_expenses)

    # قيد الراتب المستحق شهرياً مرة واحدة: لا تُطرح معه دفعات/سلف الموظف المسجلة كمصروف نقدي مرة ثانية.
    single_day = period == 'daily' or (period == 'custom' and date_from and date_to and date_from == date_to)
    salary_months = 0.0
    if period == 'monthly':
        salary_months = 1.0
    elif period == 'yearly' or (period == 'custom' and date_from and date_to and not single_day):
        try:
            start_date = datetime(now.year, 1, 1).date() if period == 'yearly' else datetime.strptime(date_from, '%Y-%m-%d').date()
            end_date = now.date() if period == 'yearly' else datetime.strptime(date_to, '%Y-%m-%d').date()
            if end_date >= start_date:
                cursor = start_date.replace(day=1)
                while cursor <= end_date:
                    next_month = datetime(cursor.year + (cursor.month == 12), 1 if cursor.month == 12 else cursor.month + 1, 1).date()
                    month_end = next_month - timedelta(days=1)
                    overlap_start, overlap_end = max(start_date, cursor), min(end_date, month_end)
                    days_in_month = (month_end - cursor).days + 1
                    salary_months += ((overlap_end - overlap_start).days + 1) / days_in_month
                    cursor = next_month
        except (TypeError, ValueError):
            salary_months = 0.0
    total_salaries = sum_money((e.get('salary', 0) or 0) * salary_months for e in data.get('employees', []))
    payroll_cash_expenses = sum_money(expense_base[id(e)] for e in period_expenses if e.get('employee_id') is not None)
    if not single_day:
        total_salaries = max(total_salaries, payroll_cash_expenses)
    other_expenses = total_expenses - purchases_total - (0 if single_day else payroll_cash_expenses)

    # تكلفة البضاعة المباعة: تعتمد على الوصفات ومتوسط سعر شراء المواد، وتُحسب فقط للأصناف ذات التكلفة المعروفة.
    cost_of_goods_sold = 0
    uncosted_products = []
    for name, entry in filtered_items.items():
        cost_of_goods_sold += entry.get('cost_total', 0) or 0
        if entry.get('uncosted'):
            uncosted_products.append(name)
    gross_profit = total_sales - cost_of_goods_sold
    gross_margin_pct = round((gross_profit / total_sales * 100), 1) if total_sales else 0
    operating_profit = gross_profit - other_expenses - total_salaries
    # التدفق النقدي ليس ربحًا على أساس الاستحقاق: شراء آجل لا يخرج نقدًا،
    # والدفعة الجزئية لا يجوز طرح كامل فاتورة المورد. احسبه من دفتر الصندوق
    # الفعلي ضمن نفس الفترة حتى تتطابق التحليلات مع النقد والبطاقات.
    period_cash_movements = [m for m in financial_cash_movements(data, period, date_from, date_to)
                             if _in_report_period(m.get('timestamp', ''), period, date_from, date_to)]
    cash_flow_after_purchases = sum_money(
        cash_movement_amount_base(data, m) * (1 if m.get('direction') == 'in' else -1)
        for m in period_cash_movements)
    inventory_value = sum((item.get('stock', 0) or 0) * (material_avg_cost(data, item.get('name', '')) or 0) for item in data.get('inventory', []))
    supplier_rows = supplier_summary(data)
    supplier_due = sum(row.get('due_total', 0) or 0 for row in supplier_rows)
    net_profit = operating_profit

    # 5. الديون المتراكمة (المتبقي غير المسدد فقط، وليس المبلغ الأصلي الكامل)
    total_debts = sum_money(
        amount_in_base(data, round_money(as_money(d.get('amount'), 0) - as_money(d.get('paid'), 0)),
                       d.get('currency', 'SYP'), d.get('exchange_rate')) or 0
        for d in data.get('debts', [])
    )

    # تفصيل الكاش الفعلي مقابل البطاقة (مهم لجرد الكاش بالدرج مقابل ما يذهب للبنك مباشرة).
    # الطلبات القديمة قبل هذا التحديث ما فيها cash_amount/card_amount فبنرجع لتخمين من حقل payment النصي.
    total_cash = 0
    total_card = 0
    for o in selected_orders:
        if 'cash_amount' in o or 'card_amount' in o:
            cash_amount = o.get('cash_amount', 0) or 0
            card_amount = o.get('card_amount', 0) or 0
        else:
            pm = o.get('payment', '')
            cash_amount = 0 if pm == 'بطاقة' else o.get('total', 0)
            card_amount = o.get('total', 0) if pm == 'بطاقة' else 0
        if category_filter or product_filter:
            order_total = round_money(o.get('total', 0))
            original_subtotal = o.get('subtotal')
            if original_subtotal is None:
                original_subtotal = sum_money((i.get('price', 0) or 0) * (i.get('quantity', i.get('qty', 1)) or 0) for i in o.get('items', []))
            selected_gross = sum((i.get('price', 0) or 0) * (i.get('quantity', i.get('qty', 1)) or 0)
                                 for i in o.get('items', [])
                                 if i.get('name', '') in filtered_items)
            selected_total = selected_gross * order_total / original_subtotal if original_subtotal else 0
            tender_ratio = selected_total / order_total if order_total else 0
            cash_amount, card_amount = round_money(cash_amount * tender_ratio), round_money(card_amount * tender_ratio)
        total_cash += cash_amount
        total_card += card_amount

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
        discount_amount = o.get('discount_total')
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
            'cash_amount': round_money((o.get('cash_amount', 0) or 0) * (detail_total / original_total)) if (category_filter or product_filter) and original_total else (o.get('cash_amount', 0) or 0),
            'card_amount': round_money((o.get('card_amount', 0) or 0) * (detail_total / original_total)) if (category_filter or product_filter) and original_total else (o.get('card_amount', 0) or 0),
            'customer': o.get('customer', ''),
            'table': o.get('table', ''),
            'cashier_name': o.get('cashier_name', 'غير معروف'),
            'subtotal': round(filtered_subtotal, 2),
            'discount': round(discount_amount if not (category_filter or product_filter) else discount_amount * (filtered_subtotal / original_subtotal if original_subtotal else 0), 2),
            'total': round(detail_total, 2),
            'voided': bool(o.get('voided')),
            'print_status': order_print_status_label(o),
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


def _report_period_orders(data, period='daily', date_from='', date_to=''):
    """يجمع الفواتير الصحيحة ضمن الفترة المطلوبة لاستعمالها بالتقرير والتصدير.
    يدمج تلقائياً فواتير الأرشيف البارد (الأقدم من فترة الاحتفاظ في data.json)
    عندما يحتاجها المدى المطلوب فعلاً، حتى تبقى التقارير التاريخية (سنوي/مدى
    مخصص) صحيحة تماماً ولو مرّت سنوات وتم نقل فواتير قديمة للأرشيف البارد."""
    now = datetime.now()
    retention_cutoff = (now - timedelta(days=ARCHIVE_RETENTION_DAYS)).strftime('%Y-%m-%d')
    if date_from or date_to:
        eff_from, eff_to = date_from, date_to
    elif period == 'daily':
        eff_from = eff_to = now.strftime('%Y-%m-%d')
    elif period == 'monthly':
        eff_from = now.strftime('%Y-%m-01')
        eff_to = now.strftime('%Y-%m-%d')
    elif period == 'yearly':
        eff_from = now.strftime('%Y-01-01')
        eff_to = now.strftime('%Y-%m-%d')
    else:
        eff_from = eff_to = ''  # 'custom' بلا تواريخ، أو فترة غير معروفة: كل شيء

    orders = [o for o in data.get('orders', []) + data.get('orders_archive', [])
              if not o.get('voided') and o.get('type') != 'تسديد دين' and o.get('accounting_type') != 'debt_payment']
    needs_cold = (not eff_from) or (eff_from < retention_cutoff)
    if needs_cold:
        cold = [o for o in load_cold_orders(eff_from, eff_to) if not o.get('voided')
                and o.get('type') != 'تسديد دين' and o.get('accounting_type') != 'debt_payment']
        if cold:
            live_ids = {str(o.get('id')) for o in orders}
            orders += [o for o in cold if str(o.get('id')) not in live_ids]

    if eff_from or eff_to:
        orders = [o for o in orders if (not eff_from or _order_stamp(o)[:10] >= eff_from) and (not eff_to or _order_stamp(o)[:10] <= eff_to)]
    return orders


def order_print_status_label(order):
    """يعيد وصفًا عربيًا موجزًا لحالة إرسال الإيصال وتذكرة المطبخ المحفوظة مع الفاتورة."""
    saved = order.get('print_status', {}) or {}
    labels = {'sent': 'تم الإرسال', 'failed': 'فشل الإرسال', 'skipped': 'لم يُنفذ', 'disabled': 'غير مفعّل'}
    parts = []
    for key, title in (('receipt', 'الإيصال'), ('kitchen', 'المطبخ')):
        job = saved.get(key, {}) if isinstance(saved, dict) else {}
        status = job.get('status') if isinstance(job, dict) else None
        parts.append(f'{title}: {labels.get(status, "غير مسجل")}')
    return ' · '.join(parts)


def _in_report_period(timestamp, period, date_from='', date_to=''):
    """يتحقق من دخول سجل الصندوق ضمن فترة التقرير."""
    value = str(timestamp or '')
    now = datetime.now()
    if date_from or date_to:
        return (not date_from or value[:10] >= date_from) and (not date_to or value[:10] <= date_to)
    if period == 'daily':
        return value.startswith(now.strftime('%Y-%m-%d'))
    if period == 'monthly':
        return value.startswith(now.strftime('%Y-%m'))
    if period == 'yearly':
        return value.startswith(now.strftime('%Y'))
    if period == 'custom':
        return (not date_from or value[:10] >= date_from) and (not date_to or value[:10] <= date_to)
    return True


def financial_report_payload(data, period='daily', date_from='', date_to='', cashier_filter=''):
    """يبني تقريرًا ماليًا قابلًا للتدقيق، مجمعًا حسب الكاشير قيصر وقناة الدفع."""
    orders = _report_period_orders(data, period, date_from, date_to)
    if cashier_filter:
        orders = [order for order in orders if order.get('cashier_name', '') == cashier_filter]
    cashier_rows = {}
    for order in orders:
        cashier = order.get('cashier_name') or 'غير معروف'
        row = cashier_rows.setdefault(cashier, {
            'cashier': cashier, 'orders': 0, 'sales': 0.0, 'cash': 0.0, 'card': 0.0,
            'discounts': 0.0, 'dine_in_orders': 0, 'takeaway_orders': 0, 'delivery_orders': 0
        })
        total = round_money(order.get('total', 0) or 0)
        subtotal = round_money(order.get('subtotal', total) or total)
        discount_value = order.get('discount_total')
        discount = round_money(max(0, subtotal - total) if discount_value is None else (discount_value or 0))
        cash_amount = order.get('cash_amount')
        card_amount = order.get('card_amount')
        if cash_amount is None and card_amount is None:
            cash_amount = 0 if order.get('payment') == 'بطاقة' else total
            card_amount = total if order.get('payment') == 'بطاقة' else 0
        row['orders'] += 1
        row['sales'] += total
        row['cash'] += round_money(cash_amount or 0)
        row['card'] += round_money(card_amount or 0)
        row['discounts'] += discount
        order_type = order.get('type', 'سفري')
        if order_type == 'صالة':
            row['dine_in_orders'] += 1
        elif order_type == 'ديليفري':
            row['delivery_orders'] += 1
        else:
            row['takeaway_orders'] += 1
    cashier_summary = []
    for row in cashier_rows.values():
        row['average_order'] = round_money(row['sales'] / row['orders']) if row['orders'] else 0
        for key in ('sales', 'cash', 'card', 'discounts'):
            row[key] = round_money(row[key])
        cashier_summary.append(row)
    cashier_summary.sort(key=lambda row: (-row['sales'], row['cashier']))
    cashbook = [movement for movement in financial_cash_movements(data, period, date_from, date_to)
                if _in_report_period(movement.get('timestamp'), period, date_from, date_to)]
    cash_in = sum_money(cash_movement_amount_base(data, m) for m in cashbook if m.get('channel') == 'cash' and m.get('direction') == 'in')
    cash_out = sum_money(cash_movement_amount_base(data, m) for m in cashbook if m.get('channel') == 'cash' and m.get('direction') == 'out')
    card_in = sum_money(cash_movement_amount_base(data, m) for m in cashbook if m.get('channel') == 'card' and m.get('direction') == 'in')
    card_out = sum_money(cash_movement_amount_base(data, m) for m in cashbook if m.get('channel') == 'card' and m.get('direction') == 'out')
    return {
        'period': period, 'from': date_from, 'to': date_to, 'cashier_filter': cashier_filter,
        'cashier_summary': cashier_summary, 'orders': orders,
        'cashbook': [normalized_cash_movement(data, row) for row in sorted(cashbook, key=lambda row: str(row.get('timestamp', '')), reverse=True)],
        'summary': {
            'sales': sum_money(order.get('total', 0) or 0 for order in orders), 'orders': len(orders),
            'cash_in': round_money(cash_in), 'cash_out': round_money(cash_out), 'cash_balance': round_money(cash_in - cash_out),
            'card_in': round_money(card_in), 'card_out': round_money(card_out), 'card_balance': round_money(card_in - card_out)
        }
    }


@app.route('/api/analytics/financial', methods=['GET'])
def financial_analytics():
    if not has_role('manager', 'supervisor'):
        return permission_error()
    period = request.args.get('period', 'daily')
    if period not in {'daily', 'monthly', 'yearly', 'custom', 'all'}:
        return jsonify({'ok': False, 'error': 'فترة التقرير غير صالحة'}), 400
    return jsonify({'ok': True, **financial_report_payload(load(), period, request.args.get('from', '').strip(), request.args.get('to', '').strip(), request.args.get('cashier', '').strip())})


def _excel_column(index):
    result = ''
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _xlsx_sheet(rows):
    body = []
    for row_number, row in enumerate(rows, 1):
        cells = []
        for column_number, value in enumerate(row, 1):
            reference = f'{_excel_column(column_number)}{row_number}'
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                cells.append(f'<c r="{reference}"><v>{value}</v></c>')
            else:
                cells.append(f'<c r="{reference}" t="inlineStr"><is><t>{xml_escape(str(value if value is not None else ""))}</t></is></c>')
        body.append(f'<row r="{row_number}">{"".join(cells)}</row>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetViews><sheetView rightToLeft="1" workbookViewId="0"/></sheetViews><sheetData>' + ''.join(body) + '</sheetData></worksheet>').encode('utf-8')


def create_financial_xlsx(report):
    """ينشئ ملف Excel حقيقيًا بأربع أوراق باستخدام مكتبات Python القياسية فقط."""
    summary = report['summary']
    sheets = [
        ('الملخص المالي', [['تقرير مالي ومبيعات - كاشير قيصر قيصر'], ['الفترة', report['period']], ['من', report['from'] or '—'], ['إلى', report['to'] or '—'], [], ['البند', 'القيمة'], ['إجمالي المبيعات', summary['sales']], ['عدد الفواتير', summary['orders']], ['نقد داخل', summary['cash_in']], ['نقد خارج', summary['cash_out']], ['رصيد النقد', summary['cash_balance']], ['بطاقة داخل', summary['card_in']], ['بطاقة خارج', summary['card_out']], ['رصيد البطاقات', summary['card_balance']]]),
        ('مبيعات الكاشير قيصر', [['الكاشير قيصر', 'عدد الفواتير', 'المبيعات', 'النقد', 'البطاقات', 'الخصومات', 'متوسط الفاتورة', 'صالة', 'سفري', 'ديليفري']] + [[row['cashier'], row['orders'], row['sales'], row['cash'], row['card'], row['discounts'], row['average_order'], row['dine_in_orders'], row['takeaway_orders'], row['delivery_orders']] for row in report['cashier_summary']]),
        ('الفواتير', [['رقم الفاتورة', 'التاريخ', 'الكاشير قيصر', 'النوع', 'الدفع', 'النقد', 'البطاقات', 'الخصم', 'الإجمالي', 'حالة الطباعة', 'الطاولة', 'الزبون', 'الأصناف']] + [[order.get('id', ''), order.get('timestamp') or order.get('date', ''), order.get('cashier_name', 'غير معروف'), order.get('type', 'سفري'), order.get('payment', ''), order.get('cash_amount', ''), order.get('card_amount', ''), order.get('discount_total', max(0, (order.get('subtotal') or 0) - (order.get('total') or 0))), order.get('total', 0), order_print_status_label(order), order.get('table', ''), order.get('customer', ''), '، '.join(f"{item.get('name', '')} × {item.get('quantity', item.get('qty', 1))}" for item in order.get('items', []))] for order in report['orders']]),
        ('دفتر الصندوق', [['التاريخ', 'الاتجاه', 'القناة', 'التصنيف', 'المبلغ', 'الكاشير قيصر/المستخدم', 'المرجع', 'الملاحظة']] + [[movement.get('timestamp', ''), movement.get('direction', ''), movement.get('channel', ''), movement.get('category', ''), movement.get('amount', 0), movement.get('created_by', ''), movement.get('reference_id', ''), movement.get('note', '')] for movement in report['cashbook']])
    ]
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        overrides = ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1, len(sheets) + 1))
        archive.writestr('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>' + overrides + '</Types>')
        archive.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr('xl/workbook.xml', '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>' + ''.join(f'<sheet name="{xml_escape(name)}" sheetId="{i}" r:id="rId{i}"/>' for i, (name, _) in enumerate(sheets, 1)) + '</sheets></workbook>')
        archive.writestr('xl/_rels/workbook.xml.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + ''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets) + 1)) + '</Relationships>')
        for index, (_, rows) in enumerate(sheets, 1):
            archive.writestr(f'xl/worksheets/sheet{index}.xml', _xlsx_sheet(rows))
    buffer.seek(0)
    return buffer


def create_print_log_xlsx(rows):
    """ينشئ ملف Excel مستقلًا لسجل محاولات الطباعة لتتبع الأعطال لاحقًا."""
    status_labels = {'sent': 'تم الإرسال', 'failed': 'فشل الإرسال', 'skipped': 'لم يُنفذ', 'disabled': 'غير مفعّل'}
    sheet_rows = [['سجل حالات الطباعة - كاشير قيصر قيصر'], ['تاريخ التصدير', datetime.now().isoformat(timespec='seconds')], [], ['التاريخ', 'رقم الطلب', 'النوع', 'الحالة', 'الطابعة', 'الرسالة']]
    sheet_rows.extend([[row.get('timestamp', ''), row.get('order_id', ''), 'إيصال العميل' if row.get('type') == 'receipt' else 'تذكرة المطبخ', status_labels.get(row.get('status'), row.get('status', '')), row.get('printer', ''), row.get('message', '')] for row in rows])
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('[Content_Types].xml', '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>')
        archive.writestr('_rels/.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr('xl/workbook.xml', '<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets><sheet name="سجل الطباعة" sheetId="1" r:id="rId1"/></sheets></workbook>')
        archive.writestr('xl/_rels/workbook.xml.rels', '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>')
        archive.writestr('xl/worksheets/sheet1.xml', _xlsx_sheet(sheet_rows))
    buffer.seek(0)
    return buffer


@app.route('/api/analytics/financial.xlsx', methods=['GET'])
def export_financial_xlsx():
    if not has_role('manager', 'supervisor'):
        return permission_error()
    period = request.args.get('period', 'daily')
    if period not in {'daily', 'monthly', 'yearly', 'custom', 'all'}:
        return jsonify({'ok': False, 'error': 'فترة التقرير غير صالحة'}), 400
    report = financial_report_payload(load(), period, request.args.get('from', '').strip(), request.args.get('to', '').strip(), request.args.get('cashier', '').strip())
    return send_file(create_financial_xlsx(report), as_attachment=True, download_name=f"financial_report_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx", mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


def _pdf_text(value):
    text = str(value if value is not None else '')
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(text))
    except ImportError:
        return text


def create_financial_pdf(report):
    """ينشئ تقرير مبيعات PDF عربيًا محليًا باستخدام خط Tajawal المضمّن."""
    if not REPORTLAB_AVAILABLE:
        return None
    output = BytesIO()
    font_name = 'Helvetica'
    font_path = os.path.join(APP_PATH, 'fonts', 'Tajawal-Regular.ttf')
    if os.path.exists(font_path):
        try:
            pdfmetrics.registerFont(TTFont('CAESARTajawal', font_path))
            font_name = 'CAESARTajawal'
        except Exception:
            pass
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('CAESARTitle', parent=styles['Title'], fontName=font_name, fontSize=17, leading=22, alignment=TA_CENTER, spaceAfter=12)
    body_style = ParagraphStyle('CAESARBody', parent=styles['BodyText'], fontName=font_name, fontSize=9.5, leading=14, alignment=TA_RIGHT)
    small_style = ParagraphStyle('CAESARSmall', parent=body_style, fontSize=8, leading=11)
    doc = SimpleDocTemplate(output, pagesize=A4, rightMargin=36, leftMargin=36, topMargin=34, bottomMargin=34, title='تقرير مبيعات كاشير قيصر قيصر')
    summary = report.get('summary', {})
    story = [Paragraph(_pdf_text('كاشير قيصر قيصر — تقرير المبيعات اليومية'), title_style)]
    meta = f"الفترة: {report.get('from') or 'اليوم'} إلى {report.get('to') or 'اليوم'} | الكاشير قيصر: {report.get('cashier_filter') or 'جميع الكاشير قيصرات'}"
    story.extend([Paragraph(_pdf_text(meta), body_style), Spacer(1, 10)])
    summary_rows = [
        [_pdf_text('البند'), _pdf_text('القيمة')],
        [_pdf_text('إجمالي المبيعات'), _pdf_text(summary.get('sales', 0))],
        [_pdf_text('عدد الفواتير'), _pdf_text(summary.get('orders', 0))],
        [_pdf_text('النقد الداخل'), _pdf_text(summary.get('cash_in', 0))],
        [_pdf_text('البطاقات الداخلة'), _pdf_text(summary.get('card_in', 0))],
        [_pdf_text('رصيد النقد'), _pdf_text(summary.get('cash_balance', 0))],
    ]
    summary_table = Table(summary_rows, colWidths=[270, 180], repeatRows=1)
    summary_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), font_name), ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1d4ed8')), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.HexColor('#cbd5e1')), ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
        ('TOPPADDING', (0, 0), (-1, -1), 7), ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
    ]))
    story.extend([summary_table, Spacer(1, 14), Paragraph(_pdf_text('تفاصيل الفواتير'), body_style), Spacer(1, 6)])
    invoice_rows = [[_pdf_text('رقم الفاتورة'), _pdf_text('التاريخ'), _pdf_text('الكاشير قيصر'), _pdf_text('الدفع'), _pdf_text('الإجمالي')]]
    for order in report.get('orders', []):
        invoice_rows.append([
            _pdf_text(order.get('id', '')),
            _pdf_text((order.get('timestamp') or order.get('date') or '')[:19]),
            _pdf_text(order.get('cashier_name', 'غير معروف')),
            _pdf_text(order.get('payment', '')),
            _pdf_text(order.get('total', 0)),
        ])
    if len(invoice_rows) == 1:
        invoice_rows.append([_pdf_text('لا توجد فواتير ضمن الفترة'), '', '', '', ''])
    invoice_table = Table(invoice_rows, colWidths=[92, 130, 105, 80, 70], repeatRows=1)
    invoice_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), font_name), ('FONTSIZE', (0, 0), (-1, -1), 7.5),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0f172a')), ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('GRID', (0, 0), (-1, -1), 0.35, colors.HexColor('#cbd5e1')), ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8fafc')]),
        ('TOPPADDING', (0, 0), (-1, -1), 5), ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(invoice_table)
    story.extend([Spacer(1, 12), Paragraph(_pdf_text('تم إنشاء هذا الملف محليًا من بيانات الخزنة الحالية.'), small_style)])
    doc.build(story)
    output.seek(0)
    return output


@app.route('/api/analytics/financial.pdf', methods=['GET'])
def export_financial_pdf():
    if not has_role('manager', 'supervisor'):
        return permission_error()
    if not REPORTLAB_AVAILABLE:
        return jsonify({'ok': False, 'error': 'تصدير PDF غير متاح في هذه النسخة'}), 503
    period = request.args.get('period', 'daily')
    if period not in {'daily', 'monthly', 'yearly', 'custom', 'all'}:
        return jsonify({'ok': False, 'error': 'فترة التقرير غير صالحة'}), 400
    report = financial_report_payload(load(), period, request.args.get('from', '').strip(), request.args.get('to', '').strip(), request.args.get('cashier', '').strip())
    return send_file(create_financial_pdf(report), as_attachment=True, download_name=f"financial_report_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf", mimetype='application/pdf')


@app.route('/api/analytics/print-log.xlsx', methods=['GET'])
def export_print_log_xlsx():
    if not has_role('manager', 'supervisor'):
        return permission_error()
    date_from = request.args.get('from', '').strip()
    date_to = request.args.get('to', '').strip()
    status = request.args.get('status', '').strip()
    ticket_type = request.args.get('type', '').strip()
    printer_query = request.args.get('printer', '').strip().casefold()
    sort_by = request.args.get('sort', 'timestamp_desc').strip()
    rows = [row for row in load().get('print_log', []) if (not date_from or str(row.get('timestamp', ''))[:10] >= date_from) and (not date_to or str(row.get('timestamp', ''))[:10] <= date_to) and (not status or row.get('status') == status) and (not ticket_type or row.get('type') == ticket_type) and (not printer_query or printer_query in str(row.get('printer', '')).casefold())]
    if sort_by == 'printer_asc':
        rows.sort(key=lambda row: (str(row.get('printer', '')).casefold(), str(row.get('timestamp', ''))))
    elif sort_by == 'printer_desc':
        rows.sort(key=lambda row: (str(row.get('printer', '')).casefold(), str(row.get('timestamp', ''))), reverse=True)
    else:
        rows.sort(key=lambda row: str(row.get('timestamp', '')), reverse=True)
    return send_file(create_print_log_xlsx(rows), as_attachment=True, download_name=f"print_log_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx", mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


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
        if low.endswith('.zip') and ('caesar' in low or 'caesar' in low):
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
    license_id = str(payload.get('license_id', '')).strip() or ('CAESAR-' + uuid.uuid4().hex[:10].upper())
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
            f.write(f'نسخة مستقلة للمطعم: {restaurant_name}\\nالمالك: {owner_name}\\nرقم الترخيص: {license_id}\\n\\n1. شغّل Start.bat (أو اختصار سطح المكتب الذي ينشئه Install_CAESAR_Desktop_Icon.bat).\\n2. أكمل الإعداد الأولي وأنشئ المدير.\\n3. لا تنسخ بيانات هذه النسخة إلى مطعم آخر.\\n')
        with open(os.path.join(tmp, 'CLIENT_SETUP.txt'), 'a', encoding='utf-8') as f:
            f.write(
                '\nتشغيل USB: شغّل USB_Start.bat من جذر المجلد أو الفلاشة.\n'
                'اقرأ دليل_التشغيل_الكامل_AR.md وتقرير DELIVERY_QA_REPORT_AR.md قبل أول وردية.\n'
                'راجع تشغيل_من_USB_AR.md لاختبار النسخة المحمولة.\n'
            )
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
    return jsonify({"name": r.get('name', ''), "phone": r.get('phone', ''), "address": r.get('address', ''), "brand_logo_data": r.get('brand_logo_data', '')})

@app.route('/api/settings/restaurant', methods=['POST'])
def set_restaurant():
    data = load()
    if 'settings' not in data:
        data['settings'] = {}
    existing = data['settings'].get('restaurant', {})
    payload = request.get_json(silent=True) or {}
    brand_logo_data = str(payload.get('brand_logo_data', existing.get('brand_logo_data', '')) or '')
    if brand_logo_data and (not brand_logo_data.startswith('data:image/') or len(brand_logo_data) > 300000):
        return jsonify({'ok': False, 'error': 'شعار واجهات المطعم يجب أن يكون صورة محلية لا تتجاوز 200 كيلوبايت'}), 400
    data['settings']['restaurant'] = {
        'name': str(payload.get('name', existing.get('name', '')) or '')[:80],
        'phone': str(payload.get('phone', existing.get('phone', '')) or '')[:50],
        'address': str(payload.get('address', existing.get('address', '')) or '')[:180],
        'brand_logo_data': brand_logo_data
    }
    save(data)
    return jsonify({"ok": True})

@app.route('/api/restaurant/name', methods=['GET'])
def get_restaurant_name():
    """يُستخدم من شاشة الكاشير قيصر لعرض اسم المطعم بالهيدر"""
    data = load()
    r = data.get('settings', {}).get('restaurant', {})
    return jsonify({"name": r.get('name', '')})

@app.route('/api/restaurant/identity', methods=['GET'])
def get_restaurant_identity():
    """هوية عرض آمنة للواجهات؛ لا تشمل أي بيانات تشغيل أو مستخدمين."""
    data = load()
    r = data.get('settings', {}).get('restaurant', {})
    return jsonify({"name": r.get('name', ''), "brand_logo_data": r.get('brand_logo_data', '')})


@app.route('/api/settings/features', methods=['GET', 'POST'])
def feature_settings():
    data = load()
    if request.method == 'POST' and session.get('role') != 'manager':
        return jsonify({'ok': False, 'error': 'إعدادات الميزات للمدير فقط'}), 403
    if request.method == 'GET':
        return jsonify(get_feature_flags(data))
    payload = request.get_json(silent=True) or {}
    settings = data.setdefault('settings', {})
    current = get_feature_flags(data)
    settings['features'] = {key: bool(payload.get(key, current[key])) for key in FEATURE_DEFAULTS}
    save(data)
    return jsonify({'ok': True, 'features': settings['features']})

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
            ['powershell', '-WindowStyle', 'Hidden', '-NoProfile', '-Command', 'Get-Printer | Select-Object -ExpandProperty Name'],
            capture_output=True, text=True, timeout=8
        )
        return [n.strip() for n in result.stdout.splitlines() if n.strip()]
    except Exception:
        return []

def list_windows_printer_status():
    """يعيد الحالة الحية من Win32_Printer، لا مجرد أسماء الطابعات المثبتة."""
    if sys.platform != 'win32':
        return []
    command = "Get-CimInstance Win32_Printer | Select-Object Name,PrinterStatus,WorkOffline,DetectedErrorState,PrinterState,Status | ConvertTo-Json -Compress"
    try:
        result = subprocess.run(['powershell', '-WindowStyle', 'Hidden', '-NoProfile', '-Command', command], capture_output=True, text=True, timeout=8)
        raw = json.loads(result.stdout or '[]')
        rows = raw if isinstance(raw, list) else ([raw] if isinstance(raw, dict) else [])
        output = []
        for row in rows:
            if not isinstance(row, dict) or not str(row.get('Name') or '').strip():
                continue
            status_code = int(row.get('PrinterStatus') or 0)
            offline = bool(row.get('WorkOffline')) or str(row.get('Status') or '').lower() in {'offline', 'error'} or int(row.get('DetectedErrorState') or 0) not in {0, 1}
            output.append({'name': str(row.get('Name')).strip(), 'status_code': status_code, 'work_offline': offline, 'error_state': row.get('DetectedErrorState'), 'printer_state': row.get('PrinterState'), 'status': 'offline' if offline else ('ready' if status_code in {0, 3, 4, 5, 6, 7, 8, 9, 10} else 'unknown')})
        return output
    except (OSError, ValueError, TypeError, subprocess.SubprocessError):
        return []

def get_default_windows_printer():
    try:
        result = subprocess.run(
            ['powershell', '-WindowStyle', 'Hidden', '-NoProfile', '-Command',
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

RECEIPT_RS = '\x01'   # بداية أمر تنسيق داخل نص الإيصال (ليس \x1c-\x1e لأن splitlines يكسرها)
RECEIPT_US = '\x02'   # فاصل حقول الأمر


def _draw_structured_receipt(text, width, font, bold_font, big_font, scale, visual):
    """يرسم إيصالاً مقسّماً بإطارات وأعمدة بعرض بكسلات ثابتة (لا يعتمد على مسافات الخط).

    الأوامر (سطر يبدأ بـ RS ويفصل حقوله US): RULE، GAP، C (نص وسط)، BOX/ENDBOX (إطار)،
    ROW (صف أعمدة مع نسب ومحاذاة)، KV (عنوان يمين وقيمة يسار).
    """
    probe = ImageDraw.Draw(Image.new('L', (width, 10), 255))
    margin, pad = 6, 6
    inner_w = width - 2 * margin
    line_h = scale + 10

    def text_w(value, fnt):
        return probe.textbbox((0, 0), visual(value), font=fnt)[2]

    def wrap_to(value, max_w, fnt):
        value = str(value or '')
        if not value:
            return ['']
        # أرقام الكمية والسعر والقيمة بيانات ذرية: تقسيم 1,481,472 إلى
        # سطرين يغيّر معناه بصرياً. الأسماء فقط هي التي يسمح لها بالانقسام.
        bare_value = value.replace('\u200e', '').replace('\u200f', '').strip()
        if re.fullmatch(r'[-+]?[0-9٠-٩][0-9٠-٩,\.]*', bare_value or ''):
            return [value]
        out, cur = [], ''
        for word in value.split(' '):
            cand = word if not cur else cur + ' ' + word
            if cur and text_w(cand, fnt) > max_w:
                out.append(cur)
                cur = word
            else:
                cur = cand
            if text_w(cur, fnt) > max_w:
                chunk = ''
                for ch in cur:
                    if chunk and text_w(chunk + ch, fnt) > max_w:
                        out.append(chunk)
                        chunk = ch
                    else:
                        chunk += ch
                cur = chunk
        out.append(cur)
        return out

    ops = []
    for raw in str(text or '').splitlines():
        if not raw.startswith(RECEIPT_RS):
            for part in wrap_to(raw, inner_w - 2 * pad, font):
                ops.append({'k': 'c', 'lines': [part], 'font': font, 'h': line_h})
            continue
        parts = raw[1:].split(RECEIPT_US)
        cmd = parts[0]
        if cmd == 'RULE':
            ops.append({'k': 'rule', 'h': 10})
        elif cmd == 'GAP':
            ops.append({'k': 'gap', 'h': int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 8})
        elif cmd == 'BOX':
            ops.append({'k': 'box', 'h': 0})
        elif cmd == 'ENDBOX':
            ops.append({'k': 'endbox', 'h': 0})
        elif cmd == 'C':
            fnt = big_font if len(parts) > 3 and parts[3] == '1' else (bold_font if len(parts) > 2 and parts[2] == '1' else font)
            lines = wrap_to(parts[1] if len(parts) > 1 else '', inner_w - 2 * pad, fnt)
            ops.append({'k': 'c', 'lines': lines, 'font': fnt, 'h': len(lines) * (line_h + (4 if fnt is big_font else 0))})
        elif cmd == 'KV':
            label = parts[1] if len(parts) > 1 else ''
            value = parts[2] if len(parts) > 2 else ''
            fnt = bold_font if len(parts) > 3 and parts[3] == '1' else font
            ops.append({'k': 'kv', 'label': label, 'value': value, 'font': fnt, 'h': line_h + 4})
        elif cmd == 'ROW' and len(parts) >= 6:
            sep = parts[1] != '0'
            dotted = parts[1] == '2'
            ratios = [max(1.0, float(x)) for x in parts[2].split(',') if x]
            aligns = parts[3].split(',')
            fnt = bold_font if parts[4] == '1' else font
            cells = parts[5:]
            total_ratio = sum(ratios[:len(cells)]) or 1.0
            xs, x_right = [], width - margin
            for idx in range(len(cells)):
                col_w = inner_w * ratios[idx] / total_ratio
                xs.append((x_right - col_w, x_right))
                x_right -= col_w
            cell_fonts = []
            wrapped = []
            for i, cell in enumerate(cells):
                cell_font = fnt
                cell_width = max(10, (xs[i][1] - xs[i][0]) - 2 * pad)
                bare_cell = str(cell or '').replace('\u200e', '').replace('\u200f', '').strip()
                # 58mm يخصص أكثر من ربع السطر للأرقام، ومع ذلك نخفض خط
                # الرقم فقط إن احتاج لتبقى الفواصل داخل عموده ولا نغير 80mm.
                if width <= 384 and re.fullmatch(r'[-+]?[0-9٠-٩][0-9٠-٩,\.]*', bare_cell or '') and text_w(cell, cell_font) > cell_width:
                    try:
                        cell_font = cell_font.font_variant(size=max(10, int(getattr(cell_font, 'size', scale) * 0.72)))
                    except (AttributeError, OSError, ValueError):
                        pass
                cell_fonts.append(cell_font)
                wrapped.append(wrap_to(cell, cell_width, cell_font))
            rows = max(len(w) for w in wrapped)
            ops.append({'k': 'row', 'sep': sep, 'dotted': dotted, 'xs': xs, 'aligns': aligns, 'font': fnt, 'fonts': cell_fonts, 'cells': wrapped,
                        'h': rows * line_h + 8})
    height = sum(op['h'] for op in ops) + 20
    image = Image.new('L', (width, max(32, height)), 255)
    draw = ImageDraw.Draw(image)
    y = 10
    box_tops = []

    def put(value, fnt, x_left, x_right_edge, align, y_top):
        shaped = visual(value)
        bb = draw.textbbox((0, 0), shaped, font=fnt)
        w = bb[2] - bb[0]
        if align == 'r':
            x = x_right_edge - pad - w
        elif align == 'l':
            x = x_left + pad
        else:
            x = x_left + ((x_right_edge - x_left) - w) / 2
        draw.text((x, y_top - bb[1]), shaped, fill=0, font=fnt)

    for op in ops:
        kind = op['k']
        if kind == 'rule':
            draw.line([(margin, y + 4), (width - margin, y + 4)], fill=0, width=2)
        elif kind == 'box':
            box_tops.append(y)
        elif kind == 'endbox':
            top = box_tops.pop() if box_tops else y
            draw.rectangle([margin, top, width - margin, y], outline=0, width=2)
        elif kind == 'c':
            fh = op['h'] // max(1, len(op['lines']))
            for i, part in enumerate(op['lines']):
                put(part, op['font'], margin, width - margin, 'c', y + i * fh + 3)
        elif kind == 'kv':
            put(op['label'], op['font'], margin, width - margin, 'r', y + 3)
            put(op['value'], op['font'], margin, width - margin, 'l', y + 3)
        elif kind == 'row':
            for i, lines in enumerate(op['cells']):
                x0, x1 = op['xs'][i]
                align = op['aligns'][i] if i < len(op['aligns']) else 'c'
                if op['sep'] and i < len(op['cells']) - 1:
                    # ارسم الفاصل خلف النص؛ لا يجوز أن يمر الخط فوق آخر حرف
                    # عندما تكون الخانة ضيقة، خصوصاً في 58mm الطولي.
                    draw.line([(x0, y), (x0, y + op['h'])], fill=0, width=1)
                for j, part in enumerate(lines):
                    put(part, op['fonts'][i], x0, x1, align, y + 4 + j * line_h)
            if op['sep']:
                if op.get('dotted'):
                    for x in range(margin, width - margin, 5):
                        draw.line([(x, y + op['h']), (min(x + 2, width - margin), y + op['h'])], fill=0, width=1)
                else:
                    draw.line([(margin, y + op['h']), (width - margin, y + op['h'])], fill=0, width=1)
        y += op['h']
    return image.crop((0, 0, width, max(y + 10, 32)))


def render_escpos_raster_payload(text, paper_width=80, font_size='medium', logo_data='', logo_size='medium', logo_alignment='center', text_alignment='center', print_density=80, print_quality='normal'):
    """يرسم العربية بخط Tajawal ثم يحولها إلى صورة ESC/POS أحادية اللون.

    لا نرسل UTF-8 خامًا إلى الطابعة؛ أغلب طابعات ESC/POS لا تعرف UTF-8 العربي
    وتطبع رموزًا. الرسم كصورة يتجاوز اختلاف code page ويدعم العربية RTL دائمًا.
    """
    # Standard printable dot widths: 58mm≈384, 80mm≈576, 112mm≈832 at
    # 203dpi. The old code treated 112mm as 80mm, which clipped wide receipts.
    try:
        paper_width = int(paper_width or 80)
    except (TypeError, ValueError):
        paper_width = 80
    width = {58: 384, 80: 576, 112: 832}.get(paper_width, 576)
    # Keep enough pixels per glyph for Arabic diacritics and avoid collisions
    # between adjacent raster rows on dense thermal heads.
    scale = {'small': 18, 'medium': 23, 'large': 29}.get(str(font_size or 'medium'), 23)
    font_candidates = (
        os.path.join(BASE_DIR, 'fonts', 'Tajawal-Regular.ttf'),
        os.path.join(BASE_DIR, 'fonts', 'Tajawal-Bold.ttf'),
    )
    font = ImageFont.load_default()
    for font_path in font_candidates:
        if os.path.exists(font_path):
            try:
                font = ImageFont.truetype(font_path, scale)
                break
            except (OSError, ValueError):
                continue
    bold_font, big_font = font, font
    bold_path = os.path.join(BASE_DIR, 'fonts', 'Tajawal-Bold.ttf')
    if os.path.exists(bold_path):
        try:
            bold_font = ImageFont.truetype(bold_path, scale)
            big_font = ImageFont.truetype(bold_path, scale + 7)
        except (OSError, ValueError):
            pass
    probe = ImageDraw.Draw(Image.new('L', (width, 10), 255))
    max_text_width = width - 24

    def visual(value):
        value = str(value or '')
        try:
            return get_display(arabic_reshaper.reshape(value)).replace('\u200e', '').replace('\u200f', '')
        except Exception:
            return value

    def wrap(value):
        """Wrap on words first, then split only an overlong token by glyph.

        Character-only wrapping can separate Arabic words and produce visually
        crowded lines. Measuring the shaped visual string also keeps RTL text
        inside the printable area before it reaches the printer.
        """
        value = str(value or '').replace('\t', '    ')
        if not value:
            return ['']
        result, current = [], ''
        for word in value.split(' '):
            candidate = word if not current else current + ' ' + word
            if current and probe.textbbox((0, 0), visual(candidate), font=font)[2] > max_text_width:
                result.append(current)
                current = word
            else:
                current = candidate
            if probe.textbbox((0, 0), visual(current), font=font)[2] <= max_text_width:
                continue
            # A single product name can itself be longer than the paper width.
            chunk = ''
            for char in current:
                candidate_chunk = chunk + char
                if chunk and probe.textbbox((0, 0), visual(candidate_chunk), font=font)[2] > max_text_width:
                    result.append(chunk)
                    chunk = char
                else:
                    chunk = candidate_chunk
            current = chunk
        if current or not result:
            result.append(current)
        return result

    if RECEIPT_RS in str(text or ''):
        image = _draw_structured_receipt(text, width, font, bold_font, big_font, scale, visual)
    else:
        lines = []
        for raw_line in str(text or '').splitlines():
            lines.extend(wrap(raw_line))
        # Derive line spacing from the actual font metrics. A fixed height is not
        # safe for Arabic marks, especially with the large font setting.
        sample_bbox = probe.textbbox((0, 0), visual('إيصال'), font=font)
        glyph_height = max(1, sample_bbox[3] - sample_bbox[1])
        line_height = max(scale + 8, glyph_height + 8)
        top_padding = 10
        bottom_padding = 10
        image = Image.new('L', (width, max(32, len(lines) * line_height + top_padding + bottom_padding)), 255)
        draw = ImageDraw.Draw(image)
        y = top_padding
        right_aligned = str(text_alignment or 'center') == 'right'
        for line in lines:
            shaped = visual(line)
            bbox = draw.textbbox((0, 0), shaped, font=font)
            line_width = bbox[2] - bbox[0]
            if right_aligned:
                # النص العربي RTL: "يمين" يعني إلصاق الحافة اليمنى بحافة الورق.
                x = max(6, width - line_width - 12)
            else:
                x = max(6, (width - line_width) // 2)
            # Compensate for fonts with a negative top bearing. Without this, the
            # first Arabic glyph row can be clipped and appear to touch the line
            # above it on some thermal printers.
            draw_y = y - bbox[1]
            draw.text((x, draw_y), shaped, fill=0, font=font)
            y += line_height
        image = image.crop((0, 0, width, max(y + bottom_padding, 32)))

    # Include the configured restaurant logo in the same raster job. This avoids
    # the old split path where the logo appeared in browser preview but was
    # silently omitted from thermal printing.
    if logo_data and isinstance(logo_data, str) and logo_data.startswith('data:image/') and ',' in logo_data:
        try:
            encoded = logo_data.split(',', 1)[1]
            logo_bytes = base64.b64decode(encoded, validate=True)
            logo = Image.open(BytesIO(logo_bytes)).convert('L')
            max_logo_width = width - 32
            is_square = logo.width > 0 and logo.height > 0 and abs(logo.width - logo.height) / max(logo.width, logo.height) <= 0.12
            if is_square:
                # الصور المربعة غالباً QR؛ تكبيرها يحسن القراءة، وNEAREST يحافظ
                # على حواف الوحدات السوداء بدلاً من تمويهها مثل شعارات الصور.
                max_logo_height = {'small': 120, 'medium': 180, 'large': 240}.get(str(logo_size or 'medium'), 180)
                resampling = Image.Resampling.NEAREST
            else:
                max_logo_height = {'small': 48, 'medium': 72, 'large': 104}.get(str(logo_size or 'medium'), 72)
                resampling = Image.Resampling.LANCZOS
            logo.thumbnail((max_logo_width, max_logo_height), resampling)
            if logo.width and logo.height:
                logo_canvas = Image.new('L', (width, logo.height + 16), 255)
                if logo_alignment == 'right':
                    logo_x = width - logo.width - 10
                elif logo_alignment == 'left':
                    logo_x = 10
                else:
                    logo_x = (width - logo.width) // 2
                logo_canvas.paste(logo, (max(0, logo_x), 8))
                combined = Image.new('L', (width, logo_canvas.height + image.height), 255)
                combined.paste(logo_canvas, (0, 0))
                combined.paste(image, (0, logo_canvas.height))
                image = combined
        except (ValueError, OSError, binascii.Error):
            # A damaged optional logo must never block printing the Arabic text.
            pass

    # Density is implemented at the raster threshold, which is safe across
    # old and new ESC/POS models because no vendor-specific head command is
    # required. Higher density marks lighter gray antialias pixels as black.
    try:
        density = max(30, min(100, int(print_density or 80)))
    except (TypeError, ValueError):
        density = 80
    threshold = 120 + int(density * 0.75)
    if str(print_quality or 'normal') == 'high':
        threshold += 6
    elif str(print_quality or 'normal') == 'draft':
        threshold -= 8
    if str(print_quality or 'normal') == 'high':
        # Ordered 4x4 dithering preserves thin Arabic strokes and logo detail
        # better than a single global threshold on low-resolution heads.
        matrix = ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))
        bitmap = Image.new('1', image.size, 1)
        source = image.load(); target = bitmap.load()
        for yy in range(image.height):
            for xx in range(image.width):
                local_threshold = threshold - 24 + matrix[yy % 4][xx % 4] * 3
                target[xx, yy] = 0 if source[xx, yy] < local_threshold else 1
    else:
        bitmap = image.point(lambda p: 0 if p < threshold else 255, mode='1')
    row_bytes = (width + 7) // 8
    data = bytearray()
    pixels = bitmap.load()
    for row in range(bitmap.height):
        for col_byte in range(row_bytes):
            value = 0
            for bit in range(8):
                col = col_byte * 8 + bit
                if col < width and pixels[col, row] == 0:
                    value |= 0x80 >> bit
            data.append(value)
    return escpos_raster_frames(row_bytes, bytes(data), bitmap.height) + b'\n\n\n\x1d\x56\x00'


def escpos_raster_frames(row_bytes, raster_bytes, height, max_frame_height=4096):
    """يبني ESC @ وإطارات GS v 0، مع حد أصغر من 16-bit للصور الطويلة."""
    row_bytes = int(row_bytes)
    height = int(height)
    if row_bytes <= 0 or height < 0 or len(raster_bytes) != row_bytes * height:
        raise ValueError('بيانات raster غير صالحة')
    max_frame_height = max(1, min(65535, int(max_frame_height)))
    frames = [b'\x1b\x40']
    for start in range(0, height, max_frame_height):
        frame_height = min(max_frame_height, height - start)
        header = bytes((0x1d, 0x76, 0x30, 0x00, row_bytes & 0xff, row_bytes >> 8,
                        frame_height & 0xff, frame_height >> 8))
        begin = start * row_bytes
        frames.extend((header, raster_bytes[begin:begin + frame_height * row_bytes]))
    return b''.join(frames)

def escpos_cut_bytes(printer=None):
    """يبني أمر القص من إعدادات الطابعة بدل افتراض أمر واحد لكل الموديلات."""
    printer = printer or {}
    try:
        feed_lines = max(0, min(10, int(printer.get('feed_before_cut', 3) or 0)))
    except (TypeError, ValueError):
        feed_lines = 3
    feed = b'\n' * feed_lines
    if not bool(printer.get('cut_enabled', True)):
        return feed
    cut_mode = str(printer.get('cut_mode', 'full') or 'full')
    cut_code = b'\x00' if cut_mode == 'full' else b'\x01'
    return feed + b'\x1d\x56' + cut_code

def render_escpos_raster_payload_for_printer(text, printer=None):
    """مسار الطباعة الرسمي: صورة عربية raster ثم قص مضبوط من إعدادات الطابعة."""
    printer = printer or {}
    # Roll-fed ESC/POS printers physically advance paper in portrait. Keep the
    # saved orientation available to the UI and non-roll drivers, but never
    # rotate a long receipt for RAW thermal output: that would clip or shrink
    # the receipt. The thermal-safe layout remains portrait for both modes.
    # Do not pad or rotate a roll receipt to a fixed page size. The raster
    # height is intentionally derived from the number of wrapped lines, so a
    # one-line order is short and a long order grows downward naturally.
    payload = render_escpos_raster_payload(
        text,
        printer.get('paper_width', 80),
        printer.get('font_size', 'medium'),
        printer.get('logo_data', ''),
        printer.get('logo_size', 'medium'),
        printer.get('logo_alignment', 'center'),
        printer.get('receipt_alignment', 'center'),
        printer.get('print_density', 80),
        printer.get('print_quality', 'normal'),
    )
    default_tail = b'\n\n\n\x1d\x56\x00'
    if payload.endswith(default_tail):
        return payload[:-len(default_tail)] + escpos_cut_bytes(printer)
    return payload + escpos_cut_bytes(printer)


def submit_network_raw_print(host, port, text, font_size='medium', paper_width=80, printer_config=None):
    """إرسال مباشر لطابعة حرارية ESC/POS عبر Wi‑Fi/LAN عند إدخال عنوانها، دون أي تعريف Windows."""
    try:
        host = str(host or '').strip()
        port = int(port or 9100)
        if not host or not (1 <= port <= 65535):
            return {'ok': False, 'status': 'not_configured', 'message': 'أدخل عنوان IP ومنفذًا صالحًا للطابعة'}
        config = dict(printer_config or {})
        config.update({'paper_width': paper_width, 'font_size': font_size})
        payload = render_escpos_raster_payload_for_printer(text, config)
        timeout = max(3, min(30, int(config.get('printer_timeout', 5) or 5)))
        retries = max(0, min(3, int(config.get('printer_retry_count', 1) or 0)))
        last_error = None
        offset = 0
        for attempt in range(retries + 1):
            try:
                with socket.create_connection((host, port), timeout=timeout) as conn:
                    while offset < len(payload):
                        sent = conn.send(payload[offset:])
                        if not sent:
                            raise OSError('لم تقبل الطابعة بيانات إضافية')
                        offset += sent
                return {'ok': True, 'status': 'submitted', 'message': f'تم إرسال الإيصال إلى الطابعة الشبكية {host}:{port}', 'job_id': uuid.uuid4().hex[:12], 'attempt': attempt + 1}
            except OSError as exc:
                last_error = exc
        raise last_error or OSError('فشل الاتصال بالطابعة')
    except (OSError, ValueError) as exc:
        return {'ok': False, 'status': 'failed', 'message': f'تعذر الاتصال بالطابعة الشبكية: {str(exc)[:160]}'}

def print_text_to_printer(printer_name, text):
    """مسار توافق قديم؛ يمر الآن عبر raster العربي ولا يرسل UTF-8 خامًا."""
    try:
        result = submit_silent_thermal_print(
            printer_name, text, 'medium', 80, 'CAESAR Arabic Receipt',
            {'cut_enabled': True, 'feed_before_cut': 3, 'cut_mode': 'full'},
        )
        return bool(result.get('ok'))
    except Exception:
        return False


def powershell_literal(value):
    """يحوّل القيمة إلى نص PowerShell آمن دون استخدام shell=True."""
    return "'" + str(value or '').replace("'", "''") + "'"


def submit_silent_windows_print(printer_name, text, document_name='CAESAR Receipt'):
    """مسار توافق قديم؛ يحوّل النص إلى صورة عربية ويرسله RAW إلى Windows."""
    if sys.platform != 'win32':
        return {'ok': False, 'status': 'unavailable', 'message': 'الطباعة الصامتة الفعلية متاحة عند تشغيل النظام على Windows'}
    return submit_silent_thermal_print(
        printer_name, text, 'medium', 80, document_name,
        {'cut_enabled': True, 'feed_before_cut': 3, 'cut_mode': 'full'},
    )


def submit_silent_thermal_print(printer_name, text, font_size='medium', paper_width=80, document_name='CAESAR Receipt', printer_config=None):
    """يرسل إيصال ESC/POS خامًا إلى Windows حتى يعمل تكبير الخط فعليًا."""
    return submit_raw_windows_bytes(
        printer_name, render_escpos_raster_payload_for_printer(text, {**(printer_config or {}), 'paper_width': paper_width, 'font_size': font_size}), document_name
    )


def submit_raw_windows_bytes(printer_name, payload, document_name='CAESAR Raw Command'):
    """يرسل بايتات ESC/POS مباشرة إلى Windows Spooler بدون تحويلها إلى نص."""
    if sys.platform != 'win32':
        return {'ok': False, 'status': 'unavailable', 'message': 'الأوامر الخام للطابعة متاحة عند التشغيل على Windows'}
    printer_name = str(printer_name or '').strip()
    if not printer_name or not payload:
        return {'ok': False, 'status': 'not_configured', 'message': 'لم تُحدد طابعة لإرسال أمر القص'}
    try:
        import ctypes
        from ctypes import wintypes

        class DOC_INFO_1W(ctypes.Structure):
            _fields_ = [('pDocName', wintypes.LPCWSTR), ('pOutputFile', wintypes.LPCWSTR), ('pDatatype', wintypes.LPCWSTR)]

        winspool = ctypes.WinDLL('winspool.drv')
        handle = wintypes.HANDLE()
        winspool.OpenPrinterW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.HANDLE), ctypes.c_void_p]
        winspool.OpenPrinterW.restype = wintypes.BOOL
        if not winspool.OpenPrinterW(printer_name, ctypes.byref(handle), None):
            raise OSError('تعذر الاتصال بالطابعة المحددة')
        try:
            doc = DOC_INFO_1W(str(document_name)[:80], None, 'RAW')
            winspool.StartDocPrinterW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p]
            winspool.StartDocPrinterW.restype = wintypes.DWORD
            if not winspool.StartDocPrinterW(handle, 1, ctypes.byref(doc)):
                raise OSError('تعذر بدء أمر الطباعة الخام')
            try:
                if not winspool.StartPagePrinter(handle):
                    raise OSError('تعذر بدء صفحة أمر القص')
                try:
                    raw = bytes(payload)
                    buffer = ctypes.create_string_buffer(raw)
                    written = wintypes.DWORD(0)
                    if not winspool.WritePrinter(handle, buffer, len(raw), ctypes.byref(written)) or written.value != len(raw):
                        raise OSError('لم تستقبل الطابعة أمر القص كاملًا')
                finally:
                    winspool.EndPagePrinter(handle)
            finally:
                winspool.EndDocPrinter(handle)
        finally:
            winspool.ClosePrinter(handle)
        return {'ok': True, 'status': 'submitted', 'message': 'تم إرسال أمر قص الورق إلى الطابعة', 'job_id': uuid.uuid4().hex[:12]}
    except Exception as exc:
        return {'ok': False, 'status': 'failed', 'message': str(exc)[:220] or 'تعذر إرسال أمر قص الورق'}


def cut_paper_to_printer(printer):
    """يقص الرول بعد إغلاق الوردية عبر ESC/POS، دون فتح نافذة أو حوار طباعة."""
    printer = printer or {}
    if printer.get('connection_mode') == 'network':
        host = str(printer.get('network_host') or '').strip()
        try:
            port = int(printer.get('network_port', 9100) or 9100)
        except (TypeError, ValueError):
            port = 9100
        if not host or not (1 <= port <= 65535):
            return {'ok': False, 'status': 'not_configured', 'message': 'لم تُضبط طابعة شبكة لقص الورق'}
        try:
            with socket.create_connection((host, port), timeout=5) as conn:
                conn.sendall(b'\x1b\x40' + escpos_cut_bytes(printer))
            return {'ok': True, 'status': 'submitted', 'message': f'تم إرسال أمر قص الورق إلى {host}:{port}', 'job_id': uuid.uuid4().hex[:12]}
        except OSError as exc:
            return {'ok': False, 'status': 'failed', 'message': f'تعذر الاتصال بطابعة الشبكة لقص الورق: {str(exc)[:160]}'}
    return submit_raw_windows_bytes(
        printer.get('printer_name', ''), b'\x1b\x40' + escpos_cut_bytes(printer), 'CAESAR Shift Paper Cut'
    )


CASH_DRAWER_PULSE_PROFILES = {
    'pin2_standard': (b'\x1b\x70\x00\x19\xfa', 'المخرج 1 — قياسي'),
    'pin2_short': (b'\x1b\x70\x00\x19\x64', 'المخرج 1 — نبضة قصيرة'),
    'pin5_standard': (b'\x1b\x70\x01\x19\xfa', 'المخرج 2 — قياسي'),
    'pin5_short': (b'\x1b\x70\x01\x19\x64', 'المخرج 2 — نبضة قصيرة'),
}


def open_cash_drawer_via_printer(printer_name, pulse_profile='pin2_standard'):
    """يرسل نبضة ESC/POS لدرج موصول بمنفذ RJ11 في طابعة متوافقة على Windows فقط."""
    if sys.platform != 'win32':
        return False, 'فتح الدرج الفعلي متاح عند تشغيل الكاشير قيصر على Windows فقط'
    try:
        import ctypes
        from ctypes import wintypes

        class DOC_INFO_1W(ctypes.Structure):
            _fields_ = [('pDocName', wintypes.LPCWSTR), ('pOutputFile', wintypes.LPCWSTR), ('pDatatype', wintypes.LPCWSTR)]

        winspool = ctypes.WinDLL('winspool.drv')
        handle = wintypes.HANDLE()
        winspool.OpenPrinterW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.HANDLE), ctypes.c_void_p]
        winspool.OpenPrinterW.restype = wintypes.BOOL
        if not winspool.OpenPrinterW(str(printer_name), ctypes.byref(handle), None):
            raise OSError('تعذر الاتصال بالطابعة المحددة')
        try:
            doc = DOC_INFO_1W('CAESAR AlCAESAR Cash Drawer', None, 'RAW')
            winspool.StartDocPrinterW.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p]
            winspool.StartDocPrinterW.restype = wintypes.DWORD
            if not winspool.StartDocPrinterW(handle, 1, ctypes.byref(doc)):
                raise OSError('تعذر بدء مهمة فتح الدرج')
            try:
                if not winspool.StartPagePrinter(handle):
                    raise OSError('تعذر بدء أمر فتح الدرج')
                try:
                    pulse_bytes = CASH_DRAWER_PULSE_PROFILES.get(pulse_profile, CASH_DRAWER_PULSE_PROFILES['pin2_standard'])[0]
                    pulse = ctypes.create_string_buffer(pulse_bytes)
                    written = wintypes.DWORD(0)
                    if not winspool.WritePrinter(handle, pulse, len(pulse_bytes), ctypes.byref(written)) or written.value != len(pulse_bytes):
                        raise OSError('لم تستقبل الطابعة نبضة فتح الدرج')
                finally:
                    winspool.EndPagePrinter(handle)
            finally:
                winspool.EndDocPrinter(handle)
        finally:
            winspool.ClosePrinter(handle)
        return True, 'تم إرسال نبضة فتح الدرج للطابعة'
    except Exception as exc:
        return False, str(exc)[:160] or 'تعذر إرسال نبضة فتح الدرج'


def record_cash_drawer_attempt(data, username, reason, source='manual'):
    """ينفذ ويسجل محاولة فتح الدرج، وتستخدمه إجراءات الفتح اليدوي والتلقائي."""
    printer = data.get('settings', {}).get('printer', {})
    drawer_printer = str(printer.get('cash_drawer_printer') or printer.get('printer_name') or '').strip()
    pulse_profile = str(printer.get('cash_drawer_pulse_profile', 'pin2_standard') or 'pin2_standard')
    log = {'id': uuid.uuid4().hex[:12], 'timestamp': datetime.now().isoformat(), 'username': username or 'unknown', 'printer': drawer_printer, 'reason': reason or 'فتح درج النقد', 'source': source, 'pulse_profile': pulse_profile, 'status': 'skipped', 'message': ''}
    if not printer.get('cash_drawer_enabled'):
        log.update({'status': 'disabled', 'message': 'فتح درج النقد غير مفعّل من الإعدادات'})
    elif not drawer_printer:
        log.update({'status': 'skipped', 'message': 'لم تُحدد طابعة متوافقة لدرج النقد'})
    else:
        opened, message = open_cash_drawer_via_printer(drawer_printer, pulse_profile)
        log.update({'status': 'sent' if opened else ('skipped' if sys.platform != 'win32' else 'failed'), 'message': message})
    data.setdefault('cash_drawer_log', []).append(log)
    data['cash_drawer_log'] = data['cash_drawer_log'][-200:]
    return log


def maybe_auto_open_cash_drawer(data, order, cash_amount):
    """يفتح الدرج تلقائيًا فقط عندما توجد دفعة نقدية فعلية والخيار مفعّل."""
    printer = data.get('settings', {}).get('printer', {})
    if not printer.get('auto_open_cash_drawer') or float(cash_amount or 0) <= 0:
        return None
    return record_cash_drawer_attempt(data, order.get('cashier_name', session.get('username', 'unknown')), f"فتح تلقائي بعد دفع نقدي للفاتورة {order.get('id', '')}", 'auto_payment')

RECEIPT_LAYOUT_DEFAULT = ('logo', 'header', 'details', 'items', 'totals', 'footer')


def is_valid_receipt_layout(value):
    return isinstance(value, list) and len(value) == len(RECEIPT_LAYOUT_DEFAULT) and set(value) == set(RECEIPT_LAYOUT_DEFAULT) and len(set(value)) == len(value)


def normalize_receipt_layout(value):
    return list(value) if is_valid_receipt_layout(value) else list(RECEIPT_LAYOUT_DEFAULT)


def thermal_receipt_text(data, order, ticket_type='receipt'):
    """ينشئ نصًا بسيطًا للطابعات الحرارية، ويضمن بقاء البيع ناجحًا إن فشلت الطابعة."""
    settings = data.get('settings', {})
    restaurant = settings.get('restaurant', {})
    printer = settings.get('printer', {})
    restaurant_name = restaurant.get('name') or 'كاشير قيصر قيصر'
    caption = str(printer.get('logo_caption', '') or '').strip()
    text_columns = {58: 32, 80: 42, 112: 60}
    try:
        configured_width = int(printer.get('paper_width', 80) or 80)
    except (TypeError, ValueError):
        configured_width = 80
    width = text_columns.get(configured_width, 42)
    divider_char = {'line': '-', 'double': '=', 'dots': '.'}.get(printer.get('receipt_divider', 'line'), '-')
    divider = divider_char * width
    align_center = printer.get('receipt_alignment', 'center') == 'center'
    density = printer.get('receipt_density', 'standard')
    gap = '' if density == 'compact' else ('\n\n' if density == 'spacious' else '\n')

    def format_line(value):
        text = str(value or '')
        return text.center(width) if align_center else text

    def receipt_amount(value):
        try:
            number = float(value or 0)
        except (TypeError, ValueError):
            number = 0
        return f'{number:,.2f}'.rstrip('0').rstrip('.')

    def receipt_item_line(item):
        name = str(item.get('name', '') or '')
        try:
            quantity = float(item.get('quantity', item.get('qty', 1)) or 0)
        except (TypeError, ValueError):
            quantity = 0
        quantity_text = str(int(quantity)) if quantity.is_integer() else receipt_amount(quantity)
        unit_price = item.get('price', item.get('unit_price', 0)) or 0
        line_total = float(unit_price or 0) * quantity
        return f'{name} × {quantity_text} | سعر: {receipt_amount(unit_price)} | الإجمالي: {receipt_amount(line_total)}'

    if ticket_type == 'kitchen':
        lines = [format_line(restaurant_name), divider, format_line('طلب مطبخ'), f"الطلب: {order.get('id', '')}", f"النوع: {order.get('type', 'سفري')}"]
        if order.get('table'):
            lines.append('الطاولة: ' + str(order.get('table')))
        if order.get('customer'):
            lines.append('الزبون: ' + str(order.get('customer')))
        lines.append(divider)
        for item in order.get('items', []):
            lines.append(f"{item.get('name', '')} × {item.get('quantity', item.get('qty', 1))}")
            modifiers = item.get('modifiers', []) if isinstance(item, dict) else []
            names = [str(row.get('name', '') if isinstance(row, dict) else row).strip() for row in modifiers]
            names = [name for name in names if name]
            if names:
                lines.append('إضافات: ' + '، '.join(names))
        if order.get('note'):
            lines.extend([divider, 'ملاحظة: ' + str(order.get('note'))])
    else:
        header = str(printer.get('receipt_header', 'إيصال مبيعات') or 'إيصال مبيعات')[:36]
        restaurant_phone = str(restaurant.get('phone', '') or '').strip()
        restaurant_address = str(restaurant.get('address', '') or '').strip()
        header_lines = [format_line(restaurant_name)] + ([format_line(caption)] if caption else [])
        if restaurant_address:
            header_lines.append(format_line(restaurant_address[:width]))
        if restaurant_phone:
            header_lines.append(format_line('هاتف: ' + restaurant_phone[:width - 6]))
        header_lines.extend([divider, format_line(header)])
        raw_date = str(order.get('timestamp') or order.get('date', ''))[:19]
        # Keep technical LTR values isolated from Arabic RTL labels.
        safe_date = raw_date.replace('T', ' ')
        isolated_date = '\u200e' + safe_date + '\u200e' if safe_date else ''
        detail_lines = [f"رقم الفاتورة: {order.get('id', '')}", f"التاريخ: {isolated_date}"]
        if order.get('customer'):
            detail_lines.append('الزبون: ' + str(order.get('customer'))[:width - 8])
        if order.get('table') or order.get('table_no'):
            detail_lines.append('الطاولة: ' + str(order.get('table') or order.get('table_no')))
        if printer.get('receipt_show_order_type', True):
            detail_lines.append('نوع الطلب: ' + str(order.get('type', 'سفري')))
        detail_lines.append(divider)

        def display_amount(value):
            currency = str(order.get('currency') or settings.get('currency', 'SYP'))
            rate = order.get('exchange_rate') or settings.get('usd_rate' if currency == 'USD' else 'eur_rate', 0)
            try:
                amount = float(value or 0)
                if currency in {'USD', 'EUR'} and float(rate or 0) > 0:
                    amount /= float(rate)
            except (TypeError, ValueError):
                amount = 0
            symbol = {'SYP': 'ل.س', 'USD': '$', 'EUR': '€'}.get(currency, 'ل.س')
            return receipt_amount(amount) + ' ' + symbol

        def table_line(name, quantity, unit_price, line_total):
            name_width = max(12, width - 25)
            compact_name = str(name or '').replace('\n', ' ')[:name_width]
            unit = '\u200e' + display_amount(unit_price) + '\u200e'
            total = '\u200e' + display_amount(line_total) + '\u200e'
            return f'{compact_name:<{name_width}} {str(quantity):>5} {unit:>9} {total:>10}'

        name_width = max(12, width - 25)
        item_lines = [f"{'الصنف':<{name_width}} {'الكمية':>5} {'السعر':>9} {'القيمة':>10}", divider]
        item_count = 0
        quantity_total = 0.0
        for item in order.get('items', []):
            try:
                quantity = float(item.get('quantity', item.get('qty', 1)) or 0)
            except (TypeError, ValueError):
                quantity = 0
            item_count += 1
            quantity_total += quantity
            unit_price = item.get('price', item.get('unit_price', 0)) or 0
            quantity_text = str(int(quantity)) if quantity.is_integer() else receipt_amount(quantity)
            item_lines.append(table_line(item.get('name', ''), quantity_text, unit_price, float(unit_price or 0) * quantity))
        item_lines.extend([divider, f'عدد البنود: {item_count}    مجموع الكمية: {receipt_amount(quantity_total)}'])

        subtotal = order.get('subtotal', order.get('total', 0)) or 0
        discount = order.get('discount_total', 0) or 0
        total = order.get('total', 0) or 0
        cash = order.get('cash_amount', total if order.get('payment') != 'بطاقة' else 0) or 0
        card = order.get('card_amount', total if order.get('payment') == 'بطاقة' else 0) or 0
        total_lines = [divider, 'المجموع الفرعي: ' + display_amount(subtotal)]
        if float(discount or 0) > 0:
            total_lines.append('الخصم: -' + display_amount(discount))
        total_lines.extend(['الإجمالي: ' + display_amount(total), 'طريقة الدفع: ' + str(order.get('payment', ''))])
        if str(order.get('payment', '')) == 'مختلط':
            total_lines.extend(['النقدي: ' + display_amount(cash), 'البطاقة: ' + display_amount(card)])
        footer_lines = []
        if printer.get('receipt_show_cashier', True) and order.get('cashier_name'):
            footer_lines.append('الكاشير: ' + str(order.get('cashier_name')))
        tax_number = str(restaurant.get('tax_number', '') or '').strip()
        if tax_number:
            footer_lines.append('الرقم الضريبي: ' + tax_number)
        social_lines = []
        for label, key in [('Facebook', 'social_facebook'), ('Instagram', 'social_instagram'), ('WhatsApp', 'social_whatsapp')]:
            value = str(printer.get(key, '') or '').strip()
            if value:
                social_lines.append(f'{label}: {value}')
        footer_lines.extend([divider, str(printer.get('footer_text', '') or '')] + social_lines + [gap + '\n\n'])
        blocks = {'logo': [], 'header': header_lines, 'details': detail_lines, 'items': item_lines, 'totals': total_lines, 'footer': footer_lines}
        lines = []
        for block_id in normalize_receipt_layout(printer.get('receipt_layout')):
            lines.extend(blocks[block_id])
    return gap.join(line for line in lines if line is not None)


def thermal_receipt_structured(data, order):
    """إيصال مبيعات مقسّم (ترويسة، صندوق بيانات، جدول أصناف، مجاميع، تذييل) للرسم الحراري.

    يعيد نصاً فيه أوامر تنسيق يفهمها _draw_structured_receipt. النسخة النصية البسيطة
    تبقى في thermal_receipt_text للمطبخ وللمعاينة والاختبارات.
    """
    settings = data.get('settings', {})
    restaurant = settings.get('restaurant', {})
    printer = settings.get('printer', {})
    RS, US = RECEIPT_RS, RECEIPT_US
    try:
        narrow = int(printer.get('paper_width', 80) or 80) <= 58
    except (TypeError, ValueError):
        narrow = False
    # نعطي الكمية والسعر والقيمة عرضاً ثابتاً كافياً للأرقام، ونمنع
    # تداخلها مع خط الفصل عند الطباعة الطولية، خصوصاً على رول 58mm.
    cols = '28,16,28,28' if narrow else '40,17,22,21'

    def cmd(*parts):
        return RS + US.join(str(part).replace('\n', ' ').replace(RS, '').replace(US, '') for part in parts)

    currency = str(order.get('currency') or settings.get('currency', 'SYP'))
    rate = order.get('exchange_rate') or settings.get('usd_rate' if currency == 'USD' else 'eur_rate', 0)
    symbol = {'SYP': 'ل.س', 'USD': '$', 'EUR': '€'}.get(currency, 'ل.س')

    def money_text(value, with_symbol=False):
        try:
            amount = float(value or 0)
            if currency in {'USD', 'EUR'} and float(rate or 0) > 0:
                amount /= float(rate)
        except (TypeError, ValueError):
            amount = 0
        converted = currency in {'USD', 'EUR'} and float(rate or 0) > 0
        text = f'{amount:,.2f}' if converted else f'{amount:,.2f}'.rstrip('0').rstrip('.')
        if with_symbol:
            text += ' ' + (symbol if converted else 'ل.س')
        return '‎' + text + '‎'

    def number_text(value):
        try:
            number = float(value or 0)
        except (TypeError, ValueError):
            number = 0
        return str(int(number)) if number.is_integer() else f'{number:,.2f}'.rstrip('0').rstrip('.')

    restaurant_name = restaurant.get('name') or 'كاشير قيصر'
    lines = [cmd('C', restaurant_name, 1, 1)]
    caption = str(printer.get('logo_caption', '') or '').strip()
    if caption:
        lines.append(cmd('C', caption))
    address = str(restaurant.get('address', '') or '').strip()
    if address:
        lines.append(cmd('C', address))
    phone = str(restaurant.get('phone', '') or '').strip()
    if phone:
        lines.append(cmd('C', 'هاتف: ' + phone))
    header = str(printer.get('receipt_header', 'إيصال مبيعات') or '').strip()
    if header:
        lines.append(cmd('C', header, 1))
    if order.get('is_reprint'):
        lines.append(cmd('C', 'نسخة', 1))
    lines.append(cmd('GAP', 6))

    stamp = str(order.get('timestamp') or order.get('date', ''))[:19].replace('T', ' ')
    date_part, _, time_part = stamp.partition(' ')
    lines.append(cmd('BOX'))
    lines.append(cmd('ROW', 1, '100', 'r', 1, 'رقم الفاتورة: ' + str(order.get('id', ''))))
    lines.append(cmd('ROW', 1, '100', 'r', 0, 'التاريخ: ‎' + date_part + '‎'))
    info = []
    if order.get('customer'):
        info.append('اسم الزبون: ' + str(order.get('customer'))[:60])
    if order.get('table') or order.get('table_no'):
        info.append('الطاولة: ' + str(order.get('table') or order.get('table_no')))
    if printer.get('receipt_show_order_type', True):
        info.append('نوع الطلب: ' + str(order.get('type', 'سفري')))
    for entry in info:
        lines.append(cmd('ROW', 1, '100', 'r', 0, entry))
    lines.append(cmd('ENDBOX'))

    lines.append(cmd('BOX'))
    lines.append(cmd('ROW', 1, cols, 'r,c,c,c', 1, 'الصنف', 'الكمية', 'السعر', 'القيمة'))
    item_count, quantity_total = 0, 0.0
    for item in order.get('items', []):
        try:
            quantity = float(item.get('quantity', item.get('qty', 1)) or 0)
        except (TypeError, ValueError):
            quantity = 0
        unit_price = item.get('price', item.get('unit_price', 0)) or 0
        try:
            line_total = float(unit_price or 0) * quantity
        except (TypeError, ValueError):
            line_total = 0
        item_count += 1
        quantity_total += quantity
        name = str(item.get('name', '') or '')
        mods = [str(m.get('name', '')) for m in item.get('modifiers', []) if isinstance(m, dict) and m.get('name')]
        if mods:
            name += ' (' + '، '.join(mods) + ')'
        # اجعل كل صنف صفاً شبكياً كاملاً: الفاصل يرسم الحدود العمودية بين
        # الأعمدة والخط الأفقي أسفل الصف، مثل فاتورة الجدول المطبوعة.
        # استخدم فاصلًا مستمرًا بين الصفوف؛ الفاصل المنقّط (2) يترك فراغات
        # واضحة على الطابعة الحرارية ويجعل مربعات الجدول تبدو منفصلة.
        lines.append(cmd('ROW', 1, cols, 'r,c,c,c', 1, name, number_text(quantity),
                         money_text(unit_price), money_text(line_total)))
    # يبقى صف الملخص داخل الشبكة نفسها حتى تستمر الخطوط العمودية في جدول
    # الأصناف من رأس الأعمدة إلى آخر صف دون انقطاع أو تغيير في مواقعها.
    lines.append(cmd('ROW', 1, cols, 'r,c,r,c', 1, 'البنود', str(item_count), 'الكمية', number_text(quantity_total)))
    lines.append(cmd('ENDBOX'))

    subtotal = order.get('subtotal', order.get('total', 0)) or 0
    discount = order.get('discount_total', 0) or 0
    total = order.get('total', 0) or 0
    lines.append(cmd('BOX'))
    lines.append(cmd('ROW', 1, '55,45', 'r,l', 0, 'المجموع الفرعي', money_text(subtotal, True)))
    try:
        has_discount = float(discount) > 0
    except (TypeError, ValueError):
        has_discount = False
    if has_discount:
        lines.append(cmd('ROW', 1, '55,45', 'r,l', 0, 'الخصم', '-' + money_text(discount, True)))
    lines.append(cmd('RULE'))
    lines.append(cmd('ROW', 1, '55,45', 'r,l', 1, 'الإجمالي', money_text(total, True)))
    lines.append(cmd('ROW', 1, '55,45', 'r,l', 0, 'طريقة الدفع', str(order.get('payment', ''))))
    if str(order.get('payment', '')) == 'مختلط':
        cash = order.get('cash_amount', 0) or 0
        card = order.get('card_amount', 0) or 0
        lines.append(cmd('ROW', 1, '55,45', 'r,l', 0, 'النقدي', money_text(cash, True)))
        lines.append(cmd('ROW', 1, '55,45', 'r,l', 0, 'البطاقة', money_text(card, True)))
    lines.append(cmd('ENDBOX'))

    footer = []
    tax_number = str(restaurant.get('tax_number', '') or '').strip()
    if tax_number:
        footer.append('الرقم الضريبي: ' + tax_number)
    footer_text = str(printer.get('footer_text', '') or '').strip()
    if footer_text:
        footer.append(footer_text)
    for label, key in [('Facebook', 'social_facebook'), ('Instagram', 'social_instagram'), ('WhatsApp', 'social_whatsapp')]:
        value = str(printer.get(key, '') or '').strip()
        if value:
            footer.append(f'{label}: {value}')
    if footer:
        lines.append(cmd('BOX'))
        for entry in footer:
            lines.append(cmd('ROW', 0, '100', 'r', 0, entry))
        lines.append(cmd('ENDBOX'))
        lines.append(cmd('GAP', 6))
    cashier = str(order.get('cashier_name', '') or '') if printer.get('receipt_show_cashier', True) else ''
    time_label = '‎' + time_part[:5] + '‎' if time_part else ''
    lines.append(cmd('ROW', 0, '60,40', 'r,l', 0, ('الكاشير: ' + cashier) if cashier else '', time_label))
    lines.append('')
    return '\n'.join(lines)


PRINT_QUEUE = queue.Queue(maxsize=1000)


def _dispatch_print_job(job):
    data, order, ticket_type, log_id = job
    printer = dict(data.get('settings', {}).get('printer', {}) or {})
    if ticket_type == 'kitchen':
        # تذكرة العمل الداخلية لا تحمل أي صورة شعار/QR ولا تتكرر لنسخ العميل.
        printer['logo_data'] = ''
        printer['logo_caption'] = ''
    printer_name = str(printer.get('printer_name') or '').strip()
    font_size = str(printer.get('font_size', 'medium') or 'medium')
    # فاتورة البيع الرئيسية تستخدم القالب الشبكي دائماً. هذا يمنع إعداد
    # receipt_style=plain القديم من إعادة الإيصال إلى أسطر نصية بلا مربعات؛
    # تذكرة المطبخ تبقى على القالب النصي المعتاد.
    if ticket_type == 'receipt':
        document_text = thermal_receipt_structured(data, order)
    else:
        document_text = thermal_receipt_text(data, order, ticket_type)
    try:
        copies = max(1, min(3, int(printer.get('copies', 1) or 1)))
    except (TypeError, ValueError):
        copies = 1
    if ticket_type == 'kitchen':
        copies = 1
    result = None
    for copy_number in range(copies):
        if printer.get('connection_mode') == 'network':
            result = submit_network_raw_print(printer.get('network_host'), printer.get('network_port', 9100), document_text, font_size, printer.get('paper_width', 80), printer)
        else:
            result = submit_silent_thermal_print(
                printer_name, document_text, font_size, printer.get('paper_width', 80),
                f"CAESAR {'Kitchen' if ticket_type == 'kitchen' else 'Receipt'} {order.get('id', '')} ({copy_number + 1}/{copies})", printer
            )
        if not result.get('ok'):
            result['copies_sent'] = copy_number
            result['copies_requested'] = copies
            return result
    result['copies_sent'] = copies
    result['copies_requested'] = copies
    return result


def _print_worker():
    while True:
        job = PRINT_QUEUE.get()
        try:
            data, order, ticket_type, log_id = job
            result = _dispatch_print_job(job)
            # load() وsave() محميتان كل واحدة على حدة، لكن العامل يحتاج
            # القفل نفسه طوال دورة القراءة والتعديل والحفظ حتى لا يكتب فوق
            # فاتورة أو حركة نقدية حفظها طلب HTTP بالتزامن.
            with DATA_LOCK:
                latest = load()
                row = next((item for item in latest.get('print_log', []) if item.get('id') == log_id), None)
                if row:
                    row.update({'status': result.get('status', 'failed'),
                                'message': result.get('message', 'تعذر إرسال أمر الطباعة'),
                                'job_id': result.get('job_id', ''),
                                'document_name': result.get('document_name', '')})
                    save(latest)
        except Exception as exc:
            error_logger.error('خطأ في عامل الطباعة: %s', exc, exc_info=True)
            try:
                with DATA_LOCK:
                    latest = load()
                    row = next((item for item in latest.get('print_log', []) if item.get('id') == log_id), None)
                    if row:
                        row.update({'status': 'failed', 'message': str(exc)[:220] or 'تعذر إرسال أمر الطباعة'})
                        save(latest)
            except Exception:
                error_logger.error('تعذر تثبيت فشل مهمة الطباعة %s', log_id, exc_info=True)
        finally:
            PRINT_QUEUE.task_done()


threading.Thread(target=_print_worker, name='caesar-print-worker', daemon=True).start()


def queue_thermal_print(data, order, ticket_type='receipt', wait=False):
    """يسجل أمر الطباعة ويضعه في queue؛ لا ينتظر الطابعة ولا يؤخر حفظ الفاتورة."""
    printer = data.get('settings', {}).get('printer', {})
    enabled = bool(printer.get('auto_print_receipt')) if ticket_type == 'receipt' else bool(printer.get('auto_print_kitchen'))
    if not enabled:
        return {'queued': False, 'status': 'disabled', 'type': ticket_type, 'message': 'الطباعة التلقائية غير مفعلة'}
    printer_name = str(printer.get('printer_name') or '').strip()
    is_network = printer.get('connection_mode') == 'network'
    printer_target = (str(printer.get('network_host') or '').strip() + ':' + str(printer.get('network_port', 9100))) if is_network else printer_name
    log = {'id': uuid.uuid4().hex[:12], 'timestamp': datetime.now().isoformat(), 'order_id': order.get('id', ''), 'type': ticket_type, 'printer': printer_target, 'status': 'skipped', 'message': '', 'resolved': False}
    if is_network and (not str(printer.get('network_host') or '').strip()):
        log.update({'status': 'skipped', 'message': 'لم يُحدد عنوان طابعة الشبكة'})
    elif not is_network and sys.platform != 'win32':
        log.update({'status': 'skipped', 'message': 'الطباعة التلقائية الفعلية متاحة على Windows فقط'})
    elif not is_network and not printer_name:
        log.update({'status': 'skipped', 'message': 'لم تُحدد طابعة حرارية'})
    else:
        try:
            if wait:
                dispatched = _dispatch_print_job((dict(data), dict(order), ticket_type, log['id']))
                log.update({'status': dispatched.get('status', 'failed'),
                            'message': dispatched.get('message', 'تعذر إرسال أمر الطباعة'),
                            'job_id': dispatched.get('job_id', ''),
                            'document_name': dispatched.get('document_name', '')})
            else:
                PRINT_QUEUE.put_nowait((dict(data), dict(order), ticket_type, log['id']))
                log.update({'status': 'queued', 'message': 'تم حفظ الفاتورة ووضع الطباعة في الطابور'})
        except queue.Full:
            log.update({'status': 'failed', 'message': 'طابور الطباعة ممتلئ؛ أعد المحاولة لاحقًا'})
        except Exception as exc:
            # الطباعة خدمة جانبية: لا يجوز أن تفشل عملية البيع بسبب خطأ
            # مفاجئ في تعريف الطابعة أو في مولد صورة الإيصال. سجّل الخطأ
            # ليظهر في سجل الطباعة وتبقى الفاتورة قابلة لإعادة المحاولة.
            error_logger.error('فشل إرسال تذكرة %s للطلب %s', ticket_type, order.get('id', ''), exc_info=True)
            log.update({'status': 'failed', 'message': str(exc)[:220] or 'تعذر إرسال أمر الطباعة'})
    data.setdefault('print_log', []).append(log)
    data['print_log'] = data['print_log'][-200:]
    return log


def unresolved_print_failures(data):
    """يعيد محاولات الإرسال الفاشلة التي لم يحلها إرسال ناجح لاحقًا."""
    return [row for row in data.get('print_log', []) if row.get('status') in {'failed', 'timed_out'} and not row.get('resolved', False)]


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
    if not has_role('manager'):
        return permission_error()
    data = load()
    p = data.get('settings', {}).get('printer', {})
    return jsonify({
        "paper_width": p.get('paper_width', 80),
        "paper_orientation": p.get('paper_orientation', 'portrait'),
        "receipt_length_mode": 'auto',
        "font_size": p.get('font_size', 'medium'),
        "copies": p.get('copies', 1),
        "footer_text": p.get('footer_text', ''),
        "printer_name": p.get('printer_name', ''),
        "connection_mode": p.get('connection_mode', 'windows'),
        "printer_transport": p.get('printer_transport', 'auto'),
        "printer_family": p.get('printer_family', 'auto'),
        "print_density": p.get('print_density', 80),
        "print_quality": p.get('print_quality', 'normal'),
        "print_speed": p.get('print_speed', 'normal'),
        "printer_timeout": p.get('printer_timeout', 5),
        "printer_retry_count": p.get('printer_retry_count', 1),
        "network_host": p.get('network_host', ''),
        "network_port": p.get('network_port', 9100),
        "cut_enabled": bool(p.get('cut_enabled', True)),
        "cut_mode": p.get('cut_mode', 'full'),
        "feed_before_cut": p.get('feed_before_cut', 3),
        "auto_print_receipt": bool(p.get('auto_print_receipt', False)),
        "auto_print_kitchen": bool(p.get('auto_print_kitchen', False)),
        "cash_drawer_enabled": bool(p.get('cash_drawer_enabled', False)),
        "auto_open_cash_drawer": bool(p.get('auto_open_cash_drawer', False)),
        "cash_drawer_printer": p.get('cash_drawer_printer', p.get('printer_name', '')),
        "cash_drawer_pulse_profile": p.get('cash_drawer_pulse_profile', 'pin2_standard'),
        "logo_data": p.get('logo_data', ''),
        "logo_caption": p.get('logo_caption', ''),
        "receipt_header": p.get('receipt_header', 'إيصال مبيعات'),
        "receipt_alignment": p.get('receipt_alignment', 'center'),
        "receipt_divider": p.get('receipt_divider', 'line'),
        "receipt_density": p.get('receipt_density', 'standard'),
        "receipt_show_cashier": bool(p.get('receipt_show_cashier', True)),
        "receipt_show_order_type": bool(p.get('receipt_show_order_type', True)),
        "logo_size": p.get('logo_size', 'medium'),
        "logo_alignment": p.get('logo_alignment', 'center'),
        "social_facebook": p.get('social_facebook', ''),
        "social_instagram": p.get('social_instagram', ''),
        "social_whatsapp": p.get('social_whatsapp', ''),
        "receipt_layout": normalize_receipt_layout(p.get('receipt_layout')),
        "receipt_font_family": p.get('receipt_font_family', 'system'),
        "receipt_font_scale": p.get('receipt_font_scale', p.get('font_size', 'medium'))
    })

@app.route('/api/printer/preview', methods=['POST'])
def printer_preview():
    """يعيد صورة البكسلات نفسها التي ستُرسل إلى ESC/POS، بدون لمس الطابعة."""
    if not has_role('manager'):
        return permission_error()
    payload = request.get_json(silent=True) or {}
    printer = dict(payload.get('printer') or {})
    try:
        printer['paper_width'] = int(printer.get('paper_width', 80) or 80)
    except (TypeError, ValueError):
        printer['paper_width'] = 80
    if printer['paper_width'] not in {58, 80, 112}:
        return jsonify({'ok': False, 'error': 'عرض ورق غير صالح للمعاينة'}), 400
    printer['font_size'] = str(printer.get('font_size', 'medium') or 'medium')
    printer['logo_data'] = str(printer.get('logo_data', '') or '')
    printer['print_density'] = printer.get('print_density', 80)
    printer['print_quality'] = printer.get('print_quality', 'normal')
    restaurant = dict(load().get('settings', {}).get('restaurant', {}) or {})
    if isinstance(payload.get('restaurant'), dict):
        restaurant.update(payload['restaurant'])
    data = {'settings': {'restaurant': restaurant, 'currency': 'SYP', 'printer': printer}}
    order = {
        'id': 'ORD-0001', 'timestamp': '2026-10-29T20:00:00', 'customer': 'زبون تجريبي',
        'type': 'سفري', 'payment': 'نقدي', 'cashier_name': 'أحمد',
        'subtotal': 25000, 'discount_total': 1000, 'total': 24000,
        'cash_amount': 24000, 'card_amount': 0,
        'items': [
            {'name': 'سندويش شاورما', 'quantity': 2, 'price': 10000},
            {'name': 'عصير طبيعي', 'quantity': 1, 'price': 5000},
        ],
    }
    raster = render_escpos_raster_payload(thermal_receipt_structured(data, order), printer['paper_width'],
                                          printer['font_size'], printer.get('logo_data', ''),
                                          printer.get('logo_size', 'medium'), printer.get('logo_alignment', 'center'),
                                          printer.get('receipt_alignment', 'center'), printer.get('print_density', 80),
                                          printer.get('print_quality', 'normal'))
    # أول بايتين هما ESC @؛ بعدها رأس GS v 0 الذي يبدأ بعرض الصف ثم الارتفاع.
    row_bytes = int.from_bytes(raster[6:8], 'little')
    height = int.from_bytes(raster[8:10], 'little')
    data_start = 10
    # في بايتات ESC/POS تكون البتة 1 هي نقطة الحبر السوداء، بينما يفسرها
    # عارض PNG في صورة 1-bit كأبيض؛ نعكسها للمعاينة فقط، ولا نغيّر payload.
    bitmap = Image.frombytes('1', (row_bytes * 8, height), raster[data_start:data_start + row_bytes * height]).convert('L')
    bitmap = bitmap.point(lambda pixel: 0 if pixel > 0 else 255, mode='1').crop((0, 0, row_bytes * 8, height))
    output = BytesIO()
    bitmap.save(output, format='PNG')
    response = send_file(BytesIO(output.getvalue()), mimetype='image/png', max_age=0)
    response.headers['X-Printer-Preview'] = 'escpos-raster'
    return response

@app.route('/api/printer/settings', methods=['POST'])
def set_printer_settings():
    if not has_role('manager'):
        return permission_error()
    data = load()
    if 'settings' not in data:
        data['settings'] = {}
    existing = data['settings'].get('printer', {})
    payload = request.get_json(silent=True) or {}
    logo_data = str(payload.get('logo_data', existing.get('logo_data', '')) or '')
    if logo_data and (not logo_data.startswith('data:image/') or len(logo_data) > 300000):
        return jsonify({'ok': False, 'error': 'صورة الشعار يجب أن تكون صورة محلية لا تتجاوز 200 كيلوبايت'}), 400
    pulse_profile = str(payload.get('cash_drawer_pulse_profile', existing.get('cash_drawer_pulse_profile', 'pin2_standard')) or 'pin2_standard')
    if pulse_profile not in CASH_DRAWER_PULSE_PROFILES:
        return jsonify({'ok': False, 'error': 'نمط نبضة درج النقد غير صالح'}), 400
    paper_width = payload.get('paper_width', existing.get('paper_width', 80))
    try:
        paper_width = int(paper_width)
    except (TypeError, ValueError):
        paper_width = 80
    if paper_width not in (58, 80, 112):
        return jsonify({'ok': False, 'error': 'عرض الورق يجب أن يكون 58mm أو 80mm أو 112mm'}), 400
    paper_orientation = str(payload.get('paper_orientation', existing.get('paper_orientation', 'portrait')) or 'portrait')
    if paper_orientation not in {'portrait', 'landscape'}:
        return jsonify({'ok': False, 'error': 'اتجاه الورق غير صالح'}), 400
    printer_transport = str(payload.get('printer_transport', existing.get('printer_transport', 'auto')) or 'auto')
    if printer_transport not in {'auto', 'windows_usb_wifi', 'network_raw'}:
        return jsonify({'ok': False, 'error': 'طريقة اتصال الطابعة غير صالحة'}), 400
    printer_family = str(payload.get('printer_family', existing.get('printer_family', 'auto')) or 'auto')
    if printer_family not in {'auto', 'escpos_thermal', 'epson_tm', 'xprinter', 'zjiang', 'generic_escpos'}:
        return jsonify({'ok': False, 'error': 'عائلة الطابعة غير صالحة'}), 400
    try:
        print_density = max(30, min(100, int(payload.get('print_density', existing.get('print_density', 80)) or 80)))
    except (TypeError, ValueError):
        print_density = 80
    print_quality = str(payload.get('print_quality', existing.get('print_quality', 'normal')) or 'normal')
    if print_quality not in {'draft', 'normal', 'high'}:
        return jsonify({'ok': False, 'error': 'جودة الطباعة غير صالحة'}), 400
    print_speed = str(payload.get('print_speed', existing.get('print_speed', 'normal')) or 'normal')
    if print_speed not in {'slow', 'normal', 'fast'}:
        return jsonify({'ok': False, 'error': 'سرعة الطباعة غير صالحة'}), 400
    try:
        printer_timeout = max(3, min(30, int(payload.get('printer_timeout', existing.get('printer_timeout', 5)) or 5)))
    except (TypeError, ValueError):
        printer_timeout = 5
    try:
        printer_retry_count = max(0, min(3, int(payload.get('printer_retry_count', existing.get('printer_retry_count', 1)) or 0)))
    except (TypeError, ValueError):
        printer_retry_count = 1
    font_size = str(payload.get('font_size', existing.get('font_size', 'medium')) or 'medium')
    if font_size not in {'small', 'medium', 'large'}:
        return jsonify({'ok': False, 'error': 'حجم خط الإيصال غير صالح'}), 400
    cut_mode = str(payload.get('cut_mode', existing.get('cut_mode', 'full')) or 'full')
    if cut_mode not in {'full', 'partial'}:
        return jsonify({'ok': False, 'error': 'نمط القص غير صالح'}), 400
    try:
        feed_before_cut = max(0, min(10, int(payload.get('feed_before_cut', existing.get('feed_before_cut', 3)) or 0)))
    except (TypeError, ValueError):
        feed_before_cut = 3
    receipt_alignment = str(payload.get('receipt_alignment', existing.get('receipt_alignment', 'center')) or 'center')
    receipt_divider = str(payload.get('receipt_divider', existing.get('receipt_divider', 'line')) or 'line')
    receipt_density = str(payload.get('receipt_density', existing.get('receipt_density', 'standard')) or 'standard')
    logo_size = str(payload.get('logo_size', existing.get('logo_size', 'medium')) or 'medium')
    logo_alignment = str(payload.get('logo_alignment', existing.get('logo_alignment', 'center')) or 'center')
    receipt_layout = payload.get('receipt_layout', existing.get('receipt_layout', list(RECEIPT_LAYOUT_DEFAULT)))
    receipt_font_family = str(payload.get('receipt_font_family', existing.get('receipt_font_family', 'system')) or 'system')
    receipt_font_scale = str(payload.get('receipt_font_scale', existing.get('receipt_font_scale', font_size)) or font_size)
    if receipt_alignment not in {'center', 'right'} or receipt_divider not in {'line', 'double', 'dots'} or receipt_density not in {'compact', 'standard', 'spacious'}:
        return jsonify({'ok': False, 'error': 'خيارات تصميم الإيصال غير صالحة'}), 400
    if logo_size not in {'small', 'medium', 'large'} or logo_alignment not in {'right', 'center', 'left'}:
        return jsonify({'ok': False, 'error': 'خيارات حجم أو محاذاة الشعار غير صالحة'}), 400
    if not is_valid_receipt_layout(receipt_layout):
        return jsonify({'ok': False, 'error': 'ترتيب عناصر الإيصال غير صالح'}), 400
    if receipt_font_family not in {'system', 'cairo', 'serif', 'mono'} or receipt_font_scale not in {'small', 'medium', 'large'}:
        return jsonify({'ok': False, 'error': 'نوع أو حجم خط الإيصال غير صالح'}), 400
    social_links = {}
    for key in ('social_facebook', 'social_instagram', 'social_whatsapp'):
        value = str(payload.get(key, existing.get(key, '')) or '').strip()[:160]
        if value and not re.match(r'^https?://[^\s]+$', value, re.IGNORECASE):
            return jsonify({'ok': False, 'error': 'روابط التواصل يجب أن تبدأ بـ http:// أو https://'}), 400
        social_links[key] = value
    data['settings']['printer'] = {
        'paper_width': paper_width,
        'paper_orientation': paper_orientation,
        'receipt_length_mode': 'auto',
        'font_size': font_size,
        'copies': max(1, min(3, int(payload.get('copies', existing.get('copies', 1)) or 1))) if str(payload.get('copies', existing.get('copies', 1)) or '1').lstrip('-').isdigit() else 1,
        'footer_text': str(payload.get('footer_text', existing.get('footer_text', '')) or '')[:160],
        'printer_name': str(payload.get('printer_name', existing.get('printer_name', '')) or '')[:160],
        'connection_mode': str(payload.get('connection_mode', existing.get('connection_mode', 'windows')) or 'windows') if str(payload.get('connection_mode', existing.get('connection_mode', 'windows')) or 'windows') in {'windows','network'} else 'windows',
        'printer_transport': printer_transport,
        'printer_family': printer_family,
        'print_density': print_density,
        'print_quality': print_quality,
        'print_speed': print_speed,
        'printer_timeout': printer_timeout,
        'printer_retry_count': printer_retry_count,
        'network_host': str(payload.get('network_host', existing.get('network_host', '')) or '')[:120],
        'network_port': int(payload.get('network_port', existing.get('network_port', 9100)) or 9100) if str(payload.get('network_port', existing.get('network_port', 9100)) or '9100').isdigit() else 9100,
        'cut_enabled': bool(payload.get('cut_enabled', existing.get('cut_enabled', True))),
        'cut_mode': cut_mode,
        'feed_before_cut': feed_before_cut,
        'auto_print_receipt': bool(payload.get('auto_print_receipt', existing.get('auto_print_receipt', False))),
        'auto_print_kitchen': bool(payload.get('auto_print_kitchen', existing.get('auto_print_kitchen', False))),
        'cash_drawer_enabled': bool(payload.get('cash_drawer_enabled', existing.get('cash_drawer_enabled', False))),
        'auto_open_cash_drawer': bool(payload.get('auto_open_cash_drawer', existing.get('auto_open_cash_drawer', False))),
        'cash_drawer_printer': str(payload.get('cash_drawer_printer', existing.get('cash_drawer_printer', existing.get('printer_name', ''))) or '')[:160],
        'cash_drawer_pulse_profile': pulse_profile,
        'logo_data': logo_data,
        'logo_caption': str(payload.get('logo_caption', existing.get('logo_caption', '')) or '')[:36],
        'receipt_header': str(payload.get('receipt_header', existing.get('receipt_header', 'إيصال مبيعات')) or 'إيصال مبيعات')[:36],
        'receipt_alignment': receipt_alignment,
        'receipt_divider': receipt_divider,
        'receipt_density': receipt_density,
        'receipt_show_cashier': bool(payload.get('receipt_show_cashier', existing.get('receipt_show_cashier', True))),
        'receipt_show_order_type': bool(payload.get('receipt_show_order_type', existing.get('receipt_show_order_type', True))),
        'logo_size': logo_size,
        'logo_alignment': logo_alignment,
        'receipt_layout': list(receipt_layout),
        'receipt_font_family': receipt_font_family,
        'receipt_font_scale': receipt_font_scale,
        **social_links,
        'receipt_templates': existing.get('receipt_templates', [])
    }
    save(data)
    return jsonify({"ok": True})


RECEIPT_TEMPLATE_FIELDS = ('paper_width', 'font_size', 'footer_text', 'receipt_header', 'receipt_alignment', 'receipt_divider', 'receipt_density', 'receipt_show_cashier', 'receipt_show_order_type', 'logo_size', 'logo_alignment', 'logo_caption', 'social_facebook', 'social_instagram', 'social_whatsapp', 'receipt_layout', 'receipt_font_family', 'receipt_font_scale')


def receipt_template_design(printer):
    """يعيد حقول تصميم قابلة للنقل دون الطابعة أو صورة الشعار أو خيارات الدرج."""
    design = {key: printer.get(key, '') for key in RECEIPT_TEMPLATE_FIELDS}
    design['receipt_layout'] = normalize_receipt_layout(design.get('receipt_layout'))
    return design


@app.route('/api/printer/templates', methods=['GET'])
def get_receipt_templates():
    if not has_role('manager'):
        return permission_error()
    printer = load().get('settings', {}).get('printer', {})
    templates = printer.get('receipt_templates', [])
    safe_templates = [row for row in templates if isinstance(row, dict) and row.get('id') and row.get('name') and isinstance(row.get('design'), dict)]
    return jsonify({'ok': True, 'templates': safe_templates})


@app.route('/api/printer/templates', methods=['POST'])
def save_receipt_template():
    if not has_role('manager'):
        return permission_error()
    payload = request.get_json(silent=True) or {}
    name = str(payload.get('name', '') or '').strip()[:36]
    if len(name) < 2:
        return jsonify({'ok': False, 'error': 'اكتب اسمًا من حرفين على الأقل للقالب'}), 400
    data = load(); printer = data.setdefault('settings', {}).setdefault('printer', {})
    templates = [row for row in printer.get('receipt_templates', []) if isinstance(row, dict) and row.get('id')]
    template = {'id': uuid.uuid4().hex[:12], 'name': name, 'design': receipt_template_design(printer), 'created_at': datetime.now().isoformat()}
    templates.append(template)
    printer['receipt_templates'] = templates[-8:]
    save(data)
    return jsonify({'ok': True, 'template': template})


@app.route('/api/printer/templates/<template_id>/apply', methods=['POST'])
def apply_receipt_template(template_id):
    if not has_role('manager'):
        return permission_error()
    data = load(); printer = data.setdefault('settings', {}).setdefault('printer', {})
    template = next((row for row in printer.get('receipt_templates', []) if isinstance(row, dict) and row.get('id') == template_id), None)
    if not template:
        return jsonify({'ok': False, 'error': 'قالب الإيصال غير موجود'}), 404
    design = template.get('design', {})
    for key in RECEIPT_TEMPLATE_FIELDS:
        if key in design:
            printer[key] = design[key]
    save(data)
    return jsonify({'ok': True, 'name': template.get('name'), 'design': receipt_template_design(printer)})


@app.route('/api/printer/templates/<template_id>', methods=['DELETE'])
def delete_receipt_template(template_id):
    if not has_role('manager'):
        return permission_error()
    data = load(); printer = data.setdefault('settings', {}).setdefault('printer', {})
    templates = printer.get('receipt_templates', [])
    remaining = [row for row in templates if not isinstance(row, dict) or row.get('id') != template_id]
    if len(remaining) == len(templates):
        return jsonify({'ok': False, 'error': 'قالب الإيصال غير موجود'}), 404
    printer['receipt_templates'] = remaining
    save(data)
    return jsonify({'ok': True})


def clean_imported_receipt_design(raw):
    """يتحقق من بيانات تصميم قابلة للمشاركة، دون قبول طابعة أو شعار أو إعدادات تشغيل."""
    if not isinstance(raw, dict):
        return None
    try:
        paper_width = int(raw.get('paper_width', 80))
    except (TypeError, ValueError):
        return None
    if paper_width not in (58, 80, 112):
        return None
    values = {
        'paper_width': paper_width,
        'font_size': str(raw.get('font_size', 'medium') or 'medium'),
        'footer_text': str(raw.get('footer_text', '') or '')[:160],
        'receipt_header': str(raw.get('receipt_header', 'إيصال مبيعات') or 'إيصال مبيعات')[:36],
        'receipt_alignment': str(raw.get('receipt_alignment', 'center') or 'center'),
        'receipt_divider': str(raw.get('receipt_divider', 'line') or 'line'),
        'receipt_density': str(raw.get('receipt_density', 'standard') or 'standard'),
        'receipt_show_cashier': bool(raw.get('receipt_show_cashier', True)),
        'receipt_show_order_type': bool(raw.get('receipt_show_order_type', True)),
        'logo_size': str(raw.get('logo_size', 'medium') or 'medium'),
        'logo_alignment': str(raw.get('logo_alignment', 'center') or 'center'),
        'logo_caption': str(raw.get('logo_caption', '') or '')[:36],
        'receipt_layout': normalize_receipt_layout(raw.get('receipt_layout')),
        'receipt_font_family': str(raw.get('receipt_font_family', 'system') or 'system'),
        'receipt_font_scale': str(raw.get('receipt_font_scale', raw.get('font_size', 'medium')) or 'medium'),
    }
    valid = values['font_size'] in {'small', 'medium', 'large'} and values['receipt_alignment'] in {'center', 'right'} and values['receipt_divider'] in {'line', 'double', 'dots'} and values['receipt_density'] in {'compact', 'standard', 'spacious'} and values['logo_size'] in {'small', 'medium', 'large'} and values['logo_alignment'] in {'right', 'center', 'left'} and values['receipt_font_family'] in {'system', 'cairo', 'serif', 'mono'} and values['receipt_font_scale'] in {'small', 'medium', 'large'} and is_valid_receipt_layout(raw.get('receipt_layout', list(RECEIPT_LAYOUT_DEFAULT)))
    if not valid:
        return None
    for key in ('social_facebook', 'social_instagram', 'social_whatsapp'):
        link = str(raw.get(key, '') or '').strip()[:160]
        if link and not re.match(r'^https?://[^\s]+$', link, re.IGNORECASE):
            return None
        values[key] = link
    return values


@app.route('/api/printer/templates/export', methods=['GET'])
def export_receipt_templates():
    if not has_role('manager'):
        return permission_error()
    printer = load().get('settings', {}).get('printer', {})
    templates = []
    for row in printer.get('receipt_templates', []):
        if isinstance(row, dict) and isinstance(row.get('design'), dict) and row.get('name'):
            templates.append({'name': str(row.get('name'))[:36], 'design': receipt_template_design(row['design'])})
    exported = {'format': 'caesar-receipt-templates', 'version': 1, 'exported_at': datetime.now().isoformat(), 'templates': templates}
    response = Response(json.dumps(exported, ensure_ascii=False, indent=2), mimetype='application/json')
    response.headers['Content-Disposition'] = 'attachment; filename="caesar-receipt-templates.json"'
    return response


@app.route('/api/printer/templates/import', methods=['POST'])
def import_receipt_templates():
    if not has_role('manager'):
        return permission_error()
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or payload.get('format') != 'caesar-receipt-templates' or payload.get('version') != 1 or not isinstance(payload.get('templates'), list):
        return jsonify({'ok': False, 'error': 'ملف القوالب غير متوافق'}), 400
    incoming = payload['templates']
    if not 1 <= len(incoming) <= 8:
        return jsonify({'ok': False, 'error': 'يجب أن يحوي الملف من قالب واحد إلى 8 قوالب'}), 400
    prepared = []
    for row in incoming:
        name = str(row.get('name', '') if isinstance(row, dict) else '').strip()[:36]
        design = clean_imported_receipt_design(row.get('design') if isinstance(row, dict) else None)
        if len(name) < 2 or not design:
            return jsonify({'ok': False, 'error': 'يتضمن الملف قالبًا أو تصميمًا غير صالح'}), 400
        prepared.append({'id': uuid.uuid4().hex[:12], 'name': name, 'design': design, 'created_at': datetime.now().isoformat()})
    data = load(); printer = data.setdefault('settings', {}).setdefault('printer', {})
    existing = [row for row in printer.get('receipt_templates', []) if isinstance(row, dict) and row.get('id')]
    printer['receipt_templates'] = (existing + prepared)[-8:]
    save(data)
    return jsonify({'ok': True, 'imported': len(prepared), 'templates': printer['receipt_templates']})


@app.route('/api/cash-drawer/open', methods=['POST'])
def open_cash_drawer():
    """فتح يدوي لدرج نقد موصول بالطابعة مع سجل تدقيق مستقل."""
    if not has_role('manager'):
        return permission_error()
    data = load()
    reason = str((request.get_json(silent=True) or {}).get('reason', '')).strip()[:160]
    if len(reason) < 2:
        return jsonify({'ok': False, 'error': 'أدخل سببًا واضحًا لفتح درج النقد'}), 400
    log = record_cash_drawer_attempt(data, session.get('username', 'unknown'), reason)
    save(data); backup()
    return jsonify({'ok': log['status'] == 'sent', 'drawer': log})


@app.route('/api/printer/orders/<order_id>/print', methods=['POST'])
def reprint_order(order_id):
    """يعيد طباعة فاتورة محفوظة بطلب صريح من مستخدم يملك صلاحية الكاشير قيصر."""
    if not has_role('manager', 'supervisor', 'cashier'):
        return permission_error()
    data = load()
    order = find_order_anywhere(data, order_id)
    if not order:
        return jsonify({'ok': False, 'error': 'الفاتورة غير موجودة أو ملغاة'}), 404
    printer = data.get('settings', {}).get('printer', {})
    if printer.get('connection_mode') == 'network':
        configured_printer = bool(str(printer.get('network_host') or '').strip())
    else:
        configured_printer = bool(str(printer.get('printer_name') or '').strip())
    if not configured_printer:
        return jsonify({'ok': False, 'error': 'حدد الطابعة أو عنوان طابعة الشبكة أولًا من الإعدادات'}), 400
    previous = printer.get('auto_print_receipt', False)
    printer['auto_print_receipt'] = True
    reprint = dict(order)
    reprint['is_reprint'] = True
    result = queue_thermal_print(data, reprint, 'receipt')
    printer['auto_print_receipt'] = previous
    save(data)
    return jsonify({'ok': result.get('status') in {'queued', 'submitted', 'sent'}, 'print': result})


@app.route('/api/printer/orders/<order_id>/retry', methods=['POST'])
def retry_failed_print(order_id):
    """يعيد محاولة مستند فاشل فقط بعد طلب صريح من مستخدم الصندوق أو الإدارة."""
    if not has_role('manager', 'supervisor', 'cashier'):
        return permission_error()
    payload = request.get_json(silent=True) or {}
    ticket_type = str(payload.get('type', 'receipt')).strip()
    if ticket_type not in ('receipt', 'kitchen'):
        return jsonify({'ok': False, 'error': 'نوع مستند الطباعة غير صالح'}), 400
    data = load()
    order = find_order_anywhere(data, order_id)
    if not order:
        return jsonify({'ok': False, 'error': 'الفاتورة غير موجودة أو ملغاة'}), 404
    failures = [row for row in unresolved_print_failures(data)
                if str(row.get('order_id')) == str(order_id)
                and row.get('type') == ticket_type
                and row.get('status') in {'failed', 'timed_out'}]
    if not failures:
        return jsonify({'ok': False, 'error': 'لا توجد محاولة طباعة فاشلة غير معالجة لهذا المستند'}), 409
    # Reserve the rows before dispatch so a second operator cannot retry the
    # same queued job while its original worker is still active.
    for failure in failures:
        failure['status'] = 'retrying'
        failure['retry_started_at'] = datetime.now().isoformat()
    printer = data.get('settings', {}).get('printer', {})
    if printer.get('connection_mode') == 'network':
        configured_printer = bool(str(printer.get('network_host') or '').strip())
    else:
        configured_printer = bool(str(printer.get('printer_name') or '').strip())
    if not configured_printer:
        return jsonify({'ok': False, 'error': 'حدد الطابعة أو عنوان طابعة الشبكة أولًا من الإعدادات'}), 400
    enabled_key = 'auto_print_receipt' if ticket_type == 'receipt' else 'auto_print_kitchen'
    previous = printer.get(enabled_key, False)
    printer[enabled_key] = True
    result = queue_thermal_print(data, order, ticket_type)
    printer[enabled_key] = previous
    order.setdefault('print_status', {})[ticket_type] = result
    if result.get('status') in {'queued', 'submitted', 'sent'}:
        now = datetime.now().isoformat()
        for failure in failures:
            failure['resolved'] = True
            failure['resolved_at'] = now
            failure['resolution'] = 'retry_queued' if result.get('status') == 'queued' else 'retry_submitted'
    else:
        for failure in failures:
            failure['status'] = 'failed'
            failure['message'] = result.get('message', 'فشلت إعادة الطباعة')
    save(data); backup()
    return jsonify({'ok': result.get('status') in {'queued', 'submitted', 'sent'}, 'print': result, 'unresolved_count': len(unresolved_print_failures(data))})


@app.route('/api/printer/errors', methods=['GET'])
def get_unresolved_print_errors():
    if not has_role('manager', 'supervisor', 'cashier'):
        return permission_error()
    rows = unresolved_print_failures(load())
    rows.sort(key=lambda row: str(row.get('timestamp', '')), reverse=True)
    return jsonify({'ok': True, 'count': len(rows), 'errors': rows[:30]})

@app.route('/api/printer/test', methods=['POST'])
def test_printer():
    """طباعة تجريبية فعلية: ترسل صفحة اختبار حقيقية للطابعة المختارة وتتأكد من نجاح الاتصال،
    بدل الرد بنجاح وهمي دائماً بغض النظر عن وجود طابعة أصلاً."""
    data = load()
    printer = data.get('settings', {}).get('printer', {})
    payload = request.get_json(silent=True) or {}
    if printer.get('connection_mode') == 'network':
        host = str(printer.get('network_host') or '').strip()
        try:
            port = int(printer.get('network_port', 9100) or 9100)
            timeout = max(1, min(10, int(printer.get('printer_timeout', 5) or 5)))
            with socket.create_connection((host, port), timeout=timeout):
                pass
            return jsonify({"ok": True, "message": f"تم الاتصال بالطابعة الشبكية {host}:{port}"})
        except (OSError, ValueError) as exc:
            return jsonify({"ok": False, "message": f"تعذر الاتصال بالطابعة الشبكية: {str(exc)[:160]}"}), 503
    if sys.platform != 'win32':
        width = payload.get('paper_width', 80)
        try:
            width = int(width)
        except (ValueError, TypeError):
            width = 80
        if width not in {58, 80, 112}:
            return jsonify({"ok": False, "message": "عرض ورق غير صالح للطباعة التجريبية"}), 400
        return jsonify({"ok": True, "message": f"تشغيل تجريبي لقالب {width}mm (بيئة غير ويندوز) - الاختبار الفعلي متاح فقط عند التشغيل على ويندوز", "paper_width": width})
    printer_name = data.get('settings', {}).get('printer', {}).get('printer_name') or get_default_windows_printer()
    if not printer_name:
        return jsonify({"ok": False, "message": "ما في طابعة محددة بعد - اختر طابعة من الإعدادات أولاً"})
    printer = data.get('settings', {}).get('printer', {})
    payload = request.get_json(silent=True) or {}
    printer = dict(printer)
    for key in ('print_density', 'print_quality', 'print_speed'):
        if key in payload:
            printer[key] = payload[key]
    try:
        width = int(payload.get('paper_width', printer.get('paper_width', 80)) or 80)
    except (ValueError, TypeError):
        width = 80
    if width not in {58, 80, 112}:
        return jsonify({"ok": False, "message": "عرض ورق غير صالح للطباعة التجريبية"}), 400
    chars = 42 if width >= 80 else 32
    restaurant = data.get('settings', {}).get('restaurant', {}).get('name', 'كاشير قيصر قيصر')
    header = str(payload.get('receipt_header', printer.get('receipt_header', 'إيصال مبيعات')) or 'إيصال مبيعات')[:36]
    divider = '-' * chars
    pattern = str(payload.get('pattern', 'standard') or 'standard')
    if pattern == 'density':
        test_text = f"{restaurant.center(chars)}\n{divider}\nاختبار الكثافة\nخفيف  متوسط  داكن\nMMMMMMMMMMMMMMMM\nالعربية: شاورما كريسبي بروستد\n1234567890\n{divider}\n"
    elif pattern == 'alignment':
        test_text = f"{restaurant.center(chars)}\n{divider}\nيمين: العربية\nوسط: CAESAR POS\nيسار: 1234567890\n{divider}\n"
    else:
        test_text = f"{restaurant.center(chars)}\n{divider}\n{header.center(chars)}\n{('اختبار مقاس ' + str(width) + 'mm').center(chars)}\n{datetime.now().strftime('%Y-%m-%d %H:%M')}\n{divider}\nتمت الطباعة العربية بنجاح\n"
    test_font_size = str(printer.get('font_size', 'medium') or 'medium')
    if printer.get('connection_mode') == 'network':
        dispatched = submit_network_raw_print(printer.get('network_host'), printer.get('network_port', 9100), test_text, test_font_size, width, printer)
        ok = dispatched.get('ok', False)
        msg = dispatched.get('message', 'تعذر اختبار الطابعة الشبكية')
    else:
        dispatched = submit_silent_thermal_print(printer_name, test_text, test_font_size, width, 'CAESAR Arabic Print Test', printer)
        ok = dispatched.get('ok', False)
        msg = dispatched.get('message', f"تعذر الإرسال للطابعة: {printer_name}")
    return jsonify({"ok": ok, "message": msg, "paper_width": width})


@app.route('/api/printer/diagnostics', methods=['POST'])
def printer_diagnostics():
    """يفحص مسار الاتصال دون إرسال إيصال أو تغيير إعدادات الطابعة."""
    if not has_role('manager', 'supervisor', 'cashier'):
        return permission_error()
    printer = load().get('settings', {}).get('printer', {})
    mode = printer.get('connection_mode', 'windows')
    if mode == 'network':
        host = str(printer.get('network_host', '') or '').strip()
        try:
            port = int(printer.get('network_port', 9100) or 9100)
            timeout = max(3, min(30, int(printer.get('printer_timeout', 5) or 5)))
        except (TypeError, ValueError):
            return jsonify({'ok': False, 'status': 'invalid_config', 'message': 'عنوان IP أو المنفذ غير صالح'}), 400
        if not host or not (1 <= port <= 65535):
            return jsonify({'ok': False, 'status': 'not_configured', 'message': 'أدخل عنوان IP ومنفذ الطابعة أولًا'}), 400
        try:
            with socket.create_connection((host, port), timeout=timeout):
                pass
            return jsonify({'ok': True, 'status': 'online', 'transport': 'network', 'message': f'الطابعة تستجيب على {host}:{port}'})
        except OSError as exc:
            return jsonify({'ok': False, 'status': 'offline', 'transport': 'network', 'message': f'لا يوجد اتصال بالطابعة: {str(exc)[:160]}'})
    if sys.platform != 'win32':
        return jsonify({'ok': False, 'status': 'unavailable', 'transport': 'windows', 'message': 'فحص USB/Windows يعمل داخل النسخة المبنية على Windows فقط'})
    printers = list_windows_printers()
    printer_status = list_windows_printer_status()
    name = printer.get('printer_name') or get_default_windows_printer()
    current = next((row for row in printer_status if row.get('name') == name), None)
    found = bool(current)
    online = bool(current and current.get('status') != 'offline')
    return jsonify({'ok': online, 'status': 'ready' if online else ('offline' if found else 'not_found'), 'transport': 'windows', 'printer_name': name or '', 'printers': printers, 'printer_status': printer_status, 'message': 'الطابعة متصلة وجاهزة حسب Windows' if online else ('الطابعة مثبتة لكنها Offline أو في حالة خطأ' if found else 'الطابعة غير ظاهرة في قائمة Windows')})


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
    ip_address = request.remote_addr or 'unknown'
    throttled = login_throttle_error(data, username, ip_address)
    if throttled:
        return throttled
    users = active_users(data)
    for u in users:
        if u.get('username') == username and verify_password(u.get('password_hash', u.get('password', '')), password):
            clear_login_failures(data, username, ip_address)
            return jsonify({"ok": True, "username": u['username'], "role": u.get('role', 'cashier')})
    record_login_failure(data, username, ip_address)
    return jsonify({"ok": False, "error": "اسم المستخدم أو كلمة المرور غير صحيحة"}), 401


@app.route('/api/auth/verify-current', methods=['POST'])
def verify_current_user():
    """يفتح قفل الشاشة فقط عندما تُدخل كلمة مرور الكاشير قيصر/المستخدم المسجل حاليًا."""
    username = session.get('username')
    if not username:
        return jsonify({'ok': False, 'error': 'سجّل الدخول أولاً'}), 401
    payload = request.get_json(silent=True) or {}
    password = payload.get('password') or ''
    data = load()
    ip_address = request.remote_addr or 'unknown'
    throttled = login_throttle_error(data, username, ip_address)
    if throttled:
        return throttled
    user = next((u for u in active_users(data) if u.get('username') == username), None)
    if not user or not verify_password(user.get('password_hash', user.get('password', '')), password):
        record_login_failure(data, username, ip_address)
        return jsonify({'ok': False, 'error': 'رمز كاشير قيصر غير صحيح'}), 401
    clear_login_failures(data, username, ip_address)
    if not str(user.get('password_hash', '')).startswith('pbkdf2_sha256$'):
        user['password_hash'] = hash_password(password)
        save(data)
    # هذا المسار مخصص للكاشير قيصر/المستخدم الحالي؛ نجاح التحقق يزيل القفل فعلياً من الجلسة.
    session['screen_locked'] = False
    session['username'] = user.get('username', username)
    session['role'] = user.get('role', 'cashier')
    return jsonify({'ok': True, 'username': session['username'], 'role': session['role'], 'locked': False})




def has_role(*allowed):
    """يتحقق من جلسة المستخدم؛ العمليات الحساسة لا تعتمد على إخفاء الزر في الواجهة."""
    users = load().get('settings', {}).get('users', [])
    return not users or session.get('role') in allowed


def permission_error():
    return jsonify({'ok': False, 'error': 'ليس لديك صلاحية لتنفيذ هذه العملية'}), 403



def active_users(data=None):
    """يعيد كل الحسابات القابلة للمصادقة، بما فيها حسابات النسخ القديمة."""
    data = data or load()
    settings_users = data.get('settings', {}).get('users', [])
    if settings_users:
        return settings_users
    return data.get('users', [])


def authenticate_pos_user(data, username, password):
    """يتحقق من أي مستخدم POS مخوّل، ويعتبر الحساب القديم بلا role كاشير قيصراً."""
    username = str(username or '').strip()
    password = str(password or '')
    for candidate in active_users(data):
        role = candidate.get('role', 'cashier')
        if (candidate.get('username') == username
                and role in ROLE_LABELS
                and verify_password(candidate.get('password_hash', candidate.get('password', '')), password)):
            candidate.setdefault('role', 'cashier')
            return candidate
    return None


def manager_session_required():
    users = active_users()
    return bool(users) and session.get('role') == 'manager'


def authenticated_roles(*roles):
    return session.get('role') in roles



def is_screen_locked():
    return bool(session.get('screen_locked'))


@app.before_request
def enforce_api_access():
    """يفرض الإعداد الأولي والجلسة والصلاحية على الواجهة البرمجية، وليس على الأزرار فقط."""
    if not request.path.startswith('/api/'):
        return None
    # القراءة لا تحتاج قفل الطلب العام؛ load() يحمي عملية القراءة نفسها.
    # حصر القفل العام في الطلبات التي تغيّر الحالة يسمح بتوازي شاشات LAN
    # (المطبخ/الطاولات/الجوال) ويمنع أن يحجب تقرير أو استعلام قراءة بقية الأجهزة.
    if request.method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
        DATA_LOCK.acquire()
        request._caesar_data_lock = True
    direct_order_read = request.method == 'GET' and (request.path == '/api/orders' or request.path.startswith('/api/order/'))
    data = load_snapshot_only() if direct_order_read else load()
    path = request.path
    method = request.method
    if method in {'POST', 'PUT', 'PATCH', 'DELETE'}:
        origin = request.headers.get('Origin', '').strip().rstrip('/')
        expected_origin = request.host_url.rstrip('/')
        mobile_origins = {item.strip().rstrip('/') for item in os.environ.get('CAESAR_MOBILE_ORIGINS', '').split(',') if item.strip()}
        allowed_origins = ({expected_origin} | mobile_origins) if path.startswith('/api/mobile/') else {expected_origin}
        if origin and origin not in allowed_origins:
            return jsonify({'ok': False, 'error': 'مصدر الطلب غير مسموح'}), 403

    # لا يمكن البيع أو مشاهدة بيانات مطعم قبل إنشاء هوية المطعم والمدير الأول.
    if not commercial_setup_complete(data):
        if path not in {'/api/setup/status', '/api/setup/initialize', '/api/network/info'}:
            return jsonify({'ok': False, 'error': 'يجب إكمال الإعداد الأولي للمطعم أولاً'}), 423
        return None

    # المعاينة صورة محلية غير تشغيلية ولا ترسل شيئًا للطابعة؛ نُبقيها متاحة
    # للمدير كي يستطيع فحص تصميم الإيصال عند الحاجة لإعادة تفعيل النسخة.
    if not installation_license_valid(data) and path != '/api/printer/preview':
        return jsonify({'ok': False, 'error': 'الترخيص غير صالح لهذا الجهاز. يلزم إعادة تفعيل النسخة.'}), 423

    # بوابة الجوال تقرأ حالة الميزات فقط لإخفاء الأقسام المعطلة؛ تغييرها يبقى للمدير.
    if path == '/api/settings/features' and method == 'GET':
        return None
    # بيانات شاشة الترحيب وتسجيل الدخول فقط. قائمة المستخدمين لا تتضمن كلمة مرور أو تجزئتها.
    if path in PUBLIC_API_PATHS:
        return None
    # تطبيق النادل لا يحمل Cookie المتصفح؛ كل واجهاته تتحقق من رمز قصير العمر داخل الدالة نفسها.
    if path.startswith('/api/mobile/'):
        return None
    if path == '/api/qr/menu':
        if os.environ.get('CAESAR_LAN') != '1':
            return jsonify({'ok': False, 'error': 'القائمة الرقمية العامة متاحة فقط عند تفعيل وضع الشبكة المحلية'}), 403
        return None

    role = session.get('role')
    if role not in ROLE_LABELS:
        return jsonify({'ok': False, 'error': 'سجّل الدخول أولاً'}), 401

    # يجب السماح لمساري حالة الجلسة وفتح القفل بالوصول أثناء القفل؛ وإلا سيمنع الحارس عملية unlock نفسها.
    if path in {'/api/auth/me', '/api/auth/unlock'}:
        return None

    if is_screen_locked():
        return jsonify({'ok': False, 'locked': True, 'error': 'الشاشة مقفلة. أدخل بيانات أي مستخدم مخوّل لإعادة فتحها.'}), 423

    if path != '/api/settings/features':
        feature_by_path = {
            '/api/kitchen/': 'kitchen',
            '/api/tables': 'tables',
            '/api/dine-in/': 'tables',
            '/api/delivery/': 'delivery',
            '/api/customers': 'customers',
            '/api/mobile/': 'mobile',
            '/api/dashboard/': 'reports',
        }
        for prefix, feature in feature_by_path.items():
            if path.startswith(prefix) and not feature_is_enabled(data, feature):
                return jsonify({'ok': False, 'error': 'هذه الميزة غير مفعّلة من إعدادات المدير'}), 403

    # مسار الصلاحيات الوحيد: كل طلب يطابق سياسة مركزية، والجديد يُغلق
    # للكاشير قيصر افتراضيًا حتى تتم مراجعته وإضافته صراحة إلى permissions.py.
    if (method, path) == ('POST', '/api/auth/verify-current'):
        return None
    allowed_roles = allowed_roles_for_request(method, path)
    if role not in (allowed_roles or frozenset()):
        return permission_error()
    return None


@app.teardown_request
def release_data_lock(_error=None):
    if getattr(request, '_caesar_data_lock', False):
        request._caesar_data_lock = False
        DATA_LOCK.release()


@app.after_request
def disable_caching(response):
    """يمنع المتصفح من الاحتفاظ بنسخة قديمة مخبّأة من أي صفحة أو ملف JS/CSS
    بعد كل تحديث للنظام، لتفادي ظهور مزيج من واجهة قديمة وجديدة بنفس الشاشة."""
    response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


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
            error_logger.error('فشل تسجيل سجل التدقيق (audit_log) لمسار %s', request.path, exc_info=True)
    return response


@app.after_request
def mobile_api_cors(response):
    """يسمح لتطبيق النادل المحلي فقط بالوصول إلى واجهات /api/mobile المحمية برمز."""
    if request.path.startswith('/api/mobile/'):
        origin = request.headers.get('Origin', '')
        configured = {item.strip() for item in os.environ.get('CAESAR_MOBILE_ORIGINS', '').split(',') if item.strip()}
        if origin and origin in configured:
            response.headers['Access-Control-Allow-Origin'] = origin
            response.headers['Vary'] = 'Origin'
        response.headers['Access-Control-Allow-Headers'] = 'Authorization, Content-Type'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PUT, OPTIONS'
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
    return jsonify({'ok': False, 'error': 'اسم المستخدم أو كلمة المرور غير صحيحة'}), 401

@app.route('/api/auth/logout', methods=['POST'])
def auth_logout():
    session.clear()
    return jsonify({"ok": True})


@app.route('/api/auth/lock', methods=['POST'])
def auth_lock_screen():
    """يقفل الواجهة فوراً ولا يمكن تجاوز القفل إلا عبر حساب POS مخوّل."""
    if session.get('role') not in ROLE_LABELS:
        return jsonify({'ok': False, 'error': 'سجّل الدخول أولاً'}), 401
    session['screen_locked'] = True
    return jsonify({'ok': True, 'locked': True, 'message': 'تم قفل الشاشة. يلزم إدخال حساب مستخدم صالح لإعادة فتحها.'})


@app.route('/api/auth/unlock', methods=['POST'])
def auth_unlock_screen():
    """يفتح القفل بحساب POS صالح، بما في ذلك الكاشير قيصر، مع الحفاظ على دوره وصلاحياته."""
    payload = request.get_json(silent=True) or {}
    username = str(payload.get('username', '')).strip()
    password = str(payload.get('password', ''))
    data = load()
    ip_address = request.remote_addr or 'unknown'
    throttled = login_throttle_error(data, username, ip_address)
    if throttled:
        return throttled
    user = authenticate_pos_user(data, username, password)
    if not user:
        record_login_failure(data, username, ip_address)
        return jsonify({'ok': False, 'error': 'اسم المستخدم أو كلمة المرور غير صحيحة'}), 401
    clear_login_failures(data, username, ip_address)
    if not str(user.get('password_hash', '')).startswith('pbkdf2_sha256$'):
        user['password_hash'] = hash_password(password)
        save(data)
    session.clear()
    session.permanent = True
    session['username'] = user['username']
    session['role'] = user.get('role', 'cashier')
    session['screen_locked'] = False
    return jsonify({'ok': True, 'locked': False, 'username': user['username'], 'role': session['role']})


@app.route('/api/auth/me', methods=['GET'])
def auth_me():
    return jsonify({"username": session.get('username'), "role": session.get('role'), "locked": is_screen_locked()})

def role_page_or_login(filename):
    """يحمي صفحة حسب المستوى الوظيفي المطلوب لها."""
    data = load()
    users = data.get('settings', {}).get('users', [])
    allowed = ROLE_PAGE_ACCESS.get(filename, {'manager'})
    if users and not page_allowed(filename, session.get('role')):
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
    backup(force=True)
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
        factory_data['order_counter'] = 0
        save(factory_data)
        conn = db_connect()
        try:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('DELETE FROM order_items')
            conn.execute('DELETE FROM orders')
            conn.execute('COMMIT')
        except Exception:
            try: conn.execute('ROLLBACK')
            except sqlite3.Error: pass
            raise
        finally:
            conn.close()
        atomic_write_json(DATA_FILE, _compact_state_snapshot(factory_data))
        return jsonify({"ok": True, "message": "تمت إعادة ضبط المصنع وتحديث SQLite وملف الحالة بنجاح"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route('/api/check-update', methods=['GET'])
def check_update_route():
    """يعيد حالة الإصدار المحلية دون فحص شبكة أو تنزيل ملفات."""
    result = check_for_updates()
    return jsonify(result)


@app.route('/api/order/<order_id>', methods=['GET'])
def get_order(order_id):
    """البحث عن فاتورة برقمها"""
    conn = db_connect()
    try:
        row = conn.execute('SELECT payload FROM orders WHERE id=?', (str(order_id),)).fetchone()
    finally:
        conn.close()
    if row:
        try:
            return jsonify(json.loads(row['payload']))
        except (TypeError, ValueError):
            pass
    for o in load_cold_orders():
        if str(o.get('id')) == str(order_id):
            return jsonify(o)
    return jsonify({"error": "الفاتورة غير موجودة"}), 404



# ========== ميزات كاشير قيصر قيصر المتقدمة ==========
def _store(data, key, default=None):
    if key not in data:
        data[key] = [] if default is None else default
    return data[key]

def _today_orders(data):
    today = datetime.now().strftime('%Y-%m-%d')
    return [o for o in data.get('orders', []) + data.get('orders_archive', [])
            if (o.get('timestamp') or o.get('date', '')).startswith(today) and not o.get('voided')]

def _shift_cutoff(data, username):
    rows = [r for r in data.get('shift_handovers', []) if r.get('from_cashier') == username]
    return max((r.get('time', '') for r in rows), default='')

def _cashier_shift_summary(data, username, cutoff=''):
    orders = []
    for order in data.get('orders', []) + data.get('orders_archive', []):
        stamp = order.get('timestamp') or order.get('date', '')
        if order.get('voided') or order.get('cashier_name') != username or (cutoff and stamp <= cutoff):
            continue
        orders.append(order)
    cash = sum_money(o.get('cash_amount', o.get('total', 0) if o.get('payment') != 'بطاقة' else 0) or 0 for o in orders)
    card = sum_money(o.get('card_amount', o.get('total', 0) if o.get('payment') == 'بطاقة' else 0) or 0 for o in orders)
    return {'cashier': username, 'from': cutoff or None, 'to': datetime.now().isoformat(), 'orders': len(orders),
            'sales': sum_money(o.get('total', 0) or 0 for o in orders), 'cash': cash, 'card': card}

@app.route('/api/shift/users', methods=['GET'])
def shift_users():
    data = load(); users = data.get('settings', {}).get('users', [])
    return jsonify([{'username': u.get('username'), 'role': u.get('role', 'cashier')}
                    for u in users if u.get('username') and u.get('role', 'cashier') == 'cashier'])


@app.route('/api/shifts/cashiers', methods=['GET'])
def cashier_shift_summaries():
    """جرد مستقل لكل كاشير قيصر، مع احترام نقطة بداية كل تسليم سابق."""
    data = load()
    users = [u.get('username') for u in data.get('settings', {}).get('users', [])
             if u.get('username') and u.get('role', 'cashier') == 'cashier']
    return jsonify([_cashier_shift_summary(data, username, _shift_cutoff(data, username))
                    for username in users])

@app.route('/api/shifts/handover', methods=['POST'])
def shift_handover():
    if not has_role('cashier', 'supervisor', 'manager'):
        return permission_error()
    data = load(); payload = request.get_json(silent=True) or {}
    from_cashier = session.get('username', 'غير محدد')
    to_cashier = str(payload.get('to_cashier', '')).strip()
    if not to_cashier or to_cashier == from_cashier:
        return jsonify({'ok': False, 'error': 'اختر كاشير قيصرًا آخر لاستلام الوردية'}), 400
    users = {u.get('username') for u in data.get('settings', {}).get('users', [])}
    if to_cashier not in users:
        return jsonify({'ok': False, 'error': 'الكاشير قيصر المستلم غير موجود'}), 404
    summary = _cashier_shift_summary(data, from_cashier, _shift_cutoff(data, from_cashier))
    actual_cash = payload.get('actual_cash')
    if actual_cash not in (None, ''):
        try:
            actual_cash = Decimal(str(actual_cash))
            if not actual_cash.is_finite() or actual_cash < 0:
                raise ValueError
            summary['actual_cash'] = round_money(actual_cash)
            summary['difference'] = round_money(summary['actual_cash'] - summary['cash'])
        except (InvalidOperation, TypeError, ValueError): return jsonify({'ok': False, 'error': 'النقد الفعلي غير صالح'}), 400
    handover = {'id': uuid.uuid4().hex[:12], 'time': datetime.now().isoformat(), 'from_cashier': from_cashier,
                'to_cashier': to_cashier, 'summary': summary, 'note': str(payload.get('note', '') or '')[:300],
                'created_by': from_cashier}
    _store(data, 'shift_handovers').append(handover); save(data); backup()
    return jsonify({'ok': True, 'handover': handover})

@app.route('/api/shifts', methods=['GET'])
def list_shifts():
    data = load()
    return jsonify(data.get('shift_handovers', []))

@app.route('/api/shifts/current', methods=['GET'])
def current_shift():
    data = load()
    if session.get('role') == 'cashier':
        return jsonify(_cashier_shift_summary(data, session.get('username', 'غير محدد'), _shift_cutoff(data, session.get('username', 'غير محدد'))))
    orders = _today_orders(data)
    return jsonify({'date': datetime.now().strftime('%Y-%m-%d'), 'orders': len(orders),
                    'sales': sum_money(o.get('total', 0) or 0 for o in orders),
                    'cash': sum_money(o.get('cash_amount', o.get('total', 0) if o.get('payment') != 'بطاقة' else 0) or 0 for o in orders),
                    'card': sum_money(o.get('card_amount', o.get('total', 0) if o.get('payment') == 'بطاقة' else 0) or 0 for o in orders),
                    'cashier': 'جميع الكاشير قيصرات'})

@app.route('/api/shifts/close', methods=['POST'])
def close_shift_secure():
    if not has_role('manager'):
        return permission_error()
    data = load(); orders = _today_orders(data); payload = request.get_json(silent=True) or {}
    expected_cash = sum_money(o.get('cash_amount', o.get('total', 0) if o.get('payment') != 'بطاقة' else 0) or 0 for o in orders)
    actual_cash = payload.get('actual_cash')
    actual_cash_value = None
    if actual_cash not in (None, ''):
        try:
            actual_cash_value = Decimal(str(actual_cash))
            if not actual_cash_value.is_finite() or actual_cash_value < 0:
                raise ValueError
            actual_cash = round_money(actual_cash_value)
        except (InvalidOperation, TypeError, ValueError):
            return jsonify({'ok': False, 'error': 'النقد الفعلي غير صالح'}), 400
    shift = {'id': len(data.get('shifts', [])) + 1, 'date': datetime.now().strftime('%Y-%m-%d'),
             'time': datetime.now().isoformat(), 'orders': len(orders),
             'sales': sum_money(o.get('total', 0) or 0 for o in orders),
             'expected_cash': expected_cash, 'actual_cash': actual_cash,
             'difference': round_money(actual_cash_value - Decimal(str(expected_cash))) if actual_cash_value is not None else None,
             'closed_by': session.get('username', 'manager'), 'reason': str(payload.get('reason', ''))[:300]}
    _store(data, 'shifts').append(shift)
    cut_result = cut_paper_to_printer(data.get('settings', {}).get('printer', {}))
    shift['paper_cut'] = {
        'status': cut_result.get('status', 'failed'),
        'message': cut_result.get('message', ''),
        'job_id': cut_result.get('job_id', ''),
        'time': datetime.now().isoformat(),
    }
    save(data); backup()
    return jsonify({'ok': True, 'shift': shift, 'paper_cut': cut_result})

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
            if not isinstance(item_indexes, list) or any(not isinstance(i, int) for i in item_indexes):
                return jsonify({'ok': False, 'error': 'فهرس الصنف غير صالح'}), 400
            if len(set(item_indexes)) != len(item_indexes):
                return jsonify({'ok': False, 'error': 'لا يمكن اختيار الصنف نفسه أكثر من مرة'}), 400
            source_items = o.get('items', []) or []
            if any(i < 0 or i >= len(source_items) for i in item_indexes):
                return jsonify({'ok': False, 'error': 'فهرس الصنف غير موجود'}), 400
            moved = [source_items[i] for i in item_indexes]
            if not moved: return jsonify({'ok': False, 'error': 'الأصناف غير موجودة'}), 400
            selected = set(item_indexes)
            remaining = [x for i, x in enumerate(source_items) if i not in selected]
            def item_total(items):
                return sum_money(float(x.get('price', 0) or 0) * float(x.get('quantity', x.get('qty', 1)) or 0) for x in items)
            old_subtotal = item_total(source_items)
            moved_subtotal = item_total(moved)
            remaining_subtotal = item_total(remaining)
            old_total = round_money(o.get('total', 0))
            discount_total = round_money(max(0, old_subtotal - old_total))
            moved_discount = round_money(discount_total * moved_subtotal / old_subtotal) if old_subtotal else 0
            remaining_discount = round_money(discount_total - moved_discount)
            moved_total = round_money(max(0, moved_subtotal - moved_discount))
            remaining_total = round_money(max(0, remaining_subtotal - remaining_discount))
            if round_money(moved_total + remaining_total) != old_total:
                remaining_total = round_money(old_total - moved_total)
                remaining_discount = round_money(remaining_subtotal - remaining_total)
            if 'cash_amount' in o or 'card_amount' in o:
                old_cash = round_money(o.get('cash_amount', 0))
                old_card = round_money(o.get('card_amount', 0))
            elif o.get('payment') == 'بطاقة':
                old_cash, old_card = 0.0, old_total
            else:
                old_cash, old_card = old_total, 0.0
            if round_money(old_cash + old_card) != old_total:
                return jsonify({'ok': False, 'error': 'تقسيمة الدفع لا تطابق إجمالي الفاتورة'}), 409
            new_cash = round_money(old_cash * moved_total / old_total) if old_total else 0.0
            new_card = round_money(moved_total - new_cash) if old_total else 0.0
            new_order = dict(o)
            new_order['id'] = next_order_id(data)
            new_order['items'] = moved
            new_order.update({'subtotal': moved_subtotal, 'discount_pct': 0,
                              'discount_amount': moved_discount, 'discount_total': moved_discount, 'total': moved_total,
                              'cash_amount': new_cash, 'card_amount': new_card,
                              'split_from': o.get('id'), 'timestamp': datetime.now().isoformat()})
            o['items'] = remaining
            o.update({'subtotal': remaining_subtotal, 'discount_pct': 0,
                      'discount_amount': remaining_discount, 'discount_total': remaining_discount, 'total': remaining_total,
                      'cash_amount': round_money(old_cash - new_cash),
                      'card_amount': round_money(old_card - new_card), 'split_into': new_order['id']})
            data['orders'].append(new_order)
            save(data, [o['id'], new_order['id']]); backup()
            return jsonify({'ok': True, 'new_order': new_order, 'original_order': o})
    return jsonify({'ok': False, 'error': 'الطلب غير موجود'}), 404

DINE_IN_STATUSES = {'open', 'closed', 'cancelled'}
KITCHEN_STATUSES = {'held', 'new', 'preparing', 'ready', 'served'}


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
    subtotal = sum_money(item['price'] * item['quantity'] for item in items)
    discount_pct = as_money(payload.get('discount_pct', 0), 0)
    discount_amount = as_money(payload.get('discount_amount', 0), 0)
    if discount_pct is None or not 0 <= discount_pct <= 100 or discount_amount is None:
        return None, 'قيمة الخصم غير صالحة'
    after_percent = round_money(subtotal * (1 - discount_pct / 100))
    if discount_amount > after_percent:
        return None, 'الخصم أكبر من إجمالي الطلب'
    total = round_money(after_percent - discount_amount)
    return {'items': items, 'subtotal': subtotal, 'discount_pct': discount_pct,
            'discount_amount': discount_amount, 'discount_total': round_money(subtotal - total),
            'total': total}, None


def dine_in_session_view(session_row):
    return {
        'id': session_row.get('id'), 'table_id': session_row.get('table_id'), 'table_name': session_row.get('table_name'),
        'status': session_row.get('status'), 'items': session_row.get('items', []), 'subtotal': session_row.get('subtotal', 0),
        'discount_pct': session_row.get('discount_pct', 0), 'discount_amount': session_row.get('discount_amount', 0),
        'discount_total': session_row.get('discount_total', 0),
        'total': session_row.get('total', 0), 'note': session_row.get('note', ''), 'customer': session_row.get('customer', ''),
        'kitchen_status': session_row.get('kitchen_status', 'new'), 'kitchen_release': session_row.get('kitchen_release', 'now'),
        'manager_approval': session_row.get('manager_approval'), 'opened_by': session_row.get('opened_by', ''),
        'created_at': session_row.get('created_at', ''), 'updated_at': session_row.get('updated_at', '')
    }


def mobile_waiter_from_request(data):
    """يتحقق من رمز النادل المرسل بالتطبيق ويقصر الوصول على شبكة المطعم المحلية."""
    if os.environ.get('CAESAR_LAN') != '1':
        return None, (jsonify({'ok': False, 'error': 'تطبيق النادل متاح فقط عند تفعيل الشبكة المحلية'}), 403)
    header = request.headers.get('Authorization', '')
    token = header[7:].strip() if header.lower().startswith('bearer ') else ''
    if not token:
        return None, (jsonify({'ok': False, 'error': 'رمز الدخول مطلوب'}), 401)
    digest = hashlib.sha256(token.encode('utf-8')).hexdigest()
    now = datetime.now().isoformat()
    for token_row in data.get('mobile_tokens', []):
        if hmac.compare_digest(str(token_row.get('digest', '')), digest):
            if token_row.get('expires_at', '') < now:
                return None, (jsonify({'ok': False, 'error': 'انتهت جلسة النادل؛ سجّل الدخول مجددًا'}), 401)
            user = next((row for row in active_users(data) if row.get('id') == token_row.get('user_id') and row.get('role') == 'waiter'), None)
            if user:
                return user, None
    return None, (jsonify({'ok': False, 'error': 'رمز دخول النادل غير صالح'}), 401)


def mobile_auth_error():
    data = load()
    waiter, error = mobile_waiter_from_request(data)
    return data, waiter, error


@app.route('/api/mobile/auth/login', methods=['POST', 'OPTIONS'])
def mobile_waiter_login():
    if request.method == 'OPTIONS':
        return ('', 204)
    if os.environ.get('CAESAR_LAN') != '1':
        return jsonify({'ok': False, 'error': 'فعّل وضع الشبكة المحلية في الكاشير قيصر أولًا'}), 403
    payload = request.get_json(silent=True) or {}
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
    clear_login_failures(data, username, ip_address)
    token = secrets.token_urlsafe(32)
    # Keep the mobile bearer session short-lived and consistent with the waiter UI.
    expires_at = (datetime.now() + timedelta(hours=12)).isoformat()
    tokens = [row for row in data.setdefault('mobile_tokens', []) if row.get('expires_at', '') >= datetime.now().isoformat() and row.get('user_id') != user.get('id')]
    tokens.append({'digest': hashlib.sha256(token.encode('utf-8')).hexdigest(), 'user_id': user['id'], 'expires_at': expires_at, 'created_at': datetime.now().isoformat()})
    data['mobile_tokens'] = tokens[-100:]
    save(data)
    return jsonify({'ok': True, 'token': token, 'expires_at': expires_at, 'user': {'id': user['id'], 'username': user['username'], 'role': 'waiter'}})


@app.route('/api/mobile/auth/logout', methods=['POST', 'OPTIONS'])
def mobile_waiter_logout():
    if request.method == 'OPTIONS':
        return ('', 204)
    data, waiter, error = mobile_auth_error()
    if error:
        return error
    digest = hashlib.sha256(request.headers.get('Authorization', '')[7:].strip().encode('utf-8')).hexdigest()
    data['mobile_tokens'] = [row for row in data.get('mobile_tokens', []) if not hmac.compare_digest(str(row.get('digest', '')), digest)]
    save(data)
    return jsonify({'ok': True})


@app.route('/api/mobile/bootstrap', methods=['GET', 'OPTIONS'])
def mobile_bootstrap():
    if request.method == 'OPTIONS':
        return ('', 204)
    data, waiter, error = mobile_auth_error()
    if error:
        return error
    normalize_tables(data)
    return jsonify({'ok': True, 'restaurant': data.get('settings', {}).get('restaurant', {}), 'waiter': {'id': waiter['id'], 'username': waiter['username']}, 'tables': data.get('tables', []), 'menu': data.get('menu', {})})


@app.route('/api/mobile/tables', methods=['GET', 'OPTIONS'])
def mobile_tables():
    if request.method == 'OPTIONS':
        return ('', 204)
    data, _, error = mobile_auth_error()
    if error:
        return error
    tables = normalize_tables(data)
    sessions = {str(row.get('table_id')): dine_in_session_view(row) for row in data.get('dine_in_sessions', []) if row.get('status') == 'open'}
    rows = []
    for table in tables:
        row = dict(table)
        row['active_session'] = sessions.get(str(table.get('id')))
        rows.append(row)
    return jsonify({'ok': True, 'tables': rows})


@app.route('/api/mobile/dine-in/sessions', methods=['POST', 'OPTIONS'])
def mobile_create_dine_in_session():
    if request.method == 'OPTIONS':
        return ('', 204)
    data, waiter, error = mobile_auth_error()
    if error:
        return error
    normalize_tables(data)
    payload = request.get_json(silent=True) or {}
    table = find_table(data, payload.get('table_id'))
    if not table:
        return jsonify({'ok': False, 'error': 'اختر طاولة صالحة'}), 404
    if table.get('status') == 'busy' or table.get('active_session_id'):
        return jsonify({'ok': False, 'error': 'هذه الطاولة مرتبطة بطلب مفتوح بالفعل'}), 409
    totals, totals_error = dine_in_totals(data, payload)
    if totals_error:
        return jsonify({'ok': False, 'error': totals_error}), 400
    discount_total = round_money(totals['subtotal'] - totals['total'])
    needs_approval, _ = manager_approval_required(data, max(totals['discount_pct'], effective_discount_pct(totals['subtotal'], discount_total)), discount_total)
    approval_record = None
    if needs_approval:
        approval_record, approval_error = verify_manager_approval(data, payload, 'خصم طلب صالة من تطبيق النادل', discount_total)
        if approval_error:
            return approval_error
    now = datetime.now().isoformat()
    session_row = {'id': 'DINE-' + uuid.uuid4().hex[:10].upper(), 'status': 'open', 'table_id': str(table['id']), 'table_name': table['name'], **totals, 'note': str(payload.get('note', ''))[:500], 'customer': str(payload.get('customer', ''))[:120], 'kitchen_status': 'new', 'opened_by': waiter['username'], 'created_at': now, 'updated_at': now}
    if approval_record:
        approval_record['reference_id'] = session_row['id']
        session_row['manager_approval'] = approval_record
    data.setdefault('dine_in_sessions', []).append(session_row)
    table['status'] = 'busy'; table['active_session_id'] = session_row['id']; table['active_since'] = now
    save(data); backup()
    return jsonify({'ok': True, 'session': dine_in_session_view(session_row)}), 201


@app.route('/api/mobile/dine-in/sessions/<session_id>', methods=['GET', 'PUT', 'OPTIONS'])
def mobile_dine_in_session_detail(session_id):
    if request.method == 'OPTIONS':
        return ('', 204)
    data, waiter, error = mobile_auth_error()
    if error:
        return error
    session_row = find_dine_in_session(data, session_id)
    if not session_row:
        return jsonify({'ok': False, 'error': 'طلب الصالة غير موجود'}), 404
    if request.method == 'GET':
        return jsonify({'ok': True, 'session': dine_in_session_view(session_row)})
    if session_row.get('status') != 'open':
        return jsonify({'ok': False, 'error': 'لا يمكن تعديل طلب مغلق'}), 409
    payload = request.get_json(silent=True) or {}
    totals, totals_error = dine_in_totals(data, payload)
    if totals_error:
        return jsonify({'ok': False, 'error': totals_error}), 400
    discount_total = round_money(totals['subtotal'] - totals['total'])
    needs_approval, _ = manager_approval_required(data, max(totals['discount_pct'], effective_discount_pct(totals['subtotal'], discount_total)), discount_total)
    approval_record = None
    if needs_approval:
        approval_record, approval_error = verify_manager_approval(data, payload, 'تعديل خصم طلب صالة من تطبيق النادل', discount_total, session_id)
        if approval_error:
            return approval_error
    session_row.update(totals)
    if approval_record:
        approval_record['reference_id'] = session_id
        session_row['manager_approval'] = approval_record
    session_row['note'] = str(payload.get('note', ''))[:500]
    session_row['customer'] = str(payload.get('customer', ''))[:120]
    session_row['updated_at'] = datetime.now().isoformat(); session_row['updated_by'] = waiter['username']; session_row['kitchen_status'] = 'new'
    save(data); backup()
    return jsonify({'ok': True, 'session': dine_in_session_view(session_row)})


@app.route('/api/mobile/dine-in/sessions/<session_id>/served', methods=['POST', 'OPTIONS'])
def mobile_mark_dine_in_served(session_id):
    if request.method == 'OPTIONS':
        return ('', 204)
    data, waiter, error = mobile_auth_error()
    if error:
        return error
    session_row = find_dine_in_session(data, session_id)
    if not session_row or session_row.get('status') != 'open':
        return jsonify({'ok': False, 'error': 'طلب الصالة المفتوح غير موجود'}), 404
    if session_row.get('kitchen_status') != 'ready':
        return jsonify({'ok': False, 'error': 'لا يمكن تأكيد التقديم قبل جاهزية المطبخ'}), 409
    session_row['kitchen_status'] = 'served'; session_row['updated_at'] = datetime.now().isoformat(); session_row['served_by'] = waiter['username']
    save(data); backup()
    return jsonify({'ok': True, 'session': dine_in_session_view(session_row)})


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
    discount_total = round_money(totals['subtotal'] - totals['total'])
    approval_record = None
    needs_approval, _ = manager_approval_required(data, max(totals['discount_pct'], effective_discount_pct(totals['subtotal'], discount_total)), discount_total)
    if needs_approval:
        approval_record, approval_error = verify_manager_approval(data, payload, 'خصم طلب صالة', discount_total)
        if approval_error:
            return approval_error
    kitchen_release = str(payload.get('kitchen_release', 'now') or 'now')
    if kitchen_release not in {'now', 'later'}:
        return jsonify({'ok': False, 'error': 'خيار إطلاق المطبخ غير صالح'}), 400
    now = datetime.now().isoformat()
    session_row = {
        'id': 'DINE-' + uuid.uuid4().hex[:10].upper(), 'status': 'open',
        'table_id': str(table['id']), 'table_name': table['name'], **totals,
        'note': str(payload.get('note', ''))[:500], 'customer': str(payload.get('customer', ''))[:120],
        'kitchen_status': 'held' if kitchen_release == 'later' else 'new', 'kitchen_release': kitchen_release,
        'opened_by': session.get('username', 'غير محدد'),
        'created_at': now, 'updated_at': now
    }
    if approval_record:
        approval_record['reference_id'] = session_row['id']; session_row['manager_approval'] = approval_record
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
    discount_total = round_money(totals['subtotal'] - totals['total'])
    needs_approval, _ = manager_approval_required(data, max(totals['discount_pct'], effective_discount_pct(totals['subtotal'], discount_total)), discount_total)
    if needs_approval:
        approval_record, approval_error = verify_manager_approval(data, payload, 'تعديل خصم طلب صالة', discount_total, session_id)
        if approval_error:
            return approval_error
        session_row['manager_approval'] = approval_record
    session_row.update(totals)
    session_row['note'] = str(payload.get('note', ''))[:500]
    session_row['customer'] = str(payload.get('customer', ''))[:120]
    kitchen_release = str(payload.get('kitchen_release', session_row.get('kitchen_release', 'now')) or 'now')
    if kitchen_release not in {'now', 'later'}:
        return jsonify({'ok': False, 'error': 'خيار إطلاق المطبخ غير صالح'}), 400
    if session_row.get('kitchen_status') in {'new', 'held'}:
        session_row['kitchen_release'] = kitchen_release
        session_row['kitchen_status'] = 'held' if kitchen_release == 'later' else 'new'
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
    total_discount = round_money(Decimal(str(session_row.get('subtotal', 0) or 0)) - Decimal(str(session_row.get('total', 0) or 0)))
    needs_approval, _ = manager_approval_required(data, max(round_money(session_row.get('discount_pct', 0) or 0), effective_discount_pct(session_row.get('subtotal', 0), total_discount)), total_discount)
    if needs_approval and not session_row.get('manager_approval'):
        approval_record, approval_error = verify_manager_approval(data, payload, 'خصم طلب صالة عند الدفع', total_discount, session_id)
        if approval_error:
            return approval_error
        session_row['manager_approval'] = approval_record
    payment_data, payment_error = normalize_payment(session_row.get('total', 0), payload)
    if payment_error:
        return jsonify({'ok': False, 'error': payment_error}), 400
    now = datetime.now().isoformat()
    order = {
        'id': next_order_id(data), 'timestamp': now, 'items': session_row['items'],
        'subtotal': session_row['subtotal'], 'discount_pct': session_row['discount_pct'], 'discount_amount': session_row['discount_amount'],
        'discount_total': session_row.get('discount_total', round_money(session_row['subtotal'] - session_row['total'])),
        'total': session_row['total'], 'type': 'صالة', 'note': session_row.get('note', ''),
        'customer': session_row.get('customer', ''), 'table': session_row.get('table_name', ''),
        'table_id': session_row.get('table_id'), 'cashier_name': session.get('username', 'غير محدد'),
        'kitchen_status': session_row.get('kitchen_status', 'new'), 'kitchen_release': session_row.get('kitchen_release', 'now'),
        'dine_in_session_id': session_row['id'], **payment_data
    }
    if session_row.get('manager_approval'):
        order['manager_approval'] = session_row['manager_approval']
    snap = currency_snapshot(data, payload)
    order['currency'] = snap['currency']; order['exchange_rate'] = snap['exchange_rate']
    data.setdefault('orders', []).append(order)
    if payment_data.get('cash_amount', 0):
        record_cash_movement(data, 'in', payment_data['cash_amount'], 'مبيعات كاشير قيصر',
                             channel='cash', reference_type='order', reference_id=order['id'],
                             note='فاتورة صالة ' + str(order['id']))
    if payment_data.get('card_amount', 0):
        record_cash_movement(data, 'in', payment_data['card_amount'], 'مبيعات كاشير قيصر',
                             channel='card', reference_type='order', reference_id=order['id'],
                             note='فاتورة صالة ' + str(order['id']))
    consume_inventory_for_order(data, order['items'], order['id'])
    session_row['status'] = 'closed'; session_row['closed_at'] = now; session_row['closed_order_id'] = order['id']
    table = find_table(data, session_row.get('table_id'))
    if table:
        table['status'] = 'free'; table.pop('active_session_id', None); table.pop('active_since', None)
    # كما في البيع المباشر، ثبّت فاتورة الصالة قبل أول خرج للطابعة أو الدرج.
    save(data, [order['id']]); backup()
    receipt_print = queue_thermal_print(data, order, 'receipt')
    kitchen_print = queue_thermal_print(data, order, 'kitchen')
    order['print_status'] = {'receipt': receipt_print, 'kitchen': kitchen_print}
    drawer_result = maybe_auto_open_cash_drawer(data, order, payment_data.get('cash_amount', 0))
    if drawer_result:
        order['cash_drawer_status'] = drawer_result
    save(data, [order['id']]); backup()
    return jsonify({'ok': True, 'id': order['id'], 'total': order['total'], 'order': order, 'print': {'receipt': receipt_print, 'kitchen': kitchen_print}, 'drawer': drawer_result})


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
    def with_station_routes(row):
        view = dict(row)
        station_items = {}
        for item in view.get('items', []):
            station = str(item.get('kitchen_station', 'main') or 'main')
            if station not in KITCHEN_STATION_LABELS:
                station = 'main'
            station_items.setdefault(station, []).append(item)
        view['station_items'] = station_items
        view['stations'] = [{'key': key, 'label': KITCHEN_STATION_LABELS[key], 'items': len(items)} for key, items in station_items.items()]
        return view
    return jsonify([with_station_routes(row) for row in paid_orders + open_sessions])


@app.route('/api/ready-orders', methods=['GET'])
def ready_orders():
    """يعيد الطلبات الجاهزة للسفري والدليفري دون بيانات مالية حساسة لشاشة الانتظار المحلية."""
    data = load()
    rows = []
    for order in data.get('orders', []):
        if order.get('voided') or order.get('kitchen_status') != 'ready' or order.get('type') not in {'سفري', 'ديليفري'}:
            continue
        rows.append({'id': order.get('id'), 'type': order.get('type'), 'customer': order.get('customer', ''),
                     'timestamp': order.get('timestamp', ''), 'driver_name': order.get('driver_name', ''),
                     'delivery_status': order.get('delivery_status', '')})
    return jsonify(rows)


@app.route('/api/delivery/drivers', methods=['GET', 'POST'])
def delivery_drivers():
    if not has_role('manager', 'supervisor'):
        return permission_error()
    data = load()
    if request.method == 'GET':
        return jsonify(data.get('delivery_drivers', []))
    payload = request.get_json(silent=True) or {}
    name = str(payload.get('name', '')).strip()[:100]
    phone = str(payload.get('phone', '')).strip()[:40]
    if len(name) < 2:
        return jsonify({'ok': False, 'error': 'اسم السائق مطلوب'}), 400
    driver = {'id': uuid.uuid4().hex[:8], 'name': name, 'phone': phone, 'status': 'available', 'created_at': datetime.now().isoformat()}
    data.setdefault('delivery_drivers', []).append(driver); save(data); backup()
    return jsonify({'ok': True, 'driver': driver})


@app.route('/api/delivery/orders', methods=['GET'])
def delivery_orders():
    if not has_role('manager', 'supervisor', 'cashier'):
        return permission_error()
    data = load(); rows = []
    for order in data.get('orders', []):
        if order.get('type') != 'ديليفري' or order.get('voided') or order.get('delivery_status') == 'delivered':
            continue
        rows.append({'id': order.get('id'), 'customer': order.get('customer', ''), 'timestamp': order.get('timestamp', ''),
                     'kitchen_status': order.get('kitchen_status', 'new'), 'delivery_status': order.get('delivery_status', 'pending'),
                     'driver_id': order.get('driver_id', ''), 'driver_name': order.get('driver_name', '')})
    return jsonify(rows)


@app.route('/api/delivery/orders/<order_id>', methods=['POST'])
def update_delivery_order(order_id):
    if not has_role('manager', 'supervisor', 'cashier'):
        return permission_error()
    data = load(); payload = request.get_json(silent=True) or {}
    order = next((row for row in data.get('orders', []) if str(row.get('id')) == str(order_id) and row.get('type') == 'ديليفري'), None)
    if not order:
        return jsonify({'ok': False, 'error': 'طلب الدليفري غير موجود'}), 404
    status = str(payload.get('status', order.get('delivery_status', 'pending')) or 'pending')
    if status not in {'pending', 'assigned', 'out_for_delivery', 'delivered'}:
        return jsonify({'ok': False, 'error': 'حالة التوصيل غير صالحة'}), 400
    if 'driver_id' in payload:
        driver = next((row for row in data.get('delivery_drivers', []) if str(row.get('id')) == str(payload.get('driver_id'))), None)
        if not driver:
            return jsonify({'ok': False, 'error': 'السائق غير موجود'}), 404
        order['driver_id'] = driver['id']; order['driver_name'] = driver['name']; status = 'assigned' if status == 'pending' else status
    order['delivery_status'] = status; order['delivery_updated_at'] = datetime.now().isoformat(); order['delivery_updated_by'] = session.get('username', 'unknown')
    save(data, [order['id']]); backup()
    return jsonify({'ok': True, 'order': order})


@app.route('/api/dashboard/daily', methods=['GET'])
def daily_dashboard():
    if not has_role('manager', 'supervisor'):
        return permission_error()
    data = load(); today = datetime.now().strftime('%Y-%m-%d')
    # يشمل الطلبات المؤرشفة اليوم (بعد تصفير العداد) حتى لا تنقص مبيعات اليوم الفعلية بعد التصفير.
    orders = _today_orders(data)
    live_today_orders = [row for row in data.get('orders', []) if not row.get('voided') and str(row.get('timestamp', row.get('date', '')))[:10] == today]
    kitchen_active = [row for row in live_today_orders if row.get('kitchen_status', 'new') != 'served']
    stock_rows = data.get('inventory', [])
    low_stock = [row for row in stock_rows if float(row.get('quantity', row.get('stock', 0)) or 0) <= float(row.get('reorder_point', row.get('min_stock', 0)) or 0)]
    attendance = attendance_rows(data, today, today)
    drivers = data.get('delivery_drivers', [])
    total_sales = round(sum(float(row.get('total', 0) or 0) for row in orders), 2)
    prep_totals = {}
    for row in data.get('kitchen_prep_log', []):
        if str(row.get('ready_at', ''))[:10] != today:
            continue
        station = str(row.get('station', 'main'))
        entry = prep_totals.setdefault(station, {'station': station, 'label': KITCHEN_STATION_LABELS.get(station, station), 'orders': 0, 'minutes_total': 0})
        entry['orders'] += 1; entry['minutes_total'] += max(0, int(row.get('minutes', 0) or 0))
    prep_averages = [{**entry, 'average_minutes': round(entry['minutes_total'] / entry['orders'], 1)} for entry in prep_totals.values()]
    return jsonify({'date': today, 'sales': total_sales, 'orders': len(orders),
                    'average_ticket': round(total_sales / len(orders), 2) if orders else 0,
                    'kitchen_active': len(kitchen_active), 'kitchen_ready': sum(1 for row in kitchen_active if row.get('kitchen_status') == 'ready'),
                    'low_stock': [{'name': row.get('name', ''), 'quantity': row.get('quantity', row.get('stock', 0))} for row in low_stock[:8]],
                    'staff_present': sum(1 for row in attendance if not row.get('clock_out')),
                    'delivery_open': sum(1 for row in orders if row.get('type') == 'ديليفري' and row.get('delivery_status') != 'delivered'),
                    'drivers_available': sum(1 for row in drivers if row.get('status', 'available') == 'available'),
                    'print_errors': len(unresolved_print_failures(data)), 'prep_averages': prep_averages})



@app.route('/api/dashboard/counters', methods=['GET'])
def dashboard_counters():
    """عدادات موحّدة؛ الكاشير قيصر يرى الحد التشغيلي فقط، والإدارة ترى الصورة الأوسع.
    ملاحظة: 'orders' يعكس الطلبات الحيّة منذ آخر تصفير للعداد (يُتوقع أن يصفر معه)،
    أما 'sales_today' فهو إجمالي مبيعات اليوم الفعلي ويجب ألا يتأثر بتصفير العداد،
    لذلك يُحسب من الطلبات الحالية + المؤرشفة اليوم معاً عبر _today_orders()."""
    data = load()
    today_orders = _today_orders(data)
    # تعرض شاشة الكاشير أرقام اليوم المتاحة للتشغيل، لا بقايا الطلبات
    # القديمة الموجودة في الوردية أو في snapshot الحالي فقط.
    active_orders = today_orders
    payload = {
        'role': session.get('role'),
        'orders': len(active_orders),
        'ready_orders': sum(1 for row in active_orders if row.get('kitchen_status') == 'ready'),
        'sales_today': round(sum(float(row.get('total', 0) or 0) for row in today_orders), 2),
        'updated_at': datetime.now().isoformat(),
    }
    if session.get('role') in {'manager', 'supervisor'}:
        payload.update({
            'delivery_open': sum(1 for row in active_orders if row.get('type') == 'ديليفري' and row.get('delivery_status') != 'delivered'),
            'print_errors': len(unresolved_print_failures(data)),
            'low_stock': len(inventory_alerts(data)),
        })
    return jsonify(payload)


def record_kitchen_ready_metrics(data, row, public_order_id):
    """يسجل مدة التحضير لكل محطة مرة واحدة عندما يصل الطلب إلى جاهز."""
    if row.get('kitchen_ready_recorded_at'):
        return
    ready_at = datetime.now()
    started_at = str(row.get('preparation_started_at') or row.get('timestamp') or row.get('created_at') or ready_at.isoformat())
    try:
        minutes = max(0, int((ready_at - datetime.fromisoformat(started_at)).total_seconds() // 60))
    except (TypeError, ValueError):
        minutes = 0
    stations = set()
    for item in row.get('items', []):
        station = str(item.get('kitchen_station', 'main') or 'main')
        stations.add(station if station in KITCHEN_STATION_LABELS else 'main')
    for station in stations or {'main'}:
        data.setdefault('kitchen_prep_log', []).append({'id': uuid.uuid4().hex[:12], 'order_id': str(public_order_id), 'station': station,
                                                         'started_at': started_at, 'ready_at': ready_at.isoformat(), 'minutes': minutes})
    data['kitchen_prep_log'] = data.get('kitchen_prep_log', [])[-1000:]
    row['kitchen_ready_recorded_at'] = ready_at.isoformat()


@app.route('/api/kitchen/orders/<order_id>/status', methods=['POST'])
def kitchen_status(order_id):
    data = load(); payload = request.get_json(silent=True) or {}; status = payload.get('status', 'new')
    if status not in KITCHEN_STATUSES:
        return jsonify({'ok': False, 'error': 'حالة غير صالحة'}), 400
    if str(order_id).startswith('SESSION-'):
        session_row = find_dine_in_session(data, str(order_id)[8:])
        if session_row and session_row.get('status') == 'open':
            prior_status = session_row.get('kitchen_status', 'new')
            if prior_status == 'held' and status != 'new':
                return jsonify({'ok': False, 'error': 'أطلق الطلب المؤجل أولاً قبل بدء التحضير'}), 409
            session_row['kitchen_status'] = status; session_row['updated_at'] = datetime.now().isoformat()
            if prior_status == 'held' and status == 'new':
                session_row['kitchen_release'] = 'now'; session_row['kitchen_released_at'] = datetime.now().isoformat()
            if status == 'preparing' and prior_status != 'preparing':
                session_row['preparation_started_at'] = datetime.now().isoformat()
            if status == 'ready' and prior_status != 'ready':
                record_kitchen_ready_metrics(data, session_row, 'SESSION-' + str(session_row['id']))
            save(data)
            return jsonify({'ok': True, 'status': status, 'dine_in_session': True})
    for order in data.get('orders', []):
        if str(order.get('id')) == str(order_id):
            prior_status = order.get('kitchen_status', 'new')
            if prior_status == 'held' and status != 'new':
                return jsonify({'ok': False, 'error': 'أطلق الطلب المؤجل أولاً قبل بدء التحضير'}), 409
            order['kitchen_status'] = status
            released_print = None
            if prior_status == 'held' and status == 'new':
                order['kitchen_release'] = 'now'; order['kitchen_released_at'] = datetime.now().isoformat()
                released_print = queue_thermal_print(data, order, 'kitchen')
                order.setdefault('print_status', {})['kitchen'] = released_print
            if status == 'preparing' and prior_status != 'preparing':
                order['preparation_started_at'] = datetime.now().isoformat()
            if status == 'ready' and prior_status != 'ready':
                record_kitchen_ready_metrics(data, order, order.get('id'))
            save(data, [order['id']]); return jsonify({'ok': True, 'status': status, 'print': released_print})
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
    payload = request.get_json(silent=True) or {}; code = payload.get('code', '').strip(); balance = as_money(payload.get('balance'), 0)
    if not code or balance <= 0: return jsonify({'ok': False, 'error': 'بيانات البطاقة غير صالحة'}), 400
    card = {'code': code, 'balance': balance, 'created_at': datetime.now().isoformat()}; _store(data, 'gift_cards').append(card); save(data); return jsonify({'ok': True, 'card': card})

@app.route('/api/qr/menu', methods=['GET'])
def qr_menu():
    data = load(); return jsonify({'restaurant': data.get('settings', {}).get('restaurant', {}), 'menu': data.get('menu', {})})

@app.route('/api/sync/status', methods=['GET'])
def sync_status():
    """يعيد بصمة البيانات القابلة للمزامنة للشاشات المحلية دون كشف بيانات حساسة."""
    data = load()
    menu_payload = json.dumps(data.get('menu', {}), ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    settings_payload = json.dumps({
        'restaurant': data.get('settings', {}).get('restaurant', {}),
        'currency': data.get('settings', {}).get('currency', 'SYP'),
    }, ensure_ascii=False, sort_keys=True, separators=(',', ':'))
    return jsonify({
        'mode': 'local',
        'online': False,
        'pending': len(data.get('sync_queue', [])),
        'last_sync': data.get('settings', {}).get('last_sync'),
        'menu_revision': hashlib.sha256(menu_payload.encode('utf-8')).hexdigest()[:16],
        'settings_revision': hashlib.sha256(settings_payload.encode('utf-8')).hexdigest()[:16],
        'updated_at': datetime.now().isoformat(),
    })

if __name__ == '__main__':
    print('='*50)
    print('كاشير قيصر قيصر')
    print(f' Version: {CURRENT_VERSION}')
    print(f'  Vault: {VAULT_DIR}')
    print('='*50)

    start_flask()
