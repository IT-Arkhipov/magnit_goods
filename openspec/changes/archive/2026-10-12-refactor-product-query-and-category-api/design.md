# Design

## Context

Мотивация — в proposal.md, требования — в specs/. Состояние кода к моменту применения (после трёх предыдущих изменений цикла):

- **`list_products`** (`routes/catalog.py`): внутри роута определена функция `_build_filtered_query()` — фильтры, окно видимости, наличие.
  - При `search` все кандидаты загружаются в Python и фильтруются через `casefold()`, затем выполняется второй запрос `Product.id IN (...)` (исправление `fix-data-integrity-bugs`).
  - `LOWER()` в SQLite не работает с кириллицей — поэтому и casefold в Python.
- **Ответы** формируются вручную как `dict`; дата/время отдаются строками `isoformat()`.
  - `response_model=list[dict]` у `/products`, `/prices/decreased`; у `/products/stats` модели нет.
  - Шаблоны читают поля напрямую.
- **`CatalogUpdater`** после `unify-store-type-and-tracking` ходит в API через `MagnitAPIClient`, но по-прежнему содержит `update_category_from_api` и `update_all_categories` — копию `CatalogScanner.scan_categories`. Вызывающих их роутов нет.
- **Роуты категорий:**
  - `/categories/scan` и `/categories/update-catalog` — идентичны;
  - `/categories/build-from-playwright` и `/categories/seed-from-playwright` — алиасы `load-from-json`.
  - Шаблоны используют только `fetch-magnit-ids`, `tree`, `update-tracking`, `/categories`.

## Goals / Non-Goals

**Goals:**
- Поиск одним SQL-запросом без загрузки товаров в Python.
- Тонкий роут `list_products`; схемы ответов, фиксирующие текущий контракт.

**Non-Goals:**
- Полнотекстовый поиск (FTS5), морфология, поиск по SKU.
- Изменение формата дат в ответах (остаются строками `isoformat()`).
- Схемы ответов для остальных эндпоинтов — по мере надобности, отдельными изменениями.

## Decisions

