# Сервисный слой (`src/server/services/`)

Модули бизнес-логики, не относящиеся к HTTP-роутам. Здесь — работа с внешним API Магнита, сканирование, bulk-операции с БД, браузерная автоматизация (Playwright) и формирование уведомлений.

| Файл | Технология | БД | Внешние вызовы | Threading |
|------|-----------|----|-----------------|-----------|
| `magnit_api.py` | `requests` | нет | magnit.ru API (goods/search, stores-facade) | нет, sync |
| `catalog_scanner.py` | SQLAlchemy + bulk ops | `Product`, `PriceHistory`, `Category`, `ScanJob` | через `MagnitAPIClient` | нет, sync (внешний job) |
| `catalog_updater.py` | SQLAlchemy | `Category` (upsert по `magnit_id`, `is_tracked` сохраняется) | через `MagnitAPIClient` | нет, sync |
| `product_query.py` | SQLAlchemy | `Product` (чтение) | нет | нет, sync |
| `jobs.py` | SQLAlchemy | `ScanJob` | нет | нет, sync |
| `category_verifier.py` | Playwright | нет (JSON-файл) | magnit.ru (браузер) | нет, sync |
| `load_catalog_from_json.py` | SQLAlchemy | `Category` | нет (чтение JSON) | нет, sync |
| `notifications.py` | SQLAlchemy | `Product`, `Category` | нет (только формирование данных) | нет, sync; **не подключён** |
| `product_opener.py` | Playwright | нет | magnit.ru (видимый браузер) | нет, sync (вызывается из потока) |
| `store_selector.py` | Playwright | нет | magnit.ru (браузер) | нет, sync; **не подключён** |

---

## 1. `magnit_api.py` — клиенты API Магнита

Единая точка взаимодействия с внешним API magnit.ru. Два независимых клиента.

### `MagnitAPIClient` (товары и категории) — `magnit_api.py`

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
- Универсальный: если `category_ids` не задан → возвращает категории; если задан → товары.
- Эндпоинт: **POST `https://magnit.ru/webgate/v2/goods/search`**.
- Возвращает `{items, total, hasMore, next_offset}`. `hasMore`/`next_offset` берётся из `pagination.nextOffset` API либо вычисляется `offset + len(items)`.

**`fetch_category_raw(category_id, store_code=None, store_type=None)`** — сырой ответ API для одной категории (поля `category` и `fastCategoriesExtended` — название и подкатегории), `limit=32, offset=0`. С ограничением частоты запросов; при ошибке возвращает `None`. Через него идут `CatalogScanner._fetch_category_data` и `CatalogUpdater.fetch_category_data`.

**Парсинг:**
- `_parse_category(item)` → `{magnit_id, name, url, product_count, parent_id}`.
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

Класс `CatalogScanner`. Сканирование каталога товаров и категорий через `MagnitAPIClient` с сохранением в БД. Реализует bulk-операции, отслеживание истории цен, очистку и интеграцию с `ScanJob`.

**Константы:** `PRICE_HISTORY_RETENTION_DAYS = 30`, `PROGRESS_MIN_INTERVAL = 2.0` (с).

**Функции модуля:**
- `get_tracked_category_magnit_ids(db)` — единое определение отслеживаемых категорий (подкатегории с `is_tracked`, порядок по `id`); используется всеми операциями сканирования.
- `resolve_store_type(db, store_code, store_type=None)` — тип магазина: явный → тип единственного магазина с таким кодом в БД → из конфигурации; если у кода несколько типов и тип не указан — `AmbiguousStoreError` (роуты отвечают 400).

**Конструктор:** `__init__(db: Session, store_code=None, address=None, job_id=None, store_type=None)`
- Принимает SQLAlchemy `Session`, код магазина, адрес (для отображения в прогрессе), `job_id` и необязательный `store_type`.
- Тип магазина — через `resolve_store_type` (см. выше).
- Создаёт `MagnitAPIClient(store_code, store_type)` только если задан `store_code`.

