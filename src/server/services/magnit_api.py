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
            "X-Client-Name": "magnit",
            "X-New-Magnit": "true",
            "X-App-Version": "2026.4.10-19.26",
            "X-Device-Platform": "Web",
        })
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
            query: Поисковый запрос (город, улица, адрес)
            store_types: Список типов магазинов (MM, GM, DG, ME, MO, MC, ZARYAD)
            limit: Кол-во результатов за запрос
            offset: Смещение для пагинации

        Returns:
            {
                "stores": [...],
                "total_count": N,
                "has_more": True/False,
            }
        """
        self._rate_limit_wait()

        if store_types is None:
            store_types = ALL_STORE_TYPES

        url = f"{self.base_url}/webgate/v1/stores-facade/search/detail"
        payload = {
            "filters": {
                "query": query,
                "storeTypeListV2": store_types,
            },
            "pagination": {
                "offset": offset,
                "size": limit,
            },
            "sorting": {
                "sortBy": "SORT_BY_CITY",
                "sortType": "SORT_TYPE_ASC",
            },
        }

        try:
            response = self.session.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            data = response.json()

            raw_stores = data.get("data", [])
            total_count = data.get("totalCount", 0)

            stores = []
            for item in raw_stores:
                store = self._parse_store(item)
                if store:
                    stores.append(store)

            return {
                "stores": stores,
                "total_count": total_count,
                "has_more": (offset + len(stores)) < total_count,
                "next_offset": offset + len(stores) if (offset + len(stores)) < total_count else None,
            }
        except requests.RequestException as e:
            raise Exception(f"Ошибка поиска магазинов: {str(e)}")

    def search_all_stores(
        self,
        query: str,
        store_types: Optional[list[str]] = None,
        page_size: int = 50,
        progress_callback=None,
        max_pages: int = 20,
    ) -> list[dict]:
        """
        Поиск всех магазинов с пагинацией.

        Args:
            query: Поисковый запрос
            store_types: Список типов
            page_size: Размер страницы
            progress_callback: Функция (progress, message)
            max_pages: Максимальное число страниц (защита от зацикливания)

        Returns:
            Полный список найденных магазинов
        """
        all_stores = []
        offset = 0
        page_num = 0

        if progress_callback:
            progress_callback(5, f"Поиск: {query}")

        while page_num < max_pages:
            page_num += 1
            result = self.search_stores(query, store_types, limit=page_size, offset=offset)
            new_stores = result["stores"]
            all_stores.extend(new_stores)

            total = result["total_count"]
            current = len(all_stores)

            if progress_callback:
                progress_pct = min(90, int((current / max(total, 1)) * 85) + 5)
                progress_callback(progress_pct, f"Найдено {current}/{total} магазинов")

            # Нет больше данных
            if not result["has_more"]:
                break

            # Не получили ни одного нового магазина — зацикливание
            if len(new_stores) == 0:
                break

            offset = result["next_offset"]
            time.sleep(self.rate_limit)

        if progress_callback:
            progress_callback(100, f"Найдено {len(all_stores)} магазинов")

        return all_stores

    def _parse_store(self, item: dict) -> Optional[dict]:
        """Парсинг данных магазина из ответа API."""
        try:
            external_id = item.get("externalId", {})
            store_code = external_id.get("storeCode")
            if not store_code:
                return None

            store_type_v2 = item.get("storeTypeV2", "")
            store_type_name = STORE_TYPE_MAP.get(store_type_v2, store_type_v2)

            # Извлекаем город из адреса
            address = item.get("address", "")
            city = self._extract_city(address)

            # Расписание
            timetable = {}
            for tt in item.get("timetableList", []):
                key = tt.get("key", "")
                value = tt.get("value", {})
                if "weeklySchedule" in value:
                    schedule = value["weeklySchedule"]
                    # Берём понедельник как пример
                    monday = schedule.get("monday", {})
                    if not monday.get("isDayOff", True):
                        daily = monday.get("dailySchedule", {})
                        timetable["opening"] = daily.get("openingTime", "")
                        timetable["closing"] = daily.get("closingTime", "")
                        break

            return {
                "store_code": str(store_code),
                "store_type": store_type_name,
                "store_type_code": store_type_v2,
                "name": f"Магнит {store_type_name}",
                "full_address": address,
                "address": self._extract_short_address(address, city),
                "city": city,
                "latitude": item.get("coordinates", {}).get("latitude"),
                "longitude": item.get("coordinates", {}).get("longitude"),
                "is_active": item.get("isActive", True),
                "opening_time": timetable.get("opening"),
                "closing_time": timetable.get("closing"),
            }
        except Exception as e:
            print(f"Ошибка парсинга магазина: {e}")
            return None

    def _extract_city(self, address: str) -> str:
        """Извлечь город из полного адреса.

        Поддерживаемые форматы:
        - 'г Новочебоксарск' / 'г. Новочебоксарск' / 'город Новочебоксарск'
        - 'Новочебоксарск г' / 'Новочебоксарск г.'
        - 'Новочебоксарск,' (просто название города)
        """
        import re

        # Список известных городов Чувашии для fallback
        known_cities = [
            "Новочебоксарск", "Чебоксары", "Шумерля", "Канаш", "Алатырь",
            "Моргауши", "Козловка", "Цивильск", "Ядрин", "Мариинский Посад",
        ]

        patterns = [
            # 'г Новочебоксарск' или 'г. Новочебоксарск'
            r'г\.?\s+([\w\-]+)',
            # 'город Новочебоксарск'
            r'город\s+([\w\-]+)',
            # 'Новочебоксарск г' или 'Новочебоксарск г.'
            r'([\w\-]+)\s+г\.?',
            # 'Новочебоксарск,' — город перед запятой
            r'([\w\-]+),',
        ]

        for pattern in patterns:
            match = re.search(pattern, address, re.IGNORECASE)
            if match:
                candidate = match.group(1)
                # Проверяем что это не слово-артефакт
                skip_words = ('ул', 'д', 'д.', 'з', 'зд', 'кв', 'к.', 'респ', 'республика',
                              'чувашия', 'чувашская', 'р-ка', 'обл', 'область', 'край', 'авто')
                if candidate.lower() not in skip_words:
                    return candidate

        # Fallback: ищем известный город в адресе
        for city in known_cities:
            if city.lower() in address.lower():
                return city

        return ""

    def _extract_short_address(self, full_address: str, city: str) -> str:
        """Извлечь краткий адрес (без региона и города)."""
        if not city:
            return full_address
        # Убираем всё до города включительно
        idx = full_address.find(f'г {city}')
        if idx == -1:
            idx = full_address.find(f'г. {city}')
        if idx != -1:
            short = full_address[idx:].replace(f'г {city}', '').replace(f'г. {city}', '').strip()
            return short.lstrip(',').strip()
        return full_address

    def close(self):
        """Закрыть сессию."""
        self.session.close()
