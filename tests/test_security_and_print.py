import json
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

APP_DIR = Path(__file__).resolve().parents[1] / 'app'
sys.path.insert(0, str(APP_DIR))
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

    def test_silent_print_submits_to_windows_spooler_without_browser_print(self):
        with patch.object(server.sys, 'platform', 'win32'), patch.object(
            server.subprocess, 'run', return_value=SimpleNamespace(returncode=0, stdout='', stderr='')
        ) as run:
            result = server.submit_silent_windows_print('Thermal 80', 'فاتورة اختبار', 'CAESAR Receipt TEST')
        self.assertTrue(result['ok'])
        self.assertEqual(result['status'], 'submitted')
        self.assertTrue(result['job_id'])
        self.assertTrue(run.called)
        index_content = (APP_DIR / 'index.html').read_text(encoding='utf-8')
        self.assertNotIn('window.print', index_content)
        self.assertNotIn('window.open', index_content)

    def test_cashier_retries_a_failed_receipt_without_manager_permission(self):
        self.login('cashier', 'cashier-pass')
        data = server.load()
        data['settings']['printer'] = {'auto_print_receipt': True, 'auto_print_kitchen': False, 'printer_name': 'Thermal 80'}
        server.save(data)
        failed = {'ok': False, 'status': 'failed', 'message': 'الطابعة غير متاحة'}
        with patch.object(server.sys, 'platform', 'win32'), patch.object(server, 'submit_silent_windows_print', return_value=failed):
            first = self.client.post('/api/orders', json={
                'items': [{'product_id': 1, 'quantity': 1}], 'payment': 'نقدي', 'type': 'سفري', 'kitchen_release': 'now'
            })
        self.assertEqual(first.status_code, 200)
        order_id = first.get_json()['id']
        submitted = {'ok': True, 'status': 'submitted', 'message': 'تم إرسال الإيصال إلى طابور الطباعة المحلي', 'job_id': 'job-001'}
        with patch.object(server.sys, 'platform', 'win32'), patch.object(server, 'submit_silent_windows_print', return_value=submitted):
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