**Прогресс задания (с троттлингом):**
- `_update_job_progress(message, force=False)` и `_update_job_progress_full(force=False, **kwargs)` накапливают значения и пишут их в `ScanJob` одним `UPDATE` + `commit` не чаще `PROGRESS_MIN_INTERVAL` (2 с). `force=True` — для обязательных сообщений (старт, категория недоступна, итог).
- `_flush_progress()` — записать накопленное.
- `_is_cancelled()` — читает одну колонку `ScanJob.status` (без загрузки сущности и `expire_all()`); предварительный `commit()` завершает транзакцию, чтобы в режиме WAL увидеть отмену из другой сессии.

### `scan_categories()`
→ `{scanned, added, updated, deleted}`
- Получает **все корневые категории с `magnit_id`** (`parent_id IS NULL AND magnit_id IS NOT NULL`), независимо от `is_tracked`: в UI отмечаются только подкатегории, корни никогда не «отслеживаются». `is_tracked` существующих подкатегорий не меняется.
- Для каждой вызывает `_fetch_category_data(magnit_id)` → `MagnitAPIClient.fetch_category_raw` (с rate limiting).
- Обновляет название корневой категории из `category.title`.
- **Полная синхронизация подкатегорий:** удаляет из БД те, которых нет в API; обновляет существующие (по `magnit_id`); добавляет новые с `parent_id=root_cat.id`.
- Коммитит после каждой корневой категории.

### `scan_products(category_ids=None, tracked_only=False, on_category_start=None)`
→ `{scanned, added, updated, price_changes, deleted, history_deleted, marked_missing}`; при отмене — нулевая статистика с `"cancelled": True`.
- Если `category_ids` не задан: при `tracked_only=True` — `get_tracked_category_magnit_ids(db)`, иначе все категории с `magnit_id`. Набор читается в момент запуска и одинаков для `POST /api/catalog/scan` (`tracked_only=true`), `scan-prices`, `scan-all-stores`, `POST /api/prices/update` и заданий планировщика.
- **Сканирует по одной категории за раз.** Колбэк `on_category_start(номер, всего, magnit_id)` вызывается перед каждой категорией (прогресс `scan-all-stores`).
- **Проверка отмены** перед каждой категорией и каждым запросом страницы (`_is_cancelled()`).
- **Retry:** до 3 попыток, между ними пауза 2 и 4 секунды (`2**retry_count`). Особая обработка `invalid_service_pair`/`service not found` — категория считается недоступной для типа магазина и пропускается.
- **Пагинация:** цикл `while has_more`, использует `next_offset` из API либо вычисляет `offset + len(products)`. Прерывается при пустом `products`.
- Обновляет `current_category_items_total` и `current_category_items_loaded` (число загруженных в **текущей** категории) в `ScanJob`.
- После сканирования обновляет `Category.last_scanned = datetime.utcnow()`.
- **Один раз за вызов, в конце:** `_mark_missing_products()` (товары полностью просканированных категорий, которых не вернул API, → `in_stock=False`, `quantity=0`, сброс полей скидки), `cleanup_stale_products(days_threshold=STALE_DAYS_DELETE)` и `cleanup_price_history()`. Поэтому сканирование магазина нужно выполнять **одним вызовом** со всеми категориями (так делает `scan-all-stores`).

### `_save_products(products, category_magnit_id)` — КЛЮЧЕВОЙ метод
→ `(added_count, updated_count, price_change_count)`

**Оптимизация:** один SELECT для всех `product_ids` (вместо N+1), bulk INSERT для новых, bulk UPDATE для существующих, один COMMIT.

**Логика цены:**
- `price_history` хранит **одну запись на день** для каждого `(product_id, store_code)`.
- `previous_price` / `price_change_percent` берутся из **последней записи предыдущего дня** (`scan_date < today`); если истории нет — fallback на сохранённую цену `existing.price`.
- `last_change_price` / `last_change_date` / `last_price_change` обновляются только при **реальном изменении** цены (`abs(existing.price - current) > 0.01`): `last_change_price` — цена непосредственно до изменения, `last_change_date` — момент скана с изменением. Повторные сканы с той же ценой эти поля не трогают.
- `price_change_percent = round((prev - current) / prev * 100, 1)`. Положительное = снижение, отрицательное = повышение.
- `name_search = name.casefold()` записывается при вставке и обновлении (для поиска по кириллице).

