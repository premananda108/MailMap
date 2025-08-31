# email_utils.py
import os
import logging
from datetime import datetime
from firebase_admin import firestore

# import requests # No longer needed for sending if using SMTP

# Configure module logger
# This logger will inherit the configuration from the Flask app logger if this module
# is imported after the Flask app's logging is configured.
# If run obstáculos, it would need its own handler configuration.
logger = logging.getLogger(__name__)
# To ensure it logs if run standalone or if Flask logger isn't set to a low enough level:
# if not logger.handlers: # Add a basic handler if no handlers are configured
#     logger.setLevel(logging.INFO) # Or DEBUG
#     ch = logging.StreamHandler()
#     ch.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
#     logger.addHandler(ch)


import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr

from flask import render_template

# Environment variables for email configuration
POSTMARK_SERVER_TOKEN = os.environ.get("POSTMARK_SERVER_TOKEN", "YOUR_POSTMARK_SERVER_TOKEN_HERE")
SENDER_EMAIL_ADDRESS = os.environ.get("SENDER_EMAIL_ADDRESS", "noreply@example.com")
SENDER_NAME = os.environ.get("SENDER_NAME", "MailMap")
BASE_URL = os.environ.get("BASE_URL", "https://mailmap.premananda.site")

# SMTP Configuration
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.postmarkapp.com")
SMTP_PORT_STR = os.environ.get("SMTP_PORT", "587")
try:
    SMTP_PORT = int(SMTP_PORT_STR)
except ValueError:
    logger.error(f"Invalid SMTP_PORT value: '{SMTP_PORT_STR}'. Defaulting to 587.")
    SMTP_PORT = 587

# For Postmark SMTP, USERNAME and PASSWORD are the Server API Token.
# Ensure these environment variables are set to your POSTMARK_SERVER_TOKEN
# or modify the server.login() call to use POSTMARK_SERVER_TOKEN directly.
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", POSTMARK_SERVER_TOKEN)  # Default to POSTMARK_SERVER_TOKEN
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", POSTMARK_SERVER_TOKEN)  # Default to POSTMARK_SERVER_TOKEN


def create_email_notification_record(db_client, content_id, recipient_email):
    """Creates a record in Firestore about the need to send an email notification."""
    try:
        if not all([db_client, content_id, recipient_email]):
            logger.error("Missing required parameters for creating email notification record.")
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
        logger.info(f"Email notification record created: {doc_ref.id} for {recipient_email}")
        return doc_ref.id
    except Exception as e:
        logger.error(f"Error in create_email_notification_record for content_id {content_id}: {e}", exc_info=True)
        return None


