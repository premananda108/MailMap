# image_utils.py

import io
import math
import traceback
from PIL import Image
# TAGS and GPSTAGS from PIL.ExifTags can be useful for debugging,
# but are not strictly necessary for the main functionality here.
# from PIL.ExifTags import TAGS, GPSTAGS
import exifread


# --- Helper functions for conversion ---

def _robust_float_conversion(value_component):
    """
    Converts a DMS component (degree, minute, or second) to float.
    Handles IFDRational from Pillow and regular numbers.
    Returns float or float('nan') in case of error.
    """
    if hasattr(value_component, 'numerator') and hasattr(value_component, 'denominator'):  # Pillow's IFDRational
        if value_component.denominator == 0:
            print("DEBUG_GPS_UTIL (_robust_float_conversion): Zero denominator in IFDRational.")
            return float('nan')
        return float(value_component.numerator) / float(value_component.denominator)
    try:
        f_val = float(value_component)
        return f_val
    except (TypeError, ValueError) as e:
        print(
            f"DEBUG_GPS_UTIL (_robust_float_conversion): Error converting '{value_component}' (type {type(value_component)}) to float: {e}")
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
            print(
                f"DEBUG_GPS_UTIL ({source} _convert_dms): dms_tuple is not a list/tuple of 3 elements: {dms_tuple}")
            return None

        if isinstance(ref_str_raw, bytes):
            ref_str = ref_str_raw.decode('utf-8', errors='ignore').strip('\x00').strip()
        else:
            ref_str = str(ref_str_raw).strip('\x00').strip()

        if ref_str not in ['N', 'S', 'E', 'W']:
            print(
                f"DEBUG_GPS_UTIL ({source} _convert_dms): Invalid Ref value: '{ref_str}' (original: '{ref_str_raw}')")
            return None

        degrees = _robust_float_conversion(dms_tuple[0])
        minutes = _robust_float_conversion(dms_tuple[1])
        seconds = _robust_float_conversion(dms_tuple[2])

        if math.isnan(degrees) or math.isnan(minutes) or math.isnan(seconds):
            print(
                f"DEBUG_GPS_UTIL ({source} _convert_dms): NaN detected in DMS components: D={degrees}, M={minutes}, S={seconds}")
            return None

        decimal_val = degrees + (minutes / 60.0) + (seconds / 3600.0)

        if ref_str in ['S', 'W']:
            decimal_val = -decimal_val

        print(
            f"DEBUG_GPS_UTIL ({source} _convert_dms): Successfully converted: {decimal_val} (from {dms_tuple}, {ref_str})")
        return decimal_val

    except Exception as e:
        print(
            f"DEBUG_GPS_UTIL ({source} _convert_dms): Error. dms_tuple: {dms_tuple}, ref_str_raw: {ref_str_raw}. Error: {e}")
        return None


# --- GPS extraction functions ---

def _extract_gps_with_pillow_modern(image_data):
    """Extract GPS coordinates using Pillow (modern approach)."""
    print("DEBUG_GPS_UTIL: Attempting extraction with Pillow (getexif/get_ifd).")
    try:
        image = Image.open(io.BytesIO(image_data))
        exif_dict = image.getexif()

        if not exif_dict:
            print("DEBUG_GPS_UTIL (Pillow): EXIF data not found via getexif().")
            return None, None

        gps_ifd = exif_dict.get_ifd(0x8825)

        if not gps_ifd:
            print("DEBUG_GPS_UTIL (Pillow): GPSInfo IFD (0x8825) not found.")
            return None, None

        lat_ref_raw = gps_ifd.get(1)
        lat_dms_raw = gps_ifd.get(2)
        lon_ref_raw = gps_ifd.get(3)
        lon_dms_raw = gps_ifd.get(4)

        print(
            f"DEBUG_GPS_UTIL (Pillow): Raw values: lat_ref={lat_ref_raw}, lat_dms={lat_dms_raw}, lon_ref={lon_ref_raw}, lon_dms={lon_dms_raw}")

        if not all([lat_dms_raw, lat_ref_raw, lon_dms_raw, lon_ref_raw]):
            print("DEBUG_GPS_UTIL (Pillow): One or more key GPS tags (1,2,3,4) not found in GPS IFD.")
            return None, None

        latitude = _convert_dms_to_decimal(lat_dms_raw, lat_ref_raw, source="Pillow")
        longitude = _convert_dms_to_decimal(lon_dms_raw, lon_ref_raw, source="Pillow")

        if latitude is not None and longitude is not None:
            # Additional NaN check here before returning
            if math.isnan(latitude) or math.isnan(longitude):
                print("DEBUG_GPS_UTIL (Pillow): Coordinates contain NaN after conversion.")
                return None, None
            print(f"DEBUG_GPS_UTIL (Pillow): Successfully extracted: Lat={latitude}, Lon={longitude}")
            return latitude, longitude
        else:
            print("DEBUG_GPS_UTIL (Pillow): Failed to convert DMS from Pillow.")
            return None, None

    except Exception as e:
        print(f"DEBUG_GPS_UTIL (Pillow): Error: {e}")
        traceback.print_exc()
        return None, None


