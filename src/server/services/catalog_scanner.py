"""
Сервис сканирования каталога товаров.
Сканирует товары через API Магнита по категориям.
"""

from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, date, timedelta
from typing import Optional, Dict
import time
import os
import logging

from src.server.models import (
    Category,
    Product,
    PriceHistory,
    ScanJob,
)
from src.server.constants import STALE_DAYS_DELETE
from src.server.services.magnit_api import MagnitAPIClient

logger = logging.getLogger(__name__)

PRICE_HISTORY_RETENTION_DAYS = 30


class CatalogScanner:
    """Сканирование каталога товаров и категорий."""

    def __init__(
        self,
        db: Session,
        store_code: Optional[str] = None,
        address: Optional[str] = None,
        job_id: Optional[int] = None,
    ):
        self.db = db
        self.store_code = store_code
        self.address = address or ""
        self.job_id = job_id
        
        # Получаем store_type из БД по store_code
        from src.server.models import Store
        store = self.db.query(Store).filter(Store.store_code == store_code).first() if store_code else None
        self.store_type = store.store_type if store and store.store_type else "Магнит"
        
        self.api = (
            MagnitAPIClient(store_code=store_code, store_type=self.store_type)
            if store_code
            else None
        )

    def _update_job_progress(self, message: str):
        """Обновить прогресс задания (только message, progress обновляется в catalog.py)."""
        if self.job_id:
            self.db.query(ScanJob).filter(ScanJob.id == self.job_id).update(
                {"progress_message": message}
            )
            self.db.commit()

    def _update_job_progress_full(self, **kwargs):
        """Обновить прогресс задания с детальными полями."""
        if self.job_id:
            self.db.query(ScanJob).filter(ScanJob.id == self.job_id).update(kwargs)
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
            self._update_job_progress("Получение списка корневых категорий из БД...")

        # Получаем все отслеживаемые корневые категории из БД
        root_categories = (
            self.db.query(Category)
            .filter(Category.parent_id.is_(None), Category.is_tracked == True)  # noqa: E712
            .all()
        )

        if not root_categories:
            if self.job_id:
                self._update_job_progress("Нет отслеживаемых корневых категорий")
            return {"scanned": 0, "added": 0, "updated": 0, "deleted": 0}

        if self.job_id:
            self._update_job_progress(
                f"Найдено {len(root_categories)} корневых категорий, обновление..."
            )

        added = 0
        updated = 0
        deleted = 0
        total_processed = 0

        for i, root_cat in enumerate(root_categories):
            if not root_cat.magnit_id:
                logger.debug(f"DEBUG: Пропуск корневой категории без magnit_id: {root_cat.name}")
                continue

            try:
                # Получаем подкатегории из API
                api_data = self._fetch_category_data(root_cat.magnit_id)

                if not api_data or "category" not in api_data:
                    logger.warning(f"WARN: Нет данных для категории {root_cat.name}")
                    continue

                cat_info = api_data["category"]
                subcats_from_api = api_data.get("fastCategoriesExtended", [])

                # Обновляем название корневой категории если изменилось
                if root_cat.name != cat_info.get("title", root_cat.name):
                    root_cat.name = cat_info["title"]
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
                        logger.debug(f"DEBUG: Удалена подкатегория: {child.name} (magnit_id={magnit_id})")
                        self.db.delete(child)
                        deleted += 1

                # Добавляем или обновляем подкатегории из API
                for sub in subcats_from_api:
                    sub_id = sub["id"]
                    sub_name = sub["title"]

                    if sub_id in current_ids:
                        # Обновляем существующую подкатегорию
                        child = current_ids[sub_id]
                        if child.name != sub_name:
                            child.name = sub_name
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
                        logger.debug(f"DEBUG: Добавлена подкатегория: {sub_name} (magnit_id={sub_id})")

                self.db.commit()
                total_processed += 1

                if self.job_id:
                    self._update_job_progress(
                        f"Обновлено {root_cat.name}: +{added} ~{updated} -{deleted}",
                    )

            except Exception as e:
                logger.error(f"ERROR: Ошибка обновления категории {root_cat.name}: {e}")

        result = {
            "scanned": total_processed,
            "added": added,
            "updated": updated,
            "deleted": deleted,
        }

        if self.job_id:
            self._update_job_progress(f"Категории синхронизированы: {total_processed}")

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
            logger.error(f"Error fetching category {category_id}: {e}")
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
                logger.debug(f"DEBUG: Found {len(categories)} tracked categories")
                if categories:
                    logger.debug(
                        f"DEBUG: First category: id={categories[0].id}, magnit_id={categories[0].magnit_id}, name={categories[0].name}"
                    )
                category_ids = [cat.magnit_id for cat in categories]
                logger.debug(f"DEBUG: category_ids (first 5): {category_ids[:5]}")
            except Exception as e:
                logger.error(f"ERROR in category_ids extraction: {e}")
                import traceback

                logger.exception("Traceback")
                raise
        else:
            logger.debug(
                f"DEBUG: Using provided category_ids: {category_ids[:5] if len(category_ids) > 5 else category_ids}"
            )

        if not category_ids:
            return {"scanned": 0, "added": 0, "updated": 0, "price_changes": 0}

        if self.job_id:
            self._update_job_progress(
                f"Сканирование товаров из {len(category_ids)} категорий..."
            )

        total_added = 0
        total_updated = 0
        total_price_changes = 0
        total_scanned = 0

