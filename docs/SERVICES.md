# Сервисный слой (`src/server/services/`)

Модули бизнес-логики, не относящиеся к HTTP-роутам. Здесь — работа с внешним API Магнита, сканирование, bulk-операции с БД, браузерная автоматизация (Playwright) и формирование уведомлений.

| Файл | Технология | БД | Внешние вызовы | Threading |
|------|-----------|----|-----------------|-----------|
| `magnit_api.py` | `requests` | нет | magnit.ru API (goods/search, stores-facade) | нет, sync |
| `catalog_scanner.py` | SQLAlchemy + bulk ops | `Product`, `PriceHistory`, `Category`, `ScanJob` | через `MagnitAPIClient` | нет, sync (внешний job) |
| `catalog_updater.py` | `requests` + SQLAlchemy | `Category` (с сохранением `is_tracked`) | magnit.ru API | нет, sync |
| `category_verifier.py` | Playwright | нет (JSON-файл) | magnit.ru (браузер) | нет, sync |
| `load_catalog_from_json.py` | SQLAlchemy | `Category` | нет (чтение JSON) | нет, sync |
| `notifications.py` | SQLAlchemy | `Product`, `Category` | нет (только формирование данных) | нет, sync |
| `product_opener.py` | Playwright | нет | magnit.ru (видимый браузер) | нет, sync |
| `store_selector.py` | Playwright | нет | magnit.ru (браузер) | нет, sync |

---

## 1. `magnit_api.py` — клиенты API Магнита

Единая точка взаимодействия с внешним API magnit.ru. Два независимых клиента.

### `MagnitAPIClient` (товары и категории) — `magnit_api.py:29`

**Конструктор:** `__init__(base_url="https://magnit.ru", store_code=None, store_type=None, timeout=15, rate_limit=0.5)` (`magnit_api.py:32`)
- `store_code`/`store_type` берутся из аргументов или env `STORE_CODE`/`STORE_TYPE` (по умолчанию `"MM"`).
- Создаёт `requests.Session` с заголовками Chrome 120 (UA, Referer, Origin, `X-Requested-With: XMLHttpRequest`).
- Хранит `_last_request_time` для rate limiting.

**Rate limiting — `_rate_limit_wait()` (`magnit_api.py:63`):**
- Гарантирует минимум `rate_limit` (**0.5 сек** по умолчанию) между запросами: если прошло меньше — `time.sleep(rate_limit - elapsed)`.
- Дополнительно **случайная пауза 0.1–0.5 сек** (`random.uniform(0.1, 0.5)`) — рандомизация защищает от детектирования ботов.

> 🔴 **КРИТИЧНО:** убирать rate limiting нельзя — API Магнита блокирует. См. `docs/DEVELOPMENT.md`.

**Главный метод `search()` (`magnit_api.py:73`):**
```python
def search(self, store_code=None, store_type=None, category_ids=None,
           limit=50, offset=0) -> dict
```
- Универсальный: если `category_ids` не задан → возвращает категории; если задан → товары.
- Эндпоинт: **POST `https://magnit.ru/webgate/v2/goods/search`**.
- **Преобразование типа магазина:** `store_type` может быть API-кодом (`MM`, `MM_MINI`, `ME`, `DG`, `GM`, `MO`, `MC`, `ZARYAD`), русским названием или числом. Сначала через `STORE_TYPE_MAP` (`constants.py:18`) → русское название, затем через `API_STORE_TYPE_CODE` → числовой код в `payload["storeType"]`.
- `payload`: `sort` (по популярности, desc), `pagination` (limit/offset), `includeAdultGoods: True`, `storeCode`, `storeType`, `catalogType: "1"`, `categories` (список или `[]`).
- Возвращает `{items, total, hasMore, next_offset}`. `hasMore`/`next_offset` берётся из `pagination.nextOffset` API либо вычисляется `offset + len(items)`.

**Парсинг:**
- `_parse_category(item)` (`magnit_api.py:213`) → `{magnit_id, name, url, product_count, parent_id}`.
- `_parse_product(item)` (`magnit_api.py:231`) → словарь с полями товара. **Цена конвертируется из копеек в рубли (деление на 100)** (`magnit_api.py:243`, `:263` для `unit_price` весовых). Берёт `gallery[0].url` как `image_url`, `ratings` → `rating`/`scores_count`/`comments_count`, `orderProperties` → `min_order_qty`/`order_step_qty`, `weighted` → `is_weighted`/`unit_price`. При ошибке парсинга логирует traceback и возвращает `None`.

