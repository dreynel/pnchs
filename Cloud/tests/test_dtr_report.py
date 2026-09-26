import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app
from db import db_cursor


class TestDTRReport(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

        # Fetch a valid employee ID from DB for testing
        with db_cursor() as (conn, cur):
            cur.execute("SELECT employee_id FROM tblemployee LIMIT 1")
            row = cur.fetchone()
            self.test_emp_id = row['employee_id'] if row else 'EMP-000-001'

    def _login_as(self, role='Admin', username='admin_test'):
        with self.app.session_transaction() as sess:
            sess['user'] = {'role': role, 'username': username, 'name': 'Admin Tester'}

    def test_dtr_employees_endpoint(self):
        res = self.app.get('/api/dtr/employees')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIsInstance(data, list)
        if len(data) > 0:
            emp = data[0]
            self.assertIn('id', emp)
            self.assertIn('full_name', emp)
            self.assertIn('designation', emp)

    def test_dtr_report_validation(self):
        # Missing employee_id
        res = self.app.get('/api/dtr/report')
        self.assertEqual(res.status_code, 400)
        self.assertIn('employee_id is required', res.get_json().get('error', ''))

        # Non-existent employee_id
        res = self.app.get('/api/dtr/report?employee_id=NON_EXISTENT_ID_999999')
        self.assertEqual(res.status_code, 404)

    def test_dtr_report_month_mode(self):
        res = self.app.get(f'/api/dtr/report?employee_id={self.test_emp_id}&date_mode=month&month=9&year=2026')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()

        # Check top-level keys
        for key in ['employee', 'period', 'summary', 'summary_h1', 'summary_h2', 'days']:
            self.assertIn(key, data)

        # Check employee CS Form 48 info
        emp = data['employee']
        self.assertEqual(emp['id'], self.test_emp_id)
        self.assertIn('principal_name', emp)
        self.assertIn('principal_designation', emp)
        self.assertIn('schedule', emp)

        # Check summary metrics
        summary = data['summary']
        for key in ['total_present', 'total_halfday', 'total_absent', 'total_late_min', 'total_undertime_min', 'total_hours_dutied']:
            self.assertIn(key, summary)

        # Check days array (September has 30 days)
        days = data['days']
        self.assertEqual(len(days), 30)
        first_day = days[0]
        for key in ['day', 'date_str', 'weekday', 'is_weekend', 'am_in', 'am_out', 'pm_in', 'pm_out', 'status', 'hours']:
            self.assertIn(key, first_day)

    def test_dtr_report_daily_mode(self):
        res = self.app.get(f'/api/dtr/report?employee_id={self.test_emp_id}&date_mode=daily&date=2026-09-26')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('days', data)
        self.assertEqual(len(data['days']), 1)

    def test_dtr_report_range_mode(self):
        res = self.app.get(f'/api/dtr/report?employee_id={self.test_emp_id}&date_mode=range&date_from=2026-09-01&date_to=2026-09-10')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('days', data)
        self.assertEqual(len(data['days']), 10)

    def test_dtr_report_year_mode(self):
        res = self.app.get(f'/api/dtr/report?employee_id={self.test_emp_id}&date_mode=year&year=2026')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('days', data)
        self.assertEqual(len(data['days']), 365)

    def test_dtr_correct_authorization(self):
        # Unauthenticated request must be rejected
        res = self.app.post('/api/dtr/correct', json={
            'employee_id': self.test_emp_id,
            'work_date': '2026-09-26',
            'am_time_in': '07:30:00',
            'am_time_out': '11:30:00'
        })
        self.assertEqual(res.status_code, 403)

        # Authenticated Admin request is authorized
        self._login_as('Admin')
        res = self.app.post('/api/dtr/correct', json={
            'employee_id': self.test_emp_id,
            'work_date': '2026-09-26',
            'am_time_in': '07:30:00',
            'am_time_out': '11:30:00',
            'pm_time_in': '13:00:00',
            'pm_time_out': '17:00:00',
            'reason': 'Test correction'
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get('success'))


if __name__ == '__main__':
    unittest.main()
