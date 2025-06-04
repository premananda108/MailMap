import os
import base64
import re
import tempfile
from datetime import datetime
import uuid
from dotenv import load_dotenv
from image_utils import extract_gps_coordinates
from flask import Flask, request, jsonify, current_app, \
    render_template, session, redirect, url_for
import firebase_admin
from firebase_admin import credentials, firestore, storage
from werkzeug.utils import secure_filename

# Загрузка переменных окружения из .env файла
load_dotenv()

from email_utils import create_email_notification_record, send_pending_notification

app = Flask(__name__, static_folder='static')


@app.route('/.well-known/appspecific/com.chrome.devtools.json')
def chrome_devtools():
    # Respond with an empty JSON object for Chrome DevTools requests
    return jsonify({})


@app.before_request
def check_content_length():
    # Only check for POST, PUT, PATCH, DELETE methods as GET, HEAD, OPTIONS typically don't have bodies
    if request.method in ['POST', 'PUT', 'PATCH', 'DELETE']:
        # Allow if content_length is explicitly set to 0
        if request.content_length is None and request.headers.get('Transfer-Encoding', '').lower() != 'chunked':
            # Log the situation for debugging
            current_app.logger.warning(
                f"Request to {request.path} from {request.remote_addr} without Content-Length or chunked encoding."
            )
            # Consider returning 411 Length Required, but be cautious as some clients might not handle it well.
            # For now, we'll log and let it proceed, as the 'unexpected EOF' might be due to other reasons.
            # abort(411, description="Content-Length header is required for this request.")
            pass  # Or decide on a specific action, like abort(400) or abort(411)


# Конфигурация
INBOUND_URL_TOKEN = os.environ.get('INBOUND_URL_TOKEN', 'INBOUND_URL_TOKEN')
FIREBASE_STORAGE_BUCKET = os.environ.get('FIREBASE_STORAGE_BUCKET', 'your-project.appspot.com')
GOOGLE_MAPS_API_KEY = os.environ.get('GOOGLE_MAPS_API_KEY', '')
app.secret_key = os.environ.get('FLASK_SECRET_KEY') or os.environ.get('SECRET_KEY',
                                                                   'default-secret-key-for-development')
ALLOWED_IMAGE_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif'}
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB

# Инициализация Firebase
if not firebase_admin._apps:
    # Для production используйте service account key
    cred = credentials.ApplicationDefault()  # или credentials.Certificate('path/to/serviceAccountKey.json')
    firebase_admin.initialize_app(cred, {
        'storageBucket': FIREBASE_STORAGE_BUCKET
    })

db = firestore.client()
bucket = storage.bucket()


def verify_inbound_token(token_to_verify):
    """Проверка токена для входящих запросов"""
    if not token_to_verify:
        return False
    return token_to_verify == INBOUND_URL_TOKEN



def parse_location_from_subject(subject):
    """Парсинг координат из темы письма в формате lat:XX.XXX,lng:YY.YYY"""
    if not subject:
        return None, None

    # Поиск паттерна lat:XX.XXX,lng:YY.YYY
    pattern = r'lat:([-+]?\d*\.?\d+),lng:([-+]?\d*\.?\d+)'
    match = re.search(pattern, subject, re.IGNORECASE)

    if match:
        try:
            lat = float(match.group(1))
            lng = float(match.group(2))

            # Валидация координат
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                return lat, lng
        except ValueError:
            pass

    return None, None


def upload_image_to_gcs(image_data, filename):
    """Загрузка изображения в Google Cloud Storage"""
    try:
        # Генерация уникального имени файла
        file_extension = filename.split('.')[-1].lower()
        unique_filename = f"content_images/{uuid.uuid4()}.{file_extension}"

        # Создание blob в bucket
        blob = bucket.blob(unique_filename)

        # Загрузка файла
        blob.upload_from_string(
            image_data,
            content_type=f'image/{file_extension}'
        )

        # Делаем файл публично доступным
        blob.make_public()

        return blob.public_url

    except Exception as e:
        print(f"Ошибка при загрузке изображения в GCS: {e}")
        return None


