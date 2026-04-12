"""
Клиент для работы с API Магнита.
Используется для сканирования каталога товаров и получения данных о ценах.
"""
import requests
from typing import Optional
from datetime import datetime
import time
import os


class MagnitAPIClient:
    """Клиент для взаимодействия с API Магнита."""

    def __init__(
        self,
        base_url: str = "https://magnit.ru",
        store_code: Optional[str] = None,
        timeout: int = 15,
        rate_limit: float = 0.5,
    ):
        self.base_url = base_url.rstrip("/")
        self.store_code = store_code or os.getenv("STORE_CODE")
        self.timeout = timeout
        self.rate_limit = rate_limit
        self.session = requests.Session()
        self.session.headers.update({
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
        })
        self._last_request_time = 0

    def _rate_limit_wait(self):
        """Пауза между запросами для соблюдения rate limiting."""
        if self._last_request_time > 0:
            elapsed = time.time() - self._last_request_time
            if elapsed < self.rate_limit:
                time.sleep(self.rate_limit - elapsed)
        self._last_request_time = time.time()

    def get_categories(self, store_code: Optional[str] = None) -> list[dict]:
        """
        Получить список категорий каталога.

        Возвращает:
            Список категорий: [{"id": 4884, "name": "Молоко, сыр, яйца", "productCount": 120}, ...]
        """
        self._rate_limit_wait()
        code = store_code or self.store_code
        if not code:
            raise ValueError("store_code не указан")

        url = f"{self.base_url}/webgate/v1/goods/filters"
        payload = {
            "storeCodes": [code],
            "catalogType": "1",
        }

        try:
            response = self.session.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()

            # Структура ответа может отличаться, адаптируемся
            categories = []
            if "categories" in data:
                categories = data["categories"]
            elif "filters" in data and "categories" in data["filters"]:
                categories = data["filters"]["categories"]
            elif isinstance(data, list):
                categories = data

            return [
                {
                    "category_id": cat.get("id") or cat.get("categoryId"),
                    "name": cat.get("name"),
                    "product_count": cat.get("productCount", 0),
                    "parent_id": cat.get("parentId"),
                }
                for cat in categories
                if cat.get("id") or cat.get("categoryId")
            ]
        except requests.RequestException as e:
            raise Exception(f"Ошибка получения категорий: {str(e)}")

    def get_products(
        self,
        category_ids: list[int],
        store_code: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        sort_type: str = "popularity",
    ) -> dict:
        """
        Получить список товаров из указанных категорий.

        Args:
            category_ids: ID категорий
            store_code: Код магазина
            limit: Кол-во товаров за запрос (макс ~50-100)
            offset: Смещение для пагинации
            sort_type: Тип сортировки (popularity, price_asc, price_desc)

        Returns:
            {
                "products": [...],
                "total": 1234,
                "hasMore": True
            }
        """
        self._rate_limit_wait()
        code = store_code or self.store_code
        if not code:
            raise ValueError("store_code не указан")

        url = f"{self.base_url}/webgate/v1/goods"
        payload = {
            "categories": category_ids,
            "storeCode": code,
            "pagination": {
                "limit": limit,
                "offset": offset,
            },
            "sort": {
                "type": sort_type,
                "order": "desc",
            },
        }

        try:
            response = self.session.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()

            products = []
            raw_products = []

            # Адаптация к структуре ответа
            if "goods" in data:
                raw_products = data["goods"]
            elif "products" in data:
                raw_products = data["products"]
            elif isinstance(data, list):
                raw_products = data

            for item in raw_products:
                product = self._parse_product(item)
                if product:
                    products.append(product)

            # Пагинация
            total = data.get("total", len(products))
            has_more = data.get("hasMore", (offset + len(products)) < total)

            return {
                "products": products,
                "total": total,
                "hasMore": has_more,
                "next_offset": offset + len(products) if has_more else None,
            }
        except requests.RequestException as e:
            raise Exception(f"Ошибка получения товаров: {str(e)}")

    def _parse_product(self, item: dict) -> Optional[dict]:
        """Парсинг данных товара из ответа API."""
        try:
            product_id = item.get("id") or item.get("productId")
            if not product_id:
                return None

            # Цена
            price_data = item.get("price", {})
            current_price = price_data.get("value") or item.get("priceValue")
            old_price = price_data.get("oldValue") or item.get("oldPrice")

            # Если цена в копейках, конвертируем в рубли
            if current_price and current_price > 1000:
                current_price = current_price / 100
            if old_price and old_price > 1000:
                old_price = old_price / 100

            return {
                "product_id": int(product_id),
                "name": item.get("name") or item.get("title", "Без названия"),
                "sku": item.get("sku") or item.get("article"),
                "price": float(current_price) if current_price else 0.0,
                "old_price": float(old_price) if old_price else None,
                "currency": "₽",
                "unit": item.get("unit") or item.get("measureUnit", "шт"),
                "image_url": item.get("imageUrl") or item.get("image"),
                "in_stock": item.get("inStock", item.get("available", True)),
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
