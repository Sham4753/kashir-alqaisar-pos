#!/usr/bin/env python3
"""Create a clean standalone client copy of Kashir Al-Qaisar.
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
        if low in {'__pycache__', 'data_vault', 'deliveries'} or low.endswith(('.pyc', '.log')) or low.startswith(('qa_', 'acceptance_')) or low == 'ui_redesign_notes.md':
            ignored.add(name)
        if low.endswith('.zip') and ('kashir' in low or 'qaisar' in low):
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
    for key in ('orders','orders_archive','debts','customers','expenses','audit_log','shifts','gift_cards','sync_queue'):
        data[key] = []
    tables = data.get('tables', [])
    if isinstance(tables, dict):
        tables = list(tables.values())
    if not isinstance(tables, list):
        tables = []
    for table in tables:
        if isinstance(table, dict):
            table['status'] = 'free'
            table.pop('order_id', None)
    data['tables'] = tables
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')

for filename in ('data_backup.json','factory_data.json'):
    clean_data(output/'app'/filename)
(output/'CLIENT_SETUP.txt').write_text(
    f'نسخة مستقلة للمطعم: {restaurant}\n\n'
    '1. شغّل QaisarCashier.exe.\n'
    '2. أكمل معالج الإعداد الأولي وأنشئ حساب المدير.\n'
    '3. لا تنسخ data_backup.json بين العملاء.\n'
    '4. لتشغيل الجوال استخدم app/Start_LAN_Mode.bat ثم إعدادات > ربط الجوال عبر QR.\n', encoding='utf-8')
print(f'CLIENT_COPY_CREATED: {output}')
