import unittest
from pathlib import Path
from unittest.mock import patch

import test_security_and_print as fixture_module

server = fixture_module.server


class PrintQueueStatusTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.SecurityAndPrintTests()
        self.fixture.setUp()
        self.client = self.fixture.client
        self.assertEqual(self.fixture.login('cashier', 'cashier-pass').status_code, 200)
        data = server.load()
        data['orders'] = [{
            'id': 'ORD-QUEUE-1', 'timestamp': '2026-10-30T12:00:00', 'items': [],
            'total': 0, 'payment': 'نقدي', 'cash_amount': 0, 'card_amount': 0,
        }]
        data['settings']['printer'].update({
            'connection_mode': 'network', 'network_host': '192.0.2.55', 'network_port': 9100,
        })
        server.save(data, ['ORD-QUEUE-1'])

    def tearDown(self):
        self.fixture.tearDown()

    def test_reprint_accepts_queued_job_and_marks_document_as_copy(self):
        captured = []

        def fake_queue(_data, order, ticket_type='receipt', wait=False):
            captured.append((dict(order), ticket_type, wait))
            return {'ok': True, 'status': 'queued', 'message': 'queued'}

        with patch.object(server, 'queue_thermal_print', side_effect=fake_queue):
            response = self.client.post('/api/printer/orders/ORD-QUEUE-1/print')

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['ok'])
        reprint, ticket_type, wait = captured[0]
        self.assertEqual(ticket_type, 'receipt')
        self.assertFalse(wait)
        self.assertTrue(reprint['is_reprint'])
        self.assertIn('نسخة', server.thermal_receipt_structured(server.load(), reprint))

    def test_retry_accepts_queued_replacement_but_refuses_running_queued_job(self):
        data = server.load()
        data['print_log'] = [{
            'id': 'failed-one', 'order_id': 'ORD-QUEUE-1', 'type': 'receipt',
            'status': 'failed', 'resolved': False, 'message': 'offline',
        }]
        server.save(data)
        calls = []

        def fake_queue(_data, _order, ticket_type='receipt', wait=False):
            calls.append((ticket_type, wait))
            return {'ok': True, 'status': 'queued', 'message': 'queued'}

        with patch.object(server, 'queue_thermal_print', side_effect=fake_queue):
            retried = self.client.post('/api/printer/orders/ORD-QUEUE-1/retry', json={'type': 'receipt'})
        self.assertEqual(retried.status_code, 200)
        self.assertTrue(retried.get_json()['ok'])
        self.assertEqual(calls, [('receipt', False)])
        row = server.load()['print_log'][0]
        self.assertTrue(row['resolved'])
        self.assertEqual(row['resolution'], 'retry_queued')

        data = server.load()
        data['print_log'] = [{
            'id': 'queued-one', 'order_id': 'ORD-QUEUE-1', 'type': 'receipt',
            'status': 'queued', 'resolved': False, 'message': 'working',
        }]
        server.save(data)
        with patch.object(server, 'queue_thermal_print') as queue_print:
            running = self.client.post('/api/printer/orders/ORD-QUEUE-1/retry', json={'type': 'receipt'})
        self.assertEqual(running.status_code, 409)
        queue_print.assert_not_called()

    def test_sale_page_treats_queued_as_an_accepted_print_state(self):
        index = (Path(__file__).resolve().parents[1] / 'app' / 'index.html').read_text(encoding='utf-8')
        self.assertIn("['queued','submitted','sent'].includes(printed.status)", index)


if __name__ == '__main__':
    unittest.main()
