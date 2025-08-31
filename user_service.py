import firebase_admin
from firebase_admin import auth, firestore
from firebase_admin.auth import generate_email_verification_link # Added for email verification
import logging # It's good practice to use the logging module
from flask import current_app # Added for app_context

# Assuming firestore_utils.py is in the same directory or accessible in PYTHONPATH
import firestore_utils
# Assuming email_utils.py is in the same directory or accessible in PYTHONPATH
from email_utils import send_verification_email # Added for email verification

class UserService:
    def __init__(self, app_logger=None):
        self.logger = app_logger if app_logger else logging.getLogger(__name__)
        self.db = firestore.client()

    def register_user_with_email_password(self, email, display_name, password):
        """
        Registers a new user with email, display name, and password.
        Creates user in Firebase Auth and then in Firestore.
        """
        try:
            user_record = auth.create_user(
                email=email,
                password=password,
                display_name=display_name,
                email_verified=False # Set email_verified to False initially
            )
            self.logger.info(f"User created in Firebase Auth: {user_record.uid} with email_verified=False")

            # Now create user in Firestore
            # Provider will be 'password' for email/password sign-ups
            # Ensure the user_data passed to Firestore reflects the auth record if needed,
            # though firestore_utils.create_user might not use email_verified directly.
            # The primary source of truth for email_verified is Firebase Auth.
            user_data = firestore_utils.create_user(
                uid=user_record.uid,
                email=user_record.email, # Use email from user_record
                display_name=user_record.display_name, # Use display_name from user_record
                provider='password',
                app_logger=self.logger
                # If firestore_utils.create_user were to store email_verified,
                # you could pass user_record.email_verified here.
            )

            if user_data:
                self.logger.info(f"User {user_record.uid} created in Firestore.")

                # Send verification email
                try:
                    # Generate the email verification link using Firebase Admin SDK, with UID
                    link = generate_email_verification_link(email)

                    app_ctx = None
                    if current_app:
                        app_ctx = current_app.app_context()

                    email_sent = send_verification_email(email, link, app_context=app_ctx)
                    if email_sent:
                        self.logger.info(f"Verification email queued for {email}.")
                        return {
                            'status': 'success',
                            'user': user_data,
                            'message': 'Registration successful. Please check your email to verify your account.'
                        }
                    else:
                        self.logger.error(f"Failed to send verification email to {email}, but user was created.")
                        return {
                            'status': 'success',
                            'user': user_data,
                            'message': 'Registration successful. Failed to send verification email; please request a new one later.'
                        }
                except Exception as e_email:
                    self.logger.error(f"Error during email verification process for {email}: {e_email}", exc_info=True)
                    # Still return success for registration, as user can verify later
                    return {
                        'status': 'success',
                        'user': user_data,
                        'message': 'Registration successful. An error occurred while sending the verification email.'
                    }
            else:
                # This case might indicate an issue with Firestore user creation
                # after Firebase Auth succeeded. Potentially needs cleanup in Auth.
                self.logger.error(f"Failed to create user {user_record.uid} in Firestore after Auth creation.")
                # Attempt to delete the Firebase Auth user to avoid orphaned auth record
                try:
                    auth.delete_user(user_record.uid)
                    self.logger.info(f"Cleaned up Firebase Auth user {user_record.uid} due to Firestore creation failure.")
                except Exception as e_auth_delete:
                    self.logger.error(f"Failed to cleanup Firebase Auth user {user_record.uid}: {e_auth_delete}")
                return {'status': 'error', 'message': 'User registration failed at database stage.'}

        except firebase_admin.auth.EmailAlreadyExistsError:
            self.logger.warning(f"Registration attempt with existing email: {email}")
            return {'status': 'error', 'message': 'Email already exists.'}
        except Exception as e:
            self.logger.error(f"Error registering user {email}: {e}", exc_info=True)
            return {'status': 'error', 'message': f'An unexpected error occurred: {str(e)}'}

    def login_user_with_email_password(self, email, password):
        """
        Placeholder for email/password login.
        Direct server-side password verification is not standard with Firebase Admin SDK.
        Client SDK handles this and sends ID token.
        """
        self.logger.info(f"Attempt to login with email/password for {email} (server-side).")
        self.logger.warning("Direct server-side email/password login is not implemented. "
                            "Client SDK should handle this and send an ID token. "
                            "This method is a placeholder for potential Firebase REST API password sign-in logic.")
        # In a real scenario with REST API, you would make an HTTP request here.
        # For now, returning a message indicating it's not implemented.
        return {
            'status': 'not_implemented',
            'message': 'Server-side email/password login is not implemented. Use ID token login.'
        }

    def login_user_with_id_token(self, id_token):
        """
        Login user with id_token (renamed from login_user).
        If user exists in db, return user.
        Else, create user in db and return user.
        Returns a dictionary with status and user_data or error message.
        """
        try:
            decoded_token = auth.verify_id_token(id_token)
            uid = decoded_token['uid']

            # Check email verification status
            email_verified = decoded_token.get('email_verified', False)
            if not email_verified:
                provider = decoded_token.get('firebase', {}).get('sign_in_provider', 'unknown')
                self.logger.warning(f"Login attempt by user {uid} with unverified email. Provider: {provider}.")
                return {'status': 'error', 'message': 'Email not verified. Please check your inbox and click the verification link.'}

            user_data = firestore_utils.get_user(uid, self.logger)

            if user_data:
                self.logger.info(f"User found in Firestore: {uid}")
                # Ensure subscription fields are initialized if missing (for older users)
                updated_user = self._ensure_subscription_fields(user_data, uid)
                return {'status': 'success', 'user': updated_user}
            else:
                self.logger.info(f"User not found in Firestore, creating new user: {uid}")
                email = decoded_token.get('email')
                display_name = decoded_token.get('name') or decoded_token.get('displayName') or email
                provider = decoded_token.get('firebase', {}).get('sign_in_provider', 'unknown')

                if provider == 'unknown':
                     self.logger.warning(f"Sign-in provider not found in token for user {uid}. Setting to 'unknown'.")


                new_user = firestore_utils.create_user(uid, email, display_name, provider, self.logger)

                if new_user:
                    self.logger.info(f'User created successfully: {uid}')
                    # New users from create_user will have subscription fields by default.
                    return {'status': 'success', 'user': new_user}
                else:
                    self.logger.error(f'Failed to create user: {uid} in Firestore.')
                    return {'status': 'error', 'message': f'Failed to create user data in Firestore for {uid}'}

        except firebase_admin.auth.InvalidIdTokenError as e:
            self.logger.error(f'Invalid ID token: {e}')
            return {'status': 'error', 'message': 'Invalid ID token.'}
        except Exception as e:
            self.logger.error(f'Error logging in user with ID token: {e}', exc_info=True)
            return {'status': 'error', 'message': f'An unexpected error occurred: {str(e)}'}

    def _ensure_subscription_fields(self, user_data, uid):
        """Helper to ensure subscription fields exist and have defaults."""
        changed = False
        if 'subscription_plan' not in user_data:
            user_data['subscription_plan'] = 'free'
            changed = True
        if 'subscription_status' not in user_data:
            user_data['subscription_status'] = 'free_tier'
            changed = True
        # Add other fields as created in firestore_utils.create_user if necessary
        if 'photo_upload_count_current_month' not in user_data:
            user_data['photo_upload_count_current_month'] = 0
            changed = True
        if 'current_period_start' not in user_data: # This might need a proper date
            user_data['current_period_start'] = firestore.SERVER_TIMESTAMP
            changed = True
        if 'current_period_end' not in user_data: # This might need a proper date
            user_data['current_period_end'] = firestore.SERVER_TIMESTAMP
            changed = True
        if 'customer_id' not in user_data:
            user_data['customer_id'] = None
            changed = True
        if 'subscription_id' not in user_data:
            user_data['subscription_id'] = None
            changed = True

        if changed:
            try:
                user_ref = self.db.collection('users').document(uid)
                user_ref.set(user_data, merge=True) # Use set with merge=True to update or create if not exist
                self.logger.info(f"Updated missing subscription fields for user {uid}")
            except Exception as e:
                self.logger.error(f"Error updating user {uid} with default subscription fields: {e}", exc_info=True)
                # Return original user_data, as update failed
        return user_data


    def handle_google_signin(self, id_token):
        """
        Handles user sign-in via Google ID token.
        Verifies token, fetches or creates user in Firestore, handles account merging.
        """
        try:
            decoded_token = auth.verify_id_token(id_token)
            google_uid = decoded_token['uid']
            email = decoded_token.get('email')
            display_name = decoded_token.get('name') or decoded_token.get('displayName') or email
            provider = 'google.com' # Standard provider ID for Google

            # 1. Try to fetch user by Google UID
            user_by_uid = firestore_utils.get_user(google_uid, self.logger)

            if user_by_uid:
                self.logger.info(f"Google sign-in: User found by UID {google_uid}.")
                # Update details if necessary (e.g., name change in Google)
                update_data = {}
                if user_by_uid.get('displayName') != display_name:
                    update_data['displayName'] = display_name
                if user_by_uid.get('email') != email: # Should ideally not happen if UID is same
                    update_data['email'] = email
                if user_by_uid.get('provider') != provider:
                    update_data['provider'] = provider

                final_user_data = self._ensure_subscription_fields(user_by_uid, google_uid)

                if update_data:
                    try:
                        user_ref = self.db.collection('users').document(google_uid)
                        user_ref.update(update_data)
                        self.logger.info(f"User {google_uid} details updated from Google token.")
                        # Apply updates to the user_data to be returned
                        for k, v in update_data.items():
                            final_user_data[k] = v
                    except Exception as e:
                        self.logger.error(f"Error updating user {google_uid} details: {e}", exc_info=True)
                        # Continue with existing user_data despite update failure

                return {'status': 'success', 'user': final_user_data}

            # 2. If not found by UID, try to fetch by email (account merge scenario)
            self.logger.info(f"Google sign-in: User not found by UID {google_uid}. Trying email {email}.")
            user_by_email = firestore_utils.get_user_by_email(email, self.logger)

            if user_by_email:
                self.logger.info(f"Google sign-in: User found by email {email} with existing UID {user_by_email['uid']}. Merging.")
                old_user_uid = user_by_email['uid']

                # If old_user_uid is the same as google_uid, something is inconsistent with the first check.
                # This case should ideally not be hit if get_user(google_uid) failed.
                # However, if it does, treat as a simple update.
                if old_user_uid == google_uid:
                    self.logger.warning(f"User {google_uid} found by email, and UID matches. Should have been found by UID earlier. Proceeding with update.")
                    # This is essentially the same logic as the `if user_by_uid:` block
                    update_data = {'displayName': display_name, 'provider': provider}
                    final_user_data = self._ensure_subscription_fields(user_by_email, google_uid)
                    try:
                        user_ref = self.db.collection('users').document(google_uid)
                        user_ref.update(update_data)
                        self.logger.info(f"User {google_uid} details updated (merge scenario, UID matched).")
                        for k,v in update_data.items(): final_user_data[k] = v
                    except Exception as e:
                        self.logger.error(f"Error updating user {google_uid} in merge (UID matched): {e}")
                    return {'status': 'success', 'user': final_user_data}

                # Account merge: Existing user (old_user_uid) needs to be linked to new Google Auth (google_uid).
                # Strategy: Create new user record with google_uid, migrate data, delete old.

                # Create the new user record with Google UID and details
                # Ensure all data from user_by_email is carried over if not in token
                # and default fields are present.
                new_user_firestore_data = {
                    'uid': google_uid,
                    'email': email, # From token, should match user_by_email
                    'displayName': display_name, # From token
                    'provider': provider, # 'google.com'
                    # Carry over subscription details and other important fields from user_by_email
                    'subscription_plan': user_by_email.get('subscription_plan', 'free'),
                    'subscription_status': user_by_email.get('subscription_status', 'free_tier'),
                    'photo_upload_count_current_month': user_by_email.get('photo_upload_count_current_month', 0),
                    'current_period_start': user_by_email.get('current_period_start') or firestore.SERVER_TIMESTAMP,
                    'current_period_end': user_by_email.get('current_period_end') or firestore.SERVER_TIMESTAMP,
                    'customer_id': user_by_email.get('customer_id'),
                    'subscription_id': user_by_email.get('subscription_id'),
                    'createdAt': user_by_email.get('createdAt'), # Preserve original creation if possible
                }
                # If createdAt is not available or needs to be set for the new record specifically
                if not new_user_firestore_data['createdAt']:
                    new_user_firestore_data['createdAt'] = firestore.SERVER_TIMESTAMP


                # Use firestore_utils.create_user to set the new record.
                # It might be better to directly set new_user_firestore_data if create_user has side effects
                # or defaults that conflict with merging. For now, let's try direct set.
                try:
                    self.db.collection('users').document(google_uid).set(new_user_firestore_data)
                    self.logger.info(f"New user record created for {google_uid} during merge.")
                except Exception as e_create:
                    self.logger.error(f"Failed to create new user record for {google_uid} during merge: {e_create}", exc_info=True)
                    return {'status': 'error', 'message': 'Failed to create user during account merge.'}

                # Migrate content
                migrated = firestore_utils.migrate_content_ownership(old_user_uid, google_uid, self.logger)
                if not migrated:
                    # This is a critical issue. The new user record was created, but content migration failed.
                    # Potentially rollback new user creation or flag for manual intervention.
                    self.logger.error(f"Content migration failed from {old_user_uid} to {google_uid}. Manual check needed.")
                    # Returning error, but state is inconsistent.
                    return {'status': 'error', 'message': 'Content migration failed during account merge.'}

                # Delete old user record
                try:
                    self.db.collection('users').document(old_user_uid).delete()
                    self.logger.info(f"Old user record {old_user_uid} deleted after merge.")
                except Exception as e_delete:
                    self.logger.error(f"Failed to delete old user record {old_user_uid} after merge: {e_delete}", exc_info=True)
                    # This is not ideal, but the primary goal (new user active, content migrated) is done.
                    # Log and continue.

                return {'status': 'success', 'user': new_user_firestore_data}

            # 3. New Google user (not found by UID or email)
            self.logger.info(f"Google sign-in: New user. Creating user for UID {google_uid}, email {email}.")
            new_user_data = firestore_utils.create_user(
                uid=google_uid,
                email=email,
                display_name=display_name,
                provider=provider,
                app_logger=self.logger
            )

            if new_user_data:
                self.logger.info(f"New Google user created successfully: {google_uid}")
                return {'status': 'success', 'user': new_user_data}
            else:
                self.logger.error(f"Failed to create new Google user {google_uid} in Firestore.")
                return {'status': 'error', 'message': 'Failed to create new user in Firestore.'}

        except firebase_admin.auth.InvalidIdTokenError as e:
            self.logger.error(f'Google sign-in: Invalid ID token: {e}')
            return {'status': 'error', 'message': 'Invalid ID token.'}
        except Exception as e:
            self.logger.error(f'Error in handle_google_signin: {e}', exc_info=True)
            return {'status': 'error', 'message': f'An unexpected error occurred: {str(e)}'}


    def handle_apple_signin(self, id_token):
        """
        Handles user sign-in via Apple ID token.
        Verifies token, fetches or creates user in Firestore, handles account merging.
        """
        try:
            decoded_token = auth.verify_id_token(id_token)
            apple_uid = decoded_token['uid']
            email = decoded_token.get('email') # This might be a private relay email
            # Firebase populates 'name' from Apple token if 'name' scope was requested during client auth
            display_name = decoded_token.get('name')
            if not display_name and email: # Fallback to generating from email if name not provided
                display_name = email.split('@')[0]
            elif not display_name: # If email is also not available (e.g. private relay and no name scope)
                display_name = 'User'

            provider = 'apple.com'
            self.logger.info(f"Attempting Apple Sign-In for UID: {apple_uid}, Email: {email if email else 'Not Provided'}")

            # 1. Try to fetch user by Apple UID
            user_by_uid = firestore_utils.get_user(apple_uid, self.logger)

            if user_by_uid:
                self.logger.info(f"Apple sign-in: User found by UID {apple_uid}.")
                update_data = {}
                if user_by_uid.get('displayName') != display_name:
                    update_data['displayName'] = display_name
                # Update email if it wasn't set before or has changed (less likely for Apple ID)
                if email and user_by_uid.get('email') != email:
                    update_data['email'] = email

                # Ensure provider info is accurate, especially if it was a generic record before
                current_provider_data = user_by_uid.get('provider_data', {})
                if not isinstance(current_provider_data, dict): # Ensure provider_data is a dict
                    current_provider_data = {}

                provider_id_field = 'provider_id' # Assuming this is the field name in your provider_data

                # Check if this provider is already listed
                is_apple_provider_listed = False
                if isinstance(user_by_uid.get('provider'), str) and user_by_uid.get('provider') == provider:
                    is_apple_provider_listed = True
                elif isinstance(user_by_uid.get('provider'), list):
                     if provider in user_by_uid.get('provider'):
                        is_apple_provider_listed = True

                if not is_apple_provider_listed:
                    # This logic assumes 'provider' field might be a string or a list
                    # And 'provider_data' stores more detailed provider specific UIDs.
                    # For simplicity, we'll focus on ensuring 'provider' reflects 'apple.com'
                    # and 'uid' (primary key) is apple_uid.
                    # If your 'provider' field is a simple string:
                    if user_by_uid.get('provider') != provider:
                         update_data['provider'] = provider # Or logic to append to a list of providers
                    # If you store detailed provider UIDs in 'provider_data':
                    # if current_provider_data.get(provider, {}).get('uid') != apple_uid:
                    #    current_provider_data[provider] = {'uid': apple_uid, 'email': email} # Or similar structure
                    #    update_data['provider_data'] = current_provider_data


                final_user_data = self._ensure_subscription_fields(user_by_uid, apple_uid)
                final_user_data['last_login_provider'] = provider # Track last login provider

                if update_data or final_user_data.get('last_login_provider') != provider : # ensure last_login_provider is updated
                    update_data['last_login_provider'] = provider
                    try:
                        user_ref = self.db.collection('users').document(apple_uid)
                        user_ref.update(update_data)
                        self.logger.info(f"User {apple_uid} details updated from Apple token.")
                        for k, v in update_data.items():
                            final_user_data[k] = v
                    except Exception as e:
                        self.logger.error(f"Error updating user {apple_uid} details: {e}", exc_info=True)

                return {'status': 'success', 'user': final_user_data}

            # 2. If not found by UID, and email is available, try by email (account merge/linking)
            if not email:
                self.logger.info(f"Apple sign-in: User not by UID {apple_uid}, and no email provided in token. Cannot check for merge.")
                # Proceed to create new user if email is not available for lookup
            else:
                self.logger.info(f"Apple sign-in: User not found by UID {apple_uid}. Trying email {email}.")
                user_by_email = firestore_utils.get_user_by_email(email, self.logger)

                if user_by_email:
                    self.logger.info(f"Apple sign-in: User found by email {email} with existing UID {user_by_email['uid']}. Merging/Linking.")
                    old_user_uid = user_by_email['uid']

                    if old_user_uid == apple_uid: # Should have been caught by user_by_uid
                        self.logger.warning(f"User {apple_uid} found by email, UID matches. Inconsistent state. Proceeding as UID match.")
                        # This is essentially the same logic as the `if user_by_uid:` block
                        # Re-fetch and ensure fields are fine.
                        user_by_uid_consistency = firestore_utils.get_user(apple_uid, self.logger) or user_by_email
                        updated_user_data = self._ensure_subscription_fields(user_by_uid_consistency, apple_uid)
                        updated_user_data['displayName'] = display_name # Ensure display name is from current token
                        updated_user_data['email'] = email # Ensure email is from current token
                        updated_user_data['provider'] = provider # Ensure provider is accurate
                        updated_user_data['last_login_provider'] = provider
                        try:
                            self.db.collection('users').document(apple_uid).set(updated_user_data, merge=True)
                        except Exception as e_merge_update:
                             self.logger.error(f"Error updating user {apple_uid} in merge (UID matched): {e_merge_update}")
                        return {'status': 'success', 'user': updated_user_data}

                    # Merge scenario: existing Firestore user (old_user_uid) to be linked with Apple Auth (apple_uid)
                    self.logger.info(f"Account merge needed: Firestore UID {old_user_uid} with Apple UID {apple_uid}.")

                    new_apple_user_firestore_data = {
                        'uid': apple_uid, # Key change: this record is now under apple_uid
                        'email': email,
                        'displayName': display_name,
                        'provider': provider,
                        'last_login_provider': provider,
                        # Carry over essential fields from the old user_by_email record
                        'subscription_plan': user_by_email.get('subscription_plan', 'free'),
                        'subscription_status': user_by_email.get('subscription_status', 'free_tier'),
                        'photo_upload_count_current_month': user_by_email.get('photo_upload_count_current_month', 0),
                        'current_period_start': user_by_email.get('current_period_start') or firestore.SERVER_TIMESTAMP,
                        'current_period_end': user_by_email.get('current_period_end') or firestore.SERVER_TIMESTAMP,
                        'customer_id': user_by_email.get('customer_id'),
                        'subscription_id': user_by_email.get('subscription_id'),
                        'createdAt': user_by_email.get('createdAt', firestore.SERVER_TIMESTAMP), # Preserve original creation if possible
                        'roles': user_by_email.get('roles', []) # Example: carry over roles
                    }
                    new_apple_user_firestore_data = self._ensure_subscription_fields(new_apple_user_firestore_data, apple_uid)


                    try:
                        self.db.collection('users').document(apple_uid).set(new_apple_user_firestore_data)
                        self.logger.info(f"New user record created for {apple_uid} during merge with {old_user_uid}.")
                    except Exception as e_create:
                        self.logger.error(f"Failed to create new user record for {apple_uid} during merge: {e_create}", exc_info=True)
                        return {'status': 'error', 'message': 'Failed to create user record during account merge.', 'status_code': 500}

                    migrated = firestore_utils.migrate_content_ownership(old_user_uid, apple_uid, self.logger)
                    if not migrated:
                        self.logger.error(f"Content migration failed from {old_user_uid} to {apple_uid}. Manual check needed.")
                        # Rollback new user creation is complex; for now, flag critical error.
                        # self.db.collection('users').document(apple_uid).delete() # Potential rollback
                        return {'status': 'error', 'message': 'Content migration failed during account merge. Critical state.', 'status_code': 500}

                    try:
                        self.db.collection('users').document(old_user_uid).delete()
                        self.logger.info(f"Old user record {old_user_uid} deleted after successful merge to {apple_uid}.")
                    except Exception as e_delete:
                        self.logger.error(f"Failed to delete old user record {old_user_uid} after merge: {e_delete}", exc_info=True)
                        # Not returning error here as merge largely succeeded. Logged for attention.

                    return {'status': 'success', 'user': new_apple_user_firestore_data}

            # 3. New Apple user (not found by UID or email, or email was not provided for lookup)
            self.logger.info(f"Apple sign-in: New user. Creating user for UID {apple_uid}, Email: {email if email else 'Not Provided'}.")
            new_user_data = firestore_utils.create_user(
                uid=apple_uid,
                email=email, # Can be None if Apple doesn't provide it
                display_name=display_name,
                provider=provider, # 'apple.com'
                app_logger=self.logger
            )

            if new_user_data:
                new_user_data['last_login_provider'] = provider # Add last login provider
                # Update Firestore with this field if create_user doesn't set it
                try:
                    self.db.collection('users').document(apple_uid).update({'last_login_provider': provider})
                except Exception as e_upd_llp:
                    self.logger.error(f"Failed to update last_login_provider for new user {apple_uid}: {e_upd_llp}")

                self.logger.info(f"New Apple user created successfully: {apple_uid}")
                return {'status': 'success', 'user': new_user_data}
            else:
                self.logger.error(f"Failed to create new Apple user {apple_uid} in Firestore.")
                return {'status': 'error', 'message': 'Failed to create new user in Firestore.', 'status_code': 500}

        except firebase_admin.auth.ExpiredIdTokenError as e:
            self.logger.warning(f'Apple sign-in: Expired ID token for {apple_uid if "apple_uid" in locals() else "unknown UID"}: {e}')
            return {'status': 'error', 'message': 'Expired ID token.', 'status_code': 401}
        except firebase_admin.auth.InvalidIdTokenError as e:
            self.logger.warning(f'Apple sign-in: Invalid ID token for {apple_uid if "apple_uid" in locals() else "unknown UID"}: {e}')
            return {'status': 'error', 'message': 'Invalid ID token.', 'status_code': 401}
        except Exception as e:
            self.logger.error(f'Error in handle_apple_signin for {apple_uid if "apple_uid" in locals() else "unknown UID"}: {e}', exc_info=True)
            return {'status': 'error', 'message': f'An unexpected error occurred: {str(e)}', 'status_code': 500}

