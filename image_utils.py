# image_utils.py

import io
import math
# import traceback # No longer needed if using logger.exception or exc_info=True
from PIL import Image
import exifread
import logging
import uuid
import os
# from firebase_admin import storage # bucket is passed as a parameter

# Configure module logger
# This logger will inherit the configuration from the Flask app logger if this module
# is imported after the Flask app's logging is configured.
# If run standalone, it would need its own handler configuration.
logger = logging.getLogger(__name__) # Using this logger, assuming it's configured by the app
# To ensure it logs if run standalone or if Flask logger isn't set to a low enough level:
# if not logger.handlers: # Add a basic handler if no handlers are configured
#     logger.setLevel(logging.DEBUG) # Set to DEBUG to see all debug messages
#     ch = logging.StreamHandler()
#     ch.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
#     logger.addHandler(ch)


# --- Helper functions for conversion ---

def _robust_float_conversion(value_component):
    """
    Converts a DMS component (degree, minute, or second) to float.
    Handles IFDRational from Pillow and regular numbers.
    Returns float or float('nan') in case of error.
    """
    if hasattr(value_component, 'numerator') and hasattr(value_component, 'denominator'):  # Pillow's IFDRational
        if value_component.denominator == 0:
            logger.warning("Zero denominator in IFDRational during robust float conversion.")
            return float('nan')
        return float(value_component.numerator) / float(value_component.denominator)
    try:
        f_val = float(value_component)
        return f_val
    except (TypeError, ValueError) as e:
        logger.warning(
            f"Error converting '{value_component}' (type {type(value_component)}) to float: {e}"
        )
        return float('nan')


def _convert_dms_to_decimal(dms_tuple, ref_str_raw, source="Unknown"):
    """
    General function to convert DMS to decimal format.
    dms_tuple: Tuple/list of 3 components (degrees, minutes, seconds).
    ref_str_raw: String or byte string for N/S/E/W.
    source: String for logging ("Pillow" or "exifread").
    """
    try:
        if not (isinstance(dms_tuple, (list, tuple)) and len(dms_tuple) == 3):
            logger.warning(
                f"({source} _convert_dms): dms_tuple is not a list/tuple of 3 elements: {dms_tuple}"
            )
            return None

        if isinstance(ref_str_raw, bytes):
            ref_str = ref_str_raw.decode('utf-8', errors='ignore').strip('\x00').strip()
        else:
            ref_str = str(ref_str_raw).strip('\x00').strip()

        if ref_str not in ['N', 'S', 'E', 'W']:
            logger.warning(
                f"({source} _convert_dms): Invalid Ref value: '{ref_str}' (original: '{ref_str_raw}')"
            )
            return None

        degrees = _robust_float_conversion(dms_tuple[0])
        minutes = _robust_float_conversion(dms_tuple[1])
        seconds = _robust_float_conversion(dms_tuple[2])

        if math.isnan(degrees) or math.isnan(minutes) or math.isnan(seconds):
            logger.warning(
                f"({source} _convert_dms): NaN detected in DMS components: D={degrees}, M={minutes}, S={seconds}"
            )
            return None

        decimal_val = degrees + (minutes / 60.0) + (seconds / 3600.0)

        if ref_str in ['S', 'W']:
            decimal_val = -decimal_val

        logger.debug(
            f"({source} _convert_dms): Successfully converted: {decimal_val} (from {dms_tuple}, {ref_str})"
        )
        return decimal_val

    except Exception as e:
        logger.error(
            f"({source} _convert_dms): Error. dms_tuple: {dms_tuple}, ref_str_raw: {ref_str_raw}. Error: {e}",
            exc_info=True
        )
        return None


# --- GPS extraction functions ---

