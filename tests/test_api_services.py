import unittest
from unittest import mock
import sys
import os
import io
from werkzeug.datastructures import FileStorage

# Add the parent directory to the Python path to allow module imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Firebase app should be initialized by conftest.py before this runs.
from app import app # Import the Flask app instance
import firebase_admin # Still needed for firestore.Increment etc.
# from firebase_admin import credentials # No longer needed here
# from google.auth import credentials as google_auth_credentials # No longer needed here

import api_services
import firestore_utils # Required for firestore.Increment
# We will mock firestore_utils.get_user, firestore_utils.create_web_content_item, etc.
# and firestore_utils.db directly for specific calls like increment.

# # Mock firebase_admin before it's imported by other modules if not already initialized
# if 'firebase_admin' not in sys.modules:
#     firebase_admin_mock = mock.MagicMock()
#     sys.modules['firebase_admin'] = firebase_admin_mock
#     sys.modules['firebase_admin.firestore'] = firebase_admin_mock.firestore

class TestApiServices(unittest.TestCase):

    def setUp(self):
        # self.mock_api_services_current_app = mock_api_services_current_app # Removed
        # Ensure config is a dictionary on the mock_current_app for patch.dict to work as expected
        # self.mock_api_services_current_app.config = {'PHOTO_UPLOAD_LIMIT': 25} # Default # Removed

        self.mock_app_logger = mock.MagicMock()
        self.mock_bucket_client = mock.MagicMock()

        # Patching firestore_utils functions and using addCleanup
        self.patch_get_user = mock.patch('firestore_utils.get_user')
        self.mock_get_user = self.patch_get_user.start()
        self.addCleanup(self.patch_get_user.stop)

        self.patch_create_web_content_item = mock.patch('firestore_utils.create_web_content_item')
        self.mock_create_web_content_item = self.patch_create_web_content_item.start()
        self.addCleanup(self.patch_create_web_content_item.stop)

        self.patch_get_db_client = mock.patch('firestore_utils.get_db_client') # Changed
        self.mock_get_db_client = self.patch_get_db_client.start()
        self.addCleanup(self.patch_get_db_client.stop)
        # Configure the mock_get_db_client to return a mock db instance
        self.mock_db_instance = mock.MagicMock()
        self.mock_get_db_client.return_value = self.mock_db_instance

        self.mock_user_doc_ref = mock.MagicMock()
        # All db interactions should now go via self.mock_db_instance
        self.mock_db_instance.collection('users').document.return_value = self.mock_user_doc_ref

        self.patch_firestore_increment = mock.patch('firebase_admin.firestore.firestore.Increment') # Patching the actual Increment class
        self.mock_Increment_class = self.patch_firestore_increment.start() # This is now a mock of the class
        self.addCleanup(self.patch_firestore_increment.stop)
        # No specific return_value for the class mock itself,
        # but calls to it, e.g., Increment(1), will return a new MagicMock instance.

        self.patch_upload_image = mock.patch('image_utils.upload_image_to_gcs')
        self.mock_upload_image_to_gcs = self.patch_upload_image.start()
        self.addCleanup(self.patch_upload_image.stop)

        # Common test data
        self.user_id = "test_user_123"
        self.form_data = {
            'text': 'Test content',
            'latitude': '10.0',
            'longitude': '20.0'
        }
        self.allowed_extensions = ['jpg', 'jpeg', 'png']
        self.max_image_size = 5 * 1024 * 1024 # 5MB

    def tearDown(self):
        # self.addCleanup handles stopping patches, so tearDown is not strictly needed for this.
        pass

    # The @mock.patch.dict decorator will target the 'config' attribute of the
    # Patching app.config directly within an app_context


    def test_create_new_content_no_image_counter_not_incremented(self):
        # Configure mocks
        # get_user will not be called if no image is in files, so no need to set it up unless logic changes
        # However, the current implementation calls get_user if 'image' key is present, even if file is invalid.
        # For a "no image" test, we should ensure 'image' key is NOT in files.
        self.mock_create_web_content_item.return_value = "test_content_id_456"

        files = {} # No image file

        # Call the function
        response = api_services.create_new_content_from_api(
            self.form_data, files, self.user_id, self.mock_app_logger,
            self.mock_bucket_client, self.allowed_extensions, self.max_image_size
        )

        # Assertions
        self.assertEqual(response['status'], 'success')
        self.assertEqual(response['http_code'], 201)
        self.assertEqual(response['contentId'], "test_content_id_456")

        self.mock_upload_image_to_gcs.assert_not_called()
        self.mock_get_user.assert_not_called() # Should not be called if no 'image' in files

        # Check content_data passed to create_web_content_item
        args_create_item, _ = self.mock_create_web_content_item.call_args
        created_content_data = args_create_item[0]
        self.assertIsNone(created_content_data['imageUrl']) # Expecting imageUrl to be None

        # Assert that counter was not incremented
        self.mock_user_doc_ref.update.assert_not_called()


