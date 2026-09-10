import unittest
from app import app

class HRRestrictionsTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_hr_restricted_pages(self):
        with self.app.session_transaction() as sess:
            sess['user'] = {'role': 'HR', 'username': 'hr_test'}

        for path in ['/pages/payroll.html', '/pages/payroll_releasing.html', '/pages/salary_grades.html', '/pages/registry.html', '/pages/payroll_report.html', '/pages/payroll_audit.html', '/pages/audit_trail.html']:
            res = self.app.get(path)
            self.assertEqual(res.status_code, 403, f"Path {path} should return 403 for HR role")

    def test_hr_restricted_routes(self):
        with self.app.session_transaction() as sess:
            sess['user'] = {'role': 'HR', 'username': 'hr_test'}

        for path in ['/salary_grades', '/registry', '/payroll_report', '/payroll_audit', '/audit_trail']:
            res = self.app.get(path)
            self.assertEqual(res.status_code, 302)

    def test_finance_restricted_audit_trail(self):
        with self.app.session_transaction() as sess:
            sess['user'] = {'role': 'Finance', 'username': 'finance_test'}

        res = self.app.get('/pages/audit_trail.html')
        self.assertEqual(res.status_code, 403)

        res = self.app.get('/audit_trail')
        self.assertEqual(res.status_code, 302)

        res = self.app.get('/api/audit/logs')
        self.assertEqual(res.status_code, 403)

    def test_hr_restricted_apis(self):
        with self.app.session_transaction() as sess:
            sess['user'] = {'role': 'HR', 'username': 'hr_test'}

        for path in ['/api/salary_grades', '/api/registry/global_payheads', '/api/payroll/process', '/api/payroll/report', '/api/audit/payroll-periods', '/api/audit/logs']:
            res = self.app.get(path)
            self.assertEqual(res.status_code, 403)

if __name__ == '__main__':
    unittest.main()