def _extract_gps_with_pillow_modern(image_data):
    """Extract GPS coordinates using Pillow (modern approach)."""
    logger.debug("Attempting GPS extraction with Pillow (getexif/get_ifd).")
    try:
        image = Image.open(io.BytesIO(image_data))
        exif_dict = image.getexif()

        if not exif_dict:
            logger.debug("(Pillow) EXIF data not found via getexif().")
            return None, None

        gps_ifd = exif_dict.get_ifd(0x8825) # GPSIFDPointer tag

        if not gps_ifd:
            logger.debug("(Pillow) GPSInfo IFD (0x8825) not found.")
            return None, None

        # GPS Tags for latitude and longitude
        # Tag 1: GPSLatitudeRef (N/S)
        # Tag 2: GPSLatitude (DMS)
        # Tag 3: GPSLongitudeRef (E/W)
        # Tag 4: GPSLongitude (DMS)
        lat_ref_raw = gps_ifd.get(1)
        lat_dms_raw = gps_ifd.get(2)
        lon_ref_raw = gps_ifd.get(3)
        lon_dms_raw = gps_ifd.get(4)

        logger.debug(
            f"(Pillow) Raw GPS values: lat_ref={lat_ref_raw}, lat_dms={lat_dms_raw}, "
            f"lon_ref={lon_ref_raw}, lon_dms={lon_dms_raw}"
        )

        if not all([lat_dms_raw, lat_ref_raw, lon_dms_raw, lon_ref_raw]):
            logger.debug("(Pillow) One or more key GPS tags (1,2,3,4) not found in GPS IFD.")
            return None, None

        latitude = _convert_dms_to_decimal(lat_dms_raw, lat_ref_raw, source="Pillow")
        longitude = _convert_dms_to_decimal(lon_dms_raw, lon_ref_raw, source="Pillow")

        if latitude is not None and longitude is not None:
            if math.isnan(latitude) or math.isnan(longitude): # Redundant if _convert_dms_to_decimal handles NaN well
                logger.warning("(Pillow) Coordinates contain NaN after conversion.")
                return None, None
            logger.info(f"(Pillow) Successfully extracted GPS: Lat={latitude}, Lon={longitude}")
            return latitude, longitude
        else:
            logger.warning("(Pillow) Failed to convert DMS to decimal coordinates.")
            return None, None

    except Exception as e:
        logger.error(f"(Pillow) Error during GPS extraction: {e}", exc_info=True)
        return None, None


def _extract_gps_with_exifread(image_data):
    """Extract GPS coordinates using exifread."""
    logger.debug("Attempting GPS extraction with exifread.")
    try:
        img_file_obj = io.BytesIO(image_data)
        tags = exifread.process_file(img_file_obj, details=False, strict=False)

        if not tags:
            logger.debug("(exifread) EXIF tags not found.")
            return None, None

        lat_tag_obj = tags.get('GPS GPSLatitude')
        lat_ref_tag_obj = tags.get('GPS GPSLatitudeRef')
        lon_tag_obj = tags.get('GPS GPSLongitude')
        lon_ref_tag_obj = tags.get('GPS GPSLongitudeRef')

        if not all([lat_tag_obj, lat_ref_tag_obj, lon_tag_obj, lon_ref_tag_obj]):
            logger.debug("(exifread) One or more key GPS tags not found.")
            return None, None

        def ratios_to_floats(ratios_list):
            """Helper to convert exifread.utils.Ratio list to float tuple."""
            result = []
            for r_obj in ratios_list:
                if hasattr(r_obj, 'num') and hasattr(r_obj, 'den'): # exifread.utils.Ratio
                    if r_obj.den == 0:
                        logger.warning("(exifread ratios_to_floats) Zero denominator in Ratio.")
                        return [float('nan')] * len(ratios_list) # Propagate NaN
                    result.append(float(r_obj.num) / float(r_obj.den))
                else: # Should not happen if input is Ratio list, but handle other types
                    result.append(_robust_float_conversion(r_obj))
            return tuple(result)

        # exifread stores values in a list of Ratio objects for DMS
        lat_dms_tuple = ratios_to_floats(lat_tag_obj.values)
        # exifread stores Ref as a string within the values list/string
        lat_ref_value = str(lat_ref_tag_obj.values[0] if isinstance(lat_ref_tag_obj.values, list)
                            else lat_ref_tag_obj.values)


        lon_dms_tuple = ratios_to_floats(lon_tag_obj.values)
        lon_ref_value = str(lon_ref_tag_obj.values[0] if isinstance(lon_ref_tag_obj.values, list)
                            else lon_ref_tag_obj.values)

        latitude = _convert_dms_to_decimal(lat_dms_tuple, lat_ref_value, source="exifread")
        longitude = _convert_dms_to_decimal(lon_dms_tuple, lon_ref_value, source="exifread")

        if latitude is not None and longitude is not None:
            if math.isnan(latitude) or math.isnan(longitude):
                logger.warning("(exifread) Coordinates contain NaN after conversion.")
                return None, None
            logger.info(f"(exifread) Successfully extracted GPS: Lat={latitude}, Lon={longitude}")
            return latitude, longitude
        else:
            logger.warning("(exifread) Failed to convert DMS to decimal coordinates.")
            return None, None

    except Exception as e:
        logger.error(f"(exifread) Error during GPS extraction: {e}", exc_info=True)
        return None, None


