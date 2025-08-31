import re
# import os # No longer used in this file

# INBOUND_URL_TOKEN global variable removed. It will be passed from app.py configuration.

def verify_inbound_token(token_to_verify, correct_token):
    """
    Verifies the provided token against the correct token.
    Args:
        token_to_verify (str): The token received in the request.
        correct_token (str): The actual token from configuration.
    Returns:
        bool: True if tokens match, False otherwise.
    """
    if not token_to_verify or not correct_token: # Ensure neither is empty
        return False
    return token_to_verify == correct_token

def parse_location_from_subject(subject):
    if not subject:
        return None, None
    pattern = r'lat:([-+]?\d*\.?\d+),lng:([-+]?\d*\.?\d+)'
    match = re.search(pattern, subject, re.IGNORECASE)
    if match:
        try:
            lat = float(match.group(1))
            lng = float(match.group(2))
            if -90 <= lat <= 90 and -180 <= lng <= 180:
                return lat, lng
        except ValueError:
            pass  # Or log this specific error
    return None, None
