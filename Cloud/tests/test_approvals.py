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

if __name__ == '__main__':
    unittest.main()
