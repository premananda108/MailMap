import pytest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime
from firestore_utils import (
    get_user_by_email,
    get_user,
    create_user,
    save_content_item,
    increment_user_photo_count,
    reset_monthly_photo_count_if_needed
)


class TestGetUserByEmail:
    """Тесты для функции get_user_by_email"""
    
    @patch('firestore_utils.firestore.client')
    def test_user_found(self, mock_client):
        """Тест когда пользователь найден"""
        # Подготовка моков
        mock_db = Mock()
        mock_client.return_value = mock_db
        
        mock_users_ref = Mock()
        mock_db.collection.return_value = mock_users_ref
        
        mock_query = Mock()
        mock_users_ref.where.return_value = mock_query
        mock_query.limit.return_value = mock_query
        
        # Создаем мок документа
        mock_doc = Mock()
        mock_doc.id = "test_uid"
        mock_doc.to_dict.return_value = {
            "email": "test@example.com",
            "displayName": "Test User"
        }
        
        mock_query.get.return_value = [mock_doc]
        
        # Выполнение
        result = get_user_by_email("test@example.com", Mock())
        
        # Проверка
        assert result is not None
        assert result["uid"] == "test_uid"
        assert result["email"] == "test@example.com"
        assert result["displayName"] == "Test User"
    
    @patch('firestore_utils.firestore.client')
    def test_user_not_found(self, mock_client):
        """Тест когда пользователь не найден"""
        # Подготовка моков
        mock_db = Mock()
        mock_client.return_value = mock_db
        
        mock_users_ref = Mock()
        mock_db.collection.return_value = mock_users_ref
        
        mock_query = Mock()
        mock_users_ref.where.return_value = mock_query
        mock_query.limit.return_value = mock_query
        
        mock_query.get.return_value = []
        
        # Выполнение
        result = get_user_by_email("nonexistent@example.com", Mock())
        
        # Проверка
        assert result is None
    
    @patch('firestore_utils.firestore.client')
    def test_exception_handling(self, mock_client):
        """Тест обработки исключений"""
        mock_client.side_effect = Exception("Database error")
        
        logger = Mock()
        result = get_user_by_email("test@example.com", logger)
        
        assert result is None
        logger.error.assert_called_once()


class TestGetUser:
    """Тесты для функции get_user"""
    
    @patch('firestore_utils.firestore.client')
    def test_user_exists(self, mock_client):
        """Тест когда пользователь существует"""
        # Подготовка моков
        mock_db = Mock()
        mock_client.return_value = mock_db
        
        mock_users_ref = Mock()
        mock_db.collection.return_value = mock_users_ref
        
        mock_doc_ref = Mock()
        mock_users_ref.document.return_value = mock_doc_ref
        
        mock_doc = Mock()
        mock_doc.exists = True
        mock_doc.id = "test_uid"
        mock_doc.to_dict.return_value = {
            "email": "test@example.com",
            "displayName": "Test User"
        }
        
        mock_doc_ref.get.return_value = mock_doc
        
        # Выполнение
        result = get_user("test_uid", Mock())
        
        # Проверка
        assert result is not None
        assert result["uid"] == "test_uid"
        assert result["email"] == "test@example.com"
    
    @patch('firestore_utils.firestore.client')
    def test_user_not_exists(self, mock_client):
        """Тест когда пользователь не существует"""
        # Подготовка моков
        mock_db = Mock()
        mock_client.return_value = mock_db
        
        mock_users_ref = Mock()
        mock_db.collection.return_value = mock_users_ref
        
        mock_doc_ref = Mock()
        mock_users_ref.document.return_value = mock_doc_ref
        
        mock_doc = Mock()
        mock_doc.exists = False
        
        mock_doc_ref.get.return_value = mock_doc
        
        # Выполнение
        result = get_user("nonexistent_uid", Mock())
        
        # Проверка
        assert result is None


    import pytest
    import os
    os.environ['TESTING'] = 'true'  # Устанавливаем переменную окружения TESTING
    from unittest.mock import Mock, patch
    from firestore_utils import create_user

class TestCreateUser:
    """Тесты для функции create_user"""
    
    @patch('firestore_utils.firestore.client')
    def test_successful_creation(self, mock_client):
        """Тест успешного создания пользователя"""
        # Подготовка моков
        mock_db = Mock()
        mock_client.return_value = mock_db
        
        mock_users_ref = Mock()
        mock_db.collection.return_value = mock_users_ref
        
        mock_doc_ref = Mock()
        mock_users_ref.document.return_value = mock_doc_ref
        
        # Выполнение
        result = create_user(
            uid="new_uid",
            email="new@example.com",
            display_name="New User",
            provider="email_webhook",
            app_logger=Mock()
        )
        
        # Проверка
        assert result is not None
        assert result["uid"] == "new_uid"
        assert result["email"] == "new@example.com"
        assert result["displayName"] == "New User"
        assert result["provider"] == "email_webhook"
        assert result["isActive"] is True
        assert "photo_upload_count_current_month" in result
        assert "last_upload_reset" in result
        assert "createdAt" in result
        
        # Проверка вызова set
        mock_doc_ref.set.assert_called_once()
    
    @patch('firestore_utils.firestore.client')
    def test_creation_exception(self, mock_client):
        """Тест исключения при создании пользователя"""
        mock_client.side_effect = Exception("Database error")
        
        logger = Mock()
        result = create_user(
            uid="new_uid",
            email="new@example.com",
            display_name="New User",
            provider="email_webhook",
            app_logger=logger
        )
        
        assert result is None
        logger.error.assert_called_once()


