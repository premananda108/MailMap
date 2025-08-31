import firebase_admin # Added import for firebase_admin.get_app()
from firebase_admin import firestore, storage
from datetime import datetime, timedelta, timezone # <--- ДОБАВЛЕН ИМПОРТ
from urllib.parse import urlparse, unquote
import re # For parsing the image path

# Firestore client will be initialized dynamically within functions
# db = firestore.client() # Removed global initialization

def get_db_client():
    """Returns an initialized Firestore client using the current Firebase app."""
    # Ensures that the client is created from the potentially mocked app instance.
    app = firebase_admin.get_app()
    return firestore.client(app=app)

def save_content_item(data, app_logger):
    """
    Saves a new content item to Firestore.
    """
    db = get_db_client()
    try:
        data.setdefault('notificationSent', False)
        data.setdefault('notificationSentAt', None)
        data.setdefault('shortUrl', None)
        data.setdefault('timestamp', firestore.SERVER_TIMESTAMP)

        doc_ref = db.collection('contentItems').document()
        data['itemId'] = doc_ref.id
        doc_ref.set(data)
        doc_ref.update({'shortUrl': doc_ref.id})
        app_logger.info(f"Content item saved successfully with ID: {doc_ref.id}")
        return doc_ref.id
    except Exception as e:
        app_logger.error(f"Error saving content item to Firestore. Data: {str(data)[:200]}. Error: {e}", exc_info=True)
        return None


def get_admin_by_email(email, app_logger):
    """
    Fetches an admin user by email.
    """
    db = get_db_client()
    try:
        admin_query_stream = db.collection('admins').where(field_path='email', op_string='==', value=email).limit(1).stream()
        admin_docs = list(admin_query_stream)
        if not admin_docs:
            app_logger.info(f"No admin found with email: {email}")
            return None

        admin_doc = admin_docs[0]
        admin_data = admin_doc.to_dict()
        admin_data['id'] = admin_doc.id
        app_logger.debug(f"Admin data retrieved for email {email}: {admin_doc.id}")
        return admin_data
    except Exception as e:
        app_logger.error(f"Error fetching admin by email '{email}': {e}", exc_info=True)
        return None


def is_admin_uid(uid, app_logger):
    """
    Checks if a UID belongs to an admin by looking for a document
    with that UID in the 'admins' collection.
    """
    db = get_db_client()
    if not uid:
        app_logger.warning("is_admin_uid: Called with no UID.")
        return False
    try:
        admin_ref = db.collection('admins').document(uid)
        admin_doc = admin_ref.get()
        if admin_doc.exists:
            app_logger.info(f"is_admin_uid: UID {uid} confirmed as admin.")
            return True
        else:
            app_logger.info(f"is_admin_uid: UID {uid} not found in admins collection.")
            return False
    except Exception as e:
        app_logger.error(f"is_admin_uid: Error checking admin status for UID {uid}: {e}", exc_info=True)
        return False


def get_content_items(app_logger, status_filter=None, order_by_field='timestamp',
                      order_by_direction=firestore.Query.DESCENDING, limit=None, filter_reported_items=False):
    """
    Fetches content items, with optional status filtering, ordering, and limit.
    """
    db = get_db_client()
    try:
        items_query = db.collection('contentItems')
        if status_filter and status_filter != 'all':
            items_query = items_query.where(field_path='status', op_string='==', value=status_filter)

        if filter_reported_items:
            items_query = items_query.where(field_path='reportedCount', op_string='>', value=0)

        if order_by_field:
            items_query = items_query.order_by(order_by_field, direction=order_by_direction)
            if order_by_field != 'timestamp' and order_by_field != 'voteCount':
                items_query = items_query.order_by('timestamp', direction=firestore.Query.DESCENDING)

        if limit:
            items_query = items_query.limit(limit)

        items_docs = items_query.stream()
        items = []
        for doc in items_docs:
            item_data = doc.to_dict()
            item_data['itemId'] = doc.id

            if (status_filter in ['for_moderation', 'all'] or filter_reported_items) and item_data.get('reportedCount', 0) > 0:
                try:
                    reports_ref = db.collection('reports').where(field_path='contentId', op_string='==', value=doc.id).stream()
                    item_data['reports'] = [report.to_dict() for report in reports_ref]
                except Exception as report_e:
                    app_logger.error(f"Error fetching reports for item {doc.id}: {report_e}", exc_info=True)
                    item_data['reports'] = []
            items.append(item_data)
        app_logger.info(
            f"Fetched {len(items)} items with status_filter='{status_filter}', ordered by '{order_by_field}'.")
        return items
    except Exception as e:
        app_logger.error(f"Error fetching content items (status: {status_filter}, order: {order_by_field}): {e}",
                         exc_info=True)
        return []


