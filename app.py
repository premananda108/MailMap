import os
import base64
import re
import tempfile
from datetime import datetime
import uuid
from dotenv import load_dotenv
from image_utils import extract_gps_coordinates  # Assuming this is handled
from flask import Flask, request, jsonify, current_app, \
    render_template, session, redirect, url_for
import firebase_admin
from firebase_admin import credentials, firestore, storage
from werkzeug.utils import secure_filename

load_dotenv()

from email_utils import create_email_notification_record, send_pending_notification  # Assuming this is handled

import logging
from logging.handlers import RotatingFileHandler

app = Flask(__name__, static_folder='static')

# Set up logging
app.logger.setLevel(logging.INFO)

file_handler = RotatingFileHandler('app.log', maxBytes=10000000, backupCount=5)
file_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
))
app.logger.addHandler(file_handler)
app.logger.info('Flask app startup')


@app.route('/.well-known/appspecific/com.chrome.devtools.json')
def chrome_devtools():
    return jsonify({})


@app.before_request
def check_content_length():
    if request.method in ['POST', 'PUT', 'PATCH', 'DELETE']:
        if request.content_length is None and request.headers.get('Transfer-Encoding', '').lower() != 'chunked':
            current_app.logger.warning(
                f"Request to {request.path} from {request.remote_addr} without Content-Length or chunked encoding."
            )
            pass


# Configuration
INBOUND_URL_TOKEN = os.environ.get('INBOUND_URL_TOKEN', 'DEFAULT_INBOUND_TOKEN_IF_NOT_SET')
FIREBASE_STORAGE_BUCKET = os.environ.get('FIREBASE_STORAGE_BUCKET', 'your-project.appspot.com')
GOOGLE_MAPS_API_KEY = os.environ.get('GOOGLE_MAPS_API_KEY', '')
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'default-secret-key-for-development')
ALLOWED_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif'}
MAX_IMAGE_SIZE = 6 * 1024 * 1024  # 6MB

# Firebase Initialization
if not firebase_admin._apps:
    cred = credentials.ApplicationDefault()
    firebase_admin.initialize_app(cred, {
        'storageBucket': FIREBASE_STORAGE_BUCKET
    })

db = firestore.client()
bucket = storage.bucket()  # Initialize bucket here after firebase_admin.initialize_app


def show_server_urls():  # This function uses print, intended for local dev startup
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


def verify_inbound_token(token_to_verify):
    if not token_to_verify:
        return False
    return token_to_verify == INBOUND_URL_TOKEN


def parse_location_from_subject(subject):
    if not subject:
        return None, None
    pattern = r'lat:([-+]?\d*\.?\d+),lng:([-+]?\d*\.?\d+)'
    match = re.search(pattern, subject, re.IGNORECASE)
    if match:
        try:
            lat = float(match.group(1))
            lng = float(match.group(2))
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                return lat, lng
        except ValueError:
            pass
    return None, None


def upload_image_to_gcs(image_data, filename):
    try:
        file_extension = filename.split('.')[-1].lower()
        unique_filename = f"content_images/{uuid.uuid4()}.{file_extension}"
        blob = bucket.blob(unique_filename)
        blob.upload_from_string(
            image_data,
            content_type=f'image/{file_extension}'
        )
        blob.make_public()
        return blob.public_url
    except Exception as e:
        app.logger.error(f"Error uploading image to GCS: {filename}. Error: {e}", exc_info=True)
        return None


def save_content_to_firestore(data):
    try:
        data['notificationSent'] = False
        data['notificationSentAt'] = None
        data['shortUrl'] = None
        doc_ref = db.collection('contentItems').document()
        doc_ref.set(data)
        doc_ref.update({'shortUrl': doc_ref.id})
        return doc_ref.id
    except Exception as e:
        app.logger.error(f"Error saving to Firestore. Data: {str(data)[:200]}. Error: {e}", exc_info=True)
        return None


