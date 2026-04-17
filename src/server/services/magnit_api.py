"""
Клиент для работы с API Магнита.
Используется для сканирования каталога товаров и получения данных о ценах.

API endpoint: POST https://magnit.ru/webgate/v2/goods/search
Используется для:
1. Получения категорий (без фильтра по категориям)
2. Получения товаров по категориям (с фильтром по категориям)
3. Пагинация через offset/limit
"""

import requests
import json
from typing import Optional
import time
import os


class MagnitAPIClient:
    """Клиент для взаимодействия с API Магнита."""

    def __init__(
        self,
        base_url: str = "https://magnit.ru",
        store_code: Optional[str] = None,
        store_type: Optional[str] = None,
        timeout: int = 15,
        rate_limit: float = 0.5,
    ):
        self.base_url = base_url.rstrip("/")
        self.store_code = store_code or os.getenv("STORE_CODE")
        self.store_type = store_type or os.getenv("STORE_TYPE", "MM")
        self.timeout = timeout
        self.rate_limit = rate_limit
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
                "Accept-Language": "ru-RU,ru;q=0.9",
                "Content-Type": "application/json",
                "Referer": "https://magnit.ru/",
                "Origin": "https://magnit.ru",
                "X-Requested-With": "XMLHttpRequest",
            }
        )
        self._last_request_time = 0

    def _rate_limit_wait(self):
        """Пауза между запросами для соблюдения rate limiting."""
        if self._last_request_time > 0:
            elapsed = time.time() - self._last_request_time
            if elapsed < self.rate_limit:
                time.sleep(self.rate_limit - elapsed)
        self._last_request_time = time.time()

    def search(
        self,
        store_code: Optional[str] = None,
        store_type: Optional[str] = None,
        category_ids: Optional[list] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """
        Универсальный метод для поиска категорий и товаров через /webgate/v2/goods/search.

        Args:
            store_code: Код магазина
            store_type: Тип магазина (MM, ME, DG, GM, MO, MC, ZARYAD, DARKSTORE, MM_MINI)
                       Или числовой код (6 для Экстра, и т.д.)
            category_ids: Список ID категорий для фильтрации товаров
                         Если None - возвращаются категории
                         Если указаны - возвращаются товары из этих категорий
            limit: Кол-во результатов за запрос (макс ~50-100)
            offset: Смещение для пагинации

        Returns:
            {
                "items": [...],  # Категории или товары
                "total": 1234,
                "hasMore": True,
                "next_offset": 50
            }
        """
        self._rate_limit_wait()
        code = store_code or self.store_code
        s_type = store_type or self.store_type
        if not code:
            raise ValueError("store_code не указан")

        url = f"{self.base_url}/webgate/v2/goods/search"

        # Строим payload с правильным форматом для API
        payload = {
            "sort": {
                "order": "desc",
                "type": "popularity",
            },
            "pagination": {
                "limit": limit,
                "offset": offset,
            },
            "includeAdultGoods": True,
            "storeCode": code,
            "storeType": s_type,
            "catalogType": "1",
        }

        # Если ищем товары по категориям, добавляем categories
        if category_ids:
            payload["categories"] = category_ids
        else:
            payload["categories"] = []

        try:
            print(f"DEBUG: POST {url}")
            print(f"DEBUG: Payload: {payload}")
            print(f"DEBUG: Payload JSON: {json.dumps(payload)}")

            response = self.session.post(url, json=payload, timeout=self.timeout)

            print(f"DEBUG: Response status: {response.status_code}")
            print(f"DEBUG: Response text: {response.text[:500]}")

            response.raise_for_status()
            data = response.json()

            print(f"DEBUG: Response keys: {list(data.keys())}")

            # Парсим ответ
            items = []

            if category_ids:
                # Ищем товары - они в items
                raw_items = data.get("items", [])
                for item in raw_items:
                    parsed_item = self._parse_product(item)
                    if parsed_item:
                        items.append(parsed_item)
            else:
                # Ищем категории - используем fastCategories на верхнем уровне
                # или fastCategoriesExtended внутри category (если есть)
                fast_cats = data.get("fastCategories", [])
                category_data = data.get("category", {}) or {}
                fast_cats_extended = category_data.get("fastCategoriesExtended", [])

                # Используем fastCategoriesExtended если есть, иначе fastCategories
                cats_source = fast_cats_extended if fast_cats_extended else fast_cats

                for cat in cats_source:
                    parsed_item = self._parse_category(cat)
                    if parsed_item:
                        items.append(parsed_item)

            # Пагинация
            total = data.get("total", len(items))
            has_more = data.get("hasMore", (offset + len(items)) < total)
            next_offset = offset + len(items) if has_more else None

            return {
                "items": items,
                "total": total,
                "hasMore": has_more,
                "next_offset": next_offset,
            }
        except requests.RequestException as e:
            print(f"ERROR: {e}")
            raise Exception(f"Ошибка при поиске: {str(e)}")

    def _parse_category(self, item: dict) -> Optional[dict]:
        """Парсинг данных категории из ответа API."""
        try:
            category_id = item.get("id") or item.get("categoryId")
            if not category_id:
                return None

            return {
                "magnit_id": int(category_id),
                "name": item.get("name", "Без названия"),
                "url": item.get("url", ""),
                "product_count": item.get("productCount", 0),
                "parent_id": item.get("parentId"),
            }
        except Exception as e:
            print(f"Ошибка парсинга категории: {e}")
            return None

    def _parse_product(self, item: dict) -> Optional[dict]:
        """Парсинг данных товара из ответа API."""
        try:
            product_id = item.get("id") or item.get("productId")
            if not product_id:
                return None

            # Цена — конвертируем из копеек в рубли
            current_price = item.get("price")
            if current_price and current_price > 1000:
                current_price = current_price / 100

            # Акция/скидка
            promotion = item.get("promotion", {})
            old_price_raw = promotion.get("oldPrice") or item.get("oldPrice")
            is_promotion = promotion.get("isPromotion", False)
            discount_percent = promotion.get("discountPercent")
            promo_end_date = promotion.get("endDate")  # ISO строка

            if old_price_raw and old_price_raw > 1000:
                old_price_raw = old_price_raw / 100

            # Рейтинги
            ratings = item.get("ratings", {})
            rating = ratings.get("rating")
            scores_count = ratings.get("scoresCount", 0)
            comments_count = ratings.get("commentsCount", 0)

            # Параметры заказа
            order_props = item.get("orderProperties", {})
            min_order_qty = order_props.get("minOrderQuantity", 1)
            order_step_qty = order_props.get("orderStepQuantity", 1)

            # Весовые товары
            weighted = item.get("weighted", {})
            is_weighted = weighted.get("isWeighted", False)
            unit_price = weighted.get("unitPrice")
            if unit_price and unit_price > 1000:
                unit_price = unit_price / 100

            # Первая картинка из gallery
            gallery = item.get("gallery", [])
            image_url = None
            if gallery and len(gallery) > 0:
                image_url = gallery[0].get("url")

            return {
                "product_id": int(product_id),
                "name": item.get("name") or item.get("title", "Без названия"),
                "sku": item.get("sku") or item.get("article"),
                "price": float(current_price) if current_price else 0.0,
                "old_price": float(old_price_raw) if old_price_raw else None,
                "currency": "₽",
                "unit": item.get("unit") or item.get("measureUnit", "шт"),
                "image_url": image_url,
                "in_stock": item.get("inStock", item.get("available", True)),
                # Остатки и доступность
                "quantity": item.get("quantity", 0),
                "is_low_stock": item.get("isLowStock"),
                "pickup_only": item.get("pickupOnly", False),
                # Акции
                "is_promotion": is_promotion,
                "discount_percent": discount_percent,
                "promo_end_date": promo_end_date,
                # Рейтинги
                "rating": rating,
                "scores_count": scores_count,
                "comments_count": comments_count,
                # SEO и каталог
                "seo_code": item.get("seoCode"),
                "service": item.get("service"),
                "catalog_type": item.get("catalogType"),
                # Параметры заказа
                "min_order_qty": min_order_qty,
                "order_step_qty": order_step_qty,
                # Весовые
                "is_weighted": is_weighted,
                "unit_price": unit_price,
                "category_id": item.get("categoryId"),
            }
        except Exception as e:
            print(f"Ошибка парсинга товара: {e}")
            return None

    def set_store_code(self, store_code: str):
        """Установить код магазина."""
        self.store_code = store_code

    def close(self):
        """Закрыть сессию."""
        self.session.close()


# Маппинг типов: API код → UI-лейбл (кнопки на magnit.ru/shops)
# Проверено через Playwright 2026-04-13: клик по кнопке → storeTypeListV2 в запросе
# URL кнопки: ?storeType=<код>
STORE_TYPE_MAP = {
    "MM": "Магнит",
    "ME": "Экстра",
    "DG": "М.Косметик",
    "GM": "Семейный",
    "MO": "Опт",
    "MC": "Моя цена",
    "ZARYAD": "Заряд",
    "DARKSTORE": "Мигом",
    "MM_MINI": "Мини",
}

ALL_STORE_TYPES = list(STORE_TYPE_MAP.keys())


class StoresAPI:
    """
    Клиент для поиска магазинов через API Магнита.

    Использует endpoint: POST /webgate/v1/stores-facade/search/detail
    """

    def __init__(
        self,
        base_url: str = "https://magnit.ru",
        timeout: int = 15,
        rate_limit: float = 0.3,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.rate_limit = rate_limit
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
                "Accept-Language": "ru-RU,ru;q=0.9",
                "Content-Type": "application/json",
                "Referer": "https://magnit.ru/",
                "Origin": "https://magnit.ru",
                "X-Client-Name": "magnit",
                "X-New-Magnit": "true",
                "X-App-Version": "2026.4.10-19.26",
                "X-Device-Platform": "Web",
            }
        )
        self._last_request_time = 0

    def _rate_limit_wait(self):
        """Пауза между запросами."""
        if self._last_request_time > 0:
            elapsed = time.time() - self._last_request_time
            if elapsed < self.rate_limit:
                time.sleep(self.rate_limit - elapsed)
        self._last_request_time = time.time()

    def search_stores(
        self,
        query: str,
        store_types: Optional[list[str]] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        """
        Поиск магазинов по адресу.

        Args:
            query: Поисковый запрос (адрес, город, улица)
            store_types: Список типов магазинов для фильтрации
            limit: Кол-во результатов
            offset: Смещение для пагинации

        Returns:
            {
                "stores": [...],
                "total": N,
                "hasMore": True
            }
        """
        self._rate_limit_wait()

        url = f"{self.base_url}/webgate/v1/stores-facade/search/detail"
        payload = {
            "query": query,
            "storeTypeListV2": store_types or ALL_STORE_TYPES,
            "limit": limit,
            "offset": offset,
        }

        try:
            response = self.session.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()

            stores = data.get("stores", [])
            total = data.get("total", len(stores))
            has_more = data.get("hasMore", False)

            return {
                "stores": stores,
                "total": total,
                "hasMore": has_more,
            }
        except requests.RequestException as e:
            raise Exception(f"Ошибка поиска магазинов: {str(e)}")

    def close(self):
        """Закрыть сессию."""
        self.session.close()