def update_content_status(content_id, new_status, admin_id, app_logger):
    """
    Updates the status of a content item (e.g., 'published', 'rejected').
    """
    db = get_db_client()
    try:
        content_ref = db.collection('contentItems').document(content_id)
        update_data = {
            'status': new_status,
            'moderated_by': admin_id,
            'moderated_at': firestore.SERVER_TIMESTAMP # Оставляем SERVER_TIMESTAMP, т.к. это прямое обновление
        }
        content_ref.update(update_data)
        app_logger.info(f"Content item {content_id} status updated to '{new_status}' by admin {admin_id}.")
        return True
    except Exception as e:
        app_logger.error(f"Error updating status for content {content_id} to '{new_status}': {e}", exc_info=True)
        return False


def get_content_item(content_id, app_logger):
    """
    Fetches a single content item by its ID.
    """
    db = get_db_client()
    try:
        doc_ref = db.collection('contentItems').document(content_id)
        doc = doc_ref.get()
        if doc.exists:
            item_data = doc.to_dict()
            item_data['itemId'] = doc.id
            app_logger.debug(f"Content item {content_id} fetched successfully.")
            return item_data
        else:
            app_logger.warning(f"Content item {content_id} not found.")
            return None
    except Exception as e:
        app_logger.error(f"Error fetching content item {content_id}: {e}", exc_info=True)
        return None


def record_vote(content_id, user_id, vote_value, app_logger, current_item_data=None):
    """
    Records a vote for a content item.
    Core logic from vote_content in app.py.
    Returns a dictionary with status and message/data.
    Accepts optional current_item_data to avoid re-fetching.
    """
    db = get_db_client()
    doc_ref = db.collection('contentItems').document(content_id)
    try:
        if current_item_data:
            doc_data = current_item_data
            app_logger.debug(f"Using provided item data for vote on {content_id}")
        else:
            app_logger.debug(f"Fetching item data for vote on {content_id}")
            doc_snapshot = doc_ref.get()
            if not doc_snapshot.exists:
                app_logger.warning(f"Content not found for voting: {content_id}")
                return {'error': 'Content not found', 'status_code': 404}
            doc_data = doc_snapshot.to_dict()

        if doc_data.get('status') == 'for_moderation':
            app_logger.info(f"Attempt to vote on content under moderation: {content_id}")
            return {'error': 'Cannot vote for content under moderation', 'status_code': 403}

        voters = doc_data.get('voters', {})
        current_vote_count = doc_data.get('voteCount', 0)
        new_vote_count = current_vote_count

        if user_id in voters and voters[user_id] == vote_value:
            app_logger.info(f"User {user_id} already voted this way for {content_id}.")
            return {'message': 'You have already voted this way', 'newVoteCount': current_vote_count,
                    'status_code': 200}

        if user_id in voters:
            previous_vote_val = voters[user_id]
            new_vote_count = current_vote_count - previous_vote_val + vote_value
        else:
            new_vote_count = current_vote_count + vote_value

        voters_update_payload = {f'voters.{user_id}': vote_value}

        update_payload_counts_voters = {
            'voteCount': new_vote_count,
        }
        for key, value in voters_update_payload.items():
            update_payload_counts_voters[key] = value
        doc_ref.update(update_payload_counts_voters)

        vote_history_entry = {
            'userId': user_id,
            'value': vote_value,
            'timestamp': datetime.now(timezone.utc),  # <--- ИЗМЕНЕНО
            'isAnonymous': True
        }
        doc_ref.update({
            'voteHistory': firestore.ArrayUnion([vote_history_entry])
        })

        app_logger.info(f"Vote recorded for {content_id} by user {user_id}. New count: {new_vote_count}")
        return {'message': 'Vote recorded', 'newVoteCount': new_vote_count, 'status_code': 200}
    except Exception as e:
        app_logger.error(f"Error recording vote for content {content_id}: {e}", exc_info=True)
        return {'error': str(e), 'status_code': 500}


