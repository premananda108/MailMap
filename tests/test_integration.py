import pytest
import os
os.environ['TESTING'] = 'true'  # Устанавливаем переменную окружения TESTING перед импортом app
import base64
import io
import json
from unittest.mock import Mock, patch, MagicMock
from PIL import Image
from flask import Flask
from app import app


class TestWebhookIntegration:
    """Интеграционные тесты для вебхуков"""
    
    def setup_method(self):
        """Настройка для каждого теста"""
        self.app = app.test_client()
        self.app.testing = True
        
        # Создаем тестовое изображение
        self.img = Image.new('RGB', (10, 10), color='red')
        self.img_bytes = io.BytesIO()
        self.img.save(self.img_bytes, format='JPEG')
        self.image_data = self.img_bytes.getvalue()
        self.image_base64 = base64.b64encode(self.image_data).decode('utf-8')
    
    @patch('app.webhook_handler.handle_postmark_webhook_request')
    def test_webhook_endpoint_success(self, mock_handler):
        """Тест успешного вызова вебхука"""
        # Подготовка данных
        webhook_data = {
            "FromFull": {"Email": "test@example.com"},
            "Subject": "Test Post lat:55.7558,lng:37.6176",
            "TextBody": "Test content",
            "Attachments": [{
                "Name": "test.jpg",
                "ContentType": "image/jpeg",
                "Content": self.image_base64
            }]
        }
        
        # Мокаем обработчик
        mock_handler.return_value = {
            'status': 'success',
            'contentIds': ['content_id_1'],
            'message': '1 content item(s) published successfully',
            'skipped_count': 0,
            'http_status_code': 200
        }
        
        # Выполнение запроса
        response = self.app.post(
            '/webhook/postmark?token=test_token',
            data=json.dumps(webhook_data),
            content_type='application/json'
        )
        
        # Проверка
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'success'
        assert 'content_id_1' in data['contentIds']
        assert data['skipped_count'] == 0
        
        # Проверяем вызов обработчика
        mock_handler.assert_called_once()
    
    @patch('app.webhook_handler.handle_postmark_webhook_request')
    def test_webhook_endpoint_error(self, mock_handler):
        """Тест ошибки в вебхуке"""
        # Подготовка данных
        webhook_data = {
            "FromFull": {"Email": "test@example.com"},
            "Subject": "Test Post",
            "TextBody": "Test content",
            "Attachments": []
        }
        
        # Мокаем обработчик с ошибкой
        mock_handler.return_value = {
            'status': 'error',
            'message': 'No valid images found in attachments',
            'http_status_code': 200
        }
        
        # Выполнение запроса
        response = self.app.post(
            '/webhook/postmark?token=test_token',
            data=json.dumps(webhook_data),
            content_type='application/json'
        )
        
        # Проверка
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'error'
        assert 'No valid images found' in data['message']
    
    def test_webhook_endpoint_invalid_json(self):
        """Тест невалидного JSON в вебхуке"""
        # Выполнение запроса с невалидным JSON
        response = self.app.post(
            '/webhook/postmark?token=test_token',
            data='invalid json',
            content_type='application/json'
        )
        
        # Проверка
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'error'
        assert 'Error parsing request data' in data['message']
    
    def test_webhook_endpoint_no_data(self):
        """Тест отсутствия данных в вебхуке"""
        # Выполнение запроса без данных
        response = self.app.post(
            '/webhook/postmark?token=test_token',
            data='',
            content_type='application/json'
        )
        
        # Проверка
        assert response.status_code == 200
        data = json.loads(response.data)
        assert data['status'] == 'error'
        assert 'No JSON data received' in data['message']


