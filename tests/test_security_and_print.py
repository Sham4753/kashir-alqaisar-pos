import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

APP_DIR = Path(__file__).resolve().parents[1] / 'app'
sys.path.insert(0, str(APP_DIR))
os.environ.setdefault('CAESAR_LICENSE_SECRET', 'test-only-secret-for-caesar-pos-tests-2026-32chars')
import server  # noqa: E402


class SecurityAndPrintTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        vault = Path(self.temp.name)
        server.VAULT_DIR = str(vault)
        server.DATA_FILE = str(vault / 'data.json')
        server.FLASH_BACKUP = str(vault / 'data_backup.json')
        server.BACKUP_DIR = str(vault / 'backups')
        Path(server.BACKUP_DIR).mkdir(parents=True, exist_ok=True)
        fixture = {
            'menu': {'السندويشات': [{'id': 1, 'name': 'سندويش اختبار', 'price': 10, 'recipe': []}]},
            'orders': [], 'orders_archive': [], 'order_counter': 0, 'shifts': [], 'audit_log': [],
            'debts': [], 'customers': [], 'employees': [], 'materials': [], 'inventory': [],
            'settings': {
                'restaurant': {'name': 'مطعم الاختبار'},
                'commercial': {'setup_completed': True},
                'currency': 'SYP',
                'printer': {'auto_print_receipt': False, 'auto_print_kitchen': False, 'printer_name': ''},
                'users': [
                    {'id': 1, 'username': 'manager', 'password_hash': server.hash_password('manager-pass'), 'role': 'manager'},
                    {'id': 2, 'username': 'cashier', 'password_hash': server.hash_password('cashier-pass'), 'role': 'cashier'},
                    {'id': 3, 'username': 'supervisor', 'password_hash': server.hash_password('supervisor-pass'), 'role': 'supervisor'},
                ],
            },
        }
        fixture['settings']['commercial'].update({
            'machine_id': server.local_machine_id(),
            'license_id': server.license_number_for(server.local_machine_id()),
            'license_key': server.license_key_for(server.local_machine_id()),
        })
        Path(server.DATA_FILE).write_text(json.dumps(fixture, ensure_ascii=False), encoding='utf-8')
        server.app.config['TESTING'] = True
        self.client = server.app.test_client()

    def tearDown(self):
        server.PRINT_QUEUE.join()
        self.temp.cleanup()

    def login(self, username, password):
        return self.client.post('/api/auth/login', json={'username': username, 'password': password})

    def page_status(self, page_name):
        response = self.client.get('/' + page_name, follow_redirects=False)
        try:
            return response.status_code, response.headers.get('Location', '')
        finally:
            response.close()

    def test_cashier_completes_sale_without_manager_permission(self):
        self.assertEqual(self.login('cashier', 'cashier-pass').status_code, 200)
        response = self.client.post('/api/orders', json={
            'items': [{'product_id': 1, 'quantity': 2}], 'payment': 'نقدي', 'type': 'سفري', 'kitchen_release': 'now'
        })
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body['ok'])
        self.assertEqual(body['total'], 20)
        self.assertEqual(body['print']['receipt']['status'], 'disabled')

    def test_license_is_revalidated_when_machine_changes(self):
        self.login('cashier', 'cashier-pass')
        with patch.object(server, 'local_machine_id', return_value='DIFFERENT-MACHINE'):
            response = self.client.get('/api/menu')
        self.assertEqual(response.status_code, 423)
        self.assertIn('الترخيص', response.get_json()['error'])

    def test_operational_state_uses_wal_sqlite(self):
        server.load()
        conn = sqlite3.connect(str(Path(server.VAULT_DIR) / 'caesar.sqlite3'))
        try:
            self.assertEqual(conn.execute('PRAGMA journal_mode').fetchone()[0].lower(), 'wal')
            self.assertIsNotNone(conn.execute('SELECT payload FROM app_state WHERE id=1').fetchone())
        finally:
            conn.close()

    def test_cashier_cannot_open_manager_pages_or_printer_settings(self):
        self.login('cashier', 'cashier-pass')
        self.assertEqual(self.client.get('/api/printer/settings').status_code, 403)
        self.assertEqual(self.client.post('/api/printer/settings', json={'printer_name': 'Local'}).status_code, 403)
        manager_pages = (
            '/settings.html', '/printer_settings.html', '/menu_manager.html',
            '/analytics.html', '/manager_ops.html', '/expenses.html',
        )
        for page_name in manager_pages:
            with self.subTest(page=page_name):
                status, location = self.page_status(page_name.lstrip('/'))
                self.assertEqual(status, 302)
                self.assertIn('/login.html', location)

    def test_locked_screen_allows_authorized_cashier_or_manager_to_unlock(self):
        self.login('cashier', 'cashier-pass')
        self.assertEqual(self.client.post('/api/auth/lock', json={}).status_code, 200)
        locked_sale = self.client.post('/api/orders', json={
            'items': [{'product_id': 1, 'quantity': 1}], 'payment': 'نقدي', 'type': 'سفري'
        })
        self.assertEqual(locked_sale.status_code, 423)
        cashier_unlock = self.client.post('/api/auth/unlock', json={'username': 'cashier', 'password': 'cashier-pass'})
        self.assertEqual(cashier_unlock.status_code, 200)
        self.assertEqual(cashier_unlock.get_json()['role'], 'cashier')
        self.assertFalse(cashier_unlock.get_json()['locked'])
        self.assertFalse(self.client.get('/api/auth/me').get_json()['locked'])

        self.assertEqual(self.client.post('/api/auth/lock', json={}).status_code, 200)
        manager_unlock = self.client.post('/api/auth/unlock', json={'username': 'manager', 'password': 'manager-pass'})
        self.assertEqual(manager_unlock.status_code, 200)
        self.assertEqual(manager_unlock.get_json()['role'], 'manager')

    def test_silent_print_submits_arabic_raster_to_windows_spooler_without_browser_print(self):
        captured = {}
        def fake_raw(name, payload, document_name='CAESAR Raw Command'):
            captured['name'], captured['payload'], captured['document'] = name, payload, document_name
            return {'ok': True, 'status': 'submitted', 'job_id': 'raw-001'}
        with patch.object(server.sys, 'platform', 'win32'), patch.object(server, 'submit_raw_windows_bytes', side_effect=fake_raw):
            result = server.submit_silent_windows_print('Thermal 80', 'فاتورة اختبار', 'CAESAR Receipt TEST')
        self.assertTrue(result['ok'])
        self.assertEqual(result['status'], 'submitted')
        self.assertTrue(result['job_id'])
        self.assertTrue(captured['payload'].startswith(b'\x1b\x40\x1d\x76\x30'))
        self.assertIn(b'\x1d\x56\x00', captured['payload'])
        index_content = (APP_DIR / 'index.html').read_text(encoding='utf-8')
        self.assertNotIn('window.print', index_content)
        self.assertNotIn('window.open', index_content)

    def test_printer_preserves_explicit_orientation_and_roll_defaults_to_portrait(self):
        self.login('manager', 'manager-pass')
        data = server.load()
        data['settings']['printer'] = {'paper_orientation': 'portrait', 'printer_name': 'Thermal 80'}
        server.save(data)
        self.assertEqual(self.client.get('/api/printer/settings').get_json()['paper_orientation'], 'portrait')
        saved = self.client.post('/api/printer/settings', json={'paper_orientation': 'portrait', 'printer_name': 'Thermal 80'})
        self.assertEqual(saved.status_code, 200)
        self.assertEqual(server.load()['settings']['printer']['paper_orientation'], 'portrait')

    def test_receipt_design_blocks_and_logo_are_present_in_thermal_output(self):
        from PIL import Image
        from io import BytesIO
        import base64
        logo = Image.new('RGB', (24, 12), (0, 0, 0))
        buf = BytesIO(); logo.save(buf, format='PNG')
        logo_data = 'data:image/png;base64,' + base64.b64encode(buf.getvalue()).decode('ascii')
        data = server.load()
        data['settings']['restaurant'] = {'name': 'مطعم الاختبار'}
        data['settings']['printer'] = {
            'paper_width': 80, 'font_size': 'medium', 'logo_data': logo_data,
            'logo_size': 'medium', 'logo_alignment': 'center', 'receipt_header': 'إيصال مبيعات',
            'footer_text': 'شكرًا لزيارتكم', 'receipt_show_cashier': True,
            'receipt_show_order_type': True, 'receipt_layout': ['logo','header','details','items','totals','footer'],
            'cut_enabled': True, 'feed_before_cut': 3, 'cut_mode': 'full',
        }
        order = {'id': 'AR-1', 'timestamp': '2026-09-09 21:00', 'items': [{'name': 'شاورما عربي', 'quantity': 2}], 'total': 25000, 'payment': 'نقدي', 'type': 'سفري', 'cashier_name': 'أحمد'}
        text = server.thermal_receipt_text(data, order)
        plain = server.render_escpos_raster_payload_for_printer(text, data['settings']['printer'])
        no_logo = server.render_escpos_raster_payload_for_printer(text, {**data['settings']['printer'], 'logo_data': ''})
        self.assertIn('شاورما عربي', text)
        self.assertIn('شكرًا لزيارتكم', text)
        self.assertGreater(len(plain), len(no_logo))
        self.assertNotIn('شاورما'.encode('utf-8'), plain)
        self.assertIn(b'\x1d\x56\x00', plain)

    def test_print_test_uses_raster_path_not_raw_utf8(self):
        self.login('manager', 'manager-pass')
        data = server.load(); data['settings']['printer'] = {'printer_name': 'Thermal 80', 'paper_width': 80, 'connection_mode': 'windows'}; server.save(data)
        captured = {}
        def fake_submit(name, text, font_size, width, document, config):
            captured['text'], captured['payload'] = text, server.render_escpos_raster_payload_for_printer(text, {**config, 'paper_width': width, 'font_size': font_size})
            return {'ok': True, 'status': 'submitted', 'message': 'تم الاختبار'}
        with patch.object(server.sys, 'platform', 'win32'), patch.object(server, 'submit_silent_thermal_print', side_effect=fake_submit):
            response = self.client.post('/api/printer/test', json={'paper_width': 80, 'receipt_header': 'اختبار عربي'})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['ok'])
        self.assertIn('تمت الطباعة العربية بنجاح', captured['text'])
        self.assertNotIn('تمت'.encode('utf-8'), captured['payload'])
        self.assertIn(b'\x1d\x56\x00', captured['payload'])

    def test_arabic_raster_payload_contains_cut_command_and_uses_wide_paper(self):
        payload = server.render_escpos_raster_payload(
            'إيصال مبيعات\nتمت الطباعة العربية بنجاح',
            {'paper_width': 80, 'font_size': 'medium', 'cut_enabled': True, 'feed_before_cut': 3, 'cut_mode': 'full'},
        )
        self.assertTrue(payload.startswith(b'\x1b\x40\x1d\x76\x30'))
        self.assertIn(b'\x1d\x56\x00', payload)
        self.assertGreater(len(payload), 100)

    def test_bidi_control_marks_are_removed_before_font_rendering(self):
        source = (APP_DIR / 'server.py').read_text(encoding='utf-8')
        self.assertIn("get_display(arabic_reshaper.reshape(value)).replace('\\u200e', '').replace('\\u200f', '')", source)

    def test_feature_settings_are_visible_and_persist_for_manager(self):
        self.login('manager', 'manager-pass')
        features = self.client.get('/api/settings/features')
        self.assertEqual(features.status_code, 200)
        self.assertTrue(features.get_json()['kitchen'])
        saved = self.client.post('/api/settings/features', json={'kitchen': False, 'tables': True, 'delivery': True, 'customers': True, 'mobile': True, 'reports': True})
        self.assertEqual(saved.status_code, 200)
        self.assertFalse(self.client.get('/api/settings/features').get_json()['kitchen'])
        settings_html = (APP_DIR / 'settings.html').read_text(encoding='utf-8')
        self.assertIn('featureKitchen', settings_html)
        self.assertIn('saveFeatures', settings_html)

    def test_network_print_does_not_require_windows_printer_name(self):
        data = server.load()
        data['settings']['printer'] = {'connection_mode': 'network', 'network_host': '192.0.2.10', 'network_port': 9100, 'auto_print_receipt': True, 'printer_name': ''}
        server.save(data)
        with patch.object(server.sys, 'platform', 'win32'), patch.object(server, 'submit_network_raw_print', return_value={'ok': True, 'status': 'submitted', 'message': 'تم الإرسال'}):
            result = server.queue_thermal_print(server.load(), {'id': 'NET-1', 'items': [], 'total': 0}, 'receipt', wait=True)
        self.assertEqual(result['status'], 'submitted')

    def test_cashier_retries_a_failed_receipt_without_manager_permission(self):
        self.login('cashier', 'cashier-pass')
        data = server.load()
        data['settings']['printer'] = {'auto_print_receipt': True, 'auto_print_kitchen': False, 'printer_name': 'Thermal 80'}
        server.save(data)
        failed = {'ok': False, 'status': 'failed', 'message': 'الطابعة غير متاحة'}
        with patch.object(server.sys, 'platform', 'win32'), patch.object(server, 'submit_silent_thermal_print', return_value=failed):
            first = self.client.post('/api/orders', json={
                'items': [{'product_id': 1, 'quantity': 1}], 'payment': 'نقدي', 'type': 'سفري', 'kitchen_release': 'now'
            })
        self.assertEqual(first.status_code, 200)
        order_id = first.get_json()['id']
        submitted = {'ok': True, 'status': 'submitted', 'message': 'تم إرسال الإيصال إلى طابور الطباعة المحلي', 'job_id': 'job-001'}
        with patch.object(server.sys, 'platform', 'win32'), patch.object(server, 'submit_silent_thermal_print', return_value=submitted):
            retry = self.client.post(f'/api/printer/orders/{order_id}/retry', json={'type': 'receipt'})
        self.assertEqual(retry.status_code, 200)
        self.assertTrue(retry.get_json()['ok'])
        self.assertEqual(retry.get_json()['unresolved_count'], 0)

    def test_role_matrix_for_operational_and_sensitive_routes(self):
        self.login('cashier', 'cashier-pass')
        for endpoint in ('/api/menu', '/api/orders', '/api/kitchen/orders', '/api/tables', '/api/customers', '/api/dine-in/sessions', '/api/ready-orders', '/api/delivery/orders'):
            with self.subTest(role='cashier', endpoint=endpoint):
                self.assertEqual(self.client.get(endpoint).status_code, 200)
        for endpoint in ('/api/printer/settings', '/api/admin/audit-log', '/api/settings/lock'):
            with self.subTest(role='cashier', endpoint=endpoint):
                self.assertEqual(self.client.get(endpoint).status_code, 403)
        for endpoint, payload in (
            ('/api/settings/users', {'username': 'blocked', 'password': 'long-enough-password', 'role': 'cashier'}),
            ('/api/shifts/close', {'actual_cash': 0, 'reason': 'اختبار'}),
            ('/api/cash-drawer/open', {'reason': 'اختبار'}),
            ('/api/offers', {'name': 'عرض', 'value': 5}),
        ):
            with self.subTest(role='cashier', endpoint=endpoint):
                self.assertEqual(self.client.post(endpoint, json=payload).status_code, 403)

        self.login('supervisor', 'supervisor-pass')
        for endpoint in ('/api/menu', '/api/orders', '/api/kitchen/orders', '/api/tables', '/api/customers'):
            with self.subTest(role='supervisor', endpoint=endpoint):
                self.assertEqual(self.client.get(endpoint).status_code, 200)
        self.assertEqual(self.client.get('/api/printer/settings').status_code, 403)
        self.assertEqual(self.client.post('/api/settings/users', json={'username': 'blocked2', 'password': 'long-enough-password', 'role': 'cashier'}).status_code, 403)

        self.login('manager', 'manager-pass')
        self.assertEqual(self.client.get('/api/printer/settings').status_code, 200)
        self.assertEqual(self.client.get('/api/admin/audit-log').status_code, 200)
        self.assertEqual(self.client.post('/api/settings/lock', json={'enabled': True, 'timeout': 5}).status_code, 200)

    def test_cashier_handover_lists_each_cashier_and_manager_can_reset_counter(self):
        data = server.load()
        data['settings']['users'].extend([
            {'id': 4, 'username': 'cashier2', 'password_hash': server.hash_password('cashier2-pass'), 'role': 'cashier'},
            {'id': 5, 'username': 'cashier3', 'password_hash': server.hash_password('cashier3-pass'), 'role': 'cashier'},
        ])
        server.save(data)
        self.login('cashier', 'cashier-pass')
        sale = self.client.post('/api/orders', json={'items': [{'product_id': 1, 'quantity': 1}], 'payment': 'نقدي', 'type': 'سفري'})
        self.assertEqual(sale.status_code, 200)
        summaries = self.client.get('/api/shifts/cashiers')
        self.assertEqual(summaries.status_code, 200)
        self.assertEqual({row['cashier'] for row in summaries.get_json()}, {'cashier', 'cashier2', 'cashier3'})
        handover = self.client.post('/api/shifts/handover', json={'to_cashier': 'cashier2', 'actual_cash': 10})
        self.assertEqual(handover.status_code, 200)
        self.assertEqual(self.client.get('/api/shifts').get_json()[-1]['to_cashier'], 'cashier2')
        self.login('manager', 'manager-pass')
        data = server.load(); data['order_counter'] = 9; server.save(data)
        reset = self.client.post('/api/shifts/reset-counter', json={'confirmation': 'RESET_COUNTER'})
        self.assertEqual(reset.status_code, 200)
        self.assertEqual(server.load()['order_counter'], 0)

    def test_page_role_matrix_covers_all_registered_html_pages(self):
        operational_pages = ('index.html', 'orders_list.html', 'kitchen.html', 'tables.html', 'customers.html', 'delivery.html', 'waiting_screen.html', 'daily_guide.html', 'attendance.html', 'employees.html', 'raw_materials.html', 'mobile.html')
        supervisor_pages = ('dashboard.html', 'debts.html')
        manager_pages = ('settings.html', 'printer_settings.html', 'menu_manager.html', 'analytics.html', 'manager_ops.html', 'expenses.html')

        self.login('cashier', 'cashier-pass')
        for page_name in operational_pages:
            with self.subTest(role='cashier', page=page_name):
                self.assertEqual(self.page_status(page_name)[0], 200)
        for page_name in supervisor_pages + manager_pages:
            with self.subTest(role='cashier', denied_page=page_name):
                self.assertEqual(self.page_status(page_name)[0], 302)

        self.login('supervisor', 'supervisor-pass')
        for page_name in operational_pages + supervisor_pages:
            with self.subTest(role='supervisor', page=page_name):
                self.assertEqual(self.page_status(page_name)[0], 200)
        for page_name in manager_pages:
            with self.subTest(role='supervisor', denied_page=page_name):
                self.assertEqual(self.page_status(page_name)[0], 302)

        self.login('manager', 'manager-pass')
        for page_name in operational_pages + supervisor_pages + manager_pages:
            with self.subTest(role='manager', page=page_name):
                self.assertEqual(self.page_status(page_name)[0], 200)


if __name__ == '__main__':
    unittest.main()
