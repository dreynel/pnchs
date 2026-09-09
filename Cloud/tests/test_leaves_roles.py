import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app

class TestLeaveRoleAccessControls(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_unauthorized_leave_balance_adjust(self):
        # Unauthenticated request to adjust balance should fail
        res = self.app.post('/api/payroll/leave_balances/adjust', json={
            'employee_id': 'EMP-001',
            'leave_type': 'VL',
            'mode': 'ADD',
            'minutes': 480
        })
        self.assertIn(res.status_code, [401, 403])

if __name__ == '__main__':
    unittest.main()
