import unittest
from unittest.mock import patch, MagicMock

# Assuming your Flask app instance is named 'app' in 'app.py'
# You might need to adjust the import based on your project structure
# For example, if app.py is in the root, and tests is a subdir:
import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Firebase app should be initialized by conftest.py before this runs.
# import firebase_admin # May not be needed if app.py doesn't directly use it before routes
# from firebase_admin import credentials # No longer needed here
# from google.auth import credentials as google_auth_credentials # No longer needed here
from google.auth import credentials as google_auth_credentials # Needed for spec in mocks
from unittest import mock # Import mock

from app import app

# # Mock firebase_admin before it's used by the app
# # This is crucial and needs to happen before 'app' is imported if 'app' itself initializes firebase.
# # For simplicity, we'll assume firebase_admin is imported within functions or routes in app.py,
# # or that we can patch it effectively after app import.

# # mock_firebase_admin = MagicMock() # Keep this if other non-auth tests need it for global app patches
# # mock_firebase_admin.auth = MagicMock()
# # mock_firebase_admin.firestore = MagicMock()
# # mock_firebase_admin.credentials = MagicMock()
# # mock_firebase_admin.initialize_app = MagicMock()


# The broad @patch decorators at the class level might not be needed if we specifically
# patch 'app.UserService' for each auth-related test method.
# However, if other routes tested by AuthTestCase still rely on direct firebase_admin mocks,
# these might need to stay or be refined. For this refactor, we focus on auth routes.