**Прочее:** `set_store_code()` (`magnit_api.py:309`), `close()` (`magnit_api.py:313`).

### `StoresAPI` (поиск магазинов) — `magnit_api.py:321`

**Конструктор:** `__init__(base_url="https://magnit.ru", timeout=15, rate_limit=0.3)` (`magnit_api.py:328`)
- `rate_limit=0.3` (короче, чем у `MagnitAPIClient`).
- Случайный `device_id = str(uuid.uuid4())` (`magnit_api.py:334`) — в заголовке `X-Device-Id`.
- Заголовки веб-клиента: `X-Client-Name: magnit`, `X-New-Magnit: true`, `X-App-Version`, `X-Device-Platform: Web`, `X-Device-Tag: disabled`.

**`search_stores(query, store_types=None, limit=50, offset=0)` (`magnit_api.py:369`):**
- Эндпоинт: **POST `/webgate/v1/stores-facade/search/detail`**.
- Сначала GET `/shops` (`magnit_api.py:399`) для получения cookies.
- **Отдельный запрос для КАЖДОГО типа магазина** из `store_types` (по умолчанию `ALL_STORE_TYPES` — все 8 типов), передавая `storeTypeListV2: [store_type]` в фильтрах.
- `payload.filters.query` = поисковый запрос, `sorting: SORT_BY_CITY ASC`.
- **Дедупликация по `code`** (`magnit_api.py:449`): берёт `externalId.storeCode` или `code`/`store_code`.
- Возвращает `{stores, total, hasMore: False}` (пагинация на уровне API не используется).

---

## 2. `catalog_scanner.py` — сканирование каталога

Класс `CatalogScanner` (`catalog_scanner.py:27`). Сканирование каталога товаров и категорий через `MagnitAPIClient` с сохранением в БД. Реализует bulk-операции, отслеживание истории цен, очистку и интеграцию с `ScanJob`.

**Константа:** `PRICE_HISTORY_RETENTION_DAYS = 30` (`catalog_scanner.py:24`).

**Конструктор:** `__init__(db: Session, store_code=None, address=None, job_id=None)` (`catalog_scanner.py:30`)
- Принимает SQLAlchemy `Session`, код магазина, адрес (для отображения в прогрессе) и `job_id`.
- **Определяет `store_type` из БД** по `store_code` (`catalog_scanner.py:43`): запрашивает `Store`, по умолчанию `"Магнит"`.
- Создаёт `MagnitAPIClient(store_code, store_type)` только если задан `store_code`.

**Обновление прогресса задания:**
- `_update_job_progress(message)` (`catalog_scanner.py:53`) — обновляет `progress_message` в `ScanJob`.
- `_update_job_progress_full(**kwargs)` (`catalog_scanner.py:61`) — обновляет произвольные поля (`current_category_items_total`, `current_category_items_loaded`).

### `scan_categories()` (`catalog_scanner.py:67`)
→ `{scanned, added, updated, deleted}`
- Получает все **отслеживаемые корневые категории** (`parent_id IS NULL AND is_tracked == True`) — `catalog_scanner.py:88`.
- Для каждой вызывает `_fetch_category_data(magnit_id)` (`catalog_scanner.py:116`).
- Обновляет название корневой категории из `category.title` (`catalog_scanner.py:126`).
- **Полная синхронизация подкатегорий** (`catalog_scanner.py:139`): удаляет из БД те, которых нет в API; обновляет существующие (по `magnit_id`); добавляет новые с `parent_id=root_cat.id`.
- Коммитит после каждой корневой категории.

