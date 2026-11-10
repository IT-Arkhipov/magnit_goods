# Сервисный слой (`src/server/services/`)

Модули бизнес-логики, не относящиеся к HTTP-роутам: работа с внешним API Магнита, сканирование, bulk-операции с БД, выборка товаров и фоновые задания.

| Файл | Технология | БД | Внешние вызовы | Threading |
|------|-----------|----|-----------------|-----------|
| `magnit_api.py` | `requests` | нет | magnit.ru API (goods/search, stores-facade) | нет, sync |
| `catalog_scanner.py` | SQLAlchemy + bulk ops | `Product`, `PriceHistory`, `Category`, `ScanJob` | через `MagnitAPIClient` | нет, sync (внешний job) |
| `catalog_updater.py` | SQLAlchemy | `Category` (upsert по `magnit_id`, `is_tracked` сохраняется) | через `MagnitAPIClient` | нет, sync |
| `product_query.py` | SQLAlchemy | `Product` (чтение) | нет | нет, sync |
| `jobs.py` | SQLAlchemy | `ScanJob` | нет | нет, sync |
| `store_scan.py` | SQLAlchemy | `ScanJob`, `Store`, `Category` (+ через сканер) | через `CatalogScanner` | нет, sync (BackgroundTasks / планировщик) |

---

## 1. `magnit_api.py` — клиенты API Магнита

Единая точка взаимодействия с внешним API magnit.ru. Два независимых клиента.

### `MagnitAPIClient` (товары и сырые данные категорий) — `magnit_api.py`

**Конструктор:** `__init__(base_url="https://magnit.ru", store_code=None, store_type=None, timeout=15, rate_limit=0.5)`
- `store_code` — из аргумента или env `STORE_CODE`; `store_type` — из аргумента или `constants.py:get_configured_store_type()` (`STORE_TYPE`, по умолчанию `DEFAULT_STORE_TYPE` = «Магнит»).
- Создаёт `requests.Session` с заголовками Chrome 120 (UA, Referer, Origin, `X-Requested-With: XMLHttpRequest`).
- Хранит `_last_request_time` для rate limiting.

**Rate limiting — `_rate_limit_wait()`:**
- Гарантирует минимум `rate_limit` (**0.5 сек** по умолчанию) между запросами: если прошло меньше — `time.sleep(rate_limit - elapsed)`.
- Дополнительно **случайная пауза 0.1–0.5 сек** (`random.uniform(0.1, 0.5)`) — рандомизация защищает от детектирования ботов.
- Применяется ко **всем** запросам каталога: `search()` и `fetch_category_raw()`.

> 🔴 **КРИТИЧНО:** убирать rate limiting нельзя — API Магнита блокирует. См. `docs/DEVELOPMENT.md`.

**Payload — `_build_payload(store_code, store_type, category_ids, limit, offset)`:** единственное место, где строится запрос каталога: `sort` (по популярности, desc), `pagination` (limit/offset), `includeAdultGoods: True`, `storeCode`, `storeType`, `catalogType: "1"`, `categories` (список или `[]`). **Тип магазина** (API-код `MM`/`MM_MINI`/`ME`/…, русское название или число) приводится к числовому коду через `constants.py:resolve_store_type_code()`; неизвестное значение → предупреждение и тип по умолчанию.

**Главный метод `search()`:**
```python
def search(self, store_code=None, store_type=None, category_ids=None,
           limit=50, offset=0) -> dict
```
- Возвращает товары указанных категорий (`_parse_product`; товары без id или цены пропускаются).
- Ошибка — `MagnitAPIError(status_code, body)`: HTTP-код (`None` — сетевая ошибка) и начало ответа. `is_retryable` — сетевые ошибки, 429 и 5xx; прочие 4xx (например, категория недоступна для типа магазина) повторять бесполезно.
- Эндпоинт: **POST `https://magnit.ru/webgate/v2/goods/search`**.
- Возвращает `{items, total, hasMore, next_offset}`. `hasMore`/`next_offset` берётся из `pagination.nextOffset` API либо вычисляется `offset + len(items)`.

**`fetch_category_raw(category_id, store_code=None, store_type=None)`** — сырой ответ API для одной категории (поля `category` и `fastCategoriesExtended` — название и подкатегории), `limit=32, offset=0`. С ограничением частоты запросов; при ошибке возвращает `None`. Через него идут `CatalogScanner._fetch_category_data` и `CatalogUpdater.fetch_category_data`.

