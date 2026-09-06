#!/usr/bin/env python3
"""Create a clean standalone client copy of CAESAR Al-CAESAR.
Usage: python Create_Restaurant_Copy.py "Restaurant Name" /path/to/output [LICENSE-ID]
Run this only on the vendor/master copy, never on a live restaurant copy.
"""
import json, shutil, sys
from pathlib import Path

if len(sys.argv) < 3:
    raise SystemExit('Usage: python Create_Restaurant_Copy.py "Restaurant Name" /path/to/output [LICENSE-ID]')
restaurant, output = sys.argv[1].strip(), Path(sys.argv[2]).expanduser().resolve()
license_id = sys.argv[3].strip() if len(sys.argv) > 3 else ''
root = Path(__file__).resolve().parent
if not restaurant: raise SystemExit('Restaurant name is required.')
if output.exists(): raise SystemExit(f'Output already exists: {output}')
def ignore_commercial_artifacts(directory, names):
    ignored = set()
    for name in names:
        low = name.lower()
        if low in {'.git', '__pycache__', 'data_vault', 'deliveries'} or low.endswith(('.pyc', '.log')) or low.startswith('qa_') or (low.startswith('acceptance_') and low.endswith(('.py', '.json', '.log'))) or low == 'ui_redesign_notes.md':
            ignored.add(name)
        if low.endswith('.zip') and ('caesar' in low or 'caesar' in low):
            ignored.add(name)
    return ignored

ignore = ignore_commercial_artifacts
shutil.copytree(root, output, ignore=ignore)

def clean_data(path):
    data = json.loads(path.read_text(encoding='utf-8'))
    settings = data.setdefault('settings', {})
    settings['restaurant'] = {}
    settings['users'] = []
    settings['commercial'] = {'setup_completed': False, 'template': True, 'template_restaurant_name': restaurant, 'preset_license_id': license_id}
    for key in (
        'orders', 'orders_archive', 'debts', 'customers', 'expenses', 'audit_log', 'shifts',
        'gift_cards', 'sync_queue', 'cash_movements', 'cashbook', 'supplier_payments',
        'inventory_movements', 'dine_in_sessions', 'mobile_tokens', 'print_jobs', 'print_log'
    ):
        data[key] = []
    tables = data.get('tables', [])
    if isinstance(tables, dict):
        tables = list(tables.values())
    if not isinstance(tables, list):
        tables = []
    for table in tables:
        if isinstance(table, dict):
            table['status'] = 'free'
            for transient_key in ('order_id', 'active_session', 'active_session_id', 'active_since', 'kitchen_status'):
                table.pop(transient_key, None)
    data['tables'] = tables
    printer = settings.setdefault('printer', {})
    printer.pop('logo_data', None)
    printer['logo_caption'] = ''
    printer['auto_print_receipt'] = False
    printer['auto_print_kitchen'] = False
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

for filename in ('data_backup.json','factory_data.json'):
    template_file = output / 'app' / filename
    if template_file.exists():
        clean_data(template_file)
(output/'CLIENT_SETUP.txt').write_text(
    f'نسخة مستقلة للمطعم: {restaurant}\n\n'
    '1. شغّل Start.bat (أو اختصار سطح المكتب الذي ينشئه Install_CAESAR_Desktop_Icon.bat).\n'
    '2. أكمل معالج الإعداد الأولي وأنشئ حساب المدير.\n'
    '3. لا تنسخ أي ملفات بيانات تشغيلية بين العملاء.\n'
    '4. اقرأ دليل_التشغيل_الكامل_AR.md وتقرير DELIVERY_QA_REPORT_AR.md قبل أول وردية.\n'
    '5. لنسخة USB شغّل USB_Start.bat من جذر الفلاشة، ثم راجع تشغيل_من_USB_AR.md.\n'
    '6. لتشغيل تطبيق النادل استخدم app/Start_LAN_Mode.bat ثم أدخل عنوان IP:8080 وحساب النادل في التطبيق.\n', encoding='utf-8')
print(f'CLIENT_COPY_CREATED: {output}')
