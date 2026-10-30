import unittest
from unittest.mock import patch

import test_security_and_print as fixture_module

server = fixture_module.server


class KitchenPrintAsyncTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.SecurityAndPrintTests()
        self.fixture.setUp()
        self.client = self.fixture.client
        self.assertEqual(self.fixture.login('cashier', 'cashier-pass').status_code, 200)

    def tearDown(self):
        self.fixture.tearDown()

    def test_sale_never_requests_synchronous_kitchen_dispatch(self):
        calls = []

        def fake_queue(_data, _order, ticket_type='receipt', wait=False):
            calls.append((ticket_type, wait))
            return {'ok': True, 'status': 'queued', 'message': 'queued'}

        with patch.object(server, 'backup'), \
             patch.object(server, 'queue_thermal_print', side_effect=fake_queue), \
             patch.object(server, 'maybe_auto_open_cash_drawer', return_value=None):
            response = self.client.post('/api/orders', json={
                'items': [{'product_id': 1, 'quantity': 1}],
                'payment': 'نقدي', 'type': 'سفري', 'kitchen_release': 'now',
            })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(calls, [('receipt', False), ('kitchen', False)])


if __name__ == '__main__':
    unittest.main()