def record_report(content_id, user_id, reason, app_logger):
    """
    Records a report for a content item.
    """
    db = get_db_client()
    try:
        doc_ref = db.collection('contentItems').document(content_id)
        doc = doc_ref.get()

        if not doc.exists:
            app_logger.warning(f"Content not found for reporting: {content_id}")
            return {'error': 'Content not found', 'status_code': 404}

        doc_data = doc.to_dict()
        if doc_data.get('status') == 'for_moderation':
            app_logger.info(f"Attempt to report content already under moderation: {content_id}")
            return {'error': 'This content is already under moderation', 'status_code': 403}

        reporters = doc_data.get('reporters', [])
        if user_id in reporters:
            app_logger.info(f"User {user_id} already reported content {content_id}.")
            return {'message': 'You have already reported this content', 'status_code': 200}

        current_reports_count = doc_data.get('reportedCount', 0)
        new_reports_count = current_reports_count + 1
        report_entry = {
            'reason': reason,
            'timestamp': datetime.now(timezone.utc), # <--- ИЗМЕНЕНО
            'userId': user_id,
            'isAnonymous': True
        }

        update_payload = {
            'reportedCount': new_reports_count,
            'reports': firestore.ArrayUnion([report_entry]),
            'reporters': firestore.ArrayUnion([user_id])
        }

        REPORT_THRESHOLD = 3
        if new_reports_count >= REPORT_THRESHOLD and doc_data.get('status') == 'published':
            app_logger.info(
                f"Content {content_id} reached {new_reports_count} reports, changing status to for_moderation."
            )
            update_payload['status'] = 'for_moderation'
            update_payload['moderation_note'] = f'Automatically sent for moderation ({new_reports_count} reports)'
            update_payload['moderation_timestamp'] = datetime.now(timezone.utc) # <--- ИЗМЕНЕНО для консистентности

        doc_ref.update(update_payload)
        app_logger.info(f"Report submitted for {content_id} by user {user_id}.")
        return {'message': 'Report submitted', 'status_code': 200}
    except Exception as e:
        app_logger.error(f"Error submitting report for content {content_id}: {e}", exc_info=True)
        return {'error': str(e), 'status_code': 500}


def create_web_content_item(data, app_logger):
    """
    Creates a new content item from web/API submission.
    """
    db = get_db_client()
    try:
        data.setdefault('timestamp', firestore.SERVER_TIMESTAMP) # Оставляем SERVER_TIMESTAMP, т.к. это прямое присвоение при создании
        data.setdefault('voteCount', 0)
        data.setdefault('reportedCount', 0)
        data.setdefault('status', 'published')
        data.setdefault('isAnonymous', True)

        doc_ref = db.collection('contentItems').document()
        data['itemId'] = doc_ref.id
        doc_ref.set(data)
        app_logger.info(f"Web content item created successfully with ID: {doc_ref.id}")
        return doc_ref.id
    except Exception as e:
        app_logger.error(f"Error creating web content item. Data: {str(data)[:200]}. Error: {e}", exc_info=True)
        return None


def get_published_items_for_map(app_logger, user_id=None):
    """
    Fetches published content items suitable for map display.
    If user_id is provided, only returns items created by that user.
    """
    db = get_db_client()
    try:
        # Начинаем с базового запроса
        items_query = db.collection('contentItems').where(field_path='status', op_string='==', value='published')

        # Добавляем фильтр по userId, если он указан
        if user_id:
            items_query = items_query.where(field_path='userId', op_string='==', value=user_id)
            app_logger.debug(f"Filtering map items for user ID: {user_id}")

        # Добавляем сортировку
        items_query = items_query.order_by('voteCount', direction=firestore.Query.ASCENDING) \
                             .order_by('timestamp', direction=firestore.Query.DESCENDING)

        items_docs = items_query.stream()
        items_for_map = []
        for item_doc in items_docs:
            item_data = item_doc.to_dict()
            item_data['itemId'] = item_doc.id
            if 'latitude' in item_data and 'longitude' in item_data:
                items_for_map.append(item_data)
            else:
                app_logger.debug(f"Item {item_doc.id} skipped for map, missing coordinates.")

        filter_message = f" for user {user_id}" if user_id else ""
        app_logger.info(f"Fetched {len(items_for_map)} published items for map display{filter_message}.")
        return items_for_map
    except Exception as e:
        app_logger.error(f"Error fetching published items for map: {e}", exc_info=True)
        return []


