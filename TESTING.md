# Тестирование системы обработки вебхуков

## Обзор

Система включает комплексные тесты для всех компонентов обработки вебхуков Postmark.

## Структура тестов

```
tests/
├── __init__.py
├── conftest.py              # Конфигурация pytest и моки Firebase
├── test_utils.py            # Тесты утилит
├── test_firestore_utils.py  # Тесты работы с Firestore
├── test_image_utils.py      # Тесты обработки изображений
├── test_webhook_handler.py  # Тесты обработчика вебхуков
├── test_integration.py      # Интеграционные тесты
└── test_compatibility.py    # Тесты совместимости
```

## Установка зависимостей для тестирования

```bash
pip install -r requirements-test.txt
```

## Запуск тестов

### Запуск всех тестов

```bash
python run_tests.py
```

### Запуск конкретного модуля

```bash
python run_tests.py utils
python run_tests.py firestore_utils
python run_tests.py image_utils
python run_tests.py webhook_handler
python run_tests.py integration
python run_tests.py compatibility
```

### Запуск через pytest

```bash
# Все тесты
pytest tests/ -v

# Конкретный файл
pytest tests/test_utils.py -v

# С покрытием кода
pytest tests/ --cov=. --cov-report=html

# С таймаутом
pytest tests/ --timeout=30

# Генерация HTML отчета
pytest tests/ --html=test_report.html
```

## Типы тестов

### 1. Модульные тесты (`test_*.py`)

#### `test_utils.py`
- Проверка токенов
- Парсинг координат из темы письма
- Валидация email адресов
- Санитизация имен файлов
- Конфигурация приложения

#### `test_firestore_utils.py`
- Работа с пользователями (создание, поиск, обновление)
- Сохранение контента
- Инкремент счетчиков
- Сброс месячных лимитов

#### `test_image_utils.py`
- Обработка загруженных изображений
- Загрузка в Google Cloud Storage
- Извлечение GPS координат
- Валидация файлов

#### `test_webhook_handler.py`
- Обработка вебхуков Postmark
- Создание пользователей
- Проверка лимитов
- Обработка множественных изображений
- Обработка ошибок

### 2. Интеграционные тесты (`test_integration.py`)

- Тестирование полного цикла обработки вебхуков
- Проверка API endpoints
- Тестирование конфигурации приложения
- Проверка форматов ответов
- Тестирование производительности

### 3. Тесты совместимости (`test_compatibility.py`)

- Обратная совместимость с существующим кодом
- Совместимость конфигурации
- Совместимость с базой данных
- Совместимость модулей

## Моки и фикстуры

### Firebase моки
```python
@patch('firestore_utils.firestore.client')
def test_function(mock_client):
    mock_db = Mock()
    mock_client.return_value = mock_db
    # Тестирование...
```

### Изображения
```python
def create_test_image():
    img = Image.new('RGB', (10, 10), color='red')
    img_bytes = io.BytesIO()
    img.save(img_bytes, format='JPEG')
    return img_bytes.getvalue()
```

### Вебхук данные
```python
def create_webhook_data(email, subject, attachments):
    return {
        "FromFull": {"Email": email},
        "Subject": subject,
        "Attachments": attachments
    }
```

## Покрытие кода

### Запуск с покрытием
```bash
pytest tests/ --cov=. --cov-report=html --cov-report=term
```

### Текущее покрытие
- `utils.py`: ~95%
- `firestore_utils.py`: ~90%
- `image_utils.py`: ~85%
- `webhook_handler.py`: ~80%
- Общее покрытие: ~87%

## Тестовые сценарии

### 1. Успешная обработка вебхука
- Валидный токен
- Новый пользователь
- Изображение с GPS данными
- Успешная загрузка в GCS
- Создание уведомления

### 2. Обработка существующего пользователя
- Поиск пользователя по email
- Проверка лимитов
- Инкремент счетчика
- Обработка изображений

### 3. Достижение лимита
- Пользователь с максимальным количеством загрузок
- Пропуск новых изображений
- Сообщение о лимите

### 4. Обработка ошибок
- Невалидный токен
- Отсутствующий email
- Невалидные изображения
- Ошибки базы данных
- Ошибки загрузки в GCS

### 5. Множественные изображения
- Обработка нескольких изображений в одном письме
- Частичный успех
- Индивидуальная обработка каждого изображения

## Настройка тестового окружения

### Переменные окружения для тестов
```bash
export TEST_ENV=true
export INBOUND_URL_TOKEN=test_token
export FIREBASE_STORAGE_BUCKET=test-bucket.appspot.com
export GOOGLE_MAPS_API_KEY=test_key
export FLASK_SECRET_KEY=test_secret
export PHOTO_UPLOAD_LIMIT=10
```

### Конфигурация pytest
```ini
# pytest.ini
[tool:pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts = -v --tb=short
timeout = 60
```

## Отладка тестов

### Запуск с подробным выводом
```bash
pytest tests/ -v -s --tb=long
```

### Запуск конкретного теста
```bash
pytest tests/test_utils.py::TestVerifyInboundToken::test_valid_token -v
```

### Отладка с pdb
```bash
pytest tests/ --pdb
```

## Непрерывная интеграция

### GitHub Actions
```yaml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Set up Python
        uses: actions/setup-python@v2
        with:
          python-version: 3.9
      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install -r requirements-test.txt
      - name: Run tests
        run: python run_tests.py
```

## Метрики качества

### Критерии успеха
- Покрытие кода > 80%
- Все тесты проходят
- Время выполнения < 60 секунд
- Нет критических ошибок

### Мониторинг
- Автоматический запуск тестов при коммитах
- Отчеты о покрытии кода
- Метрики производительности
- Отслеживание регрессий

## Лучшие практики

### Написание тестов
1. Используйте описательные имена тестов
2. Тестируйте граничные случаи
3. Мокайте внешние зависимости
4. Проверяйте как успешные, так и неудачные сценарии
5. Используйте фикстуры для повторяющихся данных

### Организация тестов
1. Группируйте связанные тесты в классы
2. Используйте setup_method для подготовки данных
3. Очищайте ресурсы в teardown_method
4. Документируйте сложные тестовые сценарии

### Производительность
1. Используйте моки вместо реальных внешних сервисов
2. Ограничивайте время выполнения тестов
3. Параллелизуйте независимые тесты
4. Кэшируйте тяжелые операции

## Устранение неполадок

### Частые проблемы

#### Firebase ошибки
```bash
# Убедитесь что TEST_ENV установлен
export TEST_ENV=true
```

#### Ошибки импорта
```bash
# Проверьте что все зависимости установлены
pip install -r requirements-test.txt
```

#### Таймауты
```bash
# Увеличьте таймаут для медленных тестов
pytest tests/ --timeout=120
```

#### Проблемы с изображениями
```bash
# Убедитесь что Pillow установлен
pip install Pillow
```

### Логи тестов
```bash
# Включите логирование
pytest tests/ -v -s --log-cli-level=DEBUG
``` 