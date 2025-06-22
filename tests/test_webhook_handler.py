import pytest
import base64
import io
from unittest.mock import Mock, patch, MagicMock
from PIL import Image
from webhook_handler import handle_postmark_webhook_request


class TestWebhookHandler:
    """Тесты для функции handle_postmark_webhook_request"""
    
    def setup_method(self):
        """Настройка для каждого теста"""
        # Создаем тестовое изображение
        self.img = Image.new('RGB', (10, 10), color='red')
        self.img_bytes = io.BytesIO()
        self.img.save(self.img_bytes, format='JPEG')
        self.image_data = self.img_bytes.getvalue()
        self.image_base64 = base64.b64encode(self.image_data).decode('utf-8')
        
        # Базовые моки
        self.mock_logger = Mock()
        self.mock_db = Mock()
        self.mock_bucket = Mock()
        self.mock_app_context = Mock()
        
        # Конфигурация
        self.inbound_token = "test_token"
        self.allowed_extensions = {'jpg', 'jpeg', 'png', 'gif'}
        self.max_size = 1024 * 1024  # 1MB
        self.app_config = {
            'PHOTO_UPLOAD_LIMIT': 10
        }
    
    def test_invalid_token(self):
        """Тест с невалидным токеном"""
        request_data = {"From": "test@example.com"}
        query_token = "wrong_token"
        
        result = handle_postmark_webhook_request(
            request_json_data=request_data,
            query_token=query_token,
            app_logger=self.mock_logger,
            db_client=self.mock_db,
            bucket=self.mock_bucket,
            app_context=self.mock_app_context,
            inbound_url_token_config=self.inbound_token,
            allowed_image_extensions_config=self.allowed_extensions,
            max_image_size_config=self.max_size,
            app_config=self.app_config
        )
        
        assert result['status'] == 'error'
        assert result['message'] == 'Invalid token'
        assert result['http_status_code'] == 401
    
    def test_missing_email(self):
        """Тест с отсутствующим email"""
        request_data = {"Subject": "Test"}
        query_token = self.inbound_token
        
        result = handle_postmark_webhook_request(
            request_json_data=request_data,
            query_token=query_token,
            app_logger=self.mock_logger,
            db_client=self.mock_db,
            bucket=self.mock_bucket,
            app_context=self.mock_app_context,
            inbound_url_token_config=self.inbound_token,
            allowed_image_extensions_config=self.allowed_extensions,
            max_image_size_config=self.max_size,
            app_config=self.app_config
        )
        
        assert result['status'] == 'error'
        assert result['message'] == 'Sender email not found'
        assert result['http_status_code'] == 400
    
    @patch('webhook_handler.firestore_utils.get_user_by_email')
    @patch('webhook_handler.firestore_utils.create_user')
    @patch('webhook_handler.image_utils.process_uploaded_image')
    @patch('webhook_handler.firestore_utils.save_content_item')
    @patch('webhook_handler.email_utils.create_email_notification_record')
    @patch('webhook_handler.email_utils.send_pending_notification')
    def test_successful_processing_new_user(
        self, mock_send_notification, mock_create_notification, 
        mock_save_content, mock_process_image, mock_create_user, mock_get_user
    ):
        """Тест успешной обработки для нового пользователя"""
        # Подготовка данных
        request_data = {
            "FromFull": {"Email": "new@example.com"},
            "Subject": "Test Post lat:55.7558,lng:37.6176",
            "TextBody": "Test content",
            "Attachments": [{
                "Name": "test.jpg",
                "ContentType": "image/jpeg",
                "Content": self.image_base64
            }]
        }
        
        # Мокаем получение пользователя (не найден)
        mock_get_user.return_value = None
        
        # Мокаем создание пользователя
        mock_create_user.return_value = {
            "uid": "new_uid",
            "email": "new@example.com",
            "photo_upload_count_current_month": 0
        }
        
        # Мокаем обработку изображения
        mock_process_image.return_value = (
            "http://example.com/image.jpg",
            55.7558,  # lat
            37.6176   # lng
        )
        
        # Мокаем сохранение контента
        mock_save_content.return_value = "content_id"
        
        # Мокаем создание уведомления
        mock_create_notification.return_value = "notification_id"
        mock_send_notification.return_value = True
        
        # Выполнение
        result = handle_postmark_webhook_request(
            request_json_data=request_data,
            query_token=self.inbound_token,
            app_logger=self.mock_logger,
            db_client=self.mock_db,
            bucket=self.mock_bucket,
            app_context=self.mock_app_context,
            inbound_url_token_config=self.inbound_token,
            allowed_image_extensions_config=self.allowed_extensions,
            max_image_size_config=self.max_size,
            app_config=self.app_config
        )
        
        # Проверка
        assert result['status'] == 'success'
        assert 'content_id' in result['contentIds']
        assert result['skipped_count'] == 0
        assert result['http_status_code'] == 200
        
        # Проверяем вызовы
        mock_get_user.assert_called_once_with("new@example.com", self.mock_logger)
        mock_create_user.assert_called_once()
        mock_process_image.assert_called_once()
        mock_save_content.assert_called_once()
        mock_create_notification.assert_called_once()
        mock_send_notification.assert_called_once()
    
    @patch('webhook_handler.firestore_utils.get_user_by_email')
    @patch('webhook_handler.firestore_utils.get_user')
    @patch('webhook_handler.image_utils.process_uploaded_image')
    @patch('webhook_handler.firestore_utils.save_content_item')
    @patch('webhook_handler.firestore_utils.increment_user_photo_count')
    @patch('webhook_handler.email_utils.create_email_notification_record')
    @patch('webhook_handler.email_utils.send_pending_notification')
    def test_successful_processing_existing_user(
        self, mock_send_notification, mock_create_notification, 
        mock_increment_count, mock_save_content, mock_process_image, 
        mock_get_user, mock_get_user_by_email
    ):
        """Тест успешной обработки для существующего пользователя"""
        # Подготовка данных
        request_data = {
            "FromFull": {"Email": "existing@example.com"},
            "Subject": "Test Post lat:55.7558,lng:37.6176",
            "TextBody": "Test content",
            "Attachments": [{
                "Name": "test.jpg",
                "ContentType": "image/jpeg",
                "Content": self.image_base64
            }]
        }
        
        # Мокаем получение пользователя (найден)
        mock_get_user_by_email.return_value = {
            "uid": "existing_uid",
            "email": "existing@example.com"
        }
        
        # Мокаем получение полных данных пользователя
        mock_get_user.return_value = {
            "uid": "existing_uid",
            "email": "existing@example.com",
            "photo_upload_count_current_month": 5
        }
        
        # Мокаем обработку изображения
        mock_process_image.return_value = (
            "http://example.com/image.jpg",
            55.7558,  # lat
            37.6176   # lng
        )
        
        # Мокаем сохранение контента
        mock_save_content.return_value = "content_id"
        
        # Мокаем инкремент счетчика
        mock_increment_count.return_value = True
        
        # Мокаем создание уведомления
        mock_create_notification.return_value = "notification_id"
        mock_send_notification.return_value = True
        
        # Выполнение
        result = handle_postmark_webhook_request(
            request_json_data=request_data,
            query_token=self.inbound_token,
            app_logger=self.mock_logger,
            db_client=self.mock_db,
            bucket=self.mock_bucket,
            app_context=self.mock_app_context,
            inbound_url_token_config=self.inbound_token,
            allowed_image_extensions_config=self.allowed_extensions,
            max_image_size_config=self.max_size,
            app_config=self.app_config
        )
        
        # Проверка
        assert result['status'] == 'success'
        assert 'content_id' in result['contentIds']
        assert result['skipped_count'] == 0
        assert result['http_status_code'] == 200
        
        # Проверяем вызовы
        mock_get_user_by_email.assert_called_once_with("existing@example.com", self.mock_logger)
        mock_get_user.assert_called_once_with("existing_uid", self.mock_logger)
        mock_increment_count.assert_called_once_with("existing_uid", self.mock_logger)
    
    @patch('webhook_handler.firestore_utils.get_user_by_email')
    @patch('webhook_handler.firestore_utils.create_user')
    def test_user_creation_failure(self, mock_create_user, mock_get_user):
        """Тест неудачного создания пользователя"""
        # Подготовка данных
        request_data = {
            "FromFull": {"Email": "new@example.com"},
            "Subject": "Test Post lat:55.7558,lng:37.6176",
            "TextBody": "Test content",
            "Attachments": [{
                "Name": "test.jpg",
                "ContentType": "image/jpeg",
                "Content": self.image_base64
            }]
        }
        
        # Мокаем получение пользователя (не найден)
        mock_get_user.return_value = None
        
        # Мокаем неудачное создание пользователя
        mock_create_user.return_value = None
        
        # Мокаем обработку изображения
        with patch('webhook_handler.image_utils.process_uploaded_image') as mock_process_image:
            mock_process_image.return_value = (
                "http://example.com/image.jpg",
                55.7558,  # lat
                37.6176   # lng
            )
            
            # Мокаем сохранение контента
            with patch('webhook_handler.firestore_utils.save_content_item') as mock_save_content:
                mock_save_content.return_value = "content_id"
                
                # Выполнение
                result = handle_postmark_webhook_request(
                    request_json_data=request_data,
                    query_token=self.inbound_token,
                    app_logger=self.mock_logger,
                    db_client=self.mock_db,
                    bucket=self.mock_bucket,
                    app_context=self.mock_app_context,
                    inbound_url_token_config=self.inbound_token,
                    allowed_image_extensions_config=self.allowed_extensions,
                    max_image_size_config=self.max_size,
                    app_config=self.app_config
                )
                
                # Проверка - контент должен быть сохранен без userId
                assert result['status'] == 'success'
                assert 'content_id' in result['contentIds']
    
    @patch('webhook_handler.firestore_utils.get_user_by_email')
    @patch('webhook_handler.firestore_utils.create_user')
    def test_photo_limit_reached(self, mock_create_user, mock_get_user):
        """Тест достижения лимита фотографий"""
        # Подготовка данных
        request_data = {
            "FromFull": {"Email": "limited@example.com"},
            "Subject": "Test Post lat:55.7558,lng:37.6176",
            "TextBody": "Test content",
            "Attachments": [{
                "Name": "test.jpg",
                "ContentType": "image/jpeg",
                "Content": self.image_base64
            }]
        }
        
        # Мокаем получение пользователя (не найден)
        mock_get_user.return_value = None
        
        # Мокаем создание пользователя
        mock_create_user.return_value = {
            "uid": "limited_uid",
            "email": "limited@example.com",
            "photo_upload_count_current_month": 10  # Достигнут лимит
        }
        
        # Устанавливаем лимит в 10
        app_config_with_limit = {'PHOTO_UPLOAD_LIMIT': 10}
        
        # Выполнение
        result = handle_postmark_webhook_request(
            request_json_data=request_data,
            query_token=self.inbound_token,
            app_logger=self.mock_logger,
            db_client=self.mock_db,
            bucket=self.mock_bucket,
            app_context=self.mock_app_context,
            inbound_url_token_config=self.inbound_token,
            allowed_image_extensions_config=self.allowed_extensions,
            max_image_size_config=self.max_size,
            app_config=app_config_with_limit
        )
        
        # Проверка
        assert result['status'] == 'error'
        assert result['message'] == 'No valid images found in attachments'
        assert result['http_status_code'] == 200
    
    @patch('webhook_handler.firestore_utils.get_user_by_email')
    @patch('webhook_handler.firestore_utils.create_user')
    @patch('webhook_handler.image_utils.process_uploaded_image')
    def test_no_valid_images(self, mock_process_image, mock_create_user, mock_get_user):
        """Тест отсутствия валидных изображений"""
        # Подготовка данных
        request_data = {
            "FromFull": {"Email": "test@example.com"},
            "Subject": "Test Post",
            "TextBody": "Test content",
            "Attachments": [{
                "Name": "test.txt",
                "ContentType": "text/plain",
                "Content": "not_an_image"
            }]
        }
        
        # Мокаем получение пользователя (не найден)
        mock_get_user.return_value = None
        
        # Мокаем создание пользователя
        mock_create_user.return_value = {
            "uid": "test_uid",
            "email": "test@example.com",
            "photo_upload_count_current_month": 0
        }
        
        # Выполнение
        result = handle_postmark_webhook_request(
            request_json_data=request_data,
            query_token=self.inbound_token,
            app_logger=self.mock_logger,
            db_client=self.mock_db,
            bucket=self.mock_bucket,
            app_context=self.mock_app_context,
            inbound_url_token_config=self.inbound_token,
            allowed_image_extensions_config=self.allowed_extensions,
            max_image_size_config=self.max_size,
            app_config=self.app_config
        )
        
        # Проверка
        assert result['status'] == 'error'
        assert result['message'] == 'No valid images found in attachments'
        assert result['http_status_code'] == 200
    
    @patch('webhook_handler.firestore_utils.get_user_by_email')
    @patch('webhook_handler.firestore_utils.create_user')
    @patch('webhook_handler.image_utils.process_uploaded_image')
    def test_no_coordinates_found(self, mock_process_image, mock_create_user, mock_get_user):
        """Тест отсутствия координат"""
        # Подготовка данных
        request_data = {
            "FromFull": {"Email": "test@example.com"},
            "Subject": "Test Post without coordinates",
            "TextBody": "Test content",
            "Attachments": [{
                "Name": "test.jpg",
                "ContentType": "image/jpeg",
                "Content": self.image_base64
            }]
        }
        
        # Мокаем получение пользователя (не найден)
        mock_get_user.return_value = None
        
        # Мокаем создание пользователя
        mock_create_user.return_value = {
            "uid": "test_uid",
            "email": "test@example.com",
            "photo_upload_count_current_month": 0
        }
        
        # Мокаем обработку изображения (без GPS данных)
        mock_process_image.return_value = (
            "http://example.com/image.jpg",
            None,  # lat
            None   # lng
        )
        
        # Выполнение
        result = handle_postmark_webhook_request(
            request_json_data=request_data,
            query_token=self.inbound_token,
            app_logger=self.mock_logger,
            db_client=self.mock_db,
            bucket=self.mock_bucket,
            app_context=self.mock_app_context,
            inbound_url_token_config=self.inbound_token,
            allowed_image_extensions_config=self.allowed_extensions,
            max_image_size_config=self.max_size,
            app_config=self.app_config
        )
        
        # Проверка
        assert result['status'] == 'error'
        assert result['message'] == 'No valid images found in attachments'
        assert result['http_status_code'] == 200
    
    @patch('webhook_handler.firestore_utils.get_user_by_email')
    @patch('webhook_handler.firestore_utils.create_user')
    @patch('webhook_handler.image_utils.process_uploaded_image')
    @patch('webhook_handler.firestore_utils.save_content_item')
    def test_multiple_images_partial_success(
        self, mock_save_content, mock_process_image, mock_create_user, mock_get_user
    ):
        """Тест частичного успеха при обработке множественных изображений"""
        # Подготовка данных с двумя изображениями
        request_data = {
            "FromFull": {"Email": "test@example.com"},
            "Subject": "Test Post lat:55.7558,lng:37.6176",
            "TextBody": "Test content",
            "Attachments": [
                {
                    "Name": "test1.jpg",
                    "ContentType": "image/jpeg",
                    "Content": self.image_base64
                },
                {
                    "Name": "test2.jpg",
                    "ContentType": "image/jpeg",
                    "Content": self.image_base64
                }
            ]
        }
        
        # Мокаем получение пользователя (не найден)
        mock_get_user.return_value = None
        
        # Мокаем создание пользователя
        mock_create_user.return_value = {
            "uid": "test_uid",
            "email": "test@example.com",
            "photo_upload_count_current_month": 0
        }
        
        # Мокаем обработку изображений (первое успешно, второе неудачно)
        mock_process_image.side_effect = [
            ("http://example.com/image1.jpg", 55.7558, 37.6176),  # Первое изображение
            (None, None, None)  # Второе изображение не удалось обработать
        ]
        
        # Мокаем сохранение контента
        mock_save_content.return_value = "content_id_1"
        
        # Выполнение
        result = handle_postmark_webhook_request(
            request_json_data=request_data,
            query_token=self.inbound_token,
            app_logger=self.mock_logger,
            db_client=self.mock_db,
            bucket=self.mock_bucket,
            app_context=self.mock_app_context,
            inbound_url_token_config=self.inbound_token,
            allowed_image_extensions_config=self.allowed_extensions,
            max_image_size_config=self.max_size,
            app_config=self.app_config
        )
        
        # Проверка
        assert result['status'] == 'success'  # Одно изображение обработано успешно
        assert len(result['contentIds']) == 1
        assert 'content_id_1' in result['contentIds']
        assert result['skipped_count'] == 0
        assert result['http_status_code'] == 200 