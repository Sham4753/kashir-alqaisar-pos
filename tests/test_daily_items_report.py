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
            'employees': [{'id': 1, 'name': 'موظف اختبار', 'salary': 9000}],
            'expenses': [],
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
             'rounding_adjustment': 5,
             'items': [{'name': 'كريسبي', 'price': 100, 'quantity': 2}], 'total': 155},
        ]
        data['orders_archive'] = [
            {'id': 'ORD-0002', 'timestamp': stamp, 'items': [
                {'name': 'فروجة', 'price': 50, 'quantity': 1},
                {'name': 'فروجة', 'price': 60, 'quantity': 1},
                {'name': 'شاورما دبل', 'price': 80, 'quantity': 3},
            ], 'total': 350},
        ]
        data['expenses'] = [
            {'id': 1, 'material_id': 10, 'amount': 300, 'amount_base': 100,
             'date': stamp, 'payment': 'نقدي'},
            {'id': 2, 'employee_id': 1, 'amount': 40, 'amount_base': 40,
             'date': stamp, 'category': 'رواتب'},
            {'id': 3, 'amount': 80, 'amount_base': 20, 'date': stamp,
             'category': 'كهرباء'},
            {'id': 4, 'material_id': 11, 'amount': 700, 'amount_base': 700,
             'date': stamp, 'voided': True},
            {'id': 5, 'employee_id': 1, 'amount': 90, 'amount_base': 90,
             'date': stamp, 'voided': True},
            {'id': 6, 'material_id': 12, 'amount': 200, 'amount_base': 200,
             'date': stamp, 'is_reversal': True},
            {'id': 7, 'amount': 50, 'amount_base': -50, 'date': stamp},
            {'id': 8, 'material_id': 13, 'amount': 999, 'amount_base': 999,
             'date': '2020-01-01T09:00:00'},
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
        self.assertEqual(rows['فروجة']['quantity'], 4)
        self.assertEqual(rows['شاورما دبل']['quantity'], 3)
        self.assertEqual(rows['كريسبي']['quantity'], 2)
        self.assertEqual(body['quantity_total'], 9)
        self.assertEqual(body['sales_total'], 605)
        self.assertEqual(body['purchases_total'], 100)
        self.assertEqual(body['payroll_total'], 40)
        self.assertEqual(body['other_expenses_total'], 20)
        self.assertEqual(body['net_total'], 445)
        self.assertNotIn('كريسبي ملغى', rows)
        self.assertNotIn('تسديد دين', rows)

    def test_day_without_expenses_has_zero_cost_totals_and_net_equals_sales(self):
        data = server.load()
        data['expenses'] = []
        server.save(data)
        response = self.request_api('get', '/api/reports/daily-items?date=' + self.today)
        self.assertEqual(response.status_code, 200)
        report = response.get_json()
        self.assertEqual(report['purchases_total'], 0)
        self.assertEqual(report['payroll_total'], 0)
        self.assertEqual(report['other_expenses_total'], 0)
        self.assertEqual(report['sales_total'], 605)
        self.assertEqual(report['net_total'], 605)

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
        self.assertEqual(body['report']['sales_total'], 605)
        self.assertEqual(body['report']['purchases_total'], 100)
        self.assertEqual(body['report']['payroll_total'], 40)
        self.assertEqual(body['report']['other_expenses_total'], 20)
        self.assertEqual(body['report']['net_total'], 445)
        self.assertEqual(submit.call_args.args[4], 80)
        document_text = submit.call_args.args[2]
        commands = [line[1:].split(server.RECEIPT_US) for line in document_text.splitlines()]
        self.assertTrue(commands)
        self.assertTrue(all(parts[0] == 'C' for parts in commands))
        printed_lines = [parts[1] for parts in commands]
        self.assertEqual(printed_lines[:2], ['تقرير آخر النهار', 'التاريخ: ' + self.today])
        self.assertEqual(printed_lines[2:5], [
            f"{int(item['quantity'])}  {item['name']}" for item in body['report']['items']
        ])
        self.assertEqual(printed_lines[-5:], [
            'المبيع = 605 ل.س', 'المشتريات = 100 ل.س', 'الرواتب = 40 ل.س',
            'مصاريف أخرى = 20 ل.س', 'الصافي = 445 ل.س',
        ])
        self.assertNotIn('ORD-', document_text)
        self.assertNotIn('DAILY-REPORT', document_text)
        self.assertNotIn('السعر', document_text)
        self.assertNotIn('الفاتورة', document_text)
        saved = server.load()
        entries = [row for row in saved.get('print_log', []) if row.get('type') == 'daily_report']
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['status'], 'submitted')
        self.assertEqual(entries[0]['order_id'], 'DAILY-REPORT-' + self.today)


if __name__ == '__main__':
    unittest.main()
