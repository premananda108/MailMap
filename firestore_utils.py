import firebase_admin
from firebase_admin import firestore
from datetime import datetime
import logging


def get_user_by_email(email, app_logger):
    """
    Get user data by email address.
    Returns user data dict or None if not found.
    """
    try:
        db = firestore.client()
        users_ref = db.collection('users').where('email', '==', email).limit(1).get()
        
        if users_ref:
            user_doc = users_ref[0]
            user_data = user_doc.to_dict()
            user_data['uid'] = user_doc.id
            app_logger.info(f"Found user by email {email}: {user_doc.id}")
            return user_data
        else:
            app_logger.info(f"No user found for email: {email}")
            return None
    except Exception as e:
        app_logger.error(f"Error getting user by email {email}: {e}", exc_info=True)
        return None


def get_user(uid, app_logger):
    """
    Get user data by UID.
    Returns user data dict or None if not found.
    """
    try:
        db = firestore.client()
        user_doc = db.collection('users').document(uid).get()
        
        if user_doc.exists:
            user_data = user_doc.to_dict()
            user_data['uid'] = user_doc.id
            app_logger.info(f"Retrieved user data for UID: {uid}")
            return user_data
        else:
            app_logger.warning(f"User document not found for UID: {uid}")
            return None
    except Exception as e:
        app_logger.error(f"Error getting user {uid}: {e}", exc_info=True)
        return None


def create_user(uid, email, display_name, provider, app_logger):
    """
    Create a new user in Firestore.
    Returns user data dict or None if creation failed.
    """
    try:
        db = firestore.client()
        user_data = {
            'email': email,
            'displayName': display_name,
            'provider': provider,
            'createdAt': datetime.utcnow(),
            'photo_upload_count_current_month': 0,
            'last_upload_reset': datetime.utcnow(),
            'isActive': True
        }
        
        db.collection('users').document(uid).set(user_data)
        user_data['uid'] = uid
        
        app_logger.info(f"Successfully created user {uid} for email {email}")
        return user_data
    except Exception as e:
        app_logger.error(f"Error creating user {uid} for email {email}: {e}", exc_info=True)
        return None


def save_content_item(content_data, app_logger):
    """
    Save content item to Firestore.
    Returns content ID or None if save failed.
    """
    try:
        db = firestore.client()
        
        # Add default fields
        content_data['timestamp'] = datetime.utcnow()
        content_data['notificationSent'] = False
        content_data['notificationSentAt'] = None
        content_data['shortUrl'] = None
        
        # Create document reference
        doc_ref = db.collection('contentItems').document()
        content_data['itemId'] = doc_ref.id
        
        # Save to Firestore
        doc_ref.set(content_data)
        
        # Update with shortUrl
        doc_ref.update({'shortUrl': doc_ref.id})
        
        app_logger.info(f"Content saved successfully with ID: {doc_ref.id}")
        return doc_ref.id
    except Exception as e:
        app_logger.error(f"Error saving content to Firestore: {e}", exc_info=True)
        return None


def increment_user_photo_count(uid, app_logger):
    """
    Increment user's photo upload count for current month.
    Returns True if successful, False otherwise.
    """
    try:
        db = firestore.client()
        user_ref = db.collection('users').document(uid)
        
        user_ref.update({
            'photo_upload_count_current_month': firestore.Increment(1)
        })
        
        app_logger.info(f"Incremented photo count for user {uid}")
        return True
    except Exception as e:
        app_logger.error(f"Error incrementing photo count for user {uid}: {e}", exc_info=True)
        return False


def reset_monthly_photo_count_if_needed(uid, app_logger):
    """
    Reset monthly photo count if it's a new month.
    Returns True if reset was needed and performed, False otherwise.
    """
    try:
        db = firestore.client()
        user_ref = db.collection('users').document(uid)
        user_doc = user_ref.get()
        
        if not user_doc.exists:
            app_logger.warning(f"User {uid} not found for photo count reset")
            return False
            
        user_data = user_doc.to_dict()
        last_reset = user_data.get('last_upload_reset')
        
        if last_reset:
            # Convert Firestore timestamp to datetime if needed
            if hasattr(last_reset, 'timestamp'):
                last_reset = datetime.fromtimestamp(last_reset.timestamp())
            elif isinstance(last_reset, dict) and '_seconds' in last_reset:
                last_reset = datetime.fromtimestamp(last_reset['_seconds'])
            
            current_month = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            last_reset_month = last_reset.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            
            if current_month > last_reset_month:
                user_ref.update({
                    'photo_upload_count_current_month': 0,
                    'last_upload_reset': datetime.utcnow()
                })
                app_logger.info(f"Reset monthly photo count for user {uid}")
                return True
        
        return False
    except Exception as e:
        app_logger.error(f"Error checking/resetting photo count for user {uid}: {e}", exc_info=True)
        return False 