import os
import base64
import re
import tempfile
from datetime import datetime
import uuid
from dotenv import load_dotenv
from image_utils import extract_gps_coordinates
from flask import Flask, request, jsonify, current_app, \
    render_template, session, redirect, url_for
import firebase_admin
from firebase_admin import credentials, firestore, storage
from werkzeug.utils import secure_filename

# Load environment variables from .env file
load_dotenv()

from email_utils import create_email_notification_record, send_pending_notification

# Configure logging
import logging
from logging.handlers import RotatingFileHandler
import sys

# Create Flask app
# Configure logging
import logging
from logging.handlers import RotatingFileHandler
import sys

# Create Flask app
app = Flask(__name__, static_folder='static')

# Set up logging to file
log_handler = RotatingFileHandler('app.log', maxBytes=10000000, backupCount=5)
log_handler.setLevel(logging.INFO)
log_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
))
# Add the log handler to the app logger
app.logger.addHandler(log_handler)
# Output logs to stdout as well
app.logger.addHandler(logging.StreamHandler(sys.stdout))
app.logger.setLevel(logging.INFO)
app.logger.info('Flask app startup')

# Set up logging to file
log_handler = RotatingFileHandler('app.log', maxBytes=10000000, backupCount=5)
log_handler.setLevel(logging.INFO)
log_handler.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
))
# Add the log handler to the app logger
app.logger.addHandler(log_handler)
# Output logs to stdout as well
app.logger.addHandler(logging.StreamHandler(sys.stdout))
app.logger.setLevel(logging.INFO)
app.logger.info('Flask app startup')


@app.route('/.well-known/appspecific/com.chrome.devtools.json')
def chrome_devtools():
    # Respond with an empty JSON object for Chrome DevTools requests
    return jsonify({})


@app.before_request
def check_content_length():
    # Only check for POST, PUT, PATCH, DELETE methods as GET, HEAD, OPTIONS typically don't have bodies
    if request.method in ['POST', 'PUT', 'PATCH', 'DELETE']:
        # Allow if content_length is explicitly set to 0
        if request.content_length is None and request.headers.get('Transfer-Encoding', '').lower() != 'chunked':
            # Log the situation for debugging
            current_app.logger.warning(
                f"Request to {request.path} from {request.remote_addr} without Content-Length or chunked encoding."
            )
            # Consider returning 411 Length Required, but be cautious as some clients might not handle it well.
            # For now, we'll log and let it proceed, as the 'unexpected EOF' might be due to other reasons.
            # abort(411, description="Content-Length header is required for this request.")
            pass  # Or decide on a specific action, like abort(400) or abort(411)


# Configuration
INBOUND_URL_TOKEN = os.environ.get('INBOUND_URL_TOKEN', 'INBOUND_URL_TOKEN')
FIREBASE_STORAGE_BUCKET = os.environ.get('FIREBASE_STORAGE_BUCKET', 'your-project.appspot.com')
GOOGLE_MAPS_API_KEY = os.environ.get('GOOGLE_MAPS_API_KEY', '')
app.secret_key = os.environ.get('FLASK_SECRET_KEY') or os.environ.get('SECRET_KEY',
                                                                   'default-secret-key-for-development')
ALLOWED_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif'}
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB

# Firebase Initialization
if not firebase_admin._apps:
    # For production, use a service account key
    cred = credentials.ApplicationDefault()  # or credentials.Certificate('path/to/serviceAccountKey.json')
    firebase_admin.initialize_app(cred, {
        'storageBucket': FIREBASE_STORAGE_BUCKET
    })

db = firestore.client()

# Print server URLs at startup when in development mode
def show_server_urls():
    """Display server URLs in console when running in development mode"""
    import socket
    try:
        # Get local IP address
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()

        # Print URLs in a way similar to Flask's development server
        print(f"\n * Running on http://127.0.0.1:{os.environ.get('PORT', 8080)}")
        print(f" * Running on http://{local_ip}:{os.environ.get('PORT', 8080)}")
        print("Press CTRL+C to quit\n")
    except Exception as e:
        app.logger.error(f"Could not determine local IP: {e}")
