import re
import os


def verify_inbound_token(token_to_verify, inbound_url_token_config):
    """
    Verify the inbound webhook token.
    Returns True if valid, False otherwise.
    """
    if not token_to_verify:
        return False
    return token_to_verify == inbound_url_token_config


def parse_location_from_subject(subject):
    """
    Parse location coordinates from email subject.
    Returns tuple (latitude, longitude) or (None, None) if not found.
    """
    if not subject:
        return None, None
    
    pattern = r'lat:([-+]?\d*\.?\d+),lng:([-+]?\d*\.?\d+)'
    match = re.search(pattern, subject, re.IGNORECASE)
    
    if match:
        try:
            lat = float(match.group(1))
            lng = float(match.group(2))
            
            # Validate coordinates
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                return lat, lng
        except ValueError:
            pass
    
    return None, None


def get_app_config():
    """
    Get application configuration from environment variables.
    Returns dict with configuration values.
    """
    return {
        'INBOUND_URL_TOKEN': os.environ.get('INBOUND_URL_TOKEN', 'DEFAULT_INBOUND_TOKEN_IF_NOT_SET'),
        'FIREBASE_STORAGE_BUCKET': os.environ.get('FIREBASE_STORAGE_BUCKET', 'your-project.appspot.com'),
        'GOOGLE_MAPS_API_KEY': os.environ.get('GOOGLE_MAPS_API_KEY', ''),
        'FLASK_SECRET_KEY': os.environ.get('FLASK_SECRET_KEY', 'default-secret-key-for-development'),
        'PHOTO_UPLOAD_LIMIT': int(os.environ.get('PHOTO_UPLOAD_LIMIT', '0')),  # 0 means no limit
        'ALLOWED_IMAGE_EXTENSIONS': {'jpg', 'jpeg', 'png', 'gif'},
        'MAX_IMAGE_SIZE': 6 * 1024 * 1024  # 6MB
    }


def validate_email(email):
    """
    Basic email validation.
    Returns True if valid, False otherwise.
    """
    if not email:
        return False
    
    # Более строгий паттерн, который не допускает .. и другие невалидные варианты
    pattern = r'^(?!\.)(?!.*\.\.)[a-zA-Z0-9._%+-]+(?<!\.)@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def sanitize_filename(filename):
    """
    Sanitize filename for safe storage.
    Returns sanitized filename.
    """
    if not filename:
        return "" # Возвращаем пустую строку вместо None для консистентности
    
    # Remove or replace unsafe characters
    # Убираем двойные кавычки из списка, т.к. они не всегда являются проблемой
    unsafe_chars = ['<', '>', ':', '/', '\\', '|', '?', '*']
    sanitized = filename
    
    for char in unsafe_chars:
        sanitized = sanitized.replace(char, '_')

    # Заменяем двойные кавычки отдельно
    sanitized = sanitized.replace('"', '_')
    
    # Limit length
    if len(sanitized) > 255:
        name, ext = sanitized.rsplit('.', 1) if '.' in sanitized else (sanitized, '')
        sanitized = name[:255 - (len(ext) + 1)] + ('.' + ext if ext else '')
    
    return sanitized 