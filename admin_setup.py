#!/usr/bin/env python3

"""
Script to create an administrator in Firestore.
Run this script once to create the first administrator.

Usage example:
    python admin_setup.py admin@example.com your_secure_password
"""

import sys
import firebase_admin
from firebase_admin import credentials, firestore

def create_admin(email, password):
    # Initialize Firebase Admin SDK
    try:
        firebase_admin.get_app()
    except ValueError:
        # Use default credentials or from environment variable
        firebase_admin.initialize_app()

    db = firestore.client()

    # Check if an administrator with this email already exists
    existing_admin = db.collection('admins').where('email', '==', email).get()

    if existing_admin:
        print(f"Administrator with email {email} already exists.")
        return False

    # Create a new administrator
    admin_data = {
        'email': email,
        'password': password,  # In a real application, the password should be hashed
        'created_at': firestore.SERVER_TIMESTAMP
    }

    db.collection('admins').add(admin_data)
    print(f"Administrator {email} created successfully!")
    print("IMPORTANT: In a production environment, password hashing should be used.")
    return True

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python admin_setup.py email password")
        sys.exit(1)

    email = sys.argv[1]
    password = sys.argv[2]

    create_admin(email, password)
