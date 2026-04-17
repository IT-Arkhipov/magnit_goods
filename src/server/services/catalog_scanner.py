"""
Сервис сканирования каталога товаров.
Сканирует товары через API Магнита по категориям.
"""

from sqlalchemy.orm import Session
from datetime import datetime, date, timedelta
from typing import Optional, Dict
import time
import os

from src.server.models import (
    Category,
    Product,
    PriceHistory,
    ScanJob,
    DailyPriceSnapshot,
)
from src.server.services.magnit_api import MagnitAPIClient


class CatalogScanner:
    """Сканирование каталога товаров и категорий."""

    def __init__(
        self,
        db: Session,
        store_code: Optional[str] = None,
        store_type: Optional[str] = None,
        job_id: Optional[int] = None,
    ):
        self.db = db
        self.store_code = store_code
        self.store_type = store_type or os.getenv("STORE_TYPE", "MM")
        self.job_id = job_id
        self.api = (
            MagnitAPIClient(store_code=store_code, store_type=self.store_type)
            if store_code
            else None
        )

    def _update_job_progress(self, progress: int, message: str):
        """Обновить прогресс задания."""
        if self.job_id:
            self.db.query(ScanJob).filter(ScanJob.id == self.job_id).update(
                {
                    "progress": progress,
                    "progress_message": message,
                }
            )
            self.db.commit()

    def scan_categories(self) -> dict:
        """
        Сканировать подкатегории из API Магнита для всех корневых категорий.

        Логика:
        1. Получает все корневые категории из БД
        2. Для каждой корневой категории вызывает API с её magnit_id
        3. Получает category.title + fastCategoriesExtended (подкатегории)
        4. Обновляет название корневой категории
        5. Добавляет/обновляет/удаляет подкатегории (полная синхронизация)

        Returns:
            {"scanned": N, "added": N, "updated": N, "deleted": N}
        """
        if not self.api or not self.store_code:
            raise ValueError("store_code не указан")

        if self.job_id:
            self._update_job_progress(5, "Получение списка корневых категорий из БД...")

        # Получаем все корневые категории из БД
        root_categories = (
            self.db.query(Category).filter(Category.parent_id.is_(None)).all()
        )

        if self.job_id:
            self._update_job_progress(
                10, f"Найдено {len(root_categories)} корневых категорий, обновление..."
            )

        added = 0
        updated = 0
        deleted = 0
        total_processed = 0

        for i, root_cat in enumerate(root_categories):
            if not root_cat.magnit_id:
                print(f"DEBUG: Пропуск корневой категории без magnit_id: {root_cat.name}")
                continue

            try:
                # Вызываем API с magnit_id корневой категории
                result = self.api.search(
                    store_code=self.store_code,
                    category_ids=[root_cat.magnit_id],
                    limit=32,
                    offset=0,
                )

                # API возвращает товары в items, но нам нужны fastCategoriesExtended
                # Поэтому делаем отдельный запрос для получения подкатегорий
                # (search() с category_ids возвращает товары, а не категории)
                # Нужно напрямую вызвать API для получения подкатегорий
                api_data = self._fetch_category_data(root_cat.magnit_id)

                if not api_data or "category" not in api_data:
                    print(f"WARN: Нет данных для категории {root_cat.name}")
                    continue

                cat_info = api_data["category"]
                subcats_from_api = api_data.get("fastCategoriesExtended", [])

                # Обновляем название корневой категории если изменилось
                if root_cat.name != cat_info.get("title", root_cat.name):
                    root_cat.name = cat_info["title"]
                    self.db.commit()
                    updated += 1

                # Получаем текущие подкатегории из БД
                current_children = (
                    self.db.query(Category)
                    .filter(Category.parent_id == root_cat.id)
                    .all()
                )
                current_ids = {child.magnit_id: child for child in current_children}
                api_ids = {sub["id"] for sub in subcats_from_api}

                # Удаляем подкатегории, которых нет в API
                for magnit_id, child in current_ids.items():
                    if magnit_id not in api_ids:
                        print(f"DEBUG: Удалена подкатегория: {child.name} (magnit_id={magnit_id})")
                        self.db.delete(child)
                        deleted += 1

                self.db.commit()

                # Добавляем или обновляем подкатегории из API
                for sub in subcats_from_api:
                    sub_id = sub["id"]
                    sub_name = sub["title"]

                    if sub_id in current_ids:
                        # Обновляем существующую подкатегорию
                        child = current_ids[sub_id]
                        if child.name != sub_name:
                            child.name = sub_name
                            self.db.commit()
                            updated += 1
                    else:
                        # Добавляем новую подкатегорию
                        new_child = Category(
                            name=sub_name,
                            url="",
                            magnit_id=sub_id,
                            parent_id=root_cat.id,
                        )
                        self.db.add(new_child)
                        added += 1
                        print(f"DEBUG: Добавлена подкатегория: {sub_name} (magnit_id={sub_id})")

                self.db.commit()
                total_processed += 1

                if self.job_id:
                    progress = 10 + int(((i + 1) / len(root_categories)) * 10)
                    self._update_job_progress(
                        progress,
                        f"Обновлено {root_cat.name}: +{added} ~{updated} -{deleted}",
                    )

            except Exception as e:
                print(f"ERROR: Ошибка обновления категории {root_cat.name}: {e}")

        result = {
            "scanned": total_processed,
            "added": added,
            "updated": updated,
            "deleted": deleted,
        }

        if self.job_id:
            self._update_job_progress(20, f"Категории синхронизированы: {total_processed}")

        return result

    def _fetch_category_data(self, category_id: int) -> Dict:
        """Получить данные категории (включая fastCategoriesExtended) из API."""
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
            url = f"{self.api.base_url}/webgate/v2/goods/search"
            response = self.api.session.post(url, json=payload, timeout=15)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"Error fetching category {category_id}: {e}")
            return None

    def scan_products(
        self,
        category_ids: Optional[list] = None,
        tracked_only: bool = False,
    ) -> dict:
        """
        Сканировать товары из указанных категорий для магазина.

        Args:
            category_ids: magnit_id категорий (если None — все отслеживаемые)
            tracked_only: Если True, сканировать только отслеживаемые категории

        Returns:
            {"scanned": N, "added": N, "updated": N, "price_changes": N}
        """
        if not self.api or not self.store_code:
            raise ValueError("store_code не указан")

        # Определяем категории
        if category_ids is None:
            try:
                query = self.db.query(Category)
                if tracked_only:
                    query = query.filter(Category.is_tracked == True)  # noqa: E712
                categories = query.all()
                print(f"DEBUG: Found {len(categories)} tracked categories")
                if categories:
                    print(
                        f"DEBUG: First category: id={categories[0].id}, magnit_id={categories[0].magnit_id}, name={categories[0].name}"
                    )
                category_ids = [cat.magnit_id for cat in categories]
                print(f"DEBUG: category_ids (first 5): {category_ids[:5]}")
            except Exception as e:
                print(f"ERROR in category_ids extraction: {e}")
                import traceback

                print(traceback.format_exc())
                raise
        else:
            print(
                f"DEBUG: Using provided category_ids: {category_ids[:5] if len(category_ids) > 5 else category_ids}"
            )

        if not category_ids:
            return {"scanned": 0, "added": 0, "updated": 0, "price_changes": 0}

        if self.job_id:
            self._update_job_progress(
                25, f"Сканирование товаров из {len(category_ids)} категорий..."
            )

        total_added = 0
        total_updated = 0
        total_price_changes = 0
        total_scanned = 0

        # Сканируем по одной категории за раз
        for cat_idx, cat_magnit_id in enumerate(category_ids):
            progress_base = 25 + int((cat_idx / len(category_ids)) * 70)
            if self.job_id:
                cat = (
                    self.db.query(Category)
                    .filter(
                        Category.magnit_id == cat_magnit_id,
                    )
                    .first()
                )
                cat_name = cat.name if cat else f"ID:{cat_magnit_id}"
                self._update_job_progress(progress_base, f"Категория: {cat_name}...")

            offset = 0
            has_more = True
            while has_more:
                # Retry logic: попытаемся 3 раза с задержкой
                max_retries = 3
                retry_count = 0
                last_error = None

                while retry_count < max_retries:
                    try:
                        print(
                            f"DEBUG: Calling search with category_ids={[cat_magnit_id]}, store_code={self.store_code} (attempt {retry_count + 1}/{max_retries})"
                        )
                        result = self.api.search(
                            store_code=self.store_code,
                            category_ids=[cat_magnit_id],
                            limit=32,
                            offset=offset,
                        )
                        print(
                            f"DEBUG: search returned {len(result.get('items', []))} products"
                        )
                        break  # Успешно, выходим из retry цикла
                    except Exception as e:
                        last_error = e
                        retry_count += 1
                        if retry_count < max_retries:
                            wait_time = (
                                2**retry_count
                            )  # Exponential backoff: 2, 4, 8 секунд
                            print(
                                f"WARN: Ошибка получения товаров (попытка {retry_count}/{max_retries}): {e}"
                            )
                            print(
                                f"DEBUG: Ожидание {wait_time} секунд перед повтором..."
                            )
                            time.sleep(wait_time)
                        else:
                            print(
                                f"ERROR: Ошибка получения товаров после {max_retries} попыток (категория {cat_magnit_id}): {e}"
                            )
                            import traceback

                            print(traceback.format_exc())

                # Если все попытки исчерпаны, пропускаем эту категорию
                if retry_count >= max_retries and last_error:
                    print(
                        f"WARN: Пропускаем категорию {cat_magnit_id} из-за ошибок API"
                    )
                    break

                products = result.get("items", [])
                has_more = result.get("hasMore", False)
                offset = result.get("next_offset", offset + 50)

                if not products:
                    break

                added, updated, price_changes = self._save_products(
                    products, cat_magnit_id
                )
                total_added += added
                total_updated += updated
                total_price_changes += price_changes
                total_scanned += len(products)

                self.db.commit()

        # Обновляем дату сканирования категорий
        for cat_magnit_id in category_ids:
            cat = (
                self.db.query(Category)
                .filter(
                    Category.magnit_id == cat_magnit_id,
                )
                .first()
            )
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
            self._update_job_progress(95, f"Товары сохранены: {total_scanned} шт.")

        return result

    def _save_products(
        self, products: list[dict], category_magnit_id: int
    ) -> tuple[int, int, int]:
        """
        Сохранить товары в БД.

        Returns:
            (added_count, updated_count, price_change_count)
        """
        added = 0
        updated = 0
        price_changes = 0

        try:
            # Находим категорию по magnit_id в БД (универсальная категория)
            cat = (
                self.db.query(Category)
                .filter(
                    Category.magnit_id == category_magnit_id,
                )
                .first()
            )
            db_category_id = cat.id if cat else None
            print(
                f"DEBUG _save_products: category_magnit_id={category_magnit_id}, cat={cat}, db_category_id={db_category_id}"
            )
        except Exception as e:
            print(f"ERROR in _save_products finding category: {e}")
            import traceback

            print(traceback.format_exc())
            raise

        for product_data in products:
            existing = (
                self.db.query(Product)
                .filter(
                    Product.product_id == product_data["product_id"],
                    Product.store_code == self.store_code,
                )
                .first()
            )

            current_price = product_data["price"]
            current_old_price = product_data.get("old_price")

            if existing:
                old_price_val = existing.price
                new_price_val = current_price

                existing.name = product_data.get("name", existing.name)
                existing.price = new_price_val
                existing.old_price = current_old_price
                existing.sku = product_data.get("sku", existing.sku)
                existing.unit = product_data.get("unit", existing.unit)
                existing.image_url = product_data.get("image_url", existing.image_url)
                existing.in_stock = product_data.get("in_stock", existing.in_stock)
                existing.last_seen = datetime.utcnow()

                # Остатки и доступность
                if "quantity" in product_data:
                    existing.quantity = product_data["quantity"]
                if "is_low_stock" in product_data:
                    existing.is_low_stock = product_data["is_low_stock"]
                if "pickup_only" in product_data:
                    existing.pickup_only = product_data["pickup_only"]

                # Акции
                if "is_promotion" in product_data:
                    existing.is_promotion = product_data["is_promotion"]
                if "discount_percent" in product_data:
                    existing.discount_percent = product_data["discount_percent"]
                if "promo_end_date" in product_data and product_data["promo_end_date"]:
                    try:
                        existing.promo_end_date = datetime.fromisoformat(
                            product_data["promo_end_date"].replace("Z", "+00:00")
                        )
                    except (ValueError, AttributeError):
                        pass

                # Рейтинги
                if "rating" in product_data:
                    existing.rating = product_data["rating"]
                if "scores_count" in product_data:
                    existing.scores_count = product_data["scores_count"]
                if "comments_count" in product_data:
                    existing.comments_count = product_data["comments_count"]

                # SEO и каталог
                if "seo_code" in product_data:
                    existing.seo_code = product_data["seo_code"]
                if "service" in product_data:
                    existing.service = product_data["service"]
                if "catalog_type" in product_data:
                    existing.catalog_type = product_data["catalog_type"]

                # Параметры заказа
                if "min_order_qty" in product_data:
                    existing.min_order_qty = product_data["min_order_qty"]
                if "order_step_qty" in product_data:
                    existing.order_step_qty = product_data["order_step_qty"]

                # Весовые
                if "is_weighted" in product_data:
                    existing.is_weighted = product_data["is_weighted"]
                if "unit_price" in product_data:
                    existing.unit_price = product_data["unit_price"]

                if abs(old_price_val - new_price_val) > 0.01:
                    change_type = (
                        "decreased" if new_price_val < old_price_val else "increased"
                    )
                    price_changes += 1
                    existing.last_price_change = datetime.utcnow()

                    history = PriceHistory(
                        product_id=existing.product_id,
                        store_code=self.store_code,
                        price=new_price_val,
                        old_price=current_old_price,
                        recorded_at=datetime.utcnow(),
                        change_type=change_type,
                    )
                    self.db.add(history)

                updated += 1
                snapshot_product_id = existing.product_id
            else:
                # Парсим promo_end_date из ISO строки
                promo_end = None
                if product_data.get("promo_end_date"):
                    try:
                        promo_end = datetime.fromisoformat(
                            product_data["promo_end_date"].replace("Z", "+00:00")
                        )
                    except (ValueError, AttributeError):
                        pass

                new_product = Product(
                    product_id=product_data["product_id"],
                    name=product_data.get("name", "Без названия"),
                    sku=product_data.get("sku"),
                    category_id=db_category_id,
                    store_code=self.store_code,
                    price=current_price,
                    old_price=current_old_price,
                    currency="₽",
                    unit=product_data.get("unit", "шт"),
                    image_url=product_data.get("image_url"),
                    in_stock=product_data.get("in_stock", True),
                    # Остатки
                    quantity=product_data.get("quantity", 0),
                    is_low_stock=product_data.get("is_low_stock"),
                    pickup_only=product_data.get("pickup_only", False),
                    # Акции
                    is_promotion=product_data.get("is_promotion", False),
                    discount_percent=product_data.get("discount_percent"),
                    promo_end_date=promo_end,
                    # Рейтинги
                    rating=product_data.get("rating"),
                    scores_count=product_data.get("scores_count", 0),
                    comments_count=product_data.get("comments_count", 0),
                    # SEO
                    seo_code=product_data.get("seo_code"),
                    service=product_data.get("service"),
                    catalog_type=product_data.get("catalog_type"),
                    # Параметры заказа
                    min_order_qty=product_data.get("min_order_qty", 1),
                    order_step_qty=product_data.get("order_step_qty", 1),
                    # Весовые
                    is_weighted=product_data.get("is_weighted", False),
                    unit_price=product_data.get("unit_price"),
                    first_seen=datetime.utcnow(),
                    last_seen=datetime.utcnow(),
                )
                self.db.add(new_product)
                added += 1

                history = PriceHistory(
                    product_id=new_product.product_id,
                    store_code=self.store_code,
                    price=new_product.price,
                    old_price=new_product.old_price,
                    recorded_at=datetime.utcnow(),
                    change_type="initial",
                )
                self.db.add(history)

                snapshot_product_id = new_product.product_id

            # Записываем ежедневный снимок цены
            self._save_price_snapshot(
                product_id=snapshot_product_id,
                price=current_price,
                old_price=current_old_price,
            )

        return added, updated, price_changes

    def _save_price_snapshot(
        self, product_id: int, price: float, old_price: float = None
    ):
        """
        Записать ежедневный снимок цены товара.
        Если снимок за сегодня уже есть — обновить его.
        Удаляет записи старше 31 дня.
        """
        today = date.today()
        cutoff_date = today - timedelta(days=31)

        # Проверяем есть ли снимок за сегодня
        existing_snapshot = (
            self.db.query(DailyPriceSnapshot)
            .filter(
                DailyPriceSnapshot.product_id == product_id,
                DailyPriceSnapshot.store_code == self.store_code,
                DailyPriceSnapshot.snapshot_date == today,
            )
            .first()
        )

        discount = None
        if old_price and old_price > 0 and price > 0:
            discount = round((old_price - price) / old_price * 100, 1)

        if existing_snapshot:
            existing_snapshot.price = price
            existing_snapshot.old_price = old_price
            existing_snapshot.discount_percent = discount
        else:
            snapshot = DailyPriceSnapshot(
                product_id=product_id,
                store_code=self.store_code,
                price=price,
                old_price=old_price,
                snapshot_date=today,
                discount_percent=discount,
            )
            self.db.add(snapshot)

        # Удаляем записи старше 31 дня
        self.db.query(DailyPriceSnapshot).filter(
            DailyPriceSnapshot.snapshot_date < cutoff_date,
            DailyPriceSnapshot.store_code == self.store_code,
        ).delete(synchronize_session=False)

    def close(self):
        """Закрыть клиент."""
        if self.api:
            self.api.close()
