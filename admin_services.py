import firestore_utils # Using direct import
from firebase_admin import auth

# Removed old authenticate_admin function

def verify_admin_id_token(id_token, app_logger):
    """
    Verifies a Firebase ID token, checks if the user is an admin,
    and returns admin details if valid.
    """
    if not id_token:
        app_logger.warning("verify_admin_id_token: Called with no ID token.")
        return None

    try:
        decoded_token = auth.verify_id_token(id_token)
        uid = decoded_token.get('uid')
        email = decoded_token.get('email')

        if not uid:
            app_logger.error("verify_admin_id_token: UID not found in decoded token.")
            return None

        app_logger.info(f"verify_admin_id_token: Token verified for UID {uid}, email {email}.")

        # Check if this UID is in the admins collection
        if firestore_utils.is_admin_uid(uid, app_logger):
            app_logger.info(f"verify_admin_id_token: UID {uid} confirmed as admin by firestore_utils.")
            return {'uid': uid, 'email': email}
        else:
            app_logger.warning(f"verify_admin_id_token: UID {uid} is NOT an admin according to firestore_utils.")
            return None

    except auth.ExpiredIdTokenError:
        app_logger.warning("verify_admin_id_token: Firebase ID token has expired.")
        return None
    except auth.InvalidIdTokenError as e:
        app_logger.warning(f"verify_admin_id_token: Firebase ID token is invalid: {e}")
        return None
    except Exception as e:
        app_logger.error(f"verify_admin_id_token: An unexpected error occurred: {e}", exc_info=True)
        return None

def get_dashboard_items(status_filter, app_logger, view_type=None):
    """
    Gets items for the admin dashboard.
    The firestore_utils.get_content_items handles fetching reports and status display text.
    """
    if view_type == 'reported':
        app_logger.debug(f"Fetching reported dashboard items, ordered by reportedCount descending.")
        # For this specific call, status_filter is effectively ignored in favor of filter_reported_items
        items = firestore_utils.get_content_items(
            app_logger,
            status_filter=None, # Fetch reported items regardless of current status
            order_by_field='reportedCount',
            order_by_direction=firestore_utils.firestore.Query.DESCENDING,
            filter_reported_items=True
        )
    else:
        app_logger.debug(f"Fetching dashboard items with status_filter: {status_filter}")
        items = firestore_utils.get_content_items(app_logger, status_filter=status_filter)
    # The 'status_display' and 'reports' are handled by get_content_items in firestore_utils
    return items

def approve_content(content_id, admin_id, app_logger):
    """
    Approves a content item.
    """
    app_logger.debug(f"Attempting to approve content_id: {content_id} by admin_id: {admin_id}")
    success = firestore_utils.update_content_status(content_id, 'published', admin_id, app_logger)
    if success:
        app_logger.info(f"Content approved: {content_id} by admin: {admin_id}")
    else:
        app_logger.error(f"Failed to approve content: {content_id} by admin: {admin_id}")
    return success

def reject_content(content_id, admin_id, app_logger):
    """
    Rejects a content item.
    """
    app_logger.debug(f"Attempting to reject content_id: {content_id} by admin_id: {admin_id}")
    success = firestore_utils.update_content_status(content_id, 'rejected', admin_id, app_logger)
    if success:
        app_logger.info(f"Content rejected: {content_id} by admin: {admin_id}")
    else:
        app_logger.error(f"Failed to reject content: {content_id} by admin: {admin_id}")
    return success

def delete_content_admin(content_id, admin_id, app_logger):
    """
    Deletes a content item by an admin.
    """
    app_logger.debug(f"Admin {admin_id} attempting to delete content_id: {content_id}")

    # First, get the content item to find its original author (userId)
    content_item = firestore_utils.get_content_item(content_id, app_logger)
    if not content_item:
        app_logger.warning(f"Content item {content_id} not found for deletion by admin {admin_id}.")
        return {'status': 'error', 'message': 'Content not found', 'code': 404}

    original_author_id = content_item.get('userId')
    if not original_author_id:
        # This case should ideally not happen for valid content items,
        # but handle it defensively.
        # If there's no author, we can still proceed with deletion by admin,
        # but photo count decrement might not work as expected if it relies on author_id.
        # The delete_content_item function in firestore_utils handles missing author_id gracefully for photo count.
        app_logger.warning(f"Content item {content_id} does not have a userId (author). Admin {admin_id} proceeding with deletion.")
        # Pass None or a placeholder if your delete_content_item expects a userId for other reasons,
        # but for admin deletion, the main goal is to remove the item.
        # Given current delete_content_item, it's better to pass what's there.

    # Call the underlying delete function with is_admin_delete=True
    # The 'user_id' parameter here is the original author's ID,
    # used for decrementing photo counts or other author-specific cleanup.
    delete_result = firestore_utils.delete_content_item(
        content_id=content_id,
        user_id=original_author_id, # This is the ID of the original author
        app_logger=app_logger,
        is_admin_delete=True
    )

    if delete_result.get('status') == 'success':
        app_logger.info(f"Content item {content_id} deleted successfully by admin {admin_id}.")
        return {'status': 'success', 'message': 'Content deleted successfully by admin'}
    else:
        app_logger.error(f"Failed to delete content_id: {content_id} by admin {admin_id}. Reason: {delete_result.get('message')}")
        # Propagate the error message and code from the utility function
        return delete_result
