import unittest
from unittest.mock import patch, MagicMock, call
from webhook_handlers import handle_postmark_webhook_request

# Basic App Context Mock (if needed by email_utils.send_pending_notification)
class MockAppContext:
    def __init__(self, db_client):
        self.db = db_client # Simulate app.db access if send_pending_notification uses it

class TestWebhookHandlers(unittest.TestCase):

    def setUp(self):
        self.mock_app_logger = MagicMock()
        self.mock_db_client = MagicMock()
        self.mock_bucket = MagicMock()
        self.mock_app_context = MockAppContext(self.mock_db_client)
        self.mock_inbound_url_token_config = "test_token"
        self.mock_allowed_image_extensions_config = ['.jpg', '.jpeg', '.png']
        self.mock_max_image_size_config = 5 * 1024 * 1024  # 5MB
        self.mock_app_config = {
            'PHOTO_UPLOAD_LIMIT': 5 # Default limit for tests, can be overridden per test
        }

        self.default_request_json_data = {
            'FromFull': {'Email': 'test@example.com'},
            'From': 'test@example.com',
            'Subject': 'Test Subject',
            'TextBody': 'Test text body',
            'HtmlBody': '<p>Test HTML body</p>',
            'Attachments': []
        }
        self.query_token = "test_token"
        self.valid_base64_content = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="

    # --- Tests for Core Webhook Logic: Token, Email Parsing, User ID ---

    @patch('webhook_handlers.utils.verify_inbound_token', return_value=False)
    def test_invalid_token_returns_401_error(self, mock_verify_token):
        request_data = self.default_request_json_data.copy()
        response = handle_postmark_webhook_request(
            request_data, "invalid_query_token", self.mock_app_logger, self.mock_db_client,
            self.mock_bucket, self.mock_app_context, self.mock_inbound_url_token_config,
            self.mock_allowed_image_extensions_config, self.mock_max_image_size_config,
            self.mock_app_config
        )
        self.assertEqual(response['status'], 'error')
        self.assertEqual(response['message'], 'Invalid token')
        self.assertEqual(response['http_status_code'], 401)
        mock_verify_token.assert_called_once_with("invalid_query_token", self.mock_inbound_url_token_config)
        self.mock_app_logger.warning.assert_called_once_with(
            f"Invalid token in Postmark webhook URL. Provided token: invalid_query_token"
        )

    @patch('webhook_handlers.utils.verify_inbound_token', return_value=True) # Token is valid for this test
    def test_missing_sender_email_returns_400_error(self, mock_verify_token):
        request_data = self.default_request_json_data.copy()
        request_data.pop('FromFull', None)
        request_data.pop('From', None)

        response = handle_postmark_webhook_request(
            request_data, self.query_token, self.mock_app_logger, self.mock_db_client,
            self.mock_bucket, self.mock_app_context, self.mock_inbound_url_token_config,
            self.mock_allowed_image_extensions_config, self.mock_max_image_size_config,
            self.mock_app_config
        )
        self.assertEqual(response['status'], 'error')
        self.assertEqual(response['message'], 'Sender email not found')
        self.assertEqual(response['http_status_code'], 400)
        mock_verify_token.assert_called_once() # Ensure token check still happens
        self.mock_app_logger.warning.assert_called_once_with(
            "Email received via webhook without a 'From' email address. Cannot process."
        )

    @patch('webhook_handlers.utils.verify_inbound_token', return_value=True)
    @patch('webhook_handlers.firestore_utils.get_user_by_email', return_value=None) # New user
    @patch('webhook_handlers.firestore_utils.create_user', return_value=None) # User creation fails
    @patch('webhook_handlers.image_utils.process_uploaded_image')
    @patch('webhook_handlers.firestore_utils.save_content_item')
    @patch('webhook_handlers.email_utils.create_email_notification_record') # To check it's still called
    @patch('webhook_handlers.email_utils.send_pending_notification')   # To check it's still called
    @patch('webhook_handlers.utils.parse_location_from_subject', return_value=(10.0, 20.0)) # Mock location parsing
    def test_user_creation_fails_processes_images_without_userid(
        self, mock_parse_location, mock_send_notification, mock_create_email_record,
        mock_save_content, mock_process_image, mock_create_user,
        mock_get_user_by_email, mock_verify_token
    ):
        user_email = "creationfail@example.com"
        request_data = self.default_request_json_data.copy()
        request_data['FromFull']['Email'] = user_email
        request_data['From'] = user_email
        request_data['Attachments'] = [
            {'Name': 'image1.jpg', 'Content': self.valid_base64_content, 'ContentType': 'image/jpeg'}
        ]
        self.mock_app_config['PHOTO_UPLOAD_LIMIT'] = 5 # Ensure limit is not 0

        mock_process_image.return_value = ('http://example.com/image.jpg', 10.0, 20.0)
        mock_save_content.return_value = 'content_id_no_user'
        # Mock the db client's document().id generation for create_user internal logic
        mock_new_user_doc_ref = MagicMock()
        mock_new_user_doc_ref.id = "generated_temp_uid" # UID that create_user would have used
        self.mock_db_client.collection('users').document.return_value = mock_new_user_doc_ref


        response = handle_postmark_webhook_request(
            request_data, self.query_token, self.mock_app_logger, self.mock_db_client,
            self.mock_bucket, self.mock_app_context, self.mock_inbound_url_token_config,
            self.mock_allowed_image_extensions_config, self.mock_max_image_size_config,
            self.mock_app_config
        )

        self.assertEqual(response['status'], 'success') # Or partial_success depending on exact definition
        self.assertEqual(len(response['contentIds']), 1)
        self.assertEqual(response['contentIds'][0], 'content_id_no_user')

        mock_get_user_by_email.assert_called_once_with(user_email, self.mock_app_logger)

        # Check that create_user was called (even if it returned None)
        # The call to db.collection('users').document() happens before create_user in the handler
        self.mock_db_client.collection('users').document.assert_called_once()
        mock_create_user.assert_called_once()

        self.mock_app_logger.warning.assert_any_call(
            f"Failed to create user for {user_email} in Firestore. Content will be saved without a specific userId."
        )

        mock_process_image.assert_called_once()
        # Verify that save_content_item was called and 'userId' was not in content_data
        args, kwargs = mock_save_content.call_args
        content_data_arg = args[0]
        self.assertNotIn('userId', content_data_arg)
        self.assertEqual(content_data_arg['imageUrl'], 'http://example.com/image.jpg')

        # Ensure no attempt to increment photo count for a non-existent user
        self.mock_db_client.collection('users').document().update.assert_not_called()
        mock_create_email_record.assert_called_once() # Email notification should still be attempted
        mock_send_notification.assert_called_once()

    # --- Original Tests (corrected app_config passing) ---
    @patch('webhook_handlers.utils.verify_inbound_token', return_value=True)
    @patch('webhook_handlers.firestore_utils.get_user_by_email')
    @patch('webhook_handlers.image_utils.process_uploaded_image')
    @patch('webhook_handlers.firestore_utils.save_content_item')
    @patch('webhook_handlers.email_utils.create_email_notification_record')
    @patch('webhook_handlers.email_utils.send_pending_notification', return_value=True)
    @patch('webhook_handlers.utils.parse_location_from_subject', return_value=(None, None))
    def test_handle_postmark_webhook_multiple_images_all_succeed(
        self, mock_parse_location, mock_send_notification, mock_create_notification,
        mock_save_content, mock_process_image, mock_get_user_by_email, mock_verify_token
    ):
        mock_get_user_by_email.return_value = {'uid': 'test_user_uid', 'email': 'test@example.com'}
        # Need to mock get_user as well, as it's called after get_user_by_email
        with patch('webhook_handlers.firestore_utils.get_user', return_value={'uid': 'test_user_uid', 'email': 'test@example.com', 'photo_upload_count_current_month': 0}) as _:
            mock_process_image.side_effect = [
                ('http://example.com/image1.jpg', 10.0, 20.0),
                ('http://example.com/image2.png', None, None),
                ('http://example.com/image3.jpeg', 30.0, 40.0)
            ]
            mock_save_content.side_effect = ['content_id_1', 'content_id_2', 'content_id_3']
            mock_create_notification.side_effect = ['notif_id_1', 'notif_id_2', 'notif_id_3']
            mock_parse_location.side_effect = [(25.0, 35.0)]

            request_data = self.default_request_json_data.copy()
            request_data['Subject'] = 'Subject for image2 lat:25.0,lng:35.0'
            request_data['Attachments'] = [
                {'Name': 'image1.jpg', 'Content': self.valid_base64_content, 'ContentType': 'image/jpeg'},
                {'Name': 'image2.png', 'Content': self.valid_base64_content, 'ContentType': 'image/png'},
                {'Name': 'document.pdf', 'Content': self.valid_base64_content, 'ContentType': 'application/pdf'},
                {'Name': 'image3.jpeg', 'Content': self.valid_base64_content, 'ContentType': 'image/jpeg'}
            ]

            response = handle_postmark_webhook_request(
                request_data, self.query_token, self.mock_app_logger, self.mock_db_client,
                self.mock_bucket, self.mock_app_context, self.mock_inbound_url_token_config,
                self.mock_allowed_image_extensions_config, self.mock_max_image_size_config,
                self.mock_app_config
            )
            self.assertEqual(response['status'], 'success')
            self.assertEqual(len(response['contentIds']), 3)

            # Check arguments to save_content_item for each image
            # Call 1: image1.jpg with EXIF GPS
            args_img1, _ = mock_save_content.call_args_list[0]
            self.assertEqual(args_img1[0]['imageUrl'], 'http://example.com/image1.jpg')
            self.assertEqual(args_img1[0]['latitude'], 10.0)
            self.assertEqual(args_img1[0]['longitude'], 20.0)

            # Call 2: image2.png with Subject GPS (since EXIF was None)
            args_img2, _ = mock_save_content.call_args_list[1]
            self.assertEqual(args_img2[0]['imageUrl'], 'http://example.com/image2.png')
            self.assertEqual(args_img2[0]['latitude'], 25.0) # From mock_parse_location
            self.assertEqual(args_img2[0]['longitude'], 35.0) # From mock_parse_location
            mock_parse_location.assert_called_once_with('Subject for image2 lat:25.0,lng:35.0')


            # Call 3: image3.jpeg with EXIF GPS
            args_img3, _ = mock_save_content.call_args_list[2]
            self.assertEqual(args_img3[0]['imageUrl'], 'http://example.com/image3.jpeg')
            self.assertEqual(args_img3[0]['latitude'], 30.0)
            self.assertEqual(args_img3[0]['longitude'], 40.0)


    @patch('webhook_handlers.utils.verify_inbound_token', return_value=True)
    @patch('webhook_handlers.firestore_utils.get_user_by_email')
    @patch('webhook_handlers.image_utils.process_uploaded_image')
    @patch('webhook_handlers.firestore_utils.save_content_item')
    @patch('webhook_handlers.email_utils.create_email_notification_record')
    @patch('webhook_handlers.email_utils.send_pending_notification', return_value=True)
    @patch('webhook_handlers.utils.parse_location_from_subject', return_value=(None, None))
    def test_handle_postmark_webhook_multiple_images_one_fails_processing(
        self, mock_parse_location, mock_send_notification, mock_create_notification,
        mock_save_content, mock_process_image, mock_get_user_by_email, mock_verify_token
    ):
        mock_get_user_by_email.return_value = {'uid': 'test_user_uid', 'email': 'test@example.com'}
        with patch('webhook_handlers.firestore_utils.get_user', return_value={'uid': 'test_user_uid', 'email': 'test@example.com', 'photo_upload_count_current_month': 0}) as _:
            mock_process_image.side_effect = [
                ('http://example.com/image1.jpg', 10.0, 20.0), None,
                ('http://example.com/image3.jpeg', 30.0, 40.0)
            ]
            mock_save_content.side_effect = ['content_id_1', 'content_id_3']
            mock_create_notification.side_effect = ['notif_id_1', 'notif_id_3']
            request_data = self.default_request_json_data.copy()
            request_data['Attachments'] = [
                {'Name': 'image1.jpg', 'Content': self.valid_base64_content, 'ContentType': 'image/jpeg'},
                {'Name': 'image2.png', 'Content': self.valid_base64_content, 'ContentType': 'image/png'},
                {'Name': 'image3.jpeg', 'Content': self.valid_base64_content, 'ContentType': 'image/jpeg'}
            ]
            response = handle_postmark_webhook_request(
                request_data, self.query_token, self.mock_app_logger, self.mock_db_client,
                self.mock_bucket, self.mock_app_context, self.mock_inbound_url_token_config,
                self.mock_allowed_image_extensions_config, self.mock_max_image_size_config,
                self.mock_app_config
            )
            self.assertEqual(response['status'], 'success')
            self.assertEqual(len(response['contentIds']), 2)


    @patch('webhook_handlers.utils.verify_inbound_token', return_value=True)
    @patch('webhook_handlers.firestore_utils.get_user_by_email')
    @patch('webhook_handlers.image_utils.process_uploaded_image')
    @patch('webhook_handlers.firestore_utils.save_content_item')
    def test_handle_postmark_webhook_no_valid_images_non_image_attachments(
        self, mock_save_content, mock_process_image, mock_get_user_by_email, mock_verify_token
    ):
        mock_get_user_by_email.return_value = {'uid': 'test_user_uid', 'email': 'test@example.com'}
        with patch('webhook_handlers.firestore_utils.get_user', return_value={'uid': 'test_user_uid', 'email': 'test@example.com', 'photo_upload_count_current_month': 0}) as _:
            request_data = self.default_request_json_data.copy()
            request_data['Attachments'] = [
                {'Name': 'doc.pdf', 'Content': self.valid_base64_content, 'ContentType': 'application/pdf'},
                {'Name': 'sheet.xlsx', 'Content': self.valid_base64_content, 'ContentType': 'application/vnd.ms-excel'}
            ]
            response = handle_postmark_webhook_request(
                request_data, self.query_token, self.mock_app_logger, self.mock_db_client,
                self.mock_bucket, self.mock_app_context, self.mock_inbound_url_token_config,
                self.mock_allowed_image_extensions_config, self.mock_max_image_size_config,
                self.mock_app_config
            )
            self.assertEqual(response['status'], 'error')
            self.assertEqual(response['message'], 'No valid images found in attachments')
            mock_process_image.assert_not_called() # Added for clarity
            mock_save_content.assert_not_called()

    @patch('webhook_handlers.utils.verify_inbound_token', return_value=True)
    @patch('webhook_handlers.firestore_utils.get_user_by_email')
    @patch('webhook_handlers.image_utils.process_uploaded_image')
    @patch('webhook_handlers.firestore_utils.save_content_item')
    @patch('webhook_handlers.utils.parse_location_from_subject')
    def test_handle_postmark_webhook_one_image_no_gps_anywhere(
        self, mock_parse_location, mock_save_content, mock_process_image,
        mock_get_user_by_email, mock_verify_token
    ):
        mock_get_user_by_email.return_value = {'uid': 'test_user_uid', 'email': 'test@example.com'}
        with patch('webhook_handlers.firestore_utils.get_user', return_value={'uid': 'test_user_uid', 'email': 'test@example.com', 'photo_upload_count_current_month': 0}) as _:
            mock_process_image.return_value = ('http://example.com/image1.jpg', None, None)
            mock_parse_location.return_value = (None, None)
            request_data = self.default_request_json_data.copy()
            request_data['Attachments'] = [
                {'Name': 'image1.jpg', 'Content': self.valid_base64_content, 'ContentType': 'image/jpeg'}
            ]
            request_data['Subject'] = "Image with no location info"
            response = handle_postmark_webhook_request(
                request_data, self.query_token, self.mock_app_logger, self.mock_db_client,
                self.mock_bucket, self.mock_app_context, self.mock_inbound_url_token_config,
                self.mock_allowed_image_extensions_config, self.mock_max_image_size_config,
                self.mock_app_config
            )
            self.assertEqual(response['status'], 'error')
            self.assertEqual(response['message'], 'No valid images found in attachments')
            mock_save_content.assert_not_called()
            # Assert specific log for skipping due to no GPS
            expected_log_msg = (
                f"Could not determine coordinates for post from image 'image1.jpg' "
                f"(email: {request_data['FromFull']['Email']}, subject: '{request_data['Subject']}'). "
                f"Skipping this image."
            )
            self.mock_app_logger.warning.assert_any_call(expected_log_msg)

    # --- Tests for Photo Upload Limit and Count Increment (Original Set) ---

    @patch('webhook_handlers.utils.verify_inbound_token', return_value=True)
    @patch('webhook_handlers.firestore_utils.get_user_by_email')
    @patch('webhook_handlers.firestore_utils.get_user')
    @patch('webhook_handlers.image_utils.process_uploaded_image')
    @patch('webhook_handlers.firestore_utils.save_content_item')
    @patch('webhook_handlers.email_utils.create_email_notification_record')
    @patch('webhook_handlers.email_utils.send_pending_notification', return_value=True)
    @patch('webhook_handlers.utils.parse_location_from_subject', return_value=(10.0, 20.0))
    @patch('webhook_handlers.firestore_utils.firestore.Increment')
    def test_user_under_limit_processes_image_and_increments_count(
        self, mock_increment, mock_parse_location, mock_send_notification, mock_create_notification,
        mock_save_content, mock_process_image, mock_get_user, mock_get_user_by_email, mock_verify_token
    ):
        user_email = 'underlimit@example.com'; user_uid = 'user_under_limit_uid'
        initial_photo_count = 2
        self.mock_app_config['PHOTO_UPLOAD_LIMIT'] = 5
        mock_get_user_by_email.return_value = {'uid': user_uid, 'email': user_email}
        mock_get_user.return_value = {'uid': user_uid, 'email': user_email, 'photo_upload_count_current_month': initial_photo_count}
        mock_process_image.return_value = ('http://example.com/image.jpg', 10.0, 20.0)
        mock_save_content.return_value = 'content_id_1'
        mock_create_notification.return_value = 'notif_id_1'
        mock_increment_instance = MagicMock(); mock_increment.return_value = mock_increment_instance
        mock_user_doc_ref = MagicMock(); self.mock_db_client.collection.return_value.document.return_value = mock_user_doc_ref
        request_data = self.default_request_json_data.copy()
        request_data['FromFull']['Email'] = user_email; request_data['From'] = user_email
        request_data['Attachments'] = [{'Name': 'image1.jpg', 'Content': self.valid_base64_content, 'ContentType': 'image/jpeg'}]
        response = handle_postmark_webhook_request(
            request_data, self.query_token, self.mock_app_logger, self.mock_db_client,
            self.mock_bucket, self.mock_app_context, self.mock_inbound_url_token_config,
            self.mock_allowed_image_extensions_config, self.mock_max_image_size_config, self.mock_app_config)
        self.assertEqual(response['status'], 'success')
        mock_save_content.assert_called_once()
        mock_user_doc_ref.update.assert_called_once_with({'photo_upload_count_current_month': mock_increment_instance})
        mock_increment.assert_called_once_with(1)

    @patch('webhook_handlers.utils.verify_inbound_token', return_value=True)
    @patch('webhook_handlers.firestore_utils.get_user_by_email')
    @patch('webhook_handlers.firestore_utils.get_user')
    @patch('webhook_handlers.image_utils.process_uploaded_image')
    @patch('webhook_handlers.firestore_utils.save_content_item')
    @patch('webhook_handlers.firestore_utils.firestore.Increment')
    def test_user_at_limit_rejects_image_and_does_not_increment( # Renamed to avoid conflict, keeping old one
        self, mock_increment, mock_save_content, mock_process_image, mock_get_user,
        mock_get_user_by_email, mock_verify_token
    ):
        user_email = 'atlimit_original@example.com'; user_uid = 'user_at_limit_original_uid'
        self.mock_app_config['PHOTO_UPLOAD_LIMIT'] = 3
        initial_photo_count = 3
        mock_get_user_by_email.return_value = {'uid': user_uid, 'email': user_email}
        mock_get_user.return_value = {'uid': user_uid, 'email': user_email, 'photo_upload_count_current_month': initial_photo_count}
        mock_user_doc_ref = MagicMock(); self.mock_db_client.collection.return_value.document.return_value = mock_user_doc_ref

        # Configure mocks for successful processing
        mock_process_image.return_value = ('http://example.com/image.jpg', 10.0, 20.0)
        mock_save_content.return_value = 'content_id_for_zero_limit_existing'

        request_data = self.default_request_json_data.copy()
        request_data['FromFull']['Email'] = user_email; request_data['From'] = user_email
        request_data['Attachments'] = [{'Name': 'image1.jpg', 'Content': self.valid_base64_content, 'ContentType': 'image/jpeg'}]
        response = handle_postmark_webhook_request(
            request_data, self.query_token, self.mock_app_logger, self.mock_db_client,
            self.mock_bucket, self.mock_app_context, self.mock_inbound_url_token_config,
            self.mock_allowed_image_extensions_config, self.mock_max_image_size_config, self.mock_app_config)
        self.assertEqual(response['status'], 'partial_success') # Corrected based on handler logic
        self.assertEqual(response['http_status_code'], 200)     # Corrected based on handler logic
        self.assertEqual(len(response['contentIds']), 0)
        self.assertEqual(response['skipped_count'], 1)
        expected_msg = f"0 content item(s) published successfully, 1 image(s) skipped due to upload limit"
        self.assertEqual(response['message'], expected_msg)

        mock_save_content.assert_not_called()
        mock_process_image.assert_not_called() # Corrected: Not called if limit is already met
        mock_user_doc_ref.update.assert_not_called()

        # Check logger warning for the skipped image
        self.mock_app_logger.warning.assert_any_call(
            f"User {user_uid} has reached photo upload limit ({initial_photo_count}/{self.mock_app_config['PHOTO_UPLOAD_LIMIT']}). Skipping image 'image1.jpg'."
        )

    @patch('webhook_handlers.utils.verify_inbound_token', return_value=True)
    @patch('webhook_handlers.firestore_utils.get_user_by_email', return_value=None)
    @patch('webhook_handlers.firestore_utils.create_user')
    @patch('webhook_handlers.firestore_utils.get_user')
    @patch('webhook_handlers.image_utils.process_uploaded_image')
    @patch('webhook_handlers.firestore_utils.save_content_item')
    @patch('webhook_handlers.email_utils.create_email_notification_record')
    @patch('webhook_handlers.email_utils.send_pending_notification', return_value=True)
    @patch('webhook_handlers.utils.parse_location_from_subject', return_value=(10.0, 20.0))
    @patch('webhook_handlers.firestore_utils.firestore.Increment')
    def test_new_user_processes_image_and_increments_count(
        self, mock_increment, mock_parse_location, mock_send_notification, mock_create_notification,
        mock_save_content, mock_process_image, mock_get_user, mock_create_user,
        mock_get_user_by_email, mock_verify_token
    ):
        user_email = 'newuser_original@example.com'; new_user_uid = 'new_user_original_uid'
        self.mock_app_config['PHOTO_UPLOAD_LIMIT'] = 5
        mock_create_user.return_value = {'uid': new_user_uid, 'email': user_email, 'photo_upload_count_current_month': 0}
        mock_process_image.return_value = ('http://example.com/image.jpg', 10.0, 20.0)
        mock_save_content.return_value = 'content_id_new_user'
        mock_increment_instance = MagicMock(); mock_increment.return_value = mock_increment_instance
        mock_user_doc_ref = MagicMock(); self.mock_db_client.collection('users').document(new_user_uid).return_value = mock_user_doc_ref

        # Simulate the document reference for user creation ID generation
        mock_new_user_id_gen_ref = MagicMock()
        mock_new_user_id_gen_ref.id = new_user_uid
        self.mock_db_client.collection('users').document.return_value = mock_new_user_id_gen_ref # For ID gen

        request_data = self.default_request_json_data.copy()
        request_data['FromFull']['Email'] = user_email; request_data['From'] = user_email
        request_data['Attachments'] = [{'Name': 'image1.jpg', 'Content': self.valid_base64_content, 'ContentType': 'image/jpeg'}]
        response = handle_postmark_webhook_request(
            request_data, self.query_token, self.mock_app_logger, self.mock_db_client,
            self.mock_bucket, self.mock_app_context, self.mock_inbound_url_token_config,
            self.mock_allowed_image_extensions_config, self.mock_max_image_size_config, self.mock_app_config)
        self.assertEqual(response['status'], 'success')
        mock_create_user.assert_called_once()
        mock_save_content.assert_called_once()
        # Check that the update call was made on the correct document reference for increment
        self.mock_db_client.collection('users').document(new_user_uid).update.assert_called_once_with({'photo_upload_count_current_month': mock_increment_instance})
        mock_increment.assert_called_once_with(1)

    @patch('webhook_handlers.utils.verify_inbound_token', return_value=True)
    @patch('webhook_handlers.firestore_utils.get_user_by_email')
    @patch('webhook_handlers.firestore_utils.get_user')
    @patch('webhook_handlers.image_utils.process_uploaded_image')
    @patch('webhook_handlers.firestore_utils.save_content_item')
    @patch('webhook_handlers.firestore_utils.firestore.Increment')
    def test_no_image_attachments_no_increment(
        self, mock_increment, mock_save_content, mock_process_image,
        mock_get_user, mock_get_user_by_email, mock_verify_token
    ):
        user_email = 'noimage@example.com'; user_uid = 'user_no_image_uid'
        self.mock_app_config['PHOTO_UPLOAD_LIMIT'] = 5
        mock_get_user_by_email.return_value = {'uid': user_uid, 'email': user_email}
        mock_get_user.return_value = {'uid': user_uid, 'email': user_email, 'photo_upload_count_current_month': 1}
        mock_user_doc_ref = MagicMock(); self.mock_db_client.collection.return_value.document.return_value = mock_user_doc_ref
        request_data = self.default_request_json_data.copy()
        request_data['FromFull']['Email'] = user_email; request_data['From'] = user_email
        request_data['Attachments'] = [{'Name': 'document.pdf', 'Content': 'pdf_content_base64', 'ContentType': 'application/pdf'}]
        response = handle_postmark_webhook_request(
            request_data, self.query_token, self.mock_app_logger, self.mock_db_client,
            self.mock_bucket, self.mock_app_context, self.mock_inbound_url_token_config,
            self.mock_allowed_image_extensions_config, self.mock_max_image_size_config, self.mock_app_config)
        self.assertEqual(response['status'], 'error')
        mock_process_image.assert_not_called() # Added for clarity
        mock_save_content.assert_not_called() # Should also be here, as no processing means no saving
        mock_user_doc_ref.update.assert_not_called()

    @patch('webhook_handlers.utils.verify_inbound_token', return_value=True)
    @patch('webhook_handlers.firestore_utils.get_user_by_email')
    @patch('webhook_handlers.firestore_utils.get_user')
    @patch('webhook_handlers.image_utils.process_uploaded_image', return_value=(None, None, None))
    @patch('webhook_handlers.firestore_utils.save_content_item')
    @patch('webhook_handlers.firestore_utils.firestore.Increment')
    def test_image_processing_fails_no_increment(
        self, mock_increment, mock_save_content, mock_process_image_fails,
        mock_get_user, mock_get_user_by_email, mock_verify_token
    ):
        user_email = 'imgfail@example.com'; user_uid = 'user_img_fail_uid'
        self.mock_app_config['PHOTO_UPLOAD_LIMIT'] = 5
        mock_get_user_by_email.return_value = {'uid': user_uid, 'email': user_email}
        mock_get_user.return_value = {'uid': user_uid, 'email': user_email, 'photo_upload_count_current_month': 1}
        mock_user_doc_ref = MagicMock(); self.mock_db_client.collection.return_value.document.return_value = mock_user_doc_ref
        request_data = self.default_request_json_data.copy()
        request_data['FromFull']['Email'] = user_email; request_data['From'] = user_email
        request_data['Attachments'] = [{'Name': 'image1.jpg', 'Content': self.valid_base64_content, 'ContentType': 'image/jpeg'}]
        response = handle_postmark_webhook_request(
            request_data, self.query_token, self.mock_app_logger, self.mock_db_client,
            self.mock_bucket, self.mock_app_context, self.mock_inbound_url_token_config,
            self.mock_allowed_image_extensions_config, self.mock_max_image_size_config, self.mock_app_config)
        self.assertEqual(response['status'], 'error')
        mock_user_doc_ref.update.assert_not_called()

    # --- New Specific Edge Case Tests ---

    @patch('webhook_handlers.utils.verify_inbound_token', return_value=True)
    @patch('webhook_handlers.firestore_utils.get_user_by_email')
    @patch('webhook_handlers.firestore_utils.get_user')
    @patch('webhook_handlers.image_utils.process_uploaded_image')
    @patch('webhook_handlers.firestore_utils.save_content_item')
    @patch('webhook_handlers.email_utils.create_email_notification_record')
    @patch('webhook_handlers.email_utils.send_pending_notification', return_value=True)
    @patch('webhook_handlers.utils.parse_location_from_subject', return_value=(10.0, 20.0))
    @patch('webhook_handlers.firestore_utils.firestore.Increment')
    def test_user_under_limit_multiple_attachments_processed_even_if_exceeds_limit_within_email(
        self, mock_increment, mock_parse_location, mock_send_notification, mock_create_notification,
        mock_save_content, mock_process_image, mock_get_user, mock_get_user_by_email, mock_verify_token
    ):
        user_email = 'multi_exceed@example.com'; user_uid = 'user_multi_exceed_uid'
        limit = 5
        self.mock_app_config['PHOTO_UPLOAD_LIMIT'] = limit
        initial_photo_count = limit - 1 # e.g., 4

        mock_get_user_by_email.return_value = {'uid': user_uid, 'email': user_email}
        mock_get_user.return_value = {'uid': user_uid, 'email': user_email, 'photo_upload_count_current_month': initial_photo_count}

        mock_process_image.side_effect = [('http://example.com/imageA.jpg', 10.0, 20.0), ('http://example.com/imageB.jpg', 10.0, 20.0)]
        mock_save_content.side_effect = ['content_id_A', 'content_id_B']
        mock_create_notification.side_effect = ['notif_A', 'notif_B']
        mock_increment_instance = MagicMock(); mock_increment.return_value = mock_increment_instance
        mock_user_doc_ref = MagicMock(); self.mock_db_client.collection.return_value.document.return_value = mock_user_doc_ref

        request_data = self.default_request_json_data.copy()
        request_data['FromFull']['Email'] = user_email; request_data['From'] = user_email
        request_data['Attachments'] = [
            {'Name': 'imageA.jpg', 'Content': self.valid_base64_content, 'ContentType': 'image/jpeg'},
            {'Name': 'imageB.jpg', 'Content': self.valid_base64_content, 'ContentType': 'image/jpeg'}
        ]
        response = handle_postmark_webhook_request(
            request_data, self.query_token, self.mock_app_logger, self.mock_db_client,
            self.mock_bucket, self.mock_app_context, self.mock_inbound_url_token_config,
            self.mock_allowed_image_extensions_config, self.mock_max_image_size_config, self.mock_app_config)

        # With per-image check, user starts at 4/5. Processes 1st image (count becomes 5/5). 2nd image is skipped.
        self.assertEqual(response['status'], 'success') # Handler returns 'success' if any image is processed
        self.assertEqual(len(response['contentIds']), 1)
        self.assertEqual(response['contentIds'][0], 'content_id_A')
        self.assertEqual(response['skipped_count'], 1)
        self.assertIn("1 image(s) skipped due to upload limit", response['message'])

        self.assertEqual(mock_save_content.call_count, 1)
        self.assertEqual(mock_process_image.call_count, 1) # Corrected: Only called for the first image

        # Check that mock_process_image was called with correct arguments for both images
        # (assuming image_bytes and other args are consistent with how process_uploaded_image is called)
        # This part might need more detailed argument checking if necessary, but call_count is primary here.

        mock_user_doc_ref.update.assert_called_once() # Incremented only for the first image
        mock_increment.assert_called_once_with(1)

        # Check logger warning for the skipped image
        self.mock_app_logger.warning.assert_any_call(
            f"User {user_uid} has reached photo upload limit ({limit}/{limit}). Skipping image 'imageB.jpg'."
        )

    @patch('webhook_handlers.utils.verify_inbound_token', return_value=True)
    @patch('webhook_handlers.firestore_utils.get_user_by_email')
    @patch('webhook_handlers.firestore_utils.get_user')
    @patch('webhook_handlers.image_utils.process_uploaded_image')
    @patch('webhook_handlers.firestore_utils.save_content_item')
    @patch('webhook_handlers.firestore_utils.firestore.Increment')
    def test_user_exactly_at_limit_rejects_all_attachments(
        self, mock_increment, mock_save_content, mock_process_image, mock_get_user,
        mock_get_user_by_email, mock_verify_token
    ):
        user_email = 'exactlimit@example.com'; user_uid = 'user_exactlimit_uid'
        limit = 5
        self.mock_app_config['PHOTO_UPLOAD_LIMIT'] = limit
        initial_photo_count = limit

        mock_get_user_by_email.return_value = {'uid': user_uid, 'email': user_email}
        mock_get_user.return_value = {'uid': user_uid, 'email': user_email, 'photo_upload_count_current_month': initial_photo_count}
        mock_user_doc_ref = MagicMock(); self.mock_db_client.collection.return_value.document.return_value = mock_user_doc_ref
        request_data = self.default_request_json_data.copy()
        request_data['FromFull']['Email'] = user_email; request_data['From'] = user_email
        request_data['Attachments'] = [
            {'Name': 'image1.jpg', 'Content': self.valid_base64_content, 'ContentType': 'image/jpeg'},
            {'Name': 'image2.jpg', 'Content': self.valid_base64_content, 'ContentType': 'image/jpeg'}
        ]
        response = handle_postmark_webhook_request(
            request_data, self.query_token, self.mock_app_logger, self.mock_db_client,
            self.mock_bucket, self.mock_app_context, self.mock_inbound_url_token_config,
            self.mock_allowed_image_extensions_config, self.mock_max_image_size_config, self.mock_app_config)

        self.assertEqual(response['status'], 'partial_success') # Corrected
        self.assertEqual(response['http_status_code'], 200)     # Corrected
        self.assertEqual(len(response['contentIds']), 0)
        self.assertEqual(response['skipped_count'], 2) # Both images skipped
        expected_msg = f"0 content item(s) published successfully, 2 image(s) skipped due to upload limit"
        self.assertEqual(response['message'], expected_msg)

        mock_save_content.assert_not_called()
        mock_process_image.assert_not_called() # Corrected: Not called if limit is already met for both
        mock_user_doc_ref.update.assert_not_called()

        # Check logger warnings for skipped images
        self.mock_app_logger.warning.assert_any_call(
            f"User {user_uid} has reached photo upload limit ({limit}/{limit}). Skipping image 'image1.jpg'."
        )
        self.mock_app_logger.warning.assert_any_call(
            f"User {user_uid} has reached photo upload limit ({limit}/{limit}). Skipping image 'image2.jpg'."
        )

    @patch('webhook_handlers.utils.verify_inbound_token', return_value=True)
    @patch('webhook_handlers.firestore_utils.get_user_by_email', return_value=None) # New user
    @patch('webhook_handlers.firestore_utils.create_user')
    @patch('webhook_handlers.firestore_utils.get_user', return_value=None) # Mock get_user to return None for new user post-creation attempt
    @patch('webhook_handlers.image_utils.process_uploaded_image')
    @patch('webhook_handlers.firestore_utils.save_content_item')
    @patch('webhook_handlers.firestore_utils.firestore.Increment')
    def test_photo_upload_limit_is_zero_blocks_all_uploads_new_user(
        self, mock_increment, mock_save_content, mock_process_image, mock_get_user,
        mock_create_user, mock_get_user_by_email, mock_verify_token
    ):
        user_email = 'newlimitzerouser@example.com'; new_user_uid = 'new_user_limitzero_uid'
        self.mock_app_config['PHOTO_UPLOAD_LIMIT'] = 0

        # Simulate create_user being called and returning a new user ID
        mock_create_user.return_value = {'uid': new_user_uid, 'email': user_email, 'photo_upload_count_current_month': 0}
        # Simulate ID generation for create_user's internal doc ref
        mock_new_user_id_gen_ref = MagicMock(); mock_new_user_id_gen_ref.id = new_user_uid
        # Ensure that when collection('users').document() is called without a specific UID (for ID generation),
        # it returns our mock_new_user_id_gen_ref. This might conflict if not handled carefully with side_effect below.

        mock_user_doc_ref_for_update = MagicMock()

        # Configure mocks for successful processing
        mock_process_image.return_value = ('http://example.com/new_user_image.jpg', 10.0, 20.0)
        mock_save_content.return_value = 'content_id_for_zero_limit_new_user'

        request_data = self.default_request_json_data.copy()
        request_data['FromFull']['Email'] = user_email; request_data['From'] = user_email
        request_data['Attachments'] = [{'Name': 'image1.jpg', 'Content': self.valid_base64_content, 'ContentType': 'image/jpeg'}]

        # Action
        # Need to ensure that the document mock for user update is different if create_user is called
        # and then later an update attempt is made on that user_id.
        def db_collection_side_effect(collection_name):
            if collection_name == 'users':
                doc_mock = MagicMock()
                # For ID generation in create_user
                doc_mock.id = new_user_uid
                # For the update attempt on the new user
                doc_mock.update = mock_user_doc_ref_for_update.update
                return MagicMock(document=MagicMock(return_value=doc_mock))
            return MagicMock()
        self.mock_db_client.collection.side_effect = db_collection_side_effect

        response = handle_postmark_webhook_request(
            request_data, self.query_token, self.mock_app_logger, self.mock_db_client,
            self.mock_bucket, self.mock_app_context, self.mock_inbound_url_token_config,
            self.mock_allowed_image_extensions_config, self.mock_max_image_size_config, self.mock_app_config)

        # According to current handler logic: if photo_limit is 0, the condition
        # `if user_id_for_content and photo_limit > 0:` is false, so the
        # per-image limit check block is skipped. Images will be processed for a new user too.
        self.assertEqual(response['status'], 'success')
        self.assertEqual(response['http_status_code'], 200)
        self.assertEqual(len(response['contentIds']), 1)
        self.assertEqual(response['skipped_count'], 0)

        mock_create_user.assert_called_once()
        mock_process_image.assert_called_once()
        mock_save_content.assert_called_once()

        # Check that new user's photo count was incremented
        # The mock_user_doc_ref_for_update is set up via the db_collection_side_effect
        mock_user_doc_ref_for_update.update.assert_called_once_with(
            {'photo_upload_count_current_month': mock_increment.return_value}
        )
        mock_increment.assert_called_once_with(1)

if __name__ == '__main__':
    unittest.main()
