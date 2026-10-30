import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = (ROOT / 'app/server.py').read_text(encoding='utf-8')
MANAGER = (ROOT / 'app/manager_ops.html').read_text(encoding='utf-8')
WELCOME = (ROOT / 'app/welcome.html').read_text(encoding='utf-8')
EXPENSES = (ROOT / 'app/expenses.html').read_text(encoding='utf-8')

class RegressionFixTests(unittest.TestCase):
    def test_release_tree_has_no_runtime_database_or_license_secret(self):
        self.assertFalse((ROOT / 'app/caesar.sqlite3').exists())
        self.assertFalse((ROOT / 'app/.license_secret').exists())

    def test_factory_reset_updates_sqlite_and_snapshot(self):
        self.assertIn("save(factory_data)", SERVER)
        self.assertIn("DELETE FROM order_items", SERVER)
        self.assertIn("DELETE FROM orders", SERVER)
        self.assertIn("atomic_write_json(DATA_FILE, _compact_state_snapshot(factory_data))", SERVER)

    def test_material_delete_reverses_cash_inventory_and_voids_expense(self):
        start = SERVER.index("def delete_material(mid):")
        end = SERVER.index("@app.route('/api/inventory'", start)
        block = SERVER[start:end]
        for marker in ("record_inventory_movement", "record_cash_movement", "e['voided']=True", "material_void"):
            self.assertIn(marker, block)

    def test_manager_operations_escape_user_values(self):
        self.assertIn('function esc(value)', MANAGER)
        self.assertIn('${esc(o.name)}', MANAGER)
        self.assertIn('${esc(m.name)}', MANAGER)
        self.assertIn('${esc(c.code)}', MANAGER)

    def test_welcome_does_not_put_username_in_inline_handler(self):
        self.assertNotIn("onclick=\"openPwModal('${u.username}'", WELCOME)
        self.assertIn("addEventListener('click'", WELCOME)
        self.assertIn("username.textContent", WELCOME)

    def test_expenses_ui_excludes_voided_rows_and_totals(self):
        self.assertIn('rows.filter(x=>!x.voided)', EXPENSES)

    def test_legacy_duplicate_brand_strings_are_removed_from_app_text(self):
        for suffix in ('.html', '.py', '.js', '.webmanifest', '.c'):
            for path in (ROOT / 'app').rglob(f'*{suffix}'):
                content = path.read_text(encoding='utf-8')
                with self.subTest(path=path.name):
                    self.assertNotIn('كاشير قيصر قيصر', content)
                    self.assertNotIn('مبيعات كاشير قيصر', content)
                    self.assertNotIn('AlCAESAR', content)

if __name__ == '__main__':
    unittest.main()
