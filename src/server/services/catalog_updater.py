"""
Сервис для обновления каталога категорий из API Магнита.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional
from src.server.database import SessionLocal
from src.server.models import Category, Product
from src.server.services.magnit_api import MagnitAPIClient

logger = logging.getLogger(__name__)

# Корневые категории: плоский массив [{"id": ..., "title": ...}]
CATEGORIES_FILE = Path(__file__).parent.parent.parent / "data" / "categories.json"


def load_root_categories(categories_file: Path = CATEGORIES_FILE) -> List[Dict]:
    """Загрузить корневые категории из JSON-файла (без обращения к API и магазину).

    Возвращает [{"id", "title"}]; при отсутствии файла или ошибке чтения — [].
    """
    if not categories_file.exists():
        logger.warning(f"Categories file not found: {categories_file}")
        return []
    try:
        with open(categories_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [{"id": cat["id"], "title": cat["title"]} for cat in data]
    except Exception as e:
        logger.error(f"Error loading categories from file: {e}")
        return []


class CatalogUpdater:
    """Обновляет каталог категорий из API Магнита."""

    def __init__(self, store_code: Optional[str] = None, store_type: Optional[str] = None):
        # Запросы идут через MagnitAPIClient: единый формат типа магазина,
        # заголовки и ограничение частоты запросов. Код магазина — из аргумента
        # или из STORE_CODE; захардкоженного магазина по умолчанию нет.
        self.client = MagnitAPIClient(store_code=store_code, store_type=store_type)
        if not self.client.store_code:
            self.client.close()
            raise ValueError("Не выбран магазин: задайте STORE_CODE или передайте store_code")
        self.store_code = self.client.store_code
        self.store_type = self.client.store_type
        self.categories_file = CATEGORIES_FILE

    def fetch_category_data(self, category_id: int) -> Optional[Dict]:
        """Получить данные категории из API Магнита."""
        return self.client.fetch_category_raw(category_id)

    def close(self):
        """Закрыть HTTP-клиент."""
        self.client.close()

    def load_root_categories_from_file(self) -> List[Dict]:
        """Загрузить корневые категории из JSON файла."""
        return load_root_categories(self.categories_file)

    def replace_all_categories(self) -> Dict:
        """
        Полная замена всех категорий: получить все из API, затем синхронизировать БД
        по magnit_id (upsert): существующие категории сохраняют внутренний id и
        is_tracked, новые добавляются с is_tracked=False, исчезнувшие из API удаляются.
        Ничего не меняет в БД, если хотя бы одна корневая категория не получена.

        Возвращает статистику или ошибку.
        """
        db = SessionLocal()

        try:
            # Шаг 1: Загрузить корневые категории из файла
            root_categories_from_file = self.load_root_categories_from_file()
            if not root_categories_from_file:
                return {
                    "status": "error",
                    "errors": ["Categories file not found or empty"],
                }

            logger.debug(
                f"DEBUG: Loaded {len(root_categories_from_file)} root categories from file"
            )

            # Шаг 2: Собрать ВСЕ категории из API (корневые + подкатегории)
            all_categories_data = []  # [(magnit_id, title, parent_magnit_id), ...]
            api_errors = []

            for cat_data in root_categories_from_file:
                try:
                    magnit_id = cat_data["id"]
                    expected_title = cat_data["title"]

                    logger.debug(f"DEBUG: Fetching category {expected_title} ({magnit_id})")

                    api_data = self.fetch_category_data(magnit_id)

                    if not api_data:
                        api_errors.append(f"Failed to fetch data for {expected_title}")
                        continue

                    cat_info = api_data.get("category", {})
                    api_title = cat_info.get("title", expected_title)

                    # Добавить корневую категорию
                    all_categories_data.append((magnit_id, api_title, None))

                    # Добавить подкатегории
                    subcats = api_data.get("fastCategoriesExtended", [])
                    for sub in subcats:
                        sub_id = sub["id"]
                        sub_title = sub["title"]
                        all_categories_data.append((sub_id, sub_title, magnit_id))

                except Exception as e:
                    error_msg = (
                        f"Error fetching {cat_data.get('title', 'unknown')}: {str(e)}"
                    )
                    logger.error(error_msg)
                    api_errors.append(error_msg)

            # Шаг 3: Если есть ошибки API - вернуть ошибку, не менять БД
            if api_errors:
                return {
                    "status": "error",
                    "errors": api_errors,
                    "message": f"Failed to fetch {len(api_errors)} categories from API",
                }

            logger.debug(
                f"DEBUG: Successfully fetched {len(all_categories_data)} categories from API"
            )

            # Шаг 4: Upsert по magnit_id в одной транзакции.
            # Внутренние ID и is_tracked существующих категорий сохраняются,
            # поэтому Product.category_id остаётся валидным.
            unique_data = []
            seen_magnit_ids = set()
            for magnit_id, title, parent_magnit_id in all_categories_data:
                if magnit_id in seen_magnit_ids:
                    logger.warning(
                        f"WARN: Дубль magnit_id={magnit_id} ({title}) в ответе API — пропущен"
                    )
                    continue
                seen_magnit_ids.add(magnit_id)
                unique_data.append((magnit_id, title, parent_magnit_id))

            # Существующие категории: при дублях magnit_id остаётся запись с минимальным id
            existing_by_magnit_id = {}
            duplicate_rows = []
            for cat in db.query(Category).order_by(Category.id).all():
                if cat.magnit_id is not None and cat.magnit_id not in existing_by_magnit_id:
                    existing_by_magnit_id[cat.magnit_id] = cat
                else:
                    duplicate_rows.append(cat)

            added_count = 0
            updated_count = 0  # переименованные или перенесённые
            kept_ids = set()
            magnit_to_db_id = {}

            # Сначала корневые категории
            for magnit_id, title, parent_magnit_id in unique_data:
                if parent_magnit_id is not None:
                    continue
                cat = existing_by_magnit_id.get(magnit_id)
                if cat is None:
                    cat = Category(
                        magnit_id=magnit_id, name=title, url="", parent_id=None,
                        is_tracked=False,
                    )
                    db.add(cat)
                    db.flush()  # получить ID
                    added_count += 1
                elif cat.name != title or cat.parent_id is not None:
                    cat.name = title
                    cat.parent_id = None
                    updated_count += 1
                magnit_to_db_id[magnit_id] = cat.id
                kept_ids.add(cat.id)

            # Затем подкатегории
            for magnit_id, title, parent_magnit_id in unique_data:
                if parent_magnit_id is None:
                    continue
                parent_id = magnit_to_db_id.get(parent_magnit_id)
                if parent_id is None:
                    logger.warning(
                        f"WARN: Parent category {parent_magnit_id} not found for {title}"
                    )
                    continue
                cat = existing_by_magnit_id.get(magnit_id)
                if cat is None:
                    cat = Category(
                        magnit_id=magnit_id, name=title, url="", parent_id=parent_id,
                        is_tracked=False,
                    )
                    db.add(cat)
                    db.flush()
                    added_count += 1
                elif cat.name != title or cat.parent_id != parent_id:
                    cat.name = title
                    cat.parent_id = parent_id
                    updated_count += 1
                kept_ids.add(cat.id)

            # Шаг 5: Удалить категории, которых нет в ответе API.
            # Товары дублей переносим на оставшуюся запись, товары остальных
            # удаляемых категорий отвязываем (category_id = NULL).
            removed_ids = []
            for cat in db.query(Category).all():
                if cat.id in kept_ids:
                    continue
                removed_ids.append(cat.id)
            for dup in duplicate_rows:
                keeper = existing_by_magnit_id.get(dup.magnit_id) if dup.magnit_id is not None else None
                if keeper is not None and keeper.id in kept_ids:
                    db.query(Product).filter(Product.category_id == dup.id).update(
                        {"category_id": keeper.id}, synchronize_session=False
                    )
            if removed_ids:
                db.query(Product).filter(Product.category_id.in_(removed_ids)).update(
                    {"category_id": None}, synchronize_session=False
                )
                db.query(Category).filter(Category.id.in_(removed_ids)).delete(
                    synchronize_session=False
                )

            db.commit()

            return {
                "status": "success",
                "total": len(unique_data),
                "added": added_count,
                "updated": updated_count,
                "deleted": len(removed_ids),
                "errors": [],
            }

        except Exception as e:
            db.rollback()
            error_msg = f"Critical error during category replacement: {str(e)}"
            logger.error(error_msg)
            import traceback

            traceback.print_exc()

            return {
                "status": "error",
                "errors": [error_msg],
            }

        finally:
            db.close()


def replace_catalog_from_api(store_code: str = None, store_type: str = None) -> Dict:
    """
    Полная замена каталога из API Магнита.
    Сначала получает все категории, затем очищает БД и заполняет заново.
    Возвращает статистику или ошибку.
    """
    updater = CatalogUpdater(store_code=store_code, store_type=store_type)
    try:
        return updater.replace_all_categories()
    finally:
        updater.close()
