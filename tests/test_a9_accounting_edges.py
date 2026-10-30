import json
import unittest
from pathlib import Path

import test_security_and_print as fixture_module

server = fixture_module.server


class A9AccountingEdgesTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.SecurityAndPrintTests()
        self.fixture.setUp()
        self.client = self.fixture.client

    def tearDown(self):
        self.fixture.tearDown()

    def test_next_order_id_checks_cold_archive(self):
        server.atomic_write_json(server._cold_archive_path('2024-05'), [
            {'id': 'ORD-0042', 'timestamp': '2024-05-10T12:00:00', 'items': []}
        ])
        data = server.load()
        self.assertEqual(server.next_order_id(data), 'ORD-0043')

    def test_order_currency_snapshot_ignores_client_override(self):
        data = server.load()
        data['settings'].update({'currency': 'EUR', 'eur_rate': 15000})
        snapshot = server.currency_snapshot(data, {'currency': 'USD', 'exchange_rate': 1})
        self.assertEqual(snapshot['currency'], 'EUR')
        self.assertEqual(snapshot['exchange_rate'], 15000)

    def test_debt_delete_is_manager_only_soft_void_with_audit(self):
        data = server.load()
        data['debts'] = [{'id': 4, 'name': 'دين تجريبي', 'amount': 100, 'paid': 0}]
        server.save(data)
        self.assertEqual(self.fixture.login('supervisor', 'supervisor-pass').status_code, 200)
        self.assertEqual(self.client.delete('/api/debts/4').status_code, 403)
        self.client.post('/api/auth/logout')
        self.assertEqual(self.fixture.login('manager', 'manager-pass').status_code, 200)
        response = self.client.delete('/api/debts/4')
        self.assertEqual(response.status_code, 200)
        debt = next(row for row in server.load()['debts'] if row['id'] == 4)
        self.assertTrue(debt['voided'])
        self.assertEqual(debt['audit_log'][-1]['action'], 'void')
        self.assertEqual(self.client.get('/api/debts').get_json(), [])

    def test_employee_deactivation_preserves_expenses_and_reverses_cash(self):
        data = server.load()
        data['employees'] = [{'id': 7, 'name': 'موظف تجريبي', 'salary': 100, 'advance': 0}]
        data['expenses'] = [{'id': 9, 'employee_id': 7, 'amount': 25, 'amount_base': 25, 'currency': 'SYP', 'exchange_rate': 1, 'payment': 'نقدي', 'date': '2026-10-30'}]
        server.save(data)
        self.assertEqual(self.fixture.login('manager', 'manager-pass').status_code, 200)
        response = self.client.delete('/api/employees/7')
        self.assertEqual(response.status_code, 200)
        after = server.load()
        self.assertFalse(after['employees'][0].get('active', True))
        self.assertTrue(after['expenses'][0]['voided'])
        self.assertTrue(any(row.get('reference_type') == 'employee_expense_void' for row in after.get('cash_movements', [])))

    def test_salary_endpoint_accepts_empty_json_body_without_attribute_error(self):
        data = server.load()
        data['employees'] = [{'id': 8, 'name': 'موظف', 'salary': 50, 'advance': 0}]
        server.save(data)
        self.assertEqual(self.fixture.login('manager', 'manager-pass').status_code, 200)
        response = self.client.post('/api/employees/8/pay-salary', data='not-json', content_type='text/plain')
        self.assertEqual(response.status_code, 200)

    def test_sale_prevents_negative_inventory_and_saves_recipe_snapshot(self):
        data = server.load()
        data['menu']['السندويشات'][0]['recipe'] = [{'material': 'طحين', 'qty': 2}]
        data['inventory'] = [{'id': 1, 'name': 'طحين', 'stock': 1, 'unit': 'كغ'}]
        server.save(data)
        self.assertEqual(self.fixture.login('cashier', 'cashier-pass').status_code, 200)
        refused = self.client.post('/api/orders', json={'items': [{'product_id': 1, 'quantity': 1}], 'payment': 'نقدي', 'type': 'سفري'})
        self.assertEqual(refused.status_code, 409)
        self.assertFalse(server.load()['orders'])

        data = server.load()
        data['inventory'][0]['stock'] = 5
        server.save(data)
        sold = self.client.post('/api/orders', json={'items': [{'product_id': 1, 'quantity': 1}], 'payment': 'نقدي', 'type': 'سفري'})
        self.assertEqual(sold.status_code, 200)
        saved_item = server.load()['orders'][-1]['items'][0]
        self.assertEqual(saved_item['recipe_snapshot'], [{'material': 'طحين', 'qty': 2}])


if __name__ == '__main__':
    unittest.main()
