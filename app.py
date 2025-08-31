import os
from flask_cors import CORS
from datetime import datetime
from dotenv import load_dotenv
from flask import Flask, request, jsonify, current_app, \
    render_template, session, redirect, url_for, flash  # Added flash
import firebase_admin
from firebase_admin import credentials, firestore, storage, auth

import logging
from logging.handlers import RotatingFileHandler
from google.cloud.firestore import SERVER_TIMESTAMP

import firestore_utils

load_dotenv()

# Firebase Initialization
FIREBASE_STORAGE_BUCKET = os.environ.get('FIREBASE_STORAGE_BUCKET', 'your-project.appspot.com')

if not firebase_admin._apps:
    if os.environ.get('TEST_ENV') == 'true':
        # Use mock credentials for testing
        from google.auth import credentials as google_auth_credentials

        cred = google_auth_credentials.AnonymousCredentials()
        firebase_admin.initialize_app(cred, {
            'projectId': 'mock-project',  # Required for mock credentials
            'storageBucket': FIREBASE_STORAGE_BUCKET
        })
        print("INFO: Firebase initialized with MOCK credentials for TEST_ENV.")
    else:
        # Original initialization for production/development
        try:
            cred = credentials.ApplicationDefault()
            firebase_admin.initialize_app(cred, {
                'storageBucket': FIREBASE_STORAGE_BUCKET
            })
        except Exception as e:
            print(f"CRITICAL: Failed to initialize Firebase Admin SDK: {e}")
            # Consider exiting if Firebase is critical
            # import sys
        # sys.exit(1)

# Initialize db and bucket after Firebase app initialization
if os.environ.get('TEST_ENV') == 'true':
    # In test_env, firebase_admin.initialize_app was called with mock credentials
    # So, firestore.client() and storage.bucket() will use that mock app.
    db = firestore.client()
    bucket = storage.bucket()  # This might also need careful handling if it makes external calls
    print("INFO: Firestore db and Storage bucket initialized using MOCK Firebase app.")
else:
    try:
        db = firestore.client()
        bucket = storage.bucket()
    except Exception as e:
        print(f"CRITICAL: Failed to create Firestore/Storage clients: {e}")
        # import sys
        # sys.exit(1)

# Project-specific imports (after Firebase init)
from email_utils import create_email_notification_record, send_pending_notification
from webhook_handlers import handle_postmark_webhook_request
from admin_services import (
    verify_admin_id_token, get_dashboard_items,
    approve_content, reject_content, delete_content_admin
)
from api_services import (
    create_new_content_from_api,
    process_content_vote,
    process_content_report,
    update_content_item as api_update_content_item  # Alias to avoid naming conflict if any
)
from view_services import (
    get_home_page_data,
    get_post_page_data,
    format_datetime_filter as view_format_datetime_filter
)
from firestore_utils import \
    delete_content_item  # Only delete_content_item might be needed directly if not part of a service
# create_user, get_user_by_email, get_user, migrate_content_ownership are now handled by UserService
from user_service import UserService

app = Flask(__name__, static_folder='static')
CORS(app)
app.jinja_env.filters['datetime'] = view_format_datetime_filter

# Logging setup
app.logger.setLevel(logging.INFO)
file_handler = RotatingFileHandler('app.log', maxBytes=10000000, backupCount=5)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
))
app.logger.addHandler(file_handler)
app.logger.info('Flask app startup')

# App Configuration
INBOUND_URL_TOKEN = os.environ.get('INBOUND_URL_TOKEN', 'DEFAULT_INBOUND_TOKEN_IF_NOT_SET')
GOOGLE_MAPS_API_KEY = os.environ.get('GOOGLE_MAPS_API_KEY', '')
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'default-secret-key-for-development')
ALLOWED_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif'}
MAX_IMAGE_SIZE = 6 * 1024 * 1024  # 6MB
PHOTO_UPLOAD_LIMIT = int(os.environ.get('PHOTO_UPLOAD_LIMIT', 5))
app.config['PHOTO_UPLOAD_LIMIT'] = PHOTO_UPLOAD_LIMIT


@app.route('/.well-known/appspecific/com.chrome.devtools.json')
def chrome_devtools():
    return jsonify({})