class TestUpdateContentItem(unittest.TestCase):
    def setUp(self):
        self.mock_app_logger = mock.MagicMock()
        self.content_id = "test_content_id"
        self.user_id = "test_user_id"
        self.owner_user_id = "test_user_id" # Same as user_id for successful cases
        self.other_user_id = "other_user_id"
        self.initial_text = "Initial content text"
        self.updated_text = "Updated content text"

        # Mock firestore_utils functions
        self.patch_get_content_item = mock.patch('firestore_utils.get_content_item')
        self.mock_get_content_item = self.patch_get_content_item.start()
        self.addCleanup(self.patch_get_content_item.stop)

        self.patch_update_web_content_item = mock.patch('firestore_utils.update_web_content_item')
        self.mock_update_web_content_item = self.patch_update_web_content_item.start()
        self.addCleanup(self.patch_update_web_content_item.stop)

        # Default mock behaviors
        self.mock_get_content_item.return_value = {
            'itemId': self.content_id,
            'userId': self.owner_user_id,
            'text': self.initial_text
        }
        self.mock_update_web_content_item.return_value = True

        # Config values (not used by current version of update_content_item, but good for completeness)
        self.gcs_bucket_name = "test-bucket"
        self.allowed_extensions = {'png', 'jpg'}
        self.max_image_size_bytes = 1024 * 1024 * 5


    def call_update_service(self, data_override=None, user_id_override=None):
        payload = {'text': self.updated_text}
        if data_override is not None: # Allow providing empty dict or specific field
            payload = data_override

        current_user_id = user_id_override if user_id_override is not None else self.user_id

        return api_services.update_content_item(
            content_id=self.content_id,
            user_id=current_user_id,
            data=payload,
            app_logger=self.mock_app_logger,
            gcs_bucket_name=self.gcs_bucket_name,
            allowed_extensions=self.allowed_extensions,
            max_image_size_bytes=self.max_image_size_bytes
        )

    def test_update_success(self):
        response = self.call_update_service()
        self.assertEqual(response['status'], 'success')
        self.assertEqual(response['http_code'], 200)
        self.assertEqual(response['message'], 'Content updated successfully')
        self.assertIn('text', response['updated_fields'])
        self.mock_get_content_item.assert_called_once_with(self.content_id, self.mock_app_logger)
        self.mock_update_web_content_item.assert_called_once_with(
            self.content_id, {'text': self.updated_text}, self.mock_app_logger
        )

    def test_update_no_changes_text_same(self):
        self.mock_get_content_item.return_value = {
            'itemId': self.content_id,
            'userId': self.owner_user_id,
            'text': self.updated_text # Text is already the updated text
        }
        response = self.call_update_service({'text': self.updated_text}) # Provide the same text
        self.assertEqual(response['status'], 'info')
        self.assertEqual(response['http_code'], 200)
        self.assertEqual(response['message'], 'No changes provided or fields are already up-to-date')
        self.mock_update_web_content_item.assert_not_called()

    def test_update_no_changes_no_relevant_data_provided(self):
        response = self.call_update_service(data_override={}) # Empty data
        self.assertEqual(response['status'], 'info')
        self.assertEqual(response['http_code'], 200)
        self.assertEqual(response['message'], 'No changes provided or fields are already up-to-date')
        self.mock_update_web_content_item.assert_not_called()

    def test_update_content_not_found(self):
        self.mock_get_content_item.return_value = None
        response = self.call_update_service()
        self.assertEqual(response['status'], 'error')
        self.assertEqual(response['http_code'], 404)
        self.assertEqual(response['message'], 'Content not found')
        self.mock_update_web_content_item.assert_not_called()

    def test_update_unauthorized_wrong_user(self):
        self.mock_get_content_item.return_value['userId'] = self.other_user_id # Item owned by someone else
        response = self.call_update_service() # Called by self.user_id
        self.assertEqual(response['status'], 'error')
        self.assertEqual(response['http_code'], 403)
        self.assertEqual(response['message'], 'User not authorized to edit this content')
        self.mock_update_web_content_item.assert_not_called()

    def test_update_firestore_fails(self):
        self.mock_update_web_content_item.return_value = False # Simulate Firestore update failure
        response = self.call_update_service()
        self.assertEqual(response['status'], 'error')
        self.assertEqual(response['http_code'], 500)
        self.assertEqual(response['message'], 'Failed to update content in database')

    def test_update_unexpected_error_get_content_item_raises(self):
        self.mock_get_content_item.side_effect = Exception("Unexpected DB error")
        response = self.call_update_service()
        self.assertEqual(response['status'], 'error')
        self.assertEqual(response['http_code'], 500)
        self.assertEqual(response['message'], 'An unexpected error occurred')
        self.mock_update_web_content_item.assert_not_called()

    def test_update_unexpected_error_update_web_content_item_raises(self):
        self.mock_update_web_content_item.side_effect = Exception("Unexpected DB update error")
        response = self.call_update_service()
        self.assertEqual(response['status'], 'error')
        self.assertEqual(response['http_code'], 500)
        self.assertEqual(response['message'], 'An unexpected error occurred')

if __name__ == '__main__':
    unittest.main()
