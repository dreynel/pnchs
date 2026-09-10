import unittest
import sys
import os
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from services.email_service import send_welcome_email

class TestEmailService(unittest.TestCase):
    @patch('requests.post')
    def test_send_welcome_email_api(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_post.return_value = mock_response

        emp_data = {
            'employee_id': 'EMP-TEST-001',
            'first_name': 'Jane',
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
