import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app

class DashboardRolesValidationTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_principal_dashboard_access(self):
        with self.app.session_transaction() as sess:
            sess['user'] = {'role': 'Principal', 'username': 'principal_test', 'name': 'Principal User'}

        # Principal access
        allowed = [
            '/pages/dashboard.html',
            '/pages/payroll_report.html',
            '/pages/payroll_audit.html',
            '/pages/audit_trail.html',
            '/pages/approvals.html',
            '/pages/logs.html',
            '/pages/leaves.html',
            '/pages/dtr.html'
        ]
        for p in allowed:
            res = self.app.get(p)
            self.assertEqual(res.status_code, 200, f"Principal should have 200 access to {p}")

        # Principal restricted from employee registry and payroll processing
        restricted = [
            '/pages/employee.html',
            '/pages/payroll.html',
            '/pages/payroll_releasing.html',
            '/pages/salary_grades.html',
            '/pages/registry.html'
        ]
        for p in restricted:
            res = self.app.get(p)
            self.assertEqual(res.status_code, 403, f"Principal must be 403 restricted from {p}")

    def test_hr_dashboard_access_and_restrictions(self):
        with self.app.session_transaction() as sess:
            sess['user'] = {'role': 'HR', 'username': 'hr_test', 'name': 'HR Officer'}

        # Allowed for HR
        allowed = [
            '/pages/dashboard.html',
            '/pages/employee.html',
            '/pages/leaves.html',
            '/pages/approvals.html',
            '/pages/logs.html',
            '/pages/dtr.html'
        ]
        for p in allowed:
            res = self.app.get(p)
            self.assertEqual(res.status_code, 200, f"HR should have 200 access to {p}")

        # Restricted for HR (Must be hidden or protected on dashboard)
        restricted = [
            '/pages/payroll.html',
            '/pages/payroll_releasing.html',
            '/pages/salary_grades.html',
            '/pages/registry.html',
            '/pages/payroll_report.html',
            '/pages/payroll_audit.html',
            '/pages/audit_trail.html'
        ]
        for p in restricted:
            res = self.app.get(p)
            self.assertEqual(res.status_code, 403, f"HR must be 403 restricted from {p}")

    def test_finance_dashboard_access_and_restrictions(self):
        with self.app.session_transaction() as sess:
            sess['user'] = {'role': 'Finance', 'username': 'finance_test', 'name': 'Finance Officer'}

        # Allowed for Finance
        allowed = [
            '/pages/dashboard.html',
            '/pages/payroll.html',
            '/pages/payroll_releasing.html',
            '/pages/salary_grades.html',
            '/pages/registry.html',
            '/pages/payroll_report.html',
            '/pages/payroll_audit.html',
            '/pages/leaves.html',
            '/pages/logs.html',
            '/pages/dtr.html'
        ]
        for p in allowed:
            res = self.app.get(p)
            self.assertEqual(res.status_code, 200, f"Finance should have 200 access to {p}")

        # Restricted for Finance
        restricted = [
            '/pages/employee.html',
            '/pages/audit_trail.html',
            '/pages/approvals.html'
        ]
        for p in restricted:
            res = self.app.get(p)
            self.assertEqual(res.status_code, 403, f"Finance must be 403 restricted from {p}")

    def test_admin_dashboard_access_and_restrictions(self):
        with self.app.session_transaction() as sess:
            sess['user'] = {'role': 'Admin', 'username': 'admin_test', 'name': 'Admin User'}

        # Admin and Principal have the exact same access & restrictions
        allowed = [
            '/pages/dashboard.html',
            '/pages/payroll_report.html',
            '/pages/payroll_audit.html',
            '/pages/audit_trail.html',
            '/pages/approvals.html',
            '/pages/logs.html',
            '/pages/leaves.html',
            '/pages/dtr.html'
        ]
        for p in allowed:
            res = self.app.get(p)
            self.assertEqual(res.status_code, 200, f"Admin should have 200 access to {p}")

        # Restricted for Admin
        restricted = [
            '/pages/employee.html',
            '/pages/payroll.html',
            '/pages/payroll_releasing.html',
            '/pages/salary_grades.html',
            '/pages/registry.html'
        ]
        for p in restricted:
            res = self.app.get(p)
            self.assertEqual(res.status_code, 403, f"Admin must be 403 restricted from {p}")

    def test_dashboard_html_role_awareness(self):
        with self.app.session_transaction() as sess:
            sess['user'] = {'role': 'Principal', 'username': 'principal_test', 'name': 'Principal User'}

        res = self.app.get('/pages/dashboard.html')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Check required semantic IDs for role adaptation
        required_ids = [
            'wbStatEmployees',
            'wbStatCutoff',
            'wbStatGross',
            'kpiCardPayroll',
            'kpiCardEmployees',
            'kpiCardDeductions',
            'kpiCardDisbursement',
            'trendReportLink',
            'cutoffOpenCycleLink',
            'pdRowEmployees',
            'pdRowCycle',
            'pdRowStatus',
            'btnCutoffAction',
            'psBoxTotalEmps',
            'psBoxTeachingEmps',
            'psBoxNetPay',
            'psBoxPendingLeaves',
            'quickShortcutsGrid'
        ]
        for elem_id in required_ids:
            self.assertIn(elem_id, html, f"Dashboard HTML must contain semantic element #{elem_id}")

        # Check permission functions in script
        self.assertIn('function canRoleAccess', html)
        self.assertIn('function applyRolePermissions', html)
        self.assertIn('function normalizeRole', html)
        self.assertIn('Access Guard', html)

    def test_accounting_approval_restricted(self):
        with self.app.session_transaction() as sess:
            sess['user'] = {'role': 'Accounting', 'username': 'acct_test', 'name': 'Accounting Officer'}

        res = self.app.get('/dashboard')
        self.assertEqual(res.status_code, 200)
        html = res.data.decode('utf-8')

        # Accounting must NOT have the Payroll Approval nav-item in sidebar
        self.assertNotIn('Payroll Approval', html)
        self.assertNotIn('/payroll_approvals', html)

        # Accessing /payroll_approvals or /approvals redirects away to /dashboard
        res_app = self.app.get('/payroll_approvals')
        self.assertEqual(res_app.status_code, 302)
        self.assertIn('/dashboard', res_app.headers.get('Location', ''))

        res_app2 = self.app.get('/approvals')
        self.assertEqual(res_app2.status_code, 302)
        self.assertIn('/dashboard', res_app2.headers.get('Location', ''))

        # Direct access to /pages/approvals.html is 403 Forbidden
        res_page = self.app.get('/pages/approvals.html')
        self.assertEqual(res_page.status_code, 403)

if __name__ == '__main__':
    unittest.main()