def send_pending_notification(db_client, notification_id, app_context=None):
    """
    Loads a pending notification, sends an email using an HTML template, and updates its status.
    """
    notification_ref = db_client.collection('emailNotifications').document(notification_id)
    notification_doc = None
    try:
        notification_doc = notification_ref.get()
        if not notification_doc.exists:
            logger.error(f"Notification record {notification_id} not found.")
            return False

        notification_data = notification_doc.to_dict()

        STATUS_PENDING = 'pending'
        # STATUS_SENT = 'sent' # Defined but not used for comparison, only for update
        # STATUS_FAILED = 'failed' # Defined but not used for comparison, only for update

        if notification_data.get('status') != STATUS_PENDING:
            logger.info(
                f"Notification {notification_id} is not pending (status: {notification_data.get('status')}). Skipping."
            )
            return True  # Not an error, just nothing to do for this notification

        content_id = notification_data.get('contentId')
        recipient_email = notification_data.get('recipientEmail')

        if not content_id or not recipient_email:
            error_msg = f"Notification {notification_id} is missing contentId or recipientEmail."
            logger.error(error_msg)
            notification_ref.update({
                'status': 'failed', 'lastError': error_msg, 'updatedAt': datetime.utcnow(),
                'lastAttemptAt': datetime.utcnow(), 'attempts': firestore.Increment(1)
            })
            return False

        content_ref = db_client.collection('contentItems').document(content_id)
        content_doc = content_ref.get()
        if not content_doc.exists:
            error_msg = f"Content item {content_id} for notification {notification_id} not found."
            logger.error(error_msg)
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

        try:
            if app_context:
                with app_context:
                    html_body = render_template('email_notification.html', **template_context)
            else:
                html_body = render_template('email_notification.html', **template_context)
        except RuntimeError as e:
            if "Working outside of application context" in str(e):
                logger.info("Rendering template outside/without active Flask application context. Using text fallback.")
                html_body = f"<p>{text_body.replace(chr(10), '<br>')}</p>"
            else:
                logger.error(f"RuntimeError rendering template 'email_notification.html': {e}", exc_info=True)
                raise  # Re-raise if it's not the expected context error
        except Exception as e:
            logger.error(f"Error rendering template 'email_notification.html': {e}. Using text fallback.",
                         exc_info=True)
            html_body = f"<p>{text_body.replace(chr(10), '<br>')}</p>"

        if html_body is None:  # Should ideally not happen if exceptions are caught
            logger.warning("html_body was not generated (remained None after render attempts). Using text fallback.")
            html_body = f"<p>{text_body.replace(chr(10), '<br>')}</p>"

        logger.info(f"Attempting to send email (SMTP) for notification {notification_id} to {recipient_email}")

        if not SMTP_USERNAME or not SMTP_PASSWORD or SMTP_USERNAME == "YOUR_POSTMARK_SERVER_TOKEN_HERE":
            logger.error(
                "SMTP_USERNAME or SMTP_PASSWORD is not configured correctly (is it still the placeholder or empty?). Email will not be sent.")
            # Update notification record to reflect this configuration error
            notification_ref.update({
                'status': 'failed', 'lastError': "SMTP credentials not configured on server.",
                'updatedAt': datetime.utcnow(), 'lastAttemptAt': datetime.utcnow(),
                'attempts': firestore.Increment(1)
            })
            return False  # Critical configuration error

        msg = MIMEMultipart('alternative')
        msg['From'] = formataddr((str(Header(SENDER_NAME, 'utf-8')), SENDER_EMAIL_ADDRESS))
        msg['To'] = recipient_email
        msg['Subject'] = Header(email_subject_text, 'utf-8')

        part1 = MIMEText(text_body, 'plain', 'utf-8')
        part2 = MIMEText(html_body, 'html', 'utf-8')
        msg.attach(part1)
        msg.attach(part2)

        smtp_error_message = None
        email_sent_successfully = False
        try:
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
            server.ehlo()
            server.starttls()
            server.ehlo()
            logger.info(
                f"Attempting SMTP login with username: {SMTP_USERNAME[:5]}...")  # Log part of username for security
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SENDER_EMAIL_ADDRESS, [recipient_email], msg.as_string())
            server.quit()
            logger.info(f"Email (SMTP) for notification {notification_id} sent successfully to {recipient_email}.")
            email_sent_successfully = True
        except smtplib.SMTPAuthenticationError as e:
            smtp_error_message = f"SMTP Authentication Error: {e}. Check SMTP_USERNAME and SMTP_PASSWORD."
            logger.error(f"SMTP Authentication Error for notification {notification_id}: {e}")
            email_sent_successfully = False
        except smtplib.SMTPException as e:
            smtp_error_message = f"SMTP Error: {e}"
            logger.error(f"SMTP Error sending email for notification {notification_id}: {e}", exc_info=True)
            email_sent_successfully = False
        except Exception as e:
            smtp_error_message = f"General error during SMTP sending: {e}"
            logger.error(f"General error sending email (SMTP) for notification {notification_id}: {e}", exc_info=True)
            email_sent_successfully = False

        current_time = datetime.utcnow()
        update_data = {
            'updatedAt': current_time,
            'lastAttemptAt': current_time,
            'attempts': firestore.Increment(1)
        }
        if email_sent_successfully:
            update_data['status'] = 'sent'
            update_data['lastError'] = None
        else:
            update_data['status'] = 'failed'
            update_data['lastError'] = smtp_error_message or "Unknown SMTP error during send process"

        notification_ref.update(update_data)
        return email_sent_successfully

    except Exception as e:
        error_str = str(e)
        logger.critical(f"Critical unhandled error in send_pending_notification for {notification_id}: {error_str}",
                        exc_info=True)
        # Attempt to update notification record even on critical failure before this point
        try:
            if notification_doc and notification_doc.exists and notification_data.get('status') == STATUS_PENDING:
                notification_ref.update({
                    'status': 'failed', 'lastError': f"Critical function error: {error_str}",
                    'updatedAt': datetime.utcnow(), 'lastAttemptAt': datetime.utcnow(),
                    'attempts': firestore.Increment(1)
                })
        except Exception as inner_e:
            logger.error(
                f"Failed to update notification status {notification_id} after critical error in outer try-except: {inner_e}")
        return False


