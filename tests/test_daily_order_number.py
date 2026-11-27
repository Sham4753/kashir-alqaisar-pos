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


class DailyOrderNumberTests(unittest.TestCase):
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
            'menu': {'السندويشات': [{'id': 1, 'name': 'شاورما', 'price': 10, 'recipe': []}]},
            'orders': [], 'orders_archive': [], 'order_counter': 0,
            'settings': {
                'restaurant': {'name': 'مطعم الاختبار'},
                'commercial': {'setup_completed': True},
                'currency': 'SYP',
                'printer': {'auto_print_receipt': False, 'auto_print_kitchen': False, 'printer_name': ''},
                'users': [{'username': 'manager', 'role': 'manager'}, {'username': 'cashier', 'role': 'cashier'}],
            },
        }
        Path(server.DATA_FILE).write_text(json.dumps(fixture, ensure_ascii=False), encoding='utf-8')
        server.app.config['TESTING'] = True
        self.client = server.app.test_client()
        self.set_role('cashier')

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

    def create_sale(self):
        return self.request_api('post', '/api/orders', json={
            'items': [{'product_id': 1, 'quantity': 1}],
            'payment': 'نقدي', 'type': 'سفري', 'kitchen_release': 'later',
        })

    def test_daily_number_is_independent_from_internal_ord_and_reset(self):
        first = self.create_sale()
        self.assertEqual(first.status_code, 200)
        first_body = first.get_json()
        self.assertEqual(first_body['id'], 'ORD-0001')
        self.assertEqual(first_body['daily_no'], 1)
        self.assertEqual(first_body['display_no'], '1')

        self.set_role('manager')
        reset = self.request_api('post', '/api/shifts/reset-counter', json={'confirmation': 'RESET_COUNTER'})
        self.assertEqual(reset.status_code, 200)
        self.assertEqual(reset.get_json()['next_daily_no'], 1)

        self.set_role('cashier')
        second = self.create_sale()
        self.assertEqual(second.status_code, 200)
        second_body = second.get_json()
        self.assertEqual(second_body['id'], 'ORD-0002')
        self.assertEqual(second_body['daily_no'], 1)
        self.assertEqual(second_body['display_no'], '1')

    def test_daily_sequence_restarts_on_a_new_date(self):
        data = {'orders': [], 'orders_archive': []}
        first_day = datetime(2026, 11, 26, 23, 59)
        next_day = datetime(2026, 11, 27, 0, 1)
        self.assertEqual(server.next_daily_order_no(data, first_day), 1)
        self.assertEqual(server.next_daily_order_no(data, first_day), 2)
        self.assertEqual(server.next_daily_order_no(data, next_day), 1)
        self.assertEqual(data['daily_order_date'], '2026-11-27')

    def test_legacy_orders_fall_back_to_internal_ord_number(self):
        self.assertEqual(server.display_no({'id': 'ORD-0042'}), 'ORD-0042')
        self.assertEqual(server.display_no({'id': 'ORD-0042', 'daily_no': None}), 'ORD-0042')
        self.assertEqual(server.display_no({'id': 'ORD-0042', 'daily_no': 7}), '7')

        data = server.load()
        old_order = {'id': 'ORD-0042', 'timestamp': datetime.now().isoformat(), 'items': [], 'total': 0}
        data['orders'].append(old_order)
        server.save(data, [old_order['id']])
        response = self.request_api('get', '/api/orders?limit=10')
        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body['orders'][0]['id'], 'ORD-0042')
        self.assertEqual(body['orders'][0]['display_no'], 'ORD-0042')

    def test_kitchen_waiting_and_receipts_use_daily_display_number(self):
        data = server.load()
        order = {
            'id': 'ORD-0088', 'daily_no': 6, 'timestamp': datetime.now().isoformat(),
            'type': 'سفري', 'payment': 'نقدي', 'kitchen_status': 'ready',
            'items': [{'name': 'شاورما', 'price': 10, 'quantity': 1}], 'subtotal': 10, 'total': 10,
        }
        data['orders'].append(order)
        server.save(data, [order['id']])

        kitchen = self.request_api('get', '/api/kitchen/orders')
        self.assertEqual(kitchen.status_code, 200)
        kitchen_order = next(row for row in kitchen.get_json() if row['id'] == 'ORD-0088')
        self.assertEqual(kitchen_order['display_no'], '6')

        waiting = self.request_api('get', '/api/ready-orders')
        waiting_order = next(row for row in waiting.get_json() if row['id'] == 'ORD-0088')
        self.assertEqual(waiting_order['display_no'], '6')

        receipt_data = {'settings': {'restaurant': {'name': 'مطعم الاختبار'}, 'printer': {}}}
        structured = server.thermal_receipt_structured(receipt_data, order)
        self.assertIn('رقم الفاتورة: 6', structured)
        self.assertNotIn('ORD-0088', structured)
        legacy_text = server.thermal_receipt_text(receipt_data, {'id': 'ORD-OLD', 'items': []})
        self.assertIn('ORD-OLD', legacy_text)

        self.set_role('manager')
        report = self.request_api('get', '/api/analytics?period=custom&from=' + order['timestamp'][:10] + '&to=' + order['timestamp'][:10])
        report_order = next(row for row in report.get_json()['order_details'] if row['id'] == order['id'])
        self.assertEqual(report_order['id'], 'ORD-0088')
        self.assertEqual(report_order['display_no'], '6')

    def test_order_screens_use_display_number_and_reset_text_keeps_ord_internal(self):
        kitchen = (APP_DIR / 'kitchen.html').read_text(encoding='utf-8')
        waiting = (APP_DIR / 'waiting_screen.html').read_text(encoding='utf-8')
        orders = (APP_DIR / 'orders_list.html').read_text(encoding='utf-8')
        analytics = (APP_DIR / 'analytics.html').read_text(encoding='utf-8')
        shift = (APP_DIR / 'shift.html').read_text(encoding='utf-8')

        self.assertIn('order.display_no||order.id', kitchen)
        self.assertIn('row.display_no||row.id', waiting)
        self.assertIn('o.display_no || o.id', orders)
        self.assertIn('order.display_no || order.id', analytics)
        self.assertIn('رقم العرض اليومي التالي من <b>1</b>', shift)
        self.assertIn('ORD الداخلي فريدًا ولا يعاد استخدامه', shift)


if __name__ == '__main__':
    unittest.main()
