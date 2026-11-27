import json
import atexit
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

APP_DIR = Path(__file__).resolve().parents[1] / 'app'
sys.path.insert(0, str(APP_DIR))
TEST_VAULT = tempfile.TemporaryDirectory()
atexit.register(TEST_VAULT.cleanup)
os.environ['CAESAR_VAULT_DIR'] = TEST_VAULT.name
import server  # noqa: E402


class DailyItemsReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        vault = Path(self.temp.name)
        server.VAULT_DIR = str(vault)
        server.DATA_FILE = str(vault / 'data.json')
        server.DATABASE_FILE = str(vault / 'caesar.sqlite3')
        server.FLASH_BACKUP = str(vault / 'data_backup.json')
        server.BACKUP_DIR = str(vault / 'backups')
        server.COLD_ARCHIVE_DIR = str(vault / 'archive_cold')
        Path(server.BACKUP_DIR).mkdir(parents=True, exist_ok=True)
        Path(server.COLD_ARCHIVE_DIR).mkdir(parents=True, exist_ok=True)
        fixture = {
            'orders': [], 'orders_archive': [], 'order_counter': 0,
            'settings': {
                'restaurant': {'name': 'مطعم الاختبار'},
                'commercial': {'setup_completed': True},
                'currency': 'SYP',
                'printer': {
                    'connection_mode': 'network', 'network_host': '127.0.0.1', 'network_port': 9100,
                    'paper_width': 58, 'auto_print_receipt': False, 'auto_print_kitchen': False,
                },
                'users': [
                    {'username': 'manager', 'role': 'manager'},
                    {'username': 'cashier', 'role': 'cashier'},
                    {'username': 'supervisor', 'role': 'supervisor'},
                ],
            },
        }
        Path(server.DATA_FILE).write_text(json.dumps(fixture, ensure_ascii=False), encoding='utf-8')
        server.app.config['TESTING'] = True
        self.client = server.app.test_client()
        self.set_role('manager')
        self.today = datetime.now().strftime('%Y-%m-%d')
        self.seed_orders()

    def tearDown(self):
        server.PRINT_QUEUE.join()
        self.temp.cleanup()

    def set_role(self, role):
        with self.client.session_transaction() as session:
            session['username'] = role
            session['role'] = role
            session['screen_locked'] = False

    def request_api(self, method, *args, **kwargs):
        with patch.object(server, 'installation_license_valid', return_value=True):
            return getattr(self.client, method)(*args, **kwargs)

    def seed_orders(self):
        data = server.load()
        stamp = self.today + 'T12:00:00'
        data['orders'] = [
            {'id': 'ORD-0001', 'timestamp': stamp, 'items': [
                {'name': 'فروجة', 'price': 50, 'quantity': 2},
            ], 'total': 100},
            {'id': 'ORD-0003', 'timestamp': stamp, 'voided': True, 'items': [
                {'name': 'كريسبي ملغى', 'price': 100, 'quantity': 4},
            ], 'total': 400},
            {'id': 'ORD-0004', 'timestamp': stamp, 'type': 'تسديد دين',
             'accounting_type': 'debt_payment', 'items': [
                 {'name': 'تسديد دين', 'price': 1000, 'quantity': 1},
             ], 'total': 1000},
            {'id': 'ORD-0005', 'timestamp': stamp, 'subtotal': 200, 'discount_total': 50,
             'items': [{'name': 'كريسبي', 'price': 100, 'quantity': 2}], 'total': 150},
        ]
        data['orders_archive'] = [
            {'id': 'ORD-0002', 'timestamp': stamp, 'items': [
                {'name': 'فروجة', 'price': 50, 'quantity': 1},
                {'name': 'شاورما دبل', 'price': 80, 'quantity': 3},
            ], 'total': 290},
        ]
        server.save(data, ['ORD-0001', 'ORD-0002', 'ORD-0003', 'ORD-0004', 'ORD-0005'])

    def test_report_aggregates_live_and_archived_sales_and_excludes_voids_and_debt(self):
        response = self.request_api('get', '/api/reports/daily-items?date=' + self.today)
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body['ok'])
        self.assertEqual(body['currency'], 'SYP')
        self.assertEqual(body['item_count'], 3)
        rows = {row['name']: row for row in body['items']}
        self.assertEqual(rows['فروجة']['quantity'], 3)
        self.assertEqual(rows['فروجة']['price'], 50)
        self.assertEqual(rows['فروجة']['total'], 150)
        self.assertEqual(rows['شاورما دبل']['quantity'], 3)
        self.assertEqual(rows['شاورما دبل']['total'], 240)
        self.assertEqual(rows['كريسبي']['quantity'], 2)
        self.assertEqual(rows['كريسبي']['price'], 100)
        self.assertEqual(rows['كريسبي']['total'], 200)
        self.assertEqual(body['quantity_total'], 8)
        self.assertEqual(body['sales_total'], 590)
        self.assertNotIn('كريسبي ملغى', rows)
        self.assertNotIn('تسديد دين', rows)

    def test_daily_report_endpoints_are_manager_only(self):
        for role in ('cashier', 'supervisor'):
            self.set_role(role)
            with self.subTest(role=role):
                get_response = self.request_api('get', '/api/reports/daily-items')
                self.assertEqual(get_response.status_code, 403)
                post_response = self.request_api('post', '/api/printer/daily-report/print', json={'date': self.today})
                self.assertEqual(post_response.status_code, 403)
        self.set_role('manager')
        response = self.request_api('get', '/api/reports/daily-items?date=not-a-date')
        self.assertEqual(response.status_code, 400)

    def test_print_uses_structured_daily_report_and_forces_80mm_without_real_printer_io(self):
        self.set_role('manager')
        with patch.object(server, 'submit_network_raw_print', return_value={
            'ok': True, 'status': 'submitted', 'message': 'test print', 'job_id': 'test-job',
        }) as submit:
            response = self.request_api('post', '/api/printer/daily-report/print', json={'date': self.today})
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body['ok'])
        self.assertEqual(body['print']['type'], 'daily_report')
        self.assertEqual(body['report']['sales_total'], 590)
        self.assertEqual(submit.call_args.args[4], 80)
        document_text = submit.call_args.args[2]
        self.assertIn(server.RECEIPT_RS + server.RECEIPT_US.join(['C', 'تقرير أصناف اليوم', '1']), document_text)
        self.assertIn('فروجة', document_text)
        self.assertIn('شاورما دبل', document_text)
        self.assertIn('ROW', document_text)
        self.assertIn('BOX', document_text)
        saved = server.load()
        entries = [row for row in saved.get('print_log', []) if row.get('type') == 'daily_report']
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['status'], 'submitted')
        self.assertEqual(entries[0]['order_id'], 'DAILY-REPORT-' + self.today)


if __name__ == '__main__':
    unittest.main()
