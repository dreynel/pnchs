import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app
from db import db_cursor

class TestAuditRoutes(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_audit_unauthorized_role(self):
        with self.app.session_transaction() as sess:
            sess['user'] = {'name': 'Staff Member', 'role': 'Staff', 'employee_id': 'EMP-001'}

        res = self.app.get('/api/audit/payroll-periods')
        self.assertEqual(res.status_code, 403)

    def test_audit_authorized_roles(self):
        roles = ['Auditor', 'Admin', 'Administrator', 'Principal', 'Finance', 'Finance Officer']
        
        # Insert a dummy payroll period if none exists
        with db_cursor(commit=True) as (conn, cur):
            cur.execute("""
                INSERT IGNORE INTO tblpayroll (period_key, year, month, half, status, is_released)
                VALUES ('TEST_AUDIT_2026_09_1', 2026, 9, 1, 'Approved', 1)
            """)

        for role in roles:
            with self.app.session_transaction() as sess:
                sess['user'] = {'name': f'{role} User', 'role': role, 'employee_id': f'{role}-001'}

            res = self.app.get('/api/audit/payroll-periods')
            self.assertEqual(res.status_code, 200, f"Role {role} should be authorized to fetch audit payroll periods")
            data = res.get_json()
            self.assertIn('periods', data)
            self.assertTrue(len(data['periods']) > 0, "Periods list should contain records")

        # HR roles should return 403 Forbidden for payroll audit periods
        for role in ['HR', 'HR Officer']:
            with self.app.session_transaction() as sess:
                sess['user'] = {'name': f'{role} User', 'role': role, 'employee_id': f'{role}-001'}

            res = self.app.get('/api/audit/payroll-periods')
            self.assertEqual(res.status_code, 403, f"Role {role} should be restricted from audit payroll periods")

        # Clean up test period
        with db_cursor(commit=True) as (conn, cur):
            cur.execute("DELETE FROM tblpayroll WHERE period_key='TEST_AUDIT_2026_09_1'")

if __name__ == '__main__':
    unittest.main()
