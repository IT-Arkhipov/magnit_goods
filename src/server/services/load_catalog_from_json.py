"""
Загрузка корневых категорий из src/data/categories.json в базу данных.
Файл — плоский массив [{"id": <magnit_id>, "title": <название>}]; подкатегории
в нём нет, их добавляет синхронизация с API (CatalogScanner.scan_categories).
"""

import logging

from sqlalchemy.orm import Session
from src.server.models import Category
from src.server.services.catalog_updater import CATEGORIES_FILE, load_root_categories

logger = logging.getLogger(__name__)


def load_catalog_from_json(db: Session = None) -> dict:
    """
    Загрузить корневые категории из src/data/categories.json в базу данных.

    Логика:
    - для каждого элемента файла ищет категорию по magnit_id (id из JSON);
    - существующую не пересоздаёт: при изменении названия обновляет его,
      is_tracked, родителя и подкатегории не трогает;
    - новую создаёт корневой (parent_id=None, is_tracked=False).

    Raises:
        FileNotFoundError: файла categories.json нет.

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
        if not CATEGORIES_FILE.exists():
            raise FileNotFoundError(f"Файл не найден: {CATEGORIES_FILE}")

        roots = load_root_categories(CATEGORIES_FILE)
        logger.info("Загрузка категорий из %s: %s корневых", CATEGORIES_FILE, len(roots))

        # Существующие категории по magnit_id (при дублях — запись с минимальным id)
        existing = {}
        for cat in db.query(Category).filter(Category.magnit_id.isnot(None)).order_by(Category.id):
            existing.setdefault(cat.magnit_id, cat)

        scanned = added = updated = 0
        for item in roots:
            scanned += 1
            magnit_id = item.get("id")
            if not magnit_id:
                logger.warning("Корневая категория без id: %s", item.get("title"))
                continue

            title = item.get("title") or "Без названия"
            category = existing.get(magnit_id)
            if category is not None:
                if category.name != title:
                    category.name = title
                    updated += 1
            else:
                category = Category(
                    magnit_id=magnit_id,
                    name=title,
                    url="",
                    parent_id=None,
                    is_tracked=False,
                    product_count=0,
                )
                db.add(category)
                existing[magnit_id] = category
                added += 1

        db.commit()

        result = {"scanned": scanned, "added": added, "updated": updated}
        logger.info("Загрузка категорий завершена: %s", result)
        return result

    except Exception:
        db.rollback()
        logger.exception("Ошибка при загрузке категорий")
        raise
    finally:
        if close_session:
            db.close()
