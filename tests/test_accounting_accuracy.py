import unittest
from datetime import datetime, timedelta

import test_security_and_print as fixture_module

server = fixture_module.server


class AccountingAccuracyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.SecurityAndPrintTests()
        self.fixture.setUp()
        self.client = self.fixture.client
        self.client.post('/api/auth/login', json={'username': 'manager', 'password': 'manager-pass'})

    def tearDown(self):
        self.fixture.tearDown()

    def update_state(self, update):
        data = server.load()
        data.update(update)
        server.save(data)
        return data

    def test_foreign_expense_is_normalized_for_ledger_and_profit_report(self):
        data = server.load()
        data['settings']['usd_rate'] = 15000
        server.save(data)
        response = self.client.post('/api/expenses', json={
            'note': 'اختبار مصروف بالدولار', 'amount': 10, 'currency': 'USD',
            'exchange_rate': 15000, 'category': 'عام', 'payment': 'نقدي'
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['expense']['amount_base'], 150000)

        cashbook = self.client.get('/api/cashbook/summary').get_json()
        self.assertEqual(cashbook['cash_out'], 150000)
        self.assertEqual(cashbook['movements'][0]['amount'], 150000)
        self.assertEqual(cashbook['movements'][0]['original_currency'], 'USD')
        analytics = self.client.get('/api/analytics?period=daily').get_json()
        self.assertEqual(analytics['total_expenses'], 150000)

    def test_discount_is_allocated_to_filtered_product_and_cashier_summary(self):
        now = datetime.now().isoformat()
        data = server.load()
        data['menu'] = {'أطعمة': [
            {'id': 1, 'name': 'A', 'price': 100, 'recipe': []},
            {'id': 2, 'name': 'B', 'price': 100, 'recipe': []},
        ]}
        data['orders'] = [{
            'id': 'TEST-1', 'timestamp': now,
            'items': [{'product_id': 1, 'name': 'A', 'price': 100, 'quantity': 1},
                      {'product_id': 2, 'name': 'B', 'price': 100, 'quantity': 1}],
            'subtotal': 200, 'discount_pct': 10, 'discount_amount': 0,
            'discount_total': 20, 'total': 180, 'payment': 'نقدي',
            'cash_amount': 180, 'card_amount': 0, 'type': 'سفري', 'cashier_name': 'manager'
        }]
        server.save(data)

        report = self.client.get('/api/analytics?period=custom&from=' + now[:10] + '&to=' + now[:10] + '&product=A').get_json()
        self.assertEqual(report['total_sales'], 90)
        self.assertEqual(report['order_details'][0]['total'], 90)
        self.assertEqual(report['order_details'][0]['discount'], 10)
        self.assertEqual(report['total_cash'], 90)
        self.assertEqual(report['cashier_stats']['manager']['sales'], 90)

        financial = self.client.get('/api/analytics/financial?period=custom&from=' + now[:10] + '&to=' + now[:10]).get_json()
        self.assertEqual(financial['cashier_summary'][0]['discounts'], 20)

    def test_edit_order_reprices_rebalances_mixed_tender_and_writes_adjustments(self):
        response = self.client.post('/api/orders', json={
            'items': [{'product_id': 1, 'quantity': 2}], 'payment': 'مختلط',
            'cash_amount': 10, 'card_amount': 10, 'type': 'سفري', 'kitchen_release': 'later'
        })
        self.assertEqual(response.status_code, 200)
        order_id = response.get_json()['id']
        edited = self.client.post(f'/api/orders/{order_id}/edit-items', json={
            'username': 'manager', 'password': 'manager-pass',
            'items': [{'product_id': 1, 'name': 'سندويش اختبار', 'price': 1, 'quantity': 1}],
            'reason': 'تصحيح كمية'
        })
        self.assertEqual(edited.status_code, 200)
        self.assertEqual(edited.get_json()['new_total'], 10)
        data = server.load()
        order = next(row for row in data['orders'] if row['id'] == order_id)
        self.assertEqual(order['total'], 10)
        self.assertEqual(order['subtotal'], 10)
        self.assertEqual(order['cash_amount'] + order['card_amount'], order['total'])
        self.assertEqual(order['items'][0]['price'], 10)  # client-sent price is never trusted
        self.assertEqual(order['cash_amount'], 5)
        self.assertEqual(order['card_amount'], 5)
        self.assertEqual(len([row for row in data['cash_movements'] if row.get('reference_type') == 'order_edit']), 2)
        cashbook = self.client.get('/api/cashbook/summary').get_json()
        self.assertEqual(cashbook['cash_balance'], 5)
        self.assertEqual(cashbook['card_balance'], 5)

    def test_salary_is_not_subtracted_twice_in_monthly_operating_profit(self):
        now = datetime.now().isoformat()
        data = server.load()
        data['employees'] = [{'id': 1, 'name': 'موظف', 'salary': 100, 'advance': 0}]
        data['expenses'] = [{'employee_id': 1, 'amount': 100, 'amount_base': 100,
                             'category': 'رواتب', 'date': now, 'note': 'دفع راتب'}]
        data['orders'] = [{'id': 'SALE-1', 'timestamp': now, 'items': [], 'total': 200,
                           'subtotal': 200, 'payment': 'نقدي', 'cash_amount': 200,
                           'card_amount': 0, 'type': 'سفري', 'cashier_name': 'manager'}]
        server.save(data)
        report = self.client.get('/api/analytics?period=monthly').get_json()
        self.assertEqual(report['total_expenses'], 100)
        self.assertEqual(report['total_salaries'], 100)
        self.assertEqual(report['other_expenses'], 0)
        self.assertEqual(report['operating_profit'], 100)

    def test_yearly_salary_accrual_does_not_include_future_months(self):
        data = server.load()
        data['employees'] = [{'id': 1, 'name': 'موظف', 'salary': 100, 'advance': 0}]
        data['expenses'] = []
        data['orders'] = []
        server.save(data)
        report = self.client.get('/api/analytics?period=yearly').get_json()
        self.assertGreater(report['total_salaries'], 0)
        self.assertLess(report['total_salaries'], 1200)

    def test_debt_collection_is_cash_inflow_but_not_new_sales(self):
        data = server.load()
        data['debts'] = [{'id': 7, 'name': 'عميل', 'amount': 100, 'paid': 0,
                          'payments': [], 'note': ''}]
        server.save(data)
        response = self.client.post('/api/debts/7/pay', json={'amount': 20, 'method': 'نقدي'})
        self.assertEqual(response.status_code, 200)
        report = self.client.get('/api/analytics?period=daily').get_json()
        self.assertEqual(report['total_sales'], 0)
        self.assertEqual(report['total_orders'], 0)
        self.assertEqual(report['cash_flow_after_purchases'], 20)
        financial = self.client.get('/api/analytics/financial?period=daily').get_json()
        self.assertEqual(financial['summary']['sales'], 0)
        self.assertEqual(financial['summary']['cash_in'], 20)

    def test_historical_sale_uses_cost_snapshot_after_recipe_and_purchase_cost_change(self):
        data = server.load()
        data['menu'] = {'أطعمة': [{'id': 1, 'name': 'A', 'price': 100,
                                  'recipe': [{'material': 'طحين', 'qty': 2}]}]}
        data['materials'] = [{'id': 1, 'name': 'طحين', 'quantity': 100, 'price': 1000}]
        server.save(data)
        sale = self.client.post('/api/orders', json={
            'items': [{'product_id': 1, 'quantity': 1}], 'payment': 'نقدي',
            'type': 'سفري', 'kitchen_release': 'later'
        })
        self.assertEqual(sale.status_code, 200)
        data = server.load()
        self.assertEqual(data['orders'][0]['items'][0]['unit_cost_snapshot'], 20)
        data['materials'][0]['price'] = 5000
        data['menu']['أطعمة'][0]['recipe'][0]['qty'] = 4
        server.save(data)
        report = self.client.get('/api/analytics?period=daily').get_json()
        self.assertEqual(report['cost_of_goods_sold'], 20)

    def test_legacy_sale_cost_ignores_material_purchases_after_sale_date(self):
        sold_at = datetime.now().isoformat()
        data = server.load()
        data['menu'] = {'أطعمة': [{'id': 1, 'name': 'A', 'price': 100,
                                  'recipe': [{'material': 'طحين', 'qty': 1}]}]}
        data['materials'] = [
            {'id': 1, 'name': 'طحين', 'quantity': 100, 'price': 1000,
             'date': (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d')},
            {'id': 2, 'name': 'طحين', 'quantity': 100, 'price': 5000,
             'date': (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')},
        ]
        data['orders'] = [{'id': 'OLD-SALE', 'timestamp': sold_at, 'subtotal': 100,
                           'total': 100, 'items': [{'product_id': 1, 'name': 'A',
                                                     'price': 100, 'quantity': 1}],
                           'payment': 'نقدي', 'cash_amount': 100, 'card_amount': 0,
                           'type': 'سفري', 'cashier_name': 'manager'}]
        server.save(data)
        report = self.client.get('/api/analytics?period=daily').get_json()
        self.assertEqual(report['cost_of_goods_sold'], 10)

    def test_split_discount_stays_correct_when_split_order_is_edited(self):
        now = datetime.now().isoformat()
        data = server.load()
        data['menu'] = {'أطعمة': [
            {'id': 1, 'name': 'A', 'price': 100, 'recipe': []},
            {'id': 2, 'name': 'B', 'price': 100, 'recipe': []},
        ]}
        data['orders'] = [{
            'id': 'SPLIT-1', 'timestamp': now,
            'items': [{'product_id': 1, 'name': 'A', 'price': 100, 'quantity': 1},
                      {'product_id': 2, 'name': 'B', 'price': 100, 'quantity': 1}],
            'subtotal': 200, 'discount_pct': 10, 'discount_amount': 0,
            'discount_total': 20, 'total': 180, 'payment': 'نقدي',
            'cash_amount': 180, 'card_amount': 0, 'type': 'سفري', 'cashier_name': 'manager'
        }]
        server.save(data)
        split = self.client.post('/api/orders/SPLIT-1/split', json={'item_indexes': [0]})
        self.assertEqual(split.status_code, 200)
        split_data = split.get_json()
        new_order = split_data['new_order']
        self.assertEqual(new_order['total'], 90)
        self.assertEqual(new_order['discount_pct'], 0)
        self.assertEqual(new_order['discount_amount'], 10)
        self.assertEqual(split_data['original_order']['total'] + new_order['total'], 180)

        edited = self.client.post(f"/api/orders/{new_order['id']}/edit-items", json={
            'username': 'manager', 'password': 'manager-pass',
            'items': [{'product_id': 1, 'quantity': 1}], 'reason': 'اختبار بعد التقسيم'
        })
        self.assertEqual(edited.status_code, 200)
        report = self.client.get('/api/analytics/financial?period=daily').get_json()
        self.assertEqual(report['summary']['sales'], 180)
        self.assertEqual(sum(row['discounts'] for row in report['cashier_summary']), 20)

    def test_dine_in_total_includes_percentage_and_fixed_discount(self):
        data = server.load()
        totals, error = server.dine_in_totals(data, {
            'items': [{'product_id': 1, 'quantity': 1}],
            'discount_pct': 10, 'discount_amount': 1
        })
        self.assertIsNone(error)
        self.assertEqual(totals['subtotal'], 10)
        self.assertEqual(totals['total'], 8)
        self.assertEqual(totals['discount_total'], 2)

    def test_payment_mismatch_of_one_cent_is_rejected(self):
        normalized, error = server.normalize_payment(10, {
            'payment': 'مختلط', 'cash_amount': 10, 'card_amount': 0.01
        })
        self.assertIsNone(normalized)
        self.assertIsNotNone(error)

    def test_financial_report_uses_decimal_rounding_for_cashier_totals(self):
        now = datetime.now().isoformat()
        data = server.load()
        data['orders'] = [{
            'id': 'ROUND-1', 'timestamp': now, 'subtotal': '1.005', 'total': '1.005',
            'items': [], 'payment': 'نقدي', 'cash_amount': '1.005', 'card_amount': 0,
            'type': 'سفري', 'cashier_name': 'manager'
        }]
        server.save(data)
        report = self.client.get('/api/analytics/financial?period=daily').get_json()
        self.assertEqual(report['summary']['sales'], 1.01)
        self.assertEqual(report['cashier_summary'][0]['sales'], 1.01)
        self.assertEqual(report['cashier_summary'][0]['cash'], 1.01)

    def test_shift_close_rejects_non_finite_actual_cash(self):
        response = self.client.post('/api/shifts/close', json={'actual_cash': 'NaN'})
        self.assertEqual(response.status_code, 400)
        self.assertIn('غير صالح', response.get_json()['error'])

    def test_non_finite_financial_inputs_are_rejected(self):
        cases = [
            ('/api/debts', {'name': 'عميل', 'amount': 'NaN'}),
            ('/api/expenses', {'note': 'مصروف اختبار', 'amount': 'Infinity'}),
            ('/api/gift-cards', {'code': 'GIFT-1', 'balance': 'NaN'}),
        ]
        for path, payload in cases:
            with self.subTest(path=path):
                response = self.client.post(path, json=payload)
                self.assertEqual(response.status_code, 400)

    def test_supplier_summary_uses_decimal_money_sums(self):
        data = server.load()
        data['suppliers'] = [{'id': 1, 'name': 'مورد'}]
        data['materials'] = [
            {'id': 1, 'supplier_id': 1, 'price': '0.10', 'paid_amount': '0.10'},
            {'id': 2, 'supplier_id': 1, 'price': '0.20', 'paid_amount': '0.10'},
        ]
        data['supplier_payments'] = [{'id': 1, 'supplier_id': 1, 'amount': '0.10'}]
        server.save(data)
        summary = self.client.get('/api/suppliers/summary').get_json()['suppliers'][0]
        self.assertEqual(summary['purchase_total'], 0.30)
        self.assertEqual(summary['paid_total'], 0.30)
        self.assertEqual(summary['due_total'], 0)


if __name__ == '__main__':
    unittest.main()
