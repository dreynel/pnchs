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
        roles = ['Admin', 'Administrator', 'Principal', 'Finance', 'Finance Officer', 'Accounting', 'Accounting Officer']
        
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
        # Insert temporary test employee and payroll data
        with db_cursor(commit=True) as (conn, cur):
            cur.execute("""
                INSERT INTO tblemployee (employee_id, first_name, last_name, designation, email, contact, address)
                VALUES ('EMP-TEST-001', 'Test', 'Teacher', 'Teacher I', 'test@example.com', '1234', 'Campus')
                ON CONFLICT (employee_id) DO NOTHING
            """)
            cur.execute("""
                INSERT INTO tblpayroll (period_key, year, month, half, status, is_released)
                VALUES ('2026-8-2', 2026, 8, 2, 'Approved', 1)
                ON CONFLICT (period_key) DO NOTHING
            """)
            cur.execute("""
                INSERT INTO tblpayroll_details (period_key, employee_id, basic_salary, half_basic, total_gross, total_deduct, net_pay)
                VALUES ('2026-8-2', 'EMP-TEST-001', 30000.00, 15000.00, 15000.00, 2000.00, 13000.00)
                ON CONFLICT DO NOTHING
            """)

        with self.app.session_transaction() as sess:
            sess['user'] = {'name': 'Auditor Admin', 'role': 'Principal', 'employee_id': 'PRIN-001'}

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
            sess['user'] = {'name': 'Accounting Lead', 'role': 'Accounting', 'employee_id': 'ACC-001'}

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

        # Cleanup test seed
        with db_cursor(commit=True) as (conn, cur):
            cur.execute("DELETE FROM tblpayroll_details WHERE period_key='2026-8-2' AND employee_id='EMP-TEST-001'")
            cur.execute("DELETE FROM tblpayroll WHERE period_key='2026-8-2'")
            cur.execute("DELETE FROM tblemployee WHERE employee_id='EMP-TEST-001'")

    def test_audit_logs_and_summary_admin(self):
        with self.app.session_transaction() as sess:
            sess['user'] = {'name': 'Auditor Admin', 'role': 'Admin', 'employee_id': 'ADM-001'}

        # Test summary endpoint (resolved grouping query)
        res_sum = self.app.get('/api/audit/summary')
        self.assertEqual(res_sum.status_code, 200)
        sum_data = res_sum.get_json()
        self.assertIn('total', sum_data)
        self.assertIn('today', sum_data)
        self.assertIn('by_category', sum_data)
        self.assertIn('recent_users', sum_data)

        # Test logs endpoint with pagination and search
        res_logs = self.app.get('/api/audit/logs?page=1&per_page=10')
        self.assertEqual(res_logs.status_code, 200)
        logs_data = res_logs.get_json()
        self.assertIn('logs', logs_data)
        self.assertIn('total', logs_data)
        self.assertIn('total_pages', logs_data)

        # Test CSV export
        res_exp = self.app.get('/api/audit/export')
        self.assertEqual(res_exp.status_code, 200)
        self.assertIn('text/csv', res_exp.headers.get('Content-Type', ''))
        exp_lines = res_exp.get_data(as_text=True).strip().splitlines()
        self.assertGreater(len(exp_lines), 0)
        self.assertIn('Timestamp', exp_lines[0])

if __name__ == '__main__':
    unittest.main()