**Парсинг:**
- `_parse_product(item)` → словарь с полями товара. **Цена конвертируется из копеек в рубли (деление на 100)**, так же `unit_price` весовых. **Товар без цены (отсутствует или ≤ 0) пропускается** (`None` + предупреждение в логе) — иначе цена 0 дала бы ложное «снижение на 100%». Берёт `gallery[0].url` как `image_url`, `ratings` → `rating`/`scores_count`/`comments_count`, `orderProperties` → `min_order_qty`/`order_step_qty`, `weighted` → `is_weighted`/`unit_price`. При ошибке парсинга логирует traceback и возвращает `None`.

**Прочее:** `close()`.

### `StoresAPI` (поиск магазинов) — `magnit_api.py`

**Конструктор:** `__init__(base_url="https://magnit.ru", timeout=15, rate_limit=0.3)`
- `rate_limit=0.3` (короче, чем у `MagnitAPIClient`).
- Случайный `device_id = str(uuid.uuid4())` — в заголовке `X-Device-Id`.
- Заголовки веб-клиента: `X-Client-Name: magnit`, `X-New-Magnit: true`, `X-App-Version`, `X-Device-Platform: Web`, `X-Device-Tag: disabled`.

**`search_stores(query, store_types=None, limit=50, offset=0)`:**
- Эндпоинт: **POST `/webgate/v1/stores-facade/search/detail`**.
- Сначала GET `/shops` для получения cookies.
- **Один запрос со всеми типами** из `store_types` (по умолчанию `ALL_STORE_TYPES` — все API-коды) в `filters.storeTypeListV2`; `filters.query` = поисковый запрос, `sorting: SORT_BY_CITY ASC`.
- Возвращает `{stores, total, hasMore: False}` (пагинация на уровне API не используется). Разбор и дедупликация по паре (код, тип) — в `routes/stores.py:preview_stores`.

---

## 2. `catalog_scanner.py` — сканирование каталога

Класс `CatalogScanner`. Сканирование товаров через `MagnitAPIClient` с сохранением в БД. Реализует bulk-операции, отслеживание истории цен, очистку и интеграцию с `ScanJob`.

**Константы:** `PRICE_HISTORY_RETENTION_DAYS = 30`, `PROGRESS_MIN_INTERVAL = 2.0` (с).

**Функции модуля:**
- `get_tracked_category_magnit_ids(db)` — единое определение отслеживаемых категорий (подкатегории с `is_tracked`, порядок по `id`); используется всеми операциями сканирования.
- `resolve_store_type(db, store_code, store_type=None)` — тип магазина: явный → тип единственного магазина с таким кодом в БД → из конфигурации; если у кода несколько типов и тип не указан — `AmbiguousStoreError` (роуты отвечают 400).
- `resolve_store_type_filter(db, store_code, store_type=None)` — то же правило для **чтения** товаров и истории (роуты `routes/catalog.py`, `routes/prices.py`): явный тип → его код (`constants.py:parse_store_type_code`, нераспознанный — `ValueError` → 400); иначе код типа единственного магазина с этим кодом; несколько типов — `AmbiguousStoreError`; магазина с кодом в БД нет — `None` (без фильтра по типу). В отличие от `resolve_store_type`, не подставляет тип из конфигурации: чтение отдаёт то, что есть в БД.
- `delete_store_products(db, store_code, store_type)` — удалить товары и историю цен магазина (код + код типа) при удалении магазина (`routes/stores.py`); коммит — за вызывающим.
- `parse_store_ref(ref)` / `parse_store_refs(csv)` — элемент набора магазинов `код` или `код|тип` → `(код, тип или None)`; CSV → список элементов без пустых и повторов.

**Конструктор:** `__init__(db: Session, store_code=None, address=None, job_id=None, store_type=None)`
- Принимает SQLAlchemy `Session`, код магазина, адрес (для отображения в прогрессе), `job_id` и необязательный `store_type`.
- Тип магазина — через `resolve_store_type` (см. выше); `self.store_type_code = resolve_store_type_code(self.store_type)` — код типа в ключе записей. **Все** чтения и записи `Product`/`PriceHistory` сканера (`_save_products`, `_upsert_price_history`, `_mark_missing_products`, `cleanup_stale_products`) идут по паре (`store_code`, `store_type_code`): магазины одного кода и разных типов не трогают данные друг друга. `cleanup_price_history` — глобальная.
- Создаёт `MagnitAPIClient(store_code, store_type)` только если задан `store_code`.

