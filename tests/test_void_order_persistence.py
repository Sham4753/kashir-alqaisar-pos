import sqlite3

import test_security_and_print as fixture_module

server = fixture_module.server


class VoidOrderPersistenceTests(fixture_module.SecurityAndPrintTests):
    def test_archived_void_persists_and_cannot_refund_twice_after_reload(self):
        data = server.load()
        data['menu']['السندويشات'][0]['recipe'] = [{'material': 'طحين', 'qty': 2}]
        data['inventory'] = [{'id': 1, 'name': 'طحين', 'unit': 'كغ', 'stock': 10, 'low_stock_threshold': 0}]
        server.save(data)

        self.assertEqual(self.login('manager', 'manager-pass').status_code, 200)
        sale = self.client.post('/api/orders', json={
            'items': [{'product_id': 1, 'quantity': 1}],
            'payment': 'نقدي', 'type': 'سفري', 'kitchen_release': 'later',
        })
        self.assertEqual(sale.status_code, 200)
        order_id = sale.get_json()['id']
        self.assertEqual(server.load()['inventory'][0]['stock'], 8)

        archived = self.client.post('/api/orders/archive')
        self.assertEqual(archived.status_code, 200)
        first_void = self.client.post(f'/api/orders/{order_id}/void', json={'reason': 'اختبار'})
        self.assertEqual(first_void.status_code, 200)
        self.assertTrue(first_void.get_json()['ok'])
        self.assertEqual(server.load()['inventory'][0]['stock'], 10)

        with sqlite3.connect(server.DATABASE_FILE) as conn:
            row = conn.execute('SELECT voided FROM orders WHERE id=?', (order_id,)).fetchone()
        self.assertEqual(row[0], 1)

        reloaded = server.load()
        archived_order = next(row for row in reloaded['orders_archive'] if row['id'] == order_id)
        self.assertTrue(archived_order['voided'])
        self.assertEqual(self.client.get('/api/orders').get_json(), [])
        included = self.client.get('/api/orders?include_voided=true').get_json()
        self.assertEqual([row['id'] for row in included], [order_id])

        cash_before = len(reloaded['cash_movements'])
        inventory_before = len(reloaded['inventory_movements'])
        second_void = self.client.post(f'/api/orders/{order_id}/void', json={'reason': 'مرة ثانية'})
        self.assertEqual(second_void.status_code, 200)
        self.assertFalse(second_void.get_json()['ok'])
        after_second_attempt = server.load()
        self.assertEqual(after_second_attempt['inventory'][0]['stock'], 10)
        self.assertEqual(len(after_second_attempt['cash_movements']), cash_before)
        self.assertEqual(len(after_second_attempt['inventory_movements']), inventory_before)


if __name__ == '__main__':
    import unittest
    unittest.main()
