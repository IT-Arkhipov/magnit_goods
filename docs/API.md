# API справочник

Полный каталог HTTP-эндпоинтов проекта `magnit_goods`. 

- **37 API-эндпоинтов** в `src/server/routes/` (stores 11, jobs 4, catalog 20, prices 2)
- **7 роутов** в `main.py` (5 веб-страниц + 2 утилитарных)

Swagger UI: http://localhost:8000/docs

## Содержание

- [Магазины (`/api/stores`)](#магазины--apistores) — 11 эндпоинтов
- [Задания (`/api/jobs`)](#задания--apijobs) — 4 эндпоинта
- [Каталог (`/api`)](#каталог--api) — 20 эндпоинтов (категории 9, товары 8, сканирование 3)
- [Цены (`/api/prices`)](#цены--apiprices) — 2 эндпоинта
- [Роуты `main.py` (7)](#роуты-mainpy-7) — 5 страниц + 2 утилитарных
- [Порядок регистрации эндпоинтов](#порядок-регистрации-эндпоинтов)

---

## Магазины (`/api/stores`)

Префикс роутера: `/api/stores`, тег «Магазины». Файл: `src/server/routes/stores.py`.

**Очистка заданий при старте:** `lifespan` в `main.py` вызывает `services/jobs.py:mark_unfinished_jobs_failed` — все задания в статусах `pending` и `running` переводятся в `failed` («Сервер был перезапущен, задание прервано»).

| # | Метод | Путь | Обработчик | Назначение |
|---|-------|------|-----------|-----------|
| 1 | GET | `/api/stores` | `list_stores` | Список магазинов. Query: `city`, `store_type`, `is_active`. → `list[StoreResponse]` |
| 2 | POST | `/api/stores` | `create_store` | Создать магазин (JSON `StoreCreate`). **409**, если магазин с такой парой (`store_code`, `store_type`) уже есть (один код может принадлежать магазинам разных типов). → `StoreResponse` (201) |
| 3 | GET | `/api/stores/search` | `search_stores` | Поиск по `q` в `city`/`full_address`/`name`. Только `is_active=True`, лимит 20. → `list[StoreResponse]` |
| 4 | GET | `/api/stores/{store_id}` | `get_store` | Магазин по ID (MD5-хэш). → `StoreResponse` / 404 |
| 5 | PUT | `/api/stores/{store_id}` | `update_store` | Обновить (`StoreUpdate`, `exclude_unset`). **400**, если меняются `store_type` или `full_address` (из них вычисляется `id`) — удалите магазин и добавьте заново; совпадающие значения допускаются. → `StoreResponse` / 400 / 404 |
| 6 | DELETE | `/api/stores/{store_id}` | `delete_store` | Удалить. → 204 / 404 |
| 7 | POST | `/api/stores/select` | `select_store` | Выбрать магазин по адресу/типу → обновить `.env`, окружение процесса и задания планировщика (перезапуск не нужен). Тело `SelectStoreRequest`. → `{store_code, store_type, name, address, city, env_updated, scheduler_updated}` |
| 8 | POST | `/api/stores/preview` | `preview_stores` | Поиск через API Магнита без сохранения. Тело `ScanStoresRequest`; **400**, если в `store_types` есть неподдерживаемый тип (доступны: Магнит, Мини, Семейный, Экстра, Моя цена, М.Косметик). → `{total_found, stores: list[StorePreviewItem]}` |
| 9 | POST | `/api/stores/add-selected` | `add_selected_stores` | Добавить выбранные из preview; пропускаются только пары (`store_code`, `store_type`), уже существующие в БД (и дубли внутри запроса). Тело `AddSelectedStoresRequest`. → `{added, skipped}` |
| 10 | POST | `/api/stores/delete-batch` | `delete_stores_batch` | Удалить несколько по ID. Тело `DeleteStoresRequest`. → 204 / 400 |
| 11 | GET | `/api/stores/by-code/{store_code}` | `get_store_by_code` | Магазин по `store_code` (для автозаполнения). → `StoreResponse` / 404 |

### `POST /api/stores/select` — особенности
- Тело: `SelectStoreRequest { city, street?, store_type, update_env=True }`.
- При `update_env=True` читает `.env`, обновляет `STORE_CODE` и `STORE_TYPE`, перезаписывает файл (`stores.py:select_store`), обновляет `os.environ` работающего процесса и вызывает `scheduler.py:register_jobs` — задания планировщика перенацеливаются на выбранный магазин (при необходимости планировщик запускается). Результат — поле `scheduler_updated`.
- 🔴 **Не редактируйте `.env` вручную** — используйте этот эндпоинт.

### `POST /api/stores/preview` — особенности
- Использует `StoresAPI` из `services/magnit_api.py`.
- Дедупликация по паре (`store_code`, тип): один код у магазинов разных типов — разные магазины. Преобразование `storeTypeV2` через `STORE_TYPE_MAP` (`constants.py`).
- Извлечение города через `extract_city_from_address` (`utils/city_extractor.py`); при отсутствии города магазин пропускается.
- Помечает `exists_in_db` по паре (`store_code`, тип). **400** при неподдерживаемом типе (`PREVIEW_STORE_TYPES` в `constants.py`). 502 при ошибке API.

> ⚠️ **Изменения контракта (BREAKING):** `PUT /api/stores/{id}` отклоняет смену `store_type`/`full_address` (400); `POST /api/stores/preview` отвечает 400 на неподдерживаемые типы (раньше они молча заменялись набором по умолчанию); `POST /api/stores` и `add-selected` считают дубликатом только пару (код, тип), а не один код.

---

## Задания (`/api/jobs`)

Префикс: `/api/jobs`, тег «Задания». Файл: `src/server/routes/jobs.py`.

| # | Метод | Путь | Обработчик | Назначение |
|---|-------|------|-----------|-----------|
| 12 | GET | `/api/jobs` | `list_jobs` | Список заданий. Query: `job_type`, `status`, `limit=20`. → `list[ScanJobResponse]` (по `created_at DESC`) |
| 13 | GET | `/api/jobs/active` | `get_active_jobs` | Активные (`pending`/`running`). Query: `job_type`. → `list[ScanJobResponse]` |
| 14 | GET | `/api/jobs/{job_id}` | `get_job` | Статус задания. Path: `job_id: int`. → `ScanJobResponse` / 404 |
| 15 | POST | `/api/jobs/{job_id}/cancel` | `cancel_job` | Отменить. 400 если уже `completed`/`failed`. → `{status: "cancelled"}` |

> 🔴 **Порядок критичен:** `/api/jobs/active` определён ДО `/api/jobs/{job_id}`. Иначе «active» попало бы в `job_id: int` → 422. Реальная остановка фоновой задачи — через проверку статуса задания в сканере (`CatalogScanner._is_cancelled`, читает одну колонку `status`). Статус `cancelled` окончательный: итоговый статус фоновых заданий пишет `services/jobs.py:finalize_job`, который его не затирает.

---

## Каталог (`/api`)

Префикс: `/api`, тег «Каталог». Файл: `src/server/routes/catalog.py`.

**Глобальное состояние:**
- `_catalog_update_status` (`catalog.py`) — `dict` статуса обновления каталога: `{in_progress, total, processed, updated, not_found, errors}`.
- `_catalog_update_lock` (`catalog.py`) — `threading.Lock` для безопасного доступа к `_catalog_update_status`.

**Фоновая функция:** `_fetch_and_update_categories_background()` (`catalog.py`) — полная замена каталога через `replace_catalog_from_api()`. Под блокировкой обновляет `_catalog_update_status`.

### Категории

| # | Метод | Путь | Обработчик | Назначение |
|---|-------|------|-----------|-----------|
| 16 | GET | `/api/categories` | `list_categories` | Список категорий. Query: `tracked`, `parent_id`. Приоритет: `tracked` > `parent_id` > корневые. → `list[dict]` |
| 17 | POST | `/api/categories/scan` | `scan_categories` | ⚠️ **Устарел (`deprecated`)** — используйте `/api/categories/update-catalog`; результат тот же. Синхронно сканировать подкатегории из API. Query: `store_code` (обязательный), `store_type` (необязательный). `store_type` нужен, если у кода магазина в БД несколько типов (иначе **400**). → `{status, scanned, added, updated, deleted}` |
| 18 | POST | `/api/categories/update-catalog` | `update_catalog_from_api` | **Основной** эндпоинт синхронизации подкатегорий всех корневых категорий (общая реализация `_sync_subcategories` с устаревшим `/scan`). Query: `store_code`, `store_type` (необязательный). `store_type` нужен, если у кода магазина в БД несколько типов (иначе **400**). → `{status, scanned, added, updated, deleted}` |
| 19 | GET | `/api/categories/tree` | `get_categories_tree` | Дерево категорий с `children`. → `list[dict]` |
| 20 | POST | `/api/categories/load-from-json` | `load_categories_from_json` | Загрузить из `categories.json`. → `{status, scanned, added, updated}` / 404 |
| — | — | `build-from-playwright`, `seed-from-playwright` | — | **Удалены (BREAKING)** — были алиасами `load-from-json`, UI их не вызывал. Используйте `POST /api/categories/load-from-json` |
| 21 | PUT | `/api/categories/{category_id}/track` | `toggle_category_tracking` | Включить/выключить отслеживание. Query: `track=True`. → `{id, name, is_tracked}` / 404 |
| 22 | POST | `/api/categories/update-tracking` | `update_categories_tracking` | Обновить отслеживание списка. Тело `{category_ids: [int]}`. Сначала сбрасывает ВСЕ, затем включает дочерние. → `{status, tracked_count, updated_ids}` |
| 23 | POST | `/api/categories/fetch-magnit-ids` | `fetch_magnit_category_ids_endpoint` | ⭐ Запустить полную замену каталога в отдельном потоке. → `{status: "started"}` или `{status: "in_progress", progress}` |
| 24 | GET | `/api/categories/fetch-magnit-ids/status` | `get_fetch_status` | Статус обновления каталога. → `{in_progress, total, processed, updated, not_found, error_count, errors}` |

### Товары

| # | Метод | Путь | Обработчик | Назначение |
|---|-------|------|-----------|-----------|
| 25 | GET | `/api/products` | `list_products` | Список товаров с фильтрами. Query: `store_code`, `category_id`, `category_ids` (CSV), `search`, `min_price`, `max_price`, `sort_by` (`name`/`price`/`last_seen`), `limit≤1000`, `offset`, `relax_stale` (окно видимости устаревших товаров до `STALE_DAYS_DELETE`), `include_out_of_stock` (включить отсутствующие). → `list[ProductListItem]` (27 полей, схема в `/docs`) |
| 26 | GET | `/api/products/stats` | `get_products_stats` | ⭐ Статистика. Query: `store_code`, `store_codes` (CSV; объединяется с `store_code`; пусто — по всем магазинам). → `ProductStats` `{total, in_stock, with_price_decrease, with_price_increase, last_update}` |
| 27 | GET | `/api/products/multi-prices` | `get_multi_store_prices` | ⭐ Цены из нескольких магазинов. Query: `product_ids` (CSV), `store_codes` (CSV). → `{product_id: {store_code: {price, previous_price, ...}}}` |
| 28 | GET | `/api/products/{product_id}` | `get_product` | Детали товара. Path: `product_id: int`. Query: `store_code`. → `dict` / 404 |
| 29 | GET | `/api/products/{product_id}/history` | `get_product_price_history` | История цен по дням. Query: `store_code`, `days=30` (1..365). → `list[dict]` |
| 30 | DELETE | `/api/products/clear` | `clear_all_products` | Удалить все товары. → `{status, message, deleted_count}` |
| 31 | DELETE | `/api/products/clear-by-categories` | `clear_products_by_categories` | Удалить по категориям. Query: `category_ids` (CSV). → `{status, message, deleted_count}` |
| 32 | DELETE | `/api/products/clear-by-store` | `clear_products_by_store` | Удалить по магазину. Query: `store_code`. → `{status, message, deleted_count}` |

### Сканирование

| # | Метод | Путь | Обработчик | Назначение |
|---|-------|------|-----------|-----------|
| 33 | POST | `/api/catalog/scan` | `scan_products` | Синхронно сканировать товары. Query: `store_code` (обязательный), `store_type` (необязательный), `category_ids` (CSV), `tracked_only=True`. `store_type` нужен, если у кода магазина в БД несколько типов (иначе **400**). → `{status, scanned, added, updated}` |
| 34 | POST | `/api/catalog/scan-all-stores` | `scan_all_stores` | ⭐ Фоновое сканирование всех активных магазинов (каждый — со своим `store_type`; один вызов сканера на магазин). Отслеживаемые категории — только подкатегории; **400**, если их нет. Query: `tracked_only=True`. → `{job_id, status, stores_count}` |
| 35 | POST | `/api/catalog/scan-prices` | `scan_prices_in_store` | Обновить цены в магазине. Query: `store_code`, `store_type` (необязательный). `store_type` нужен, если у кода магазина в БД несколько типов (иначе **400**). → `{status, scanned, added, updated}` |

### `GET /api/products/stats` — особенности
- Все счётчики считаются по **уникальным `product_id`** выбранных магазинов (один магазин, набор через `store_codes` или все магазины — одни и те же выражения): товар, продающийся в нескольких магазинах набора, учитывается один раз.
- `total` — все товары выборки; `in_stock` — в наличии (`in_stock=true` и `quantity > 0`) хотя бы в одном магазине набора; `with_price_increase` — с повышением цены (`price_change_percent < 0`) хотя бы в одном магазине.
- `with_price_decrease` — со снижением цены (`price_change_percent > 0`) в магазине, где товар при этом **в наличии**: снижения на отсутствующих товарах не считаются, как и в списке режима «Новая цена».
- Статистика не учитывает окно видимости устаревших товаров, категории и поиск, поэтому может отличаться от длины списка.
- Изменения значений относительно прежней версии: `with_price_decrease` одного магазина может уменьшиться; `total` без магазина — число уникальных товаров, а не строк. Набор полей ответа прежний.
- Пример: `GET /api/products/stats?store_codes=992104,210117` → `{"total": 6369, "in_stock": 5425, "with_price_decrease": 3, "with_price_increase": 1, "last_update": "2026-10-14T12:07:13.208683"}`.

### `POST /api/catalog/scan-all-stores` — особенности ⭐
- Использует `BackgroundTasks` (FastAPI).
- 400 если нет активных магазинов или отслеживаемых подкатегорий (набор — `catalog_scanner.py:get_tracked_category_magnit_ids`).
- Создаёт `ScanJob` (job_type=`scan_all_stores`, store_code=`"{N} stores"`).
- Вложенная `run_scan_all` создаёт отдельную `SessionLocal`. Для каждого магазина — **один** вызов `CatalogScanner.scan_products` со всеми категориями (со своим `store_type` магазина), поэтому очистка устаревших товаров, истории цен и пометка отсутствующих выполняются один раз на магазин. Детальный прогресс (`current_store_*`, `current_category_*`) пишет колбэк `on_category_start`; `progress` = позиция в (магазины × категории): `(индекс_магазина × категорий + номер_категории − 1) / (магазинов × категорий) × 100`.
- Отмена: проверка статуса между магазинами и в сканере перед каждым запросом страницы; итог пишет `finalize_job` (отмена не затирается).
- Если `background_tasks` не передан — выполняет синхронно.

### `GET /api/products` — особенности
- `response_model=list[ProductListItem]` (`schemas.py`): набор и имена полей зафиксированы схемой и не меняются без согласования с UI. Выборка — `services/product_query.py` (`build_product_query` → фильтры, окно видимости, наличие, поиск → сортировка/пагинация); роут только разбирает параметры. Поиск по `search` — один SQL-запрос `LIKE` по `Product.name_search` (`name.casefold()`; заполняется сканером и миграцией `add_product_name_search`), т.к. SQLite `LOWER()` не работает с кириллицей; `%`, `_` и `\` в запросе — обычные символы.
- Видимость: показываются товары с `last_seen` не старше `STALE_DAYS_VISIBLE` дней (при `relax_stale=true` — `STALE_DAYS_DELETE`); отсутствующие (`in_stock=false` или `quantity=0`) скрыты, `include_out_of_stock=true` их возвращает. Правила одни и те же для обычного списка и поиска.
- Поля ответа включают: `product_id, name, price, previous_price, price_change_percent, last_price_change, last_change_price, last_change_date, currency, unit, image_url, in_stock, category_id, store_code, category_name, category_parent_id, quantity, is_low_stock, pickup_only, rating, scores_count, comments_count, seo_code, is_weighted, unit_price, first_seen, last_seen`.

---

## Цены (`/api/prices`)

Префикс: `/api/prices`, тег «Цены». Файл: `src/server/routes/prices.py`.

| # | Метод | Путь | Обработчик | Назначение |
|---|-------|------|-----------|-----------|
| 36 | GET | `/api/prices/decreased` | `get_decreased_prices` | Товары со сниженными ценами. Query: `store_code` (обязательный), `min_discount_percent=10.0`, `limit≤500`. → `list[DecreasedPriceItem]` |
| 37 | POST | `/api/prices/update` | `update_prices` | ⭐ Фоновое обновление цен. Query: `store_code` (обязательный), `store_type` (необязательный), `category_ids` (CSV), `tracked_only=True`. `store_type` нужен, если у кода магазина в БД несколько типов (иначе **400**). → `{job_id, status}` |

### `POST /api/prices/update` — особенности ⭐
- Использует `BackgroundTasks` (FastAPI).
- 400 при неверном формате `category_ids`.
- Создаёт `ScanJob` (job_type=`prices`).
- Тип магазина определяется до создания задания (`catalog_scanner.py:resolve_store_type`): неоднозначный код без `store_type` → 400.
- Вложенная `run_update` (`prices.py`) создаёт **новую `SessionLocal()`** (не переиспользует закрытую FastAPI-сессию), ставит `status="running"` (если задание не отменено до старта), вызывает `CatalogScanner.scan_products`, итог пишет `finalize_job` (`completed`/`failed`; отменённое остаётся `cancelled`).

---

## Роуты `main.py` (7)

Файл: `src/server/main.py`. Определены напрямую на `app` (не через `include_router`).

### Веб-страницы (HTML, 5)

| Метод | Путь | Обработчик | Назначение |
|-------|------|-----------|-----------|
| GET | `/` | `page_stores` | Главная — управление магазинами (`stores.html`) |
| GET | `/catalog` | `page_catalog` | Страница категорий |
| GET | `/products` | `page_products` | Страница товаров |
| GET | `/jobs` | `page_jobs` | Страница фоновых заданий |
| GET | `/shopping-list` | `page_shopping_list` | Страница списка покупок |

### Утилитарные (2)

| Метод | Путь | Обработчик | Назначение |
|-------|------|-----------|-----------|
| GET | `/redirect-to-product` | `redirect_to_product` | Редирект на magnit.ru с установкой cookies `shopCode`, `x_shop_type` (max_age=3600). Query: `url`, `shop_code`, `x_shop_type`. **Только `https://magnit.ru/...`** (схема `https`, хост ровно `magnit.ru`, без userinfo и обратных слешей), иначе **400** `Допустимы только ссылки на magnit.ru` и cookies не ставятся |
| GET | `/open-product-in-browser` | `open_product_in_browser` | ⭐ Открыть товар в браузере через Playwright (фоновый `threading.Thread`). Query: `product_url`, `store_code`, `store_type`. `product_url` проверяется так же, как `url` в `/redirect-to-product` (иначе **400**, браузер не запускается). → `{status: "opening", message}`. Ошибки фонового потока пишутся в лог с traceback (`utils/threads.py:run_logged`) |

---

## Порядок регистрации эндпоинтов

FastAPI матчит маршруты **в порядке регистрации**. Статические пути должны идти ДО параметрических.

### `catalog.py` — `/api/products/*` (критично)
1. `GET /api/products` — статический
2. `GET /api/products/stats` — статический, **ДО** `{product_id}` ★
3. `GET /api/products/multi-prices` — статический, **ДО** `{product_id}` ★
4. `GET /api/products/{product_id}` — параметрический, последним
5. `GET /api/products/{product_id}/history` — двухсегментный, не конфликтует
6. `DELETE /api/products/clear`, `/clear-by-categories`, `/clear-by-store` — другой метод, не конфликтуют

> 🔴 Если бы `/stats` или `/multi-prices` были после `/{product_id}` — «stats»/«multi-prices» попали бы в `product_id: int` → 422.

### `jobs.py` — критично
- `GET /api/jobs/active` — **ДО** `GET /api/jobs/{job_id}`

### `stores.py` — критично
- `GET /api/stores/search` — **ДО** `GET /api/stores/{store_id}`. Иначе «search» попало бы в `store_id: str` (не упало бы, но искало бы магазин с id="search" → 404).
- `GET /api/stores/by-code/{store_code}` — двухсегментный, не конфликтует.

---

## Фоновые задачи и потоки

| Эндпоинт | Механизм | Назначение |
|----------|---------|-----------|
| `POST /api/catalog/scan-all-stores` | `BackgroundTasks` (FastAPI) | Сканирование всех магазинов |
| `POST /api/prices/update` | `BackgroundTasks` (FastAPI) | Обновление цен |
| `POST /api/categories/fetch-magnit-ids` | `threading.Thread` (daemon) через `run_logged` | Полная замена каталога |
| `GET /open-product-in-browser` | `threading.Thread` через `run_logged` | Запуск Playwright |

> 🔴 **Важно:** фоновые задачи создают **свою `SessionLocal()`** внутри — не используют сессию из FastAPI-dependency (она закрывается после HTTP-ответа). См. `docs/DEVELOPMENT.md`.