def _extract_gps_with_exifread(image_data):
    """Extract GPS coordinates using exifread."""
    print("DEBUG_GPS_UTIL: Attempting extraction with exifread.")
    try:
        img_file_obj = io.BytesIO(image_data)
        tags = exifread.process_file(img_file_obj, details=False, strict=False)

        if not tags:
            print("DEBUG_GPS_UTIL (exifread): EXIF tags not found.")
            return None, None

        lat_tag_obj = tags.get('GPS GPSLatitude')
        lat_ref_tag_obj = tags.get('GPS GPSLatitudeRef')
        lon_tag_obj = tags.get('GPS GPSLongitude')
        lon_ref_tag_obj = tags.get('GPS GPSLongitudeRef')

        if not all([lat_tag_obj, lat_ref_tag_obj, lon_tag_obj, lon_ref_tag_obj]):
            print("DEBUG_GPS_UTIL (exifread): One or more key GPS tags not found.")
            return None, None

        def ratios_to_floats(ratios_list):
            result = []
            for r_obj in ratios_list:
                if hasattr(r_obj, 'num') and hasattr(r_obj, 'den'):
                    if r_obj.den == 0: return [float('nan')] * len(ratios_list)
                    result.append(float(r_obj.num) / float(r_obj.den))
                else:
                    result.append(_robust_float_conversion(r_obj))
            return tuple(result)

        lat_dms_tuple = ratios_to_floats(lat_tag_obj.values)
        lat_ref_value = (lat_ref_tag_obj.values[0] if isinstance(lat_ref_tag_obj.values, list)
                         else lat_ref_tag_obj.values)

        lon_dms_tuple = ratios_to_floats(lon_tag_obj.values)
        lon_ref_value = (lon_ref_tag_obj.values[0] if isinstance(lon_ref_tag_obj.values, list)
                         else lon_ref_tag_obj.values)

        latitude = _convert_dms_to_decimal(lat_dms_tuple, lat_ref_value, source="exifread")
        longitude = _convert_dms_to_decimal(lon_dms_tuple, lon_ref_value, source="exifread")

        if latitude is not None and longitude is not None:
            if math.isnan(latitude) or math.isnan(longitude):
                print("DEBUG_GPS_UTIL (exifread): Coordinates contain NaN after conversion.")
                return None, None
            print(f"DEBUG_GPS_UTIL (exifread): Successfully extracted: Lat={latitude}, Lon={longitude}")
            return latitude, longitude
        else:
            print("DEBUG_GPS_UTIL (exifread): Failed to convert DMS from exifread.")
            return None, None

    except Exception as e:
        print(f"DEBUG_GPS_UTIL (exifread): Error: {e}")
        traceback.print_exc()
        return None, None


def extract_gps_coordinates(image_data):
    """
    Main public function to extract GPS coordinates from image byte data.
    Tries exifread first, then Pillow.
    Returns (latitude, longitude) or (None, None) if coordinates are not extracted or invalid.
    """
    print("DEBUG_GPS_UTIL: Starting extract_gps_coordinates (combined method).")

    lat, lon = _extract_gps_with_exifread(image_data)
    if lat is not None and lon is not None:  # NaN check already handled within _extract_gps_...
        print("DEBUG_GPS_UTIL: Coordinates successfully extracted via exifread.")
        return lat, lon

    print("DEBUG_GPS_UTIL: exifread did not return valid coordinates, trying Pillow.")

    lat_pil, lon_pil = _extract_gps_with_pillow_modern(image_data)
    if lat_pil is not None and lon_pil is not None:
        print("DEBUG_GPS_UTIL: Coordinates successfully extracted via Pillow.")
        return lat_pil, lon_pil

    print("DEBUG_GPS_UTIL: Both methods (exifread and Pillow) failed to extract valid coordinates.")
    return None, None


if __name__ == '__main__':
    # Example usage for local testing of image_utils.py
    # Place a test image next to this file or specify the full path
    # test_image_path = 'path/to/your/test_image.jpg'
    test_image_path = '2.jpg' # If the file is in the same folder

    # For testing, let's create an "empty" image without EXIF and a "problematic" one

    print("\n--- Test 1: Empty image ---")
    empty_image_bytes = io.BytesIO()
    Image.new('RGB', (60, 30), color='red').save(empty_image_bytes, format='JPEG')
    lat, lon = extract_gps_coordinates(empty_image_bytes.getvalue())
    if lat is None:
        print("Result for empty image: Coordinates not extracted (Expected)")
    else:
        print(f"Result for empty image: Lat={lat}, Lon={lon} (Unexpected)")

    # To test with a real problematic file, uncomment:
    print(f"\n--- Test 2: Problematic image ({test_image_path}) ---")
    try:
        with open(test_image_path, 'rb') as f:
            image_bytes_real = f.read()
        lat_real, lon_real = extract_gps_coordinates(image_bytes_real)
        if lat_real is not None and lon_real is not None:
            if math.isnan(lat_real) or math.isnan(lon_real):
                print(f"Result for {test_image_path}: Coordinates contain NaN. Lat={lat_real}, Lon={lon_real}")
            else:
                print(f"Result for {test_image_path}: Lat={lat_real:.6f}, Lon={lon_real:.6f}")
        else:
            print(f"Result for {test_image_path}: Coordinates not extracted.")
    except FileNotFoundError:
        print(f"Test file not found: {test_image_path}")
    except Exception as e:
        print(f"Error testing file {test_image_path}: {e}")