@app.before_request
def before_request_funcs():
    original_host = request.environ.get('HTTP_HOST')
    if original_host and ',' in original_host:
        new_host = original_host.split(',', 1)[0]
        request.environ['HTTP_HOST'] = new_host
        current_app.logger.info(f"Sanitizing HTTP_HOST: Original '{original_host}', New: '{new_host}'")

    if request.method in ['POST', 'PUT', 'PATCH', 'DELETE']:
        if request.content_length is None and request.headers.get('Transfer-Encoding', '').lower() != 'chunked':
            current_app.logger.warning(
                f"Request to {request.path} from {request.remote_addr} without Content-Length or chunked encoding."
            )
            pass


def show_server_urls():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        print(f"\n * Running on http://127.0.0.1:{os.environ.get('PORT', 8080)}")
        print(f" * Running on http://{local_ip}:{os.environ.get('PORT', 8080)}")
        print("Press CTRL+C to quit\n")
    except Exception as e:
        app.logger.error(f"Could not determine local IP: {e}")


with app.app_context():
    pass


@app.route('/webhook/postmark', methods=['POST'])
def postmark_webhook():
    token_from_query = request.args.get('token')
    app.logger.info(f"Postmark webhook called. Token from query: {token_from_query}")
    try:
        request_json_data = request.get_json(force=True)
        if not request_json_data:
            app.logger.warning(f"No JSON data received in Postmark webhook from {request.remote_addr}.")
            return jsonify({'status': 'error', 'message': 'No JSON data received'}), 200
    except Exception as e:
        app.logger.error(f"Error parsing JSON data in Postmark webhook: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': f'Error parsing request data: {str(e)}'}), 200

    result_dict = handle_postmark_webhook_request(
        request_json_data=request_json_data,
        query_token=token_from_query,
        app_logger=current_app.logger,
        db_client=db,
        bucket=bucket,
        app_context=app.app_context(),
        inbound_url_token_config=INBOUND_URL_TOKEN,
        allowed_image_extensions_config=ALLOWED_IMAGE_EXTENSIONS,
        max_image_size_config=MAX_IMAGE_SIZE,
        app_config=current_app.config  # Pass the app's config
    )
    http_status_code = result_dict.pop('http_status_code', 200)
    return jsonify(result_dict), http_status_code


@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        try:
            data = request.get_json()
            if not data or 'idToken' not in data:
                current_app.logger.warning("/admin/login POST: Missing idToken in request.")
                return jsonify({'status': 'error', 'message': 'Missing idToken'}), 400

            id_token = data['idToken']
            # Ensure verify_admin_id_token is imported from admin_services
            admin_info = verify_admin_id_token(id_token, current_app.logger)

            if admin_info:
                session['admin_id'] = admin_info['uid']  # Changed to 'uid'
                session['admin_email'] = admin_info['email']
                current_app.logger.info(
                    f"Admin '{admin_info['email']}' logged in successfully using ID token. UID: {admin_info['uid']}")
                return jsonify({'status': 'success', 'message': 'Admin login successful',
                                'redirect_url': url_for('admin_dashboard')}), 200
            else:
                current_app.logger.warning(f"/admin/login POST: Admin authentication failed for token.")
                return jsonify({'status': 'error', 'message': 'Invalid credentials or not an admin'}), 401
        except Exception as e:
            current_app.logger.error(f"Error in /admin/login POST: {e}", exc_info=True)
            return jsonify({'status': 'error', 'message': 'An unexpected error occurred'}), 500

    # GET request part remains the same
    if 'admin_id' in session:
        return redirect(url_for('admin_dashboard'))
    return render_template('admin/login.html')


@app.route('/admin/logout')
def admin_logout():
    admin_email = session.get('admin_email', 'Unknown admin')
    session.pop('admin_id', None)
    session.pop('admin_email', None)
    app.logger.info(f"Admin '{admin_email}' logged out.")
    return redirect(url_for('admin_login'))


@app.route('/admin/dashboard')
def admin_dashboard():
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))

    view_type = request.args.get('view')
    status_filter_from_query = request.args.get('status', 'for_moderation')  # Original status filter

    try:
        # Pass view_type to the service. status_filter_from_query might be ignored by the service if view_type is 'reported'.
        items = get_dashboard_items(status_filter_from_query, current_app.logger, view_type=view_type)

        status_map = {'published': 'Published', 'for_moderation': 'For Moderation', 'rejected': 'Rejected'}
        for item in items:
            item['status_display'] = status_map.get(item.get('status'), item.get('status'))

        section_titles = {
            'all': 'All Posts',
            'for_moderation': 'Posts for Moderation',
            'published': 'Published Posts',
            'rejected': 'Rejected Posts',
            'reported': 'Reported Posts'  # New title
        }

        active_filter_name_for_title = None
        status_for_dropdown = status_filter_from_query

        if view_type == 'reported':
            active_filter_name_for_title = 'reported'
            # When viewing reported posts, the status dropdown could default to 'all',
            # as the primary filter is 'reportedCount > 0' and items can be of any status.
            status_for_dropdown = 'all'
        else:
            active_filter_name_for_title = status_filter_from_query

        current_section_title = section_titles.get(active_filter_name_for_title, 'Posts')

        return render_template('admin/dashboard.html',
                               items=items,
                               status=status_for_dropdown,  # Used to set selected option in dropdown
                               section_title=current_section_title,
                               admin_email=session.get('admin_email'),
                               current_view=view_type,  # Pass current_view for sidebar active state
                               active_status_filter=status_filter_from_query  # Pass original status for sidebar
                               )
    except Exception as e:
        error_desc = f"status: {status_filter_from_query}, view: {view_type}"
        app.logger.error(f"Error loading admin dashboard ({error_desc}): {e}", exc_info=True)
        return render_template('500.html'), 500


