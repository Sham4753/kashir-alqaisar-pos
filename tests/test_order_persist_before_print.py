import unittest
from unittest.mock import patch

import test_security_and_print as fixture_module

server = fixture_module.server


class OrderPersistBeforePrintTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.SecurityAndPrintTests()
        self.fixture.setUp()
        self.client = self.fixture.client
        self.assertEqual(self.fixture.login('cashier', 'cashier-pass').status_code, 200)

    def tearDown(self):
        self.fixture.tearDown()

    def test_sale_is_saved_and_backed_up_before_print_or_drawer(self):
        events = []

        def fake_backup(*_args, **_kwargs):
            events.append('backup')

        def assert_persisted_then_queue(_data, order, ticket_type='receipt', wait=False):
            orders = server.load()['orders']
            self.assertTrue(any(row['id'] == order['id'] for row in orders))
            self.assertIn('backup', events)
            events.append(f'print:{ticket_type}')
            return {'ok': True, 'status': 'queued', 'message': 'queued'}

        def assert_persisted_then_drawer(_data, order, _cash):
            self.assertTrue(any(row['id'] == order['id'] for row in server.load()['orders']))
            self.assertIn('backup', events)
            events.append('drawer')
            return {'ok': True, 'status': 'queued'}

        with patch.object(server, 'backup', side_effect=fake_backup), \
             patch.object(server, 'queue_thermal_print', side_effect=assert_persisted_then_queue), \
             patch.object(server, 'maybe_auto_open_cash_drawer', side_effect=assert_persisted_then_drawer):
            response = self.client.post('/api/orders', json={
                'items': [{'product_id': 1, 'quantity': 1}],
                'payment': 'نقدي', 'type': 'سفري', 'kitchen_release': 'now',
            })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(events[:4], ['backup', 'print:receipt', 'print:kitchen', 'drawer'])
        self.assertEqual(events.count('backup'), 2)


if __name__ == '__main__':
    unittest.main()