**Шаги:**
1. Находит категорию в БД по `magnit_id`.
2. **Одним запросом** получает все существующие товары по `(product_id IN (...), store_code)`.
3. **Одним запросом** получает историю цен предыдущих дней.
4. Разделяет на `to_insert` и `to_update`, формируя словари для `bulk_insert_mappings` / `bulk_update_mappings`.
5. `self.db.bulk_insert_mappings(Product, to_insert)`.
6. `self.db.bulk_update_mappings(Product, to_update)`.
7. `self._upsert_price_history(products, today)`.
8. Один `commit()`.

### `_upsert_price_history(products_data, scan_date)`
Для каждого товара проверяет существование записи за `scan_date` по `(product_id, store_code)`. Если есть — bulk UPDATE (`price`, `quantity`, `in_stock`); если нет — bulk INSERT. Upsert-семантика «одна запись на день».

### `cleanup_stale_products(days_threshold=STALE_DAYS_DELETE)`
Удаляет товары с `last_seen < now - days_threshold` для текущего `store_code`. **Порог по умолчанию — `STALE_DAYS_DELETE` = 6 дней** (`constants.py`: 1 день товар виден после `last_seen`, затем 5 дней скрыт, затем удаляется).

### `cleanup_price_history(days=30)`
Удаляет записи `PriceHistory` старше 30 дней (`PRICE_HISTORY_RETENTION_DAYS`).

### `close()`
Закрывает `MagnitAPIClient`.

---

## 3. `catalog_updater.py` — обновление дерева категорий

Класс `CatalogUpdater` (`catalog_updater.py`). Обновление дерева категорий из API. Единственный режим — **полная замена** (upsert по `magnit_id`) с сохранением `id` и `is_tracked`; синхронизация подкатегорий живёт только в `CatalogScanner.scan_categories`.

**Конструктор:** `__init__(store_code=None, store_type=None)`
- Код магазина — из аргумента или `STORE_CODE`; **захардкоженного магазина по умолчанию нет** — без магазина `ValueError("Не выбран магазин ...")`. Тип — из аргумента, иначе `STORE_TYPE`, иначе `DEFAULT_STORE_TYPE`.
- Запросы идут через `MagnitAPIClient.fetch_category_raw()` (`self.client`): единый формат `storeType` (числовой код через `resolve_store_type_code`), общие заголовки и **общее ограничение частоты запросов** (0.5 с + случайная пауза 0.1–0.5 с).
- `categories_file` = `CATEGORIES_FILE` = `src/data/categories.json`; `close()` закрывает HTTP-клиент.

**Методы:**
- `fetch_category_data(category_id)` — делегирует `MagnitAPIClient.fetch_category_raw` (POST с `categories: [category_id]`, `limit: 32`, `offset: 0`).
- `load_root_categories_from_file()` — читает `categories.json` через модульную функцию `load_root_categories(path)`, которой пользуется и `load_catalog_from_json` (без магазина).

### `replace_all_categories()` (`catalog_updater.py`) — полная замена
1. Загружает корневые категории из файла.
2. Собирает ВСЕ категории из API (корневые + подкатегории) в `[(magnit_id, title, parent_magnit_id)]`.
3. Если есть ошибки API — **возвращает ошибку и НЕ меняет БД** (защита от потери данных).
4. **Upsert по `magnit_id` в одной транзакции.** Существующие категории **сохраняют внутренний `id` и `is_tracked`** — поэтому `Product.category_id` остаётся валидным. Сначала обрабатываются корневые (`parent_magnit_id is None`), затем подкатегории (`parent_id` берётся из `magnit_to_db_id`). Для существующей категории обновляются только название и родитель; новые создаются с `is_tracked=False`. Дубли `magnit_id` в ответе API пропускаются с предупреждением.
5. **Удаляются только категории, которых нет в ответе API.** Дубли `magnit_id` в БД (след старого кода) сливаются в запись с минимальным `id`: их товары переносятся на неё. У товаров остальных удаляемых категорий `category_id` обнуляется.
6. Возвращает `{status, total, added, updated, deleted, errors}` (`updated` — переименованные или перенесённые категории). При критической ошибке — `rollback()` + traceback.

