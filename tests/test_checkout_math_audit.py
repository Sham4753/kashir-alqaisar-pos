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


if __name__ == '__main__':
    unittest.main()
