import unittest

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from permissions import allowed_roles_for_request, page_allowed, role_can_access


class RbacPolicyTests(unittest.TestCase):
    def test_cashier_can_run_daily_operations(self):
        self.assertTrue(role_can_access("GET", "/api/menu", "cashier"))
        self.assertTrue(role_can_access("POST", "/api/orders", "cashier"))
        self.assertTrue(role_can_access("GET", "/api/sync/status", "cashier"))

    def test_cashier_cannot_access_management(self):
        self.assertFalse(role_can_access("GET", "/api/analytics", "cashier"))
        self.assertFalse(role_can_access("POST", "/api/category", "cashier"))
        self.assertFalse(role_can_access("POST", "/api/settings/users", "cashier"))

    def test_only_manager_can_void_an_order(self):
        self.assertTrue(role_can_access("POST", "/api/orders/123/void", "manager"))
        self.assertFalse(role_can_access("POST", "/api/orders/123/void", "cashier"))
        self.assertFalse(role_can_access("POST", "/api/orders/123/void", "supervisor"))

    def test_manager_can_access_management(self):
        self.assertTrue(role_can_access("GET", "/api/analytics", "manager"))
        self.assertTrue(role_can_access("POST", "/api/category", "manager"))
        self.assertEqual(allowed_roles_for_request("POST", "/api/category"), frozenset({"manager"}))

    def test_unknown_write_is_closed_by_default(self):
        self.assertFalse(role_can_access("POST", "/api/new-future-route", "cashier"))
        self.assertTrue(role_can_access("POST", "/api/new-future-route", "manager"))

    def test_page_roles_are_explicit(self):
        self.assertTrue(page_allowed("index.html", "cashier"))
        self.assertFalse(page_allowed("settings.html", "cashier"))
        self.assertTrue(page_allowed("settings.html", "manager"))


if __name__ == "__main__":
    unittest.main()
