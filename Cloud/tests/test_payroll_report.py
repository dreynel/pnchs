import unittest
import sys
import os
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app
from db import db_cursor


class TestPayrollReportAndBiometrics(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def _login_as(self, role='Admin', username='admin_test'):
        with self.app.session_transaction() as sess:
            sess['user'] = {'role': role, 'username': username, 'name': 'Test Admin'}

    # ══════════════════════════════════════════════
    # PAYROLL REPORT TESTS
    # ══════════════════════════════════════════════

    def test_payroll_runs_endpoint(self):
        self._login_as('Admin')
        res = self.app.get('/api/payroll/runs')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIsInstance(data, list)

    def test_payroll_report_unauthorized_without_session(self):
        res = self.app.get('/api/payroll/report')
        self.assertIn(res.status_code, [401, 403])

    def test_payroll_report_modes(self):
        self._login_as('Finance')
        
        # Test Run Mode
        res = self.app.get('/api/payroll/report?filter_mode=run&run=all')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('records', data)
        self.assertIn('summary', data)
        self.assertIn('period_label', data)

        # Test Month Mode
        res = self.app.get('/api/payroll/report?filter_mode=month&month=9&year=2026')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('records', data)

        # Test Year Mode
        res = self.app.get('/api/payroll/report?filter_mode=year&year=2026')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('records', data)

        # Test Date Range Mode
        res = self.app.get('/api/payroll/report?filter_mode=range&date_from=2026-09-01&date_to=2026-09-30')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('records', data)

        # Test Daily Mode
        res = self.app.get('/api/payroll/report?filter_mode=daily&date=2026-09-26')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('records', data)

    def test_payroll_report_data_alias(self):
        self._login_as('Admin')
        res = self.app.get('/api/payroll/report_data?filter_mode=month&month=9&year=2026')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('records', data)
        self.assertIn('summary', data)

    # ══════════════════════════════════════════════
    # BIOMETRIC LOGS TESTS
    # ══════════════════════════════════════════════

    def test_biometric_today_categorized_default(self):
        res = self.app.get('/api/attendance/today_categorized')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('summary', data)
        self.assertIn('records', data)
        self.assertIn('raw_punches', data)
        self.assertIn('period_label', data)
        self.assertTrue(data.get('is_single_day'))
        
        # Check summary metrics presence
        summary = data['summary']
        for key in ['total_employees', 'am_in', 'am_out', 'pm_in', 'pm_out']:
            self.assertIn(key, summary)

    def test_biometric_categorized_daily_mode(self):
        res = self.app.get('/api/attendance/today_categorized?date_mode=daily&date=2026-09-26')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get('date_mode'), 'daily')
        self.assertTrue(data.get('is_single_day'))
        self.assertIsInstance(data.get('records'), list)

    def test_biometric_categorized_month_mode(self):
        res = self.app.get('/api/attendance/today_categorized?date_mode=month&month=9&year=2026')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get('date_mode'), 'month')
        self.assertFalse(data.get('is_single_day'))
        self.assertIn('September 2026', data.get('period_label', ''))

    def test_biometric_categorized_year_mode(self):
        res = self.app.get('/api/attendance/today_categorized?date_mode=year&year=2026')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get('date_mode'), 'year')
        self.assertFalse(data.get('is_single_day'))

    def test_biometric_categorized_range_mode(self):
        res = self.app.get('/api/attendance/today_categorized?date_mode=range&date_from=2026-09-01&date_to=2026-09-15')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get('date_mode'), 'range')
        self.assertFalse(data.get('is_single_day'))

    def test_biometric_logs_feed_data(self):
        res = self.app.get('/api/attendance/logs/data?date_mode=daily&date=2026-09-26')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIsInstance(data, list)


if __name__ == '__main__':
    unittest.main()
