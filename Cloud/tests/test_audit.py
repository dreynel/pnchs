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
        roles = ['Admin', 'Administrator', 'Principal', 'Finance', 'Finance Officer']
        
        # Insert a dummy payroll period if none exists
        with db_cursor(commit=True) as (conn, cur):
            cur.execute("""
                INSERT INTO tblpayroll (period_key, year, month, half, status, is_released)
                VALUES ('TEST_AUDIT_2026_09_1', 2026, 9, 1, 'Approved', 1)
                ON CONFLICT (period_key) DO NOTHING
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

    def test_payroll_verification_calculation(self):
        with self.app.session_transaction() as sess:
            sess['user'] = {'name': 'Auditor Admin', 'role': 'Admin', 'employee_id': 'ADM-001'}

        res = self.app.get('/api/audit/payroll-verification?period_key=2026-8-2')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('summary', data)
        self.assertIn('details', data)
        self.assertEqual(data['period_key'], '2026-8-2')
        self.assertGreater(data['summary']['total_employees'], 0)
        self.assertIn('compliance_rate', data['summary'])
        
        # Verify first detail item mathematical formulas
        item = data['details'][0]
        self.assertIn('formulas', item)
        self.assertIn('daily_rate', item['formulas'])
        self.assertIn('gross_sum', item['formulas'])
        self.assertIn('ded_sum', item['formulas'])
        self.assertIn('net_sum', item['formulas'])
        self.assertIn(item['status'], ['ACCURATE', 'DISCREPANCY'])

    def test_payroll_verification_export_csv(self):
        with self.app.session_transaction() as sess:
            sess['user'] = {'name': 'Finance Lead', 'role': 'Finance', 'employee_id': 'FIN-001'}

        res = self.app.get('/api/audit/export-payroll-verification?period_key=2026-8-2')
        self.assertEqual(res.status_code, 200)
        self.assertIn('text/csv', res.headers.get('Content-Type', ''))
        csv_text = res.get_data(as_text=True)
        lines = csv_text.strip().splitlines()
        self.assertGreater(len(lines), 1, "CSV should contain header and employee data rows")
        header = lines[0]
        self.assertIn('Period Key', header)
        self.assertIn('Employee ID', header)
        self.assertIn('Audited Gross', header)
        self.assertIn('Audited Total Deductions', header)
        self.assertIn('Audited Net Pay', header)
        self.assertIn('Audit Status', header)

if __name__ == '__main__':
    unittest.main()
