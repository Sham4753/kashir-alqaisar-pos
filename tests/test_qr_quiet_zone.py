import base64
import io
import os
import sys
import unittest

from PIL import Image

import test_security_and_print as fixture_module

server = fixture_module.server
sys.path.insert(0, os.path.join(server.BASE_DIR, 'vendor'))
import qrcode  # noqa: E402


def frames_to_image(payload):
    pos = 2 if payload[:2] == b'\x1b\x40' else 0
    parts = []
    while payload[pos:pos + 3] == b'\x1d\x76\x30':
        row_bytes = int.from_bytes(payload[pos + 4:pos + 6], 'little')
        height = int.from_bytes(payload[pos + 6:pos + 8], 'little')
        data = payload[pos + 8:pos + 8 + row_bytes * height]
        parts.append(Image.frombytes('1', (row_bytes * 8, height), data).convert('L'))
        pos += 8 + row_bytes * height
    image = Image.new('L', (parts[0].width, sum(p.height for p in parts)), 255)
    y = 0
    for part in parts:
        image.paste(part.point(lambda v: 255 - v), (0, y))
        y += part.height
    return image


class QrQuietZoneTests(unittest.TestCase):
    def test_real_qr_keeps_four_module_quiet_zone_on_58_and_80mm(self):
        qr = qrcode.QRCode(border=0, box_size=1, error_correction=qrcode.constants.ERROR_CORRECT_M)
        qr.add_data('https://example.com/menu/CAESAR-TEST-12345')
        qr.make(fit=True)
        modules = qr.modules_count
        small = Image.new('L', (modules, modules), 255)
        pixels = small.load()
        for y, row in enumerate(qr.get_matrix()):
            for x, value in enumerate(row):
                if value:
                    pixels[x, y] = 0
        out = io.BytesIO()
        small.resize((120, 120), Image.Resampling.NEAREST).save(out, format='PNG')
        data_url = 'data:image/png;base64,' + base64.b64encode(out.getvalue()).decode('ascii')
        required = 4 * 120 / modules
        for width in (58, 80):
            with self.subTest(width=width):
                cfg = {'paper_width': width, 'font_size': 'small', 'logo_data': data_url,
                       'logo_is_qr': True, 'logo_size': 'large', 'logo_alignment': 'center'}
                image = frames_to_image(server.render_escpos_raster_payload_for_printer('QR', cfg))
                box = image.point(lambda v: 255 if v < 128 else 0).getbbox()
                self.assertGreaterEqual(box[1] - 8, required)


if __name__ == '__main__':
    unittest.main()