def extract_gps_coordinates(image_data):
    """
    Main public function to extract GPS coordinates from image byte data.
    Tries exifread first, then Pillow.
    Returns (latitude, longitude) or (None, None) if coordinates are not extracted or invalid.
    """
    logger.info("Starting GPS coordinate extraction (trying exifread first, then Pillow).")

    lat, lon = _extract_gps_with_exifread(image_data)
    if lat is not None and lon is not None:
        logger.info("GPS coordinates successfully extracted via exifread.")
        return lat, lon

    logger.info("exifread did not return valid coordinates, trying Pillow method.")

    lat_pil, lon_pil = _extract_gps_with_pillow_modern(image_data)
    if lat_pil is not None and lon_pil is not None:
        logger.info("GPS coordinates successfully extracted via Pillow.")
        return lat_pil, lon_pil

    logger.warning("Both exifread and Pillow methods failed to extract valid GPS coordinates.")
    return None, None


def upload_image_to_gcs(image_data, filename, app_logger, bucket, content_type=None):
    """
    Uploads image data to Google Cloud Storage.
    Args:
        image_data (bytes): The image data to upload.
        filename (str): The **unique** filename to use in GCS (e.g., "content_images/uuid.ext").
        app_logger (logging.Logger): Logger instance for logging.
        bucket (google.cloud.storage.bucket.Bucket): GCS bucket object.
        content_type (str, optional): The content type of the image. Defaults to None.
    Returns:
        str: The public URL of the uploaded image, or None on failure.
    """
    try:
        current_logger = app_logger if app_logger else logger

        # The filename passed is assumed to be the final, unique GCS path/object name.
        # Example: "content_images/some_uuid.jpg"
        blob = bucket.blob(filename)

        ct_to_upload = content_type
        if not ct_to_upload:
            # Try to guess from filename extension if not provided
            file_extension = os.path.splitext(filename)[1].lstrip('.').lower()
            if file_extension in ["jpg", "jpeg"]:
                ct_to_upload = "image/jpeg"
            elif file_extension == "png":
                ct_to_upload = "image/png"
            elif file_extension == "gif":
                ct_to_upload = "image/gif"
            # Add more common image types as needed
            else:
                current_logger.warning(
                    f"Could not determine content type for '{filename}' from extension '{file_extension}'. "
                    f"Defaulting to 'application/octet-stream'."
                )
                ct_to_upload = 'application/octet-stream'

        current_logger.debug(f"Uploading to GCS as '{filename}' with content type '{ct_to_upload}'.")

        blob.upload_from_string(
            image_data,
            content_type=ct_to_upload
        )
        blob.make_public()
        current_logger.info(f"Successfully uploaded '{filename}' to GCS. Public URL: {blob.public_url}")
        return blob.public_url
    except Exception as e:
        current_logger = app_logger if app_logger else logger
        current_logger.error(f"Error uploading image to GCS: {filename}. Error: {e}", exc_info=True)
        return None


