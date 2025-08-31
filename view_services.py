import firestore_utils # Direct import
from datetime import datetime # Needed for format_datetime_filter
from google.cloud import firestore

def get_home_page_data(app_logger, maps_api_key, user_id_for_filtering=None, logged_in_user_id=None, photo_upload_limit=25):
    """
    Gets the data required for the home page.
    With optional filtering by user ID for map items, and checks for logged-in user's photo limits.
    """
    remaining_photos = None # Default for anonymous users or if user data not found

    if logged_in_user_id:
        app_logger.debug(f"Fetching user data for {logged_in_user_id} to check photo limits.")
        user_data = firestore_utils.get_user(logged_in_user_id, app_logger)
        if user_data:
            photo_upload_count_current_month = user_data.get('photo_upload_count_current_month', 0)
            # PHOTO_UPLOAD_LIMIT = 25 # Standard limit # Removed
            calculated_remaining = photo_upload_limit - photo_upload_count_current_month
            remaining_photos = max(0, calculated_remaining)
            app_logger.info(f"User {logged_in_user_id}: Uploaded {photo_upload_count_current_month} photos this month (Limit: {photo_upload_limit}). Remaining: {remaining_photos}.")
        else:
            app_logger.warning(f"Logged-in user ID {logged_in_user_id} provided, but user data not found.")
            # remaining_photos stays None

    if user_id_for_filtering:
        app_logger.debug(f"Fetching map items for home page filtered by user ID: {user_id_for_filtering}")
        items_for_map = firestore_utils.get_published_items_for_map(app_logger, user_id_for_filtering)
    else:
        app_logger.debug("Fetching map items for home page without filtering")
        items_for_map = firestore_utils.get_published_items_for_map(app_logger)

    return {'items': items_for_map, 'maps_api_key': maps_api_key, 'remaining_photos': remaining_photos}

def get_post_page_data(item_id, app_logger, maps_api_key, user_id_for_filtering=None):
    """
    Gets the data required for a single post page.
    With optional filtering by user ID.
    """
    if user_id_for_filtering:
        app_logger.debug(f"Fetching data for post page, item_id: {item_id}, filtered by user ID: {user_id_for_filtering}")
        items_for_map = firestore_utils.get_published_items_for_map(app_logger, user_id_for_filtering)
    else:
        app_logger.debug(f"Fetching data for post page, item_id: {item_id}, without filtering")
        items_for_map = firestore_utils.get_published_items_for_map(app_logger)

    target_item_data = firestore_utils.get_content_item(item_id, app_logger)

    # Log if target item is not found, but still return data for map display
    if not target_item_data:
        app_logger.warning(f"Target item {item_id} not found for post_view service.")

    return {
        'items': items_for_map,
        'target_item_id': item_id,
        'target_item_data': target_item_data,
        'maps_api_key': maps_api_key
    }

def format_datetime_filter(timestamp_obj):
    """
    Formats a Firestore timestamp (which can be a datetime object or a dict)
    into a human-readable string.
    Moved from app.py.
    """
    if not timestamp_obj:
        return ''

    # Firestore Timestamps are often returned as Python datetime objects by the client library.
    # However, if they are ever passed as raw dicts (e.g., from a direct JSON source or older client versions),
    # this handles the conversion.
    if isinstance(timestamp_obj, dict):
        if '_seconds' in timestamp_obj: # Common representation in some contexts
            timestamp_obj = datetime.fromtimestamp(timestamp_obj['_seconds'])
        elif 'seconds' in timestamp_obj: # Another common representation
            timestamp_obj = datetime.fromtimestamp(timestamp_obj['seconds'])
        # If it's a dict but not in expected format, it might be problematic.
        # For now, if it's not converted, it will fall through to str() or fail isinstance below.

    if isinstance(timestamp_obj, datetime):
        return timestamp_obj.strftime('%d.%m.%Y %H:%M')

    # Fallback for unexpected types, or if it was a dict not converted
    return str(timestamp_obj)