def process_email_attachments(attachments):
    if not attachments:
        app.logger.info("No attachments found in email.")
        return None, None, None

    app.logger.info(f"Processing {len(attachments)} attachments.")
    for i, attachment in enumerate(attachments):
        content_type = attachment.get('ContentType', '')
        filename = attachment.get('Name', '')
        content = attachment.get('Content', '')

        app.logger.debug(
            f"Attachment {i + 1}: Name='{filename}', ContentType='{content_type}', HasContent={bool(content)}")

        if not content_type.startswith('image/'):
            app.logger.debug(
                f"Attachment {i + 1} ('{filename}') is not an image (ContentType: {content_type}). Skipping.")
            continue
        if not filename or '.' not in filename:
            app.logger.debug(f"Attachment {i + 1} ('{filename}') has no extension. Skipping.")
            continue
        file_extension = filename.split('.')[-1].lower()
        if file_extension not in ALLOWED_IMAGE_EXTENSIONS:
            app.logger.debug(
                f"Attachment {i + 1} ('{filename}') has unsupported extension '{file_extension}'. Skipping.")
            continue
        try:
            app.logger.debug(f"Attachment {i + 1} ('{filename}'): Attempting to decode Base64 content.")
            image_data = base64.b64decode(content)
            app.logger.debug(f"Attachment {i + 1} ('{filename}'): Decoded. Image data length: {len(image_data)} bytes.")

            if len(image_data) > MAX_IMAGE_SIZE:
                app.logger.warning(
                    f"File {filename} is too large ({len(image_data)} bytes). MAX_IMAGE_SIZE is {MAX_IMAGE_SIZE}. Skipping.")
                continue

            app.logger.debug(f"Attachment {i + 1} ('{filename}'): Extracting EXIF GPS data.")
            lat, lng = extract_gps_coordinates(image_data)  # Assuming this function is defined in image_utils
            app.logger.debug(f"Attachment {i + 1} ('{filename}'): EXIF GPS: lat={lat}, lng={lng}")

            app.logger.debug(f"Attachment {i + 1} ('{filename}'): Uploading to GCS.")
            image_url = upload_image_to_gcs(image_data, filename)
            app.logger.debug(f"Attachment {i + 1} ('{filename}'): GCS URL: {image_url}")

            if image_url:
                app.logger.info(
                    f"Attachment {i + 1} ('{filename}'): Successfully processed. Returning URL: {image_url}")
                return image_url, lat, lng
            else:
                app.logger.warning(
                    f"Attachment {i + 1} ('{filename}'): Failed to upload to GCS or get URL. Continuing to next attachment.")
        except Exception as e:
            app.logger.error(f"Error processing attachment {filename}: {e}", exc_info=True)
            continue
    app.logger.debug("Finished processing attachments loop.")
    return None, None, None


