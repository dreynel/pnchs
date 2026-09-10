import unittest
from app import app

class HRRestrictionsTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_hr_restricted_pages(self):
        with self.app.session_transaction() as sess:
            sess['user'] = {'role': 'HR', 'username': 'hr_test'}

        for path in ['/pages/payroll.html', '/pages/payroll_releasing.html', '/pages/salary_grades.html', '/pages/registry.html', '/pages/payroll_report.html', '/pages/payroll_audit.html']:
            res = self.app.get(path)
            self.assertEqual(res.status_code, 403, f"Path {path} should return 403 for HR role")

    def test_hr_restricted_routes(self):
        with self.app.session_transaction() as sess:
            sess['user'] = {'role': 'HR', 'username': 'hr_test'}

        res = self.app.get('/salary_grades')
        self.assertEqual(res.status_code, 302)

        res = self.app.get('/registry')
        self.assertEqual(res.status_code, 302)

        res = self.app.get('/payroll_report')
        self.assertEqual(res.status_code, 302)

        res = self.app.get('/payroll_audit')
        self.assertEqual(res.status_code, 302)

    def test_hr_restricted_apis(self):
        with self.app.session_transaction() as sess:
            sess['user'] = {'role': 'HR', 'username': 'hr_test'}

        res = self.app.get('/api/salary_grades')
        self.assertEqual(res.status_code, 403)

        res = self.app.get('/api/registry/global_payheads')
        self.assertEqual(res.status_code, 403)

        res = self.app.get('/api/payroll/process')
        self.assertEqual(res.status_code, 403)

        res = self.app.get('/api/payroll/report')
        self.assertEqual(res.status_code, 403)

        res = self.app.get('/api/audit/payroll-periods')
        self.assertEqual(res.status_code, 403)

if __name__ == '__main__':
    unittest.main()