class TestAppConfiguration:
    """Тесты конфигурации приложения"""
    
    def test_app_initialization(self):
        """Тест инициализации приложения"""
        assert app is not None
        assert app.name == 'app'
        assert app.static_folder == 'static'
    
    def test_app_logging_setup(self):
        """Тест настройки логирования"""
        assert app.logger is not None
        assert len(app.logger.handlers) > 0
    
    @patch.dict('os.environ', {
        'INBOUND_URL_TOKEN': 'test_token',
        'FIREBASE_STORAGE_BUCKET': 'test-bucket.appspot.com',
        'GOOGLE_MAPS_API_KEY': 'test_api_key',
        'FLASK_SECRET_KEY': 'test_secret',
        'PHOTO_UPLOAD_LIMIT': '5'
    })
    def test_environment_configuration(self):
        """Тест конфигурации из переменных окружения"""
        # Перезагружаем конфигурацию
        import utils
        config = utils.get_app_config()
        
        assert config['INBOUND_URL_TOKEN'] == 'test_token'
        assert config['FIREBASE_STORAGE_BUCKET'] == 'test-bucket.appspot.com'
        assert config['GOOGLE_MAPS_API_KEY'] == 'test_api_key'
        assert config['FLASK_SECRET_KEY'] == 'test_secret'
        assert config['PHOTO_UPLOAD_LIMIT'] == 5


class TestUtilityFunctions:
    """Тесты утилитарных функций"""
    
    def test_verify_inbound_token(self):
        """Тест проверки токена"""
        from app import verify_inbound_token
        
        # Устанавливаем токен
        app.config['INBOUND_URL_TOKEN'] = 'test_token'
        
        assert verify_inbound_token('test_token') is True
        assert verify_inbound_token('wrong_token') is False
        assert verify_inbound_token('') is False
        assert verify_inbound_token(None) is False
    
    def test_parse_location_from_subject(self):
        """Тест парсинга координат из темы"""
        from app import parse_location_from_subject
        
        # Валидные координаты
        lat, lng = parse_location_from_subject("Test lat:55.7558,lng:37.6176")
        assert lat == 55.7558
        assert lng == 37.6176
        
        # Невалидные координаты
        lat, lng = parse_location_from_subject("Test without coordinates")
        assert lat is None
        assert lng is None
        
        # Пустая тема
        lat, lng = parse_location_from_subject("")
        assert lat is None
        assert lng is None


class TestErrorHandling:
    """Тесты обработки ошибок"""
    
    def setup_method(self):
        """Настройка для каждого теста"""
        self.app = app.test_client()
        self.app.testing = True

    def test_webhook_critical_error(self):
        """Тест критической ошибки в вебхуке"""
        with patch('app.webhook_handler.handle_postmark_webhook_request') as mock_handler:
            # Симулируем критическую ошибку
            mock_handler.side_effect = Exception("Critical error")
            
            webhook_data = {
                "FromFull": {"Email": "test@example.com"},
                "Subject": "Test",
                "Attachments": []
            }
            
            response = self.app.post(
                '/webhook/postmark?token=test_token',
                data=json.dumps(webhook_data),
                content_type='application/json'
            )
            
            assert response.status_code == 500
            data = json.loads(response.data)
            assert data['status'] == 'error'
            assert 'Internal server error' in data['message']
    
    def test_webhook_invalid_token(self):
        """Тест невалидного токена"""
        with patch('app.webhook_handler.handle_postmark_webhook_request') as mock_handler:
            mock_handler.return_value = {
                'status': 'error',
                'message': 'Invalid token',
                'http_status_code': 401
            }
            
            webhook_data = {
                "FromFull": {"Email": "test@example.com"},
                "Subject": "Test",
                "Attachments": []
            }
            
            response = self.app.post(
                '/webhook/postmark?token=wrong_token',
                data=json.dumps(webhook_data),
                content_type='application/json'
            )
            
            assert response.status_code == 401
            data = json.loads(response.data)
            assert data['status'] == 'error'
            assert data['message'] == 'Invalid token'


