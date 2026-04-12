"""
Скрипт импорта магазинов из YAML в SQLite.
Использование: python data/import_stores.py
"""
import os
import sys
import yaml
from datetime import datetime

# Добавляем корень проекта в путь
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from src.server.database import SessionLocal, init_db
from src.server.models import Store


def import_stores_from_yaml(yaml_path: str):
    """
    Импортировать магазины из YAML файла в SQLite.

    Args:
        yaml_path: Путь к YAML файлу
    """
    # Инициализируем БД
    init_db()
    db = SessionLocal()

    try:
        # Читаем YAML
        with open(yaml_path, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)

        if not data or 'stores' not in data:
            print("Ошибка: YAML файл должен содержать ключ 'stores'")
            return

        stores_data = data['stores']
        print(f"Найдено {len(stores_data)} магазинов в YAML")

        added = 0
        updated = 0
        skipped = 0

        for store_data in stores_data:
            # Проверяем обязательные поля
            required = ['store_code', 'store_type', 'city', 'address', 'full_address']
            for field in required:
                if field not in store_data:
                    print(f"Пропущено: отсутствует поле '{field}' в {store_data}")
                    skipped += 1
                    continue

            # Ищем существующий магазин
            existing = db.query(Store).filter(
                Store.store_code == store_data['store_code']
            ).first()

            if existing:
                # Обновляем
                for key, value in store_data.items():
                    if hasattr(existing, key):
                        setattr(existing, key, value)
                updated += 1
                print(f"Обновлён: {store_data['store_code']} - {store_data.get('name', 'Без названия')}")
            else:
                # Создаём новый
                new_store = Store(
                    store_code=store_data['store_code'],
                    store_type=store_data['store_type'],
                    city=store_data['city'],
                    address=store_data['address'],
                    full_address=store_data['full_address'],
                    name=store_data.get('name'),
                    is_active=store_data.get('is_active', True),
                    created_at=datetime.utcnow(),
                )
                db.add(new_store)
                added += 1
                print(f"Добавлен: {store_data['store_code']} - {store_data.get('name', 'Без названия')}")

        db.commit()
        print(f"\nИмпорт завершён!")
        print(f"  Добавлено: {added}")
        print(f"  Обновлено: {updated}")
        print(f"  Пропущено: {skipped}")

    except FileNotFoundError:
        print(f"Ошибка: файл не найден {yaml_path}")
    except yaml.YAMLError as e:
        print(f"Ошибка парсинга YAML: {e}")
    except Exception as e:
        print(f"Ошибка импорта: {e}")
        db.rollback()
    finally:
        db.close()


if __name__ == "__main__":
    yaml_file = os.path.join(PROJECT_ROOT, 'data', 'stores.yaml')

    if len(sys.argv) > 1:
        yaml_file = sys.argv[1]

    if not os.path.exists(yaml_file):
        print(f"Файл не найден: {yaml_file}")
        sys.exit(1)

    print(f"Импорт магазинов из: {yaml_file}")
    import_stores_from_yaml(yaml_file)