# Example of how this service might be instantiated and used (for context, not part of the class)
# if __name__ == '__main__':
#     # Initialize Firebase Admin SDK (needs to be done once)
#     # cred = credentials.Certificate("path/to/your/serviceAccountKey.json")
#     # firebase_admin.initialize_app(cred)
#
#     # Basic logger for testing
#     logger = logging.getLogger("UserServiceTest")
#     logging.basicConfig(level=logging.INFO)
#
#     user_service = UserService(app_logger=logger)
#
#     # Test cases would require a live Firebase project or mocks
#     # print("Testing email/password registration (will fail without proper setup or if email exists)")
#     # registration_result = user_service.register_user_with_email_password("test@example.com", "Test User", "password123")
#     # print(registration_result)
#
#     # print("\nTesting email/password login (placeholder)")
#     # login_result = user_service.login_user_with_email_password("test@example.com", "password123")
#     # print(login_result)
#
#     # To test ID token and Google Sign-In, you'd need a valid ID token.
#     # print("\nTesting ID token login (needs valid token)")
#     # id_token_result = user_service.login_user_with_id_token("your_id_token_here")
#     # print(id_token_result)
#
#     # print("\nTesting Google Sign-In (needs valid token)")
#     # google_token_result = user_service.handle_google_signin("your_google_id_token_here")
#     # print(google_token_result)
