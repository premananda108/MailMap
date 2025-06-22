import pytest
import base64
import io
from unittest.mock import Mock, patch, MagicMock
from PIL import Image
from image_utils import (
    process_uploaded_image,
    upload_image_to_gcs,
    extract_gps_coordinates
)


class TestProcessUploadedImage:
    """Тесты для функции process_uploaded_image"""
    
    def test_valid_image_processing(self):
        """Тест обработки валидного изображения"""
        # Создаем тестовое изображение
        img = Image.new('RGB', (10, 10), color='red')
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='JPEG')
        image_data = img_bytes.getvalue()
        
        # Мокаем bucket и logger
        mock_bucket = Mock()
        mock_logger = Mock()
        
        # Мокаем upload_image_to_gcs
        with patch('image_utils.upload_image_to_gcs') as mock_upload:
            mock_upload.return_value = "http://example.com/image.jpg"
            
            # Мокаем extract_gps_coordinates
            with patch('image_utils.extract_gps_coordinates') as mock_gps:
                mock_gps.return_value = (55.7558, 37.6176)
                
                # Выполнение
                result = process_uploaded_image(
                    image_bytes=image_data,
                    original_filename="test.jpg",
                    app_logger=mock_logger,
                    bucket=mock_bucket,
                    allowed_extensions={'jpg', 'jpeg', 'png', 'gif'},
                    max_size=1024 * 1024  # 1MB
                )
                
                # Проверка
                assert result[0] == "http://example.com/image.jpg"
                assert result[1] == 55.7558
                assert result[2] == 37.6176
    
    def test_invalid_filename(self):
        """Тест с невалидным именем файла"""
        mock_logger = Mock()
        mock_bucket = Mock()
        
        result = process_uploaded_image(
            image_bytes=b"fake_image_data",
            original_filename="",
            app_logger=mock_logger,
            bucket=mock_bucket,
            allowed_extensions={'jpg'},
            max_size=1024 * 1024
        )
        
        assert result == (None, None, None)
        mock_logger.warning.assert_called()
    
    def test_unsupported_extension(self):
        """Тест с неподдерживаемым расширением"""
        mock_logger = Mock()
        mock_bucket = Mock()
        
        result = process_uploaded_image(
            image_bytes=b"fake_image_data",
            original_filename="test.txt",
            app_logger=mock_logger,
            bucket=mock_bucket,
            allowed_extensions={'jpg'},
            max_size=1024 * 1024
        )
        
        assert result == (None, None, None)
        mock_logger.warning.assert_called()
    
    def test_file_too_large(self):
        """Тест с файлом слишком большого размера"""
        mock_logger = Mock()
        mock_bucket = Mock()
        
        # Создаем большой файл
        large_data = b"x" * (2 * 1024 * 1024)  # 2MB
        
        result = process_uploaded_image(
            image_bytes=large_data,
            original_filename="test.jpg",
            app_logger=mock_logger,
            bucket=mock_bucket,
            allowed_extensions={'jpg'},
            max_size=1024 * 1024  # 1MB limit
        )
        
        assert result == (None, None, None)
        mock_logger.warning.assert_called()
    
    def test_upload_failure(self):
        """Тест когда загрузка в GCS не удалась"""
        # Создаем тестовое изображение
        img = Image.new('RGB', (10, 10), color='red')
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='JPEG')
        image_data = img_bytes.getvalue()
        
        mock_bucket = Mock()
        mock_logger = Mock()
        
        with patch('image_utils.upload_image_to_gcs') as mock_upload:
            mock_upload.return_value = None  # Загрузка не удалась
            
            with patch('image_utils.extract_gps_coordinates') as mock_gps:
                mock_gps.return_value = (55.7558, 37.6176)
                
                result = process_uploaded_image(
                    image_bytes=image_data,
                    original_filename="test.jpg",
                    app_logger=mock_logger,
                    bucket=mock_bucket,
                    allowed_extensions={'jpg'},
                    max_size=1024 * 1024
                )
                
                assert result == (None, None, None)
                mock_logger.error.assert_called()
    
    def test_exception_handling(self):
        """Тест обработки исключений"""
        mock_logger = Mock()
        mock_bucket = Mock()
        
        # Симулируем исключение при обработке
        with patch('image_utils.extract_gps_coordinates') as mock_gps:
            mock_gps.side_effect = Exception("GPS extraction failed")
            
            result = process_uploaded_image(
                image_bytes=b"fake_image_data",
                original_filename="test.jpg",
                app_logger=mock_logger,
                bucket=mock_bucket,
                allowed_extensions={'jpg'},
                max_size=1024 * 1024
            )
            
            assert result == (None, None, None)
            mock_logger.error.assert_called()


