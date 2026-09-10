import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app
from db import db_cursor

class TestApprovalsSystem(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_tblapprovals_exists(self):
        with db_cursor() as (conn, cur):
            cur.execute("SHOW TABLES LIKE 'tblapprovals'")
            res = cur.fetchone()
            self.assertIsNotNone(res, "tblapprovals should exist in database")

    def test_get_approvals_unauthorized(self):
        res = self.app.get('/api/approvals')
        self.assertEqual(res.status_code, 401)

    def test_approvals_fetching_and_approver_tracking(self):
        # Create test approval record in tblapprovals
        with db_cursor(commit=True) as (conn, cur):
            cur.execute("DELETE FROM tblapprovals WHERE DocNumber='999999'")
            cur.execute("""
                INSERT INTO tblapprovals (DocType, DocNumber, ApprovalStatus, ApproverRole, RequesterID, Title, Remarks)
                VALUES ('Leave', '999999', 'Pending', 'HR', 'Test Employee', 'Test Leave Request', 'Filing test')
            """)
            cur.execute("SELECT ApprovalID FROM tblapprovals WHERE DocNumber='999999'")
            row = cur.fetchone()
            app_id = row['ApprovalID']

        # Fetch as HR and verify default returns all statuses including Pending
        with self.app.session_transaction() as sess:
            sess['user'] = {'name': 'HR Manager', 'role': 'HR', 'employee_id': 'HR-001'}

        res = self.app.get('/api/approvals?status=all')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data.get('success'))
        items = data.get('approvals', [])
        test_item = next((i for i in items if i['DocNumber'] == '999999'), None)
        self.assertIsNotNone(test_item)
        self.assertEqual(test_item['RequesterID'], 'Test Employee')

        # Action (Approve) item and verify ApproverID tracking
        action_res = self.app.post(f'/api/approvals/{app_id}/action', json={
            'action': 'Approved',
            'remarks': 'Approved by HR test'
        })
        self.assertEqual(action_res.status_code, 200)

        with db_cursor() as (conn, cur):
            cur.execute("SELECT ApprovalStatus, ApproverID, Remarks FROM tblapprovals WHERE ApprovalID=%s", (app_id,))
            updated = cur.fetchone()
            self.assertEqual(updated['ApprovalStatus'], 'Approved')
            self.assertEqual(updated['ApproverID'], 'HR Manager')
            self.assertEqual(updated['Remarks'], 'Approved by HR test')

        # Clean up test row
        with db_cursor(commit=True) as (conn, cur):
            cur.execute("DELETE FROM tblapprovals WHERE DocNumber='999999'")

if __name__ == '__main__':
    unittest.main()
