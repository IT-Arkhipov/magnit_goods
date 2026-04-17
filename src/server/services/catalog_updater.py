"""
Сервис для обновления каталога категорий из API Магнита.
"""

import os
import json
import time
from pathlib import Path
from typing import Dict, List, Tuple
import requests
from src.server.database import SessionLocal
from src.server.models import Category, Store


class CatalogUpdater:
    """Обновляет каталог категорий из API Магнита."""

    def __init__(self, store_code: str = None, store_type: str = None):
        self.base_url = "https://magnit.ru/webgate/v2/goods/search"
        self.store_code = store_code or "210117"
        self.store_type = store_type or "9"
        self.rate_limit = 0.5  # seconds between requests
        self._last_request_time = 0
        self.categories_file = (
            Path(__file__).parent.parent.parent / "data" / "categories.json"
        )
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)

    def _rate_limit_wait(self):
        """Пауза между запросами для соблюдения rate limiting."""
        if self._last_request_time > 0:
            elapsed = time.time() - self._last_request_time
            if elapsed < self.rate_limit:
                time.sleep(self.rate_limit - elapsed)
        self._last_request_time = time.time()

    def fetch_category_data(self, category_id: int) -> Dict:
        """Получить данные категории из API Магнита."""
        payload = {
            "sort": {"order": "desc", "type": "popularity"},
            "pagination": {"limit": 32, "offset": 0},
            "categories": [category_id],
            "includeAdultGoods": True,
            "storeCode": self.store_code,
            "storeType": self.store_type,
            "catalogType": "1",
        }

        try:
            self._rate_limit_wait()
            response = self.session.post(self.base_url, json=payload, timeout=15)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error fetching category {category_id}: {e}")
            return None

    def load_root_categories_from_file(self) -> List[Dict]:
        """Загрузить корневые категории из JSON файла."""
        if not self.categories_file.exists():
            print(f"Categories file not found: {self.categories_file}")
            return []
        try:
            with open(self.categories_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return [{"id": cat["id"], "title": cat["title"]} for cat in data]
        except Exception as e:
            print(f"Error loading categories from file: {e}")
            return []

    def update_category_from_api(
        self, db, category: Category, api_data: Dict
    ) -> Tuple[int, int, int]:
        """
        Обновить категорию и её подкатегории из данных API.
        Возвращает (updated_count, added_count, deleted_count)
        """
        updated = 0
        added = 0
        deleted = 0

        if not api_data or "category" not in api_data:
            return updated, added, deleted

        cat_info = api_data["category"]
        subcats_from_api = api_data.get("fastCategoriesExtended", [])

        # Обновляем название корневой категории если изменилось
        if category.name != cat_info.get("title", category.name):
            category.name = cat_info["title"]
            db.commit()
            updated += 1

        # Получаем текущие подкатегории из БД
        current_children = (
            db.query(Category).filter(Category.parent_id == category.id).all()
        )
        current_ids = {child.magnit_id: child for child in current_children}
        api_ids = {sub["id"] for sub in subcats_from_api}

        # Удаляем подкатегории, которых нет в API
        for magnit_id, child in current_ids.items():
            if magnit_id not in api_ids:
                db.delete(child)
                deleted += 1

        db.commit()

        # Добавляем или обновляем подкатегории из API
        for sub in subcats_from_api:
            sub_id = sub["id"]
            sub_name = sub["title"]

            if sub_id in current_ids:
                # Обновляем существующую подкатегорию
                child = current_ids[sub_id]
                if child.name != sub_name:
                    child.name = sub_name
                    db.commit()
                    updated += 1
            else:
                # Добавляем новую подкатегорию
                new_child = Category(
                    name=sub_name, url="", magnit_id=sub_id, parent_id=category.id
                )
                db.add(new_child)
                added += 1

        db.commit()
        return updated, added, deleted

    def update_all_categories(self) -> Dict:
        """
        Обновить все корневые категории из JSON файла через API Магнита.
        Возвращает статистику обновления.
        """
        db = SessionLocal()

        try:
            root_categories_from_file = self.load_root_categories_from_file()
            if not root_categories_from_file:
                return {
                    "total": 0,
                    "processed": 0,
                    "updated": 0,
                    "added": 0,
                    "deleted": 0,
                    "errors": ["Categories file not found or empty"],
                }

            stats = {
                "total": len(root_categories_from_file),
                "processed": 0,
                "updated": 0,
                "added": 0,
                "deleted": 0,
                "errors": [],
            }

            for cat_data in root_categories_from_file:
                try:
                    magnit_id = cat_data["id"]
                    expected_title = cat_data["title"]

                    print(f"Updating category: {expected_title} ({magnit_id})")

                    api_data = self.fetch_category_data(magnit_id)

                    if not api_data:
                        stats["errors"].append(
                            f"Failed to fetch data for {expected_title}"
                        )
                        stats["processed"] += 1
                        continue

                    cat_info = api_data.get("category", {})
                    api_title = cat_info.get("title", expected_title)

                    db_category = (
                        db.query(Category)
                        .filter(Category.magnit_id == magnit_id)
                        .filter(Category.parent_id.is_(None))
                        .first()
                    )

                    if not db_category:
                        db_category = Category(
                            magnit_id=magnit_id, name=api_title, url="", parent_id=None
                        )
                        db.add(db_category)
                        db.commit()
                        db.refresh(db_category)
                        stats["added"] += 1

                    if db_category.name != api_title:
                        db_category.name = api_title
                        db.commit()
                        stats["updated"] += 1

                    if api_data.get("fastCategoriesExtended"):
                        upd, add, deleted = self.update_category_from_api(
                            db, db_category, api_data
                        )
                        stats["updated"] += upd
                        stats["added"] += add
                        stats["deleted"] += deleted

                    stats["processed"] += 1

                except Exception as e:
                    error_msg = (
                        f"Error updating {cat_data.get('title', 'unknown')}: {str(e)}"
                    )
                    print(error_msg)
                    stats["errors"].append(error_msg)
                    stats["processed"] += 1

            return stats

        finally:
            db.close()


def update_catalog_from_api(store_code: str = None, store_type: str = None) -> Dict:
    """
    Обновить каталог из API Магнита.
    Возвращает статистику обновления.
    """
    updater = CatalogUpdater(store_code=store_code, store_type=store_type)
    return updater.update_all_categories()
