import unittest

import test_security_and_print as fixture_module

server = fixture_module.server


class ReceiptKvWrapTests(unittest.TestCase):
    def payload_height(self, text, width):
        payload = server.render_escpos_raster_payload(text, paper_width=width, font_size='medium')
        return int.from_bytes(payload[8:10], 'little')

    def test_long_kv_label_and_value_allocate_multiple_lines_without_overlap(self):
        short = server.RECEIPT_RS + 'KV' + server.RECEIPT_US + 'الاسم' + server.RECEIPT_US + '100'
        long = server.RECEIPT_RS + 'KV' + server.RECEIPT_US + (
            'اسم عميل طويل جداً يحتاج إلى التفاف واضح داخل عمود العنوان فقط'
        ) + server.RECEIPT_US + '1,234,567,890 قيمة مجموع طويلة'
        for width in (58, 80):
            with self.subTest(width=width):
                self.assertGreater(self.payload_height(long, width), self.payload_height(short, width))


if __name__ == '__main__':
    unittest.main()
