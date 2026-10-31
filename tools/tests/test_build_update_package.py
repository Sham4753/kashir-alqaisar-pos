from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.asymmetric.rsa import generate_private_key

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from build_update_package import PackageError, build_package


class BuildUpdatePackageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "dist" / "CAESAR_POS"
        (self.source / "app").mkdir(parents=True)
        (self.source / "_internal").mkdir()
        (self.source / "CAESAR_POS.exe").write_bytes(b"windows executable mock")
        (self.source / "app" / "welcome.html").write_text("<h1>CAESAR</h1>", encoding="utf-8")
        (self.source / "app" / "license_crypto.py").write_text("# app licensing logic", encoding="utf-8")
        (self.source / "app" / "factory_data.json").write_text('{"menu": {}}', encoding="utf-8")
        vendor_license = self.source / "app" / "vendor" / "qrcode-8.2.dist-info" / "LICENSE"
        vendor_license.parent.mkdir(parents=True)
        vendor_license.write_text("Third-party package license notice", encoding="utf-8")
        public_key = Ed25519PrivateKey.generate().public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        (self.source / "app" / "license_public_key.pem").write_bytes(public_key)
        (self.source / "_internal" / "python312.dll").write_bytes(b"runtime mock")
        pythonnet_runtime = self.source / "_internal" / "pythonnet" / "runtime"
        pythonnet_runtime.mkdir(parents=True)
        (pythonnet_runtime / "Python.Runtime.deps.json").write_text('{"runtimeTarget": "netstandard2.0"}', encoding="utf-8")
        # Files that must never be shipped, even if present in a dirty build.
        (self.source / "app" / "restaurant.json").write_text('{"customers": ["private"]}', encoding="utf-8")
        (self.source / "app" / "license.json").write_text('{"license": "customer"}', encoding="utf-8")
        customer_license = self.source / "app" / "license" / "customer-license.txt"
        customer_license.parent.mkdir()
        customer_license.write_text("per-customer license", encoding="utf-8")
        (self.source / "app" / "customer-license.txt").write_text("per-customer license key", encoding="utf-8")
        (self.source / "app" / ".license_secret").write_text("signing secret", encoding="utf-8")
        (self.source / "app" / ".license").write_text("preconfigured license", encoding="utf-8")
        (self.source / "vault").mkdir()
        (self.source / "vault" / "store.sqlite3").write_bytes(b"sqlite mock")
        (self.source / "logs").mkdir()
        (self.source / "logs" / "server.log").write_text("private log", encoding="utf-8")
        (self.source / "app" / "restaurant.sqlite3-wal").write_bytes(b"private WAL data")
        (self.source / "app" / "restaurant.db-shm").write_bytes(b"private SHM data")
        (self.source / "app" / "vendor.p12").write_bytes(b"private certificate")
        (self.source / "misc" / "app").mkdir(parents=True)
        (self.source / "misc" / "app" / "factory_data.json").write_text('{"unexpected": true}', encoding="utf-8")
        (self.source / "misc" / "app" / "license_public_key.pem").write_bytes(public_key)
        (self.source / "generate_license.py").write_text("print('secret tool')", encoding="utf-8")
        self.output = self.root / "release" / "CAESAR_POS_Update_test-1.zip"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_zip_preserves_runtime_files_and_excludes_sensitive_files(self) -> None:
        included, excluded = build_package(self.source, self.output, "test-1")
        self.assertGreaterEqual(included, 5)
        self.assertGreaterEqual(excluded, 7)
        with zipfile.ZipFile(self.output) as archive:
            names = archive.namelist()
            self.assertIn("CAESAR_POS_Update_test-1/payload/CAESAR_POS/CAESAR_POS.exe", names)
            self.assertIn("CAESAR_POS_Update_test-1/payload/CAESAR_POS/app/welcome.html", names)
            self.assertIn("CAESAR_POS_Update_test-1/payload/CAESAR_POS/app/license_crypto.py", names)
            self.assertIn("CAESAR_POS_Update_test-1/payload/CAESAR_POS/app/factory_data.json", names)
            self.assertIn("CAESAR_POS_Update_test-1/payload/CAESAR_POS/app/license_public_key.pem", names)
            self.assertIn("CAESAR_POS_Update_test-1/payload/CAESAR_POS/app/vendor/qrcode-8.2.dist-info/LICENSE", names)
            self.assertNotIn("CAESAR_POS_Update_test-1/payload/CAESAR_POS/app/license/customer-license.txt", names)
            self.assertNotIn("CAESAR_POS_Update_test-1/payload/CAESAR_POS/app/customer-license.txt", names)
            self.assertNotIn("CAESAR_POS_Update_test-1/payload/CAESAR_POS/misc/app/factory_data.json", names)
            self.assertNotIn("CAESAR_POS_Update_test-1/payload/CAESAR_POS/misc/app/license_public_key.pem", names)
            self.assertIn("CAESAR_POS_Update_test-1/payload/CAESAR_POS/_internal/python312.dll", names)
            self.assertIn("CAESAR_POS_Update_test-1/payload/CAESAR_POS/_internal/pythonnet/runtime/Python.Runtime.deps.json", names)
            self.assertIn("CAESAR_POS_Update_test-1/Apply_CAESAR_Update.ps1", names)
            self.assertIn("CAESAR_POS_Update_test-1/Apply_CAESAR_Update.bat", names)
            self.assertIn("CAESAR_POS_Update_test-1/README_UPDATE_AR.txt", names)
            for name in names:
                lowered = name.casefold()
                self.assertNotRegex(lowered, r"(^|/)(vault|logs?)(/|$)")
                self.assertNotRegex(lowered, r"\.license_secret|license\.json|generate_license")
                if not lowered.endswith(("/app/factory_data.json", "/pythonnet/runtime/python.runtime.deps.json")):
                    self.assertFalse(lowered.endswith(".json"), name)
                self.assertFalse(lowered.endswith((".db", ".sqlite", ".sqlite3", ".log")), name)
                if lowered.endswith(".pem"):
                    self.assertTrue(lowered.endswith("/app/license_public_key.pem"), name)
            payload_bytes = b"".join(archive.read(name) for name in names if "/payload/" in name)
            self.assertNotIn(b"private", payload_bytes)
            self.assertNotIn(b"signing secret", payload_bytes)
            self.assertNotIn(b"private WAL data", payload_bytes)
            self.assertNotIn(b"private SHM data", payload_bytes)
            self.assertNotIn(b"private certificate", payload_bytes)

    def test_rejects_missing_executable(self) -> None:
        (self.source / "CAESAR_POS.exe").unlink()
        with self.assertRaises(PackageError):
            build_package(self.source, self.output, "test-1")
        self.assertFalse(self.output.exists())

    def test_rejects_missing_runtime_structure(self) -> None:
        import shutil

        shutil.rmtree(self.source / "app")
        shutil.rmtree(self.source / "_internal")
        with self.assertRaises(PackageError):
            build_package(self.source, self.output, "test-1")
        self.assertFalse(self.output.exists())

    def test_rejects_unsafe_version(self) -> None:
        with self.assertRaises(PackageError):
            build_package(self.source, self.output, "../release")
        self.assertFalse(self.output.exists())

    def test_rejects_symlink_in_source(self) -> None:
        link = self.source / "app" / "linked.dll"
        try:
            link.symlink_to(self.source / "_internal" / "python312.dll")
        except (OSError, NotImplementedError):
            self.skipTest("Symlinks are unavailable in this environment")
        with self.assertRaises(PackageError):
            build_package(self.source, self.output, "test-1")

    def test_rejects_rsa_or_private_key_at_public_key_path(self) -> None:
        rsa_key = generate_private_key(public_exponent=65537, key_size=2048)
        (self.source / "app" / "license_public_key.pem").write_bytes(rsa_key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo))
        with self.assertRaises(PackageError):
            build_package(self.source, self.output, "test-1")

        (self.source / "app" / "license_public_key.pem").write_bytes(rsa_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        with self.assertRaises(PackageError):
            build_package(self.source, self.output, "test-1")


if __name__ == "__main__":
    unittest.main()