bucket = storage.bucket()

# Register startup event handler
with app.app_context():
    # Initialize any application resources here
    pass


def verify_inbound_token(token_to_verify):
    """Verify token for inbound requests"""
    if not token_to_verify:
        return False
    return token_to_verify == INBOUND_URL_TOKEN



def parse_location_from_subject(subject):
    """Parse coordinates from email subject in lat:XX.XXX,lng:YY.YYY format"""
    if not subject:
        return None, None

    # Search for lat:XX.XXX,lng:YY.YYY pattern
    pattern = r'lat:([-+]?\d*\.?\d+),lng:([-+]?\d*\.?\d+)'
    match = re.search(pattern, subject, re.IGNORECASE)

    if match:
        try:
            lat = float(match.group(1))
            lng = float(match.group(2))

            # Validate coordinates
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                return lat, lng
        except ValueError:
            pass

    return None, None


def upload_image_to_gcs(image_data, filename):
    """Upload image to Google Cloud Storage"""
    try:
        # Generate unique filename
        file_extension = filename.split('.')[-1].lower()
        unique_filename = f"content_images/{uuid.uuid4()}.{file_extension}"

        # Create blob in bucket
        blob = bucket.blob(unique_filename)

        # Upload file
        blob.upload_from_string(
            image_data,
            content_type=f'image/{file_extension}'
        )

        # Make file publicly accessible
        blob.make_public()

        return blob.public_url

    except Exception as e:
        print(f"Error uploading image to GCS: {e}")
        return None


def save_content_to_firestore(data):
    """Save content to Firestore with additional fields for the notification system."""
    try:
        # Add fields for tracking notification status
        data['notificationSent'] = False  # Has the publication notification been sent
        data['notificationSentAt'] = None  # Time the notification was sent

        # Add shortUrl for use in short links (e.g., base62 of itemId)
        # This field will be populated after the document is created, when the ID is known
        data['shortUrl'] = None

        doc_ref = db.collection('contentItems').document()
        doc_ref.set(data)

        # Now that we have the document ID, we can create a shortUrl
        # For simplicity, we use the ID itself, but in production,
        # shorter identifiers or hashes could be used
        doc_ref.update({
            'shortUrl': doc_ref.id  # In the future, a function for generating a short URL can be used here
        })

        return doc_ref.id
    except Exception as e:
        print(f"Error saving to Firestore: {e}")
        return None


def process_email_attachments(attachments):
    """Process email attachments"""
    if not attachments:
        app.logger.info("No attachments found in email.")
        return None, None, None

    app.logger.info(f"Processing {len(attachments)} attachments.")
    for i, attachment in enumerate(attachments):
        content_type = attachment.get('ContentType', '')
        filename = attachment.get('Name', '')
        content = attachment.get('Content', '')  # Base64 encoded

        print(f"DEBUG: Attachment {i + 1}: Name='{filename}', ContentType='{content_type}', HasContent={bool(content)}")

        # Check if it's an image
        if not content_type.startswith('image/'):
            print(f"DEBUG: Attachment {i + 1} ('{filename}') is not an image (ContentType: {content_type}). Skipping.")
            continue

        # Check file extension
        if not filename or '.' not in filename:
            print(f"DEBUG: Attachment {i + 1} ('{filename}') has no extension. Skipping.")
            continue
        file_extension = filename.split('.')[-1].lower()
        if file_extension not in ALLOWED_IMAGE_EXTENSIONS:
            print(f"DEBUG: Attachment {i + 1} ('{filename}') has unsupported extension '{file_extension}'. Skipping.")
            continue

        try:
            # Decode base64
            print(f"DEBUG: Attachment {i + 1} ('{filename}'): Attempting to decode Base64 content.")
            image_data = base64.b64decode(content)
            print(f"DEBUG: Attachment {i + 1} ('{filename}'): Decoded. Image data length: {len(image_data)} bytes.")

            # Check file size
            if len(image_data) > MAX_IMAGE_SIZE:
                print(
                    f"DEBUG: File {filename} is too large ({len(image_data)} bytes). MAX_IMAGE_SIZE is {MAX_IMAGE_SIZE}. Skipping.")
                continue

            # Extract GPS coordinates
            print(f"DEBUG: Attachment {i + 1} ('{filename}'): Extracting EXIF GPS data.")
            lat, lng = extract_gps_coordinates(image_data)
            print(f"DEBUG: Attachment {i + 1} ('{filename}'): EXIF GPS: lat={lat}, lng={lng}")

            # Upload to GCS
            print(f"DEBUG: Attachment {i + 1} ('{filename}'): Uploading to GCS.")
            image_url = upload_image_to_gcs(image_data, filename)
            print(f"DEBUG: Attachment {i + 1} ('{filename}'): GCS URL: {image_url}")

            if image_url:
                print(f"DEBUG: Attachment {i + 1} ('{filename}'): Successfully processed. Returning URL: {image_url}")
                return image_url, lat, lng
            else:
                print(
                    f"DEBUG: Attachment {i + 1} ('{filename}'): Failed to upload to GCS or get URL. Continuing to next attachment.")


        except Exception as e:
            print(f"Error processing attachment {filename}: {e}")
            import traceback
            traceback.print_exc()  # Print full traceback for errors
            continue

    print("DEBUG: END OF LOOP IN process_email_attachments. BEFORE FINAL RETURN.")
    return None, None, None


