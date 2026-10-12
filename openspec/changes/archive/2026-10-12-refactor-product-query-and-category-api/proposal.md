# Proposal

## Why

Невыполненные шаги `docs/PLAN_FIXES_2026-09-27.md` о слое API каталога:
- поиск товаров грузит все товары магазина в Python и делает второй запрос с `IN (тысячи id)` — главное узкое место UI;
- логика выборки товаров живёт в роуте;
- синхронизация категорий реализована дважды (`CatalogScanner.scan_categories` и `CatalogUpdater.update_category_from_api`);
- четыре эндпоинта категорий делают одно и то же;
- ответы ключевых эндпоинтов не описаны схемами, поэтому поля могут незаметно измениться;
- в запросах остались `!= None` с `noqa`.

Это шаги 4.1 (остаток после `unify-store-type-and-tracking`), 4.2, 5.1, 6.2, 6.3 и 6.4 плана.

## What Changes

- **Поиск товаров** выполняется одним SQL-запросом по нормализованному полю названия (casefold) — шаг 5.1:
  - результат совпадает с прежним, включая регистронезависимый поиск по кириллице;
  - поле заполняется при сохранении товаров и миграцией для существующих.
- **Выборка товаров** выносится из роута `GET /api/products` в сервисный модуль. Роут только разбирает параметры и формирует ответ (шаг 6.4).
- **Схемы ответов**: `GET /api/products`, `GET /api/products/stats`, `GET /api/prices/decreased` получают Pydantic-схемы ответа. Набор и имена полей не меняются (шаг 6.3).
- **Синхронизация категорий**: единственная реализация — `CatalogScanner.scan_categories`. Дубли в `CatalogUpdater` (`update_category_from_api`, `update_all_categories`, сервисная `update_catalog_from_api`) удаляются (шаг 4.1).
- **Эндпоинты категорий** (шаг 4.2):
  - `POST /api/categories/update-catalog` — основной;
  - `POST /api/categories/scan` помечается устаревшим (`deprecated`) и работает как прежде;
  - **BREAKING:** удаляются алиасы `POST /api/categories/build-from-playwright` и `POST /api/categories/seed-from-playwright` — UI их не вызывает, остаётся `POST /api/categories/load-from-json`.
- **Сравнения с NULL** в запросах — через `.isnot(None)` / `.is_(None)`, без `# noqa: E711` (шаг 6.2).

## Capabilities

### New Capabilities
Нет.

### Modified Capabilities
Нет — в `openspec/specs/` пока нет спецификаций. Требования добавляются как ADDED с новыми именами в `product-catalog` и `category-catalog`, которые вводит `fix-data-integrity-bugs`.

## Impact

- **Новый модуль** `src/server/services/product_query.py` — фильтры, видимость, поиск, сортировка, пагинация.
- **Модели и БД:**
  - `src/server/models.py` — колонка `Product.name_search`;
  - `src/server/database.py` — миграция `add_product_name_search` (колонка + заполнение батчами), правка `!= None`.
- **Сканер:** `src/server/services/catalog_scanner.py` — запись `name_search` в bulk insert/update.
- **Роуты:**
  - `src/server/routes/catalog.py` — `list_products`, `get_products_stats`, роуты категорий, `!= None`;
  - `src/server/routes/prices.py` — `response_model`.
- **Схемы:** `src/server/schemas.py` — `ProductListItem`, `ProductStats`, `DecreasedPriceItem`.
- **Удаление дублей:** `src/server/services/catalog_updater.py` — удаление дублирующей синхронизации.
- **Документация:** `docs/API.md` — удалённые алиасы, deprecated `/categories/scan`, схемы ответов.
- **Порядок:** применять после `fix-data-integrity-bugs`, `unify-store-type-and-tracking` и `harden-runtime-reliability`, до `sync-docs-and-dead-code`.
