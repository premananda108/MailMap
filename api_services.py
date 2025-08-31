import os
import uuid
from flask import current_app
import firestore_utils  # Direct import
import image_utils  # Direct import
from werkzeug.utils import secure_filename


def create_new_content_from_api(form_data, files, user_id, app_logger, bucket_client, allowed_extensions,
                                max_image_size):
    """
    Handles the logic for creating new content submitted via an API endpoint.
    Returns a dictionary with status, message, and contentId or error.
    """
    app_logger.info(f"API: create_new_content_from_api called by user: {user_id}. Form data keys: {list(form_data.keys()) if form_data else 'None'}. Files keys: {list(files.keys()) if files else 'None'}.")
    # Log parts of content_data (form_data here)
    app_logger.info(f"API: text='{form_data.get('text', '')[:50]}...', latitude='{form_data.get('latitude')}', longitude='{form_data.get('longitude')}'")

    try: # Outer try-block for general errors
        text = form_data.get('text', '')
        try:
            latitude = float(form_data.get('latitude'))
            longitude = float(form_data.get('longitude'))
        except (TypeError, ValueError, AttributeError):
            app_logger.warning("API content creation: Invalid or missing coordinates.")
            return {'status': 'error', 'message': 'Latitude and longitude are required and must be numbers.',
                    'http_code': 400}

        if not user_id:
            app_logger.warning("API content creation: User ID missing.")
            return {'status': 'error', 'message': 'User ID is required.', 'http_code': 400}

        image_url = None # Initialize image_url

        if 'image' in files and files['image'] and files['image'].filename != '': # Ensure an actual file is provided
            # Check user and upload limit first
            app_logger.info(f"API: Image file found: {files['image'].filename}. Checking user and limits for user_id: {user_id}")
            user_data = firestore_utils.get_user(user_id, app_logger)
            app_logger.info(f"API: get_user returned: {user_data}")

            if not user_data:
                app_logger.warning(f"API content creation: User {user_id} not found before image processing.")
                return {'status': 'error', 'message': 'User not found.', 'http_code': 404}

            photo_upload_count_current_month = user_data.get('photo_upload_count_current_month', 0)
            # Use .get for config to avoid KeyError if not set, though tests should set it.
            photo_upload_limit = current_app.config.get('PHOTO_UPLOAD_LIMIT', current_app.config.get('MAX_FREE_PHOTO_UPLOADS_PER_MONTH', 0)) # Check both names
            app_logger.info(f"API: User {user_id} photo count: {photo_upload_count_current_month}, Limit from config: {photo_upload_limit}")

            if photo_upload_count_current_month >= photo_upload_limit:
                app_logger.warning(f"API content creation: User {user_id} reached photo upload limit ({photo_upload_count_current_month}/{photo_upload_limit}).")
                return {'status': 'error', 'message': f"Photo upload limit of {photo_upload_limit} reached for this month.", 'http_code': 403}

            # Proceed with image processing if limit not reached
            image_file = files['image']
            app_logger.info(f"API: Processing image file: {image_file.filename}")
            original_filename = secure_filename(image_file.filename)
            file_extension = os.path.splitext(original_filename)[1].lower().lstrip('.')

            if file_extension not in allowed_extensions:
                app_logger.warning(f"API content creation: Unsupported image type uploaded: {original_filename}")
                return {'status': 'error', 'message': 'Unsupported image type.', 'http_code': 400}

            image_data = image_file.read()
            if len(image_data) > max_image_size:
                app_logger.warning(
                    f"API content creation: Uploaded image {original_filename} too large: {len(image_data)} bytes.")
                return {'status': 'error',
                        'message': f'Image size exceeds limit of {max_image_size // (1024 * 1024)}MB.',
                        'http_code': 400}

            image_file.seek(0)  # Reset stream position

            unique_gcs_filename = f"{user_id}/{str(uuid.uuid4())}.{file_extension}"
            app_logger.info(f"API: Attempting to upload image to GCS as {unique_gcs_filename}")
            # This will set image_url if successful
            image_url = image_utils.upload_image_to_gcs(
                image_data,
                unique_gcs_filename,
                app_logger,
                bucket_client,
                content_type=image_file.content_type
            )
            app_logger.info(f"API: upload_image_to_gcs returned: {image_url}")
            if not image_url: # Check if upload failed
                app_logger.error(f"API content creation: Failed to upload image {original_filename} to GCS.")
                return {'status': 'error', 'message': 'Image upload failed.', 'http_code': 500}

        elif 'image' in files: # Handles cases where 'image' key exists but file is invalid (e.g. empty filename)
            app_logger.info("API content creation: Image file provided but filename is empty or file is not valid.")
            # image_url remains None

        new_content_data = {
            'text': text,
            'imageUrl': image_url,
            'latitude': latitude,
            'longitude': longitude,
            'userId': user_id,
            'isAnonymous': True,
        }
        app_logger.info(f"API: Data for create_web_content_item: {new_content_data}")
        content_id = firestore_utils.create_web_content_item(new_content_data, app_logger)
        app_logger.info(f"API: create_web_content_item returned: {content_id}")

        if content_id:
            if image_url: # Only increment if an image was actually uploaded
                app_logger.info(f"API: Image uploaded, attempting to increment photo count for user {user_id}")
                try:
                    # Ensure firestore_utils.firestore.Increment is the correct reference
                    # If firestore_utils imports 'from firebase_admin import firestore', then this is correct.
                    user_ref = firestore_utils.get_db_client().collection('users').document(user_id) # Use get_db_client()
                    user_ref.update({
                        'photo_upload_count_current_month': firestore_utils.firestore.Increment(1)
                    })
                    app_logger.info(f"API: Incremented photo count for user {user_id}.")
                except Exception as e_increment: # More specific exception variable
                    app_logger.error(f"API: Failed to increment photo count for user {user_id}: {e_increment}", exc_info=True)
                    # For now, log the error; content creation is still considered successful.

            app_logger.info(
                f"API content creation: Content created successfully by user {user_id}. Content ID: {content_id}")
            return {'status': 'success', 'message': 'Content created successfully', 'contentId': content_id,
                    'http_code': 201}
        else:
            app_logger.error(f"API content creation: Failed to save content for user {user_id}.")
            return {'status': 'error', 'message': 'Failed to save content.', 'http_code': 500}

    except Exception as e_outer: # More specific exception variable for outer try-block
        app_logger.error(f"API content creation: Unexpected error for user {user_id} in outer try-block: {e_outer}", exc_info=True) # Log from outer try-block
        return {'status': 'error', 'message': 'An unexpected error occurred.', 'http_code': 500}


