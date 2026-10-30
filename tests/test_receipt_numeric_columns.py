import unittest

import test_security_and_print as fixture_module

server = fixture_module.server


class ReceiptNumericColumnsTests(unittest.TestCase):
    def receipt_data(self, width):
        data = {
            'settings': {
                'restaurant': {'name': 'مطعم الاختبار'},
                'currency': 'SYP',
                'printer': {'paper_width': width, 'font_size': 'medium', 'receipt_layout': ['logo', 'header', 'details', 'items', 'totals', 'footer']},
            }
        }
        order = {
            'id': 'ORD-NUMBERS', 'timestamp': '2026-10-30T12:00:00', 'payment': 'نقدي',
            'subtotal': 1234567890, 'total': 1234567890,
            'items': [{
                'name': 'اسم صنف طويل جداً يحتاج إلى التفاف آمن داخل عمود الاسم فقط',
                'quantity': 1, 'price': 1234567890,
            }],
        }
        return data, order

    def test_large_numeric_cells_are_not_split_on_58_or_80mm(self):
        for width, expected_columns in ((58, '30,18,22,30'), (80, '40,17,22,21')):
            with self.subTest(width=width):
                data, order = self.receipt_data(width)
                structured = server.thermal_receipt_structured(data, order)
                self.assertIn(expected_columns, structured)
                self.assertIn('1,234,567,890', structured)
                item_row = next(line for line in structured.splitlines() if 'اسم صنف طويل' in line)
                cells = item_row.split(server.RECEIPT_US)[5:]
                self.assertTrue(all('\n' not in cell for cell in cells))
                payload = server.render_escpos_raster_payload_for_printer(structured, data['settings']['printer'])
                self.assertTrue(payload.startswith(b'\x1b\x40\x1d\x76\x30'))
                self.assertEqual(int.from_bytes(payload[6:8], 'little') * 8, 384 if width == 58 else 576)

    def test_numeric_font_is_shrunk_until_long_value_fits_cell(self):
        candidates = (
            server.os.path.join(server.BASE_DIR, 'fonts', 'Tajawal-Regular.ttf'),
            '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        )
        font_path = next((path for path in candidates if server.os.path.isfile(path)), None)
        if not font_path:
            self.skipTest('لا يتوفر خط TrueType لاختبار قياس عرض الرقم')
        font = server.ImageFont.truetype(font_path, 23)
        measure = lambda value, fnt: server.ImageDraw.Draw(server.Image.new('L', (400, 40))).textbbox((0, 0), value, font=fnt)[2]
        value = '14,814,814,680'
        fitted = server.fit_numeric_cell_font(value, font, 100, measure)
        self.assertLessEqual(measure(value, fitted), 100)


if __name__ == '__main__':
    unittest.main()