def create_user(uid, email, display_name, provider, app_logger):
    """
    Creates a new user document in Firestore.
    """
    db = get_db_client()
    try:
        user_ref = db.collection('users').document(uid)
        now_utc = datetime.now(timezone.utc)
        period_end_date = now_utc + timedelta(days=30)
        user_data = {
            'uid': uid,
            'email': email,
            'displayName': display_name,
            'provider': provider,
            'createdAt': firestore.SERVER_TIMESTAMP,
            'subscription_plan': 'free',
            'subscription_status': 'free_tier',
            'photo_upload_count_current_month': 0,
            'current_period_start': now_utc,
            'current_period_end': period_end_date,
            'customer_id': None,
            'subscription_id': None
        }
        user_ref.set(user_data)
        app_logger.info(f"User created successfully with UID: {uid}")
        return user_data
    except Exception as e:
        app_logger.error(f"Error creating user {uid}: {e}", exc_info=True)
        return None


def get_user(uid, app_logger):
    """
    Fetches a user document by UID from Firestore.
    """
    db_client = get_db_client() # Renamed to avoid conflict with global 'db' in app.py if imported there
    try:
        user_ref = db_client.collection('users').document(uid)
        doc = user_ref.get()
        if doc.exists:
            user_data = doc.to_dict()
            app_logger.debug(f"User data fetched successfully for UID: {uid}")
            return user_data
        else:
            app_logger.warning(f"User document not found for UID: {uid}")
            return None
    except Exception as e:
        app_logger.error(f"Error fetching user {uid}: {e}", exc_info=True)
        return None


def get_user_by_email(email, app_logger):
    """
    Fetches a user document by email from Firestore.
    """
    db = get_db_client()
    try:
        users_ref = db.collection('users')
        query = users_ref.where(field_path='email', op_string='==', value=email).limit(1)
        results = query.stream()
        user_list = list(results)

        if user_list:
            user_doc = user_list[0]
            user_data = user_doc.to_dict()
            app_logger.debug(f"User data fetched successfully for email: {email}")
            return user_data
        else:
            app_logger.warning(f"User document not found for email: {email}")
            return None
    except Exception as e:
        app_logger.error(f"Error fetching user by email {email}: {e}", exc_info=True)
        return None

def migrate_content_ownership(old_user_id, new_user_id, app_logger):
    """
    Updates the userId in contentItems from old_user_id to new_user_id.
    """
    if old_user_id == new_user_id:
        app_logger.info(f"Old UID and New UID are the same ({old_user_id}). No content migration needed.")
        return True
    db = get_db_client()
    try:
        content_items_ref = db.collection('contentItems')
        query = content_items_ref.where(field_path='userId', op_string='==', value=old_user_id)
        docs_to_update = query.stream()

        updated_count = 0
        batch = db.batch()
        for doc in docs_to_update:
            app_logger.info(f"Migrating content item {doc.id} from user {old_user_id} to {new_user_id}")
            batch.update(doc.reference, {'userId': new_user_id})
            updated_count += 1
            if updated_count % 400 == 0:  # Firestore batch limit is 500 operations
                batch.commit()
                batch = db.batch()

        if updated_count % 400 != 0:  # Commit any remaining operations
            batch.commit()

        app_logger.info(f"Successfully migrated {updated_count} content items from {old_user_id} to {new_user_id}.")
        return True
    except Exception as e:
        app_logger.error(f"Error migrating content ownership from {old_user_id} to {new_user_id}: {e}", exc_info=True)
        return False