@app.route('/admin/api/content/<content_id>/approve', methods=['POST'])
def admin_approve_content(content_id):
    if 'admin_id' not in session:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    success = approve_content(content_id, session.get('admin_id'), current_app.logger)
    if success:
        return jsonify({'status': 'success', 'message': 'Post approved'})
    else:
        return jsonify({'status': 'error', 'message': 'Failed to approve post'}), 500


@app.route('/admin/api/content/<content_id>/reject', methods=['POST'])
def admin_reject_content(content_id):
    if 'admin_id' not in session:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    success = reject_content(content_id, session.get('admin_id'), current_app.logger)
    if success:
        return jsonify({'status': 'success', 'message': 'Post rejected'})
    else:
        return jsonify({'status': 'error', 'message': 'Failed to reject post'}), 500


@app.route('/admin/api/content/<content_id>/delete', methods=['POST'])
def admin_delete_content(content_id):
    if 'admin_id' not in session:
        current_app.logger.warning(f"Unauthorized attempt to delete content {content_id}. No admin in session.")
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    admin_id = session.get('admin_id')
    current_app.logger.info(f"Admin {admin_id} attempting to delete content {content_id} via API.")

    # Call the service function for deletion
    result = delete_content_admin(content_id, admin_id, current_app.logger)

    if result.get('status') == 'success':
        current_app.logger.info(f"Content {content_id} successfully deleted by admin {admin_id}.")
        return jsonify({'status': 'success', 'message': result.get('message', 'Post deleted successfully')})
    else:
        current_app.logger.error(
            f"Failed to delete content {content_id} by admin {admin_id}. API Error: {result.get('message')}")
        # Propagate the status code from the service if available, otherwise default to 500
        status_code = result.get('code', 500)
        return jsonify({'status': 'error', 'message': result.get('message', 'Failed to delete post')}), status_code


@app.template_filter('datetime')
def format_datetime_filter(timestamp):
    if not timestamp: return ''
    if isinstance(timestamp, dict):
        if '_seconds' in timestamp:
            timestamp = datetime.fromtimestamp(timestamp['_seconds'])
        elif 'seconds' in timestamp:
            timestamp = datetime.fromtimestamp(timestamp['seconds'])
    if isinstance(timestamp, datetime): return timestamp.strftime('%d.%m.%Y %H:%M')
    return str(timestamp)


@app.route('/')
def home():
    # Получаем userId из URL-параметра
    filtered_user_id = request.args.get('userId', None)
    current_logged_in_user_id = session.get('user_id')

    # Подготавливаем контекст с отфильтрованными данными
    context = get_home_page_data(current_app.logger, GOOGLE_MAPS_API_KEY,
                                 user_id_for_filtering=filtered_user_id,
                                 logged_in_user_id=current_logged_in_user_id,
                                 photo_upload_limit=current_app.config['PHOTO_UPLOAD_LIMIT'])

    app.logger.debug(f"Home page: Loaded {len(context.get('items', []))} items for map" +
                     (f" filtered by user {filtered_user_id}" if filtered_user_id else ""))

    # Pass user session info and filter info to the template
    context['user_id_session'] = session.get('user_id')
    context['user_displayName_session'] = session.get('user_displayName')
    context['filtered_user_id'] = filtered_user_id  # Для отображения активного фильтра

    return render_template('index.html', **context)


