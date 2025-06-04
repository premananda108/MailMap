# image_utils.py

import io
import math
import traceback
from PIL import Image
# TAGS и GPSTAGS из PIL.ExifTags могут быть полезны для отладки,
# но не являются строго необходимыми для основного функционала здесь.
# from PIL.ExifTags import TAGS, GPSTAGS
import exifread


# --- Вспомогательные функции для конвертации ---

def _robust_float_conversion(value_component):
    """
    Преобразует компонент DMS (градус, минута или секунда) в float.
    Обрабатывает IFDRational от Pillow и обычные числа.
    Возвращает float или float('nan') в случае ошибки.
    """
    if hasattr(value_component, 'numerator') and hasattr(value_component, 'denominator'):  # Pillow's IFDRational
        if value_component.denominator == 0:
            print("DEBUG_GPS_UTIL (_robust_float_conversion): Нулевой знаменатель в IFDRational.")
            return float('nan')
        return float(value_component.numerator) / float(value_component.denominator)
    try:
        f_val = float(value_component)
        return f_val
    except (TypeError, ValueError) as e:
        print(
            f"DEBUG_GPS_UTIL (_robust_float_conversion): Ошибка преобразования '{value_component}' (тип {type(value_component)}) во float: {e}")
        return float('nan')


def _convert_dms_to_decimal(dms_tuple, ref_str_raw, source="Unknown"):
    """
    Общая функция для конвертации DMS в десятичный формат.
    dms_tuple: Кортеж/список из 3 компонентов (градусы, минуты, секунды).
    ref_str_raw: Строка или байтовая строка для N/S/E/W.
    source: Строка для логирования ("Pillow" или "exifread").
    """
    try:
        if not (isinstance(dms_tuple, (list, tuple)) and len(dms_tuple) == 3):
            print(
                f"DEBUG_GPS_UTIL ({source} _convert_dms): dms_tuple не является списком/кортежем из 3 элементов: {dms_tuple}")
            return None

        if isinstance(ref_str_raw, bytes):
            ref_str = ref_str_raw.decode('utf-8', errors='ignore').strip('\x00').strip()
        else:
            ref_str = str(ref_str_raw).strip('\x00').strip()

        if ref_str not in ['N', 'S', 'E', 'W']:
            print(
                f"DEBUG_GPS_UTIL ({source} _convert_dms): Некорректное значение Ref: '{ref_str}' (исходное: '{ref_str_raw}')")
            return None

        degrees = _robust_float_conversion(dms_tuple[0])
        minutes = _robust_float_conversion(dms_tuple[1])
        seconds = _robust_float_conversion(dms_tuple[2])

        if math.isnan(degrees) or math.isnan(minutes) or math.isnan(seconds):
            print(
                f"DEBUG_GPS_UTIL ({source} _convert_dms): Обнаружено NaN в компонентах DMS: D={degrees}, M={minutes}, S={seconds}")
            return None

        decimal_val = degrees + (minutes / 60.0) + (seconds / 3600.0)

        if ref_str in ['S', 'W']:
            decimal_val = -decimal_val

        print(
            f"DEBUG_GPS_UTIL ({source} _convert_dms): Успешно конвертировано: {decimal_val} (из {dms_tuple}, {ref_str})")
        return decimal_val

    except Exception as e:
        print(
            f"DEBUG_GPS_UTIL ({source} _convert_dms): Ошибка. dms_tuple: {dms_tuple}, ref_str_raw: {ref_str_raw}. Ошибка: {e}")
        return None


# --- Функции извлечения GPS ---

def _extract_gps_with_pillow_modern(image_data):
    """Извлечение GPS координат с помощью Pillow (современный подход)."""
    print("DEBUG_GPS_UTIL: Попытка извлечения с Pillow (getexif/get_ifd).")
    try:
        image = Image.open(io.BytesIO(image_data))
        exif_dict = image.getexif()

        if not exif_dict:
            print("DEBUG_GPS_UTIL (Pillow): EXIF данные не найдены через getexif().")
            return None, None

        gps_ifd = exif_dict.get_ifd(0x8825)

        if not gps_ifd:
            print("DEBUG_GPS_UTIL (Pillow): GPSInfo IFD (0x8825) не найден.")
            return None, None

        lat_ref_raw = gps_ifd.get(1)
        lat_dms_raw = gps_ifd.get(2)
        lon_ref_raw = gps_ifd.get(3)
        lon_dms_raw = gps_ifd.get(4)

        print(
            f"DEBUG_GPS_UTIL (Pillow): Сырые значения: lat_ref={lat_ref_raw}, lat_dms={lat_dms_raw}, lon_ref={lon_ref_raw}, lon_dms={lon_dms_raw}")

        if not all([lat_dms_raw, lat_ref_raw, lon_dms_raw, lon_ref_raw]):
            print("DEBUG_GPS_UTIL (Pillow): Один или несколько ключевых GPS тегов (1,2,3,4) не найдены в GPS IFD.")
            return None, None

        latitude = _convert_dms_to_decimal(lat_dms_raw, lat_ref_raw, source="Pillow")
        longitude = _convert_dms_to_decimal(lon_dms_raw, lon_ref_raw, source="Pillow")

        if latitude is not None and longitude is not None:
            # Дополнительная проверка на NaN здесь перед возвратом
            if math.isnan(latitude) or math.isnan(longitude):
                print("DEBUG_GPS_UTIL (Pillow): Координаты содержат NaN после конвертации.")
                return None, None
            print(f"DEBUG_GPS_UTIL (Pillow): Успешно извлечено: Lat={latitude}, Lon={longitude}")
            return latitude, longitude
        else:
            print("DEBUG_GPS_UTIL (Pillow): Не удалось конвертировать DMS из Pillow.")
            return None, None

    except Exception as e:
        print(f"DEBUG_GPS_UTIL (Pillow): Ошибка: {e}")
        traceback.print_exc()
        return None, None


