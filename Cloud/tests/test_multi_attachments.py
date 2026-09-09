import unittest
import sys
import os
import io
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import app
from db import db_cursor

class TestMultiAttachments(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True
        self._cleanup()

    def tearDown(self):
        self._cleanup()

    def _cleanup(self):
        with db_cursor(commit=True) as (conn, cur):
            cur.execute("DELETE FROM tblapprovals WHERE RequesterID='TEST-EMP-001' OR DocNumber IN (SELECT CAST(id AS CHAR) FROM tblleaves WHERE employee_id='TEST-EMP-001')")
            cur.execute("DELETE FROM tblleaves WHERE employee_id='TEST-EMP-001'")
            cur.execute("DELETE FROM tblemployee WHERE employee_id='TEST-EMP-001'")

    def test_multi_attachment_leave_filing_and_approval_parsing(self):
        # Create dummy employee to satisfy foreign key constraint
        with db_cursor(commit=True) as (conn, cur):
            cur.execute("""
                INSERT IGNORE INTO tblemployee (employee_id, first_name, last_name, email, designation, contact, address)
                VALUES ('TEST-EMP-001', 'Test', 'Teacher', 'test@school.edu', 'Teacher I', '09123456789', 'Campus')
            """)

        with self.app.session_transaction() as sess:
            sess['user'] = {'employee_id': 'TEST-EMP-001', 'role': 'Teacher', 'username': 'testteacher'}

        data = {
            'leave_type': 'VL',
            'leave_date': '2026-10-15',
            'reason': 'Multi-file test leave',
            'attachment': [
                (io.BytesIO(b"file 1 content"), "doc1.pdf"),
                (io.BytesIO(b"file 2 content"), "img2.jpg")
            ]
        }

        res = self.app.post('/api/payroll/leaves', data=data, content_type='multipart/form-data')
        self.assertIn(res.status_code, [200, 201], f"Response: {res.get_data(as_text=True)}")
        resp_json = res.get_json()
        self.assertTrue(resp_json.get('success'))

        leave_id = None
        with db_cursor(commit=True) as (conn, cur):
            cur.execute("SELECT id, attachment FROM tblleaves WHERE employee_id='TEST-EMP-001' ORDER BY id DESC LIMIT 1")
            row = cur.fetchone()
            self.assertIsNotNone(row)
            leave_id = row['id']
            att_str = row['attachment']
            parsed_atts = json.loads(att_str)
            self.assertIsInstance(parsed_atts, list)
            self.assertEqual(len(parsed_atts), 2)
            self.assertTrue(parsed_atts[0].endswith("doc1.pdf"))
            self.assertTrue(parsed_atts[1].endswith("img2.jpg"))

        # Test approval endpoint fetching as HR
        with self.app.session_transaction() as sess:
            sess['user'] = {'employee_id': 'HR-001', 'role': 'HR', 'username': 'hruser'}

        app_res = self.app.get('/api/approvals?status=Pending&doc_type=Leave')
        self.assertEqual(app_res.status_code, 200)
        app_json = app_res.get_json()
        self.assertTrue(app_json.get('success'))
        
        target_approval = None
        for a in app_json.get('approvals', []):
            if a.get('DocNumber') == str(leave_id):
                target_approval = a
                break

        self.assertIsNotNone(target_approval, f"Approval entry for leave {leave_id} should be returned")
        details = target_approval.get('details', {})
        self.assertIn('attachments', details)
        self.assertEqual(len(details['attachments']), 2)

        # Clean up database test records
        with db_cursor(commit=True) as (conn, cur):
            cur.execute("DELETE FROM tblapprovals WHERE DocType='Leave' AND DocNumber=%s", (str(leave_id),))
            cur.execute("DELETE FROM tblleaves WHERE id=%s", (leave_id,))
            cur.execute("DELETE FROM tblemployee WHERE employee_id='TEST-EMP-001'")

if __name__ == '__main__':
    unittest.main()
