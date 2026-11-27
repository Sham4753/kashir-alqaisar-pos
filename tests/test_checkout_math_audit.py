"""فحص حسابات الفاتورة: خصم، تقريب، دفع مختلط، إلغاء، عملات. يطبع نتائج الفحص صراحةً."""
import unittest
import test_security_and_print as fx

server = fx.server


class CheckoutMathAudit(unittest.TestCase):
    def setUp(self):
        self.f = fx.SecurityAndPrintTests(); self.f.setUp(); self.c = self.f.client
        d = server.load()
        d['menu'] = {'عام': [
            {'id': 1, 'name': 'أ', 'price': 10, 'recipe': []},
            {'id': 2, 'name': 'ب', 'price': 3.33, 'recipe': [],
             'modifiers': [{'name': 'جبنة', 'price': 1.11}]},
            {'id': 3, 'name': 'ج', 'price': 35000, 'recipe': []},
        ]}
        server.save(d)

    def tearDown(self):
        self.f.tearDown()

    def post(self, **kw):
        return self.c.post('/api/orders', json=kw)

    def test_basic_and_rounding(self):
        self.f.login('cashier', 'cashier-pass')
        r = self.post(items=[{'product_id': 2, 'quantity': 3, 'modifiers': [{'name': 'جبنة'}]}])
        self.assertEqual(r.get_json()['total'], round((3.33 + 1.11) * 3, 2))  # 13.32
        r = self.post(items=[{'product_id': 3, 'quantity': 3}], discount_pct=7.5)
        self.assertEqual(r.get_json()['total'], 97125.0)

    def test_item_note_is_saved_with_server_approved_order_line(self):
        self.f.login('cashier', 'cashier-pass')
        response = self.post(items=[{'product_id': 1, 'quantity': 1, 'note': 'بدون مخلل،\nصوص على جنب'}])
        self.assertEqual(response.status_code, 200)
        order = self.c.get(f"/api/order/{response.get_json()['id']}").get_json()
        self.assertEqual(order['items'][0]['note'], 'بدون مخلل، صوص على جنب')

    def test_held_cart_keeps_item_note(self):
        items, error = server.sanitize_held_items([
            {'id': 1, 'name': 'شاورما', 'price': 10, 'quantity': 1, 'note': 'بدون مخلل'}
        ])
        self.assertIsNone(error)
        self.assertEqual(items[0]['note'], 'بدون مخلل')

    def test_client_cannot_inject_price_or_fractional_qty(self):
        self.f.login('cashier', 'cashier-pass')
        r = self.post(items=[{'product_id': 1, 'quantity': 1, 'price': 0.01}])
        self.assertEqual(r.get_json()['total'], 10)
        self.assertEqual(self.post(items=[{'product_id': 1, 'quantity': 1.5}]).status_code, 400)
        self.assertEqual(self.post(items=[{'product_id': 1, 'quantity': -1}]).status_code, 400)
        self.assertEqual(self.post(items=[{'product_id': 1, 'quantity': 0}]).status_code, 400)

    def test_percent_discount_over_limit_needs_approval(self):
        self.f.login('cashier', 'cashier-pass')
        self.assertEqual(self.post(items=[{'product_id': 1, 'quantity': 1}], discount_pct=50).status_code, 403)

    def test_FINDING_fixed_discount_bypasses_approval(self):
        """الخصم بمبلغ ثابت لا يحتاج موافقة افتراضياً (discount_amount_limit=0 تعني معطّل)."""
        self.f.login('cashier', 'cashier-pass')
        r = self.post(items=[{'product_id': 3, 'quantity': 1}], discount_amount=35000)
        self.assertEqual(r.status_code, 403)  # after fix: needs manager approval

    def test_mixed_payment_must_match_total(self):
        self.f.login('cashier', 'cashier-pass')
        it = [{'product_id': 1, 'quantity': 3}]
        self.assertEqual(self.post(items=it, payment='مختلط', cash_amount=10, card_amount=19.99).status_code, 400)
        self.assertEqual(self.post(items=it, payment='مختلط', cash_amount=10, card_amount=20).status_code, 200)

    def test_void_reverses_cash_exactly(self):
        self.f.login('manager', 'manager-pass')
        oid = self.post(items=[{'product_id': 3, 'quantity': 2}], payment='نقدي').get_json()['id']
        cb = self.c.get('/api/cashbook/summary').get_json()
        self.assertEqual(cb['cash_in'], 70000)
        r = self.c.post(f'/api/orders/{oid}/void', json={'reason': 't'})
        self.assertTrue(r.get_json()['ok'])
        cb = self.c.get('/api/cashbook/summary').get_json()
        print('\n[void] cashbook after void:', {k: cb.get(k) for k in ('cash_in', 'cash_out', 'net', 'balance')})
        self.assertEqual(cb['cash_in'] - cb['cash_out'], 0)
        self.assertEqual(self.c.post(f'/api/orders/{oid}/void', json={}).get_json().get('ok'), False)

    def test_usd_display_mode_order_total_stays_in_syp(self):
        self.f.login('manager', 'manager-pass')
        d = server.load(); d['settings'].update(currency='USD', usd_rate=15000); server.save(d)
        r = self.post(items=[{'product_id': 3, 'quantity': 1}]).get_json()
        o = [x for x in self.c.get('/api/orders').get_json()][0]
        print('\n[USD mode] total=%s currency=%s rate=%s' % (r['total'], o.get('currency'), o.get('exchange_rate')))
        an = self.c.get('/api/analytics?period=daily').get_json()
        print('[USD mode] analytics keys sample:', {k: an.get(k) for k in ('total_sales', 'revenue', 'sales') if k in an})
        self.assertEqual(r['total'], 35000)

    def test_cashier_invoice_adjustment_is_signed_separate_and_cashbook_uses_net_paid(self):
        self.f.login('cashier', 'cashier-pass')
        positive = self.post(items=[{'product_id': 1, 'quantity': 1}], rounding_adjustment=0.5,
                             cash_received=11)
        self.assertEqual(positive.status_code, 200)
        first = self.c.get(f"/api/order/{positive.get_json()['id']}").get_json()
        self.assertEqual(first['total'], 10.5)
        self.assertEqual(first['rounding_adjustment'], 0.5)
        self.assertEqual(first['discount_total'], 0)
        self.assertEqual(first['cashier_name'], 'cashier')
        self.assertEqual(first['rounding_adjustment_by'], 'cashier')
        self.assertTrue(first['rounding_adjustment_at'])
        self.assertEqual(first['cash_amount'], 10.5)
        self.assertEqual(first['cash_received'], 11)
        self.assertEqual(first['change_due'], 0.5)
        data = server.load()
        text_receipt = server.thermal_receipt_text(data, first)
        structured_receipt = server.thermal_receipt_structured(data, first)
        for receipt in (text_receipt, structured_receipt):
            self.assertIn('تسوية المبلغ', receipt)
            self.assertIn('المبلغ المستلم', receipt)
            self.assertIn('الباقي', receipt)

        negative = self.post(items=[{'product_id': 1, 'quantity': 1}], rounding_adjustment=-0.5,
                             cash_received=10)
        self.assertEqual(negative.status_code, 200)
        second = self.c.get(f"/api/order/{negative.get_json()['id']}").get_json()
        self.assertEqual(second['total'], 9.5)
        self.assertEqual(second['rounding_adjustment'], -0.5)
        self.assertEqual(second['cash_amount'], 9.5)
        self.assertEqual(second['change_due'], 0.5)
        self.f.login('manager', 'manager-pass')
        self.assertEqual(self.c.get('/api/cashbook/summary').get_json()['cash_in'], 20)

    def test_adjustment_limit_is_inclusive_at_five_percent_and_requires_manager_above(self):
        self.f.login('cashier', 'cashier-pass')
        boundary = self.post(items=[{'product_id': 1, 'quantity': 1}], rounding_adjustment=0.5)
        self.assertEqual(boundary.status_code, 200)

        over_limit = self.post(items=[{'product_id': 1, 'quantity': 1}], rounding_adjustment=0.51)
        self.assertEqual(over_limit.status_code, 403)
        self.assertTrue(over_limit.get_json().get('approval_required'))

        approved = self.post(items=[{'product_id': 1, 'quantity': 1}], rounding_adjustment=0.51,
                             manager_approval={'username': 'manager', 'password': 'manager-pass'})
        self.assertEqual(approved.status_code, 200)
        order = self.c.get(f"/api/order/{approved.get_json()['id']}").get_json()
        self.assertEqual(order['total'], 10.51)
        self.assertEqual(order['manager_approval']['approved_by'], 'manager')
        self.assertEqual(order['manager_approval']['rounding_adjustment'], 0.51)

    def test_negative_invoice_and_underpayment_are_rejected(self):
        self.f.login('cashier', 'cashier-pass')
        negative_total = self.post(items=[{'product_id': 1, 'quantity': 1}], rounding_adjustment=-10.01)
        self.assertEqual(negative_total.status_code, 400)
        underpaid = self.post(items=[{'product_id': 1, 'quantity': 1}], rounding_adjustment=-0.5,
                              cash_received=9)
        self.assertEqual(underpaid.status_code, 400)

    def test_foreign_currency_adjustment_and_change_are_stored_in_base_currency(self):
        self.f.login('manager', 'manager-pass')
        data = server.load()
        data['settings'].update(currency='USD', usd_rate=15000)
        server.save(data)
        response = self.post(items=[{'product_id': 3, 'quantity': 1}], rounding_adjustment=0.1,
                             cash_received=2.5)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['total'], 36500)
        order = self.c.get(f"/api/order/{response.get_json()['id']}").get_json()
        self.assertEqual(order['rounding_adjustment'], 1500)
        self.assertEqual(order['cash_received'], 37500)
        self.assertEqual(order['change_due'], 1000)
        self.assertEqual(order['cash_amount'], 36500)

    def test_foreign_cash_input_requires_a_valid_rate_but_legacy_zero_adjustment_remains_valid(self):
        self.f.login('manager', 'manager-pass')
        data = server.load()
        data['settings']['currency'] = 'USD'
        data['settings'].pop('usd_rate', None)
        server.save(data)

        entered_cash = self.post(items=[{'product_id': 1, 'quantity': 1}], cash_received=10)
        self.assertEqual(entered_cash.status_code, 400)
        self.assertIn('تحويل المبلغ المستلم', entered_cash.get_json()['error'])

        legacy_payload = self.post(items=[{'product_id': 1, 'quantity': 1}])
        self.assertEqual(legacy_payload.status_code, 200)
        self.assertEqual(legacy_payload.get_json()['total'], 10)

    def test_legacy_payment_payload_defaults_received_amount_to_due_total(self):
        normalized, error = server.normalize_payment(10, {'payment': 'نقدي'})
        self.assertIsNone(error)
        self.assertEqual(normalized['cash_amount'], 10)
        self.assertEqual(normalized['cash_received'], 10)
        self.assertEqual(normalized['change_due'], 0)

    def test_card_receipts_do_not_label_card_payment_as_cash_received(self):
        self.f.login('cashier', 'cashier-pass')
        response = self.post(items=[{'product_id': 1, 'quantity': 1}], payment='بطاقة')
        self.assertEqual(response.status_code, 200)
        order = self.c.get(f"/api/order/{response.get_json()['id']}").get_json()
        data = server.load()
        for receipt in (server.thermal_receipt_text(data, order), server.thermal_receipt_structured(data, order)):
            self.assertNotIn('المبلغ المستلم', receipt)


if __name__ == '__main__':
    unittest.main()