### `scan_products(category_ids=None, tracked_only=False)` (`catalog_scanner.py:213`)
→ `{scanned, added, updated, price_changes, deleted, history_deleted}`
- Если `category_ids` не задан — берёт все категории из БД (с фильтром `is_tracked` если `tracked_only`), извлекает их `magnit_id`.
- **Сканирует по одной категории за раз** (`catalog_scanner.py:270`).
- **Проверка отмены** перед каждой итерацией: `self.db.expire_all()` сбрасывает кэш сессии, затем проверяет `ScanJob.status == "cancelled"` (`catalog_scanner.py:272-277`, `:295-300`). При отмене возвращает нулевые счётчики.
- **Retry с экспоненциальным backoff** (`catalog_scanner.py:288-340`): до 3 попыток, задержки 2/4/8 секунд (`2**retry_count`). Особая обработка `invalid_service_pair`/`service not found` — категория считается недоступной для типа магазина и пропускается.
- **Пагинация:** цикл `while has_more`, использует `next_offset` из API либо вычисляет `offset + len(products)`. Прерывается при пустом `products`.
- Обновляет `current_category_items_total`/`current_category_items_loaded` в `ScanJob`.
- После сканирования обновляет `Category.last_scanned = datetime.utcnow()` (`catalog_scanner.py:399-411`).
- **Вызывает очистку:** `cleanup_stale_products(days_threshold=7)` и `cleanup_price_history()`.

### `_save_products(products, category_magnit_id)` (`catalog_scanner.py:435`) — КЛЮЧЕВОЙ метод
→ `(added_count, updated_count, price_change_count)`

**Оптимизация:** один SELECT для всех `product_ids` (вместо N+1), bulk INSERT для новых, bulk UPDATE для существующих, один COMMIT.

**Логика цены:**
- `price_history` хранит **одну запись на день** для каждого `(product_id, store_code)`.
- `previous_price` / `price_change_percent` берутся из **последней записи предыдущего дня** (`scan_date < today`) — `catalog_scanner.py:495-516`.
- `last_change_price` / `last_change_date` обновляются только при **реальном изменении** цены (`abs(diff) > 0.01`) относительно `existing.last_change_price` — `catalog_scanner.py:576-588`.
- `price_change_percent = round((prev - current) / prev * 100, 1)` — `catalog_scanner.py:564`. Положительное = снижение, отрицательное = повышение.

**Шаги:**
1. Находит категорию в БД по `magnit_id` (`catalog_scanner.py:463`).
2. **Одним запросом** получает все существующие товары по `(product_id IN (...), store_code)` (`catalog_scanner.py:482`).
3. **Одним запросом** получает историю цен предыдущих дней (`catalog_scanner.py:499`).
4. Разделяет на `to_insert` и `to_update` (`catalog_scanner.py:519-632`), формируя словари для `bulk_insert_mappings` / `bulk_update_mappings`.
5. `self.db.bulk_insert_mappings(Product, to_insert)` (`catalog_scanner.py:637`).
6. `self.db.bulk_update_mappings(Product, to_update)` (`catalog_scanner.py:644`).
7. `self._upsert_price_history(products, today)` (`catalog_scanner.py:649`).
8. Один `commit()` (`catalog_scanner.py:652`).

### `_upsert_price_history(products_data, scan_date)` (`catalog_scanner.py:656`)
Для каждого товара проверяет существование записи за `scan_date` по `(product_id, store_code)`. Если есть — bulk UPDATE (`price`, `quantity`, `in_stock`); если нет — bulk INSERT. Upsert-семантика «одна запись на день».

### `cleanup_stale_products(days_threshold=7)` (`catalog_scanner.py:707`)
Удаляет товары с `last_seen < now - days_threshold` для текущего `store_code`. **Порог: 7 дней** (не 30, как было в старой документации).

### `cleanup_price_history(days=30)` (`catalog_scanner.py:730`)
Удаляет записи `PriceHistory` старше 30 дней (`PRICE_HISTORY_RETENTION_DAYS`).

### `close()` (`catalog_scanner.py:749`)
Закрывает `MagnitAPIClient`.

---

## 3. `catalog_updater.py` — обновление дерева категорий

Класс `CatalogUpdater` (`catalog_updater.py:18`). Обновление дерева категорий из API. Поддерживает два режима: инкрементальное и **полную замену** с сохранением `is_tracked`.

**Конструктор:** `__init__(store_code=None, store_type=None)` (`catalog_updater.py:21`)
- `store_code` по умолчанию `"210117"`, `store_type` по умолчанию `"9"` (числовой код «Моя цена»).
- `base_url` = `https://magnit.ru/webgate/v2/goods/search` (`catalog_updater.py:22`).
- `categories_file` = `src/data/categories.json` (`catalog_updater.py:27`).
- Свой `requests.Session` (не использует `MagnitAPIClient`).

