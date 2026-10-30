import json
import unittest
from pathlib import Path

import test_security_and_print as fixture_module

server = fixture_module.server


class BackupRestoreTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.SecurityAndPrintTests()
        self.fixture.setUp()
        self.client = self.fixture.client
        self.assertEqual(self.fixture.login('manager', 'manager-pass').status_code, 200)
        data = server.load()
        today = '2026-10-30T12:00:00'
        data['orders'] = [{'id': 'ORD-LIVE', 'timestamp': today, 'items': [], 'total': 10, 'payment': 'نقدي'}]
        data['orders_archive'] = [{'id': 'ORD-ARCHIVE', 'timestamp': today, 'items': [], 'total': 20, 'payment': 'نقدي'}]
        server.save(data, ['ORD-LIVE', 'ORD-ARCHIVE'])
        server.atomic_write_json(server._cold_archive_path('2025-01'), [
            {'id': 'ORD-COLD', 'timestamp': '2025-01-10T12:00:00', 'items': [], 'total': 30, 'payment': 'نقدي'}
        ])

    def tearDown(self):
        self.fixture.tearDown()

    def test_backup_bundle_contains_hot_and_cold_archives_and_daily_copy(self):
        server.backup(force=True)
        backup_files = list(Path(server.BACKUP_DIR).glob('backup_*.json'))
        daily_files = list(Path(server.BACKUP_DIR).glob('daily_*.json'))
        self.assertTrue(backup_files)
        self.assertTrue(daily_files)
        bundle = json.loads(backup_files[-1].read_text(encoding='utf-8'))
        self.assertEqual(bundle['format_version'], server.BACKUP_FORMAT_VERSION)
        self.assertEqual({row['id'] for row in bundle['state']['orders_archive']}, {'ORD-ARCHIVE'})
        self.assertEqual(bundle['archive_cold']['2025-01'][0]['id'], 'ORD-COLD')

    def test_manager_restore_requires_confirmation_and_preserves_previous_cold_archive(self):
        bundle = server.build_backup_bundle()
        self.assertEqual(self.client.post('/api/backup/restore', json={'backup': bundle}).status_code, 400)

        changed = server.load()
        changed['settings']['restaurant']['name'] = 'حالة معدلة'
        server.save(changed)
        response = self.client.post('/api/backup/restore', json={'confirmation': 'RESTORE', 'backup': bundle})
        self.assertEqual(response.status_code, 200)
        restored = server.load()
        self.assertEqual(restored['settings']['restaurant']['name'], 'مطعم الاختبار')
        self.assertEqual({row['id'] for row in restored['orders_archive']}, {'ORD-ARCHIVE'})
        self.assertEqual(json.loads(Path(server._cold_archive_path('2025-01')).read_text(encoding='utf-8'))[0]['id'], 'ORD-COLD')
        self.assertTrue(list(Path(server.BACKUP_DIR).glob('archive_cold_pre_restore_*')))


if __name__ == '__main__':
    unittest.main()
