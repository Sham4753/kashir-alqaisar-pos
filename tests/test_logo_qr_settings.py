import base64
import io
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

import test_security_and_print as fixture_module

server = fixture_module.server
import qrcode  # noqa: E402


class LogoQrSettingsTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.SecurityAndPrintTests()
        self.fixture.setUp()
        self.client = self.fixture.client
        self.assertEqual(self.fixture.login('manager', 'manager-pass').status_code, 200)

    def tearDown(self):
        self.fixture.tearDown()

    @staticmethod
    def image_data_url(image):
        output = io.BytesIO()
        image.save(output, format='PNG')
        return 'data:image/png;base64,' + base64.b64encode(output.getvalue()).decode('ascii')

    @classmethod
    def qr_data_url(cls, box_size=8):
        qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=box_size, border=4)
        qr.add_data('https://example.com/menu/CAESAR-TEST-12345')
        qr.make(fit=True)
        return cls.image_data_url(qr.make_image(fill_color='black', back_color='white').convert('RGB'))

    @classmethod
    def plain_square_logo_data_url(cls):
        image = Image.new('RGB', (96, 96), 'white')
        draw = ImageDraw.Draw(image)
        draw.ellipse((16, 16, 80, 80), fill='#111111')
        draw.ellipse((34, 34, 62, 62), fill='white')
        return cls.image_data_url(image)

    @staticmethod
    def raster_height(payload):
        return int.from_bytes(payload[8:10], 'little')

    def test_square_logo_is_not_treated_as_qr_without_explicit_flag(self):
        data_url = self.plain_square_logo_data_url()
        self.assertFalse(server.logo_data_url_is_qr(data_url))
        normal = server.render_escpos_raster_payload('test', 58, 'small', data_url, 'large', 'center')
        qr = server.render_escpos_raster_payload(
            'test', 58, 'small', data_url, 'large', 'center', logo_is_qr=True)
        self.assertGreater(self.raster_height(qr), self.raster_height(normal) + 100)

    def test_qr_is_detected_and_respects_each_selected_size(self):
        data_url = self.qr_data_url()
        self.assertTrue(server.logo_data_url_is_qr(data_url))
        small = server.render_escpos_raster_payload(
            'test', 80, 'small', data_url, 'small', 'center', logo_is_qr=False)
        medium = server.render_escpos_raster_payload(
            'test', 80, 'small', data_url, 'medium', 'center', logo_is_qr=False)
        large = server.render_escpos_raster_payload(
            'test', 80, 'small', data_url, 'large', 'center', logo_is_qr=False)
        explicitly_small = server.render_escpos_raster_payload(
            'test', 80, 'small', data_url, 'small', 'center', logo_is_qr=True)
        normal = server.render_escpos_raster_payload(
            'test', 80, 'small', self.plain_square_logo_data_url(), 'medium', 'center')
        small_height = self.raster_height(small)
        medium_height = self.raster_height(medium)
        large_height = self.raster_height(large)
        self.assertGreater(small_height, self.raster_height(normal) + 80)
        self.assertGreater(medium_height, small_height + 100)
        self.assertGreater(large_height, medium_height + 100)
        self.assertEqual(self.raster_height(explicitly_small), small_height)

    def test_logo_url_length_is_bounded_and_qr_setting_is_persisted(self):
        too_large = 'data:image/png;base64,' + ('A' * server.MAX_LOGO_DATA_URL_CHARS)
        rejected = self.client.post('/api/printer/settings', json={'logo_data': too_large})
        self.assertEqual(rejected.status_code, 400)

        data_url = self.qr_data_url()
        saved = self.client.post('/api/printer/settings', json={
            'logo_data': data_url, 'logo_is_qr': False, 'logo_size': 'small'})
        self.assertEqual(saved.status_code, 200)
        self.assertFalse(server.load()['settings']['printer']['logo_is_qr'])
        self.assertEqual(server.load()['settings']['printer']['logo_size'], 'small')
        settings = self.client.get('/api/printer/settings').get_json()
        self.assertTrue(settings['logo_is_qr'])
        self.assertEqual(settings['logo_size'], 'small')
        preview = self.client.post('/api/printer/preview', json={'printer': {
            'paper_width': 80, 'logo_data': data_url, 'logo_size': 'medium', 'logo_is_qr': False,
        }})
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.headers.get('X-Printer-QR-Detected'), 'true')
        page = (Path(server.BASE_DIR) / 'printer_settings.html').read_text(encoding='utf-8')
        self.assertIn('maxBytes: 180 * 1024', page)
        self.assertIn("config.logo_size || 'medium'", page)
        self.assertNotIn("getElementById('logo_size').value = 'large'", page)
