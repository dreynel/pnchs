import unittest
import sys
import os
import json
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from app import app
from db import db_cursor
from werkzeug.security import generate_password_hash, check_password_hash

class TestPasswordSecurityAndValidation(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_employee_creation_password_encryption_and_email(self):
        """Test that registering an employee creates an encrypted password in tblusers and passes plain password to email."""
        test_emp_id = "EMP-TEST-SEC-01"
        test_email = "test.sec.employee@example.com"
        test_username = "testsecemp"

        with db_cursor(commit=True) as (conn, cur):
            # Clean up prior test data if exists
            cur.execute("DELETE FROM tblusers WHERE username = %s OR employee_id = %s", (test_username, test_emp_id))
            cur.execute("DELETE FROM tblemployee WHERE employee_id = %s", (test_emp_id,))

        with patch('routes.employee_routes.send_welcome_email') as mock_email:
            mock_email.return_value = {'success': True, 'method': 'Mock', 'message': 'Delivered'}
            
            with self.app.session_transaction() as sess:
                sess['user'] = {'role': 'HR', 'username': 'nsilguera', 'name': 'HR Admin'}

            payload = {
                'employee_id': test_emp_id,
                'first_name': 'Security',
                'last_name': test_username,
                'middle_name': 'Test',
                'designation': 'Teacher I',
                'employee_type': 'TEACHING',
                'employment_status': 'Active',
                'salary_grade': 11,
                'step': 1,
                'birthday': '1990-05-15',
                'email': test_email,
                'contact': '09123456789',
                'address': 'Pototan, Iloilo',
                'system_role': 'Employee'
            }

            res = self.app.post('/api/employees/', data=json.dumps(payload), content_type='application/json')
            self.assertEqual(res.status_code, 201)

            # 1. Verify email was called with readable plain password
            self.assertTrue(mock_email.called)
            called_args = mock_email.call_args[0]
            email_emp_data = called_args[0]
            email_username = called_args[1]
            email_raw_pwd = called_args[2]

            self.assertEqual(email_emp_data['email'], test_email)
            self.assertEqual(email_username, test_username)
            self.assertIsInstance(email_raw_pwd, str)
            self.assertGreaterEqual(len(email_raw_pwd), 8)

            # 2. Verify stored password in tblusers is ENCRYPTED / HASHED
            with db_cursor() as (conn, cur):
                cur.execute("SELECT password FROM tblusers WHERE employee_id = %s", (test_emp_id,))
                user_row = cur.fetchone()
                self.assertIsNotNone(user_row)
                stored_pwd = user_row['password']

                # Stored password MUST NOT be the raw password
                self.assertNotEqual(stored_pwd, email_raw_pwd)
                self.assertTrue(stored_pwd.startswith(('scrypt:', 'pbkdf2:', 'argon2:')))
                self.assertTrue(check_password_hash(stored_pwd, email_raw_pwd))
                self.assertFalse(check_password_hash(stored_pwd, "WrongPass123!"))

            # 3. Verify logging in with the generated credentials works
            login_client = app.test_client()
            login_res = login_client.post('/login', data={'email': test_username, 'password': email_raw_pwd}, follow_redirects=False)
            self.assertEqual(login_res.status_code, 302)
            self.assertIn(login_res.headers.get('Location', ''), ['/dtr', '/dashboard'])

            # 4. Verify logging in with wrong password fails
            bad_client = app.test_client()
            bad_login = bad_client.post('/login', data={'email': test_username, 'password': 'WrongPassword123'}, follow_redirects=True)
            self.assertIn(b'Invalid username or password', bad_login.data)

        # Cleanup
        with db_cursor(commit=True) as (conn, cur):
            cur.execute("DELETE FROM tblusers WHERE employee_id = %s", (test_emp_id,))
            cur.execute("DELETE FROM tblemployee WHERE employee_id = %s", (test_emp_id,))

    def test_change_password_validation_encryption_and_subsequent_login(self):
        """Test password change validations, hash encryption, and login with new password."""
        test_username = "test_pwd_change_user"
        initial_pwd = "OldPassword123!"
        new_pwd = "NewSecurePassword456@"

        with db_cursor(commit=True) as (conn, cur):
            cur.execute("DELETE FROM tblusers WHERE username = %s", (test_username,))
            cur.execute(
                "INSERT INTO tblusers (username, password, name, role) VALUES (%s, %s, %s, %s)",
                (test_username, generate_password_hash(initial_pwd), "Password Change Test", "Employee")
            )
            cur.execute("SELECT id FROM tblusers WHERE username = %s", (test_username,))
            user_id = cur.fetchone()['id']

        with self.app.session_transaction() as sess:
            sess['user'] = {
                'id': user_id,
                'username': test_username,
                'email': test_username,
                'name': 'Password Change Test',
                'role': 'Employee'
            }

        # 1. Validation test: Wrong current password
        res = self.app.post('/api/auth/change_password', json={
            'current_password': 'IncorrectOldPassword!',
            'new_password': new_pwd,
            'confirm_password': new_pwd
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn('Incorrect current password', res.get_json().get('error', ''))

        # 2. Validation test: Password too short (< 6 chars)
        res = self.app.post('/api/auth/change_password', json={
            'current_password': initial_pwd,
            'new_password': '123',
            'confirm_password': '123'
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn('at least 6 characters', res.get_json().get('error', ''))

        # 3. Validation test: Confirmation mismatch
        res = self.app.post('/api/auth/change_password', json={
            'current_password': initial_pwd,
            'new_password': new_pwd,
            'confirm_password': 'DifferentPassword789!'
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn('do not match', res.get_json().get('error', ''))

        # 4. Validation test: Identical to current password
        res = self.app.post('/api/auth/change_password', json={
            'current_password': initial_pwd,
            'new_password': initial_pwd,
            'confirm_password': initial_pwd
        })
        self.assertEqual(res.status_code, 400)
        self.assertIn('cannot be identical', res.get_json().get('error', ''))

        # 5. Successful password change
        res = self.app.post('/api/auth/change_password', json={
            'current_password': initial_pwd,
            'new_password': new_pwd,
            'confirm_password': new_pwd
        })
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.get_json().get('success'))

        # 6. Verify password in database is cryptographically encrypted
        with db_cursor() as (conn, cur):
            cur.execute("SELECT password FROM tblusers WHERE id = %s", (user_id,))
            updated_stored = cur.fetchone()['password']
            self.assertNotEqual(updated_stored, new_pwd)
            self.assertTrue(updated_stored.startswith(('scrypt:', 'pbkdf2:', 'argon2:')))
            self.assertTrue(check_password_hash(updated_stored, new_pwd))
            self.assertFalse(check_password_hash(updated_stored, initial_pwd))

        # 7. Verify logging in with old password now FAILS
        old_client = app.test_client()
        old_login = old_client.post('/login', data={'email': test_username, 'password': initial_pwd}, follow_redirects=True)
        self.assertIn(b'Invalid username or password', old_login.data)

        # 8. Verify logging in with new password SUCCEEDS
        new_client = app.test_client()
        new_login = new_client.post('/login', data={'email': test_username, 'password': new_pwd}, follow_redirects=False)
        self.assertEqual(new_login.status_code, 302)
        self.assertIn(new_login.headers.get('Location', ''), ['/dtr', '/dashboard'])

        # Cleanup
        with db_cursor(commit=True) as (conn, cur):
            cur.execute("DELETE FROM tblusers WHERE id = %s", (user_id,))

    def test_legacy_plaintext_password_auto_upgrades_to_hash_on_login(self):
        """Test that legacy plaintext passwords automatically upgrade to cryptographic hash on login."""
        test_username = "test_legacy_user"
        plain_pwd = "LegacyPlainPass2026!"

        with db_cursor(commit=True) as (conn, cur):
            cur.execute("DELETE FROM tblusers WHERE username = %s", (test_username,))
            # Store intentionally as plain text
            cur.execute(
                "INSERT INTO tblusers (username, password, name, role) VALUES (%s, %s, %s, %s)",
                (test_username, plain_pwd, "Legacy Plain User", "Employee")
            )

        # Verify it was stored as plaintext
        with db_cursor() as (conn, cur):
            cur.execute("SELECT password FROM tblusers WHERE username = %s", (test_username,))
            self.assertEqual(cur.fetchone()['password'], plain_pwd)

        # Log in with the plaintext password
        login_res = self.app.post('/login', data={'email': test_username, 'password': plain_pwd}, follow_redirects=False)
        self.assertEqual(login_res.status_code, 302)

        # Verify it has now been upgraded to a secure cryptographic hash
        with db_cursor() as (conn, cur):
            cur.execute("SELECT password FROM tblusers WHERE username = %s", (test_username,))
            upgraded_pwd = cur.fetchone()['password']
            self.assertNotEqual(upgraded_pwd, plain_pwd)
            self.assertTrue(upgraded_pwd.startswith(('scrypt:', 'pbkdf2:', 'argon2:')))
            self.assertTrue(check_password_hash(upgraded_pwd, plain_pwd))

        # Cleanup
        with db_cursor(commit=True) as (conn, cur):
            cur.execute("DELETE FROM tblusers WHERE username = %s", (test_username,))


if __name__ == '__main__':
    unittest.main()