def save_content_to_firestore(data):
    """Сохранение контента в Firestore с дополнительными полями для системы уведомлений."""
    try:
        # Добавляем поля для отслеживания статуса уведомлений
        data['notificationSent'] = False  # Было ли отправлено уведомление о публикации
        data['notificationSentAt'] = None  # Время отправки уведомления

        # Добавляем shortUrl для использования в кратких ссылках (например, base62 от itemId)
        # Это поле будет заполнено после создания документа, когда будет известен ID
        data['shortUrl'] = None

        doc_ref = db.collection('contentItems').document()
        doc_ref.set(data)

        # Теперь, когда у нас есть ID документа, мы можем создать shortUrl
        # Для простоты используем сам ID, но в продакшене можно использовать
        # более короткие идентификаторы или хеши
        doc_ref.update({
            'shortUrl': doc_ref.id  # В будущем здесь можно использовать функцию для генерации короткого URL
        })

        return doc_ref.id
    except Exception as e:
        print(f"Ошибка при сохранении в Firestore: {e}")
        return None


def process_email_attachments(attachments):
    """Обработка вложений письма"""
    if not attachments:
        print("DEBUG: No attachments found in email.")
        return None, None, None

    print(f"DEBUG: Processing {len(attachments)} attachments.")
    for i, attachment in enumerate(attachments):
        content_type = attachment.get('ContentType', '')
        filename = attachment.get('Name', '')
        content = attachment.get('Content', '')  # Base64 encoded

        print(f"DEBUG: Attachment {i + 1}: Name='{filename}', ContentType='{content_type}', HasContent={bool(content)}")

        # Проверяем, что это изображение
        if not content_type.startswith('image/'):
            print(f"DEBUG: Attachment {i + 1} ('{filename}') is not an image (ContentType: {content_type}). Skipping.")
            continue

        # Проверяем расширение файла
        if not filename or '.' not in filename:
            print(f"DEBUG: Attachment {i + 1} ('{filename}') has no extension. Skipping.")
            continue
        file_extension = filename.split('.')[-1].lower()
        if file_extension not in ALLOWED_IMAGE_EXTENSIONS:
            print(f"DEBUG: Attachment {i + 1} ('{filename}') has unsupported extension '{file_extension}'. Skipping.")
            continue

        try:
            # Декодируем base64
            print(f"DEBUG: Attachment {i + 1} ('{filename}'): Attempting to decode Base64 content.")
            image_data = base64.b64decode(content)
            print(f"DEBUG: Attachment {i + 1} ('{filename}'): Decoded. Image data length: {len(image_data)} bytes.")

            # Проверяем размер файла
            if len(image_data) > MAX_IMAGE_SIZE:
                print(
                    f"DEBUG: Файл {filename} слишком большой ({len(image_data)} байт). MAX_IMAGE_SIZE is {MAX_IMAGE_SIZE}. Skipping.")
                continue

            # Извлекаем GPS координаты
            print(f"DEBUG: Attachment {i + 1} ('{filename}'): Extracting EXIF GPS data.")
            lat, lng = extract_gps_coordinates(image_data)
            print(f"DEBUG: Attachment {i + 1} ('{filename}'): EXIF GPS: lat={lat}, lng={lng}")

            # Загружаем в GCS
            print(f"DEBUG: Attachment {i + 1} ('{filename}'): Uploading to GCS.")
            image_url = upload_image_to_gcs(image_data, filename)
            print(f"DEBUG: Attachment {i + 1} ('{filename}'): GCS URL: {image_url}")

            if image_url:
                print(f"DEBUG: Attachment {i + 1} ('{filename}'): Successfully processed. Returning URL: {image_url}")
                return image_url, lat, lng
            else:
                print(
                    f"DEBUG: Attachment {i + 1} ('{filename}'): Failed to upload to GCS or get URL. Continuing to next attachment.")


        except Exception as e:
            print(f"Ошибка при обработке вложения {filename}: {e}")
            import traceback
            traceback.print_exc()  # Печатаем полный traceback для ошибок
            continue

    print("DEBUG: ЗАВЕРШЕНИЕ ЦИКЛА В process_email_attachments. ПЕРЕД ФИНАЛЬНЫМ RETURN.")  # ДОБАВЬТЕ ЭТУ СТРОКУ
    return None, None, None


