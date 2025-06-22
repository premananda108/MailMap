#!/usr/bin/env python3
"""
Скрипт для запуска всех тестов системы обработки вебхуков.
"""

import sys
import os
import subprocess
import time

def run_test_module(module_name):
    """Запускает тесты для конкретного модуля"""
    print(f"\n{'='*60}")
    print(f"Запуск тестов для {module_name}")
    print(f"{'='*60}")
    
    start_time = time.time()
    
    try:
        result = subprocess.run([
            sys.executable, '-m', 'pytest', 
            f'tests/test_{module_name}.py', 
            '-v', '--tb=short'
        ], capture_output=True, text=True, timeout=60)
        
        end_time = time.time()
        duration = end_time - start_time
        
        print(f"Время выполнения: {duration:.2f} секунд")
        
        if result.returncode == 0:
            print(f"✅ Тесты {module_name} прошли успешно")
            return True
        else:
            print(f"❌ Тесты {module_name} провалились")
            print("Вывод:")
            print(result.stdout)
            print("Ошибки:")
            print(result.stderr)
            return False
            
    except subprocess.TimeoutExpired:
        print(f"⏰ Тесты {module_name} превысили лимит времени")
        return False
    except Exception as e:
        print(f"💥 Ошибка запуска тестов {module_name}: {e}")
        return False

def run_integration_tests():
    """Запускает интеграционные тесты"""
    print(f"\n{'='*60}")
    print("Запуск интеграционных тестов")
    print(f"{'='*60}")
    
    start_time = time.time()
    
    try:
        result = subprocess.run([
            sys.executable, '-m', 'pytest', 
            'tests/test_integration.py', 
            '-v', '--tb=short'
        ], capture_output=True, text=True, timeout=120)
        
        end_time = time.time()
        duration = end_time - start_time
        
        print(f"Время выполнения: {duration:.2f} секунд")
        
        if result.returncode == 0:
            print("✅ Интеграционные тесты прошли успешно")
            return True
        else:
            print("❌ Интеграционные тесты провалились")
            print("Вывод:")
            print(result.stdout)
            print("Ошибки:")
            print(result.stderr)
            return False
            
    except subprocess.TimeoutExpired:
        print("⏰ Интеграционные тесты превысили лимит времени")
        return False
    except Exception as e:
        print(f"💥 Ошибка запуска интеграционных тестов: {e}")
        return False

def run_compatibility_tests():
    """Запускает тесты совместимости"""
    print(f"\n{'='*60}")
    print("Запуск тестов совместимости")
    print(f"{'='*60}")
    
    start_time = time.time()
    
    try:
        result = subprocess.run([
            sys.executable, '-m', 'pytest', 
            'tests/test_compatibility.py', 
            '-v', '--tb=short'
        ], capture_output=True, text=True, timeout=60)
        
        end_time = time.time()
        duration = end_time - start_time
        
        print(f"Время выполнения: {duration:.2f} секунд")
        
        if result.returncode == 0:
            print("✅ Тесты совместимости прошли успешно")
            return True
        else:
            print("❌ Тесты совместимости провалились")
            print("Вывод:")
            print(result.stdout)
            print("Ошибки:")
            print(result.stderr)
            return False
            
    except subprocess.TimeoutExpired:
        print("⏰ Тесты совместимости превысили лимит времени")
        return False
    except Exception as e:
        print(f"💥 Ошибка запуска тестов совместимости: {e}")
        return False

def run_all_tests():
    """Запускает все тесты"""
    print("🚀 Запуск всех тестов системы обработки вебхуков")
    print(f"Python версия: {sys.version}")
    print(f"Рабочая директория: {os.getcwd()}")
    
    # Список модулей для тестирования
    modules = [
        'utils',
        'firestore_utils', 
        'image_utils',
        'webhook_handler'
    ]
    
    results = {}
    
    # Запускаем тесты модулей
    for module in modules:
        results[module] = run_test_module(module)
    
    # Запускаем интеграционные тесты
    results['integration'] = run_integration_tests()
    
    # Запускаем тесты совместимости
    results['compatibility'] = run_compatibility_tests()
    
    # Выводим итоговый отчет
    print(f"\n{'='*60}")
    print("ИТОГОВЫЙ ОТЧЕТ")
    print(f"{'='*60}")
    
    total_tests = len(results)
    passed_tests = sum(results.values())
    failed_tests = total_tests - passed_tests
    
    print(f"Всего тестовых наборов: {total_tests}")
    print(f"Успешно: {passed_tests}")
    print(f"Провалилось: {failed_tests}")
    print(f"Процент успеха: {(passed_tests/total_tests)*100:.1f}%")
    
    print("\nДетали:")
    for test_name, result in results.items():
        status = "✅ ПРОШЕЛ" if result else "❌ ПРОВАЛИЛСЯ"
        print(f"  {test_name}: {status}")
    
    if failed_tests == 0:
        print(f"\n🎉 ВСЕ ТЕСТЫ ПРОШЛИ УСПЕШНО!")
        return 0
    else:
        print(f"\n⚠️  {failed_tests} ТЕСТОВ ПРОВАЛИЛОСЬ")
        return 1

def run_specific_test(test_name):
    """Запускает конкретный тест"""
    if test_name == 'integration':
        return run_integration_tests()
    elif test_name == 'compatibility':
        return run_compatibility_tests()
    elif test_name in ['utils', 'firestore_utils', 'image_utils', 'webhook_handler']:
        return run_test_module(test_name)
    else:
        print(f"❌ Неизвестный тест: {test_name}")
        print("Доступные тесты: utils, firestore_utils, image_utils, webhook_handler, integration, compatibility")
        return False

if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Запуск конкретного теста
        test_name = sys.argv[1]
        success = run_specific_test(test_name)
        sys.exit(0 if success else 1)
    else:
        # Запуск всех тестов
        exit_code = run_all_tests()
        sys.exit(exit_code) 