@app.route('/webhook/postmark', methods=['POST'])
def postmark_webhook():
    token_from_query = request.args.get('token')
    app.logger.info(f"Postmark webhook called. Token from query: {token_from_query}")

    try:
        data = request.get_json(force=True)  # Consider removing force=True and checking Content-Type
        if not data:
            app.logger.warning(f"No JSON data received in Postmark webhook from {request.remote_addr}.")
            return jsonify({'status': 'error', 'message': 'No JSON data received'}), 400
    except Exception as e:
        app.logger.error(f"Error parsing JSON data in Postmark webhook: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': f'Error parsing request data: {str(e)}'}), 400

    if not verify_inbound_token(token_from_query):
        app.logger.warning(
            f"Invalid token in Postmark webhook URL from {request.remote_addr}. Token: {token_from_query}")
        return jsonify({'status': 'error', 'message': 'Invalid token'}), 401

    try:
        from_email = data.get('FromFull', {}).get('Email', '') if data.get('FromFull') else data.get('From', '')
        subject = data.get('Subject', '')
        text_body = data.get('TextBody', '')
        html_body = data.get('HtmlBody', '')
        attachments = data.get('Attachments', [])

        app.logger.info(
            f"Received email via Postmark from {from_email} with subject: '{subject}'. Attachments: {len(attachments)}")

        image_url, exif_lat, exif_lng = process_email_attachments(attachments)

        if not image_url:
            app.logger.warning(
                f"No suitable images found in attachments from email by {from_email}, subject: '{subject}'.")
            return jsonify({'status': 'error', 'message': 'No valid images found in attachments'}), 400

        latitude, longitude = exif_lat, exif_lng
        if latitude is None or longitude is None:
            subject_lat, subject_lng = parse_location_from_subject(subject)
            if subject_lat is not None and subject_lng is not None:
                latitude, longitude = subject_lat, subject_lng
                app.logger.info(f"Used coordinates from subject: lat={latitude}, lng={longitude}")

        if latitude is None or longitude is None:
            app.logger.warning(f"Could not determine coordinates for post from {from_email}, subject: '{subject}'.")
            return jsonify({
                'status': 'error',
                'message': 'Location coordinates not found. Please include GPS data in image or specify in subject as lat:XX.XXX,lng:YY.YYY'
            }), 200  # 200 to prevent Postmark retries for content issues

        content_data = {
            'submitterEmail': from_email, 'text': text_body or html_body,
            'imageUrl': image_url, 'latitude': latitude, 'longitude': longitude,
            'timestamp': datetime.utcnow(), 'status': 'published',
            'voteCount': 0, 'reportedCount': 0, 'subject': subject
        }
        content_id = save_content_to_firestore(content_data)

        if content_id:
            app.logger.info(f"Content saved successfully with ID: {content_id} from email by {from_email}")
            if from_email:
                notification_id = create_email_notification_record(db, content_id, from_email)
                if notification_id:
                    # Consider making email sending asynchronous for production
                    email_sent_ok = send_pending_notification(db, notification_id, app_context=app.app_context())
                    if email_sent_ok:
                        app.logger.info(
                            f'Notification email process initiated for {notification_id} (content: {content_id}).')
                    else:
                        app.logger.warning(
                            f'Notification email process failed for {notification_id} (content: {content_id}).')
                else:
                    app.logger.warning(f"Failed to create notification record for content {content_id}")
            return jsonify({'status': 'success', 'contentId': content_id, 'message': 'Content published successfully'})
        else:
            app.logger.error(f"Failed to save content from email by {from_email}, subject: '{subject}'.")
            return jsonify({'status': 'error', 'message': 'Failed to save content'}), 500
    except Exception as e:
        app.logger.error(f"Critical error processing Postmark webhook: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': f'Internal server error: {str(e)}'}), 500


# --- ADMIN PANEL ---
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        try:
            admin_ref = db.collection('admins').where('email', '==', email).limit(1).get()
            if not admin_ref:
                return render_template('admin/login.html', error='Invalid email or password')
            admin_doc = admin_ref[0]
            admin_data = admin_doc.to_dict()
            # IMPORTANT: Use hashed passwords in a real application!
            if admin_data.get('password') != password:
                return render_template('admin/login.html', error='Invalid email or password')
            session['admin_id'] = admin_doc.id
            session['admin_email'] = admin_data.get('email')
            app.logger.info(f"Admin '{email}' logged in successfully.")
            return redirect(url_for('admin_dashboard'))
        except Exception as e:
            app.logger.error(f"Error during admin login for email {email}: {e}", exc_info=True)
            return render_template('admin/login.html', error='An error occurred during login')
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
    status_filter = request.args.get('status', 'for_moderation')
    try:
        items_query = db.collection('contentItems')
        if status_filter != 'all':
            items_query = items_query.where('status', '==', status_filter)
        items_query = items_query.order_by('timestamp', direction=firestore.Query.DESCENDING)
        items_docs = items_query.get()
        items = []
        for doc in items_docs:
            item_data = doc.to_dict()
            item_data['itemId'] = doc.id
            if status_filter == 'for_moderation' or status_filter == 'all':  # Simplified condition
                reports_ref = db.collection('reports').where('contentId', '==',
                                                             doc.id).get()  # Assuming 'reports' collection
                item_data['reports'] = [report.to_dict() for report in reports_ref]
            status_map = {'published': 'Published', 'for_moderation': 'For Moderation', 'rejected': 'Rejected'}
            item_data['status_display'] = status_map.get(item_data.get('status'), item_data.get('status'))
            items.append(item_data)
        section_titles = {
            'all': 'All Posts', 'for_moderation': 'Posts for Moderation',
            'published': 'Published Posts', 'rejected': 'Rejected Posts'
        }
        return render_template('admin/dashboard.html',
                               items=items, status=status_filter,
                               section_title=section_titles.get(status_filter, 'Posts'),
                               admin_email=session.get('admin_email'))
    except Exception as e:
        app.logger.error(f"Error loading admin dashboard (status: {status_filter}): {e}", exc_info=True)
        return render_template('500.html'), 500  # Assuming you have a 500.html template


@app.route('/admin/api/content/<content_id>/approve', methods=['POST'])
def admin_approve_content(content_id):
    if 'admin_id' not in session:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    try:
        content_ref = db.collection('contentItems').document(content_id)
        content_ref.update({
            'status': 'published',
            'moderated_by': session.get('admin_id'),
            'moderated_at': firestore.SERVER_TIMESTAMP
        })
        app.logger.info(f"Admin '{session.get('admin_email')}' approved content ID: {content_id}")
        return jsonify({'status': 'success', 'message': 'Post approved'})
    except Exception as e:
        app.logger.error(f"Error approving post {content_id} by admin '{session.get('admin_email')}': {e}",
                         exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/admin/api/content/<content_id>/reject', methods=['POST'])
def admin_reject_content(content_id):
    if 'admin_id' not in session:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401
    try:
        content_ref = db.collection('contentItems').document(content_id)
        content_ref.update({
            'status': 'rejected',
            'moderated_by': session.get('admin_id'),
            'moderated_at': firestore.SERVER_TIMESTAMP
        })
        app.logger.info(f"Admin '{session.get('admin_email')}' rejected content ID: {content_id}")
        return jsonify({'status': 'success', 'message': 'Post rejected'})
    except Exception as e:
        app.logger.error(f"Error rejecting post {content_id} by admin '{session.get('admin_email')}': {e}",
                         exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.template_filter('datetime')
def format_datetime_filter(timestamp):  # Renamed to avoid conflict with datetime module
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
    items_for_map = []
    try:
        items_query = db.collection('contentItems') \
            .where('status', '==', 'published') \
            .order_by('voteCount', direction=firestore.Query.ASCENDING) \
            .order_by('timestamp', direction=firestore.Query.DESCENDING) \
            .stream()
        for item_doc in items_query:
            item_data = item_doc.to_dict()
            item_data['itemId'] = item_doc.id
            if 'latitude' in item_data and 'longitude' in item_data:
                items_for_map.append(item_data)
            else:
                app.logger.debug(f"Item {item_doc.id} skipped for map, missing coordinates.")
        app.logger.debug(f"Loaded {len(items_for_map)} items from Firestore for the map.")
    except Exception as e:
        app.logger.error(f"Error loading data from Firestore for the map: {e}", exc_info=True)
    return render_template('index.html', items=items_for_map, maps_api_key=GOOGLE_MAPS_API_KEY)


# --- API for interacting with posts ---
@app.route('/api/content/<content_id>/vote', methods=['POST'])
def vote_content(content_id):
    app.logger.info(f"Vote request for content_id: {content_id}")
    try:
        data = request.get_json()
        if not data or 'vote' not in data:
            app.logger.warning(f"Missing 'vote' parameter for content_id: {content_id}. Data: {data}")
            return jsonify({'status': 'error', 'message': 'Missing vote parameter'}), 400
        vote_value = data.get('vote')
        user_id = data.get('userId') or request.headers.get('X-User-ID')  # Consider a more robust user ID system
        if not user_id:
            app.logger.warning(f"Missing 'userId' for voting on content_id: {content_id}.")
            return jsonify({'status': 'error', 'message': 'User ID is required'}), 400
        if vote_value not in [1, -1]:
            app.logger.warning(f"Invalid 'vote' value: {vote_value} for content_id: {content_id}.")
            return jsonify({'status': 'error', 'message': 'Invalid vote value'}), 400

        doc_ref = db.collection('contentItems').document(content_id)
        doc = doc_ref.get()
        if not doc.exists:
            app.logger.warning(f"Content not found for voting: {content_id}")
            return jsonify({'status': 'error', 'message': 'Content not found'}), 404

        doc_data = doc.to_dict()
        if doc_data.get('status') == 'for_moderation':
            app.logger.info(f"Attempt to vote on content under moderation: {content_id}")
            return jsonify({'status': 'error', 'message': 'Cannot vote for content under moderation'}), 403

        voters = doc_data.get('voters', {})
        vote_adjustment = vote_value  # Simplified logic, assumes new vote or overwrites
        if user_id in voters and voters[user_id] == vote_value:
            app.logger.info(f"User {user_id} already voted this way for {content_id}.")
            return jsonify({'status': 'error', 'message': 'You have already voted this way',
                            'newVoteCount': doc_data.get('voteCount', 0)}), 200

        current_votes = doc_data.get('voteCount', 0)
        # More robust vote change logic might be needed if users can change from +1 to -1 etc.
        # This simple adjustment assumes a new vote or a direct change.
        if user_id in voters:  # User is changing vote
            previous_vote_val = voters[user_id]
            new_vote_count = current_votes - previous_vote_val + vote_value
        else:  # New vote
            new_vote_count = current_votes + vote_value

        voters_update = {f'voters.{user_id}': vote_value}
        vote_history = {'userId': user_id, 'value': vote_value, 'timestamp': datetime.utcnow(), 'isAnonymous': True}
        doc_ref.update(
            {'voteCount': new_vote_count, **voters_update, 'voteHistory': firestore.ArrayUnion([vote_history])})
        app.logger.info(f"Vote recorded for {content_id} by user {user_id}. New count: {new_vote_count}")
        return jsonify({'status': 'success', 'message': 'Vote recorded', 'newVoteCount': new_vote_count})
    except Exception as e:
        app.logger.error(f"Error voting for content {content_id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/content/<content_id>/report', methods=['POST'])
def report_content(content_id):
    app.logger.info(f"Report request for content_id: {content_id}")
    try:
        data = request.get_json()
        reason = data.get('reason', 'Not specified')
        user_id = data.get('userId') or request.headers.get('X-User-ID')
        if not user_id:
            app.logger.warning(f"Missing 'userId' for reporting content_id: {content_id}.")
            return jsonify({'status': 'error', 'message': 'User ID is required'}), 400

        doc_ref = db.collection('contentItems').document(content_id)
        doc = doc_ref.get()
        if not doc.exists:
            app.logger.warning(f"Content not found for reporting: {content_id}")
            return jsonify({'status': 'error', 'message': 'Content not found'}), 404

        doc_data = doc.to_dict()
        if doc_data.get('status') == 'for_moderation':
            app.logger.info(f"Attempt to report content already under moderation: {content_id}")
            return jsonify({'status': 'error', 'message': 'This content is already under moderation'}), 403

        reporters = doc_data.get('reporters', [])  # Assuming 'reporters' is a list of user IDs
        if user_id in reporters:
            app.logger.info(f"User {user_id} already reported content {content_id}.")
            return jsonify({'status': 'error', 'message': 'You have already reported this content'}), 200

        current_reports_count = doc_data.get('reportedCount', 0)
        report_data = {'reason': reason, 'timestamp': datetime.utcnow(), 'userId': user_id, 'isAnonymous': True}

        update_payload = {
            'reportedCount': current_reports_count + 1,
            'reports': firestore.ArrayUnion([report_data]),  # Assuming 'reports' is an array of report objects
            'reporters': firestore.ArrayUnion([user_id])
        }

        if update_payload['reportedCount'] >= 3 and doc_data.get('status') == 'published':
            app.logger.info(
                f"Content {content_id} reached {update_payload['reportedCount']} reports, changing status to for_moderation")
            update_payload['status'] = 'for_moderation'
            update_payload[
                'moderation_note'] = f'Automatically sent for moderation ({update_payload["reportedCount"]} reports)'
            update_payload['moderation_timestamp'] = datetime.utcnow()

        doc_ref.update(update_payload)
        app.logger.info(f"Report submitted for {content_id} by user {user_id}.")
        return jsonify({'status': 'success', 'message': 'Report submitted'})
    except Exception as e:
        app.logger.error(f"Error submitting report for content {content_id}: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/content/create', methods=['POST'])
def create_content():
    app.logger.info("Received request to /api/content/create")
    try:
        text = request.form.get('text', '')
        try:
            latitude = float(request.form.get('latitude'))
            longitude = float(request.form.get('longitude'))
        except (TypeError, ValueError):
            app.logger.warning("Invalid or missing coordinates for content creation.")
            return jsonify(
                {'status': 'error', 'message': 'Latitude and longitude are required and must be numbers.'}), 400

        user_id = request.form.get('userId') or request.headers.get('X-User-ID')
        if not user_id:
            app.logger.warning("User ID missing for content creation.")
            return jsonify({'status': 'error', 'message': 'User ID is required'}), 400

        image_url = None
        if 'image' in request.files:
            image = request.files['image']
            if image and image.filename != '':
                filename = secure_filename(image.filename)
                file_extension = os.path.splitext(filename)[1].lower()
                if file_extension.lstrip('.') not in ALLOWED_IMAGE_EXTENSIONS:
                    app.logger.warning(f"Unsupported image type uploaded: {filename}")
                    return jsonify({'status': 'error', 'message': 'Unsupported image type.'}), 400

                image_data = image.read()  # Read image data
                if len(image_data) > MAX_IMAGE_SIZE:  # Check size before temp file
                    app.logger.warning(f"Uploaded image {filename} too large: {len(image_data)} bytes.")
                    return jsonify({'status': 'error',
                                    'message': f'Image size exceeds limit of {MAX_IMAGE_SIZE // (1024 * 1024)}MB.'}), 400

                # Re-assign unique_filename to avoid using original potentially unsafe filename in GCS path
                unique_gcs_filename = f"content_images/{str(uuid.uuid4())}{file_extension}"

                # Uploading image_data (bytes) directly
                blob = bucket.blob(unique_gcs_filename)
                blob.upload_from_string(image_data, content_type=image.content_type)
                blob.make_public()
                image_url = blob.public_url
            else:
                app.logger.info("Image file provided but filename is empty or file is not valid.")

        new_content = {
            'text': text, 'imageUrl': image_url, 'latitude': latitude, 'longitude': longitude,
            'timestamp': datetime.utcnow(), 'userId': user_id, 'isAnonymous': True,
            # Consider if API posts should be anonymous
            'voteCount': 0, 'reportedCount': 0, 'status': 'published'
        }
        doc_ref = db.collection('contentItems').document()
        doc_ref.set(new_content)
        doc_ref.update({'itemId': doc_ref.id})  # Add itemId to the document
        app.logger.info(f"Content created successfully via API by user {user_id}. Content ID: {doc_ref.id}")
        return jsonify(dict(status='success', message='Content created successfully', contentId=doc_ref.id))
    except Exception as e:
        app.logger.error(f"Error creating content via API: {e}", exc_info=True)
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/post/<item_id>')
def post_view(item_id):
    items_for_map = []
    try:
        items_query = db.collection('contentItems') \
            .where('status', '==', 'published') \
            .order_by('voteCount', direction=firestore.Query.ASCENDING) \
            .order_by('timestamp', direction=firestore.Query.DESCENDING) \
            .stream()
        for item_doc in items_query:
            item_data = item_doc.to_dict()
            item_data['itemId'] = item_doc.id
            if 'latitude' in item_data and 'longitude' in item_data:
                items_for_map.append(item_data)
    except Exception as e:
        app.logger.error(f"Error loading map items for post_view: {e}", exc_info=True)

    target_item_data = None
    try:
        doc_ref = db.collection('contentItems').document(item_id)
        doc = doc_ref.get()
        if doc.exists:
            target_item_data = doc.to_dict()
            target_item_data['itemId'] = item_id
        else:
            app.logger.warning(f"Target item {item_id} not found for post_view.")
            # Optionally, return a 404 page here:
            # return render_template('404.html'), 404
    except Exception as e:
        app.logger.error(f"Error retrieving target item {item_id} for post_view: {e}", exc_info=True)

    return render_template(
        'index.html',
        items=items_for_map,
        target_item_id=item_id,
        target_item_data=target_item_data,
        maps_api_key=GOOGLE_MAPS_API_KEY
    )


if __name__ == '__main__':
    if os.environ.get("WERKZEUG_RUN_MAIN") != "true":  # To prevent show_server_urls from running twice with reloader
        show_server_urls()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=True)