@app.route('/webhook/postmark', methods=['POST'])
def postmark_webhook():
    token_from_query = request.args.get('token')

    app.logger.info(f"=== WEBHOOK DEBUG INFO ===")
    app.logger.info(f"Received request with token from query: {token_from_query}")
    app.logger.info(f"Expected token: {INBOUND_URL_TOKEN}")
    app.logger.info(f"Method: {request.method}")
    app.logger.info(f"Headers: {dict(request.headers)}")
    app.logger.info(f"Content-Type: {request.content_type}")
    app.logger.info(f"Content-Length: {request.content_length}")

    try:
        raw_data = request.get_data()
        app.logger.info(f"Raw data length: {len(raw_data) if raw_data else 0}")

        data = request.get_json(force=True)
        app.logger.info(f"JSON data received: {bool(data)}")
        if data:
            app.logger.info(f"JSON keys: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
    except Exception as e:
        app.logger.error(f"Error getting request data: {e}")
        return jsonify({
            'status': 'error',
            'message': f'Error parsing request data: {str(e)}'
        }), 400

    if not verify_inbound_token(token_from_query):
        print("Invalid token in URL query parameter")
        return jsonify({'status': 'error', 'message': 'Invalid token'}), 401

    try:
        if not data:
            print("No JSON data received")
            return jsonify({'status': 'error', 'message': 'No JSON data received'}), 400

        from_email = data.get('FromFull', {}).get('Email', '') if data.get('FromFull') else data.get('From', '')
        subject = data.get('Subject', '')
        text_body = data.get('TextBody', '')
        html_body = data.get('HtmlBody', '')
        attachments = data.get('Attachments', [])

        print(f"Received email from {from_email} with subject: {subject}")
        print(f"Number of attachments: {len(attachments)}")

        image_url, exif_lat, exif_lng = process_email_attachments(attachments)

        if not image_url:
            print("No suitable images found in attachments")
            return jsonify({'status': 'error', 'message': 'No valid images found'}), 400

        latitude, longitude = exif_lat, exif_lng

        if latitude is None or longitude is None:
            subject_lat, subject_lng = parse_location_from_subject(subject)
            if subject_lat is not None and subject_lng is not None:
                latitude, longitude = subject_lat, subject_lng

        if latitude is None or longitude is None:
            print("Could not determine coordinates for the post")
            return jsonify({
                'status': 'error',
                'message': 'Location coordinates not found. Please include GPS data in image or specify in subject as lat:XX.XXX,lng:YY.YYY'
            }), 200

        content_data = {
            'submitterEmail': from_email,
            'text': text_body or html_body,
            'imageUrl': image_url,
            'latitude': latitude,
            'longitude': longitude,
            'timestamp': datetime.utcnow(),
            'status': 'published',
            'voteCount': 0,
            'reportedCount': 0,
            'subject': subject
        }

        content_id = save_content_to_firestore(content_data)

        if content_id:
            print(f"Content saved successfully with ID: {content_id}")

            # Create a record for sending a notification
            if from_email:  # Check if we have the sender's address
                notification_id = create_email_notification_record(db, content_id, from_email)
                if notification_id:
                    ok = send_pending_notification(db, notification_id)   # app_context is not needed
                    if ok:
                        print(f'Notification {notification_id} sent')
                else:
                    print(f"Failed to create notification record for content {content_id}")

            return jsonify({
                'status': 'success',
                'contentId': content_id,
                'message': 'Content published successfully'
            })
        else:
            return jsonify({
                'status': 'error',
                'message': 'Failed to save content'
            }), 500

    except Exception as e:
        print(f"Error processing webhook: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'status': 'error',
            'message': f'Internal server error: {str(e)}'
        }), 500