**Модульные функции-обёртки:**
- `replace_catalog_from_api(store_code, store_type)` — полная замена (закрывает HTTP-клиент по окончании).

> Используется фоновой задачей `_fetch_and_update_categories_background()` в `routes/catalog.py` (запускается через `POST /api/categories/fetch-magnit-ids`).

---

## 4. `category_verifier.py` — верификация категорий через Playwright

Класс `CategoryVerifier` (`category_verifier.py`). Проверка и актуализация названий корневых категорий в `categories.json` через **Playwright**. Браузер открывает magnit.ru, кликает по каталогу, перехватывает API-ответы и сравнивает названия.

**Константы:**
- `CATEGORIES_FILE` = `src/data/categories.json` (`category_verifier.py`).
- `MAGNIT_URL` = `https://magnit.ru/` (`category_verifier.py`).
- `API_ENDPOINT` = glob `**/webgate/v2/goods/search` (`category_verifier.py`).

**Конструктор:** `__init__(headless=True)` (`category_verifier.py`).

**Методы:**
- `load_categories()` / `save_categories(data)` (`category_verifier.py` / ).
- **`handle_response(response)`** (`category_verifier.py`) — callback на `page.on("response")`. Если URL содержит `API_ENDPOINT`, метод POST и в `post_data_json` есть `categories`, берёт `category_id = post_data["categories"][0]`, парсит тело и сохраняет `{api_id, api_title, subcategories: [{id, title}]}`. Ошибки глушатся `except: pass`.
- **`verify_and_update()`** (`category_verifier.py`) — основной метод:
  - `sync_playwright()`, Chromium, контекст с viewport 1920×1080, locale `ru-RU`.
  - `page.goto(MAGNIT_URL, domcontentloaded, timeout=60000)`, `sleep(3)`.
  - Кликает «Каталог», для каждой корневой категории: ищет `text={cat_title}`, кликает → «Все товары этой категории» → сравнивает `api_title` с `cat_title`. При расхождении обновляет JSON. Кликает «Назад».
  - Возвращает `{total, checked, updated}`.

> Дублируется standalone-скриптом `src/scripts/verify_categories.py` (аналогичная логика, но с интерактивным `input()` для подтверждения записи).

---

## 5. `load_catalog_from_json.py` — загрузка корневых категорий из JSON

Функция `load_catalog_from_json(db: Session = None) -> dict`. Загружает **корневые категории** из `src/data/categories.json` — плоского массива `[{"id": <magnit_id>, "title": <название>}]` — в таблицу `Category`. Подкатегорий в файле нет: их добавляет синхронизация с API (`CatalogScanner.scan_categories`). Используется `POST /api/categories/load-from-json`.

**Логика:**
1. Если `db=None` — создаёт `SessionLocal()` и закрывает его по окончании.
2. Файла нет — `FileNotFoundError` (эндпоинт отвечает 404 `Файл categories.json не найден`).
3. Читает массив через `load_root_categories()` (`catalog_updater.py`).
4. Для каждого элемента ищет категорию по `magnit_id`: есть — при изменении названия обновляет `name` (`is_tracked`, родитель и подкатегории не трогает); нет — создаёт корневую (`parent_id=None`, `is_tracked=False`, `product_count=0`).
5. Один `db.commit()` в конце; при ошибке — `db.rollback()` + `raise`.

**Возвращает:** `{scanned, added, updated}` (`updated` — категории с изменённым названием; повторная загрузка даёт `added: 0`).

---

## 5a. `product_query.py` — выборка товаров для API

Единый слой выборки товаров; роуты `GET /api/products` и `GET /api/products/stats` только разбирают параметры и вызывают его.

