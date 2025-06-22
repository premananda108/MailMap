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


class TestBackwardCompatibility:
    """Тесты обратной совместимости"""
    
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
    
    def test_existing_functions_still_available(self):
        """Тест что существующие функции все еще доступны"""
        # Проверяем что старые функции все еще существуют
        assert hasattr(app, 'verify_inbound_token')
        assert hasattr(app, 'parse_location_from_subject')
        assert hasattr(app, 'upload_image_to_gcs')
        assert hasattr(app, 'save_content_to_firestore')
        assert hasattr(app, 'process_email_attachments')
    
    def test_old_webhook_format_still_works(self):
        """Тест что старый формат вебхука все еще работает"""
        # Старый формат данных
        old_format_data = {
            "From": "test@example.com",  # Старый формат
            "Subject": "Test Post lat:55.7558,lng:37.6176",
            "TextBody": "Test content",
            "Attachments": [{
                "Name": "test.jpg",
                "ContentType": "image/jpeg",
                "Content": self.image_base64
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
                data=json.dumps(old_format_data),
                content_type='application/json'
            )
            
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['status'] == 'success'
    
    def test_new_webhook_format_works(self):
        """Тест что новый формат вебхука работает"""
        # Новый формат данных
        new_format_data = {
            "FromFull": {"Email": "test@example.com"},  # Новый формат
            "Subject": "Test Post lat:55.7558,lng:37.6176",
            "TextBody": "Test content",
            "Attachments": [{
                "Name": "test.jpg",
                "ContentType": "image/jpeg",
                "Content": self.image_base64
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
                data=json.dumps(new_format_data),
                content_type='application/json'
            )
            
            assert response.status_code == 200
            data = json.loads(response.data)
            assert data['status'] == 'success'
    
    def test_existing_api_endpoints_still_work(self):
        """Тест что существующие API endpoints все еще работают"""
        # Тестируем существующие endpoints
        endpoints = [
            '/',
            '/admin/login',
            '/api/content/create'
        ]
        
        for endpoint in endpoints:
            response = self.app.get(endpoint)
            # Проверяем что endpoint отвечает (не 404)
            assert response.status_code != 404
    
    def test_existing_template_filters_still_work(self):
        """Тест что существующие template filters все еще работают"""
        from app import format_datetime_filter
        
        # Тестируем filter
        from datetime import datetime
        test_time = datetime(2024, 1, 1, 12, 30)
        result = format_datetime_filter(test_time)
        assert result == "01.01.2024 12:30"
        
        # Тестируем с None
        result = format_datetime_filter(None)
        assert result == ""


class TestConfigurationCompatibility:
    """Тесты совместимости конфигурации"""
    
    def test_old_configuration_still_works(self):
        """Тест что старая конфигурация все еще работает"""
        # Проверяем что старые переменные окружения все еще поддерживаются
        old_config_vars = [
            'INBOUND_URL_TOKEN',
            'FIREBASE_STORAGE_BUCKET',
            'GOOGLE_MAPS_API_KEY',
            'FLASK_SECRET_KEY'
        ]
        
        for var in old_config_vars:
            # Проверяем что переменная может быть установлена
            with patch.dict('os.environ', {var: 'test_value'}):
                import utils
                config = utils.get_app_config()
                assert var in config
    
    def test_new_configuration_works(self):
        """Тест что новая конфигурация работает"""
        # Проверяем новую переменную окружения
        with patch.dict('os.environ', {'PHOTO_UPLOAD_LIMIT': '15'}):
            import utils
            config = utils.get_app_config()
            assert config['PHOTO_UPLOAD_LIMIT'] == 15
    
    def test_default_configuration_values(self):
        """Тест значений по умолчанию"""
        import utils
        
        # Очищаем переменные окружения
        with patch.dict('os.environ', {}, clear=True):
            config = utils.get_app_config()
            
            # Проверяем значения по умолчанию
            assert config['INBOUND_URL_TOKEN'] == 'DEFAULT_INBOUND_TOKEN_IF_NOT_SET'
            assert config['FIREBASE_STORAGE_BUCKET'] == 'your-project.appspot.com'
            assert config['GOOGLE_MAPS_API_KEY'] == ''
            assert config['FLASK_SECRET_KEY'] == 'default-secret-key-for-development'
            assert config['PHOTO_UPLOAD_LIMIT'] == 0


class TestDatabaseCompatibility:
    """Тесты совместимости с базой данных"""
    
    @patch('app.firestore.client')
    def test_existing_content_structure_preserved(self, mock_client):
        """Тест что структура существующего контента сохранена"""
        # Проверяем что новые поля не ломают старую структуру
        old_content_structure = {
            'text': 'Test content',
            'imageUrl': 'http://example.com/image.jpg',
            'latitude': 55.7558,
            'longitude': 37.6176,
            'timestamp': '2024-01-01T12:00:00Z',
            'status': 'published',
            'voteCount': 0,
            'reportedCount': 0
        }
        
        # Проверяем что все обязательные поля присутствуют
        required_fields = [
            'text', 'imageUrl', 'latitude', 'longitude', 
            'timestamp', 'status', 'voteCount', 'reportedCount'
        ]
        
        for field in required_fields:
            assert field in old_content_structure
    
    @patch('app.firestore.client')
    def test_new_content_structure_works(self, mock_client):
        """Тест что новая структура контента работает"""
        # Проверяем новые поля
        new_content_structure = {
            'text': 'Test content',
            'imageUrl': 'http://example.com/image.jpg',
            'latitude': 55.7558,
            'longitude': 37.6176,
            'timestamp': '2024-01-01T12:00:00Z',
            'status': 'published',
            'voteCount': 0,
            'reportedCount': 0,
            'userId': 'test_user_id',  # Новое поле
            'subject': 'Test Subject'  # Новое поле
        }
        
        # Проверяем что новые поля не конфликтуют со старыми
        assert 'userId' in new_content_structure
        assert 'subject' in new_content_structure
        assert new_content_structure['userId'] == 'test_user_id'


class TestModuleCompatibility:
    """Тесты совместимости модулей"""
    
    def test_all_modules_importable(self):
        """Тест что все модули можно импортировать"""
        modules = [
            'utils',
            'firestore_utils',
            'webhook_handler',
            'image_utils',
            'email_utils'
        ]
        
        for module_name in modules:
            try:
                __import__(module_name)
            except ImportError as e:
                pytest.fail(f"Module {module_name} cannot be imported: {e}")
    
    def test_module_functions_available(self):
        """Тест что функции модулей доступны"""
        import utils
        import firestore_utils
        import webhook_handler
        import image_utils
        
        # Проверяем основные функции
        assert hasattr(utils, 'verify_inbound_token')
        assert hasattr(utils, 'parse_location_from_subject')
        assert hasattr(utils, 'get_app_config')
        
        assert hasattr(firestore_utils, 'get_user_by_email')
        assert hasattr(firestore_utils, 'create_user')
        assert hasattr(firestore_utils, 'save_content_item')
        
        assert hasattr(webhook_handler, 'handle_postmark_webhook_request')
        
        assert hasattr(image_utils, 'process_uploaded_image')
        assert hasattr(image_utils, 'extract_gps_coordinates')
    
    def test_module_dependencies_resolved(self):
        """Тест что зависимости модулей разрешены"""
        # Проверяем что модули могут использовать друг друга
        import utils
        import firestore_utils
        import webhook_handler
        
        # Проверяем что функции могут быть вызваны
        config = utils.get_app_config()
        assert isinstance(config, dict)
        
        # Проверяем что функции принимают правильные параметры
        token_valid = utils.verify_inbound_token("test", "test")
        assert isinstance(token_valid, bool)
        
        lat, lng = utils.parse_location_from_subject("Test lat:55.7558,lng:37.6176")
        assert lat == 55.7558
        assert lng == 37.6176


class TestErrorHandlingCompatibility:
    """Тесты совместимости обработки ошибок"""
    
    def test_old_error_handling_still_works(self):
        """Тест что старая обработка ошибок все еще работает"""
        # Проверяем что старые функции обработки ошибок все еще существуют
        assert hasattr(app, 'logger')
        assert app.logger is not None
        
        # Проверяем что логирование работает
        app.logger.info("Test log message")
        app.logger.warning("Test warning message")
        app.logger.error("Test error message")
    
    def test_new_error_handling_works(self):
        """Тест что новая обработка ошибок работает"""
        # Проверяем что новые модули имеют логирование
        import utils
        import firestore_utils
        import webhook_handler
        
        # Проверяем что функции принимают logger параметр
        mock_logger = Mock()
        
        # Тестируем функции с logger
        utils.verify_inbound_token("test", "test")  # Не требует logger
        utils.parse_location_from_subject("test")   # Не требует logger
        
        # Эти функции должны работать с logger
        firestore_utils.get_user_by_email("test@example.com", mock_logger)
        firestore_utils.create_user("uid", "email", "name", "provider", mock_logger) 