### D1. Колонка `Product.name_search` = `name.casefold()`
- **Модель:** `name_search = Column(String, nullable=True)`.
- **Миграция `add_product_name_search`:** `ALTER TABLE` (если колонки нет, проверка через `inspect`), затем заполнение батчами по 1000 строк. Читаются `id, name`, пишется `bulk_update_mappings` с `name_search = (name or "").casefold()`.
- **Сканер:** в `_save_products` поле вычисляется в обеих ветках, insert и update. В update — от итогового `name`, чтобы переименование сразу отражалось в поиске.
- **Поиск:** `Product.name_search.like(f"%{escaped}%", escape="\\")`. В `escaped` из `search.casefold().strip()` экранированы `\`, `%` и `_`, чтобы пользовательский ввод не работал как шаблон.

*Почему casefold в Python, а не SQL-функция:* можно зарегистрировать `create_function("py_casefold")` в событии `connect`, но тогда индекс и колонка не нужны, а каждый запрос вызывает Python для каждой строки. Хранимая колонка дешевле на чтении, которое здесь основное. ICU-сборки SQLite в окружении нет.

*Почему без индекса:* `LIKE '%...%'` с ведущим `%` индекс не использует. Выигрыш даёт один запрос вместо загрузки всех строк в Python.

### D2. Сервис `services/product_query.py`
- **`ProductFilters`** (dataclass): `store_code`, `category_id`, `category_ids`, `min_price`, `max_price`, `search`, `relax_stale`, `include_out_of_stock`.
- **`build_product_query(db, filters) -> Query`**: все фильтры, включая поиск по `name_search`, окно видимости (`STALE_DAYS_VISIBLE` / `STALE_DAYS_DELETE`), наличие, `joinedload(Product.category)`.
- **`list_products(db, filters, sort_by, limit, offset) -> list[Product]`**: сортировка и пагинация.
- **`product_to_list_item(p) -> dict`**: текущий формат элемента ответа.
- **`get_products_stats(db, store_code) -> dict`**: агрегаты из роута.

Роут `list_products` разбирает query-параметры (включая `category_ids` через запятую), вызывает сервис и отдаёт результат. Поиск и обычный список проходят один путь, поэтому расхождение фильтров, исправленное в `fix-data-integrity-bugs`, повториться не может.

### D3. Схемы ответов фиксируют текущий контракт
В `schemas.py`:
- `ProductListItem` — все поля, которые сейчас возвращает `list_products`. Даты имеют тип `Optional[str]`, остальные поля — свои типы, все nullable-поля — `Optional`.
- `ProductStats` — `total`, `in_stock`, `with_price_decrease`, `with_price_increase`, `last_update: Optional[str]`.
- `DecreasedPriceItem` — `product_id`, `name`, `price`, `previous_price`, `change_percent`, `last_price_change: str`, `image_url`.

Подключение: `response_model=list[ProductListItem]` и т. д. Сервис по-прежнему отдаёт `dict`, FastAPI валидирует его и фильтрует лишние поля (так `name_search` не попадает в ответ).

*Почему даты строками:* сериализация `datetime` в Pydantic совпадает с `isoformat()` не во всех случаях (микросекунды, таймзона). Контракт фиксируется без изменения формата.

Проверка совместимости: до и после правки снимается ответ `GET /api/products?store_code=X&limit=5` и сравнивается набор ключей и значений.

### D4. Удаление дублирующей синхронизации категорий
Из `catalog_updater.py` удаляются `update_category_from_api`, `update_all_categories` и модульная функция `update_catalog_from_api`. В `CatalogUpdater` остаётся `replace_all_categories` (upsert из `fix-data-integrity-bugs`) вместе с `load_root_categories_from_file` и `fetch_category_data` (через `MagnitAPIClient`). Перед удалением выполняется `grep` по репозиторию без каталогов агентов. Если `sync-docs-and-dead-code` применится позже, её проверка «удалять только неиспользуемое» просто не найдёт эти имена.

### D5. Роуты категорий
- `@router.post("/categories/scan", deprecated=True)` — тело заменяется вызовом той же функции, что и у `update-catalog` (общая `_sync_subcategories(store_code, store_type, db)`), чтобы ответы совпадали буквально.
- Алиасы `build-from-playwright` и `seed-from-playwright` удаляются. Перед этим `grep -rn "build-from-playwright\|seed-from-playwright" src/ docs/` подтверждает, что вызовы есть только в документации.

### D6. `!= None` → `.isnot(None)`
Затрагивает `routes/catalog.py` (два места: `update-tracking` и `scan-all-stores`, если после `unify-store-type-and-tracking` они ещё есть) и `database.py:migrate_fill_shop_type`. Соответствующие `# noqa: E711` удаляются. Для `== True` с `# noqa: E712` поведение не меняется — это отдельное решение, оно не входит в шаг 6.2.

## Risks / Trade-offs

- [Миграция заполнения на большой БД при старте] → батчи по 1000 строк, около 5–10 тыс. товаров, единицы секунд. Миграция выполняется один раз.
- [Товар без `name_search`, вставленный в обход сканера] → такой товар не находится поиском. Других путей вставки товаров нет; при необходимости миграцию можно сделать повторно применимой через `WHERE name_search IS NULL`.
- [`response_model` отбросит поле, которое забыли описать] → сравнение ответов до и после (D3) для каждого эндпоинта.
- [Внешний клиент вызывает удалённые алиасы] → BREAKING описан в `docs/API.md`; замена — `load-from-json`.

## Migration Plan

Перезапуск сервера выполняет миграцию `add_product_name_search`. Откат — `git revert`. Колонка `name_search` остаётся в БД, старый код её игнорирует.