# @patch('app.firebase_admin', mock_firebase_admin)
# @patch('firestore_utils.db', mock_firebase_admin.firestore.client())
# @patch('app.auth', mock_firebase_admin.auth)
# @patch('firebase_admin.auth', mock_firebase_admin.auth)
# @patch('firebase_admin.firestore', mock_firebase_admin.firestore)
class AuthTestCase(unittest.TestCase):

    def setUp(self):
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        app.config['SECRET_KEY'] = 'test_secret_key'
        app.config['SERVER_NAME'] = 'localhost'
        app.config['APPLICATION_ROOT'] = '/'
        app.config['PREFERRED_URL_SCHEME'] = 'http'
        self.client = app.test_client()
        # No direct firebase mocks needed here if UserService is consistently mocked for auth routes.

    @mock.patch('google.auth.default', return_value=(mock.MagicMock(spec=google_auth_credentials.Credentials), 'mock-project'))
    def test_register_page_loads(self, mock_google_auth_default): # Signature should be correct based on decorator
        response = self.client.get('/register')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Register', response.data)

    @patch('app.UserService')
    @mock.patch('google.auth.default', return_value=(mock.MagicMock(spec=google_auth_credentials.Credentials), 'mock-project'))
    def test_successful_registration(self, mock_google_auth_default, MockUserService):
        mock_user_service_instance = MockUserService.return_value
        mock_user_service_instance.register_user_with_email_password.return_value = {
            'status': 'success',
            'user': {'uid': 'testuid123', 'email': 'test@example.com', 'displayName': 'Test User'}
        }

        response = self.client.post('/register', data={
            'email': 'test@example.com',
            'displayName': 'Test User',
            'password': 'password123',
            'confirm_password': 'password123'
        }, follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Login', response.data) # Should redirect to login page

        MockUserService.assert_called_once_with(app.logger)
        mock_user_service_instance.register_user_with_email_password.assert_called_once_with(
            'test@example.com', 'Test User', 'password123'
        )

    @patch('app.UserService')
    @mock.patch('google.auth.default', return_value=(mock.MagicMock(spec=google_auth_credentials.Credentials), 'mock-project'))
    def test_registration_email_exists(self, mock_google_auth_default, MockUserService): # Signature was correct
        mock_user_service_instance = MockUserService.return_value
        mock_user_service_instance.register_user_with_email_password.return_value = {
            'status': 'error',
            'message': 'Email already exists.'
        }

        response = self.client.post('/register', data={
            'email': 'existing@example.com',
            'displayName': 'Another User',
            'password': 'password123',
            'confirm_password': 'password123'
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Email already exists.', response.data)
        MockUserService.assert_called_once_with(app.logger)
        mock_user_service_instance.register_user_with_email_password.assert_called_once_with(
            'existing@example.com', 'Another User', 'password123'
        )

    @mock.patch('google.auth.default', return_value=(mock.MagicMock(spec=google_auth_credentials.Credentials), 'mock-project'))
    def test_registration_password_mismatch(self, mock_google_auth_default): # Added mock_google_auth_default
        response = self.client.post('/register', data={
            'email': 'test@example.com',
            'displayName': 'Test User',
            'password': 'password123',
            'confirm_password': 'password456'
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Passwords do not match', response.data)


    @patch('app.UserService')
    @mock.patch('google.auth.default', return_value=(mock.MagicMock(spec=google_auth_credentials.Credentials), 'mock-project'))
    def test_login_with_invalid_id_token(self, mock_google_auth_default, MockUserService):
        mock_user_service_instance = MockUserService.return_value
        # Corrected to mock login_user_with_id_token
        mock_user_service_instance.login_user_with_id_token.return_value = {
            'status': 'error', 'message': 'Invalid ID token.' # Message from UserService
        }

        response = self.client.post('/login', json={'idToken': 'invalid_dummy_token'})

        self.assertEqual(response.status_code, 401)
        response_json = response.get_json()
        self.assertEqual(response_json['status'], 'error')
        self.assertEqual(response_json['message'], 'Invalid ID token.') # Assert specific message

        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get('user_id'))

        MockUserService.assert_called_once_with(app.logger)
        # Corrected to assert call on login_user_with_id_token
        mock_user_service_instance.login_user_with_id_token.assert_called_once_with('invalid_dummy_token')

    @mock.patch('google.auth.default', return_value=(mock.MagicMock(spec=google_auth_credentials.Credentials), 'mock-project'))
    def test_login_with_missing_token(self, mock_google_auth_default): # Added mock_google_auth_default
        response = self.client.post('/login', json={})
        self.assertEqual(response.status_code, 400)
        response_json = response.get_json()
        self.assertEqual(response_json['status'], 'error')
        self.assertEqual(response_json['message'], 'Missing idToken')
        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get('user_id'))

    # --- Tests for /google_callback ---
    @patch('app.UserService')
    @mock.patch('google.auth.default', return_value=(mock.MagicMock(spec=google_auth_credentials.Credentials), 'mock-project'))
    def test_google_callback_success_new_user(self, mock_google_auth_default, MockUserService): # Signature was correct
        mock_user_service_instance = MockUserService.return_value
        user_data = {'uid': 'newgoogleuid', 'email': 'new@google.com', 'displayName': 'New Google User'}
        mock_user_service_instance.handle_google_signin.return_value = {
            'status': 'success', 'user': user_data
        }

        response = self.client.post('/google_callback', json={'idToken': 'google_new_user_token'})
        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertEqual(json_data['status'], 'success')
        # Используем относительный путь для сравнения
        expected_path = app.url_for('home', _external=False)
        self.assertTrue(json_data['redirect_url'].endswith(expected_path))
        with self.client.session_transaction() as sess:
            self.assertEqual(sess['user_id'], user_data['uid'])
            self.assertEqual(sess['user_email'], user_data['email'])
        MockUserService.assert_called_once_with(app.logger)
        mock_user_service_instance.handle_google_signin.assert_called_once_with('google_new_user_token')

    @mock.patch('google.auth.default', return_value=(mock.MagicMock(spec=google_auth_credentials.Credentials), 'mock-project'))
    def test_login_page_loads(self, mock_google_auth_default): # Added mock_google_auth_default
        response = self.client.get('/login')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Login', response.data)

        with self.client.session_transaction() as sess:
            sess['user_id'] = 'testuid_already_logged_in'
        # Используем app.test_request_context() для url_for при проверке редиректа
        with app.test_request_context():
            expected_path = app.url_for('home', _external=False)
            response_loggedin = self.client.get('/login', follow_redirects=False)
            self.assertEqual(response_loggedin.status_code, 302)
            # response_loggedin.location может быть абсолютным URL
            self.assertTrue(response_loggedin.location.endswith(expected_path))
        with self.client.session_transaction() as sess:
            del sess['user_id']

    @patch('app.UserService')
    @mock.patch('google.auth.default', return_value=(mock.MagicMock(spec=google_auth_credentials.Credentials), 'mock-project'))
    def test_successful_login_with_id_token(self, mock_google_auth_default, MockUserService): # Signature was correct
        mock_user_service_instance = MockUserService.return_value
        user_data_from_service = {'uid': 'testuid123', 'email': 'test@example.com', 'displayName': 'Test User'}
        mock_user_service_instance.login_user_with_id_token.return_value = {
            'status': 'success', 'user': user_data_from_service
        }

        response = self.client.post('/login', json={'idToken': 'valid_dummy_token'})

        self.assertEqual(response.status_code, 200)
        response_json = response.get_json()
        self.assertEqual(response_json['status'], 'success')
        # Используем относительный путь для сравнения
        expected_path = app.url_for('home', _external=False)
        self.assertTrue(response_json['redirect_url'].endswith(expected_path))

        with self.client.session_transaction() as sess:
            self.assertEqual(sess['user_id'], 'testuid123')
            self.assertEqual(sess['user_email'], 'test@example.com')
            self.assertEqual(sess['user_displayName'], 'Test User')

        MockUserService.assert_called_once_with(app.logger)
        mock_user_service_instance.login_user_with_id_token.assert_called_once_with('valid_dummy_token')

    @mock.patch('google.auth.default', return_value=(mock.MagicMock(spec=google_auth_credentials.Credentials), 'mock-project'))
    def test_logout(self, mock_google_auth_default): # Added mock_google_auth_default
        with self.client.session_transaction() as sess:
            sess['user_id'] = 'testuid123'
            sess['user_email'] = 'test@example.com'
            sess['user_displayName'] = 'Test User'

        # Используем app.test_request_context() для url_for при проверке пути после редиректа
        with app.test_request_context():
            expected_path = app.url_for('home', _external=False)
            response = self.client.get('/logout', follow_redirects=True)
            self.assertEqual(response.status_code, 200)
            # response.request.path это относительный путь после редиректа
            self.assertEqual(response.request.path, expected_path)

        with self.client.session_transaction() as sess:  # Check session after redirect
            self.assertIsNone(sess.get('user_id'))

    @patch('app.UserService')
    @mock.patch('google.auth.default', return_value=(mock.MagicMock(spec=google_auth_credentials.Credentials), 'mock-project'))
    def test_google_callback_success_existing_user(self, mock_google_auth_default, MockUserService):
        mock_user_service_instance = MockUserService.return_value
        user_data = {'uid': 'existinguid', 'email': 'existing@google.com', 'displayName': 'Existing Google User'}
        mock_user_service_instance.handle_google_signin.return_value = {
            'status': 'success', 'user': user_data
        }

        response = self.client.post('/google_callback', json={'idToken': 'google_existing_user_token'})
        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertEqual(json_data['status'], 'success')
        with self.client.session_transaction() as sess:
            self.assertEqual(sess['user_id'], user_data['uid'])
        mock_user_service_instance.handle_google_signin.assert_called_once_with('google_existing_user_token')

    @patch('app.UserService')
    @mock.patch('google.auth.default', return_value=(mock.MagicMock(spec=google_auth_credentials.Credentials), 'mock-project'))
    def test_google_callback_success_merge_user(self, mock_google_auth_default, MockUserService):
        mock_user_service_instance = MockUserService.return_value
        user_data = {'uid': 'mergeduid', 'email': 'merged@google.com', 'displayName': 'Merged Google User'}
        mock_user_service_instance.handle_google_signin.return_value = {
            'status': 'success', 'user': user_data # Simulate successful merge
        }
        response = self.client.post('/google_callback', json={'idToken': 'google_merge_user_token'})
        self.assertEqual(response.status_code, 200)
        json_data = response.get_json()
        self.assertEqual(json_data['status'], 'success')
        with self.client.session_transaction() as sess:
            self.assertEqual(sess['user_id'], user_data['uid'])
        mock_user_service_instance.handle_google_signin.assert_called_once_with('google_merge_user_token')

    @patch('app.UserService')
    @mock.patch('google.auth.default', return_value=(mock.MagicMock(spec=google_auth_credentials.Credentials), 'mock-project'))
    def test_google_callback_failure_invalid_token(self, mock_google_auth_default, MockUserService):
        mock_user_service_instance = MockUserService.return_value
        mock_user_service_instance.handle_google_signin.return_value = {
            'status': 'error', 'message': 'Invalid ID token.'
        }
        response = self.client.post('/google_callback', json={'idToken': 'invalid_google_token'})
        self.assertEqual(response.status_code, 401) # As per app.py logic for this error message
        json_data = response.get_json()
        self.assertEqual(json_data['status'], 'error')
        self.assertEqual(json_data['message'], 'Invalid ID token.')
        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get('user_id'))
        mock_user_service_instance.handle_google_signin.assert_called_once_with('invalid_google_token')

    @patch('app.UserService')
    @mock.patch('google.auth.default', return_value=(mock.MagicMock(spec=google_auth_credentials.Credentials), 'mock-project'))
    def test_google_callback_failure_service_error(self, mock_google_auth_default, MockUserService):
        mock_user_service_instance = MockUserService.return_value
        mock_user_service_instance.handle_google_signin.return_value = {
            'status': 'error', 'message': 'User creation failed after Google Sign-In' # Example service error
        }
        response = self.client.post('/google_callback', json={'idToken': 'google_service_error_token'})
        self.assertEqual(response.status_code, 500) # As per app.py logic for this error message
        json_data = response.get_json()
        self.assertEqual(json_data['status'], 'error')
        self.assertEqual(json_data['message'], 'User creation failed after Google Sign-In')
        with self.client.session_transaction() as sess:
            self.assertIsNone(sess.get('user_id'))
        mock_user_service_instance.handle_google_signin.assert_called_once_with('google_service_error_token')

    @mock.patch('google.auth.default', return_value=(mock.MagicMock(spec=google_auth_credentials.Credentials), 'mock-project'))
    def test_google_callback_missing_token(self, mock_google_auth_default):
        response = self.client.post('/google_callback', json={})
        self.assertEqual(response.status_code, 400)
        json_data = response.get_json()
        self.assertEqual(json_data['status'], 'error')
        self.assertEqual(json_data['message'], 'Missing idToken')

    # Removed the direct UserService unit tests that were previously here.
    # Those should be in a dedicated test_user_service.py file.


# The TestContentDeletionAPI class remains unchanged by this refactoring.
# Its existing mocks for firestore_utils.db and firestore_utils.storage.bucket are still valid
# as it tests a different part of the application not directly using UserService.