**Прогресс задания (с троттлингом):**
- `_update_job_progress(message, force=False)` и `_update_job_progress_full(force=False, **kwargs)` накапливают значения и пишут их в `ScanJob` одним `UPDATE` + `commit` не чаще `PROGRESS_MIN_INTERVAL` (2 с). `force=True` — для обязательных сообщений (старт, категория недоступна, итог).
- `_flush_progress()` — записать накопленное.
- `_is_cancelled()` — читает одну колонку `ScanJob.status` (без загрузки сущности и `expire_all()`); предварительный `commit()` завершает транзакцию, чтобы в режиме WAL увидеть отмену из другой сессии.

### `scan_products(category_ids=None, tracked_only=False, on_category_start=None)`
→ `{scanned, added, updated, price_changes, deleted, history_deleted, marked_missing}`; при отмене — нулевая статистика с `"cancelled": True`.
- Если `category_ids` не задан: при `tracked_only=True` — `get_tracked_category_magnit_ids(db)`, иначе все категории с `magnit_id`. Набор читается в момент запуска и одинаков для `POST /api/catalog/scan` (`tracked_only=true`), `scan-prices`, `scan-all-stores`, `POST /api/prices/update` и заданий планировщика.
- **Сканирует по одной категории за раз.** Колбэк `on_category_start(номер, всего, magnit_id)` вызывается перед каждой категорией (прогресс `scan-all-stores`).
- **Проверка отмены** перед каждой категорией и каждым запросом страницы (`_is_cancelled()`).
- **Retry:** до 3 попыток с паузой 2 и 4 с — только для повторяемых ошибок (`MagnitAPIError.is_retryable`: сетевые, 429, 5xx). Прочие 4xx — категория сразу пропускается как недоступная для типа магазина (сообщение в прогрессе задания); пропущенная категория не участвует в пометке отсутствующих.
- **Пагинация:** цикл `while has_more`, использует `next_offset` из API либо вычисляет `offset + len(products)`. Прерывается при пустом `products`.
- Обновляет `current_category_items_total` и `current_category_items_loaded` (число загруженных в **текущей** категории) в `ScanJob`.
- После сканирования обновляет `Category.last_scanned = datetime.utcnow()`.
- **Один раз за вызов, в конце:** `_mark_missing_products()` (товары полностью просканированных категорий, которых не вернул API, → `in_stock=False`, `quantity=0`, сброс полей скидки), `cleanup_stale_products(days_threshold=STALE_DAYS_DELETE)` и `cleanup_price_history()`. Поэтому сканирование магазина нужно выполнять **одним вызовом** со всеми категориями (так делает `scan-all-stores`).

### `_save_products(products, category_magnit_id)` — КЛЮЧЕВОЙ метод
→ `(added_count, updated_count, price_change_count)`

**Оптимизация:** один SELECT для всех `product_ids` (вместо N+1), bulk INSERT для новых, bulk UPDATE для существующих, один COMMIT.

**Логика цены:**
- `price_history` хранит **одну запись на день** для каждого `(product_id, store_code, store_type_code)`; цена предыдущего дня берётся из истории того же магазина (код и тип).
- `previous_price` / `price_change_percent` берутся из **последней записи предыдущего дня** (`scan_date < today`); если истории нет — fallback на сохранённую цену `existing.price`.
- `last_change_price` / `last_change_date` / `last_price_change` обновляются только при **реальном изменении** цены (`abs(existing.price - current) > 0.01`): `last_change_price` — цена непосредственно до изменения, `last_change_date` — момент скана с изменением. Повторные сканы с той же ценой эти поля не трогают.
- `price_change_percent = round((prev - current) / prev * 100, 1)`. Положительное = снижение, отрицательное = повышение.
- `name_search = name.casefold()` записывается при вставке и обновлении (для поиска по кириллице).

**Шаги:**
1. Находит категорию в БД по `magnit_id`.
2. **Одним запросом** получает все существующие товары по `(product_id IN (...), store_code, store_type_code)`.
3. **Одним запросом** получает историю цен предыдущих дней.
4. Разделяет на `to_insert` и `to_update`, формируя словари для `bulk_insert_mappings` / `bulk_update_mappings`.
5. `self.db.bulk_insert_mappings(Product, to_insert)`.
6. `self.db.bulk_update_mappings(Product, to_update)`.
7. `self._upsert_price_history(products, today)`.
8. Один `commit()`.