def _extract_gps_with_exifread(image_data):
    """Извлечение GPS координат с помощью exifread."""
    print("DEBUG_GPS_UTIL: Попытка извлечения с exifread.")
    try:
        img_file_obj = io.BytesIO(image_data)
        tags = exifread.process_file(img_file_obj, details=False, strict=False)

        if not tags:
            print("DEBUG_GPS_UTIL (exifread): Теги EXIF не найдены.")
            return None, None

        lat_tag_obj = tags.get('GPS GPSLatitude')
        lat_ref_tag_obj = tags.get('GPS GPSLatitudeRef')
        lon_tag_obj = tags.get('GPS GPSLongitude')
        lon_ref_tag_obj = tags.get('GPS GPSLongitudeRef')

        if not all([lat_tag_obj, lat_ref_tag_obj, lon_tag_obj, lon_ref_tag_obj]):
            print("DEBUG_GPS_UTIL (exifread): Один или несколько ключевых GPS тегов не найдены.")
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
                print("DEBUG_GPS_UTIL (exifread): Координаты содержат NaN после конвертации.")
                return None, None
            print(f"DEBUG_GPS_UTIL (exifread): Успешно извлечено: Lat={latitude}, Lon={longitude}")
            return latitude, longitude
        else:
            print("DEBUG_GPS_UTIL (exifread): Не удалось конвертировать DMS из exifread.")
            return None, None

    except Exception as e:
        print(f"DEBUG_GPS_UTIL (exifread): Ошибка: {e}")
        traceback.print_exc()
        return None, None


def extract_gps_coordinates(image_data):
    """
    Основная публичная функция для извлечения GPS координат из байтовых данных изображения.
    Сначала пробует exifread, затем Pillow.
    Возвращает (latitude, longitude) или (None, None), если координаты не извлечены или невалидны.
    """
    print("DEBUG_GPS_UTIL: Начало extract_gps_coordinates (комбинированный метод).")

    lat, lon = _extract_gps_with_exifread(image_data)
    if lat is not None and lon is not None:  # Проверка на None, NaN уже обработан внутри _extract_gps_...
        print("DEBUG_GPS_UTIL: Координаты успешно извлечены через exifread.")
        return lat, lon

    print("DEBUG_GPS_UTIL: exifread не вернул валидные координаты, пробуем Pillow.")

    lat_pil, lon_pil = _extract_gps_with_pillow_modern(image_data)
    if lat_pil is not None and lon_pil is not None:
        print("DEBUG_GPS_UTIL: Координаты успешно извлечены через Pillow.")
        return lat_pil, lon_pil

    print("DEBUG_GPS_UTIL: Оба метода (exifread и Pillow) не смогли извлечь валидные координаты.")
    return None, None


if __name__ == '__main__':
    # Пример использования для локального тестирования image_utils.py
    # Поместите тестовое изображение рядом с этим файлом или укажите полный путь
    # test_image_path = 'path/to/your/test_image.jpg'
    test_image_path = '2.jpg' # Если файл в той же папке

    # Для теста создадим "пустое" изображение без EXIF и "проблемное"

    print("\n--- Тест 1: Пустое изображение ---")
    empty_image_bytes = io.BytesIO()
    Image.new('RGB', (60, 30), color='red').save(empty_image_bytes, format='JPEG')
    lat, lon = extract_gps_coordinates(empty_image_bytes.getvalue())
    if lat is None:
        print("Результат для пустого изображения: Координаты не извлечены (Ожидаемо)")
    else:
        print(f"Результат для пустого изображения: Lat={lat}, Lon={lon} (Неожиданно)")

    # Чтобы протестировать с реальным проблемным файлом, раскомментируйте:
    print(f"\n--- Тест 2: Проблемное изображение ({test_image_path}) ---")
    try:
        with open(test_image_path, 'rb') as f:
            image_bytes_real = f.read()
        lat_real, lon_real = extract_gps_coordinates(image_bytes_real)
        if lat_real is not None and lon_real is not None:
            if math.isnan(lat_real) or math.isnan(lon_real):
                print(f"Результат для {test_image_path}: Координаты содержат NaN. Lat={lat_real}, Lon={lon_real}")
            else:
                print(f"Результат для {test_image_path}: Lat={lat_real:.6f}, Lon={lon_real:.6f}")
        else:
            print(f"Результат для {test_image_path}: Координаты не извлечены.")
    except FileNotFoundError:
        print(f"Тестовый файл не найден: {test_image_path}")
    except Exception as e:
        print(f"Ошибка при тестировании файла {test_image_path}: {e}")