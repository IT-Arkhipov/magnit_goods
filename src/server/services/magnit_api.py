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
import random
import logging

from src.server.constants import (
    STORE_TYPE_MAP,
    REVERSE_STORE_TYPE_MAP,
    API_STORE_TYPE_CODE,
)

logger = logging.getLogger(__name__)


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
        """Пауза между запросами для соблюдения rate limiting (случайная 0.1-0.5 сек)."""
        if self._last_request_time > 0:
            elapsed = time.time() - self._last_request_time
            if elapsed < self.rate_limit:
                delay = self.rate_limit - elapsed
                time.sleep(delay)
        time.sleep(random.uniform(0.1, 0.5))
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
            store_type: Тип магазина (MM, ME, DG, GM, MO, MC, ZARYAD, MM_MINI)
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
        # s_type может быть:
        # 1. API код (MM, MM_MINI, ME, DG, GM, MO, MC, ZARYAD)
        # 2. Русское название (Магнит, Мини, Экстра, и т.д.)
        # 3. Числовой код (1, 2, 3, и т.д.)
        
        # Сначала преобразуем API код в русское название, если нужно
        if s_type in STORE_TYPE_MAP:
            # s_type это API код (MM, MM_MINI, и т.д.)
            russian_name = STORE_TYPE_MAP[s_type]
        else:
            # s_type это русское название или числовой код
            russian_name = s_type
        
        # Теперь преобразуем русское название в числовой код
        s_type_code = API_STORE_TYPE_CODE.get(russian_name, russian_name)
        
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
            "storeType": s_type_code,
            "catalogType": "1",
        }

        # Если ищем товары по категориям, добавляем categories
        if category_ids:
            payload["categories"] = category_ids
        else:
            payload["categories"] = []

        try:
            logger.debug(f"DEBUG: POST {url}")
            logger.debug(f"DEBUG: Payload: {payload}")
            logger.debug(f"DEBUG: Payload JSON: {json.dumps(payload)}")

            response = self.session.post(url, json=payload, timeout=self.timeout)

            logger.debug(f"DEBUG: Response status: {response.status_code}")
            logger.debug(f"DEBUG: Response text: {response.text[:500]}")

            response.raise_for_status()
            data = response.json()

            logger.debug(f"DEBUG: Response keys: {list(data.keys())}")

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
            pagination = data.get("pagination", {})
            total = pagination.get("totalCount", len(items))
            has_more = pagination.get("hasMore", (offset + len(items)) < total)
            
            # Используем nextOffset из API, если он есть
            api_next_offset = pagination.get("nextOffset")
            if api_next_offset is not None:
                next_offset = api_next_offset if has_more else None
            else:
                # Если API не вернул nextOffset, вычисляем сами
                next_offset = offset + len(items) if has_more else None
            
            logger.debug(f"DEBUG pagination: offset={offset}, len(items)={len(items)}, total={total}, hasMore={has_more}, api_next_offset={api_next_offset}, next_offset={next_offset}")

            return {
                "items": items,
                "total": total,
                "hasMore": has_more,
                "next_offset": next_offset,
            }
        except requests.RequestException as e:
            logger.error(f"ERROR: {e}")
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
            logger.error(f"Ошибка парсинга категории: {e}")
            return None

    def _parse_product(self, item: dict) -> Optional[dict]:
        """Парсинг данных товара из ответа API."""
        try:
            product_id = item.get("id") or item.get("productId")
            if not product_id:
                return None

            # Цена — конвертируем из копеек в рубли
            current_price = item.get("price")
            product_name = item.get("name") or item.get("title", "")
            
            # API всегда возвращает цены в копейках, делим на 100
            if current_price:
                current_price = current_price / 100

            # Параметры заказа
            order_props = item.get("orderProperties") or {}
            min_order_qty = order_props.get("minOrderQuantity", 1)
            order_step_qty = order_props.get("orderStepQuantity", 1)

            # Рейтинги
            ratings = item.get("ratings") or {}
            rating = ratings.get("rating")
            scores_count = ratings.get("scoresCount", 0)
            comments_count = ratings.get("commentsCount", 0)

            # Весовые товары
            weighted = item.get("weighted") or {}
            is_weighted = weighted.get("isWeighted", False)
            unit_price = weighted.get("unitPrice")
            
            # API всегда возвращает цены в копейках, делим на 100
            if unit_price:
                unit_price = unit_price / 100

            # Первая картинка из gallery
            gallery = item.get("gallery", [])
            image_url = None
            if gallery and len(gallery) > 0:
                first_image = gallery[0]
                if first_image and isinstance(first_image, dict):
                    image_url = first_image.get("url")

            return {
                "product_id": int(product_id),
                "name": item.get("name") or item.get("title", "Без названия"),
                "sku": item.get("sku") or item.get("article"),
                "price": float(current_price) if current_price else 0.0,
                "currency": "₽",
                "unit": item.get("unit") or item.get("measureUnit", "шт"),
                "image_url": image_url,
                "in_stock": item.get("inStock", item.get("available", True)),
                # Остатки и доступность
                "quantity": item.get("quantity", 0),
                "is_low_stock": item.get("isLowStock"),
                "pickup_only": item.get("pickupOnly", False),
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
            logger.error(f"Ошибка парсинга товара: {e}")
            import traceback
            traceback.print_exc()
            return None

    def set_store_code(self, store_code: str):
        """Установить код магазина."""
        self.store_code = store_code

    def close(self):
        """Закрыть сессию."""
        self.session.close()


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
        import uuid
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.rate_limit = rate_limit
        self.session = requests.Session()
        self.device_id = str(uuid.uuid4())
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36",
                "Accept": "application/json, text/plain, */*",
                "Accept-Language": "en-US,en;q=0.9,ru-RU;q=0.8,ru;q=0.7",
                "Referer": "https://magnit.ru/",
                "Origin": "https://magnit.ru",
                "Content-Type": "application/json",
                "X-Client-Name": "magnit",
                "X-New-Magnit": "true",
                "X-App-Version": "2026.4.16-18.51",
                "X-Device-Platform": "Web",
                "X-Device-Id": self.device_id,
                "X-Device-Tag": "disabled",
                "X-Platform-Version": f"Windows Chrome {self.device_id[:3]}",
            }
        )
        self._last_request_time = 0

    def _rate_limit_wait(self):
        """Пауза между запросами (случайная 0.1-0.5 сек)."""
        if self._last_request_time > 0:
            elapsed = time.time() - self._last_request_time
            if elapsed < self.rate_limit:
                delay = self.rate_limit - elapsed
                time.sleep(delay)
        time.sleep(random.uniform(0.1, 0.5))
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
        Выполняет отдельный запрос для каждого типа магазина и объединяет результаты.

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
        
        # Сначала получаем cookies с главной страницы
        try:
            self.session.get(f"{self.base_url}/shops", timeout=10)
        except Exception as e:
            logger.warning(f"Warning: Could not get cookies: {e}")
        
        # Список типов для запроса
        types_to_search = store_types if store_types else ALL_STORE_TYPES
        
        all_stores = []
        
        # Выполняем отдельный запрос для каждого типа магазина
        for store_type in types_to_search:
            payload = {
                "filters": {
                    "query": query,
                    "storeTypeListV2": [store_type],  # Только один тип за запрос
                },
                "pagination": {
                    "offset": offset,
                    "size": limit,
                },
                "sorting": {
                    "sortBy": "SORT_BY_CITY",
                    "sortType": "SORT_TYPE_ASC",
                }
            }

            try:
                logger.debug(f"DEBUG StoresAPI: POST {url} (type={store_type})")
                logger.debug(f"DEBUG StoresAPI: Payload: {json.dumps(payload, ensure_ascii=False)}")
                logger.debug(f"DEBUG StoresAPI: Cookies: {self.session.cookies.get_dict()}")
                
                response = self.session.post(url, json=payload, timeout=self.timeout)
                
                logger.debug(f"DEBUG StoresAPI: Response status: {response.status_code}")
                logger.debug(f"DEBUG StoresAPI: Response text: {response.text[:500]}")
                
                if response.status_code == 200:
                    data = response.json()
                    # Ответ API имеет структуру: {"data": [...], "totalCount": N}
                    stores = data.get("data", [])
                    logger.debug(f"DEBUG StoresAPI: Found {len(stores)} stores for type {store_type}")
                    all_stores.extend(stores)
                else:
                    logger.debug(f"DEBUG StoresAPI: Response text: {response.text[:500]}")
                    
            except requests.RequestException as e:
                logger.error(f"ERROR StoresAPI for type {store_type}: {e}")
                # Продолжаем поиск для остальных типов

        # Дедупликация по code
        seen_codes = {}
        for store in all_stores:
            # API возвращает code в externalId.storeCode
            external_id = store.get("externalId", {})
            code = external_id.get("storeCode") or store.get("code") or store.get("store_code")
            if code and code not in seen_codes:
                seen_codes[code] = store
        
        unique_stores = list(seen_codes.values())
        
        logger.debug(f"DEBUG StoresAPI: Total unique stores: {len(unique_stores)}")

        return {
            "stores": unique_stores,
            "total": len(unique_stores),
            "hasMore": False,
        }

    def close(self):
        """Закрыть сессию."""
        self.session.close()