- `ProductFilters` — параметры: `store_code`, `category_id`, `category_ids`, `min_price`, `max_price`, `search`, `relax_stale`, `include_out_of_stock`. `parse_category_ids("1,2,x")` → `[1, 2]`.
- `build_product_query(db, filters)` — все фильтры в одном месте: магазин, категории, цена; окно видимости устаревших (`STALE_DAYS_VISIBLE`, при `relax_stale` — `STALE_DAYS_DELETE`); наличие (`in_stock` и `quantity > 0`, если не `include_out_of_stock`); поиск `Product.name_search LIKE '%…%' ESCAPE '\'` по `casefold()`-терму. Поиск и обычный список проходят один путь.
- `list_products(db, filters, sort_by, limit, offset)` — сортировка (`name` / `price` / `last_seen`) и пагинация.
- `product_to_list_item(p)` — элемент ответа (контракт — схема `ProductListItem`); `get_products_stats(db, store_code)` — агрегаты (`ProductStats`).

---

## 6. `notifications.py` — формирование уведомлений

Класс `NotificationService`. **Генерация отчётов и текстов уведомлений. Не отправляет во внешние системы** (нет Telegram/email/webhook) — только формирует данные и текст. Отправку выполняет вызывающий код.

> ⚠️ **Модуль не подключён:** ни роуты, ни планировщик его не вызывают (`daily_report` в `scheduler.py:register_jobs` закомментирован). Не удалён — за ним стоит возможный сценарий ежедневных отчётов; решение за владельцем проекта (`docs/DEVELOPMENT.md`).

**Конструктор:** `__init__(db: Session, store_code: Optional[str] = None)` (`notifications.py`).

**Методы:**
- **`generate_daily_report()`** (`notifications.py`) — отчёт за вчерашний день:
  - `decreased` — товары с `price_change_percent > 0` (снижение) и `last_price_change` вчера.
  - `increased` — `price_change_percent < 0` (повышение).
  - `new_products_count` — `first_seen` вчера.
  - `top_deals` — топ-5 с `price_change_percent >= 10.0`, отсортированных по убыванию (`notifications.py`).
  - Возвращает `{date, summary: {total_changes, price_decreases, price_increases, new_products}, top_deals: [...]}`.
- **`check_new_products_in_tracked_categories(days=1)`** (`notifications.py`) — товары с `first_seen >= now - days` в отслеживаемых категориях.
- **`check_out_of_stock_to_available(days=1)`** (`notifications.py`) — упрощённая логика: возвращает товары в наличии с `last_seen >= cutoff`, лимит 20.
- **`format_alert_message(alert_type, data)`** (`notifications.py`) — текст с эмодзи:
  - `"deal"` → «🔥 Скидка! {name}\nБыло: ...₽\nСтало: ...₽\nЭкономия: ...%»
  - `"new_product"` → «🆕 Новый товар: {name} — {price}₽»
  - `"in_stock"` → «✅ В наличии: {name} — {price}₽»

---

## 7. `product_opener.py` — открытие товара в браузере

Функция `open_product_with_store(product_url, store_code, store_type)` (`product_opener.py`). Открывает страницу товара на magnit.ru в **видимом Chromium через Playwright** с попыткой автоматического выбора магазина.

**Логика (`product_opener.py`):**
- `sync_playwright()`, `p.chromium.launch(headless=False)` — **видимое окно**.
- `page.goto("https://magnit.ru/", domcontentloaded)`, `sleep(2)`.
- Пытается выбрать магазин: ищет кнопку «Выбрать магазин», заполняет поле поиска кодом магазина, кликает первый результат «Выбрать». При ошибке — логирует и продолжает («Пользователь может выбрать магазин вручную»).
- `page.goto(product_url, domcontentloaded)`.
- **Браузер НЕ закрывается автоматически** — остаётся открытым для пользователя (`product_opener.py`).

> Запускается из `main.py` (`GET /open-product-in-browser`) через `threading.Thread` и `utils/threads.py:run_logged` (ошибки потока пишутся в лог с traceback), чтобы не блокировать HTTP-ответ. Адрес товара предварительно проверяется: только `https://magnit.ru/...`.

