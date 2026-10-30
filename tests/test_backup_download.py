import json
import unittest

import test_security_and_print as fixture_module

server = fixture_module.server


def contains_sensitive_key(value):
    if isinstance(value, dict):
        return any(key in {'password_hash', 'license_key'} or contains_sensitive_key(item)
                   for key, item in value.items())
    if isinstance(value, list):
        return any(contains_sensitive_key(item) for item in value)
    return False


class BackupDownloadTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.SecurityAndPrintTests()
        self.fixture.setUp()
        self.client = self.fixture.client

    def tearDown(self):
        self.fixture.tearDown()

    def test_only_manager_can_download_a_backup_without_password_or_license_keys(self):
        self.assertEqual(self.fixture.login('supervisor', 'supervisor-pass').status_code, 200)
        self.assertEqual(self.client.get('/api/backup/download').status_code, 403)

        self.assertEqual(self.fixture.login('manager', 'manager-pass').status_code, 200)
        response = self.client.get('/api/backup/download')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, 'application/json')
        payload = json.loads(response.data.decode('utf-8'))
        self.assertFalse(contains_sensitive_key(payload))
        self.assertEqual(payload['settings']['restaurant']['name'], 'مطعم الاختبار')
        self.assertIn('license_id', payload['settings']['commercial'])


if __name__ == '__main__':
    unittest.main()