class TestSaveContentItem:
    """Тесты для функции save_content_item"""
    
    @patch('firestore_utils.firestore.client')
    def test_successful_save(self, mock_client):
        """Тест успешного сохранения контента"""
        # Подготовка моков
        mock_db = Mock()
        mock_client.return_value = mock_db
        
        mock_content_ref = Mock()
        mock_db.collection.return_value = mock_content_ref
        
        mock_doc_ref = Mock()
        mock_content_ref.document.return_value = mock_doc_ref
        mock_doc_ref.id = "content_id"
        
        # Выполнение
        content_data = {
            "text": "Test content",
            "imageUrl": "http://example.com/image.jpg",
            "latitude": 55.7558,
            "longitude": 37.6176
        }
        
        result = save_content_item(content_data, Mock())
        
        # Проверка
        assert result == "content_id"
        mock_doc_ref.set.assert_called_once()
        mock_doc_ref.update.assert_called_once()
    
    @patch('firestore_utils.firestore.client')
    def test_save_exception(self, mock_client):
        """Тест исключения при сохранении"""
        mock_client.side_effect = Exception("Database error")
        
        logger = Mock()
        content_data = {"text": "Test content"}
        
        result = save_content_item(content_data, logger)
        
        assert result is None
        logger.error.assert_called_once()


class TestIncrementUserPhotoCount:
    """Тесты для функции increment_user_photo_count"""
    
    @patch('firestore_utils.firestore.client')
    def test_successful_increment(self, mock_client):
        """Тест успешного инкремента счетчика"""
        # Подготовка моков
        mock_db = Mock()
        mock_client.return_value = mock_db
        
        mock_users_ref = Mock()
        mock_db.collection.return_value = mock_users_ref
        
        mock_doc_ref = Mock()
        mock_users_ref.document.return_value = mock_doc_ref
        
        # Выполнение
        result = increment_user_photo_count("test_uid", Mock())
        
        # Проверка
        assert result is True
        mock_doc_ref.update.assert_called_once()
    
    @patch('firestore_utils.firestore.client')
    def test_increment_exception(self, mock_client):
        """Тест исключения при инкременте"""
        mock_client.side_effect = Exception("Database error")
        
        logger = Mock()
        result = increment_user_photo_count("test_uid", logger)
        
        assert result is False
        logger.error.assert_called_once()


class TestResetMonthlyPhotoCountIfNeeded:
    """Тесты для функции reset_monthly_photo_count_if_needed"""
    
    @patch('firestore_utils.firestore.client')
    def test_reset_needed(self, mock_client):
        """Тест когда сброс необходим"""
        # Подготовка моков
        mock_db = Mock()
        mock_client.return_value = mock_db
        
        mock_users_ref = Mock()
        mock_db.collection.return_value = mock_users_ref
        
        mock_doc_ref = Mock()
        mock_users_ref.document.return_value = mock_doc_ref
        
        mock_doc = Mock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {
            "last_upload_reset": datetime(2023, 12, 1)  # Старый месяц
        }
        
        mock_doc_ref.get.return_value = mock_doc
        
        # Выполнение
        result = reset_monthly_photo_count_if_needed("test_uid", Mock())
        
        # Проверка
        assert result is True
        mock_doc_ref.update.assert_called_once()
    
    @patch('firestore_utils.firestore.client')
    def test_reset_not_needed(self, mock_client):
        """Тест когда сброс не необходим"""
        # Подготовка моков
        mock_db = Mock()
        mock_client.return_value = mock_db
        
        mock_users_ref = Mock()
        mock_db.collection.return_value = mock_users_ref
        
        mock_doc_ref = Mock()
        mock_users_ref.document.return_value = mock_doc_ref
        
        mock_doc = Mock()
        mock_doc.exists = True
        mock_doc.to_dict.return_value = {
            "last_upload_reset": datetime(2024, 1, 1)  # Текущий месяц
        }
        
        mock_doc_ref.get.return_value = mock_doc
        
        # Выполнение
        result = reset_monthly_photo_count_if_needed("test_uid", Mock())
        
        # Проверка
        assert result is False
        mock_doc_ref.update.assert_not_called()
    
    @patch('firestore_utils.firestore.client')
    def test_user_not_found(self, mock_client):
        """Тест когда пользователь не найден"""
        # Подготовка моков
        mock_db = Mock()
        mock_client.return_value = mock_db
        
        mock_users_ref = Mock()
        mock_db.collection.return_value = mock_users_ref
        
        mock_doc_ref = Mock()
        mock_users_ref.document.return_value = mock_doc_ref
        
        mock_doc = Mock()
        mock_doc.exists = False
        
        mock_doc_ref.get.return_value = mock_doc
        
        # Выполнение
        logger = Mock()
        result = reset_monthly_photo_count_if_needed("nonexistent_uid", logger)
        
        # Проверка
        assert result is False
        logger.warning.assert_called_once() 