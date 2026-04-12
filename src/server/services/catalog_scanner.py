"""
Сервис сканирования каталога товаров.
Сканирует категории и товары через API Магнита, сохраняет в БД.
"""
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Optional
import json

from src.server.models import Category, Product, PriceHistory, ScanJob
from src.server.services.magnit_api import MagnitAPIClient


class CatalogScanner:
    """Сканирование каталога товаров и категорий."""

    def __init__(self, db: Session, store_code: str, job_id: Optional[int] = None):
        self.db = db
        self.store_code = store_code
        self.job_id = job_id
        self.api = MagnitAPIClient(store_code=store_code)

    def _update_job_progress(self, progress: int, message: str):
        """Обновить прогресс задания."""
        if self.job_id:
            self.db.query(ScanJob).filter(ScanJob.id == self.job_id).update({
                "progress": progress,
                "progress_message": message,
            })
            self.db.commit()

    def scan_categories(self) -> dict:
        """
        Сканировать все категории каталога.

        Returns:
            {"scanned": N, "added": N, "updated": N}
        """
        if self.job_id:
            self._update_job_progress(5, "Получение списка категорий...")

        try:
            categories_data = self.api.get_categories(store_code=self.store_code)
        except Exception as e:
            if self.job_id:
                self._update_job_progress(-1, f"Ошибка получения категорий: {str(e)}")
            raise

        added = 0
        updated = 0
        total = len(categories_data)

        if self.job_id:
            self._update_job_progress(10, f"Получено {total} категорий, сохранение...")

        for i, cat_data in enumerate(categories_data):
            # Ищем существующую категорию
            existing = self.db.query(Category).filter(
                Category.category_id == cat_data["category_id"],
                Category.store_code == self.store_code,
            ).first()

            if existing:
                # Обновляем
                existing.name = cat_data.get("name", existing.name)
                existing.product_count = cat_data.get("product_count", existing.product_count)
                if cat_data.get("parent_id"):
                    existing.parent_id = cat_data["parent_id"]
                updated += 1
            else:
                # Создаём
                new_cat = Category(
                    category_id=cat_data["category_id"],
                    name=cat_data.get("name", "Без названия"),
                    parent_id=cat_data.get("parent_id"),
                    store_code=self.store_code,
                    product_count=cat_data.get("product_count", 0),
                )
                self.db.add(new_cat)
                added += 1

            # Коммитим каждые 50 записей
            if (i + 1) % 50 == 0:
                self.db.commit()

        self.db.commit()

        result = {"scanned": total, "added": added, "updated": updated}

        if self.job_id:
            self._update_job_progress(20, f"Категории сохранены: {total}")

        return result

    def scan_products(
        self,
        category_ids: Optional[list[int]] = None,
        tracked_only: bool = False,
    ) -> dict:
        """
        Сканировать товары из указанных категорий.

        Args:
            category_ids: ID категорий (если None — все отслеживаемые)
            tracked_only: Если True, сканировать только отслеживаемые категории

        Returns:
            {"scanned": N, "added": N, "updated": N, "price_changes": N}
        """
        # Определяем категории
        if category_ids is None:
            query = self.db.query(Category).filter(Category.store_code == self.store_code)
            if tracked_only:
                query = query.filter(Category.is_tracked == True)  # noqa: E712
            categories = query.all()
            category_ids = [cat.category_id for cat in categories]

        if not category_ids:
            return {"scanned": 0, "added": 0, "updated": 0, "price_changes": 0}

        if self.job_id:
            self._update_job_progress(
                25,
                f"Сканирование товаров из {len(category_ids)} категорий..."
            )

        total_added = 0
        total_updated = 0
        total_price_changes = 0
        total_scanned = 0

        # Сканируем по одной категории за раз для лучшего контроля прогресса
        for cat_idx, cat_id in enumerate(category_ids):
            progress_base = 25 + int((cat_idx / len(category_ids)) * 70)
            if self.job_id:
                cat = self.db.query(Category).filter(
                    Category.category_id == cat_id,
                    Category.store_code == self.store_code,
                ).first()
                cat_name = cat.name if cat else f"ID:{cat_id}"
                self._update_job_progress(
                    progress_base,
                    f"Категория: {cat_name}..."
                )

            # Пагинация
            offset = 0
            has_more = True
            while has_more:
                try:
                    result = self.api.get_products(
                        category_ids=[cat_id],
                        store_code=self.store_code,
                        limit=50,
                        offset=offset,
                    )
                except Exception as e:
                    print(f"Ошибка получения товаров (категория {cat_id}): {e}")
                    break

                products = result.get("products", [])
                has_more = result.get("hasMore", False)
                offset = result.get("next_offset", offset + 50)

                if not products:
                    break

                added, updated, price_changes = self._save_products(products, cat_id)
                total_added += added
                total_updated += updated
                total_price_changes += price_changes
                total_scanned += len(products)

                # Промежуточный коммит
                self.db.commit()

        # Обновляем дату сканирования категорий
        for cat_id in category_ids:
            cat = self.db.query(Category).filter(
                Category.category_id == cat_id,
                Category.store_code == self.store_code,
            ).first()
            if cat:
                cat.last_scanned = datetime.utcnow()

        self.db.commit()

        result = {
            "scanned": total_scanned,
            "added": total_added,
            "updated": total_updated,
            "price_changes": total_price_changes,
        }

        if self.job_id:
            self._update_job_progress(
                95,
                f"Товары сохранены: {total_scanned} шт."
            )

        return result

    def _save_products(self, products: list[dict], category_id: int) -> tuple[int, int, int]:
        """
        Сохранить товары в БД.

        Returns:
            (added_count, updated_count, price_change_count)
        """
        added = 0
        updated = 0
        price_changes = 0

        # Находим category_id в БД
        cat = self.db.query(Category).filter(
            Category.category_id == category_id,
            Category.store_code == self.store_code,
        ).first()
        db_category_id = cat.id if cat else None

        for product_data in products:
            # Ищем существующий товар
            existing = self.db.query(Product).filter(
                Product.product_id == product_data["product_id"],
                Product.store_code == self.store_code,
            ).first()

            if existing:
                # Проверяем изменение цены
                old_price = existing.price
                new_price = product_data["price"]

                # Обновляем товар
                existing.name = product_data.get("name", existing.name)
                existing.price = new_price
                existing.old_price = product_data.get("old_price")
                existing.sku = product_data.get("sku", existing.sku)
                existing.unit = product_data.get("unit", existing.unit)
                existing.image_url = product_data.get("image_url", existing.image_url)
                existing.in_stock = product_data.get("in_stock", existing.in_stock)
                existing.last_seen = datetime.utcnow()

                # Записываем историю если цена изменилась
                if abs(old_price - new_price) > 0.01:  # Изменение > 1 копейки
                    change_type = "decreased" if new_price < old_price else "increased"
                    price_changes += 1
                    existing.last_price_change = datetime.utcnow()

                    history = PriceHistory(
                        product_id=existing.product_id,
                        store_code=self.store_code,
                        price=new_price,
                        old_price=product_data.get("old_price"),
                        recorded_at=datetime.utcnow(),
                        change_type=change_type,
                    )
                    self.db.add(history)

                updated += 1
            else:
                # Новый товар
                new_product = Product(
                    product_id=product_data["product_id"],
                    name=product_data.get("name", "Без названия"),
                    sku=product_data.get("sku"),
                    category_id=db_category_id,
                    store_code=self.store_code,
                    price=product_data["price"],
                    old_price=product_data.get("old_price"),
                    currency="₽",
                    unit=product_data.get("unit", "шт"),
                    image_url=product_data.get("image_url"),
                    in_stock=product_data.get("in_stock", True),
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                )
                self.db.add(new_product)
                added += 1

                # Первичная запись в историю
                history = PriceHistory(
                    product_id=new_product.product_id,
                    store_code=self.store_code,
                    price=new_product.price,
                    old_price=new_product.old_price,
                    recorded_at=datetime.utcnow(),
                    change_type="initial",
                )
                self.db.add(history)

        return added, updated, price_changes

    def close(self):
        """Закрыть клиент."""
        self.api.close()
