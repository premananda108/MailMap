import unittest
import json
from unittest import mock
import sys
import os

# Add the parent directory to the Python path to allow module imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Firebase app should be initialized by conftest.py before this runs.
from app import app # Import the Flask app instance

# Ensure api_services is importable if you need to mock its functions directly
# For route testing, we often mock the service layer functions called by the routes.
# import api_services # Not strictly needed if using @mock.patch on the module itself

class TestApiRoutes(unittest.TestCase):

    def setUp(self):
        self.app = app
        self.client = self.app.test_client()
        self.content_id = "test_content_123"
        self.user_id = "test_user_abc"

        # Patch the service function that the route calls
        # Note: The path to mock is where the function is *looked up*,
        # which is in the 'app' module's namespace if imported as 'from api_services import ...' in app.py
        # or 'api_services.update_content_item' if imported as 'import api_services' in app.py.
        # Checking app.py, it uses 'from api_services import ... update_content_item as api_update_content_item'
        self.patch_update_item_service = mock.patch('app.api_update_content_item')
        self.mock_update_item_service = self.patch_update_item_service.start()
        self.addCleanup(self.patch_update_item_service.stop)

        # Patch for the GET /api/content/<content_id> endpoint
        # This route directly calls firestore_utils.get_content_item
        self.patch_get_content_item_util = mock.patch('app.firestore_utils.get_content_item')
        self.mock_get_content_item_util = self.patch_get_content_item_util.start()
        self.addCleanup(self.patch_get_content_item_util.stop)


    def test_edit_endpoint_success(self):
        self.mock_update_item_service.return_value = {
            'status': 'success',
            'message': 'Content updated successfully',
            'updated_fields': ['text'],
            'content_id': self.content_id,
            'http_code': 200  # This will be popped by the route, actual status code set from it
        }
        payload = {'text': 'New updated text'}
        response = self.client.put(
            f'/api/content/{self.content_id}/edit',
            headers={'X-User-ID': self.user_id},
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 200)
        json_response = response.get_json()
        self.assertEqual(json_response['status'], 'success')
        self.assertEqual(json_response['content_id'], self.content_id)
        # The route itself pops 'http_code', so it won't be in the final JSON response body
        self.assertNotIn('http_code', json_response)


    def test_edit_endpoint_no_user_id_header(self):
        payload = {'text': 'New updated text'}
        response = self.client.put(
            f'/api/content/{self.content_id}/edit',
            data=json.dumps(payload),
            content_type='application/json'
            # Missing X-User-ID header
        )
        self.assertEqual(response.status_code, 401)
        json_response = response.get_json()
        self.assertEqual(json_response['status'], 'error')
        self.assertEqual(json_response['message'], 'User authentication required (X-User-ID header missing).')
        self.mock_update_item_service.assert_not_called()

    def test_edit_endpoint_invalid_json(self):
        response = self.client.put(
            f'/api/content/{self.content_id}/edit',
            headers={'X-User-ID': self.user_id},
            data="not a valid json",
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 400)
        json_response = response.get_json()
        self.assertEqual(json_response['status'], 'error')
        self.assertEqual(json_response['message'], 'Invalid JSON format.')
        self.mock_update_item_service.assert_not_called()

    def test_edit_endpoint_service_returns_not_found(self):
        self.mock_update_item_service.return_value = {
            'status': 'error',
            'message': 'Content not found',
            'http_code': 404
        }
        payload = {'text': 'Update attempt'}
        response = self.client.put(
            f'/api/content/{self.content_id}/edit',
            headers={'X-User-ID': self.user_id},
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 404)
        json_response = response.get_json()
        self.assertEqual(json_response['status'], 'error')
        self.assertEqual(json_response['message'], 'Content not found')

    def test_edit_endpoint_service_returns_forbidden(self):
        self.mock_update_item_service.return_value = {
            'status': 'error',
            'message': 'User not authorized',
            'http_code': 403
        }
        payload = {'text': 'Update attempt'}
        response = self.client.put(
            f'/api/content/{self.content_id}/edit',
            headers={'X-User-ID': self.user_id},
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 403)
        json_response = response.get_json()
        self.assertEqual(json_response['status'], 'error')
        self.assertEqual(json_response['message'], 'User not authorized')

    def test_edit_endpoint_service_returns_server_error(self):
        self.mock_update_item_service.return_value = {
            'status': 'error',
            'message': 'Database update failed',
            'http_code': 500
        }
        payload = {'text': 'Update attempt'}
        response = self.client.put(
            f'/api/content/{self.content_id}/edit',
            headers={'X-User-ID': self.user_id},
            data=json.dumps(payload),
            content_type='application/json'
        )
        self.assertEqual(response.status_code, 500)
        json_response = response.get_json()
        self.assertEqual(json_response['status'], 'error')
        self.assertEqual(json_response['message'], 'Database update failed')

    def test_edit_endpoint_service_unexpected_exception_in_route(self):
        # Test if the route's own try-except for get_json() works.
        # This is slightly different from service error, this is error before service call
        # To test this, we need to make get_json() raise an error
        # One way is to send data that's not valid for get_json if content_type is json
        # but the `test_edit_endpoint_invalid_json` already covers the default Flask error for that.
        # Instead, let's test if the service call itself raises an *unexpected* error
        # that is not caught by the service and propagates to the route.
        self.mock_update_item_service.side_effect = Exception("Unexpected service layer boom!")
        payload = {'text': 'Update attempt'}

        # Flask's default error handling will catch this and return a 500 HTML page by default
        # or JSON if it's an API and errorhandler is set up.
        # For now, just ensure it doesn't crash and the mock was called.
        # The actual response might be HTML if no specific error handler for Exception is in app.py for JSON.
        # Let's assume the default Flask 500 for now if not specified by an error handler.
        # The app.py doesn't have a generic except Exception returning JSON for all routes,
        # but the specific route has a try-except for request.get_json().
        # The call to the service is *not* in a try-except in the route itself.
        # So an exception from the service would likely result in Flask's default 500 HTML.
        # If we want JSON, app.py should have a @app.errorhandler(Exception) def handle_exception(e): ...

        # For this test, let's verify the service was called and then check that the status is 500.
        # The default Flask test client behavior for unhandled exceptions is to propagate them.
        # To prevent test runner from crashing, we can use try-except in the test
        # or ensure Flask app is in debug=False mode for tests (usually default for test_client).

        initial_app_debug_state = self.app.debug
        try:
            self.app.debug = False # Ensure default 500 error page, not Werkzeug debugger
            response = self.client.put(
                f'/api/content/{self.content_id}/edit',
                headers={'X-User-ID': self.user_id},
                data=json.dumps(payload),
                content_type='application/json'
            )
            self.assertEqual(response.status_code, 500)
            # Default Flask 500 is HTML, so not asserting JSON content here.
        finally:
            self.app.debug = initial_app_debug_state # Restore app debug state

        self.mock_update_item_service.assert_called_once()

    # --- Tests for GET /api/content/<content_id> ---

    def test_get_content_item_success(self):
        sample_item_id = "sample_item_get_id"
        sample_item_data = {
            'itemId': sample_item_id,
            'text': 'Sample content for GET',
            'userId': 'user_get_abc'
            # Add other fields as returned by firestore_utils.get_content_item
        }
        self.mock_get_content_item_util.return_value = sample_item_data

        response = self.client.get(f'/api/content/{sample_item_id}')

        self.assertEqual(response.status_code, 200)
        json_response = response.get_json()
        self.assertEqual(json_response['status'], 'success')
        self.assertEqual(json_response['content'], sample_item_data)
        self.mock_get_content_item_util.assert_called_once_with(sample_item_id, mock.ANY) # ANY for app_logger

    def test_get_content_item_not_found(self):
        item_id_not_found = "non_existent_id"
        self.mock_get_content_item_util.return_value = None

        response = self.client.get(f'/api/content/{item_id_not_found}')

        self.assertEqual(response.status_code, 404)
        json_response = response.get_json()
        self.assertEqual(json_response['status'], 'error')
        self.assertEqual(json_response['message'], 'Content not found')
        self.mock_get_content_item_util.assert_called_once_with(item_id_not_found, mock.ANY)

    def test_get_content_item_firestore_exception(self):
        item_id_exception = "item_causes_exception"
        self.mock_get_content_item_util.side_effect = Exception("Simulated Firestore error")

        response = self.client.get(f'/api/content/{item_id_exception}')

        self.assertEqual(response.status_code, 500)
        json_response = response.get_json()
        self.assertEqual(json_response['status'], 'error')
        self.assertEqual(json_response['message'], 'An internal server error occurred')
        self.mock_get_content_item_util.assert_called_once_with(item_id_exception, mock.ANY)


if __name__ == '__main__':
    unittest.main()