**Rate limiting — `_rate_limit_wait()` (`catalog_updater.py:38`):** 0.5 сек, **без случайной паузы** (в отличие от `MagnitAPIClient`).

**Методы:**
- `fetch_category_data(category_id)` (`catalog_updater.py:46`) — POST с `categories: [category_id]`, `limit: 32`, `offset: 0`.
- `load_root_categories_from_file()` (`catalog_updater.py:67`) — читает `categories.json`.
- `update_category_from_api(db, category, api_data)` (`catalog_updater.py:80`) → `(updated, added, deleted)` — синхронизация подкатегорий.
- `update_all_categories()` (`catalog_updater.py:137`) → `{total, processed, updated, added, deleted, errors}` — инкрементальное обновление всех категорий.

### `replace_all_categories()` (`catalog_updater.py:228`) — полная замена
1. Загружает корневые категории из файла.
2. Собирает ВСЕ категории из API (корневые + подкатегории) в `[(magnit_id, title, parent_magnit_id)]`.
3. Если есть ошибки API — **возвращает ошибку и НЕ меняет БД** (защита от потери данных).
4. **Сохраняет старые `is_tracked`** в `old_tracked_status = {magnit_id: is_tracked}` (`catalog_updater.py:300-305`).
5. `db.query(Category).delete()` — полная очистка таблицы (`catalog_updater.py:309`).
6. Сначала добавляет корневые (`parent_magnit_id is None`) с `db.flush()` для получения ID; затем подкатегории, привязывая `parent_id = magnit_to_db_id[parent_magnit_id]`. **`is_tracked` восстанавливается** из `old_tracked_status.get(magnit_id, False)` (`catalog_updater.py:327`, `:353`).
7. Возвращает `{status, total, added, updated, errors}`. При критической ошибке — `rollback()` + traceback.

**Модульные функции-обёртки:**
- `update_catalog_from_api(store_code, store_type)` (`catalog_updater.py:389`) — инкрементальное.
- `replace_catalog_from_api(store_code, store_type)` (`catalog_updater.py:398`) — полная замена.

> Используется фоновой задачей `_fetch_and_update_categories_background()` в `routes/catalog.py:785` (запускается через `POST /api/categories/fetch-magnit-ids`).

---

## 4. `category_verifier.py` — верификация категорий через Playwright

Класс `CategoryVerifier` (`category_verifier.py:16`). Проверка и актуализация названий корневых категорий в `categories.json` через **Playwright**. Браузер открывает magnit.ru, кликает по каталогу, перехватывает API-ответы и сравнивает названия.

**Константы:**
- `CATEGORIES_FILE` = `src/data/categories.json` (`category_verifier.py:11`).
- `MAGNIT_URL` = `https://magnit.ru/` (`category_verifier.py:12`).
- `API_ENDPOINT` = glob `**/webgate/v2/goods/search` (`category_verifier.py:13`).

**Конструктор:** `__init__(headless=True)` (`category_verifier.py:17`).

**Методы:**
- `load_categories()` / `save_categories(data)` (`category_verifier.py:22` / `:26`).
- **`handle_response(response)`** (`category_verifier.py:30`) — callback на `page.on("response")`. Если URL содержит `API_ENDPOINT`, метод POST и в `post_data_json` есть `categories`, берёт `category_id = post_data["categories"][0]`, парсит тело и сохраняет `{api_id, api_title, subcategories: [{id, title}]}`. Ошибки глушатся `except: pass`.
- **`verify_and_update()`** (`category_verifier.py:51`) — основной метод:
  - `sync_playwright()`, Chromium, контекст с viewport 1920×1080, locale `ru-RU`.
  - `page.goto(MAGNIT_URL, domcontentloaded, timeout=60000)`, `sleep(3)`.
  - Кликает «Каталог», для каждой корневой категории: ищет `text={cat_title}`, кликает → «Все товары этой категории» → сравнивает `api_title` с `cat_title`. При расхождении обновляет JSON. Кликает «Назад».
  - Возвращает `{total, checked, updated}`.

> Дублируется standalone-скриптом `src/scripts/verify_categories.py` (аналогичная логика, но с интерактивным `input()` для подтверждения записи).

