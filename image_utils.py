# image_utils.py

import io
import math
# import traceback # No longer needed if using logger.exception or exc_info=True
from PIL import Image
import exifread
import logging
import uuid
import base64
from firebase_admin import storage

# Configure module logger
# This logger will inherit the configuration from the Flask app logger if this module
# is imported after the Flask app's logging is configured.
# If run standalone, it would need its own handler configuration.
logger = logging.getLogger(__name__)
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


def process_uploaded_image(image_bytes, original_filename, app_logger, bucket, allowed_extensions, max_size):
    """
    Process uploaded image: validate, extract GPS, upload to GCS.
    
    Args:
        image_bytes: Raw image bytes
        original_filename: Original filename
        app_logger: Application logger instance
        bucket: Firebase Storage bucket
        allowed_extensions: Set of allowed file extensions
        max_size: Maximum file size in bytes
    
    Returns:
        tuple: (image_url, latitude, longitude) or (None, None, None) if processing failed
    """
    app_logger.debug(f"Processing uploaded image: {original_filename}")
    
    # Validate file extension
    if not original_filename or '.' not in original_filename:
        app_logger.warning(f"Invalid filename: {original_filename}")
        return None, None, None
    
    file_extension = original_filename.split('.')[-1].lower()
    if file_extension not in allowed_extensions:
        app_logger.warning(f"Unsupported file extension: {file_extension}")
        return None, None, None
    
    # Validate file size
    if len(image_bytes) > max_size:
        app_logger.warning(f"File too large: {len(image_bytes)} bytes (max: {max_size})")
        return None, None, None
    
    try:
        # Extract GPS coordinates
        app_logger.debug(f"Extracting GPS coordinates from {original_filename}")
        lat, lng = extract_gps_coordinates(image_bytes)
        app_logger.debug(f"GPS extraction result for {original_filename}: lat={lat}, lng={lng}")
        
        # Upload to GCS
        app_logger.debug(f"Uploading {original_filename} to GCS")
        image_url = upload_image_to_gcs(image_bytes, original_filename, bucket, app_logger)
        
        if image_url:
            app_logger.info(f"Successfully processed {original_filename}: URL={image_url}, GPS=({lat}, {lng})")
            return image_url, lat, lng
        else:
            app_logger.error(f"Failed to upload {original_filename} to GCS")
            return None, None, None
            
    except Exception as e:
        app_logger.error(f"Error processing image {original_filename}: {e}", exc_info=True)
        return None, None, None


def upload_image_to_gcs(image_data, filename, bucket, app_logger):
    """
    Upload image to Google Cloud Storage.
    
    Args:
        image_data: Raw image bytes
        filename: Original filename
        bucket: Firebase Storage bucket
        app_logger: Application logger instance
    
    Returns:
        str: Public URL of uploaded image or None if upload failed
    """
    try:
        file_extension = filename.split('.')[-1].lower()
        unique_filename = f"content_images/{uuid.uuid4()}.{file_extension}"
        
        blob = bucket.blob(unique_filename)
        blob.upload_from_string(
            image_data,
            content_type=f'image/{file_extension}'
        )
        blob.make_public()
        
        app_logger.info(f"Successfully uploaded {filename} to GCS: {blob.public_url}")
        return blob.public_url
        
    except Exception as e:
        app_logger.error(f"Error uploading {filename} to GCS: {e}", exc_info=True)
        return None


if __name__ == '__main__':
    # This block is for local testing of image_utils.py
    # It needs its own logger configuration if not run as part of the Flask app.
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        ch = logging.StreamHandler() # Output to console
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(funcName)s - %(message)s')
        ch.setFormatter(formatter)
        logger.addHandler(ch)

    logger.info("Running image_utils.py standalone tests...")

    test_image_path = '2.jpg' # Assumes '2.jpg' is in the same folder for testing

    logger.info("\n--- Test 1: Empty/dummy image (no EXIF) ---")
    empty_image_bytes_io = io.BytesIO()
    try:
        Image.new('RGB', (60, 30), color='red').save(empty_image_bytes_io, format='JPEG')
        lat_empty, lon_empty = extract_gps_coordinates(empty_image_bytes_io.getvalue())
        if lat_empty is None and lon_empty is None:
            logger.info("Result for empty image: Coordinates not extracted (Expected).")
        else:
            logger.warning(f"Result for empty image: Lat={lat_empty}, Lon={lon_empty} (Unexpected).")
    except Exception as e:
        logger.error(f"Error during empty image test: {e}", exc_info=True)


    logger.info(f"\n--- Test 2: Image with potential EXIF data ({test_image_path}) ---")
    try:
        with open(test_image_path, 'rb') as f:
            image_bytes_real = f.read()
        logger.info(f"Read {len(image_bytes_real)} bytes from {test_image_path}")
        lat_real, lon_real = extract_gps_coordinates(image_bytes_real)

        if lat_real is not None and lon_real is not None:
            # NaN check is important as math operations on NaN can be tricky
            if math.isnan(lat_real) or math.isnan(lon_real):
                logger.warning(f"Result for {test_image_path}: Coordinates contain NaN. Lat={lat_real}, Lon={lon_real}")
            else:
                logger.info(f"Result for {test_image_path}: Lat={lat_real:.6f}, Lon={lon_real:.6f}")
        else:
            logger.info(f"Result for {test_image_path}: Coordinates not extracted or invalid.")
    except FileNotFoundError:
        logger.error(f"Test file not found: {test_image_path}")
    except Exception as e:
        logger.error(f"Error testing file {test_image_path}: {e}", exc_info=True)