@app.route('/webhook/postmark', methods=['POST'])
def postmark_webhook():
    token_from_query = request.args.get('token')

    print(f"=== WEBHOOK DEBUG INFO ===")
    print(f"Получен запрос с токеном из query: {token_from_query}")
    print(f"Ожидаемый токен: {INBOUND_URL_TOKEN}")
    print(f"Method: {request.method}")
    print(f"Headers: {dict(request.headers)}")
    print(f"Content-Type: {request.content_type}")
    print(f"Content-Length: {request.content_length}")

    try:
        raw_data = request.get_data()
        print(f"Raw data length: {len(raw_data) if raw_data else 0}")

        data = request.get_json(force=True)
        print(f"JSON data received: {bool(data)}")
        if data:
            print(f"JSON keys: {list(data.keys()) if isinstance(data, dict) else 'Not a dict'}")
    except Exception as e:
        print(f"Error getting request data: {e}")
        return jsonify({
            'status': 'error',
            'message': f'Error parsing request data: {str(e)}'
        }), 400

    if not verify_inbound_token(token_from_query):
        print("Неверный токен в URL query parameter")
        return jsonify({'status': 'error', 'message': 'Invalid token'}), 401

    try:
        if not data:
            print("Не получены JSON данные")
            return jsonify({'status': 'error', 'message': 'No JSON data received'}), 400

        from_email = data.get('FromFull', {}).get('Email', '') if data.get('FromFull') else data.get('From', '')
        subject = data.get('Subject', '')
        text_body = data.get('TextBody', '')
        html_body = data.get('HtmlBody', '')
        attachments = data.get('Attachments', [])

        print(f"Получено письмо от {from_email} с темой: {subject}")
        print(f"Количество вложений: {len(attachments)}")

        image_url, exif_lat, exif_lng = process_email_attachments(attachments)

        if not image_url:
            print("Не найдено подходящих изображений во вложениях")
            return jsonify({'status': 'error', 'message': 'No valid images found'}), 400

        latitude, longitude = exif_lat, exif_lng

        if latitude is None or longitude is None:
            subject_lat, subject_lng = parse_location_from_subject(subject)
            if subject_lat is not None and subject_lng is not None:
                latitude, longitude = subject_lat, subject_lng

        if latitude is None or longitude is None:
            print("Не удалось определить координаты для публикации")
            return jsonify({
                'status': 'error',
                'message': 'Location coordinates not found. Please include GPS data in image or specify in subject as lat:XX.XXX,lng:YY.YYY'
            }), 200

        content_data = {
            'submitterEmail': from_email,
            'text': text_body or html_body,
            'imageUrl': image_url,
            'latitude': latitude,
            'longitude': longitude,
            'timestamp': datetime.utcnow(),
            'status': 'published',
            'voteCount': 0,
            'reportedCount': 0,
            'subject': subject
        }

        content_id = save_content_to_firestore(content_data)

        if content_id:
            print(f"Контент успешно сохранен с ID: {content_id}")

            # Создаем запись о необходимости отправки уведомления
            if from_email:  # Проверяем, что у нас есть адрес отправителя
                notification_id = create_email_notification_record(db, content_id, from_email)
                if notification_id:
                    ok = send_pending_notification(db, notification_id)   # app_context не нужен
                    if ok:
                        print(f'Notification {notification_id} sent')
                else:
                    print(f"Failed to create notification record for content {content_id}")

            return jsonify({
                'status': 'success',
                'contentId': content_id,
                'message': 'Content published successfully'
            })
        else:
            return jsonify({
                'status': 'error',
                'message': 'Failed to save content'
            }), 500

    except Exception as e:
        print(f"Ошибка при обработке веб-хука: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'status': 'error',
            'message': f'Internal server error: {str(e)}'
        }), 500


# --- АДМИНИСТРАТИВНАЯ ПАНЕЛЬ ---

@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        try:
            # Проверка учетных данных администратора
            admin_ref = db.collection('admins').where('email', '==', email).limit(1).get()

            if not admin_ref:
                return render_template('admin/login.html', error='Неверный email или пароль')

            admin_doc = admin_ref[0]
            admin_data = admin_doc.to_dict()

            # Проверка пароля (в реальном проекте использовать хеширование)
            if admin_data.get('password') != password:
                return render_template('admin/login.html', error='Неверный email или пароль')

            # Создаем сессию для администратора
            session['admin_id'] = admin_doc.id
            session['admin_email'] = admin_data.get('email')

            return redirect(url_for('admin_dashboard'))

        except Exception as e:
            print(f"Ошибка при входе администратора: {e}")
            return render_template('admin/login.html', error='Произошла ошибка при входе')

    # Если пользователь уже вошел как админ, перенаправляем на панель
    if 'admin_id' in session:
        return redirect(url_for('admin_dashboard'))

    return render_template('admin/login.html')

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_id', None)
    session.pop('admin_email', None)
    return redirect(url_for('admin_login'))