# Сканируем по одной категории за раз
        for cat_idx, cat_magnit_id in enumerate(category_ids):
            # Проверка на отмену - сбрасываем кэш сессии
            self.db.expire_all()
            if self.job_id:
                job = self.db.query(ScanJob).filter(ScanJob.id == self.job_id).first()
                if job and job.status == "cancelled":
                    logger.debug(f"DEBUG: Задание {self.job_id} отменено, выходим")
                    return {"scanned": 0, "added": 0, "updated": 0, "price_changes": 0}
                
                # Показать магазин и категорию
                cat = self.db.query(Category).filter(Category.magnit_id == cat_magnit_id).first()
                cat_name = cat.name if cat else f"ID:{cat_magnit_id}"
                clean_address = (self.address or "").replace("\n", " ").replace("\r", " ").strip()
                self._update_job_progress(f"{self.store_type}: {clean_address} | 📁 {cat_name}")

            offset = 0
            has_more = True
            while has_more:
                # Retry logic: попытаемся 3 раза с задержкой
                max_retries = 3
                retry_count = 0
                last_error = None

                while retry_count < max_retries:
                    # Проверка на отмену перед каждым запросом
                    self.db.expire_all()
                    if self.job_id:
                        job = self.db.query(ScanJob).filter(ScanJob.id == self.job_id).first()
                        if job and job.status == "cancelled":
                            logger.debug(f"DEBUG: Задание {self.job_id} отменено, выходим")
                            return {"scanned": 0, "added": 0, "updated": 0, "price_changes": 0}
                    
                    try:
                        logger.debug(
                            f"DEBUG: Calling search with category_ids={[cat_magnit_id]}, store_code={self.store_code} (attempt {retry_count + 1}/{max_retries})"
                        )
                        result = self.api.search(
                            store_code=self.store_code,
                            category_ids=[cat_magnit_id],
                            limit=32,
                            offset=offset,
                        )
                        logger.debug(
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
                            logger.warning(
                                f"WARN: Ошибка получения товаров (попытка {retry_count}/{max_retries}): {e}"
                            )
                            logger.debug(
                                f"DEBUG: Ожидание {wait_time} секунд перед повтором..."
                            )
                            time.sleep(wait_time)
                        else:
                            err_msg = str(e)
                            if "invalid_service_pair" in err_msg or "service not found" in err_msg:
                                logger.warning(
                                    f"WARN: Категория {cat_magnit_id} недоступна для типа магазина {self.store_type} — пропускаем"
                                )
                            else:
                                logger.error(
                                    f"ERROR: Ошибка получения товаров после {max_retries} попыток (категория {cat_magnit_id}): {e}"
                                )
                            logger.exception("Traceback")

                # Если все попытки исчерпаны, пропускаем эту категорию
                if retry_count >= max_retries and last_error:
                    err_msg = str(last_error)
                    if "invalid_service_pair" in err_msg or "service not found" in err_msg:
                        msg = f"⚠️ Категория {cat_name} недоступна для {self.store_type}"
                        if self.job_id:
                            self._update_job_progress(msg)
                        logger.warning(f"WARN: Категория {cat_magnit_id} недоступна для {self.store_type} — пропущена")
                    else:
                        logger.warning(
                            f"WARN: Пропускаем категорию {cat_magnit_id} из-за ошибок API"
                        )
                    break

                products = result.get("items", [])
                has_more = result.get("hasMore", False)
                next_offset = result.get("next_offset")
                total_count = result.get("total", 0)
                
                # Обновляем общее количество товаров в категории (только при первом запросе)
                if self.job_id and offset == 0 and total_count > 0:
                    self._update_job_progress_full(
                        current_category_items_total=total_count,
                        current_category_items_loaded=0
                    )
                
                # Логируем пагинацию для отладки
                logger.debug(f"DEBUG: Pagination - offset={offset}, items_count={len(products)}, has_more={has_more}, next_offset={next_offset}, total={total_count}")
                
                # Если нет товаров, выходим из цикла (даже если hasMore=True)
                if not products:
                    logger.debug(f"DEBUG: No products returned, breaking pagination loop")
                    break
                
                # Если next_offset не определён, но есть товары, вычисляем сами
                if next_offset is None and has_more:
                    next_offset = offset + len(products)
                    logger.debug(f"DEBUG: Calculated next_offset={next_offset}")
                
                offset = next_offset if next_offset is not None else offset + len(products)

                added, updated, price_changes = self._save_products(
                    products, cat_magnit_id
                )
                total_added += added
                total_updated += updated
                total_price_changes += price_changes
                total_scanned += len(products)

                # Обновляем количество загруженных товаров в категории
                if self.job_id:
                    self._update_job_progress_full(
                        current_category_items_loaded=total_scanned
                    )

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

        # Удаляем устаревшие товары (STALE_DAYS_DELETE+ дней без обновлений).
        # Жизненный цикл: STALE_DAYS_VISIBLE (видно) → STALE_DAYS_HIDDEN (скрыто) → удаление.
        deleted = self.cleanup_stale_products(days_threshold=STALE_DAYS_DELETE)

        # Удаляем устаревшие записи истории цен (>30 дней)
        history_deleted = self.cleanup_price_history()

        result = {
            "scanned": total_scanned,
            "added": total_added,
            "updated": total_updated,
            "price_changes": total_price_changes,
            "deleted": deleted,
            "history_deleted": history_deleted,
        }

        if self.job_id:
            self._update_job_progress(f"Товары сохранены: {total_scanned} шт.")
            if deleted > 0:
                self._update_job_progress(f"Удалено устаревших товаров: {deleted}")

        return result

    def _save_products(
        self, products: list[dict], category_magnit_id: int
    ) -> tuple[int, int, int]:
        """
        Сохранить товары в БД с использованием bulk операций для оптимизации.

        Логика цены:
        - price_history хранит одну запись на день для каждого (product_id, store_code)
        - previous_price / price_change_percent берутся из последнего дня сканирования
          (предыдущая запись в price_history)
        - last_change_price / last_change_date обновляются только при реальном изменении
          цены относительно предыдущего дня

        Оптимизация:
        - Один SELECT для всех product_ids (вместо N+1 запросов)
        - Bulk INSERT для новых товаров
        - Bulk UPDATE для существующих товаров
        - Bulk INSERT/UPDATE для истории цен
        - Один COMMIT в конце

        Returns:
            (added_count, updated_count, price_change_count)
        """
        if not products:
            return 0, 0, 0

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
            logger.debug(
                f"DEBUG _save_products: category_magnit_id={category_magnit_id}, cat={cat}, db_category_id={db_category_id}"
            )
        except Exception as e:
            logger.error(f"ERROR in _save_products finding category: {e}")
            import traceback

            logger.exception("Traceback")
            raise

        # 1. Получаем все существующие товары ОДНИМ запросом
        product_ids = [p["product_id"] for p in products]
        existing_products = {
            p.product_id: p
            for p in self.db.query(Product)
            .filter(
                Product.product_id.in_(product_ids),
                Product.store_code == self.store_code,
            )
            .all()
        }

        # 2. Получаем последнюю цену ПРЕДЫДУЩЕГО дня для каждого товара
        # (используется для previous_price / price_change_percent)
        today = date.today()
        yesterday = today - timedelta(days=1)
        previous_day_prices: dict[int, float] = {}
        if product_ids:
            price_history_rows = (
                self.db.query(
                    PriceHistory.product_id,
                    PriceHistory.scan_date,
                    PriceHistory.price,
                )
                .filter(
                    PriceHistory.product_id.in_(product_ids),
                    PriceHistory.store_code == self.store_code,
                    PriceHistory.scan_date < today,
                )
                .all()
            )
            latest_by_pid: dict[int, tuple[date, float]] = {}
            for pid, sd, pr in price_history_rows:
                if pid not in latest_by_pid or sd > latest_by_pid[pid][0]:
                    latest_by_pid[pid] = (sd, pr)
            previous_day_prices = {pid: pr for pid, (_, pr) in latest_by_pid.items()}

        # 3. Разделяем на INSERT и UPDATE
        to_insert = []
        to_update = []
        now = datetime.utcnow()
        price_changes_count = 0

        for product_data in products:
            product_id = product_data["product_id"]
            current_price = product_data["price"]

            existing = existing_products.get(product_id)
            # Цена предыдущего дня (None если товар новый или истории нет)
            prev_day_price = previous_day_prices.get(product_id)

            if existing:
                # UPDATE: обновляем поля
                update_data = {
                    "id": existing.id,
                    "name": product_data.get("name", existing.name),
                    "price": current_price,
                    "category_id": db_category_id,
                    "sku": product_data.get("sku", existing.sku),
                    "unit": product_data.get("unit", existing.unit),
                    "image_url": product_data.get("image_url", existing.image_url),
                    "in_stock": product_data.get("in_stock", existing.in_stock),
                    "last_seen": now,
                    "last_scan_found": now,
                    "quantity": product_data.get("quantity", existing.quantity),
                    "is_low_stock": product_data.get("is_low_stock", existing.is_low_stock),
                    "pickup_only": product_data.get("pickup_only", existing.pickup_only),
                    "rating": product_data.get("rating", existing.rating),
                    "scores_count": product_data.get("scores_count", existing.scores_count),
                    "comments_count": product_data.get("comments_count", existing.comments_count),
                    "seo_code": product_data.get("seo_code", existing.seo_code),
                    "service": product_data.get("service", existing.service),
                    "catalog_type": product_data.get("catalog_type", existing.catalog_type),
                    "min_order_qty": product_data.get("min_order_qty", existing.min_order_qty),
                    "order_step_qty": product_data.get("order_step_qty", existing.order_step_qty),
                    "is_weighted": product_data.get("is_weighted", existing.is_weighted),
                    "unit_price": product_data.get("unit_price", existing.unit_price),
                }

                # previous_price и price_change_percent — от предыдущего дня
                if prev_day_price is not None and abs(prev_day_price - current_price) > 0.01:
                    update_data["previous_price"] = prev_day_price
                    change_percent = round(
                        (prev_day_price - current_price) / prev_day_price * 100, 1
                    )
                    update_data["price_change_percent"] = change_percent
                    if change_percent != 0:
                        price_changes_count += 1
                else:
                    # Нет предыдущего дня или цена не изменилась
                    update_data["previous_price"] = current_price
                    update_data["price_change_percent"] = None

                # last_change_price / last_change_date — обновляем только при реальном
                # изменении относительно last_change_price
                last_change_price = existing.last_change_price
                if (
                    last_change_price is not None
                    and abs(last_change_price - current_price) > 0.01
                ):
                    update_data["last_change_price"] = last_change_price
                    update_data["last_change_date"] = existing.last_seen or now
                    update_data["last_price_change"] = now
                elif last_change_price is None and prev_day_price is not None and abs(prev_day_price - current_price) > 0.01:
                    # Первое изменение после появления
                    update_data["last_change_price"] = prev_day_price
                    update_data["last_change_date"] = existing.last_seen or now
                    update_data["last_price_change"] = now

                to_update.append(update_data)
            else:
                # INSERT: новый товар
                to_insert.append({
                    "product_id": product_id,
                    "name": product_data.get("name", "Без названия"),
                    "sku": product_data.get("sku"),
                    "category_id": db_category_id,
                    "store_code": self.store_code,
                    "price": current_price,
                    "currency": "₽",
                    "unit": product_data.get("unit", "шт"),
                    "image_url": product_data.get("image_url"),
                    "in_stock": product_data.get("in_stock", True),
                    # Остатки
                    "quantity": product_data.get("quantity", 0),
                    "is_low_stock": product_data.get("is_low_stock"),
                    "pickup_only": product_data.get("pickup_only", False),
                    # Рейтинги
                    "rating": product_data.get("rating"),
                    "scores_count": product_data.get("scores_count", 0),
                    "comments_count": product_data.get("comments_count", 0),
                    # SEO
                    "seo_code": product_data.get("seo_code"),
                    "service": product_data.get("service"),
                    "catalog_type": product_data.get("catalog_type"),
                    # Параметры заказа
                    "min_order_qty": product_data.get("min_order_qty", 1),
                    "order_step_qty": product_data.get("order_step_qty", 1),
                    # Весовые
                    "is_weighted": product_data.get("is_weighted", False),
                    "unit_price": product_data.get("unit_price"),
                    # Временные метки
                    "first_seen": now,
                    "last_seen": now,
                    "last_scan_found": now,
                    # Отслеживание цен — нет истории, всё None/текущая цена
                    "previous_price": current_price,
                    "price_change_percent": None,
                    "last_price_change": None,
                    "last_change_price": None,
                    "last_change_date": None,
                })

        # 4. Bulk INSERT
        added = 0
        if to_insert:
            self.db.bulk_insert_mappings(Product, to_insert)
            added = len(to_insert)
            logger.debug(f"DEBUG: Bulk inserted {added} products")

        # 5. Bulk UPDATE
        updated = 0
        if to_update:
            self.db.bulk_update_mappings(Product, to_update)
            updated = len(to_update)
            logger.debug(f"DEBUG: Bulk updated {updated} products")

        # 6. Upsert в price_history за сегодняшнюю дату
        self._upsert_price_history(products, today)

        # 7. Один COMMIT для всех операций
        self.db.commit()

        return added, updated, price_changes_count

    def _upsert_price_history(
        self, products_data: list[dict], scan_date: date
    ) -> None:
        """
        Сохранить цены товаров в price_history (одна запись на день).
        Если запись за этот день уже есть — обновляем цену, остаток и наличие.
        """
        if not products_data:
            return

        product_ids = [p["product_id"] for p in products_data]
        existing_rows = {
            (r.product_id, r.store_code): r
            for r in self.db.query(PriceHistory)
            .filter(
                PriceHistory.product_id.in_(product_ids),
                PriceHistory.store_code == self.store_code,
                PriceHistory.scan_date == scan_date,
            )
            .all()
        }

        to_insert = []
        to_update = []
        for p in products_data:
            pid = p["product_id"]
            key = (pid, self.store_code)
            if key in existing_rows:
                to_update.append({
                    "id": existing_rows[key].id,
                    "price": p["price"],
                    "quantity": p.get("quantity"),
                    "in_stock": p.get("in_stock"),
                })
            else:
                to_insert.append({
                    "product_id": pid,
                    "store_code": self.store_code,
                    "price": p["price"],
                    "quantity": p.get("quantity"),
                    "in_stock": p.get("in_stock"),
                    "scan_date": scan_date,
                })

        if to_insert:
            self.db.bulk_insert_mappings(PriceHistory, to_insert)
            logger.debug(f"DEBUG: Inserted {len(to_insert)} price_history records for {scan_date}")
        if to_update:
            self.db.bulk_update_mappings(PriceHistory, to_update)
            logger.debug(f"DEBUG: Updated {len(to_update)} price_history records for {scan_date}")

    def cleanup_stale_products(self, days_threshold: int = STALE_DAYS_DELETE) -> int:
        """
        Удалить товары, которые не обновлялись N дней.

        Args:
            days_threshold: Количество дней без обновлений (по умолчанию STALE_DAYS_DELETE)

        Returns:
            Количество удалённых товаров
        """
        cutoff_date = datetime.utcnow() - timedelta(days=days_threshold)

        deleted = self.db.query(Product).filter(
            Product.last_seen < cutoff_date,
            Product.store_code == self.store_code,
        ).delete(synchronize_session=False)

        if deleted > 0:
            self.db.commit()
            logger.info(f"Удалено {deleted} устаревших товаров для магазина {self.store_code}")

        return deleted

    def cleanup_price_history(self, days: int = PRICE_HISTORY_RETENTION_DAYS) -> int:
        """
        Удалить записи price_history старше N дней.
        Вызывается после каждого сканирования.
        """
        try:
            cutoff = date.today() - timedelta(days=days)
            deleted = self.db.query(PriceHistory).filter(
                PriceHistory.scan_date < cutoff
            ).delete(synchronize_session=False)
            if deleted > 0:
                self.db.commit()
                logger.info(f"Удалено {deleted} устаревших записей price_history старше {days} дней")
            return deleted
        except Exception as e:
            self.db.rollback()
            logger.error(f"ERROR cleanup_price_history: {e}")
            return 0

    def close(self):
        """Закрыть клиент."""
        if self.api:
            self.api.close()
