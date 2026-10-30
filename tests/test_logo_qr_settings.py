import base64
import io
import unittest
from pathlib import Path

from PIL import Image

import test_security_and_print as fixture_module

server = fixture_module.server


class LogoQrSettingsTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.SecurityAndPrintTests()
        self.fixture.setUp()
        self.client = self.fixture.client
        self.assertEqual(self.fixture.login('manager', 'manager-pass').status_code, 200)

    def tearDown(self):
        self.fixture.tearDown()

    @staticmethod
    def qr_data_url():
        image = Image.new('1', (21, 21), 1)
        pixels = image.load()
        for y in range(21):
            for x in range(21):
                if (x * 7 + y * 3) % 5 == 0:
                    pixels[x, y] = 0
        for x0, y0 in ((0, 0), (14, 0), (0, 14)):
            for y in range(y0, y0 + 7):
                for x in range(x0, x0 + 7):
                    pixels[x, y] = 0 if x in (x0, x0 + 6) or y in (y0, y0 + 6) or (x0 + 2 <= x <= x0 + 4 and y0 + 2 <= y <= y0 + 4) else 1
        out = io.BytesIO()
        image.save(out, format='PNG')
        return 'data:image/png;base64,' + base64.b64encode(out.getvalue()).decode('ascii')

    def test_square_logo_is_not_treated_as_qr_without_explicit_flag(self):
        data_url = self.qr_data_url()
        normal = server.render_escpos_raster_payload('test', 58, 'small', data_url, 'large', 'center')
        qr = server.render_escpos_raster_payload('test', 58, 'small', data_url, 'large', 'center', logo_is_qr=True)
        normal_height = int.from_bytes(normal[8:10], 'little')
        qr_height = int.from_bytes(qr[8:10], 'little')
        self.assertGreater(qr_height, normal_height + 100)

    def test_logo_url_length_is_bounded_and_qr_setting_is_persisted(self):
        too_large = 'data:image/png;base64,' + ('A' * server.MAX_LOGO_DATA_URL_CHARS)
        rejected = self.client.post('/api/printer/settings', json={'logo_data': too_large})
        self.assertEqual(rejected.status_code, 400)

        data_url = self.qr_data_url()
        saved = self.client.post('/api/printer/settings', json={'logo_data': data_url, 'logo_is_qr': True})
        self.assertEqual(saved.status_code, 200)
        self.assertTrue(server.load()['settings']['printer']['logo_is_qr'])
        page = (Path(server.BASE_DIR) / 'printer_settings.html').read_text(encoding='utf-8')
        self.assertIn('maxBytes: 180 * 1024', page)


if __name__ == '__main__':
    unittest.main()
