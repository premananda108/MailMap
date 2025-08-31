import unittest
from unittest import mock
from datetime import datetime, timedelta, timezone
import sys
import os

# Add the parent directory to the Python path to allow module imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Firebase app should be initialized by conftest.py before this runs.
# Ensure mock is imported if it's used standalone in the test class setup or methods.
from unittest import mock
import firebase_admin # Still needed for firestore.SERVER_TIMESTAMP etc.
# from firebase_admin import credentials # No longer needed here
# from google.auth import credentials as google_auth_credentials # No longer needed here

import firestore_utils

class TestFirestoreUtils(unittest.TestCase):

    @mock.patch('firestore_utils.datetime')
    @mock.patch('firestore_utils.get_db_client') # Changed from 'firestore_utils.db'
    def test_create_user_period_end(self, mock_get_db_client, mock_datetime):
        # Configure mocks
        mock_db_instance = mock.MagicMock() # This will simulate the db client
        mock_get_db_client.return_value = mock_db_instance
        mock_user_set = mock.MagicMock()
        mock_db_instance.collection('users').document.return_value.set = mock_user_set

        fixed_now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = fixed_now
        # This mock is for firestore_utils.datetime.now used inside create_user
        # The datetime, timedelta, timezone imported in this test file are for test logic itself.

        # Call the function
        uid = "test_uid"
        email = "test@example.com"
        display_name = "Test User"
        provider = "test_provider"

        firestore_utils.create_user(uid, email, display_name, provider, app_logger=mock.MagicMock())

        # Assertions
        self.assertTrue(mock_user_set.called)
        args, kwargs = mock_user_set.call_args

        # The actual call is user_ref.set(user_data), so user_data is the first positional argument
        called_user_data = args[0]

        expected_period_end = fixed_now + timedelta(days=30)

        self.assertEqual(called_user_data['uid'], uid)
        self.assertEqual(called_user_data['email'], email)
        self.assertEqual(called_user_data['createdAt'], firestore_utils.firestore.SERVER_TIMESTAMP)
        self.assertEqual(called_user_data['current_period_start'], fixed_now)
        self.assertEqual(called_user_data['current_period_end'], expected_period_end)
        self.assertEqual(called_user_data['subscription_plan'], 'free')

if __name__ == '__main__':
    unittest.main()
