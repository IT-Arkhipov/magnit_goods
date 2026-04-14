"""
Загрузка категорий из magnit_catalog.json в базу данных.
JSON содержит только корневые категории (18 шт).
Подкатегории получаются динамически из API при сканировании.
"""

import json
import os
from pathlib import Path
from sqlalchemy.orm import Session
from src.server.models import Category


def load_catalog_from_json(db: Session = None) -> dict:
    """
    Загрузить ТОЛЬКО КОРНЕВЫЕ категории из magnit_catalog.json в базу данных.

    Логика:
    1. Читает magnit_catalog.json из корня проекта
    2. Для каждой корневой категории:
       - Проверяет наличие по magnit_id
       - Если существует: обновляет name, url
       - Если новая: создаёт с parent_id=None
    3. Подкатегории (subcategories в JSON) ИГНОРИРУЮТСЯ
       - Они будут получены динамически из API при сканировании

    Returns:
        {"scanned": N, "added": N, "updated": N}
    """
    from src.server.database import SessionLocal

    if db is None:
        db = SessionLocal()
        close_session = True
    else:
        close_session = False

    try:
        # Находим файл magnit_catalog.json
        project_root = Path(__file__).parent.parent.parent.parent
        json_file = project_root / "magnit_catalog.json"

        if not json_file.exists():
            raise FileNotFoundError(f"Файл не найден: {json_file}")

        print(f"DEBUG: Загрузка КОРНЕВЫХ категорий из {json_file}")

        with open(json_file, "r", encoding="utf-8") as f:
            categories_data = json.load(f)

        print(f"DEBUG: Прочитано {len(categories_data)} корневых категорий из JSON")

        scanned = 0
        added = 0
        updated = 0

        # Обрабатываем ТОЛЬКО корневые категории
        for root_cat_data in categories_data:
            scanned += 1
            magnit_id = root_cat_data.get("magnit_id")

            if not magnit_id:
                print(
                    f"WARN: Корневая категория без magnit_id: {root_cat_data.get('name')}"
                )
                continue

            # Проверяем наличие категории
            existing = (
                db.query(Category).filter(Category.magnit_id == magnit_id).first()
            )

            if existing:
                # Обновляем существующую категорию
                existing.name = root_cat_data.get("name", existing.name)
                existing.url = root_cat_data.get("url", existing.url)
                print(
                    f"DEBUG: Обновлена корневая категория: {existing.name} (magnit_id={magnit_id})"
                )
                updated += 1
            else:
                # Создаём новую корневую категорию
                new_cat = Category(
                    magnit_id=magnit_id,
                    name=root_cat_data.get("name", "Без названия"),
                    url=root_cat_data.get("url", ""),
                    parent_id=None,  # Корневая категория
                    is_tracked=False,
                    product_count=0,
                )
                db.add(new_cat)
                print(
                    f"DEBUG: Добавлена корневая категория: {new_cat.name} (magnit_id={magnit_id})"
                )
                added += 1

        # Коммитим все изменения
        db.commit()

        result = {
            "scanned": scanned,
            "added": added,
            "updated": updated,
        }

        print(f"INFO: Загрузка корневых категорий завершена. Результат: {result}")
        print(f"INFO: Подкатегории будут получены динамически из API при сканировании")
        return result

    except Exception as e:
        db.rollback()
        print(f"ERROR: Ошибка при загрузке категорий: {str(e)}")
        import traceback

        print(traceback.format_exc())
        raise
    finally:
        if close_session:
            db.close()
