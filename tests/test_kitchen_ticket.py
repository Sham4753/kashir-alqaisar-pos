import unittest
from unittest.mock import patch

import test_security_and_print as fixture_module

server = fixture_module.server


class KitchenTicketTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.SecurityAndPrintTests()
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def test_kitchen_text_uses_note_and_lists_modifiers_without_logo_caption(self):
        data = server.load()
        data['settings']['printer'].update({'logo_caption': 'شعار لا يجب طباعته', 'paper_width': 80})
        order = {
            'id': 'ORD-KITCHEN-1', 'type': 'سفري', 'note': 'بدون بصل',
            'items': [{'name': 'شاورما', 'quantity': 2, 'modifiers': [{'name': 'جبنة إضافية'}, 'حار']}],
        }
        ticket = server.thermal_receipt_text(data, order, 'kitchen')
        self.assertIn('ملاحظة: بدون بصل', ticket)
        self.assertIn('إضافات: جبنة إضافية، حار', ticket)
        self.assertNotIn('شعار لا يجب طباعته', ticket)

    def test_kitchen_dispatch_strips_image_and_limits_to_one_copy(self):
        data = server.load()
        data['settings']['printer'].update({
            'printer_name': 'Kitchen', 'connection_mode': 'windows', 'copies': 3,
            'logo_data': 'data:image/png;base64,AAAA', 'logo_caption': 'شعار',
        })
        order = {'id': 'ORD-KITCHEN-2', 'type': 'سفري', 'items': []}
        calls = []

        def fake_submit(_name, _text, _font, _width, _document, config):
            calls.append(dict(config))
            return {'ok': True, 'status': 'submitted', 'message': 'ok'}

        with patch.object(server, 'submit_silent_thermal_print', side_effect=fake_submit):
            result = server._dispatch_print_job((data, order, 'kitchen', 'log-1'))

        self.assertEqual(result['copies_requested'], 1)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['logo_data'], '')
        self.assertEqual(calls[0]['logo_caption'], '')


if __name__ == '__main__':
    unittest.main()