class TestResponseFormats:
    """Тесты форматов ответов"""
    
    def setup_method(self):
        """Настройка для каждого теста"""
        self.app = app.test_client()
        self.app.testing = True

    @patch('app.webhook_handler.handle_postmark_webhook_request')
    def test_success_response_format(self, mock_handler):
        """Тест формата успешного ответа"""
        mock_handler.return_value = {
            'status': 'success',
            'contentIds': ['id1', 'id2'],
            'message': '2 content item(s) published successfully',
            'skipped_count': 0,
            'http_status_code': 200
        }
        
        webhook_data = {
            "FromFull": {"Email": "test@example.com"},
            "Subject": "Test",
            "Attachments": []
        }
        
        response = self.app.post(
            '/webhook/postmark?token=test_token',
            data=json.dumps(webhook_data),
            content_type='application/json'
        )
        
        data = json.loads(response.data)
        assert 'status' in data
        assert 'message' in data
        assert 'contentIds' in data
        assert 'skipped_count' in data
        assert data['status'] == 'success'
        assert len(data['contentIds']) == 2
        assert data['skipped_count'] == 0
    
    @patch('app.webhook_handler.handle_postmark_webhook_request')
    def test_partial_success_response_format(self, mock_handler):
        """Тест формата частичного успеха"""
        mock_handler.return_value = {
            'status': 'partial_success',
            'contentIds': ['id1'],
            'message': '1 content item(s) published successfully, 1 image(s) skipped due to upload limit',
            'skipped_count': 1,
            'http_status_code': 200
        }
        
        webhook_data = {
            "FromFull": {"Email": "test@example.com"},
            "Subject": "Test",
            "Attachments": []
        }
        
        response = self.app.post(
            '/webhook/postmark?token=test_token',
            data=json.dumps(webhook_data),
            content_type='application/json'
        )
        
        data = json.loads(response.data)
        assert data['status'] == 'partial_success'
        assert len(data['contentIds']) == 1
        assert data['skipped_count'] == 1
        assert 'skipped due to upload limit' in data['message']


class TestPerformance:
    """Тесты производительности"""
    
    def setup_method(self):
        """Настройка для каждого теста"""
        self.app = app.test_client()
        self.app.testing = True

        # Создаем тестовое изображение
        self.img = Image.new('RGB', (10, 10), color='red')
        self.img_bytes = io.BytesIO()
        self.img.save(self.img_bytes, format='JPEG')
        self.image_data = self.img_bytes.getvalue()
        self.image_base64 = base64.b64encode(self.image_data).decode('utf-8')

    @patch('app.webhook_handler.handle_postmark_webhook_request')
    def test_webhook_response_time(self, mock_handler):
        """Тест времени ответа вебхука"""
        import time
        
        mock_handler.return_value = {
            'status': 'success',
            'contentIds': ['id1'],
            'message': 'Success',
            'http_status_code': 200
        }
        
        webhook_data = {
            "FromFull": {"Email": "test@example.com"},
            "Subject": "Test",
            "Attachments": []
        }
        
        start_time = time.time()
        response = self.app.post(
            '/webhook/postmark?token=test_token',
            data=json.dumps(webhook_data),
            content_type='application/json'
        )
        end_time = time.time()
        
        # Проверяем, что ответ получен менее чем за 1 секунду
        assert end_time - start_time < 1.0
        assert response.status_code == 200
    
    def test_large_payload_handling(self):
        """Тест обработки больших payload"""
        # Создаем большое изображение
        large_img = Image.new('RGB', (1000, 1000), color='blue')
        large_img_bytes = io.BytesIO()
        large_img.save(large_img_bytes, format='JPEG', quality=95)
        large_image_data = large_img_bytes.getvalue()
        large_image_base64 = base64.b64encode(large_image_data).decode('utf-8')
        
        webhook_data = {
            "FromFull": {"Email": "test@example.com"},
            "Subject": "Large Image Test",
            "Attachments": [{
                "Name": "large.jpg",
                "ContentType": "image/jpeg",
                "Content": large_image_base64
            }]
        }
        
        with patch('app.webhook_handler.handle_postmark_webhook_request') as mock_handler:
            mock_handler.return_value = {
                'status': 'success',
                'contentIds': ['id1'],
                'message': 'Success',
                'http_status_code': 200
            }
            
            response = self.app.post(
                '/webhook/postmark?token=test_token',
                data=json.dumps(webhook_data),
                content_type='application/json'
            )
            
            assert response.status_code == 200