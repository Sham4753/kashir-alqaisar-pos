import unittest
import test_security_and_print as fx

server = fx.server
RS, US = server.RECEIPT_RS, server.RECEIPT_US


def sample(width=80):
    data = {'settings': {'restaurant': {'name': 'مطعم', 'tax_number': '123'}, 'currency': 'SYP',
                         'printer': {'paper_width': width, 'footer_text': 'شكرا'}}}
    order = {'id': 'A-1', 'timestamp': '2026-10-28T16:22:00', 'customer': 'زبون', 'payment': 'نقدي',
             'cashier_name': 'محمد', 'subtotal': 311, 'discount_total': 1, 'total': 310,
             'items': [{'name': 'صنف أول', 'quantity': 10, 'price': 7}, {'name': 'صنف ثان', 'quantity': 2.5, 'price': 4}]}
    return data, order


class StructuredReceiptTests(unittest.TestCase):
    def test_structured_text_has_table_counts_and_totals(self):
        data, order = sample()
        text = server.thermal_receipt_structured(data, order)
        for needle in ('الصنف', 'الكمية', 'السعر', 'القيمة', 'البنود', '12.5',
                       'الإجمالي', 'الخصم', 'الرقم الضريبي: 123', 'الكاشير: محمد'):
            self.assertIn(needle, text)
        self.assertEqual(text.count(RS + 'BOX'), text.count(RS + 'ENDBOX'))

    def test_item_note_is_in_customer_receipt_under_its_item(self):
        data, order = sample()
        order['items'][0]['note'] = 'بدون مخلل، صوص على جنب'
        text = server.thermal_receipt_structured(data, order)
        self.assertIn('ملاحظة الصنف: بدون مخلل، صوص على جنب', text)
        self.assertIn(RS + 'ROW' + US + '0' + US + '100', text)
        for width in (58, 80):
            with self.subTest(width=width):
                data['settings']['printer']['paper_width'] = width
                with_note = server.render_escpos_raster_payload_for_printer(text, data['settings']['printer'])
                without_note = dict(order)
                without_note['items'] = [dict(item, note='') for item in order['items']]
                plain_text = server.thermal_receipt_structured(data, without_note)
                without_note_payload = server.render_escpos_raster_payload_for_printer(
                    plain_text, data['settings']['printer'])
                self.assertGreater(len(with_note), len(without_note_payload))

    def test_directives_cannot_be_injected_from_item_names(self):
        data, order = sample()
        order['items'][0]['name'] = 'x' + RS + 'RULE' + US + 'y'
        text = server.thermal_receipt_structured(data, order)
        self.assertNotIn(RS + 'RULE' + US + 'y', text)

    def test_renders_on_both_paper_widths_and_differs_from_plain(self):
        for width in (58, 80):
            data, order = sample(width)
            printer = data['settings']['printer']
            boxed = server.render_escpos_raster_payload_for_printer(server.thermal_receipt_structured(data, order), printer)
            plain = server.render_escpos_raster_payload_for_printer(server.thermal_receipt_text(data, order), printer)
            self.assertTrue(boxed.startswith(b'\x1b\x40\x1d\x76\x30'))
            self.assertNotEqual(boxed, plain)

    def test_dispatch_keeps_sales_receipt_boxed_when_legacy_plain_is_saved(self):
        from unittest.mock import patch
        for style in ('boxed', 'plain'):
            data, order = sample()
            data['settings']['printer'].update({'printer_name': 'X', 'receipt_style': style})
            seen = {}
            def fake(name, text, *a, **k):
                seen['text'] = text; return {'ok': True, 'status': 'sent', 'message': 'ok'}
            with patch.object(server, 'submit_silent_thermal_print', fake):
                server._dispatch_print_job((data, order, 'receipt', 'log'))
            self.assertIn(RS, seen['text'], style)

    def test_kitchen_ticket_stays_plain(self):
        data, order = sample()
        data['settings']['printer']['printer_name'] = 'X'
        from unittest.mock import patch
        seen = {}
        def fake(name, text, *a, **k):
            seen['text'] = text; return {'ok': True, 'status': 'sent', 'message': 'ok'}
        with patch.object(server, 'submit_silent_thermal_print', fake):
            server._dispatch_print_job((data, order, 'kitchen', 'log'))
        self.assertNotIn(RS, seen['text'])


if __name__ == '__main__':
    unittest.main()