@app.route('/help')
def help_page():
    POSTMARK_FROM_EMAIL = os.environ.get('POSTMARK_FROM_EMAIL', 'default_email@example.com')
    base_url_from_env = os.environ.get('BASE_URL', 'https://mailmap.store')
    if not base_url_from_env.startswith(('http://', 'https://')):
        base_url_to_template = 'https://' + base_url_from_env
    else:
        base_url_to_template = base_url_from_env
    return render_template('help_page.html', postmark_from_email=POSTMARK_FROM_EMAIL, base_url=base_url_to_template)


@app.route('/api/content/<content_id>/vote', methods=['POST'])
def vote_content(content_id):
    app.logger.info(f"Vote request for content_id: {content_id}")
    try:
        data = request.get_json()
        if not data or 'vote' not in data:
            app.logger.warning(f"Missing 'vote' parameter for content_id: {content_id}. Data: {data}")
            return jsonify({'status': 'error', 'message': 'Missing vote parameter'}), 400
        vote_value = data.get('vote')
        user_id = data.get('userId') or request.headers.get('X-User-ID')
        data = {
            'vote': vote_value,
            'timestamp': SERVER_TIMESTAMP
        }
        result = process_content_vote(content_id, user_id, vote_value, current_app.logger)
        http_status_code = result.pop('http_code', 500 if result.get('status') == 'error' else 200)
        return jsonify(result), http_status_code
    except Exception as e:
        app.logger.error(f"Unexpected error in /api/content/.../vote route for {content_id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': "An unexpected error occurred."}), 500


@app.route('/api/content/<content_id>/report', methods=['POST'])
def report_content(content_id):
    app.logger.info(f"Report request for content_id: {content_id}")
    try:
        data = request.get_json()
        reason = data.get('reason', 'Not specified')
        user_id = data.get('userId') or request.headers.get('X-User-ID')
        result = process_content_report(content_id, user_id, reason, current_app.logger)
        http_status_code = result.pop('http_code', 500 if result.get('status') == 'error' else 200)
        return jsonify(result), http_status_code
    except Exception as e:
        app.logger.error(f"Unexpected error in /api/content/.../report route for {content_id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': "An unexpected error occurred."}), 500


@app.route('/api/content/create', methods=['POST'])
def create_content():
    app.logger.info("Received request to /api/content/create")
    try:
        user_id = request.form.get('userId') or request.headers.get('X-User-ID')
        result = create_new_content_from_api(
            form_data=request.form,
            files=request.files,
            user_id=user_id,
            app_logger=current_app.logger,
            bucket_client=bucket,
            allowed_extensions=ALLOWED_IMAGE_EXTENSIONS,
            max_image_size=MAX_IMAGE_SIZE
        )
        http_status_code = result.pop('http_code', 500 if result.get('status') == 'error' else 200)
        if http_status_code == 201 and 'contentId' not in result:
            app.logger.error("API create content: service returned success but no contentId.")
            return jsonify({'status': 'error', 'message': 'Content creation succeeded but contentId missing.'}), 500
        return jsonify(result), http_status_code
    except Exception as e:
        app.logger.error(f"Unexpected error in /api/content/create route: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': "An unexpected error occurred."}), 500


@app.route('/api/content/<content_id>/delete', methods=['DELETE'])
def api_delete_content(content_id):
    user_id = session.get('user_id')
    if not user_id:
        current_app.logger.warning(f"Unauthorized attempt to delete content {content_id}. No user in session.")
        return jsonify({'status': 'error', 'message': 'User not authenticated'}), 401

    current_app.logger.info(f"User {user_id} attempting to delete content {content_id}.")

    result = delete_content_item(content_id, user_id, current_app.logger)

    current_app.logger.info(
        f"Deletion attempt for content {content_id} by user {user_id}. Result: {result.get('message')}, Code: {result.get('code')}")

    return jsonify(result), result.get('code', 500)


@app.route('/api/content/<content_id>/edit', methods=['PUT'])
def api_edit_content(content_id):
    user_id = request.headers.get('X-User-ID')
    if not user_id:
        current_app.logger.warning(f"Edit attempt for content {content_id} without X-User-ID.")
        return jsonify({'status': 'error', 'message': 'User authentication required (X-User-ID header missing).'}), 401

    try:
        data = request.get_json()
        if not data:
            current_app.logger.warning(f"Edit attempt for content {content_id} by user {user_id} with no JSON data.")
            return jsonify({'status': 'error', 'message': 'No data provided for update.'}), 400
    except Exception as e:
        current_app.logger.error(f"Error parsing JSON for content {content_id} edit by user {user_id}: {e}",
                                 exc_info=True)
        return jsonify({'status': 'error', 'message': 'Invalid JSON format.'}), 400

    current_app.logger.info(f"User {user_id} attempting to edit content {content_id} with data: {data}")

    # Call the placeholder service function
    # Note: MAX_IMAGE_SIZE is used as MAX_IMAGE_SIZE_BYTES is not explicitly defined in app.config
    result = api_update_content_item(
        content_id=content_id,
        user_id=user_id,
        data=data,
        app_logger=current_app.logger,
        gcs_bucket_name=current_app.config.get('FIREBASE_STORAGE_BUCKET'),  # Corrected bucket name
        allowed_extensions=current_app.config.get('ALLOWED_IMAGE_EXTENSIONS'),
        max_image_size_bytes=current_app.config.get('MAX_IMAGE_SIZE')
    )

    http_status_code = result.pop('http_code', 500 if result.get('status') == 'error' else 200)
    return jsonify(result), http_status_code


@app.route('/api/content/<content_id>', methods=['GET'])
def get_api_content_item(content_id):
    current_app.logger.info(f"Request to fetch content item with ID: {content_id}")
    try:
        item_data = firestore_utils.get_content_item(content_id, current_app.logger)

        if item_data:
            # The 'itemId' is already part of item_data as returned by get_content_item
            current_app.logger.info(f"Content item {content_id} found.")
            # Optionally, remove sensitive data or reformat before sending
            # For now, sending all data as is.
            return jsonify({'status': 'success', 'content': item_data}), 200
        else:
            current_app.logger.warning(f"Content item {content_id} not found when fetching via API.")
            return jsonify({'status': 'error', 'message': 'Content not found'}), 404
    except Exception as e:
        current_app.logger.error(f"Error fetching content item {content_id} via API: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'An internal server error occurred'}), 500


@app.route('/post/<item_id>')
def post_view(item_id):
    # Получаем userId из URL-параметра
    filtered_user_id = request.args.get('userId', None)

    # Подготавливаем контекст с отфильтрованными данными и целевым элементом
    context = get_post_page_data(item_id, current_app.logger, GOOGLE_MAPS_API_KEY,
                                 user_id_for_filtering=filtered_user_id)

    # Добавляем информацию о текущей сессии
    context['user_id_session'] = session.get('user_id')
    context['user_displayName_session'] = session.get('user_displayName')
    context['filtered_user_id'] = filtered_user_id  # Для отображения активного фильтра

    app.logger.debug(f"Post page {item_id}: Loaded {len(context.get('items', []))} items for map" +
                     (f" filtered by user {filtered_user_id}" if filtered_user_id else ""))

    if not context.get('target_item_data'):
        app.logger.warning(f"Post page: Target item {item_id} not found.")

    return render_template('index.html', **context)


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        email = request.form.get('email')
        displayName = request.form.get('displayName')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        error = None

        if password != confirm_password:
            error = "Passwords do not match."

        if not error:
            user_service = UserService(current_app.logger)
            registration_result = user_service.register_user_with_email_password(email, displayName, password)

            if registration_result['status'] == 'success':
                current_app.logger.info(
                    f"User {registration_result['user']['uid']} ({email}) registered successfully via UserService. Message: {registration_result.get('message')}")
                # Flash message based on the outcome of sending the verification email
                message_from_service = registration_result.get('message', '')
                if 'Please check your email to verify your account' in message_from_service:
                    flash('Registration successful. Please check your email to verify your account.', 'success')
                elif 'Failed to send verification email' in message_from_service:
                    flash(
                        'Registration successful. Failed to send verification email; please try requesting a new one later or contact support.',
                        'warning')
                elif 'An error occurred while sending the verification email' in message_from_service:
                    flash(
                        'Registration successful. An error occurred while attempting to send the verification email. Please try verifying later or contact support.',
                        'warning')
                else:
                    # Default success message if the specific verification message isn't found
                    flash('Registration successful. Please log in.', 'success')

                return redirect(url_for('login'))  # Redirect to login page after successful registration
            else:
                error = registration_result.get('message', 'An unknown error occurred during registration.')
                current_app.logger.warning(f"Registration failed for {email}: {error}")

        # If error is set either by initial checks or by UserService response
        if error:
            return render_template('register.html', error=error, email=email, displayName=displayName)

    return render_template('register.html')


@app.route('/login', methods=['GET', 'POST'])  # Now handles GET and POST
def login():
    if request.method == 'GET':
        if session.get('user_id'):
            return redirect(url_for('home'))
        return render_template('login.html')

    # POST request logic
    # The initial `if session.get('user_id'):` check that returned JSON is removed.
    # If a POST request comes, we attempt to log in with the token.
    try:
        data = request.get_json()
        if not data or 'idToken' not in data:
            current_app.logger.warning("/login POST: Missing idToken in request.")
            return jsonify({'status': 'error', 'message': 'Missing idToken'}), 400

        id_token = data['idToken']

        user_service = UserService(current_app.logger)
        # Call the renamed method login_user_with_id_token
        login_response = user_service.login_user_with_id_token(id_token)

        if login_response['status'] == 'success':
            user_data = login_response['user']
            session['user_id'] = user_data['uid']
            session['user_email'] = user_data['email']
            session['user_displayName'] = user_data.get('displayName', user_data.get('email'))  # Fallback to email

            current_app.logger.info(f"User {user_data['uid']} ({user_data['email']}) logged in via ID token (POST).")
            return jsonify({'status': 'success', 'message': 'Login successful', 'redirect_url': url_for('home')}), 200
        else:
            # Log the specific error message from the service
            error_message = login_response.get('message', 'Login failed. Invalid token or user issue.')
            current_app.logger.warning(
                f"Login failed for token (POST). Service message: {error_message}")  # Avoid logging token itself
            return jsonify({'status': 'error', 'message': error_message}), 401

    except Exception as e:
        # General exception handling for unexpected errors
        current_app.logger.error(f"Unexpected error in /login POST route: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'An unexpected error occurred during login.'}), 500


@app.route('/logout')
def logout():
    user_email = session.get('user_email', 'Unknown user')  # For logging
    session.pop('user_id', None)
    session.pop('user_email', None)
    session.pop('user_displayName', None)
    current_app.logger.info(f"User '{user_email}' logged out from server session.")
    # Перенаправляем на домашнюю страницу
    return redirect(url_for('home'))


@app.route('/client_logout')
def client_logout_page():
    return render_template('client_logout.html')


@app.route('/google_login', methods=['GET'])
def google_login():
    # This route is a placeholder.
    # Actual Google Sign-In is initiated client-side.
    # Client obtains an ID token and sends it to /google_callback.
    # Redirecting to home or login page, or showing a message.
    current_app.logger.info("Accessed /google_login placeholder route. Redirecting to home.")
    return redirect(url_for('home'))


@app.route('/google_callback', methods=['POST'])
def google_callback():
    current_app.logger.info("Attempting Google Sign-In via /google_callback.")
    try:
        data = request.get_json()
        if not data or 'idToken' not in data:
            current_app.logger.warning("/google_callback: Missing idToken in request.")
            return jsonify({'status': 'error', 'message': 'Missing idToken'}), 400

        id_token = data['idToken']

        user_service = UserService(current_app.logger)
        google_signin_response = user_service.handle_google_signin(id_token)

        if google_signin_response['status'] == 'success':
            user_data = google_signin_response['user']
            session['user_id'] = user_data['uid']
            session['user_email'] = user_data['email']
            session['user_displayName'] = user_data.get('displayName', user_data.get('email'))  # Fallback to email

            current_app.logger.info(f"User {user_data['uid']} ({user_data['email']}) processed via Google Sign-In.")
            return jsonify(
                {'status': 'success', 'message': 'Google Sign-In successful', 'redirect_url': url_for('home')}), 200
        else:
            error_message = google_signin_response.get('message', 'Google Sign-In failed.')
            # Specific errors like InvalidIdTokenError are now handled within UserService,
            # so we check the message for more context if needed.
            if "Invalid ID token" in error_message:
                status_code = 401
            elif "User creation failed" in error_message or "Account merge failed" in error_message:
                status_code = 500
            else:
                status_code = 401  # Default to 401 for other auth-related issues

            current_app.logger.warning(f"Google Sign-In failed. Service message: {error_message}")
            return jsonify({'status': 'error', 'message': error_message}), status_code

    # Removed specific Firebase exception handling (ExpiredIdTokenError, InvalidIdTokenError)
    # as these are now caught within user_service.handle_google_signin and returned as error statuses.
    except Exception as e:
        # General exception handling for unexpected errors during request processing in the route itself
        current_app.logger.error(f"Unexpected error in /google_callback route: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'An unexpected error occurred during Google Sign-In.'}), 500


@app.route('/apple_callback', methods=['POST'])
def apple_callback():
    current_app.logger.info("Attempting Apple Sign-In via /apple_callback.")
    try:
        data = request.get_json()
        if not data or 'idToken' not in data:
            current_app.logger.warning("/apple_callback: Missing idToken in request.")
            return jsonify({'status': 'error', 'message': 'Missing idToken'}), 400

        id_token = data['idToken']

        user_service = UserService(current_app.logger)
        # This method will be created in user_service.py
        apple_signin_response = user_service.handle_apple_signin(id_token)

        if apple_signin_response['status'] == 'success':
            user_data = apple_signin_response['user']
            session['user_id'] = user_data['uid']
            session['user_email'] = user_data['email']
            # Apple might not always provide a display name, fallback to email or a placeholder
            session['user_displayName'] = user_data.get('displayName', user_data.get('email', 'User'))

            current_app.logger.info(f"User {user_data['uid']} ({user_data['email']}) processed via Apple Sign-In.")
            return jsonify({
                'status': 'success',
                'message': 'Apple Sign-In successful',
                'redirect_url': url_for('home')
            }), 200
        else:
            error_message = apple_signin_response.get('message', 'Apple Sign-In failed.')
            status_code = apple_signin_response.get('status_code', 401)  # Get status_code from service or default

            current_app.logger.warning(f"Apple Sign-In failed. Service message: {error_message}")
            return jsonify({'status': 'error', 'message': error_message}), status_code

    except Exception as e:
        current_app.logger.error(f"Unexpected error in /apple_callback route: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': 'An unexpected error occurred during Apple Sign-In.'}), 500


@app.route('/auth/action', methods=['GET'])
def handle_auth_action():
    """
    Handles actions like email verification or password reset redirects from Firebase.
    Flashes a message to the user and redirects them to the login page.
    """
    mode = request.args.get('mode')
    action_code = request.args.get('oobCode')  # Out Of Band code
    # continue_url = request.args.get('continueUrl') # Optional, not used in this simple handler
    # lang = request.args.get('lang', 'en') # Optional

    current_app.logger.info(
        f"Auth action called with mode: {mode}, oobCode: {'present' if action_code else 'missing'}.")

    # Here you could potentially verify the oobCode with Firebase Admin SDK
    # auth.verify_password_reset_code(action_code) or similar for email verification if needed,
    # but often Firebase handles the code verification itself before redirecting to this link.
    # This handler primarily acts as a user-friendly landing page.

    if mode == 'verifyEmail':
        # Potentially, you could call auth.apply_action_code(action_code) here if not done by Firebase.
        # However, the link from Firebase usually completes the action, then redirects.
        # So, we just confirm to the user.
        flash('Your email has been successfully verified! You can now log in.', 'success')
        current_app.logger.info(
            f"Email verification action completed for user (oobCode: {'present' if action_code else 'N/A'}).")
    elif mode == 'resetPassword':
        # For password reset, Firebase handles the reset page. This is if it redirects back to our app.
        # Typically, you'd guide the user to a page to enter a new password if this link was for that.
        # But if Firebase handles the password entry and this is just a confirmation redirect:
        flash('Password reset successful. You can now log in with your new password.', 'success')
        current_app.logger.info(f"Password reset action completed (oobCode: {'present' if action_code else 'N/A'}).")
    elif mode == 'recoverEmail':
        flash('Your email has been recovered. Please check your inbox for further instructions or try logging in.',
              'info')
        current_app.logger.info(f"Email recovery action processed (oobCode: {'present' if action_code else 'N/A'}).")
    else:
        # Generic message for other actions or if mode is unknown
        flash('The requested action has been completed.', 'info')
        current_app.logger.info(f"Unknown or generic auth action completed with mode: {mode}.")

    return redirect(url_for('login'))


if __name__ == '__main__':
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":
        show_server_urls()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=True)