def process_content_vote(content_id, user_id, vote_value, app_logger):
    """
    Processes a vote on a content item.
    Returns a dictionary with status, message, newVoteCount, and http_code.
    """
    app_logger.info(f"API request: User {user_id} voting {vote_value} on content {content_id}")
    if vote_value not in [1, -1]:
        app_logger.warning(f"API vote: Invalid vote value {vote_value} by user {user_id} for content {content_id}.")
        return {'status': 'error', 'message': 'Invalid vote value', 'http_code': 400}

    if not user_id:
        app_logger.warning(f"API vote: User ID missing for content {content_id}.")
        return {'status': 'error', 'message': 'User ID is required', 'http_code': 400}

    try:
        item_data = firestore_utils.get_content_item(content_id, app_logger)
        if not item_data:
            return {'status': 'error', 'message': 'Content not found', 'http_code': 404}

        if item_data.get('status') == 'for_moderation':
            app_logger.info(f"API vote: Attempt to vote on content under moderation: {content_id}")
            return {'status': 'error', 'message': 'Cannot vote for content under moderation', 'http_code': 403}

        vote_result = firestore_utils.record_vote(content_id, user_id, vote_value, app_logger,
                                                  current_item_data=item_data)

        if 'error' in vote_result:
            app_logger.error(f"API vote: Error from firestore_utils for content {content_id}: {vote_result['error']}")
            return {
                'status': 'error',
                'message': vote_result['error'],
                'http_code': vote_result.get('status_code', 500)
            }
        else:
            # Успех от firestore_utils
            message_from_firestore = vote_result.get('message', 'Vote processed successfully')

            # ИЗМЕНЕНИЕ ЗДЕСЬ:
            # Если сообщение содержит "already voted", меняем статус, чтобы JS показал alert
            if message_from_firestore.lower().startswith('you have already voted'):
                app_logger.info(f"API vote: User already voted. Message: {message_from_firestore}")
                return {
                    'status': 'info',  # <--- Статус НЕ 'success', чтобы JS показал alert
                    'message': message_from_firestore,
                    'newVoteCount': vote_result.get('newVoteCount'),
                    'http_code': vote_result.get('status_code', 200)  # HTTP статус остается 200 OK
                }
            else:
                # Обычный успешный голос
                app_logger.info(f"API vote: Success for content {content_id}. Message: {message_from_firestore}")
                return {
                    'status': 'success',
                    'message': message_from_firestore,
                    'newVoteCount': vote_result.get('newVoteCount'),
                    'http_code': vote_result.get('status_code', 200)
                }

    except Exception as e:
        app_logger.error(f"API vote: Unexpected error for content {content_id} by user {user_id}: {e}", exc_info=True)
        return {'status': 'error', 'message': 'An unexpected error occurred during voting.', 'http_code': 500}


