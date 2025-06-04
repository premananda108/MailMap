# email_utils.py
import os
from datetime import datetime
from firebase_admin import firestore
# import requests # Больше не нужен для отправки, если используем SMTP

# --- НОВЫЕ ИМПОРТЫ для SMTP ---
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header  # Для корректной обработки не-ASCII символов в теме
from email.utils import formataddr  # Для форматирования From/To с именами
# --- КОНЕЦ НОВЫХ ИМПОРТОВ ---

from flask import render_template

POSTMARK_SERVER_TOKEN = os.environ.get("POSTMARK_SERVER_TOKEN", "YOUR_POSTMARK_SERVER_TOKEN_HERE")
SENDER_EMAIL_ADDRESS = os.environ.get("SENDER_EMAIL_ADDRESS", "noreply@example.com")
SENDER_NAME = os.environ.get("SENDER_NAME", "MailMap")  # Опционально: имя отправителя
BASE_URL = os.environ.get("BASE_URL", "https://399c-37-54-223-113.ngrok-free.app")

# SMTP Конфигурация Postmark
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.postmarkapp.com")
SMTP_PORT = os.environ.get("SMTP_PORT", "587")  # Рекомендуемый порт для TLS/STARTTLS
SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")


def create_email_notification_record(db_client, content_id, recipient_email):
    # ... (эта функция остается без изменений) ...
    try:
        if not all([db_client, content_id, recipient_email]):
            print("Ошибка в create_email_notification_record: Отсутствуют обязательные параметры")
            return None
        notification_data = {
            'contentId': content_id,
            'recipientEmail': recipient_email,
            'status': 'pending',
            'createdAt': datetime.utcnow(),
            'updatedAt': datetime.utcnow(),
            'attempts': 0,
            'lastAttemptAt': None,
            'lastError': None,
            'type': 'content_published',
            'metadata': {
                'contentId': content_id,
                'recipientEmail': recipient_email
            }
        }
        doc_ref = db_client.collection('emailNotifications').document()
        doc_ref.set(notification_data)
        print(f"DEBUG: Создана запись об email-уведомлении: {doc_ref.id} для {recipient_email}")
        return doc_ref.id
    except Exception as e:
        print(f"Ошибка в create_email_notification_record: {str(e)}")
        import traceback
        traceback.print_exc()
        return None


