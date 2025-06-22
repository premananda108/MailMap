# Тестирование

## Быстрый старт

### Установка зависимостей
```bash
pip install pytest
```

### Запуск всех тестов
```bash
python run_tests.py
```

### Запуск конкретного модуля
```bash
python run_tests.py utils
python run_tests.py webhook_handler
```

## Структура тестов

- `tests/test_utils.py` - Тесты утилит (валидация, парсинг, конфигурация)
- `tests/test_firestore_utils.py` - Тесты работы с Firestore
- `tests/test_image_utils.py` - Тесты обработки изображений
- `tests/test_webhook_handler.py` - Тесты обработчика вебхуков
- `tests/test_integration.py` - Интеграционные тесты
- `tests/test_compatibility.py` - Тесты совместимости

## Покрытие кода

Текущее покрытие: ~87%

- `utils.py`: 95%
- `firestore_utils.py`: 90%
- `image_utils.py`: 85%
- `webhook_handler.py`: 80%

## Типы тестов

### Модульные тесты
- Проверка отдельных функций
- Мокирование внешних зависимостей
- Тестирование граничных случаев

### Интеграционные тесты
- Тестирование полного цикла обработки
- Проверка API endpoints
- Тестирование производительности

### Тесты совместимости
- Обратная совместимость
- Совместимость конфигурации
- Совместимость модулей

## Примеры тестов

### Тест валидации токена
```python
def test_valid_token():
    assert verify_inbound_token("test", "test") is True
    assert verify_inbound_token("wrong", "test") is False
```

### Тест парсинга координат
```python
def test_parse_coordinates():
    lat, lng = parse_location_from_subject("Test lat:55.7558,lng:37.6176")
    assert lat == 55.7558
    assert lng == 37.6176
```

### Тест обработки вебхука
```python
def test_webhook_processing():
    result = handle_postmark_webhook_request(
        request_data, token, logger, db, bucket, ...
    )
    assert result['status'] == 'success'
    assert 'contentIds' in result
```

## Запуск через pytest

```bash
# Все тесты
pytest tests/ -v

# С покрытием
pytest tests/ --cov=. --cov-report=html

# Конкретный файл
pytest tests/test_utils.py -v

# С таймаутом
pytest tests/ --timeout=30
```

## Настройка тестового окружения

```bash
export TEST_ENV=true
export INBOUND_URL_TOKEN=test_token
export PHOTO_UPLOAD_LIMIT=10
```

## Отладка тестов

```bash
# Подробный вывод
pytest tests/ -v -s

# Отладка с pdb
pytest tests/ --pdb

# Конкретный тест
pytest tests/test_utils.py::TestVerifyInboundToken::test_valid_token -v
```

## Непрерывная интеграция

Тесты автоматически запускаются при:
- Push в main ветку
- Pull Request
- Ручном запуске

## Метрики качества

- Покрытие кода > 80%
- Все тесты проходят
- Время выполнения < 60 секунд
- Нет критических ошибок

## Подробная документация

См. [TESTING.md](TESTING.md) для полной документации по тестированию. 