import unittest
from unittest.mock import patch

import test_security_and_print as fixture_module

server = fixture_module.server


class AuthenticationThrottleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.SecurityAndPrintTests()
        self.fixture.setUp()
        self.client = self.fixture.client
        self.limit_patch = patch.object(server, 'LOGIN_MAX_FAILURES', 2)
        self.limit_patch.start()

    def tearDown(self):
        self.limit_patch.stop()
        self.fixture.tearDown()

    def test_verify_endpoint_records_failures_locks_and_success_clears_counter(self):
        remote = {'REMOTE_ADDR': '198.51.100.10'}
        for _ in range(2):
            response = self.client.post('/api/auth/verify', json={'username': 'manager', 'password': 'bad'},
                                        environ_overrides=remote)
            self.assertEqual(response.status_code, 401)
        locked = self.client.post('/api/auth/verify', json={'username': 'manager', 'password': 'manager-pass'},
                                  environ_overrides=remote)
        self.assertEqual(locked.status_code, 429)

        data = server.load()
        self.assertGreater(server.login_throttle_remaining(data, 'manager', remote['REMOTE_ADDR']), 0)
        with patch.object(server.time, 'time', return_value=10 ** 12):
            unlocked = self.client.post('/api/auth/verify',
                                        json={'username': 'manager', 'password': 'manager-pass'},
                                        environ_overrides=remote)
        self.assertEqual(unlocked.status_code, 200)
        self.assertEqual(server.login_throttle_remaining(server.load(), 'manager', remote['REMOTE_ADDR']), 0)

    def test_manager_approval_and_manager_password_share_the_throttle_contract(self):
        data = server.load()
        with server.app.test_request_context('/api/orders/ORD-1/edit-items', environ_base={'REMOTE_ADDR': '198.51.100.11'}):
            for _ in range(2):
                ok, error = server.check_manager_password(data, {'username': 'manager', 'password': 'bad'})
                self.assertFalse(ok)
                self.assertEqual(error[1], 401)
            ok, error = server.check_manager_password(data, {'username': 'manager', 'password': 'manager-pass'})
            self.assertFalse(ok)
            self.assertEqual(error[1], 429)

        data = server.load()
        with server.app.test_request_context('/api/orders/ORD-2/void', environ_base={'REMOTE_ADDR': '198.51.100.12'}):
            for _ in range(2):
                record, error = server.verify_manager_approval(
                    data, {'manager_approval': {'username': 'manager', 'password': 'bad'}}, 'اختبار'
                )
                self.assertIsNone(record)
                self.assertEqual(error[1], 403)
            record, error = server.verify_manager_approval(
                data, {'manager_approval': {'username': 'manager', 'password': 'manager-pass'}}, 'اختبار'
            )
            self.assertIsNone(record)
            self.assertEqual(error[1], 429)

    def test_verify_current_password_is_throttled(self):
        self.assertEqual(self.fixture.login('cashier', 'cashier-pass').status_code, 200)
        remote = {'REMOTE_ADDR': '198.51.100.13'}
        for _ in range(2):
            response = self.client.post('/api/auth/verify-current', json={'password': 'bad'}, environ_overrides=remote)
            self.assertEqual(response.status_code, 401)
        response = self.client.post('/api/auth/verify-current', json={'password': 'cashier-pass'},
                                    environ_overrides=remote)
        self.assertEqual(response.status_code, 429)


if __name__ == '__main__':
    unittest.main()
