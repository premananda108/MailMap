# email_utils.py
import os
from datetime import datetime
from firebase_admin import firestore
# import requests # No longer needed for sending if using SMTP

# --- NEW IMPORTS for SMTP ---
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header  # For correct handling of non-ASCII characters in subject
from email.utils import formataddr  # For formatting From/To with names
# --- END OF NEW IMPORTS ---

from flask import render_template

POSTMARK_SERVER_TOKEN = os.environ.get("POSTMARK_SERVER_TOKEN", "YOUR_POSTMARK_SERVER_TOKEN_HERE")
SENDER_EMAIL_ADDRESS = os.environ.get("SENDER_EMAIL_ADDRESS", "noreply@example.com")
SENDER_NAME = os.environ.get("SENDER_NAME", "MailMap")  # Optional: sender name
BASE_URL = os.environ.get("BASE_URL", "https://mailmap.premananda.site")

# SMTP Postmark Configuration
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.postmarkapp.com")
SMTP_PORT = os.environ.get("SMTP_PORT", "587")  # Recommended port for TLS/STARTTLS
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")


def create_email_notification_record(db_client, content_id, recipient_email):
    # ... (this function remains unchanged) ...
    try:
        if not all([db_client, content_id, recipient_email]):
            print("Error in create_email_notification_record: Missing required parameters")
            return None
        notification_data = {
            'contentId': content_id,
            'recipientEmail': recipient_email,
            'status': 'pending',
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow(),
            'attempts': 0,
            'lastAttemptAt': None,
            'lastError': None,
            'type': 'content_published',
            'metadata': {
                'contentId': content_id,
                'recipientEmail': recipient_email
            }
        }
        doc_ref = db_client.collection('emailNotifications').document()
        doc_ref.set(notification_data)
        print(f"DEBUG: Email notification record created: {doc_ref.id} for {recipient_email}")
        return doc_ref.id
    except Exception as e:
        print(f"Error in create_email_notification_record: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


def send_pending_notification(db_client, notification_id, app_context=None):
    notification_ref = db_client.collection('emailNotifications').document(notification_id)
    notification_doc = None
    try:
        notification_doc = notification_ref.get()
        if not notification_doc.exists:
            print(f"Error: Notification record {notification_id} not found.")
            return False

        notification_data = notification_doc.to_dict()
        STATUS_PENDING = 'pending'
        STATUS_SENT = 'sent'
        STATUS_FAILED = 'failed'
        # ...
        if notification_data.get('status') != STATUS_PENDING:
            print(
                f"Notification {notification_id} is not pending (status: {notification_data.get('status')}). Skipping.")
            return True

        content_id = notification_data.get('contentId')
        recipient_email = notification_data.get('recipientEmail')

        if not content_id or not recipient_email:
            # ... (error handling remains) ...
            error_msg = f"Notification {notification_id} does not contain contentId or recipientEmail."
            print(f"Error: {error_msg}")
            notification_ref.update({
                'status': 'failed', 'lastError': error_msg, 'updatedAt': datetime.utcnow(),
                'lastAttemptAt': datetime.utcnow(), 'attempts': firestore.Increment(1)
            })
            return False

        content_ref = db_client.collection('contentItems').document(content_id)
        content_doc = content_ref.get()
        if not content_doc.exists:
            # ... (error handling remains) ...
            error_msg = f"Content item {content_id} for notification {notification_id} not found."
            print(f"Error: {error_msg}")
            notification_ref.update({
                'status': 'failed', 'lastError': error_msg, 'updatedAt': datetime.utcnow(),
                'lastAttemptAt': datetime.utcnow(), 'attempts': firestore.Increment(1)
            })
            return False

        content_data = content_doc.to_dict()
        post_url = f"{BASE_URL}/post/{content_id}"
        original_subject_text = content_data.get('subject', 'Your content has been published!')
        image_url = content_data.get('imageUrl')
        text_from_content = content_data.get('text', '')
        latitude = content_data.get('latitude')
        longitude = content_data.get('longitude')

        email_subject_text = f"Your post on MailMap: \"{original_subject_text}\" has been published!"

        text_body = (
            f"Hello,\n\n"
            f"Your post \"{original_subject_text}\" has been successfully published on MailMap.\n"
            f"Text: {text_from_content}\n"
            f"Coordinates: {latitude}, {longitude}\n"
            f"View: {post_url}\n\n"
            f"Sincerely, The MailMap Team"
        )

        html_body = None
        template_context = {
            'text_content': text_from_content, 'image_url': image_url,
            'latitude': latitude, 'longitude': longitude, 'post_url': post_url,
            'subject_title': original_subject_text
        }

        html_body = None  # Initialize in case something goes wrong

        try:
            if app_context:
                # If app_context is provided (e.g., from a background task),
                # use it for template rendering.
                with app_context:
                    html_body = render_template('email_notification.html', **template_context)
            else:
                # If app_context is not provided (e.g., call from a Flask view function),
                # render_template will try to find an existing application context.
                # If no context exists, a RuntimeError will occur here.
                html_body = render_template('email_notification.html', **template_context)

        except RuntimeError as e:
            # This error occurs if render_template is called without an active Flask context
            # (and app_context was not provided or did not work).
            if "Working outside of application context" in str(e):
                print(
                    "Information: Rendering template outside/without active Flask application context. Using text fallback.")
                html_body = f"<p>{text_body.replace(chr(10), '<br>')}</p>"  # Use simple HTML from text body
            else:
                # If it's another RuntimeError not related to missing context,
                # it's better to re-raise it to avoid hiding another problem.
                raise e
        except Exception as e:
            # Catch other possible errors during rendering (e.g., TemplateNotFound if template is not found)
            print(f"Error rendering template 'email_notification.html': {e}. Using text fallback.")
            html_body = f"<p>{text_body.replace(chr(10), '<br>')}</p>"

        # Additional check in case html_body remains None for some reason
        # (e.g., if render_template returned None, although it usually raises an exception on error)
        if html_body is None:
            print("WARNING: html_body was not generated (remained None). Using text fallback.")
            html_body = f"<p>{text_body.replace(chr(10), '<br>')}</p>"

        print(f"Attempting to send email (SMTP) for notification {notification_id} to {recipient_email}")

        if POSTMARK_SERVER_TOKEN == "YOUR_POSTMARK_SERVER_TOKEN_HERE" or not POSTMARK_SERVER_TOKEN:
            print(
                "WARNING: Postmark server token (SMTP_USERNAME/PASSWORD) is not configured. Email will not be sent.")
            raise Exception("Postmark server token (SMTP_USERNAME/PASSWORD) is not configured.")

        # --- NEW EMAIL SENDING LOGIC via SMTP ---
        msg = MIMEMultipart('alternative')
        # Use formataddr for correct display of sender name if present
        msg['From'] = formataddr((str(Header(SENDER_NAME, 'utf-8')), SENDER_EMAIL_ADDRESS))
        msg['To'] = recipient_email
        # Use Header for correct handling of non-ASCII characters in subject
        msg['Subject'] = Header(email_subject_text, 'utf-8')

        # Attach text and HTML versions
        # Important: text first, then HTML
        part1 = MIMEText(text_body, 'plain', 'utf-8')
        part2 = MIMEText(html_body, 'html', 'utf-8')

        msg.attach(part1)
        msg.attach(part2)

        smtp_error = None
        try:
            # Connect to Postmark SMTP server
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
            server.ehlo()  # Greet the server
            server.starttls()  # Enable TLS encryption
            server.ehlo()  # Re-greet after STARTTLS
            server.login(SMTP_USERNAME, SMTP_PASSWORD)  # Authenticate
            server.sendmail(SENDER_EMAIL_ADDRESS, [recipient_email], msg.as_string())  # Send email
            server.quit()  # Close connection
            print(f"Email (SMTP) for notification {notification_id} sent successfully to {recipient_email}.")
            email_sent_status = True
        except smtplib.SMTPException as e:  # Catch specific SMTP errors
            smtp_error = f"SMTP Error: {str(e)}"
            print(f"Error sending email (SMTP) for notification {notification_id}: {smtp_error}")
            email_sent_status = False
        except Exception as e:  # Catch other possible errors (e.g., network issues)
            smtp_error = f"General error during SMTP sending: {str(e)}"
            print(f"Error sending email (SMTP) for notification {notification_id}: {smtp_error}")
            email_sent_status = False
        # --- END OF NEW SMTP LOGIC ---

        current_time = datetime.utcnow()
        if email_sent_status:
            notification_ref.update({
                'status': 'sent', 'updatedAt': current_time, 'lastAttemptAt': current_time,
                'attempts': firestore.Increment(1), 'lastError': None
            })
            return True
        else:
            notification_ref.update({
                'status': 'failed', 'lastError': smtp_error or "Unknown SMTP error",
                'updatedAt': current_time, 'lastAttemptAt': current_time,
                'attempts': firestore.Increment(1)
            })
            return False

    except Exception as e:
        # ... (critical error handling remains) ...
        error_str = str(e)
        print(f"Critical error in send_pending_notification for {notification_id}: {error_str}")
        import traceback
        traceback.print_exc()
        try:
            if notification_doc and notification_doc.exists:
                notification_ref.update({
                    'status': 'failed', 'lastError': error_str, 'updatedAt': datetime.utcnow(),
                    'lastAttemptAt': datetime.utcnow(), 'attempts': firestore.Increment(1)
                })
        except Exception as inner_e:
            print(f"Failed to update notification status {notification_id} after critical error: {inner_e}")
        return False