def delete_content_item(content_id, user_id, app_logger, is_admin_delete=False):
    """
    Deletes a content item from Firestore and its associated image from Firebase Storage.
    Decrements the user's photo upload count if an image was deleted.
    """
    db = get_db_client()
    try:
        content_ref = db.collection('contentItems').document(content_id)
        content_doc = content_ref.get()

        if not content_doc.exists:
            app_logger.warning(f"Content item {content_id} not found for deletion.")
            return {'status': 'error', 'message': 'Content not found', 'code': 404}

        content_data = content_doc.to_dict()
        author_id = content_data.get('userId')
        image_url = content_data.get('imageUrl')

        # Важно: Проверка авторизации должна оставаться здесь,
        # чтобы только владелец мог удалить свой контент.
        if not is_admin_delete and author_id != user_id:
            app_logger.warning(f"User {user_id} not authorized to delete content {content_id} owned by {author_id}.")
            return {'status': 'error', 'message': 'User not authorized to delete this content', 'code': 403}

        # Сначала удаляем документ из Firestore
        content_ref.delete()
        app_logger.info(f"Content item {content_id} deleted successfully from Firestore.")

        image_deleted_from_storage = False # Флаг для отслеживания удаления из Storage

        if image_url:
            if 'firebasestorage.googleapis.com' in image_url:
                try:
                    parsed_url = urlparse(image_url)
                    match = re.search(r'/o/([^?]+)', parsed_url.path)
                    if match:
                        image_path = unquote(match.group(1))
                        bucket = storage.bucket()
                        blob = bucket.blob(image_path)

                        if blob.exists():
                            blob.delete()
                            app_logger.info(f"Image {image_path} deleted successfully from Firebase Storage for content {content_id}.")
                            image_deleted_from_storage = True # Устанавливаем флаг
                        else:
                            app_logger.warning(f"Image {image_path} not found in Firebase Storage for content {content_id}.")
                    else:
                        app_logger.warning(f"Could not parse image path from URL: {image_url} for content {content_id}")
                except Exception as e:
                    app_logger.error(f"Error deleting image {image_url} from Firebase Storage for content {content_id}: {e}", exc_info=True)
                    # Даже если удаление из Storage не удалось, продолжаем, т.к. запись из Firestore удалена.
                    # Можно добавить более сложную логику обработки ошибок здесь.
            else:
                app_logger.info(f"Image URL {image_url} is not a Firebase Storage URL, skipping deletion for content {content_id}.")

        # Уменьшаем счетчик фото, если было изображение и оно было связано с этим контентом
        # (независимо от того, успешно ли оно удалилось из Storage, т.к. запись контента удалена)
        # ИЛИ если image_deleted_from_storage is True (если хотите уменьшать только при успешном удалении из Storage)
        if image_url:
            try:
                user_ref = db.collection('users').document(author_id) # Используем author_id
                user_doc = user_ref.get()
                if user_doc.exists:
                    # Уменьшаем счетчик, но не позволяем ему стать отрицательным,
                    # хотя Firestore.Increment(-1) сам по себе не предотвратит < 0,
                    # если значение уже 0. Лучше проверить.
                    current_count = user_doc.to_dict().get('photo_upload_count_current_month', 0)
                    if current_count > 0:
                        user_ref.update({
                            'photo_upload_count_current_month': firestore.Increment(-1)
                        })
                        app_logger.info(f"Decremented photo upload count for user {author_id} for deleted content {content_id} (had image).")
                    else:
                        app_logger.info(f"Photo upload count for user {author_id} is already 0 or not set, not decrementing (had image).")
                else:
                    app_logger.warning(f"User {author_id} not found, cannot decrement photo count for deleted content {content_id} (had image).")
            except Exception as e:
                app_logger.error(f"Error decrementing photo count for user {author_id} after deleting content {content_id} (had image): {e}", exc_info=True)
                # Ошибка здесь не должна прерывать общий успех удаления контента.
        else:
            app_logger.info(f"Content item {content_id} did not have an imageUrl. Skipping photo count decrement for user {author_id}.")

        return {'status': 'success', 'message': 'Content deleted successfully', 'code': 200}

    except Exception as e:
        app_logger.error(f"An unexpected error occurred while deleting content {content_id}: {e}", exc_info=True)
        return {'status': 'error', 'message': 'An unexpected error occurred', 'code': 500}


def update_web_content_item(content_id, data, app_logger):
    """
    Updates a specific content item in Firestore.
    Adds 'timestamp_updated' to the data.
    Returns True on success, False on failure.
    """
    db = get_db_client()
    doc_ref = db.collection('contentItems').document(content_id) # Changed from 'web_content' to 'contentItems'

    # Add or update the 'timestamp_updated' field
    data_to_update = data.copy() # Avoid modifying the original dict passed to the function
    data_to_update['timestamp_updated'] = firestore.SERVER_TIMESTAMP

    app_logger.info(f"Attempting to update content item {content_id} with data fields: {list(data_to_update.keys())}")

    try:
        doc_ref.update(data_to_update)
        app_logger.info(f"Content item {content_id} updated successfully in Firestore.")
        return True
    except Exception as e:
        app_logger.error(f"Error updating content item {content_id} in Firestore: {e}", exc_info=True)
        return False