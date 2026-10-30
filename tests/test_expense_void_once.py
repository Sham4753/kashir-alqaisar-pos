import unittest

import test_security_and_print as fixture_module

server = fixture_module.server


class ExpenseVoidOnceTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.SecurityAndPrintTests()
        self.fixture.setUp()
        self.client = self.fixture.client
        self.assertEqual(self.fixture.login('manager', 'manager-pass').status_code, 200)

    def tearDown(self):
        self.fixture.tearDown()

    def test_deleting_an_already_voided_expense_does_not_reverse_cash_twice(self):
        created = self.client.post('/api/expenses', json={
            'amount': 125, 'note': 'مصروف اختبار', 'payment': 'نقدي'
        })
        self.assertEqual(created.status_code, 200)
        expense_id = created.get_json()['expense']['id']

        self.assertEqual(self.client.delete(f'/api/expenses/{expense_id}').status_code, 200)
        movements_after_first_void = [
            row for row in server.load()['cash_movements']
            if str(row.get('reference_id')) == str(expense_id)
        ]
        self.assertEqual([row['reference_type'] for row in movements_after_first_void], ['expense', 'expense_void'])

        second = self.client.delete(f'/api/expenses/{expense_id}')
        self.assertEqual(second.status_code, 404)
        movements_after_second_void = [
            row for row in server.load()['cash_movements']
            if str(row.get('reference_id')) == str(expense_id)
        ]
        self.assertEqual(movements_after_second_void, movements_after_first_void)


if __name__ == '__main__':
    unittest.main()
