"""
Загрузка категорий из src/data/categories.json в базу данных.
JSON содержит только корневые категории с подкатегориями.
"""

import json
from pathlib import Path
from sqlalchemy.orm import Session
from src.server.models import Category


def load_catalog_from_json(db: Session = None) -> dict:
    """
    Загрузить категории из src/data/categories.json в базу данных.

    Логика:
    1. Читает src/data/categories.json из проекта
    2. Для каждой корневой категории:
       - Проверяет наличие по magnit_id (id из JSON)
       - Если существует: обновляет name, url
       - Если новая: создаёт с parent_id=None
    3. Для каждой подкатегории:
       - Находит родителя по magnit_id
       - Если родитель не найден: логирует ошибку и пропускает
       - Если найден: создаёт/обновляет подкатегорию с parent_id

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
        # Находим файл src/data/categories.json
        project_root = Path(__file__).parent.parent.parent.parent
        json_file = project_root / "src" / "data" / "categories.json"

        if not json_file.exists():
            raise FileNotFoundError(f"Файл не найден: {json_file}")

        print(f"DEBUG: Загрузка категорий из {json_file}")

        with open(json_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        root_categories = data.get("root_categories", [])
        print(f"DEBUG: Прочитано {len(root_categories)} корневых категорий из JSON")

        scanned = 0
        added = 0
        updated = 0

        # Обрабатываем корневые категории
        for root_cat_data in root_categories:
            scanned += 1
            magnit_id = root_cat_data.get("id")

            if not magnit_id:
                print(f"WARN: Корневая категория без id: {root_cat_data.get('title')}")
                continue

            # Проверяем наличие категории
            existing = (
                db.query(Category).filter(Category.magnit_id == magnit_id).first()
            )

            if existing:
                # Обновляем существующую категорию
                existing.name = root_cat_data.get("title", existing.name)
                print(
                    f"DEBUG: Обновлена корневая категория: {existing.name} (magnit_id={magnit_id})"
                )
                updated += 1
            else:
                # Создаём новую корневую категорию
                new_cat = Category(
                    magnit_id=magnit_id,
                    name=root_cat_data.get("title", "Без названия"),
                    url="",
                    parent_id=None,  # Корневая категория
                    is_tracked=False,
                    product_count=0,
                )
                db.add(new_cat)
                print(
                    f"DEBUG: Добавлена корневая категория: {new_cat.name} (magnit_id={magnit_id})"
                )
                added += 1

            # Обрабатываем подкатегории
            subcategories = root_cat_data.get("fastCategoriesExtended", [])
            for sub_cat_data in subcategories:
                scanned += 1
                sub_magnit_id = sub_cat_data.get("id")

                if not sub_magnit_id:
                    print(f"WARN: Подкатегория без id: {sub_cat_data.get('title')}")
                    continue

                # Находим родителя
                parent = (
                    db.query(Category).filter(Category.magnit_id == magnit_id).first()
                )

                if not parent:
                    print(
                        f"WARN: Родитель не найден для подкатегории {sub_cat_data.get('title')} (parent_magnit_id={magnit_id})"
                    )
                    continue

                # Проверяем наличие подкатегории
                existing_sub = (
                    db.query(Category)
                    .filter(Category.magnit_id == sub_magnit_id)
                    .first()
                )

                if existing_sub:
                    # Обновляем существующую подкатегорию
                    existing_sub.name = sub_cat_data.get("title", existing_sub.name)
                    existing_sub.parent_id = parent.id
                    print(
                        f"DEBUG: Обновлена подкатегория: {existing_sub.name} (magnit_id={sub_magnit_id})"
                    )
                    updated += 1
                else:
                    # Создаём новую подкатегорию
                    new_sub_cat = Category(
                        magnit_id=sub_magnit_id,
                        name=sub_cat_data.get("title", "Без названия"),
                        url="",
                        parent_id=parent.id,  # Связываем с родителем
                        is_tracked=False,
                        product_count=0,
                    )
                    db.add(new_sub_cat)
                    print(
                        f"DEBUG: Добавлена подкатегория: {new_sub_cat.name} (magnit_id={sub_magnit_id}, parent_id={parent.id})"
                    )
                    added += 1

        # Коммитим все изменения
        db.commit()

        result = {
            "scanned": scanned,
            "added": added,
            "updated": updated,
        }

        print(f"INFO: Загрузка категорий завершена. Результат: {result}")
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
