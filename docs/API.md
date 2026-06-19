# API справочник

Полный каталог HTTP-эндпоинтов проекта `magnit_goods`. 

- **39 API-эндпоинтов** в `src/server/routes/`
- **10 роутов** в `main.py` (7 веб-страниц + 3 утилитарных, включая перекрытый `POST /api/stores`)

Swagger UI: http://localhost:8000/docs

## Содержание

- [Магазины (`/api/stores`)](#магазины--apistores) — 11 эндпоинтов
- [Задания (`/api/jobs`)](#задания--apijobs) — 4 эндпоинта
- [Каталог (`/api`)](#каталог--api) — 22 эндпоинта
- [Цены (`/api/prices`)](#цены--apiprices) — 2 эндпоинта
- [Роуты `main.py` (10)](#роуты-mainpy-10) — 7 страниц + 3 утилитарных
- [Порядок регистрации эндпоинтов](#порядок-регистрации-эндпоинтов)

---

## Магазины (`/api/stores`)

Префикс роутера: `/api/stores`, тег «Магазины». Файл: `src/server/routes/stores.py`.

**Вспомогательные функции модуля:**
- `_cleanup_stale_jobs(db)` (`stores.py:23`) — переводит зависшие задания типа `stores` со статусом `running` и `started_at` старше 2 минут в `failed`.
- `_mark_all_running_failed_on_startup(db)` (`stores.py:39`) — при старте сервера помечает **все** `running` задания как `failed`. Вызывается из `lifespan` в `main.py:33`.

| # | Метод | Путь | Обработчик | Назначение |
|---|-------|------|-----------|-----------|
| 1 | GET | `/api/stores` | `list_stores:53` | Список магазинов. Query: `city`, `store_type`, `is_active`. → `list[StoreResponse]` |
| 2 | POST | `/api/stores` | `create_store:71` | Создать магазин (JSON `StoreCreate`). 409 если `store_code` существует. → `StoreResponse` (201) |
| 3 | GET | `/api/stores/search` | `search_stores:84` | Поиск по `q` в `city`/`full_address`/`name`. Только `is_active=True`, лимит 20. → `list[StoreResponse]` |
| 4 | GET | `/api/stores/{store_id}` | `get_store:102` | Магазин по ID (MD5-хэш). → `StoreResponse` / 404 |
| 5 | PUT | `/api/stores/{store_id}` | `update_store:111` | Обновить (`StoreUpdate`, `exclude_unset`). → `StoreResponse` / 404 |
| 6 | DELETE | `/api/stores/{store_id}` | `delete_store:125` | Удалить. → 204 / 404 |
| 7 | POST | `/api/stores/select` | `select_store:136` | Выбрать магазин по адресу/типу → обновить `.env`. Тело `SelectStoreRequest`. → `{store_code, store_type, name, address, city, env_updated}` |
| 8 | POST | `/api/stores/preview` | `preview_stores:201` | Поиск через API Магнита без сохранения. Тело `ScanStoresRequest`. → `{total_found, stores: list[StorePreviewItem]}` |
| 9 | POST | `/api/stores/add-selected` | `add_selected_stores:320` | Добавить выбранные из preview. Тело `AddSelectedStoresRequest`. → `{added, skipped}` |
| 10 | POST | `/api/stores/delete-batch` | `delete_stores_batch:352` | Удалить несколько по ID. Тело `DeleteStoresRequest`. → 204 / 400 |
| 11 | GET | `/api/stores/by-code/{store_code}` | `get_store_by_code:366` | Магазин по `store_code` (для автозаполнения). → `StoreResponse` / 404 |

### `POST /api/stores/select` — особенности
- Тело: `SelectStoreRequest { city, street?, store_type, update_env=True }`.
- При `update_env=True` читает `.env`, обновляет `STORE_CODE` и `STORE_TYPE`, перезаписывает файл через `dotenv.load_dotenv()` (`stores.py:164`).
- 🔴 **Не редактируйте `.env` вручную** — используйте этот эндпоинт.

### `POST /api/stores/preview` — особенности
- Использует `StoresAPI` из `services/magnit_api.py`.
- Дедупликация по `store_code`. Преобразование `storeTypeV2` через `API_STORE_TYPE_MAP`.
- Извлечение города через `extract_city_from_address` (`utils/city_extractor.py`); при отсутствии города магазин пропускается.
- Помечает `exists_in_db` по существующим кодам. 502 при ошибке API.

> ⚠️ В `main.py:158` определён ещё один `POST /api/stores` (`create_store_htmx`) — HTMX-заглушка под form-data. Поскольку `app.include_router(stores.router)` (`main.py:81`) выполняется раньше, роутеровский `create_store` имеет приоритет; HTMX-вариант фактически перекрыт.

---

## Задания (`/api/jobs`)

Префикс: `/api/jobs`, тег «Задания». Файл: `src/server/routes/jobs.py`.

| # | Метод | Путь | Обработчик | Назначение |
|---|-------|------|-----------|-----------|
| 12 | GET | `/api/jobs` | `list_jobs:15` | Список заданий. Query: `job_type`, `status`, `limit=20`. → `list[ScanJobResponse]` (по `created_at DESC`) |
| 13 | GET | `/api/jobs/active` | `get_active_jobs:31` | Активные (`pending`/`running`). Query: `job_type`. → `list[ScanJobResponse]` |
| 14 | GET | `/api/jobs/{job_id}` | `get_job:43` | Статус задания. Path: `job_id: int`. → `ScanJobResponse` / 404 |
| 15 | POST | `/api/jobs/{job_id}/cancel` | `cancel_job:52` | Отменить. 400 если уже `completed`/`failed`. → `{status: "cancelled"}` |

> 🔴 **Порядок критичен:** `/api/jobs/active` определён ДО `/api/jobs/{job_id}` (строка 31 vs 43). Иначе «active» попало бы в `job_id: int` → 422. Реальная остановка фоновой задачи — через проверку `ScanJob.status == "cancelled"` в `CatalogScanner.scan_products()`.

---

## Каталог (`/api`)

Префикс: `/api`, тег «Каталог». Файл: `src/server/routes/catalog.py`.

**Глобальное состояние:**
- `_catalog_update_status` (`catalog.py:774`) — `dict` статуса обновления каталога: `{in_progress, total, processed, updated, not_found, errors}`.
- `_catalog_update_lock` (`catalog.py:782`) — `threading.Lock` для безопасного доступа к `_catalog_update_status`.

**Фоновая функция:** `_fetch_and_update_categories_background()` (`catalog.py:785`) — полная замена каталога через `replace_catalog_from_api()`. Под блокировкой обновляет `_catalog_update_status`.

### Категории

| # | Метод | Путь | Обработчик | Назначение |
|---|-------|------|-----------|-----------|
| 16 | GET | `/api/categories` | `list_categories:21` | Список категорий. Query: `tracked`, `parent_id`. Приоритет: `tracked` > `parent_id` > корневые. → `list[dict]` |
| 17 | POST | `/api/categories/scan` | `scan_categories:57` | Синхронно сканировать подкатегории из API. Query: `store_code` (обязательный). → `{status, scanned, added, updated, deleted}` |
| 18 | POST | `/api/categories/update-catalog` | `update_catalog_from_api:87` | Аналог `/scan` с расширенным логированием. Query: `store_code`. → `{status, scanned, added, updated, deleted}` |
| 19 | GET | `/api/categories/tree` | `get_categories_tree:128` | Дерево категорий с `children`. → `list[dict]` |
| 20 | POST | `/api/categories/load-from-json` | `load_categories_from_json:158` | Загрузить из `categories.json`. → `{status, scanned, added, updated}` / 404 |
| 21 | POST | `/api/categories/build-from-playwright` | `build_categories_from_playwright:176` | Алиас `load-from-json`. |
| 22 | POST | `/api/categories/seed-from-playwright` | `seed_categories:186` | Алиас `build-from-playwright`. |
| 23 | PUT | `/api/categories/{category_id}/track` | `toggle_category_tracking:194` | Включить/выключить отслеживание. Query: `track=True`. → `{id, name, is_tracked}` / 404 |
| 24 | POST | `/api/categories/update-tracking` | `update_categories_tracking:216` | Обновить отслеживание списка. Тело `{category_ids: [int]}`. Сначала сбрасывает ВСЕ, затем включает дочерние. → `{status, tracked_count, updated_ids}` |
| 25 | POST | `/api/categories/fetch-magnit-ids` | `fetch_magnit_category_ids_endpoint:866` | ⭐ Запустить полную замену каталога в отдельном потоке. → `{status: "started"}` или `{status: "in_progress", progress}` |
| 26 | GET | `/api/categories/fetch-magnit-ids/status` | `get_fetch_status:897` | Статус обновления каталога. → `{in_progress, total, processed, updated, not_found, error_count, errors}` |

### Товары

| # | Метод | Путь | Обработчик | Назначение |
|---|-------|------|-----------|-----------|
| 27 | GET | `/api/products` | `list_products:249` | Список товаров с фильтрами. Query: `store_code`, `category_id`, `category_ids` (CSV), `search`, `min_price`, `max_price`, `sort_by` (`name`/`price`/`last_seen`), `limit≤1000`, `offset`. → `list[dict]` |
| 28 | GET | `/api/products/stats` | `get_products_stats:388` | ⭐ Статистика. Query: `store_code`. → `{total, in_stock, with_price_decrease, with_price_increase, last_update}` |
| 29 | GET | `/api/products/multi-prices` | `get_multi_store_prices:415` | ⭐ Цены из нескольких магазинов. Query: `product_ids` (CSV), `store_codes` (CSV). → `{product_id: {store_code: {price, previous_price, ...}}}` |
| 30 | GET | `/api/products/{product_id}` | `get_product:458` | Детали товара. Path: `product_id: int`. Query: `store_code`. → `dict` / 404 |
| 31 | GET | `/api/products/{product_id}/history` | `get_product_price_history:496` | История цен по дням. Query: `store_code`, `days=30` (1..365). → `list[dict]` |
| 32 | DELETE | `/api/products/clear` | `clear_all_products:914` | Удалить все товары. → `{status, message, deleted_count}` |
| 33 | DELETE | `/api/products/clear-by-categories` | `clear_products_by_categories:930` | Удалить по категориям. Query: `category_ids` (CSV). → `{status, message, deleted_count}` |
| 34 | DELETE | `/api/products/clear-by-store` | `clear_products_by_store:953` | Удалить по магазину. Query: `store_code`. → `{status, message, deleted_count}` |

### Сканирование

| # | Метод | Путь | Обработчик | Назначение |
|---|-------|------|-----------|-----------|
| 35 | POST | `/api/catalog/scan` | `scan_products:527` | Синхронно сканировать товары. Query: `store_code` (обязательный), `category_ids` (CSV), `tracked_only=True`. → `{status, scanned, added, updated}` |
| 36 | POST | `/api/catalog/scan-all-stores` | `scan_all_stores:571` | ⭐ Фоновое сканирование всех активных магазинов. Query: `tracked_only=True`. → `{job_id, status, stores_count}` |
| 37 | POST | `/api/catalog/scan-prices` | `scan_prices_in_store:746` | Обновить цены в магазине. Query: `store_code`. → `{status, scanned, added, updated}` |

> ⚠️ **Расхождение с AGENTS.md:** ранее было `POST /api/products/scan` — фактически `/api/catalog/scan`.

### `POST /api/catalog/scan-all-stores` — особенности ⭐
- Использует `BackgroundTasks` (FastAPI).
- 400 если нет активных магазинов или отслеживаемых дочерних категорий.
- Создаёт `ScanJob` (job_type=`scan_all_stores`, store_code=`"{N} stores"`).
- Вложенная `run_scan_all` (`catalog.py:617`) создаёт отдельную `SessionLocal`, ведёт детальный прогресс (`current_store_*`, `current_category_*`). Прогресс: `current_operation / (total_stores * total_categories) * 100`.
- Проверяет `status == "cancelled"` для досрочной остановки.
- Если `background_tasks` не передан — выполняет синхронно.

### `GET /api/products` — особенности
- `response_model=list[dict]`. Поиск по `search` выполняется в Python через `casefold()` (Unicode-aware), т.к. SQLite `LOWER()` не работает с кириллицей.
- Логика «свежих» товаров по `last_scan_found` (окно 1 час от максимума по категории) — только при указанном `store_code`.
- Поля ответа включают: `product_id, name, price, previous_price, price_change_percent, last_price_change, last_change_price, last_change_date, currency, unit, image_url, in_stock, category_id, store_code, category_name, category_parent_id, quantity, is_low_stock, pickup_only, rating, scores_count, comments_count, seo_code, is_weighted, unit_price, first_seen, last_seen`.

---

## Цены (`/api/prices`)

Префикс: `/api/prices`, тег «Цены». Файл: `src/server/routes/prices.py`.

| # | Метод | Путь | Обработчик | Назначение |
|---|-------|------|-----------|-----------|
| 38 | GET | `/api/prices/decreased` | `get_decreased_prices:16` | Товары со сниженными ценами. Query: `store_code` (обязательный), `min_discount_percent=10.0`, `limit≤500`. → `list[dict]` |
| 39 | POST | `/api/prices/update` | `update_prices:53` | ⭐ Фоновое обновление цен. Query: `store_code` (обязательный), `category_ids` (CSV), `tracked_only=True`. → `{job_id, status}` |

> ⚠️ **Расхождения с AGENTS.md:**
> - Ранее `GET /api/prices/alerts` — фактически `/api/prices/decreased`.
> - Ранее `GET /api/prices/history/{product_id}` — фактически `GET /api/products/{product_id}/history` (в `catalog.py:496`).

### `POST /api/prices/update` — особенности ⭐
- Использует `BackgroundTasks` (FastAPI).
- 400 при неверном формате `category_ids`.
- Создаёт `ScanJob` (job_type=`prices`).
- Вложенная `run_update` (`prices.py:86`) создаёт **новую `SessionLocal()`** (не переиспользует закрытую FastAPI-сессию), ставит `status="running"`, вызывает `CatalogScanner.scan_products`, финализирует `completed`/`failed`.

---

## Роуты `main.py` (10)

Файл: `src/server/main.py`. Определены напрямую на `app` (не через `include_router`).

### Веб-страницы (HTML, 7)

| Метод | Путь | Строка | Назначение |
|-------|------|--------|-----------|
| GET | `/` | `main.py:90` | Главная — управление магазинами (`stores.html`) |
| GET | `/catalog` | `main.py:104` | Страница категорий |
| GET | `/products` | `main.py:113` | Страница товаров |
| GET | `/test-discount` | `main.py:122` | Тестовая страница скидок |
| GET | `/test-stores-loading` | `main.py:130` | Тестовая страница загрузки магазинов |
| GET | `/jobs` | `main.py:139` | Страница фоновых заданий |
| GET | `/shopping-list` | `main.py:148` | Страница списка покупок |

### Утилитарные (3)

| Метод | Путь | Строка | Назначение |
|-------|------|--------|-----------|
| POST | `/api/stores` | `main.py:158` | HTMX-заглушка создания магазина (form-data). **Перекрыта** роутером `stores.router` — недостижима |
| GET | `/redirect-to-product` | `main.py:192` | Редирект на magnit.ru с установкой cookies `shopCode`, `x_shop_type` (max_age=3600). Query: `url`, `shop_code`, `x_shop_type` |
| GET | `/open-product-in-browser` | `main.py:205` | ⭐ Открыть товар в браузере через Playwright (фоновый `threading.Thread`). Query: `product_url`, `store_code`, `store_type`. → `{status: "opening", message}` |

---

## Порядок регистрации эндпоинтов

FastAPI матчит маршруты **в порядке регистрации**. Статические пути должны идти ДО параметрических.

### `catalog.py` — `/api/products/*` (критично)
1. `GET /api/products` (`:249`) — статический
2. `GET /api/products/stats` (`:388`) — статический, **ДО** `{product_id}` ★
3. `GET /api/products/multi-prices` (`:415`) — статический, **ДО** `{product_id}` ★
4. `GET /api/products/{product_id}` (`:458`) — параметрический, последним
5. `GET /api/products/{product_id}/history` (`:496`) — двухсегментный, не конфликтует
6. `DELETE /api/products/clear*` (`:914`, `:930`, `:953`) — другой метод, не конфликтуют

> 🔴 Если бы `/stats` или `/multi-prices` были после `/{product_id}` — «stats»/«multi-prices» попали бы в `product_id: int` → 422.

### `jobs.py` — критично
- `GET /api/jobs/active` (`:31`) — **ДО** `GET /api/jobs/{job_id}` (`:43`)

### `stores.py` — критично
- `GET /api/stores/search` (`:84`) — **ДО** `GET /api/stores/{store_id}` (`:102`). Иначе «search» попало бы в `store_id: str` (не упало бы, но искало бы магазин с id="search" → 404).
- `GET /api/stores/by-code/{store_code}` (`:366`) — двухсегментный, не конфликтует.

---

## Фоновые задачи и потоки

| Эндпоинт | Механизм | Назначение |
|----------|---------|-----------|
| `POST /api/catalog/scan-all-stores` | `BackgroundTasks` (FastAPI) | Сканирование всех магазинов |
| `POST /api/prices/update` | `BackgroundTasks` (FastAPI) | Обновление цен |
| `POST /api/categories/fetch-magnit-ids` | `threading.Thread` (daemon) | Полная замена каталога |
| `GET /open-product-in-browser` | `threading.Thread` | Запуск Playwright |

> 🔴 **Важно:** фоновые задачи создают **свою `SessionLocal()`** внутри — не используют сессию из FastAPI-dependency (она закрывается после HTTP-ответа). См. `docs/DEVELOPMENT.md`.
