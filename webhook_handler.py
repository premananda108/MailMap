import base64
import utils
import image_utils
import firestore_utils
import email_utils


def handle_postmark_webhook_request(
        request_json_data,
        query_token,
        app_logger,
        db_client,
        bucket,
        app_context,
        inbound_url_token_config,
        allowed_image_extensions_config,
        max_image_size_config,
        app_config
):
    """
    Handles the logic for processing an inbound Postmark webhook request.
    Checks for user existence by email, creates if not found, and associates content.
    Returns a dictionary with 'status' and other relevant data (message, contentId).
    """
    app_logger.info(f"handle_postmark_webhook_request called. Verifying token: {query_token}")

    if not utils.verify_inbound_token(query_token, inbound_url_token_config):
        app_logger.warning(
            f"Invalid token in Postmark webhook URL. Provided token: {query_token}")
        return {'status': 'error', 'message': 'Invalid token', 'http_status_code': 401}

    try:
        from_email = request_json_data.get('FromFull', {}).get('Email', '') if request_json_data.get(
            'FromFull') else request_json_data.get('From', '')
        subject = request_json_data.get('Subject', '')
        text_body = request_json_data.get('TextBody', '')
        html_body = request_json_data.get('HtmlBody', '')
        attachments = request_json_data.get('Attachments', [])

        app_logger.info(
            f"Processing email via webhook from {from_email} with subject: '{subject}'. Attachments: {len(attachments)}")

        if not from_email:
            app_logger.warning("Email received via webhook without a 'From' email address. Cannot process.")
            return {'status': 'error', 'message': 'Sender email not found', 'http_status_code': 400}

        # --- Блок проверки и создания пользователя ---
        user_id_for_content = None
        user_data_from_email_check = firestore_utils.get_user_by_email(from_email, app_logger)

        if user_data_from_email_check:
            user_id_for_content = user_data_from_email_check.get('uid')
            app_logger.info(f"Existing user found for {from_email}: UID {user_id_for_content}")
            user_data = firestore_utils.get_user(user_id_for_content, app_logger)
            if not user_data:
                app_logger.error(f"Could not retrieve full user data for UID {user_id_for_content} after email check.")
            else:
                app_logger.info(f"Full user data fetched for UID {user_id_for_content}")
        else:
            user_data = None
            app_logger.info(f"No user found for {from_email}. Attempting to create one.")
            display_name = from_email.split('@')[0] if '@' in from_email else from_email

            try:
                new_user_doc_ref = db_client.collection('users').document()
                new_user_uid = new_user_doc_ref.id

                created_user_info = firestore_utils.create_user(
                    uid=new_user_uid,
                    email=from_email,
                    display_name=display_name,
                    provider='email_webhook',
                    app_logger=app_logger
                )
                if created_user_info:
                    user_id_for_content = new_user_uid
                    user_data = created_user_info
                    app_logger.info(f"Successfully created new user for {from_email} with UID: {user_id_for_content}")
                else:
                    app_logger.warning(
                        f"Failed to create user for {from_email} in Firestore. Content will be saved without a specific userId.")
            except Exception as e_user_create:
                app_logger.error(f"Exception during user creation for {from_email}: {e_user_create}", exc_info=True)
                app_logger.warning(f"Content will be saved without a specific userId due to user creation error.")

        # Получаем настройки лимита
        photo_limit = app_config.get('PHOTO_UPLOAD_LIMIT', 0)

        # Получаем текущий счетчик пользователя
        current_photo_count = 0
        if user_data:
            current_photo_count = user_data.get('photo_upload_count_current_month', 0)

        app_logger.info(
            f"User {user_id_for_content or 'N/A'}: Current photo count: {current_photo_count}, Limit: {photo_limit}")

        processed_content_ids = []
        skipped_due_to_limit = 0

        if attachments:
            app_logger.info(f"Processing {len(attachments)} attachments for email from {from_email}.")

            # Считаем количество изображений в attachments
            image_attachments = [att for att in attachments if att.get('ContentType', '').startswith('image/')]
            app_logger.info(f"Found {len(image_attachments)} image attachments to process.")

            for i, attachment in enumerate(attachments):
                # Reset per-image variables
                current_image_url = None
                current_exif_lat = None
                current_exif_lng = None

                content_type = attachment.get('ContentType', '')
                original_filename = attachment.get('Name', '')
                content_base64 = attachment.get('Content', '')

                app_logger.debug(
                    f"Attachment {i + 1}: Name='{original_filename}', ContentType='{content_type}', HasContent={bool(content_base64)}")

                if not content_type.startswith('image/'):
                    app_logger.debug(f"Attachment '{original_filename}' is not an image. Skipping.")
                    continue
                if not original_filename:
                    app_logger.debug(f"Attachment {i + 1} has no filename. Skipping.")
                    continue

                # ПРОВЕРКА ЛИМИТА ДЛЯ КАЖДОГО ИЗОБРАЖЕНИЯ
                if user_id_for_content and photo_limit > 0:
                    if current_photo_count >= photo_limit:
                        app_logger.warning(
                            f"User {user_id_for_content} has reached photo upload limit ({current_photo_count}/{photo_limit}). "
                            f"Skipping image '{original_filename}'."
                        )
                        skipped_due_to_limit += 1
                        continue  # Пропускаем это изображение, но продолжаем обработку других

                try:
                    app_logger.debug(f"Decoding Base64 for attachment '{original_filename}'.")
                    image_bytes = base64.b64decode(content_base64)
                    app_logger.debug(f"Decoded '{original_filename}'. Length: {len(image_bytes)} bytes.")

                    current_image_url, current_exif_lat, current_exif_lng = image_utils.process_uploaded_image(
                        image_bytes=image_bytes,
                        original_filename=original_filename,
                        app_logger=app_logger,
                        bucket=bucket,
                        allowed_extensions=allowed_image_extensions_config,
                        max_size=max_image_size_config
                    )

                    if current_image_url:
                        app_logger.info(
                            f"Successfully processed image attachment '{original_filename}'. URL: {current_image_url}")

                        # Определяем координаты для этого изображения
                        image_specific_latitude = None
                        image_specific_longitude = None

                        if current_exif_lat is not None and current_exif_lng is not None:
                            image_specific_latitude = current_exif_lat
                            image_specific_longitude = current_exif_lng
                            app_logger.info(
                                f"Using EXIF GPS data for '{original_filename}': lat={image_specific_latitude}, lng={image_specific_longitude}")
                        else:
                            app_logger.info(
                                f"No EXIF GPS data for image '{original_filename}'. Attempting to parse from subject: '{subject}'")
                            subject_lat, subject_lng = utils.parse_location_from_subject(subject)
                            if subject_lat is not None and subject_lng is not None:
                                image_specific_latitude = subject_lat
                                image_specific_longitude = subject_lng
                                app_logger.info(
                                    f"Used coordinates from subject for '{original_filename}': lat={image_specific_latitude}, lng={image_specific_longitude}")

                        if image_specific_latitude is None or image_specific_longitude is None:
                            app_logger.warning(
                                f"Could not determine coordinates for post from image '{original_filename}' (email: {from_email}, subject: '{subject}'). Skipping this image.")
                            continue

                        content_data = {
                            'text': text_body or html_body,
                            'imageUrl': current_image_url,
                            'latitude': image_specific_latitude,
                            'longitude': image_specific_longitude,
                            'status': 'published',
                            'voteCount': 0,
                            'reportedCount': 0,
                            'subject': subject
                        }
                        if user_id_for_content:
                            content_data['userId'] = user_id_for_content

                        content_id = firestore_utils.save_content_item(content_data, app_logger)

                        if content_id:
                            processed_content_ids.append(content_id)
                            app_logger.info(
                                f"Content saved for image '{original_filename}' with ID: {content_id} from email by {from_email}")

                            # ИНКРЕМЕНТИРУЕМ СЧЕТЧИК СРАЗУ ПОСЛЕ УСПЕШНОГО СОХРАНЕНИЯ
                            if user_id_for_content:
                                try:
                                    firestore_utils.increment_user_photo_count(user_id_for_content, app_logger)
                                    # Обновляем локальный счетчик для следующих изображений в этом же письме
                                    current_photo_count += 1
                                    app_logger.info(
                                        f"Incremented photo_upload_count_current_month for user {user_id_for_content} to {current_photo_count} for image {original_filename}.")
                                except Exception as e_increment:
                                    app_logger.error(
                                        f"Failed to increment photo_upload_count_current_month for user {user_id_for_content}: {e_increment}",
                                        exc_info=True)

                            # Отправляем уведомление
                            if from_email:
                                notification_id = email_utils.create_email_notification_record(db_client, content_id,
                                                                                               from_email)
                                if notification_id:
                                    email_sent_ok = email_utils.send_pending_notification(db_client, notification_id,
                                                                                          app_context=app_context)
                                    if email_sent_ok:
                                        app_logger.info(
                                            f'Notification email process initiated for notification_id {notification_id} (content: {content_id}).')
                                    else:
                                        app_logger.warning(
                                            f'Notification email process failed for notification_id {notification_id} (content: {content_id}).')
                                else:
                                    app_logger.warning(
                                        f"Failed to create email notification record for content {content_id}")
                        else:
                            app_logger.error(
                                f"Failed to save content for image '{original_filename}' from email by {from_email}, subject: '{subject}'.")
                            continue
                    else:
                        app_logger.warning(f"Failed to process image attachment '{original_filename}'.")
                        continue

                except base64.binascii.Error as b64_error:
                    app_logger.error(f"Base64 decoding error for attachment '{original_filename}': {b64_error}",
                                     exc_info=True)
                    continue
                except Exception as e_proc:
                    app_logger.error(f"Error processing attachment '{original_filename}': {e_proc}", exc_info=True)
                    continue
        else:
            app_logger.info("No attachments found in the email.")

        # Формируем ответ с учетом пропущенных изображений
        if not processed_content_ids and not skipped_due_to_limit:
            app_logger.warning(
                f"No suitable images found or processed from attachments for email by {from_email}, subject: '{subject}'.")
            return {'status': 'error', 'message': 'No valid images found in attachments', 'http_status_code': 200}

        # Если есть обработанный контент
        success_message = f'{len(processed_content_ids)} content item(s) published successfully'
        if skipped_due_to_limit > 0:
            success_message += f', {skipped_due_to_limit} image(s) skipped due to upload limit'

        return {
            'status': 'success' if processed_content_ids else 'partial_success',
            'contentIds': processed_content_ids,
            'message': success_message,
            'skipped_count': skipped_due_to_limit,
            'http_status_code': 200
        }

    except Exception as e:
        app_logger.error(f"Critical error in handle_postmark_webhook_request: {e}", exc_info=True)
        return {'status': 'error', 'message': f'Internal server error: {str(e)}', 'http_status_code': 500} 