def process_uploaded_image(image_bytes, original_filename, app_logger, bucket, allowed_extensions, max_size):
    """
    Processes an uploaded image: validates, extracts GPS, uploads to GCS.
    Args:
        image_bytes (bytes): Raw bytes of the image.
        original_filename (str): The original name of the uploaded file.
        app_logger (logging.Logger): Logger instance.
        bucket (google.cloud.storage.bucket.Bucket): GCS bucket object.
        allowed_extensions (set): Set of allowed file extensions (e.g., {'jpg', 'png'}).
        max_size (int): Maximum allowed image size in bytes.
    Returns:
        tuple: (image_url, lat, lng) or (None, None, None) if processing fails.
    """
    current_logger = app_logger if app_logger else logger # Prefer app_logger

    if not original_filename or '.' not in original_filename:
        current_logger.warning(f"File ('{original_filename}') has no name or extension. Skipping.")
        return None, None, None

    file_extension = os.path.splitext(original_filename)[1].lstrip('.').lower()
    if not file_extension: # This case should ideally be caught by the check above.
        current_logger.warning(f"File '{original_filename}' has no extension after splitting. Skipping.")
        return None, None, None

    if file_extension not in allowed_extensions:
        current_logger.warning(
            f"File '{original_filename}' has unsupported extension '{file_extension}'. Skipping."
        )
        return None, None, None

    if len(image_bytes) > max_size:
        current_logger.warning(
            f"File {original_filename} is too large ({len(image_bytes)} bytes). MAX_IMAGE_SIZE is {max_size}. Skipping."
        )
        return None, None, None

    current_logger.debug(f"Processing image '{original_filename}': Extracting EXIF GPS data.")
    lat, lng = extract_gps_coordinates(image_bytes) # Uses the module logger internally
    current_logger.debug(f"Image '{original_filename}': EXIF GPS: lat={lat}, lng={lng}")

    current_logger.debug(f"Image '{original_filename}': Uploading to GCS.")
    image_url = upload_image_to_gcs(image_bytes, original_filename, current_logger, bucket)

    if image_url:
        current_logger.info(
            f"Image '{original_filename}': Successfully processed. URL: {image_url}, GPS: ({lat}, {lng})"
        )
        return image_url, lat, lng
    else:
        current_logger.warning(
            f"Image '{original_filename}': Failed to upload to GCS. No URL returned."
        )
        return None, None, None


