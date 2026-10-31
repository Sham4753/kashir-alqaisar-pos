from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LicenseIssuerLauncherTests(unittest.TestCase):
    def test_vendor_launcher_prompts_for_machine_id_and_uses_local_key(self):
        launcher = (ROOT / "tools" / "Issue_CAESAR_License.cmd").read_text(encoding="utf-8")
        generator = (ROOT / "generate_license.py").read_text(encoding="utf-8")
        self.assertIn("Enter the customer's Machine ID:", launcher)
        self.assertIn("caesar-vendor-private-v3.pem", launcher)
        self.assertIn('--machine-id "%MACHINE_ID%"', launcher)
        self.assertIn("--no-pause", launcher)
        self.assertIn("generate_license.py", launcher)
        self.assertIn('"--no-pause"', generator)
        self.assertNotIn("passphrase=", launcher.lower())

    def test_customer_packager_excludes_vendor_launcher(self):
        builder = (ROOT / "Setup_CAESAR_OneFile.ps1").read_text(encoding="utf-8-sig")
        self.assertIn("issue_caesar_license.cmd", builder.lower())
        self.assertIn('"Issue_CAESAR_License.cmd"', builder)


if __name__ == "__main__":
    unittest.main()
