from __future__ import annotations

import importlib.metadata
import json
import struct
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE_PACKAGES = ROOT / "Lib" / "site-packages"
if str(SITE_PACKAGES) not in sys.path:
    sys.path.insert(0, str(SITE_PACKAGES))


class EmbeddedManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((ROOT / "embedded_packages_manifest.json").read_text(encoding="utf-8"))

    def test_manifest_targets_the_expected_embedded_python_runtime(self):
        self.assertEqual(self.manifest["format"], 1)
        self.assertEqual(self.manifest["python"], "3.12")
        self.assertEqual(self.manifest["source"], "Lib/site-packages")
        distributions = [item["distribution"].casefold() for item in self.manifest["packages"]]
        self.assertEqual(len(distributions), len(set(distributions)))

    def test_declared_nonbundled_distribution_versions_match_embedded_metadata(self):
        for package in self.manifest["packages"]:
            with self.subTest(distribution=package["distribution"]):
                expected = package["version"]
                if expected == "bundled":
                    continue
                self.assertEqual(importlib.metadata.version(package["distribution"]), expected)

    def test_cffi_windows_native_import_and_pe_architecture_are_pinned(self):
        package = next(item for item in self.manifest["packages"] if item["distribution"].casefold() == "cffi")
        self.assertEqual(package["import"], "cffi")
        self.assertEqual(package["windows_native_import"], "_cffi_backend")
        self.assertEqual(package["windows_abi"], "CPython 3.12 x64")
        self.assertEqual(package["windows_native_file"], "Lib/site-packages/_cffi_backend.cp312-win_amd64.pyd")

        backend = ROOT / package["windows_native_file"]
        data = backend.read_bytes()
        self.assertEqual(data[:2], b"MZ")
        pe_offset = struct.unpack("<I", data[0x3C:0x40])[0]
        self.assertEqual(data[pe_offset : pe_offset + 4], b"PE\0\0")
        self.assertEqual(struct.unpack("<H", data[pe_offset + 4 : pe_offset + 6])[0], 0x8664)


if __name__ == "__main__":
    unittest.main()