if __name__ == '__main__':
    # This block is for local testing of image_utils.py
    # It needs its own logger configuration if not run as part of the Flask app.
    if not logger.handlers: # Check module logger specifically
        logger.setLevel(logging.DEBUG)
        ch = logging.StreamHandler() # Output to console
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(funcName)s - %(message)s')
        ch.setFormatter(formatter)
        logger.addHandler(ch)
        logger.info("Configured basic StreamHandler for image_utils.py standalone testing.")


    logger.info("Running image_utils.py standalone tests...")

    # Mock GCS bucket and logger for standalone testing
    class MockBucket:
        def blob(self, name):
            logger.debug(f"[MockBucket] blob(name='{name}') called.")
            return MockBlob(name, self)
        def __init__(self, name="mock_bucket"):
            self.name = name
            logger.debug(f"[MockBucket] Initialized with name '{self.name}'.")

    class MockBlob:
        def __init__(self, name, bucket_ref):
            self.name = name
            self.bucket = bucket_ref # Reference to the mock bucket
            self.public_url = f"http://fake.storage.googleapis.com/{self.bucket.name}/{self.name}"
            self._data = None
            self._content_type = None
            logger.debug(f"[MockBlob] Initialized for '{name}'. Public URL: {self.public_url}")

        def upload_from_string(self, data, content_type):
            self._data = data
            self._content_type = content_type
            logger.info(
                f"[MockBlob] upload_from_string for '{self.name}'. Content-Type: {content_type}. Data length: {len(data)} bytes."
            )

        def make_public(self):
            logger.info(f"[MockBlob] make_public for '{self.name}'.")


    mock_gcs_bucket = MockBucket()
    mock_logger = logger # Use the configured module logger for tests

    # Test image data (replace with actual image bytes if needed for more thorough testing)
    # Creating a minimal valid JPEG for testing structure, not content extraction
    minimal_jpeg_io = io.BytesIO()
    try:
        Image.new('RGB', (10, 10), color='blue').save(minimal_jpeg_io, format='JPEG')
        minimal_jpeg_bytes = minimal_jpeg_io.getvalue()
    except Exception as e:
        logger.error(f"Failed to create minimal JPEG for testing: {e}")
        minimal_jpeg_bytes = b'' # Fallback to empty bytes

    logger.info("\n--- Test 1: process_uploaded_image with valid data ---")
    test_filename_valid = "test_image.jpg"
    allowed_exts = {'jpg', 'jpeg', 'png', 'gif'}
    max_img_size = 10 * 1024 * 1024 # 10MB

    if minimal_jpeg_bytes:
        url, lat, lng = process_uploaded_image(
            minimal_jpeg_bytes, test_filename_valid, mock_logger, mock_gcs_bucket, allowed_exts, max_img_size
        )
        if url and "content_images/" in url and ".jpg" in url:
            logger.info(f"process_uploaded_image (valid) PASSED. URL: {url}, Lat: {lat}, Lng: {lng}")
        else:
            logger.error(f"process_uploaded_image (valid) FAILED. URL: {url}, Lat: {lat}, Lng: {lng}")
    else:
        logger.warning("Skipping 'process_uploaded_image with valid data' test as minimal_jpeg_bytes is empty.")


    logger.info("\n--- Test 2: process_uploaded_image with unsupported extension ---")
    test_filename_unsupported_ext = "test_image.txt"
    url_txt, _, _ = process_uploaded_image(
        b"some text data", test_filename_unsupported_ext, mock_logger, mock_gcs_bucket, allowed_exts, max_img_size
    )
    if url_txt is None:
        logger.info("process_uploaded_image (unsupported ext) PASSED.")
    else:
        logger.error(f"process_uploaded_image (unsupported ext) FAILED. URL: {url_txt}")


    logger.info("\n--- Test 3: process_uploaded_image with image too large ---")
    test_filename_large = "large_image.jpg"
    # Create dummy bytes larger than max_size for testing this specific check
    # Note: max_img_size is 10MB for this test case.
    # Creating actual large image data can be slow/memory intensive.
    # For unit test, just checking the size logic is often enough.
    # If more detailed test for upload_image_to_gcs with large file is needed,
    # it should be a separate, more focused test.
    large_image_bytes = b"a" * (max_img_size + 1)
    url_large, _, _ = process_uploaded_image(
        large_image_bytes, test_filename_large, mock_logger, mock_gcs_bucket, allowed_exts, max_img_size
    )
    if url_large is None:
        logger.info("process_uploaded_image (too large) PASSED.")
    else:
        logger.error(f"process_uploaded_image (too large) FAILED. URL: {url_large}")

    logger.info("\n--- Test 4: upload_image_to_gcs basic functionality ---")
    if minimal_jpeg_bytes:
        gcs_url = upload_image_to_gcs(minimal_jpeg_bytes, "direct_upload_test.jpeg", mock_logger, mock_gcs_bucket)
        if gcs_url and "content_images/" in gcs_url and ".jpeg" in gcs_url:
            logger.info(f"upload_image_to_gcs basic PASSED. URL: {gcs_url}")
        else:
            logger.error(f"upload_image_to_gcs basic FAILED. URL: {gcs_url}")
    else:
        logger.warning("Skipping 'upload_image_to_gcs basic functionality' test as minimal_jpeg_bytes is empty.")


    logger.info("\n--- Test 5: GPS Extraction from a real image (if available) ---")
    # This test is similar to the original one for extract_gps_coordinates
    # but now it's integrated into the new structure.
    # Assumes '2.jpg' is in the same folder for testing, and it has EXIF GPS.
    # This part relies on having a real image with GPS data.
    real_test_image_path = '2.jpg'
    try:
        with open(real_test_image_path, 'rb') as f:
            image_bytes_real_exif = f.read()
        logger.info(f"Read {len(image_bytes_real_exif)} bytes from {real_test_image_path} for GPS test.")

        # Test extract_gps_coordinates directly as it's a core part
        lat_exif, lon_exif = extract_gps_coordinates(image_bytes_real_exif)
        if lat_exif is not None and lon_exif is not None:
            logger.info(f"extract_gps_coordinates with {real_test_image_path}: Lat={lat_exif:.6f}, Lon={lon_exif:.6f}")
        else:
            logger.warning(f"extract_gps_coordinates with {real_test_image_path}: No GPS data found or error.")

        # Also test it via process_uploaded_image
        # Ensure this image doesn't exceed max_img_size for this test path
        if len(image_bytes_real_exif) <= max_img_size:
            url_exif, lat_pui, lon_pui = process_uploaded_image(
                image_bytes_real_exif, real_test_image_path, mock_logger, mock_gcs_bucket, allowed_exts, max_img_size
            )
            if url_exif:
                logger.info(f"process_uploaded_image with {real_test_image_path}: URL={url_exif}, Lat={lat_pui}, Lon={lon_pui}")
                if lat_pui is None or lon_pui is None:
                    logger.warning(f"   ...but GPS data was not extracted via process_uploaded_image path.")
            else:
                logger.error(f"process_uploaded_image with {real_test_image_path} FAILED to upload.")
        else:
            logger.warning(f"Skipping process_uploaded_image test for {real_test_image_path} as it exceeds max_size for this test case.")

    except FileNotFoundError:
        logger.warning(f"Test file not found: {real_test_image_path}. GPS extraction test with real image skipped.")
    except Exception as e:
        logger.error(f"Error testing file {real_test_image_path}: {e}", exc_info=True)

    logger.info("\n--- image_utils.py standalone tests finished ---")