# --- ADMIN PANEL ---

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        try:
            # Check administrator credentials
            admin_ref = db.collection('admins').where('email', '==', email).limit(1).get()

            if not admin_ref:
                return render_template('admin/login.html', error='Invalid email or password')

            admin_doc = admin_ref[0]
            admin_data = admin_doc.to_dict()

            # Password check (in a real project, use hashing)
            if admin_data.get('password') != password:
                return render_template('admin/login.html', error='Invalid email or password')

            # Create session for administrator
            session['admin_id'] = admin_doc.id
            session['admin_email'] = admin_data.get('email')

            return redirect(url_for('admin_dashboard'))

        except Exception as e:
            print(f"Error during administrator login: {e}")
            return render_template('admin/login.html', error='An error occurred during login')

    # If user is already logged in as admin, redirect to dashboard
    if 'admin_id' in session:
        return redirect(url_for('admin_dashboard'))

    return render_template('admin/login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_id', None)
    session.pop('admin_email', None)
    return redirect(url_for('admin_login'))

@app.route('/admin/dashboard')
def admin_dashboard():
    # Administrator access check
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))

    status_filter = request.args.get('status', 'for_moderation')

    try:
        items_query = db.collection('contentItems')

        # Apply status filter if it's not 'all'
        if status_filter != 'all':
            items_query = items_query.where('status', '==', status_filter)

        # Sort by creation time (newest first)
        items_query = items_query.order_by('timestamp', direction=firestore.Query.DESCENDING)

        # Get documents
        items_docs = items_query.get()

        items = []
        for doc in items_docs:
            item_data = doc.to_dict()
            item_data['itemId'] = doc.id

            # Get all reports for this item
            if status_filter == 'for_moderation' or status_filter == 'all':
                reports_ref = db.collection('reports').where('contentId', '==', doc.id).get()
                item_data['reports'] = [report.to_dict() for report in reports_ref]

            # Add display name for status
            status_map = {
                'published': 'Published',
                'for_moderation': 'For Moderation',
                'rejected': 'Rejected'
            }
            item_data['status_display'] = status_map.get(item_data.get('status'), item_data.get('status'))

            items.append(item_data)

        # Section title depending on the filter
        section_titles = {
            'all': 'All Posts',
            'for_moderation': 'Posts for Moderation',
            'published': 'Published Posts',
            'rejected': 'Rejected Posts'
        }

        return render_template('admin/dashboard.html', 
                              items=items, 
                              status=status_filter,
                              section_title=section_titles.get(status_filter, 'Posts'),
                              admin_email=session.get('admin_email'))

    except Exception as e:
        print(f"Error loading admin dashboard: {e}")
        import traceback
        traceback.print_exc()
        return render_template('500.html'), 500

