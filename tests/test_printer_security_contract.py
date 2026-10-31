import os
import subprocess
import sys
import tempfile
import atexit
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TEST_VAULT = tempfile.TemporaryDirectory()
atexit.register(TEST_VAULT.cleanup)
os.environ.setdefault('CAESAR_VAULT_DIR', TEST_VAULT.name)

from app.server import render_escpos_raster_payload_for_printer


def test_roll_receipt_stays_portrait_and_grows_with_lines():
    short = render_escpos_raster_payload_for_printer('طلب واحد', {'paper_width': 58, 'paper_orientation': 'portrait'})
    long = render_escpos_raster_payload_for_printer('\n'.join(['شاورما Krispy Broasted'] * 12), {'paper_width': 58, 'paper_orientation': 'landscape'})
    assert int.from_bytes(short[8:10], 'little') < int.from_bytes(long[8:10], 'little')
    assert int.from_bytes(short[6:8], 'little') * 8 == 384
    assert int.from_bytes(long[6:8], 'little') * 8 == 384


def test_license_generator_refuses_missing_vendor_private_key():
    env = dict(os.environ)
    env.pop('CAESAR_LICENSE_PRIVATE_KEY_PATH', None)
    result = subprocess.run([sys.executable, str(ROOT / 'generate_license.py')], input='ABC\n', text=True, capture_output=True, env=env)
    assert result.returncode != 0
    assert 'private key' in (result.stderr + result.stdout).lower()
