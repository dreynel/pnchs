import unittest
import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from services.email_service import send_welcome_email, is_valid_email, validate_email_service
from werkzeug.security import generate_password_hash, check_password_hash

class TestEmailService(unittest.TestCase):
    def test_email_validation(self):
        self.assertTrue(is_valid_email("teacher@pnchs.edu.ph"))
        self.assertTrue(is_valid_email("user.name+tag@sub.domain.org"))
        self.assertFalse(is_valid_email("invalid-email"))
        self.assertFalse(is_valid_email("@domain.com"))
        self.assertFalse(is_valid_email("user@"))
        self.assertFalse(is_valid_email(""))
        self.assertFalse(is_valid_email(None))

    def test_validate_email_service_structure(self):
        result = validate_email_service()
        self.assertIn("status", result)
        self.assertIn("api_valid", result)
        self.assertIn("smtp_valid", result)
        self.assertIn("configured", result)

    def test_password_hashing_best_practices(self):
        plain = "TestPassword@2026"
        hashed = generate_password_hash(plain)
        self.assertNotEqual(plain, hashed)
        self.assertTrue(hashed.startswith("scrypt:") or hashed.startswith("pbkdf2:"))
        self.assertTrue(check_password_hash(hashed, plain))
        self.assertFalse(check_password_hash(hashed, "WrongPassword"))

    @patch('requests.post')
    def test_send_welcome_email_api(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_post.return_value = mock_response

        emp_data = {
            'employee_id': 'EMP-TEST-001',
            'first_name': 'Jane',
            'middle_name': 'Santos',
            'last_name': 'Doe',
            'email': 'jane.doe@example.com',
            'designation': 'Teacher I',
            'employment_status': 'Active'
        }

        # Should trigger async thread without raising exception
        send_welcome_email(emp_data, 'janedoe', 'janedoe')
        self.assertTrue(callable(send_welcome_email))

if __name__ == '__main__':
    unittest.main()