### `_upsert_price_history(products_data, scan_date)`
Для каждого товара проверяет существование записи за `scan_date` по `(product_id, store_code, store_type_code)`. Если есть — bulk UPDATE (`price`, `quantity`, `in_stock`); если нет — bulk INSERT. Upsert-семантика «одна запись на день».

### `cleanup_stale_products(days_threshold=STALE_DAYS_DELETE)`
Удаляет товары с `last_seen < now - days_threshold` для текущего магазина (`store_code` + `store_type_code`). **Порог по умолчанию — `STALE_DAYS_DELETE` = 6 дней** (`constants.py`: 1 день товар виден после `last_seen`, затем 5 дней скрыт, затем удаляется).

### `cleanup_price_history(days=30)`
Удаляет записи `PriceHistory` старше 30 дней (`PRICE_HISTORY_RETENTION_DAYS`).

### `close()`
Закрывает `MagnitAPIClient`.

---

## 3. `catalog_updater.py` — обновление дерева категорий

Класс `CatalogUpdater` (`catalog_updater.py`). Обновление дерева категорий из API. Единственный режим — **полная замена** (upsert по `magnit_id`) с сохранением `id` и `is_tracked` — единственный способ обновить категории.

**Конструктор:** `__init__(store_code=None, store_type=None)`
- Код магазина — из аргумента или `STORE_CODE`; **захардкоженного магазина по умолчанию нет** — без магазина `ValueError("Не выбран магазин ...")`. Тип — из аргумента, иначе `STORE_TYPE`, иначе `DEFAULT_STORE_TYPE`.
- Запросы идут через `MagnitAPIClient.fetch_category_raw()` (`self.client`): единый формат `storeType` (числовой код через `resolve_store_type_code`), общие заголовки и **общее ограничение частоты запросов** (0.5 с + случайная пауза 0.1–0.5 с).
- `categories_file` = `CATEGORIES_FILE` = `src/data/categories.json`; `close()` закрывает HTTP-клиент.

**Методы:**
- `fetch_category_data(category_id)` — делегирует `MagnitAPIClient.fetch_category_raw` (POST с `categories: [category_id]`, `limit: 32`, `offset: 0`).
- `load_root_categories_from_file()` — читает `categories.json` через модульную функцию `load_root_categories(path)`.

### `replace_all_categories()` (`catalog_updater.py`) — полная замена
1. Загружает корневые категории из файла.
2. Собирает ВСЕ категории из API (корневые + подкатегории) в `[(magnit_id, title, parent_magnit_id)]`.
3. Если есть ошибки API — **возвращает ошибку и НЕ меняет БД** (защита от потери данных).
4. **Upsert по `magnit_id` в одной транзакции.** Существующие категории **сохраняют внутренний `id` и `is_tracked`** — поэтому `Product.category_id` остаётся валидным. Сначала обрабатываются корневые (`parent_magnit_id is None`), затем подкатегории (`parent_id` берётся из `magnit_to_db_id`). Для существующей категории обновляются только название и родитель; новые создаются с `is_tracked=False`. Дубли `magnit_id` в ответе API пропускаются с предупреждением.
5. **Удаляются только категории, которых нет в ответе API.** Дубли `magnit_id` в БД (след старого кода) сливаются в запись с минимальным `id`: их товары переносятся на неё. У товаров остальных удаляемых категорий `category_id` обнуляется.
6. Возвращает `{status, total, added, updated, deleted, errors}` (`updated` — переименованные или перенесённые категории). При критической ошибке — `rollback()` + traceback.

**Модульные функции-обёртки:**
- `replace_catalog_from_api(store_code, store_type)` — полная замена (закрывает HTTP-клиент по окончании).

**Статус и запуск** (в памяти процесса — не `ScanJob`):
- `try_begin_catalog_update()` — проверить и взять флаг `in_progress` под одной блокировкой; `False`, если замена уже идёт.
- `run_catalog_update()` — замена с записью статуса; магазин-источник — `STORE_CODE` (тип — `STORE_TYPE` или тип магазина), иначе первый активный магазин (`_catalog_source_store`); флаг снимается в `finally`.
- `get_catalog_update_status()` — снимок для `GET /api/categories/fetch-magnit-ids/status`; `end_catalog_update()` — снять флаг, если поток не запустился.