@app.route('/admin/dashboard')
def admin_dashboard():
    # Проверка доступа администратора
    if 'admin_id' not in session:
        return redirect(url_for('admin_login'))

    status_filter = request.args.get('status', 'for_moderation')

    try:
        items_query = db.collection('contentItems')

        # Применяем фильтр по статусу, если он не 'all'
        if status_filter != 'all':
            items_query = items_query.where('status', '==', status_filter)

        # Сортировка по времени создания (новые в начале)
        items_query = items_query.order_by('timestamp', direction=firestore.Query.DESCENDING)

        # Получаем документы
        items_docs = items_query.get()

        items = []
        for doc in items_docs:
            item_data = doc.to_dict()
            item_data['itemId'] = doc.id

            # Получаем все жалобы для этого элемента
            if status_filter == 'for_moderation' or status_filter == 'all':
                reports_ref = db.collection('reports').where('contentId', '==', doc.id).get()
                item_data['reports'] = [report.to_dict() for report in reports_ref]

            # Добавляем отображаемое имя статуса
            status_map = {
                'published': 'Опубликовано',
                'for_moderation': 'На модерации',
                'rejected': 'Отклонено'
            }
            item_data['status_display'] = status_map.get(item_data.get('status'), item_data.get('status'))

            items.append(item_data)

        # Заголовок секции в зависимости от фильтра
        section_titles = {
            'all': 'Все публикации',
            'for_moderation': 'Публикации на модерации',
            'published': 'Опубликованные публикации',
            'rejected': 'Отклоненные публикации'
        }

        return render_template('admin/dashboard.html', 
                              items=items, 
                              status=status_filter,
                              section_title=section_titles.get(status_filter, 'Публикации'),
                              admin_email=session.get('admin_email'))

    except Exception as e:
        print(f"Ошибка при загрузке панели администратора: {e}")
        import traceback
        traceback.print_exc()
        return render_template('500.html'), 500