---

## 5. `load_catalog_from_json.py` — загрузка каталога из JSON

Функция `load_catalog_from_json(db: Session = None) -> dict` (`load_catalog_from_json.py:12`). Загрузка корневых категорий и подкатегорий из `src/data/categories.json` в таблицу `Category`. Используется для инициализации каталога при первом запуске.

**Логика (`load_catalog_from_json.py:38-148`):**
1. Если `db=None` — создаёт `SessionLocal()` и помечает `close_session=True`.
2. Читает `data["root_categories"]`.
3. Для каждой корневой: проверяет наличие по `magnit_id` — если есть, обновляет `name`; если нет — создаёт с `parent_id=None`, `is_tracked=False`, `product_count=0`.
4. Для каждой подкатегории (`fastCategoriesExtended`): находит родителя по `magnit_id`; если родитель не найден — логирует и пропускает; иначе создаёт/обновляет с `parent_id=parent.id`.
5. Один `db.commit()` в конце.
6. При ошибке — `db.rollback()` + `raise`.

**Возвращает:** `{scanned, added, updated}`.

> ⚠️ **Потенциальный баг:** ожидает `data["root_categories"]`, но фактический `categories.json` — плоский массив `[{id, title}]` без этого ключа. Зафиксировано в `docs/DEVELOPMENT.md` как техдолг.

---

## 6. `notifications.py` — формирование уведомлений

Класс `NotificationService` (`notifications.py:12`). **Генерация отчётов и текстов уведомлений. Не отправляет во внешние системы** (нет Telegram/email/webhook) — только формирует данные и текст. Отправку выполняет вызывающий код.

**Конструктор:** `__init__(db: Session, store_code: Optional[str] = None)` (`notifications.py:15`).

**Методы:**
- **`generate_daily_report()`** (`notifications.py:19`) — отчёт за вчерашний день:
  - `decreased` — товары с `price_change_percent > 0` (снижение) и `last_price_change` вчера.
  - `increased` — `price_change_percent < 0` (повышение).
  - `new_products_count` — `first_seen` вчера.
  - `top_deals` — топ-5 с `price_change_percent >= 10.0`, отсортированных по убыванию (`notifications.py:67-77`).
  - Возвращает `{date, summary: {total_changes, price_decreases, price_increases, new_products}, top_deals: [...]}`.
- **`check_new_products_in_tracked_categories(days=1)`** (`notifications.py:100`) — товары с `first_seen >= now - days` в отслеживаемых категориях.
- **`check_out_of_stock_to_available(days=1)`** (`notifications.py:150`) — упрощённая логика: возвращает товары в наличии с `last_seen >= cutoff`, лимит 20.
- **`format_alert_message(alert_type, data)`** (`notifications.py:189`) — текст с эмодзи:
  - `"deal"` → «🔥 Скидка! {name}\nБыло: ...₽\nСтало: ...₽\nЭкономия: ...%»
  - `"new_product"` → «🆕 Новый товар: {name} — {price}₽»
  - `"in_stock"` → «✅ В наличии: {name} — {price}₽»

---

## 7. `product_opener.py` — открытие товара в браузере

Функция `open_product_with_store(product_url, store_code, store_type)` (`product_opener.py:10`). Открывает страницу товара на magnit.ru в **видимом Chromium через Playwright** с попыткой автоматического выбора магазина.

**Логика (`product_opener.py:19-64`):**
- `sync_playwright()`, `p.chromium.launch(headless=False)` — **видимое окно**.
- `page.goto("https://magnit.ru/", domcontentloaded)`, `sleep(2)`.
- Пытается выбрать магазин: ищет кнопку «Выбрать магазин», заполняет поле поиска кодом магазина, кликает первый результат «Выбрать». При ошибке — логирует и продолжает («Пользователь может выбрать магазин вручную»).
- `page.goto(product_url, domcontentloaded)`.
- **Браузер НЕ закрывается автоматически** — остаётся открытым для пользователя (`product_opener.py:59-63`).

> Запускается из `main.py:205` (`GET /open-product-in-browser`) через `threading.Thread`, чтобы не блокировать HTTP-ответ.

---

## 8. `store_selector.py` — Playwright-сканер магазинов

Класс `MagnitStoreSelector` (`store_selector.py:11`). Автоматизация выбора и сканирования магазинов на magnit.ru через Playwright.