---

## 8. `store_selector.py` — Playwright-сканер магазинов

Класс `MagnitStoreSelector`. Автоматизация выбора и сканирования магазинов на magnit.ru через Playwright.

> ⚠️ **Модуль не подключён:** поиск магазинов в приложении идёт через `StoresAPI` (`POST /api/stores/preview`); этот Playwright-сканер роутами не используется. Не удалён — альтернативный способ получить список магазинов; решение за владельцем проекта.

> ⚠️ **Важно:** этот модуль **НЕ обновляет `.env`** — это Playwright-браузерная автоматизация. Фактическое обновление `.env` выполняется в `routes/stores.py` (через `python-dotenv`).

**Конструктор:** `__init__(headless=True)` (`store_selector.py`). Хранит `playwright`, `browser`, `page`.

**Управление жизненным циклом:**
- `start()` (`store_selector.py`) — `sync_playwright().start()`, `chromium.launch(headless)`, контекст с UA Chrome 120, `locale="ru-RU"`.
- `close()` (`store_selector.py`) — `browser.close()` + `playwright.stop()`.

**Навигация (перебор CSS-селекторов с try/except — устойчивость к изменениям вёрстки):**
- `open_store_selector()` (`store_selector.py`)
- `select_mode_in_store()` (`store_selector.py`)
- `click_select_store_button()` (`store_selector.py`)
- `enter_address(address)` (`store_selector.py`)
- `select_store_type(store_type)` (`store_selector.py`) — маппинг русских названий (`Экстра`→`["Экстра", "Extra"]`, `Мини`→`["Мини", "Mini"]` и др.)
- `get_all_stores_from_list()` (`store_selector.py`) — парсит элементы списка магазинов.
- `_parse_store_text(text)` (`store_selector.py`) — извлекает `{name, full_address, city, address}`. **Город** — регулярками (`, г Город`, `, г. Город` и обратные формы), эвристика при отсутствии.
- `extract_store_code_from_api()` (`store_selector.py`) — **заглушка** (`return None`).

### `run_full_scan(city, street=None, store_types=None, progress_callback=None)` (`store_selector.py`)
1. `open_store_selector()`.
2. Формирует `address = city[, street]`, `enter_address`.
3. Для каждого типа из `store_types` (по умолчанию `["Экстра", "Мини", "Семейный"]`): `select_store_type` → `get_all_stores_from_list` → помечает `store["store_type"]` → добавляет в `all_stores` (без дублей) → сбрасывает фильтр `select_store_type("Все")`.
4. `progress_callback(progress, message)` с процентами 5/15/20-80/90/100.
5. При ошибке — `progress_callback(-1, ...)` и `raise`.

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
- Один SELECT для всех существующих товаров по `(product_id IN (...), store_code)`.
- Один `commit()` в конце.

### Retry
Только в `CatalogScanner.scan_products()`: до 3 попыток, между ними пауза 2 и 4 сек (`2**retry_count`). Особая обработка `invalid_service_pair`/`service not found` — категория пропускается.

### Проверка отмены и статусы заданий
`CatalogScanner._is_cancelled()` — чтение колонки `ScanJob.status` перед каждой категорией и каждым запросом страницы. Задание помечается `cancelled` через `POST /api/jobs/{id}/cancel` (`routes/jobs.py`). Итоговый статус фоновых заданий пишет `services/jobs.py:finalize_job`: он перечитывает задание и **не затирает `cancelled`**. `mark_unfinished_jobs_failed()` при старте сервера переводит оставшиеся `pending`/`running` в `failed`.

### Playwright-модули (3)
| Модуль | Назначение | headless |
|--------|-----------|----------|
| `category_verifier.py` | Верификация названий категорий через перехват API | configurable |
| `product_opener.py` | Открытие товара пользователю в видимом браузере | **False** (видимое окно) |
| `store_selector.py` | Сканирование списка магазинов | configurable |

Перед использованием Playwright: `playwright install chromium`.