def process_content_report(content_id, user_id, reason, app_logger):
    """
    Processes a report on a content item.
    Returns a dictionary with status, message, and http_code.
    """
    app_logger.info(f"API request: User {user_id} reporting content {content_id} for reason: {reason}")
    if not user_id:
        app_logger.warning(f"API report: User ID missing for content {content_id}.")
        return {'status': 'error', 'message': 'User ID is required', 'http_code': 400}

    if not reason:
        app_logger.warning(f"API report: Reason missing for content {content_id} by user {user_id}.")
        return {'status': 'error', 'message': 'A reason for reporting is required.', 'http_code': 400}

    try:
        item_data = firestore_utils.get_content_item(content_id, app_logger)
        if not item_data:
            return {'status': 'error', 'message': 'Content not found', 'http_code': 404}

        if item_data.get('status') == 'for_moderation':
            app_logger.info(f"API report: Attempt to report content already under moderation: {content_id}")
            return {'status': 'error', 'message': 'This content is already under moderation', 'http_code': 403}

        # В вашем коде вы уже передавали current_item_data, это хорошо
        report_result = firestore_utils.record_report(content_id, user_id, reason, app_logger)

        # report_result от firestore_utils.record_report будет:
        # {'message': 'Report submitted', 'status_code': 200} при успехе
        # или {'error': 'Сообщение об ошибке', 'status_code': XXX} при ошибке

        if 'error' in report_result:
            # Ошибка от firestore_utils
            app_logger.error(
                f"API report: Error from firestore_utils for content {content_id}: {report_result['error']}")
            return {
                'status': 'error',
                'message': report_result['error'],
                'http_code': report_result.get('status_code', 500)
            }
        else:
            # Успех от firestore_utils
            app_logger.info(f"API report: Success for content {content_id}. Message: {report_result.get('message')}")
            return {
                'status': 'success',  # <--- Устанавливаем success
                'message': report_result.get('message', 'Report processed successfully'),
                'http_code': report_result.get('status_code', 200)
            }

    except Exception as e:
        app_logger.error(f"API report: Unexpected error for content {content_id} by user {user_id}: {e}", exc_info=True)
        return {'status': 'error', 'message': 'An unexpected error occurred during reporting.', 'http_code': 500}


def update_content_item(content_id, user_id, data, app_logger, gcs_bucket_name, allowed_extensions, max_image_size_bytes):
    """
    Placeholder for updating a content item.
    This function will be more fully implemented later.
    """
    app_logger.info(f"Starting update process for content_id: {content_id} by user_id: {user_id}.")
    app_logger.debug(f"Update data received: {data}")
    # gcs_bucket_name, allowed_extensions, max_image_size_bytes are not used in this iteration

    try:
        # 1. Fetch the existing content item
        item_data = firestore_utils.get_content_item(content_id, app_logger)
        if not item_data:
            app_logger.warning(f"Update failed: Content item {content_id} not found.")
            return {'status': 'error', 'message': 'Content not found', 'http_code': 404}

        # 2. Verify ownership
        if item_data.get('userId') != user_id:
            app_logger.warning(f"Update failed: User {user_id} not authorized to edit content {content_id} owned by {item_data.get('userId')}.")
            return {'status': 'error', 'message': 'User not authorized to edit this content', 'http_code': 403}

        update_data = {}

        # 3. Update text if provided
        if 'text' in data:
            if data['text'] != item_data.get('text'): # Only update if text is different
                update_data['text'] = data['text']
                app_logger.info(f"Text field for {content_id} will be updated.")
            else:
                app_logger.info(f"Text field for {content_id} is the same, no update to text.")


        # 4. Image handling - deferred for this iteration as per instructions.
        # No direct file uploads or image URL manipulations here.
        # If 'imageUrl' or 'image_action' were in 'data', logic would go here.
        app_logger.info("Image update logic is currently deferred for this function.")


        # 5. If update_data is empty, no changes were provided or needed
        if not update_data:
            app_logger.info(f"No actual changes to apply for content {content_id}.")
            return {'status': 'info', 'message': 'No changes provided or fields are already up-to-date', 'http_code': 200}

        # 6. Call Firestore update utility function (assumed to exist)
        # This function needs to be created in firestore_utils.py
        # For now, we assume it returns True on success, False on failure.
        app_logger.info(f"Attempting to update Firestore for content {content_id} with data: {update_data}")

        # Simulate the call to the not-yet-existing function
        # success = firestore_utils.update_web_content_item(content_id, update_data, app_logger)
        # For now, let's assume success to proceed with structuring the response.
        # This will be replaced by the actual call in the next step.

        # Call the new utility function from firestore_utils
        success = firestore_utils.update_web_content_item(content_id, update_data, app_logger)

        if success:
            app_logger.info(f"Content {content_id} updated successfully via firestore_utils.update_web_content_item.")
            return {
                'status': 'success',
                'message': 'Content updated successfully',
                'updated_fields': list(update_data.keys()),
                'content_id': content_id,
                'http_code': 200
            }
        else:
            app_logger.error(f"Failed to update content {content_id} in Firestore (as reported by update_web_content_item).")
            return {'status': 'error', 'message': 'Failed to update content in database', 'http_code': 500}

    except Exception as e:
        app_logger.error(f"Unexpected error in update_content_item for {content_id}: {e}", exc_info=True)
        return {'status': 'error', 'message': 'An unexpected error occurred', 'http_code': 500}