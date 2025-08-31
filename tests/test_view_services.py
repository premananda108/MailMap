import unittest
from unittest import mock
import sys
import os

# Add the parent directory to the Python path to allow module imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Firebase app should be initialized by conftest.py before this runs.
# import firebase_admin # May not be needed directly in this file
# from firebase_admin import credentials # No longer needed here
# from google.auth import credentials as google_auth_credentials # No longer needed here

import view_services
# firestore_utils will be mocked, so direct import isn't strictly needed in the test file itself
# but it's good to be aware of what's being mocked.

class TestViewServices(unittest.TestCase):

    def setUp(self):
        self.mock_logger = mock.MagicMock()

        # Patch firestore_utils functions used by view_services
        self.patch_get_published_items = mock.patch('firestore_utils.get_published_items_for_map')
        self.mock_get_published_items_for_map = self.patch_get_published_items.start()
        # Configure a default return value for items_for_map, as it's not the focus here
        self.mock_get_published_items_for_map.return_value = []

        self.patch_get_user = mock.patch('firestore_utils.get_user')
        self.mock_get_user = self.patch_get_user.start()

        self.dummy_maps_api_key = "dummy_api_key"

    def tearDown(self):
        self.patch_get_published_items.stop()
        self.patch_get_user.stop()

    def test_get_home_page_data_user_logged_in_with_photos(self):
        user_id = "test_user_id_1"
        self.mock_get_user.return_value = {'photo_upload_count_current_month': 5}

        context = view_services.get_home_page_data(
            app_logger=self.mock_logger,
            maps_api_key=self.dummy_maps_api_key,
            logged_in_user_id=user_id
        )

        self.assertEqual(context['remaining_photos'], 20)
        self.mock_get_user.assert_called_once_with(user_id, self.mock_logger)
        self.mock_logger.info.assert_called_with(f"User {user_id}: Uploaded 5 photos this month (Limit: 25). Remaining: 20.")

    def test_get_home_page_data_user_logged_in_limit_reached(self):
        user_id = "test_user_id_2"
        test_limit = 10
        self.mock_get_user.return_value = {'photo_upload_count_current_month': test_limit} # At the limit

        context = view_services.get_home_page_data(
            app_logger=self.mock_logger,
            maps_api_key=self.dummy_maps_api_key,
            logged_in_user_id=user_id,
            photo_upload_limit=test_limit
        )

        self.assertEqual(context['remaining_photos'], 0)
        self.mock_get_user.assert_called_once_with(user_id, self.mock_logger)
        self.mock_logger.info.assert_called_with(f"User {user_id}: Uploaded {test_limit} photos this month (Limit: {test_limit}). Remaining: 0.")


    def test_get_home_page_data_user_logged_in_over_limit(self):
        user_id = "test_user_id_3"
        test_limit = 20
        self.mock_get_user.return_value = {'photo_upload_count_current_month': test_limit + 5} # Over the limit

        context = view_services.get_home_page_data(
            app_logger=self.mock_logger,
            maps_api_key=self.dummy_maps_api_key,
            logged_in_user_id=user_id,
            photo_upload_limit=test_limit
        )

        self.assertEqual(context['remaining_photos'], 0) # Should not be negative
        self.mock_get_user.assert_called_once_with(user_id, self.mock_logger)
        self.mock_logger.info.assert_called_with(f"User {user_id}: Uploaded {test_limit+5} photos this month (Limit: {test_limit}). Remaining: 0.")

    def test_get_home_page_data_user_not_logged_in(self):
        test_limit = 15 # This limit won't be used but needs to be passed
        context = view_services.get_home_page_data(
            app_logger=self.mock_logger,
            maps_api_key=self.dummy_maps_api_key,
            logged_in_user_id=None,
            photo_upload_limit=test_limit
        )

        self.assertIsNone(context['remaining_photos'])
        self.mock_get_user.assert_not_called()

    def test_get_home_page_data_user_logged_in_user_not_found(self):
        user_id = "test_user_id_not_found"
        test_limit = 10
        self.mock_get_user.return_value = None # Simulate user not found

        context = view_services.get_home_page_data(
            app_logger=self.mock_logger,
            maps_api_key=self.dummy_maps_api_key,
            logged_in_user_id=user_id,
            photo_upload_limit=test_limit
        )

        self.assertIsNone(context['remaining_photos'])
        self.mock_get_user.assert_called_once_with(user_id, self.mock_logger)
        self.mock_logger.warning.assert_called_with(f"Logged-in user ID {user_id} provided, but user data not found.")

    def test_get_home_page_data_user_logged_in_photo_count_missing(self):
        user_id = "test_user_id_no_count"
        test_limit = 30
        # Simulate user data exists but 'photo_upload_count_current_month' key is missing
        self.mock_get_user.return_value = {'uid': user_id, 'email': 'test@example.com'}

        context = view_services.get_home_page_data(
            app_logger=self.mock_logger,
            maps_api_key=self.dummy_maps_api_key,
            logged_in_user_id=user_id,
            photo_upload_limit=test_limit
        )

        # Expecting default of 0 for count, so test_limit remaining
        self.assertEqual(context['remaining_photos'], test_limit)
        self.mock_get_user.assert_called_once_with(user_id, self.mock_logger)
        self.mock_logger.info.assert_called_with(f"User {user_id}: Uploaded 0 photos this month (Limit: {test_limit}). Remaining: {test_limit}.")

if __name__ == '__main__':
    unittest.main()