def send_pending_notification(db_client, notification_id, app_context=None):
    notification_ref = db_client.collection('emailNotifications').document(notification_id)
    notification_doc = None
    try:
        notification_doc = notification_ref.get()
        if not notification_doc.exists:
            print(f"Ошибка: Запись уведомления {notification_id} не найдена.")
            return False

        notification_data = notification_doc.to_dict()
        STATUS_PENDING = 'pending'
        STATUS_SENT = 'sent'
        STATUS_FAILED = 'failed'
        # ...
        if notification_data.get('status') != STATUS_PENDING:
            print(
                f"Уведомление {notification_id} не ожидает отправки (статус: {notification_data.get('status')}). Пропуск.")
            return True

        content_id = notification_data.get('contentId')
        recipient_email = notification_data.get('recipientEmail')

        if not content_id or not recipient_email:
            # ... (обработка ошибки остается) ...
            error_msg = f"Уведомление {notification_id} не содержит contentId или recipientEmail."
            print(f"Ошибка: {error_msg}")
            notification_ref.update({
                'status': 'failed', 'lastError': error_msg, 'updatedAt': datetime.utcnow(),
                'lastAttemptAt': datetime.utcnow(), 'attempts': firestore.Increment(1)
            })
            return False

        content_ref = db_client.collection('contentItems').document(content_id)
        content_doc = content_ref.get()
        if not content_doc.exists:
            # ... (обработка ошибки остается) ...
            error_msg = f"Элемент контента {content_id} для уведомления {notification_id} не найден."
            print(f"Ошибка: {error_msg}")
            notification_ref.update({
                'status': 'failed', 'lastError': error_msg, 'updatedAt': datetime.utcnow(),
                'lastAttemptAt': datetime.utcnow(), 'attempts': firestore.Increment(1)
            })
            return False

        content_data = content_doc.to_dict()
        post_url = f"{BASE_URL}/post/{content_id}"
        original_subject_text = content_data.get('subject', 'Ваш контент опубликован!')
        image_url = content_data.get('imageUrl')
        text_from_content = content_data.get('text', '')
        latitude = content_data.get('latitude')
        longitude = content_data.get('longitude')

        email_subject_text = f"Ваша публикация на MailMap: \"{original_subject_text}\" размещена!"

        text_body = (
            f"Здравствуйте,\n\n"
            f"Ваша публикация \"{original_subject_text}\" успешно размещена на MailMap.\n"
            f"Текст: {text_from_content}\n"
            f"Координаты: {latitude}, {longitude}\n"
            f"Просмотреть: {post_url}\n\n"
            f"С уважением, команда MailMap"
        )

        html_body = None
        template_context = {
            'text_content': text_from_content, 'image_url': image_url,
            'latitude': latitude, 'longitude': longitude, 'post_url': post_url,
            'subject_title': original_subject_text
        }

        html_body = None  # Инициализируем на случай, если что-то пойдет не так

        try:
            if app_context:
                # Если app_context предоставлен (например, из фоновой задачи),
                # используем его для рендеринга шаблона.
                with app_context:
                    html_body = render_template('email_notification.html', **template_context)
            else:
                # Если app_context не предоставлен (например, вызов из view-функции Flask),
                # render_template попытается найти существующий контекст приложения.
                # Если контекста нет, здесь возникнет RuntimeError.
                html_body = render_template('email_notification.html', **template_context)

        except RuntimeError as e:
            # Эта ошибка возникает, если render_template вызывается без активного контекста Flask
            # (и app_context не был предоставлен или не сработал).
            if "Working outside of application context" in str(e):
                print(
                    "Информация: Рендеринг шаблона вне/без активного контекста приложения Flask. Используется текстовый fallback.")
                html_body = f"<p>{text_body.replace(chr(10), '<br>')}</p>"  # Используем простой HTML из текстового тела
            else:
                # Если это другой RuntimeError, не связанный с отсутствием контекста,
                # лучше его перевыбросить, чтобы не скрыть другую проблему.
                raise e
        except Exception as e:
            # Ловим другие возможные ошибки при рендеринге (например, TemplateNotFound, если шаблон не найден)
            print(f"Ошибка при рендеринге шаблона 'email_notification.html': {e}. Используется текстовый fallback.")
            html_body = f"<p>{text_body.replace(chr(10), '<br>')}</p>"

        # Дополнительная проверка на случай, если html_body по какой-то причине остался None
        # (например, если render_template вернул None, хотя обычно он вызывает исключение при ошибке)
        if html_body is None:
            print("ПРЕДУПРЕЖДЕНИЕ: html_body не был сгенерирован (остался None). Используется текстовый fallback.")
            html_body = f"<p>{text_body.replace(chr(10), '<br>')}</p>"

        print(f"Попытка отправки email (SMTP) для уведомления {notification_id} на адрес {recipient_email}")

        if POSTMARK_SERVER_TOKEN == "YOUR_POSTMARK_SERVER_TOKEN_HERE" or not POSTMARK_SERVER_TOKEN:
            print(
                "ПРЕДУПРЕЖДЕНИЕ: Серверный токен Postmark (SMTP_USERNAME/PASSWORD) не настроен. Email не будет отправлен.")
            raise Exception("Серверный токен Postmark (SMTP_USERNAME/PASSWORD) не настроен.")

        # --- НОВАЯ ЛОГИКА ОТПРАВКИ EMAIL через SMTP ---
        msg = MIMEMultipart('alternative')
        # Используем formataddr для правильного отображения имени отправителя, если оно есть
        msg['From'] = formataddr((str(Header(SENDER_NAME, 'utf-8')), SENDER_EMAIL_ADDRESS))
        msg['To'] = recipient_email
        # Используем Header для корректной обработки не-ASCII символов в теме
        msg['Subject'] = Header(email_subject_text, 'utf-8')

        # Прикрепляем текстовую и HTML версии
        # Важно: сначала текстовая, потом HTML
        part1 = MIMEText(text_body, 'plain', 'utf-8')
        part2 = MIMEText(html_body, 'html', 'utf-8')

        msg.attach(part1)
        msg.attach(part2)

        smtp_error = None
        try:
            # Подключение к SMTP серверу Postmark
            server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
            server.ehlo()  # Приветствие серверу
            server.starttls()  # Включение TLS шифрования
            server.ehlo()  # Повторное приветствие после STARTTLS
            server.login(SMTP_USERNAME, SMTP_PASSWORD)  # Аутентификация
            server.sendmail(SENDER_EMAIL_ADDRESS, [recipient_email], msg.as_string())  # Отправка письма
            server.quit()  # Закрытие соединения
            print(f"Email (SMTP) для уведомления {notification_id} успешно отправлен на {recipient_email}.")
            email_sent_status = True
        except smtplib.SMTPException as e:  # Ловим специфичные ошибки SMTP
            smtp_error = f"Ошибка SMTP: {str(e)}"
            print(f"Ошибка отправки email (SMTP) для уведомления {notification_id}: {smtp_error}")
            email_sent_status = False
        except Exception as e:  # Ловим другие возможные ошибки (например, сетевые)
            smtp_error = f"Общая ошибка при отправке SMTP: {str(e)}"
            print(f"Ошибка отправки email (SMTP) для уведомления {notification_id}: {smtp_error}")
            email_sent_status = False
        # --- КОНЕЦ НОВОЙ ЛОГИКИ SMTP ---

        current_time = datetime.utcnow()
        if email_sent_status:
            notification_ref.update({
                'status': 'sent', 'updatedAt': current_time, 'lastAttemptAt': current_time,
                'attempts': firestore.Increment(1), 'lastError': None
            })
            return True
        else:
            notification_ref.update({
                'status': 'failed', 'lastError': smtp_error or "Неизвестная ошибка SMTP",
                'updatedAt': current_time, 'lastAttemptAt': current_time,
                'attempts': firestore.Increment(1)
            })
            return False

    except Exception as e:
        # ... (обработка критических ошибок остается) ...
        error_str = str(e)
        print(f"Критическая ошибка в send_pending_notification для {notification_id}: {error_str}")
        import traceback
        traceback.print_exc()
        try:
            if notification_doc and notification_doc.exists:
                notification_ref.update({
                    'status': 'failed', 'lastError': error_str, 'updatedAt': datetime.utcnow(),
                    'lastAttemptAt': datetime.utcnow(), 'attempts': firestore.Increment(1)
                })
        except Exception as inner_e:
            print(f"Не удалось обновить статус уведомления {notification_id} после критической ошибки: {inner_e}")
        return False