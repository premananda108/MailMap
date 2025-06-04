#!/usr/bin/env python3

"""
Скрипт для создания администратора в Firestore.
Запустите этот скрипт один раз для создания первого администратора.

Пример использования:
    python admin_setup.py admin@example.com your_secure_password
"""

import sys
import firebase_admin
from firebase_admin import credentials, firestore

def create_admin(email, password):
    # Инициализация Firebase Admin SDK
    try:
        firebase_admin.get_app()
    except ValueError:
        # Используем учетные данные по умолчанию или из переменной окружения
        firebase_admin.initialize_app()

    db = firestore.client()

    # Проверяем, существует ли уже администратор с таким email
    existing_admin = db.collection('admins').where('email', '==', email).get()

    if existing_admin:
        print(f"Администратор с email {email} уже существует.")
        return False

    # Создаем нового администратора
    admin_data = {
        'email': email,
        'password': password,  # В реальном приложении следует хешировать пароль
        'created_at': firestore.SERVER_TIMESTAMP
    }

    db.collection('admins').add(admin_data)
    print(f"Администратор {email} успешно создан!")
    print("ВАЖНО: В производственной среде следует использовать хеширование паролей.")
    return True

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Использование: python admin_setup.py email password")
        sys.exit(1)

    email = sys.argv[1]
    password = sys.argv[2]

    create_admin(email, password)