class TestUploadImageToGCS:
    """Тесты для функции upload_image_to_gcs"""
    
    def test_successful_upload(self):
        """Тест успешной загрузки в GCS"""
        # Создаем тестовое изображение
        img = Image.new('RGB', (10, 10), color='red')
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='JPEG')
        image_data = img_bytes.getvalue()
        
        # Мокаем bucket
        mock_bucket = Mock()
        mock_blob = Mock()
        mock_bucket.blob.return_value = mock_blob
        mock_blob.public_url = "http://example.com/image.jpg"
        
        mock_logger = Mock()
        
        # Выполнение
        result = upload_image_to_gcs(
            image_data=image_data,
            filename="test.jpg",
            bucket=mock_bucket,
            app_logger=mock_logger
        )
        
        # Проверка
        assert result == "http://example.com/image.jpg"
        mock_blob.upload_from_string.assert_called_once()
        mock_blob.make_public.assert_called_once()
        mock_logger.info.assert_called()
    
    def test_upload_exception(self):
        """Тест исключения при загрузке"""
        mock_bucket = Mock()
        mock_bucket.blob.side_effect = Exception("Upload failed")
        
        mock_logger = Mock()
        
        result = upload_image_to_gcs(
            image_data=b"fake_data",
            filename="test.jpg",
            bucket=mock_bucket,
            app_logger=mock_logger
        )
        
        assert result is None
        mock_logger.error.assert_called()
    
    def test_different_file_extensions(self):
        """Тест различных расширений файлов"""
        mock_bucket = Mock()
        mock_blob = Mock()
        mock_bucket.blob.return_value = mock_blob
        mock_blob.public_url = "http://example.com/image"
        
        mock_logger = Mock()
        
        # Тестируем разные расширения
        extensions = ['jpg', 'jpeg', 'png', 'gif']
        
        for ext in extensions:
            result = upload_image_to_gcs(
                image_data=b"fake_data",
                filename=f"test.{ext}",
                bucket=mock_bucket,
                app_logger=mock_logger
            )
            
            assert result == "http://example.com/image"
            # Проверяем, что content_type установлен правильно
            mock_blob.upload_from_string.assert_called_with(
                b"fake_data",
                content_type=f'image/{ext}'
            )


class TestExtractGPSCoordinates:
    """Тесты для функции extract_gps_coordinates"""
    
    def test_extract_gps_with_exifread_success(self):
        """Тест успешного извлечения GPS через exifread"""
        # Создаем тестовое изображение с GPS данными
        img = Image.new('RGB', (10, 10), color='red')
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='JPEG')
        image_data = img_bytes.getvalue()
        
        # Мокаем exifread для возврата GPS данных
        mock_tags = {
            'GPS GPSLatitude': Mock(values=[Mock(num=55, den=1), Mock(num=45, den=1), Mock(num=18, den=1)]),
            'GPS GPSLatitudeRef': Mock(values=['N']),
            'GPS GPSLongitude': Mock(values=[Mock(num=37, den=1), Mock(num=37, den=1), Mock(num=3, den=1)]),
            'GPS GPSLongitudeRef': Mock(values=['E'])
        }
        
        with patch('image_utils.exifread.process_file') as mock_exifread:
            mock_exifread.return_value = mock_tags
            
            lat, lng = extract_gps_coordinates(image_data)
            
            # Проверяем, что функция была вызвана
            mock_exifread.assert_called_once()
    
    def test_extract_gps_with_pillow_success(self):
        """Тест успешного извлечения GPS через Pillow"""
        # Создаем тестовое изображение
        img = Image.new('RGB', (10, 10), color='red')
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='JPEG')
        image_data = img_bytes.getvalue()
        
        # Мокаем exifread для возврата пустых данных
        with patch('image_utils.exifread.process_file') as mock_exifread:
            mock_exifread.return_value = {}
            
            # Мокаем Pillow для возврата GPS данных
            mock_exif_dict = Mock()
            mock_gps_ifd = {
                1: b'N',  # GPSLatitudeRef
                2: [(55, 1), (45, 1), (18, 1)],  # GPSLatitude
                3: b'E',  # GPSLongitudeRef
                4: [(37, 1), (37, 1), (3, 1)]   # GPSLongitude
            }
            mock_exif_dict.get_ifd.return_value = mock_gps_ifd
            
            with patch('image_utils.Image.open') as mock_image_open:
                mock_image = Mock()
                mock_image.getexif.return_value = mock_exif_dict
                mock_image_open.return_value = mock_image
                
                lat, lng = extract_gps_coordinates(image_data)
                
                # Проверяем, что оба метода были вызваны
                mock_exifread.assert_called_once()
                mock_image_open.assert_called_once()
    
    def test_no_gps_data(self):
        """Тест когда GPS данные отсутствуют"""
        # Создаем тестовое изображение без GPS
        img = Image.new('RGB', (10, 10), color='red')
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='JPEG')
        image_data = img_bytes.getvalue()
        
        # Мокаем оба метода для возврата пустых данных
        with patch('image_utils.exifread.process_file') as mock_exifread:
            mock_exifread.return_value = {}
            
            with patch('image_utils.Image.open') as mock_image_open:
                mock_image = Mock()
                mock_exif_dict = Mock()
                mock_exif_dict.get_ifd.return_value = {}
                mock_image.getexif.return_value = mock_exif_dict
                mock_image_open.return_value = mock_image
                
                lat, lng = extract_gps_coordinates(image_data)
                
                assert lat is None
                assert lng is None
    
    def test_exception_handling(self):
        """Тест обработки исключений при извлечении GPS"""
        # Создаем тестовое изображение
        img = Image.new('RGB', (10, 10), color='red')
        img_bytes = io.BytesIO()
        img.save(img_bytes, format='JPEG')
        image_data = img_bytes.getvalue()
        
        # Симулируем исключение
        with patch('image_utils.exifread.process_file') as mock_exifread:
            mock_exifread.side_effect = Exception("EXIF processing failed")
            
            with patch('image_utils.Image.open') as mock_image_open:
                mock_image_open.side_effect = Exception("Image processing failed")
                
                lat, lng = extract_gps_coordinates(image_data)
                
                assert lat is None
                assert lng is None 