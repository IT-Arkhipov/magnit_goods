"""
Скрипт обновления категорий из API Магнита.
Обновляет названия корневых категорий и подкатегории в БД.
"""

import json
import time
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.server.database import SessionLocal
from src.server.models import Category
from src.server.services.magnit_api import MagnitAPIClient
from dotenv import load_dotenv

load_dotenv()

CATEGORIES_FILE = Path("src/data/categories.json")


def main():
    store_code = os.getenv("STORE_CODE", "992104")
    store_type = os.getenv("STORE_TYPE", "6")

    print(f"Store: {store_code}, Type: {store_type}")

    with open(CATEGORIES_FILE, "r", encoding="utf-8") as f:
        categories_data = json.load(f)

    root_categories = categories_data.get("root_categories", [])
    print(f"Загружено {len(root_categories)} корневых категорий")

    # Получить список валидных magnit_id из JSON
    valid_ids = [cat["id"] for cat in root_categories]

    api = MagnitAPIClient(store_code=store_code, store_type=store_type)

    db = SessionLocal()

    # Удалить категории с magnit_id НЕ в JSON
    orphans = db.query(Category).filter(~Category.magnit_id.in_(valid_ids)).all()
    print(f"Удаляю {len(orphans)} лишних категорий из БД")
    for cat in orphans:
        children = db.query(Category).filter(Category.parent_id == cat.id).all()
        for child in children:
            db.delete(child)
        db.delete(cat)
    db.commit()

    # Создать корневые категории из JSON, если их нет в БД
    for cat in root_categories:
        existing = (
            db.query(Category)
            .filter(Category.magnit_id == cat["id"], Category.parent_id.is_(None))
            .first()
        )
        if not existing:
            new_cat = Category(
                name=cat["title"],
                url="",
                magnit_id=cat["id"],
            )
            db.add(new_cat)
            print(f"Создана категория: {cat['title']} (magnit_id={cat['id']})")
    db.commit()

    updated_count = 0

    for cat in root_categories:
        cat_id = cat["id"]
        cat_title = cat["title"]

        print(f"\n[{cat_id}] {cat_title}")

        payload = {
            "sort": {"order": "desc", "type": "popularity"},
            "pagination": {"limit": 32, "offset": 0},
            "categories": [cat_id],
            "includeAdultGoods": True,
            "storeCode": store_code,
            "storeType": store_type,
            "catalogType": "1",
        }

        try:
            url = f"{api.base_url}/webgate/v2/goods/search"
            response = api.session.post(url, json=payload, timeout=15)
            response.raise_for_status()
            data = response.json()

            if "category" in data:
                api_cat = data["category"]
                api_title = api_cat.get("title")
                print(f"  API title: {api_title}")

                # Обновить название корневой категории если изменилось
                if api_title and api_title != cat_title:
                    cat["title"] = api_title
                    print(f"  Updated JSON: {cat_title} -> {api_title}")
                    updated_count += 1

                # Найти корневую категорию в БД и обновить подкатегории
                db_cat = (
                    db.query(Category)
                    .filter(Category.magnit_id == cat_id, Category.parent_id.is_(None))
                    .first()
                )

                if db_cat:
                    if db_cat.name != api_title:
                        db_cat.name = api_title
                        db.commit()
                        print(f"  Updated DB name: {db_cat.name} -> {api_title}")

                # Обработка подкатегорий
                subcats = data.get("fastCategoriesExtended", [])
                print(f"  Subcategories: {len(subcats)}")

                if subcats:
                    # Получить текущие подкатегории из БД
                    current_children = (
                        db.query(Category)
                        .filter(Category.parent_id == (db_cat.id if db_cat else None))
                        .all()
                        if db_cat
                        else []
                    )

                    current_ids = {child.magnit_id: child for child in current_children}
                    api_ids = {sub["id"] for sub in subcats}

                    # Удалить старые подкатегории
                    for magnit_id, child in current_ids.items():
                        if magnit_id not in api_ids:
                            print(f"    - Delete: {child.name}")
                            db.delete(child)

                    db.commit()

                    # Добавить/обновить подкатегории
                    for sub in subcats:
                        sub_id = sub["id"]
                        sub_name = sub["title"]

                        if sub_id in current_ids:
                            child = current_ids[sub_id]
                            if child.name != sub_name:
                                child.name = sub_name
                                db.commit()
                                print(f"    ~ Update: {sub_name}")
                        else:
                            new_sub = Category(
                                name=sub_name,
                                url="",
                                magnit_id=sub_id,
                                parent_id=db_cat.id if db_cat else None,
                            )
                            db.add(new_sub)
                            db.commit()
                            print(f"    + Add: {sub_name}")

            time.sleep(0.5)

        except Exception as e:
            print(f"  Error: {e}")

    api.close()
    db.close()

    # Сохранить обновлённый JSON
    categories_data["timestamp"] = time.strftime("%Y-%m-%d")
    with open(CATEGORIES_FILE, "w", encoding="utf-8") as f:
        json.dump(categories_data, f, ensure_ascii=False, indent=2)

    print(f"\nDone! Updated {updated_count} categories")
    print(f"Categories JSON updated: {CATEGORIES_FILE}")


if __name__ == "__main__":
    main()
