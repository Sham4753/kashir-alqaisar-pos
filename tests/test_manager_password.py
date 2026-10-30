import unittest

import test_security_and_print as fixture_module

server = fixture_module.server


class ManagerPasswordTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.SecurityAndPrintTests()
        self.fixture.setUp()

    def tearDown(self):
        self.fixture.tearDown()

    def test_only_a_manager_password_is_accepted_for_sensitive_approval(self):
        data = server.load()
        with server.app.test_request_context('/api/orders/ORD-1/edit-items'):
            cashier_ok, cashier_error = server.check_manager_password(
                data, {'username': 'cashier', 'password': 'cashier-pass'}
            )
            supervisor_ok, supervisor_error = server.check_manager_password(
                data, {'username': 'supervisor', 'password': 'supervisor-pass'}
            )
            manager_ok, manager_error = server.check_manager_password(
                data, {'username': 'manager', 'password': 'manager-pass'}
            )
        self.assertFalse(cashier_ok)
        self.assertEqual(cashier_error[1], 401)
        self.assertFalse(supervisor_ok)
        self.assertEqual(supervisor_error[1], 401)
        self.assertTrue(manager_ok)
        self.assertIsNone(manager_error)


if __name__ == '__main__':
    unittest.main()
