import pytest
import os
from unittest.mock import patch
from utils import (
    verify_inbound_token,
    parse_location_from_subject,
    get_app_config,
    validate_email,
    sanitize_filename
)


class TestVerifyInboundToken:
    """Тесты для функции verify_inbound_token"""
    
    def test_valid_token(self):
        """Тест с валидным токеном"""
        token = "test_token"
        config_token = "test_token"
        assert verify_inbound_token(token, config_token) is True
    
    def test_invalid_token(self):
        """Тест с невалидным токеном"""
        token = "wrong_token"
        config_token = "test_token"
        assert verify_inbound_token(token, config_token) is False
    
    def test_empty_token(self):
        """Тест с пустым токеном"""
        token = ""
        config_token = "test_token"
        assert verify_inbound_token(token, config_token) is False
    
    def test_none_token(self):
        """Тест с None токеном"""
        token = None
        config_token = "test_token"
        assert verify_inbound_token(token, config_token) is False


class TestParseLocationFromSubject:
    """Тесты для функции parse_location_from_subject"""
    
    def test_valid_coordinates(self):
        """Тест с валидными координатами"""
        subject = "Test Post lat:55.7558,lng:37.6176"
        lat, lng = parse_location_from_subject(subject)
        assert lat == 55.7558
        assert lng == 37.6176
    
    def test_negative_coordinates(self):
        """Тест с отрицательными координатами"""
        subject = "Test Post lat:-55.7558,lng:-37.6176"
        lat, lng = parse_location_from_subject(subject)
        assert lat == -55.7558
        assert lng == -37.6176
    
    def test_case_insensitive(self):
        """Тест с разным регистром"""
        subject = "Test Post LAT:55.7558,LNG:37.6176"
        lat, lng = parse_location_from_subject(subject)
        assert lat == 55.7558
        assert lng == 37.6176
    
    def test_invalid_coordinates(self):
        """Тест с невалидными координатами"""
        subject = "Test Post lat:200,lng:300"  # Вне диапазона
        lat, lng = parse_location_from_subject(subject)
        assert lat is None
        assert lng is None
    
    def test_malformed_subject(self):
        """Тест с неправильным форматом"""
        subject = "Test Post lat:55.7558 lng:37.6176"  # Без запятой
        lat, lng = parse_location_from_subject(subject)
        assert lat is None
        assert lng is None
    
    def test_empty_subject(self):
        """Тест с пустой темой"""
        subject = ""
        lat, lng = parse_location_from_subject(subject)
        assert lat is None
        assert lng is None
    
    def test_none_subject(self):
        """Тест с None темой"""
        subject = None
        lat, lng = parse_location_from_subject(subject)
        assert lat is None
        assert lng is None


class TestGetAppConfig:
    """Тесты для функции get_app_config"""
    
    @patch.dict(os.environ, {
        'INBOUND_URL_TOKEN': 'test_token',
        'FIREBASE_STORAGE_BUCKET': 'test-bucket.appspot.com',
        'GOOGLE_MAPS_API_KEY': 'test_api_key',
        'FLASK_SECRET_KEY': 'test_secret',
        'PHOTO_UPLOAD_LIMIT': '10'
    })
    def test_config_with_env_vars(self):
        """Тест конфигурации с переменными окружения"""
        config = get_app_config()
        assert config['INBOUND_URL_TOKEN'] == 'test_token'
        assert config['FIREBASE_STORAGE_BUCKET'] == 'test-bucket.appspot.com'
        assert config['GOOGLE_MAPS_API_KEY'] == 'test_api_key'
        assert config['FLASK_SECRET_KEY'] == 'test_secret'
        assert config['PHOTO_UPLOAD_LIMIT'] == 10
    
    @patch.dict(os.environ, {}, clear=True)
    def test_config_without_env_vars(self):
        """Тест конфигурации без переменных окружения"""
        config = get_app_config()
        assert config['INBOUND_URL_TOKEN'] == 'DEFAULT_INBOUND_TOKEN_IF_NOT_SET'
        assert config['FIREBASE_STORAGE_BUCKET'] == 'your-project.appspot.com'
        assert config['GOOGLE_MAPS_API_KEY'] == ''
        assert config['FLASK_SECRET_KEY'] == 'default-secret-key-for-development'
        assert config['PHOTO_UPLOAD_LIMIT'] == 0
    
    def test_allowed_extensions(self):
        """Тест разрешенных расширений файлов"""
        config = get_app_config()
        assert 'jpg' in config['ALLOWED_IMAGE_EXTENSIONS']
        assert 'jpeg' in config['ALLOWED_IMAGE_EXTENSIONS']
        assert 'png' in config['ALLOWED_IMAGE_EXTENSIONS']
        assert 'gif' in config['ALLOWED_IMAGE_EXTENSIONS']
    
    def test_max_image_size(self):
        """Тест максимального размера изображения"""
        config = get_app_config()
        assert config['MAX_IMAGE_SIZE'] == 6 * 1024 * 1024  # 6MB


class TestValidateEmail:
    """Тесты для функции validate_email"""
    
    def test_valid_emails(self):
        """Тест валидных email адресов"""
        valid_emails = [
            "test@example.com",
            "user.name@domain.co.uk",
            "user+tag@example.org",
            "123@test.com"
        ]
        for email in valid_emails:
            assert validate_email(email) is True
    
    def test_invalid_emails(self):
        """Тест невалидных email адресов"""
        invalid_emails = [
            "invalid-email",
            "@example.com",
            "user@",
            "user@.com",
            "user..name@example.com",
            ""
        ]
        for email in invalid_emails:
            assert validate_email(email) is False
    
    def test_none_email(self):
        """Тест с None email"""
        assert validate_email(None) is False


class TestSanitizeFilename:
    """Тесты для функции sanitize_filename"""
    
    def test_safe_filename(self):
        """Тест безопасного имени файла"""
        filename = "safe_image.jpg"
        sanitized = sanitize_filename(filename)
        assert sanitized == "safe_image.jpg"
    
    def test_unsafe_characters(self):
        """Тест с небезопасными символами"""
        filename = "file<name>:with\"unsafe/chars\\|?*.jpg"
        sanitized = sanitize_filename(filename)
        assert sanitized == "file_name__with_unsafe_chars_____.jpg"
    
    def test_long_filename(self):
        """Тест с длинным именем файла"""
        long_name = "a" * 300 + ".jpg"
        sanitized = sanitize_filename(long_name)
        assert len(sanitized) <= 255
        assert sanitized.endswith(".jpg")
    
    def test_empty_filename(self):
        """Тест с пустым именем файла"""
        assert sanitize_filename("") is None
        assert sanitize_filename(None) is None
    
    def test_filename_without_extension(self):
        """Тест имени файла без расширения"""
        filename = "filename_without_extension"
        sanitized = sanitize_filename(filename)
        assert sanitized == "filename_without_extension" 