> ⚠️ **Важно:** этот модуль **НЕ обновляет `.env`** — это Playwright-браузерная автоматизация. Фактическое обновление `.env` выполняется в `routes/stores.py:141-171` (через `python-dotenv`).

**Конструктор:** `__init__(headless=True)` (`store_selector.py:14`). Хранит `playwright`, `browser`, `page`.

**Управление жизненным циклом:**
- `start()` (`store_selector.py:20`) — `sync_playwright().start()`, `chromium.launch(headless)`, контекст с UA Chrome 120, `locale="ru-RU"`.
- `close()` (`store_selector.py:34`) — `browser.close()` + `playwright.stop()`.

**Навигация (перебор CSS-селекторов с try/except — устойчивость к изменениям вёрстки):**
- `open_store_selector()` (`store_selector.py:41`)
- `select_mode_in_store()` (`store_selector.py:46`)
- `click_select_store_button()` (`store_selector.py:73`)
- `enter_address(address)` (`store_selector.py:94`)
- `select_store_type(store_type)` (`store_selector.py:120`) — маппинг русских названий (`Экстра`→`["Экстра", "Extra"]`, `Мини`→`["Мини", "Mini"]` и др.)
- `get_all_stores_from_list()` (`store_selector.py:156`) — парсит элементы списка магазинов.
- `_parse_store_text(text)` (`store_selector.py:193`) — извлекает `{name, full_address, city, address}`. **Город** — регулярками (`, г Город`, `, г. Город` и обратные формы), эвристика при отсутствии.
- `extract_store_code_from_api()` (`store_selector.py:254`) — **заглушка** (`return None`).

### `run_full_scan(city, street=None, store_types=None, progress_callback=None)` (`store_selector.py:263`)
1. `open_store_selector()`.
2. Формирует `address = city[, street]`, `enter_address`.
3. Для каждого типа из `store_types` (по умолчанию `["Экстра", "Мини", "Семейный"]`): `select_store_type` → `get_all_stores_from_list` → помечает `store["store_type"]` → добавляет в `all_stores` (без дублей) → сбрасывает фильтр `select_store_type("Все")`.
4. `progress_callback(progress, message)` с процентами 5/15/20-80/90/100.
5. При ошибке — `progress_callback(-1, ...)` и `raise`.

---

## Сводка ключевых механизмов

### Rate limiting
| Клиент | Файл:строка | Пауза | Случайная добавка |
|--------|------------|-------|-------------------|
| `MagnitAPIClient` | `magnit_api.py:63` | 0.5 сек | `random.uniform(0.1, 0.5)` |
| `StoresAPI` | `magnit_api.py` (внутри) | 0.3 сек | — |
| `CatalogUpdater` | `catalog_updater.py:38` | 0.5 сек | — |

### Bulk-операции (только в `CatalogScanner._save_products`)
- `bulk_insert_mappings(Product, to_insert)` — массовая вставка новых товаров.
- `bulk_update_mappings(Product, to_update)` — массовое обновление существующих.
- `bulk_insert_mappings` / `bulk_update_mappings` для `PriceHistory` в `_upsert_price_history`.
- Один SELECT для всех существующих товаров по `(product_id IN (...), store_code)`.
- Один `commit()` в конце.

### Retry с экспоненциальным backoff
Только в `CatalogScanner.scan_products()` (`catalog_scanner.py:288-340`): до 3 попыток, задержки 2/4/8 сек. Особая обработка `invalid_service_pair`/`service not found` — категория пропускается.

### Проверка отмены
`CatalogScanner.scan_products()` перед каждой итерацией: `self.db.expire_all()` (сброс кэша) → проверка `ScanJob.status == "cancelled"`. Реальная остановка — задание помечается `cancelled` через `POST /api/jobs/{id}/cancel` (`routes/jobs.py:52`).

### Playwright-модули (3)
| Модуль | Назначение | headless |
|--------|-----------|----------|
| `category_verifier.py` | Верификация названий категорий через перехват API | configurable |
| `product_opener.py` | Открытие товара пользователю в видимом браузере | **False** (видимое окно) |
| `store_selector.py` | Сканирование списка магазинов | configurable |

Перед использованием Playwright: `playwright install chromium`.
