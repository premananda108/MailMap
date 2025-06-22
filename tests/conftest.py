import os
from unittest import mock

# Set TEST_ENV to true BEFORE any application modules are imported.
os.environ['TEST_ENV'] = 'true'

# --- Simplified Firebase Admin SDK Mocking ---

# 1. Mock firebase_admin.credentials.ApplicationDefault
# This prevents the SDK from trying to find real credentials.
mock_app_default_creds = mock.Mock()
# This mock will be used by app.py when os.environ.get('TEST_ENV') != 'true',
# but since TEST_ENV is true, app.py should use AnonymousCredentials.
# However, having this mock ensures that if TEST_ENV logic fails or is bypassed,
# it still doesn't try to load real ADC.
mock_app_default_creds.return_value = mock.MagicMock() # Simulates a credential object

# 2. Mock firebase_admin.initialize_app
# This prevents any real initialization if somehow called directly by test modules
# outside of app.py's control, though app.py should be the one initializing.
mock_initialize_app = mock.Mock()
mock_firebase_app_instance = mock.MagicMock()
mock_firebase_app_instance.name = '[MOCK_APP_CONTEST]'
mock_initialize_app.return_value = mock_firebase_app_instance

# Apply these specific mocks.
# This relies on app.py correctly using AnonymousCredentials when TEST_ENV is 'true'.
import firebase_admin
firebase_admin.credentials.ApplicationDefault = mock_app_default_creds
# We mock initialize_app as a fallback, but app.py should be performing the
# actual (mocked) initialization in a test environment.
# If app.py's initialize_app is called, it will use AnonymousCredentials due to TEST_ENV.
# If something else calls initialize_app, this mock catches it.
_original_initialize_app = firebase_admin.initialize_app
def safe_mock_initialize_app(*args, **kwargs):
    # If app is already initialized (e.g., by app.py), don't re-initialize or error.
    if not firebase_admin._apps:
        print("INFO (conftest.py): Fallback mock initialize_app called.")
        return mock_initialize_app(*args, **kwargs)
    return firebase_admin.get_app() # Return existing app

firebase_admin.initialize_app = safe_mock_initialize_app

# Do NOT mock firebase_admin.firestore.client or storage.bucket here.
# Let app.py initialize them using the (mocked via TEST_ENV) Firebase app.

print("INFO (conftest.py): TEST_ENV set. Firebase credentials and initialize_app minimally mocked.")