@app.route('/admin/api/content/<content_id>/approve', methods=['POST'])
def admin_approve_content(content_id):
    # Проверка доступа администратора
    if 'admin_id' not in session:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    try:
        # Обновляем статус публикации на 'published'
        content_ref = db.collection('contentItems').document(content_id)
        content_ref.update({
            'status': 'published',
            'moderated_by': session.get('admin_id'),
            'moderated_at': firestore.SERVER_TIMESTAMP
        })

        return jsonify({'status': 'success', 'message': 'Публикация одобрена'})

    except Exception as e:
        print(f"Ошибка при одобрении публикации: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

@app.route('/admin/api/content/<content_id>/reject', methods=['POST'])
def admin_reject_content(content_id):
    # Проверка доступа администратора
    if 'admin_id' not in session:
        return jsonify({'status': 'error', 'message': 'Unauthorized'}), 401

    try:
        # Обновляем статус публикации на 'rejected'
        content_ref = db.collection('contentItems').document(content_id)
        content_ref.update({
            'status': 'rejected',
            'moderated_by': session.get('admin_id'),
            'moderated_at': firestore.SERVER_TIMESTAMP
        })

        return jsonify({'status': 'success', 'message': 'Публикация отклонена'})

    except Exception as e:
        print(f"Ошибка при отклонении публикации: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

# Фильтр для форматирования временных меток в шаблонах
@app.template_filter('datetime')
def format_datetime(timestamp):
    if not timestamp:
        return ''

    # Обработка различных типов временных меток Firestore
    if isinstance(timestamp, dict):
        if '_seconds' in timestamp:
            timestamp = datetime.fromtimestamp(timestamp['_seconds'])
        elif 'seconds' in timestamp:
            timestamp = datetime.fromtimestamp(timestamp['seconds'])

    if isinstance(timestamp, datetime):
        return timestamp.strftime('%d.%m.%Y %H:%M')

    return str(timestamp)

# --- ИЗМЕНЕНИЯ НАЧИНАЮТСЯ ЗДЕСЬ ---

@app.route('/')
def home():
    """
    Маршрут для главной страницы, отображающей карту с реальными данными из Firestore.
    """
    items_for_map = []
    try:
        # Запрашиваем все опубликованные элементы из коллекции 'contentItems'
        # Сортируем по убыванию времени для отображения сначала новых (опционально)
        items_query = db.collection('contentItems') \
            .where('status', '==', 'published') \
            .order_by('voteCount', direction=firestore.Query.ASCENDING) \
            .order_by('timestamp', direction=firestore.Query.DESCENDING) \
            .stream()

        for item_doc in items_query:
            item_data = item_doc.to_dict()
            item_data['itemId'] = item_doc.id  # Добавляем ID документа, может пригодиться

            # Убедимся, что есть широта и долгота
            if 'latitude' in item_data and 'longitude' in item_data:
                # Опционально: Преобразуем timestamp в строку, если нужно отображать в InfoWindow
                # if isinstance(item_data.get('timestamp'), datetime):
                #    item_data['timestamp'] = item_data['timestamp'].strftime('%Y-%m-%d %H:%M:%S')
                items_for_map.append(item_data)
            else:
                print(f"DEBUG: Item {item_doc.id} skipped, missing coordinates.")

        print(f"DEBUG: Loaded {len(items_for_map)} items from Firestore for the map.")

    except Exception as e:
        print(f"Ошибка при загрузке данных из Firestore для карты: {e}")
        # Можно передать пустой список или сообщение об ошибке в шаблон
        # items_for_map = []
        # flash('Не удалось загрузить данные для карты.', 'error') # если используете flash сообщения

    return render_template('index.html', items=items_for_map, maps_api_key=GOOGLE_MAPS_API_KEY)


# --- API для взаимодействия с публикациями ---

@app.route('/api/content/<content_id>/vote', methods=['POST'])
def vote_content(content_id):
    """API для голосования за контент (лайк/дизлайк)"""
    print(f"=== VOTE DEBUG INFO ===")
    print(f"Получен запрос на голосование за content_id: {content_id}")
    print(f"Headers: {dict(request.headers)}")
    print(f"Content-Type: {request.content_type}")
    print(f"Content-Length: {request.content_length}")

    try:
        # Получаем данные из запроса
        data = request.get_json()
        print(f"Полученные данные: {data}")

        if not data or 'vote' not in data:
            print(f"Ошибка: отсутствует параметр vote в данных")
            return jsonify({'status': 'error', 'message': 'Missing vote parameter'}), 400

        vote_value = data.get('vote')  # 1 для лайка, -1 для дизлайка
        user_id = data.get('userId') or request.headers.get('X-User-ID')
        print(f"Значение vote: {vote_value}, user_id: {user_id}")

        if not user_id:
            print(f"Ошибка: отсутствует user_id")
            return jsonify({'status': 'error', 'message': 'User ID is required'}), 400

        if vote_value not in [1, -1]:
            print(f"Ошибка: недопустимое значение vote: {vote_value}")
            return jsonify({'status': 'error', 'message': 'Invalid vote value'}), 400

        # Получаем документ из Firestore
        doc_ref = db.collection('contentItems').document(content_id)
        print(f"Запрашиваем документ из Firestore: {content_id}")
        doc = doc_ref.get()

        if not doc.exists:
            print(f"Ошибка: документ не найден в Firestore: {content_id}")
            return jsonify({'status': 'error', 'message': 'Content not found'}), 404

        print(f"Документ найден в Firestore: {content_id}")
        doc_data = doc.to_dict()
        print(f"Данные документа: {doc_data}")

        # Проверяем, не находится ли публикация на модерации
        if doc_data.get('status') == 'for_moderation':
            print(f"Публикация {content_id} находится на модерации, голосование запрещено")
            return jsonify({
                'status': 'error',
                'message': 'Cannot vote for content under moderation'
            }), 403

        # Проверяем, не голосовал ли этот пользователь уже
        voters = doc_data.get('voters', {})
        if user_id in voters:
            previous_vote = voters[user_id]
            print(f"Пользователь {user_id} уже голосовал за публикацию {content_id}, предыдущий голос: {previous_vote}")

            # Если голос такой же, возвращаем ошибку
            if previous_vote == vote_value:
                return jsonify({
                    'status': 'error',
                    'message': 'You have already voted this way',
                    'newVoteCount': doc_data.get('voteCount', 0)
                }), 200

            vote_adjustment = vote_value
        else:
            # Если пользователь голосует впервые, просто добавляем его голос
            vote_adjustment = vote_value

        # Обновляем счетчик голосов
        # Для простоты просто увеличиваем/уменьшаем, в реальном приложении
        # нужно отслеживать IP/пользователей для предотвращения накрутки
        current_votes = doc_data.get('voteCount', 0)
        print(f"Текущее количество голосов: {current_votes}")

        new_vote_count = current_votes + vote_adjustment
        print(f"Новое количество голосов: {new_vote_count}")

        try:
            # Сохраняем информацию о пользователе и его голосе
            voters_update = {f'voters.{user_id}': vote_value}

            # Записываем историю голосования
            vote_history = {
                'userId': user_id,
                'value': vote_value,
                'timestamp': datetime.utcnow(),
                'isAnonymous': True
            }

            doc_ref.update({
                'voteCount': new_vote_count,
                **voters_update,
                'voteHistory': firestore.ArrayUnion([vote_history])
            })
            print(f"Обновление документа успешно выполнено")
        except Exception as e:
            print(f"Ошибка при обновлении документа: {e}")
            return jsonify({'status': 'error', 'message': f'Error updating vote count: {str(e)}'}), 500

        return jsonify({
            'status': 'success',
            'message': 'Vote recorded',
            'newVoteCount': new_vote_count
        })

    except Exception as e:
        print(f"Ошибка при голосовании за контент {content_id}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


@app.route('/api/content/<content_id>/report', methods=['POST'])
def report_content(content_id):
    """API для жалобы на контент"""
    try:
        # Получаем данные из запроса
        data = request.get_json()
        reason = data.get('reason', 'Не указана')
        user_id = data.get('userId') or request.headers.get('X-User-ID')

        if not user_id:
            return jsonify({'status': 'error', 'message': 'User ID is required'}), 400

        # Получаем документ из Firestore
        doc_ref = db.collection('contentItems').document(content_id)
        doc = doc_ref.get()

        if not doc.exists:
            return jsonify({'status': 'error', 'message': 'Content not found'}), 404

        # Проверяем, не находится ли публикация уже на модерации
        doc_data = doc.to_dict()
        if doc_data.get('status') == 'for_moderation':
            return jsonify({
                'status': 'error',
                'message': 'This content is already under moderation'
            }), 403

        # Проверяем, не жаловался ли этот пользователь уже
        reports = doc_data.get('reports', [])
        reporters = [report.get('userId') for report in reports if 'userId' in report]

        if user_id in reporters:
            return jsonify({
                'status': 'error',
                'message': 'You have already reported this content'
            }), 200

        # Увеличиваем счетчик жалоб
        doc_data = doc.to_dict()
        current_reports = doc_data.get('reportedCount', 0)

        # Создаем объект жалобы с информацией о пользователе
        report_data = {
            'reason': reason,
            'timestamp': datetime.utcnow(),
            'userId': user_id,
            'isAnonymous': True  # Помечаем как анонимную жалобу
        }

        # Обновляем документ
        doc_ref.update({
            'reportedCount': current_reports + 1,
            'reports': firestore.ArrayUnion([report_data]),
            'reporters': firestore.ArrayUnion([user_id])  # Сохраняем список пользователей, отправивших жалобы
        })

        # Если количество жалоб >= 3, помечаем контент как требующий модерации
        if current_reports + 1 >= 3 and doc_data.get('status') == 'published':
            print(f"Публикация {content_id} достигла {current_reports + 1} жалоб, переводим в статус for_moderation")
            try:
                doc_ref.update({
                    'status': 'for_moderation',
                    'moderation_note': f'Автоматически отправлено на модерацию ({current_reports + 1} жалоб)',
                    'moderation_timestamp': datetime.utcnow()
                })
                print(f"Статус публикации {content_id} успешно изменен на for_moderation")
            except Exception as e:
                print(f"Ошибка при изменении статуса публикации {content_id}: {e}")

        return jsonify({
            'status': 'success',
            'message': 'Report submitted'
        })

    except Exception as e:
        print(f"Ошибка при отправке жалобы на контент {content_id}: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500

        @app.route('/api/content/create', methods=['POST'])
        def create_content():
            try:
                # Получаем параметры из запроса
                text = request.form.get('text', '')
                latitude = float(request.form.get('latitude'))
                longitude = float(request.form.get('longitude'))
                user_id = request.form.get('userId') or request.headers.get('X-User-ID')

                if not user_id:
                    return jsonify({'status': 'error', 'message': 'User ID is required'}), 400

                if not latitude or not longitude:
                    return jsonify({'status': 'error', 'message': 'Location coordinates are required'}), 400

                # Проверяем, есть ли изображение в запросе
                image_url = None
                if 'image' in request.files:
                    image = request.files['image']
                    if image.filename != '':
                        # Генерируем уникальное имя файла
                        filename = secure_filename(image.filename)
                        file_extension = os.path.splitext(filename)[1]
                        unique_filename = f"{str(uuid.uuid4())}{file_extension}"

                        # Создаем временный файл для загрузки
                        with tempfile.NamedTemporaryFile(delete=False) as temp:
                            image.save(temp.name)

                            # Загружаем файл в Firebase Storage
                            bucket = storage.bucket()
                            blob = bucket.blob(f"content_images/{unique_filename}")
                            blob.upload_from_filename(temp.name)

                            # Делаем файл публичным
                            blob.make_public()

                            # Получаем URL изображения
                            image_url = blob.public_url

                        # Удаляем временный файл
                        os.unlink(temp.name)

                # Создаем новую запись в Firestore
                new_content = {
                    'text': text,
                    'imageUrl': image_url,
                    'latitude': latitude,
                    'longitude': longitude,
                    'timestamp': datetime.utcnow(),
                    'userId': user_id,
                    'isAnonymous': True,
                    'voteCount': 0,
                    'reportedCount': 0,
                    'status': 'published'  # Начальный статус - опубликовано
                }

                # Добавляем документ в коллекцию
                doc_ref = db.collection('contentItems').document()
                doc_ref.set(new_content)

                # Обновляем id документа
                doc_ref.update({
                    'itemId': doc_ref.id
                })

                return jsonify(dict(status='success', message='Content created successfully', contentId=doc_ref.id))
            except Exception as e:
                print(f"Ошибка при создании контента: {e}")

        return jsonify({'status': 'error', 'message': str(e)}), 500


# --- КОНЕЦ API для взаимодействия с публикациями ---

@app.route('/post/<item_id>')
def post_view(item_id):
    """
    Маршрут для просмотра конкретной публикации.
    Карта центрируется на соответствующем маркере и маркер автоматически открывается.
    """
    # Получаем все опубликованные элементы для карты
    items_for_map = []
    try:
        # Запрашиваем все опубликованные элементы (такой же запрос, как в home())
        items_query = db.collection('contentItems') \
            .where('status', '==', 'published') \
            .order_by('voteCount', direction=firestore.Query.ASCENDING) \
            .order_by('timestamp', direction=firestore.Query.DESCENDING) \
            .stream()

        for item_doc in items_query:
            item_data = item_doc.to_dict()
            item_data['itemId'] = item_doc.id
            if 'latitude' in item_data and 'longitude' in item_data:
                items_for_map.append(item_data)
    except Exception as e:
        print(f"Ошибка при загрузке данных из Firestore для карты: {e}")

    # Получаем данные целевой публикации для SEO и метаданных
    target_item_data = None
    try:
        doc_ref = db.collection('contentItems').document(item_id)
        doc = doc_ref.get()
        if doc.exists:
            target_item_data = doc.to_dict()
            # Не забываем добавить ID, так как он не входит в данные документа
            target_item_data['itemId'] = item_id
    except Exception as e:
        print(f"Ошибка при получении данных публикации {item_id}: {e}")

    # Передаем в шаблон все элементы для карты, ID целевого элемента и данные целевого элемента для SEO
    return render_template(
        'index.html',
        items=items_for_map,
        target_item_id=item_id,
        target_item_data=target_item_data,
        maps_api_key=GOOGLE_MAPS_API_KEY
    )


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)), debug=True)