def send_verification_email(recipient_email, verification_link, app_context=None):
    """
    Sends a verification email to the user.

    Args:
        recipient_email (str): The email address of the recipient.
        verification_link (str): The email verification link.
        app_context: Flask application context, required for render_template.
    """
    subject_text = "Verify your email for MailMap"
    logger.info(f"Preparing to send verification email to {recipient_email} using link: {verification_link}")

    try:
        html_body = None
        # Plain text version for email clients that don't support HTML or as a fallback
        text_body = (
            f"Hello {recipient_email},\n\n"
            f"Thank you for registering with MailMap. Please verify your email address by clicking the link below:\n"
            f"{verification_link}\n\n"
            f"If you cannot click the link, please copy and paste it into your web browser.\n"
            f"If you did not create an account, please ignore this email.\n\n"
            f"Sincerely,\nThe MailMap Team"
        )

        template_context = {
            "verification_link": verification_link,
            "recipient_email": recipient_email  # Passed to template for personalization
        }

        # Try to render the HTML email body using Flask's render_template
        try:
            if app_context:
                with app_context:
                    html_body = render_template("email_verification.html", **template_context)
            else:
                # This branch might be hit if called from a script without app context
                # Flask's render_template typically needs an app context.
                # If current_app could be imported and used, it would be an option here,
                # but passing app_context is cleaner if the caller can provide it.
                logger.warning("Attempting to render 'email_verification.html' without explicit Flask app_context.")
                # This will likely fail if no context is implicitly available.
                html_body = render_template("email_verification.html", **template_context)
        except RuntimeError as e:
            if "Working outside of application context" in str(e) or "No application found" in str(e):
                logger.warning(
                    f"Flask app_context not available for render_template ('email_verification.html'): {e}. "
                    "Falling back to basic HTML link."
                )
                html_body = f"<p>Please verify your email by clicking this link: <a href='{verification_link}'>{verification_link}</a></p>"
            else:
                # Some other RuntimeError occurred
                logger.error(f"RuntimeError rendering template 'email_verification.html': {e}", exc_info=True)
                raise # Re-raise if it's not an expected context error
        except Exception as e: # Catch other template rendering errors
            logger.error(f"Error rendering template 'email_verification.html': {e}. Falling back to basic HTML link.", exc_info=True)
            html_body = f"<p>Please verify your email by clicking this link: <a href='{verification_link}'>{verification_link}</a></p>"

        if not html_body: # Ensure html_body is set
            logger.info("html_body was not generated by render_template, using basic HTML link as final fallback.")
            html_body = f"<p>Please verify your email by clicking this link: <a href='{verification_link}'>{verification_link}</a></p>"

        # Construct the email message
        msg = MIMEMultipart('alternative')
        msg['From'] = formataddr((str(Header(SENDER_NAME, 'utf-8')), SENDER_EMAIL_ADDRESS))
        msg['To'] = recipient_email
        msg['Subject'] = Header(subject_text, 'utf-8')

        # Attach parts
        part1 = MIMEText(text_body, 'plain', 'utf-8')
        part2 = MIMEText(html_body, 'html', 'utf-8')
        msg.attach(part1)
        msg.attach(part2)

        # Check SMTP configuration (same as in send_pending_notification)
        if not SMTP_USERNAME or not SMTP_PASSWORD or SMTP_USERNAME == "YOUR_POSTMARK_SERVER_TOKEN_HERE":
            logger.error("SMTP_USERNAME or SMTP_PASSWORD is not configured correctly. Verification email will not be sent.")
            return False

        # Send the email via SMTP
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.ehlo()  # Extended Hello
            server.starttls()  # Enable security
            server.ehlo()  # Re-send EHLO after STARTTLS
            logger.info(f"Attempting SMTP login for verification email with username: {SMTP_USERNAME[:5]}...") # Log first 5 chars for tracing
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.sendmail(SENDER_EMAIL_ADDRESS, [recipient_email], msg.as_string()) # Use list for recipients

        logger.info(f"Verification email sent successfully to {recipient_email}")
        return True
    except smtplib.SMTPAuthenticationError as e:
        logger.error(f"SMTP Authentication Error sending verification email to {recipient_email}: {e}. Check SMTP credentials.")
    except smtplib.SMTPServerDisconnected as e:
        logger.error(f"SMTP Server Disconnected error sending verification email to {recipient_email}: {e}")
    except smtplib.SMTPException as e: # Catch other specific SMTP errors
        logger.error(f"SMTP Error sending verification email to {recipient_email}: {e}")
    except Exception as e: # Catch any other non-SMTP errors
        logger.error(f"An unexpected error occurred while sending verification email to {recipient_email}: {e}", exc_info=True)

    return False