> Вызывают `POST /api/categories/fetch-magnit-ids` (в потоке через `run_logged`) и еженедельное задание планировщика `update_catalog`. Это единственный способ обновить категории.

---

## 4. `store_scan.py` — сканирование всех магазинов

Одна реализация для `POST /api/catalog/scan-all-stores` и ежедневного задания планировщика `scan_all_stores`.

- `create_scan_all_stores_job(db)` → `job_id`: `ScanJob(job_type="scan_all_stores", status="pending")`; `NothingToScanError`, если нет активных магазинов или отслеживаемых категорий.
- `run_scan_all_stores(job_id)` — своя `SessionLocal()`; магазины и отслеживаемые категории читаются в момент запуска. Для каждого активного магазина — **один** `CatalogScanner.scan_products` со своим типом; прогресс (магазин × категория) через `on_category_start`; ошибка магазина пишется в `progress_message` и не прерывает остальные. Отмена проверяется между магазинами и в сканере; итог — `finalize_job` (отмена не затирается).

## 4a. `product_query.py` — выборка товаров для API

Единый слой выборки товаров; роуты `GET /api/products` и `GET /api/products/stats` только разбирают параметры и вызывают его.

- `ProductFilters` — параметры: `store_code`, `store_type_code` (код типа из `resolve_store_type_filter`; `None` — все типы кода), `category_id`, `category_ids`, `min_price`, `max_price`, `search`, `relax_stale`, `include_out_of_stock`. `parse_category_ids("1,2,x")` → `[1, 2]`.
- `build_product_query(db, filters)` — все фильтры в одном месте: магазин, категории, цена; окно видимости устаревших (`STALE_DAYS_VISIBLE`, при `relax_stale` — `STALE_DAYS_DELETE`); наличие (`in_stock` и `quantity > 0`, если не `include_out_of_stock`); поиск `Product.name_search LIKE '%…%' ESCAPE '\'` по `casefold()`-терму. Поиск и обычный список проходят один путь.
- `list_products(db, filters, sort_by, limit, offset)` — сортировка (`name` / `price` / `last_seen`) и пагинация.
- `product_to_list_item(p)` — элемент ответа (контракт — схема `ProductListItem`); `get_products_stats(db, stores)` — агрегаты (`ProductStats`) по набору магазинов: `stores` — пары `(store_code, store_type_code или None)`, условие строит `store_condition(stores)`.

---

---

## Сводка ключевых механизмов

### Rate limiting
| Клиент | Где | Пауза | Случайная добавка |
|--------|-----|-------|-------------------|
| `MagnitAPIClient` | `magnit_api.py:MagnitAPIClient._rate_limit_wait` — все запросы каталога, включая `CatalogUpdater` и подкатегории | 0.5 сек | `random.uniform(0.1, 0.5)` |
| `StoresAPI` | `magnit_api.py:StoresAPI._rate_limit_wait` | 0.3 сек | `random.uniform(0.1, 0.5)` |

### Bulk-операции (только в `CatalogScanner._save_products`)
- `bulk_insert_mappings(Product, to_insert)` — массовая вставка новых товаров.
- `bulk_update_mappings(Product, to_update)` — массовое обновление существующих.
- `bulk_insert_mappings` / `bulk_update_mappings` для `PriceHistory` в `_upsert_price_history`.
- Один SELECT для всех существующих товаров по `(product_id IN (...), store_code, store_type_code)`.
- Один `commit()` в конце.

### Retry
Только в `CatalogScanner.scan_products()`: до 3 попыток с паузой 2 и 4 сек, только для `MagnitAPIError.is_retryable` (сетевые ошибки, 429, 5xx); прочие 4xx — категория пропускается без повторов.

### Проверка отмены и статусы заданий
`CatalogScanner._is_cancelled()` — чтение колонки `ScanJob.status` перед каждой категорией и каждым запросом страницы. Задание помечается `cancelled` через `POST /api/jobs/{id}/cancel` (`routes/jobs.py`). Итоговый статус фоновых заданий пишет `services/jobs.py:finalize_job`: он перечитывает задание и **не затирает `cancelled`**. `mark_unfinished_jobs_failed()` при старте сервера переводит оставшиеся `pending`/`running` в `failed`.

