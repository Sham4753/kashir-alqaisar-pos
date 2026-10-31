from __future__ import annotations

import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

TOOLS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS_DIR))
from create_vendor_keys import REPO_ROOT, main  # noqa: E402


class CreateVendorKeysTests(unittest.TestCase):
    def test_creates_encrypted_private_key_and_matching_public_key(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            private_path = root / "owner-keys" / "vendor-private.pem"
            public_path = root / "application" / "license_public_key.pem"
            output = io.StringIO()
            with patch("create_vendor_keys.getpass", side_effect=["safe passphrase 2026", "safe passphrase 2026"]):
                with contextlib.redirect_stdout(output):
                    self.assertEqual(main([
                        "--private-key-path", str(private_path),
                        "--public-key-path", str(public_path),
                    ]), 0)

            private_pem = private_path.read_bytes()
            self.assertIn(b"-----BEGIN ENCRYPTED PRIVATE KEY-----", private_pem)
            self.assertNotIn(b"safe passphrase 2026", private_pem)
            private_key = serialization.load_pem_private_key(private_pem, password=b"safe passphrase 2026")
            public_key = serialization.load_pem_public_key(public_path.read_bytes())
            self.assertIsInstance(private_key, Ed25519PrivateKey)
            self.assertEqual(
                private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw),
                public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw),
            )
            self.assertIn("encrypted", output.getvalue())

    def test_refuses_private_key_path_inside_repository(self):
        private_path = REPO_ROOT / "private-key-must-not-be-created-test.pem"
        with tempfile.TemporaryDirectory() as temporary:
            public_path = Path(temporary) / "public.pem"
            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                with self.assertRaises(SystemExit) as raised:
                    main([
                        "--private-key-path", str(private_path),
                        "--public-key-path", str(public_path),
                    ])
            self.assertNotEqual(raised.exception.code, 0)
            self.assertIn("outside the repository", error.getvalue())
            self.assertFalse(private_path.exists())
            self.assertFalse(public_path.exists())

    def test_refuses_to_overwrite_existing_key_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            private_path = Path(temporary) / "owner" / "private.pem"
            public_path = Path(temporary) / "public" / "public.pem"
            private_path.parent.mkdir(parents=True)
            private_path.write_text("keep existing", encoding="utf-8")
            error = io.StringIO()
            with contextlib.redirect_stderr(error):
                with self.assertRaises(SystemExit):
                    main([
                        "--private-key-path", str(private_path),
                        "--public-key-path", str(public_path),
                    ])
            self.assertEqual(private_path.read_text(encoding="utf-8"), "keep existing")
            self.assertFalse(public_path.exists())


if __name__ == "__main__":
    unittest.main()