@app.route('/admin/api/content/<content_id>/approve', methods=['POST'])
def admin_approve_content(content_id):
    # Administrator access check
    if 'admin_id' not in session:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    try:
        # Update post status to 'published'
        content_ref = db.collection('contentItems').document(content_id)
        content_ref.update({
            'status': 'published',
            'moderated_by': session.get('admin_id'),
            'moderated_at': firestore.SERVER_TIMESTAMP
        })

        return jsonify({'status': 'success', 'message': 'Post approved'})

    except Exception as e:
        print(f"Error approving post: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/admin/api/content/<content_id>/reject', methods=['POST'])
def admin_reject_content(content_id):
    # Administrator access check
    if 'admin_id' not in session:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    try:
        # Update post status to 'rejected'
        content_ref = db.collection('contentItems').document(content_id)
        content_ref.update({
            'status': 'rejected',
            'moderated_by': session.get('admin_id'),
            'moderated_at': firestore.SERVER_TIMESTAMP
        })

        return jsonify({'status': 'success', 'message': 'Post rejected'})

    except Exception as e:
        print(f"Error rejecting post: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

# Filter for formatting timestamps in templates
@app.template_filter('datetime')
def format_datetime(timestamp):
    if not timestamp:
        return ''

    # Handle different Firestore timestamp types
    if isinstance(timestamp, dict):
        if '_seconds' in timestamp:
            timestamp = datetime.fromtimestamp(timestamp['_seconds'])
        elif 'seconds' in timestamp:
            timestamp = datetime.fromtimestamp(timestamp['seconds'])

    if isinstance(timestamp, datetime):
        return timestamp.strftime('%d.%m.%Y %H:%M')

    return str(timestamp)

# --- CHANGES START HERE --- (This comment seems to be a leftover, removing)

@app.route('/')
def home():
    """
    Route for the main page, displaying a map with real data from Firestore.
    """
    items_for_map = []
    try:
        # Request all published items from the 'contentItems' collection
        # Sort by time descending to show newest first (optional)
        items_query = db.collection('contentItems') \
            .where('status', '==', 'published') \
            .order_by('voteCount', direction=firestore.Query.ASCENDING) \
            .order_by('timestamp', direction=firestore.Query.DESCENDING) \
            .stream()

        for item_doc in items_query:
            item_data = item_doc.to_dict()
            item_data['itemId'] = item_doc.id  # Add document ID, might be useful

            # Ensure latitude and longitude exist
            if 'latitude' in item_data and 'longitude' in item_data:
                # Optionally: Convert timestamp to string if needed for display in InfoWindow
                # if isinstance(item_data.get('timestamp'), datetime):
                #    item_data['timestamp'] = item_data['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
                items_for_map.append(item_data)
            else:
                print(f"DEBUG: Item {item_doc.id} skipped, missing coordinates.")

        print(f"DEBUG: Loaded {len(items_for_map)} items from Firestore for the map.")

    except Exception as e:
        print(f"Error loading data from Firestore for the map: {e}")
        # Can pass an empty list or an error message to the template
        # items_for_map = []
        # flash('Failed to load data for the map.', 'error') # if using flash messages

    return render_template('index.html', items=items_for_map, maps_api_key=GOOGLE_MAPS_API_KEY)


# --- API for interacting with posts ---

@app.route('/api/content/<content_id>/vote', methods=['POST'])
def vote_content(content_id):
    """API for voting on content (like/dislike)"""
    app.logger.info(f"=== VOTE DEBUG INFO ===")
    app.logger.info(f"Received vote request for content_id: {content_id}")
    app.logger.info(f"Headers: {dict(request.headers)}")
    app.logger.info(f"Content-Type: {request.content_type}")
    app.logger.info(f"Content-Length: {request.content_length}")

    try:
        # Get data from request
        data = request.get_json()
        print(f"Received data: {data}")

        if not data or 'vote' not in data:
            print(f"Error: missing vote parameter in data")
            return jsonify({'status': 'error', 'message': 'Missing vote parameter'}), 400

        vote_value = data.get('vote')  # 1 for like, -1 for dislike
        user_id = data.get('userId') or request.headers.get('X-User-ID')
        print(f"Vote value: {vote_value}, user_id: {user_id}")

        if not user_id:
            print(f"Error: missing user_id")
            return jsonify({'status': 'error', 'message': 'User ID is required'}), 400

        if vote_value not in [1, -1]:
            print(f"Error: invalid vote value: {vote_value}")
            return jsonify({'status': 'error', 'message': 'Invalid vote value'}), 400

        # Get document from Firestore
        doc_ref = db.collection('contentItems').document(content_id)
        print(f"Requesting document from Firestore: {content_id}")
        doc = doc_ref.get()

        if not doc.exists:
            print(f"Error: document not found in Firestore: {content_id}")
            return jsonify({'status': 'error', 'message': 'Content not found'}), 404

        print(f"Document found in Firestore: {content_id}")
        doc_data = doc.to_dict()
        print(f"Document data: {doc_data}")

        # Check if post is under moderation
        if doc_data.get('status') == 'for_moderation':
            print(f"Post {content_id} is under moderation, voting prohibited")
            return jsonify({
                'status': 'error',
                'message': 'Cannot vote for content under moderation'
            }), 403

        # Check if this user has already voted
        voters = doc_data.get('voters', {})
        if user_id in voters:
            previous_vote = voters[user_id]
            print(f"User {user_id} already voted for post {content_id}, previous vote: {previous_vote}")

            # If the vote is the same, return an error
            if previous_vote == vote_value:
                return jsonify({
                    'status': 'error',
                    'message': 'You have already voted this way',
                    'newVoteCount': doc_data.get('voteCount', 0)
                }), 200

            vote_adjustment = vote_value
        else:
            # If the user is voting for the first time, just add their vote
            vote_adjustment = vote_value

        # Update vote count
        # For simplicity, just increment/decrement; in a real application,
        # track IPs/users to prevent manipulation
        current_votes = doc_data.get('voteCount', 0)
        print(f"Current vote count: {current_votes}")

        new_vote_count = current_votes + vote_adjustment
        print(f"New vote count: {new_vote_count}")

        try:
            # Save user information and their vote
            voters_update = {f'voters.{user_id}': vote_value}

            # Record vote history
            vote_history = {
                'userId': user_id,
                'value': vote_value,
                'timestamp': datetime.utcnow(),
                'isAnonymous': True
            }

            doc_ref.update({
                'voteCount': new_vote_count,
                **voters_update,
                'voteHistory': firestore.ArrayUnion([vote_history])
            })
            print(f"Document update successful")
        except Exception as e:
            print(f"Error updating document: {e}")
            return jsonify({'status': 'error', 'message': f'Error updating vote count: {str(e)}'}), 500

        return jsonify({
            'status': 'success',
            'message': 'Vote recorded',
            'newVoteCount': new_vote_count
        })

    except Exception as e:
        print(f"Error voting for content {content_id}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/content/<content_id>/report', methods=['POST'])
def report_content(content_id):
    """API for reporting content"""
    try:
        # Get data from request
        data = request.get_json()
        reason = data.get('reason', 'Not specified')
        user_id = data.get('userId') or request.headers.get('X-User-ID')

        if not user_id:
            return jsonify({'status': 'error', 'message': 'User ID is required'}), 400

        # Get document from Firestore
        doc_ref = db.collection('contentItems').document(content_id)
        doc = doc_ref.get()

        if not doc.exists:
            return jsonify({'status': 'error', 'message': 'Content not found'}), 404

        # Check if post is already under moderation
        doc_data = doc.to_dict()
        if doc_data.get('status') == 'for_moderation':
            return jsonify({
                'status': 'error',
                'message': 'This content is already under moderation'
            }), 403

        # Check if this user has already reported
        reports = doc_data.get('reports', [])
        reporters = [report.get('userId') for report in reports if 'userId' in report]

        if user_id in reporters:
            return jsonify({
                'status': 'error',
                'message': 'You have already reported this content'
            }), 200

        # Increment report count
        doc_data = doc.to_dict()
        current_reports = doc_data.get('reportedCount', 0)

        # Create report object with user information
        report_data = {
            'reason': reason,
            'timestamp': datetime.utcnow(),
            'userId': user_id,
            'isAnonymous': True  # Mark as anonymous report
        }

        # Update document
        doc_ref.update({
            'reportedCount': current_reports + 1,
            'reports': firestore.ArrayUnion([report_data]),
            'reporters': firestore.ArrayUnion([user_id])  # Save list of users who reported
        })

        # If report count >= 3, mark content as requiring moderation
        if current_reports + 1 >= 3 and doc_data.get('status') == 'published':
            print(f"Post {content_id} reached {current_reports + 1} reports, changing status to for_moderation")
            try:
                doc_ref.update({
                    'status': 'for_moderation',
                    'moderation_note': f'Automatically sent for moderation ({current_reports + 1} reports)',
                    'moderation_timestamp': datetime.utcnow()
                })
                print(f"Post status {content_id} successfully changed to for_moderation")
            except Exception as e:
                print(f"Error changing post status {content_id}: {e}")

        return jsonify({
            'status': 'success',
            'message': 'Report submitted'
        })

    except Exception as e:
        print(f"Error submitting report for content {content_id}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

        @app.route('/api/content/create', methods=['POST'])
        def create_content():
            try:
                # Get parameters from request
                text = request.form.get('text', '')
                latitude = float(request.form.get('latitude'))
                longitude = float(request.form.get('longitude'))
                user_id = request.form.get('userId') or request.headers.get('X-User-ID')

                if not user_id:
                    return jsonify({'status': 'error', 'message': 'User ID is required'}), 400

                if not latitude or not longitude:
                    return jsonify({'status': 'error', 'message': 'Location coordinates are required'}), 400

                # Check if image is in request
                image_url = None
                if 'image' in request.files:
                    image = request.files['image']
                    if image.filename != '':
                        # Generate unique filename
                        filename = secure_filename(image.filename)
                        file_extension = os.path.splitext(filename)[1]
                        unique_filename = f"{str(uuid.uuid4())}{file_extension}"

                        # Create temporary file for upload
                        with tempfile.NamedTemporaryFile(delete=False) as temp:
                            image.save(temp.name)

                            # Upload file to Firebase Storage
                            bucket = storage.bucket()
                            blob = bucket.blob(f"content_images/{unique_filename}")
                            blob.upload_from_filename(temp.name)

                            # Make file public
                            blob.make_public()

                            # Get image URL
                            image_url = blob.public_url

                        # Delete temporary file
                        os.unlink(temp.name)

                # Create new record in Firestore
                new_content = {
                    'text': text,
                    'imageUrl': image_url,
                    'latitude': latitude,
                    'longitude': longitude,
                    'timestamp': datetime.utcnow(),
                    'userId': user_id,
                    'isAnonymous': True,
                    'voteCount': 0,
                    'reportedCount': 0,
                    'status': 'published'  # Initial status - published
                }

                # Add document to collection
                doc_ref = db.collection('contentItems').document()
                doc_ref.set(new_content)

                # Update document id
                doc_ref.update({
                    'itemId': doc_ref.id
                })

                return jsonify(dict(status='success', message='Content created successfully', contentId=doc_ref.id))
            except Exception as e:
                print(f"Error creating content: {e}")

        return jsonify({'status': 'error', 'message': str(e)}), 500


# --- END API for interacting with posts ---

@app.route('/post/<item_id>')
def post_view(item_id):
    """
    Route for viewing a specific post.
    The map is centered on the corresponding marker, and the marker is automatically opened.
    """
    # Get all published items for the map
    items_for_map = []
    try:
        # Request all published items (same query as in home())
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
        print(f"Error loading data from Firestore for the map: {e}")

    # Get target post data for SEO and metadata
    target_item_data = None
    try:
        doc_ref = db.collection('contentItems').document(item_id)
        doc = doc_ref.get()
        if doc.exists:
            target_item_data = doc.to_dict()
            # Don't forget to add the ID, as it's not part of the document data
            target_item_data['itemId'] = item_id
    except Exception as e:
        print(f"Error retrieving post data {item_id}: {e}")

    # Pass all items for the map, target item ID, and target item data for SEO to the template
    return render_template(
        'index.html',
        items=items_for_map,
        target_item_id=item_id,
        target_item_data=target_item_data,
        maps_api_key=GOOGLE_MAPS_API_KEY
    )


if __name__ == '__main__':
    # Show server URLs before starting
    show_server_urls()
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=True)