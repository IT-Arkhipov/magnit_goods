# База данных

СУБД: **SQLite**. Файл: `src/data/magnit.db` (в `.gitignore`).

Создаётся автоматически при старте через `init_db()` (`src/server/database.py`), которая вызывает `Base.metadata.create_all(bind=engine)` и затем выполняет миграции.

Engine и сессия:
- `engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False, "timeout": 30})` — `database.py:engine`. При каждом подключении (`_set_sqlite_pragma`) включаются `journal_mode=WAL` и `busy_timeout=30000`; файлы `magnit.db-wal`/`magnit.db-shm` в `.gitignore`. Подробности и правила бэкапа — `docs/DEPLOYMENT.md`.
- `SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)` — `database.py`
- `get_db()` (`database.py`) — FastAPI-dependency: открывает сессию, отдаёт через `yield`, закрывает в `finally`.

> ⚠️ **Важно:** `check_same_thread=False` позволяет использовать один engine из разных потоков (фоновые задачи, scheduler). При этом каждая задача обязана создавать **свою** `SessionLocal()` — не переиспользовать сессию из FastAPI-dependency (она закрывается после HTTP-ответа).

---

## Модели (`src/server/models.py`)

### 1. `Store` — магазин Магнит (`models.py`)

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | `String(12)` PK | MD5-хэш (12 символов) из `store_code + store_type + full_address` |
| `store_code` | `String` index | Код магазина в API Магнита (напр. `992104`) |
| `store_type` | `String` index | Русское название типа (`Магнит`, `Мини`, `Экстра` и др.) |
| `shop_type` | `Integer` nullable index | Числовой код типа (1–9), см. `STORE_TYPE_CODES` в `constants.py` |
| `city` | `String` index | Город |
| `address` | `String` | Улица и дом |
| `full_address` | `String` | Полный адрес с регионом |
| `name` | `String` nullable | Название (`Магнит Экстра`, `Магнит Мини`…) |
| `is_active` | `Boolean` default `True` | Активен ли магазин |
| `created_at` | `DateTime` default `utcnow` | Дата создания записи |

**Уникальность:** пара (`store_code`, `store_type`) уникальна (индекс `uq_store_code_type`, миграция `add_store_code_type_unique`): один код может принадлежать магазинам разных типов, но не дважды одному типу. Дубликаты в старых БД миграция схлопывает, оставляя самую раннюю запись, и пишет удалённые в лог.

**Генерация ID:** функция `store_hash_id(store_code, store_type, full_address)` (`models.py`) — `hashlib.md5(f"{code}|{type}|{addr}").hexdigest()[:12]`.

Конструктор `Store.__init__` (`models.py`) автоматически:
- вычисляет `id` через `store_hash_id`, если не передан явно;
- проставляет `shop_type` из `STORE_TYPE_CODES` по `store_type`, если не передан.

> 🔴 **Критично:** ID магазинов — **строки** (MD5-хэши), НЕ integers. FastAPI path-параметры для магазинов должны объявляться как `store_id: str`. Использовать `store_hash_id()` при ручном создании `Store`.

### 2. `Category` — категория каталога (`models.py`)

Универсальная, **без привязки к конкретному магазину** — дерево общее для всех магазинов.

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | `Integer` PK index | Внутренний ID |
| `magnit_id` | `Integer` nullable index | ID из API Магнита |
| `name` | `String` | Название (`Бакалея`, `Молочный прилавок`…) |
| `url` | `String` | URL категории на magnit.ru |
| `parent_id` | `Integer` FK→`categories.id` index | Родительская категория (`None` для корневых) |
| `is_tracked` | `Boolean` index default `False` | Отслеживается (включена в сканирование товаров) |
| `product_count` | `Integer` default `0` | Кол-во товаров (из API) |
| `last_scanned` | `DateTime` nullable | Дата последнего сканирования товаров категории |
| `created_at` | `DateTime` default `utcnow` | Дата создания |

Связь: `children = relationship("Category", backref="parent", remote_side=[id])` — `models.py`. В БД хранится только `parent_id`; отношение `children` — ORM-удобство, **не использовать** для рекурсивных запросов (порождает N+1, см. `docs/code_review_2026-06-12.md`).

### 3. `Product` — товар, текущее состояние (`models.py`)

Центральная модель. Товары идентифицируются парой `(product_id, store_code)` — один и тот же товар в разных магазинах это **разные строки**.

**Идентификация и связи:**
| Поле | Тип | Описание |
|------|-----|----------|
| `id` | `Integer` PK index | Внутренний ID |
| `product_id` | `Integer` | ID товара в API Магнита (без index — покрыт составным) |
| `name` | `String` | Название |
| `sku` | `String` nullable | Артикул |
| `category_id` | `Integer` FK→`categories.id` nullable index | Категория |
| `store_code` | `String` | Код магазина (без index — покрыт составным) |
| `category` | relationship | Обратная связь к `Category` (backref `products`) |

**Цена и наличие:**
| Поле | Тип | Описание |
|------|-----|----------|
| `price` | `Float` index | Текущая цена в рублях (в API — в копейках, делится на 100) |
| `currency` | `String` default `₽` | Символ валюты |
| `unit` | `String` nullable | Единица измерения (`шт`, `кг`, `л`…) |
| `image_url` | `String` nullable | URL картинки (первая из `gallery`) |
| `in_stock` | `Boolean` default `True` | В наличии |

**Остатки:**
| Поле | Тип | Описание |
|------|-----|----------|
| `quantity` | `Integer` default `0` | Остаток на складе |
| `is_low_stock` | `Boolean` nullable | Мало ли осталось |
| `pickup_only` | `Boolean` default `False` | Только самовывоз |

**Рейтинги и отзывы:**
| Поле | Тип | Описание |
|------|-----|----------|
| `rating` | `Float` nullable | Рейтинг товара |
| `scores_count` | `Integer` default `0` | Кол-во оценок |
| `comments_count` | `Integer` default `0` | Кол-во отзывов |

**SEO и каталог:**
| Поле | Тип | Описание |
|------|-----|----------|
| `seo_code` | `String` nullable | SEO-слаг |
| `service` | `String` nullable | Сервис (`core_mm` и т.п.) |
| `catalog_type` | `String` nullable | Тип каталога |

**Параметры заказа:**
| Поле | Тип | Описание |
|------|-----|----------|
| `min_order_qty` | `Integer` default `1` | Минимальное кол-во |
| `order_step_qty` | `Integer` default `1` | Шаг заказа |

**Весовые товары:**
| Поле | Тип | Описание |
|------|-----|----------|
| `is_weighted` | `Boolean` default `False` | Весовой ли товар |
| `unit_price` | `Float` nullable | Цена за кг/л |

**Временные метки:**
| Поле | Тип | Описание |
|------|-----|----------|
| `first_seen` | `DateTime` default `utcnow` | Первое появление в сканах |
| `last_seen` | `DateTime` default `utcnow` | Последнее сканирование, где товар найден |
| `last_price_change` | `DateTime` nullable | Дата последнего изменения цены |
| `last_scan_found` | `DateTime` nullable | Дата последнего скана, когда товар был найден |
| `name_search` | `String` nullable | `name.casefold()` — для регистронезависимого поиска по кириллице в SQL (SQLite `LOWER()` её не поддерживает). Заполняется `CatalogScanner._save_products` и миграцией `add_product_name_search`; в API не отдаётся |

**Отслеживание цен:**
| Поле | Тип | Описание |
|------|-----|----------|
| `previous_price` | `Float` nullable | Цена из **предыдущего сканирования** |
| `price_change_percent` | `Float` index nullable | Процент изменения: **+** снижение, **−** повышение |
| `last_change_price` | `Float` nullable | Цена **до последнего реального изменения** |
| `last_change_date` | `DateTime` nullable | Дата последнего реального изменения |

> Семантика `previous_price` и `last_change_price` различается — см. раздел [Логика цен](#логика-цен) ниже.

**Индексы и ограничения** (`__table_args__`, `models.py`):
| Имя | Тип | Колонки |
|-----|-----|---------|
| `uq_product_store` | UNIQUE | `(product_id, store_code)` |
| `ix_product_store_lookup` | INDEX | `(product_id, store_code)` |
| `ix_product_price_change` | INDEX | `(store_code, price_change_percent)` |
| `ix_product_last_scan` | INDEX | `(store_code, last_scan_found)` |

Составной индекс `(product_id, store_code)` ускоряет `bulk_update_mappings` и выборки «свежих» товаров по магазину.

### 4. `PriceHistory` — история цен по дням (`models.py`)

Одна запись на день для каждого `(product_id, store_code)`. Используется для расчёта `previous_price`/`price_change_percent` и отображения истории на странице товара.

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | `Integer` PK index | Внутренний ID |
| `product_id` | `Integer` index | ID товара |
| `store_code` | `String` index | Код магазина |
| `price` | `Float` | Цена на день скана (рубли) |
| `quantity` | `Integer` nullable | Остаток на момент скана |
| `in_stock` | `Boolean` nullable | Наличие на момент скана |
| `scan_date` | `Date` | День сканирования (одна запись на день) |
| `created_at` | `DateTime` default `utcnow` | Дата создания записи |

**Индексы и ограничения** (`models.py`):
| Имя | Тип | Колонки |
|-----|-----|---------|
| `uq_price_history_day` | UNIQUE | `(product_id, store_code, scan_date)` |
| `ix_price_history_lookup` | INDEX | `(product_id, store_code, scan_date)` |

Хранение: retention **30 дней** (`PRICE_HISTORY_RETENTION_DAYS` в `catalog_scanner.py`). Очистка — `CatalogScanner.cleanup_price_history()` (`catalog_scanner.py`).

> **История изменений модели:** ранее в проекте была отдельная таблица `DailyPriceSnapshot` и поля акций (`old_price`, `discount_percent`, `is_promotion`, `promo_end_date`, `historical_*`). Они удалены миграцией `migrate_simplify_price_tracking`. Затем `PriceHistory` была **восстановлена** миграцией `migrate_create_price_history` для по-дневной истории.

### 5. `ScanJob` — задание на сканирование (`models.py`)

Фоновые задания: `prices`, `catalog`, `stores`, `scan_all_stores`. См. `docs/scan_jobs.md` — зачем нужны статусы.

| Поле | Тип | Описание |
|------|-----|----------|
| `id` | `Integer` PK index | ID задания |
| `job_type` | `String` | Тип: `prices` / `catalog` / `stores` / `scan_all_stores` |
| `store_code` | `String` nullable | Код магазина (для `scan_all_stores` — `"{N} stores"`) |
| `category_ids` | `Text` nullable | CSV список ID категорий |
| `status` | `String` default `pending` | `pending` / `running` / `completed` / `failed` / `cancelled` |
| `progress` | `Integer` default `0` | Прогресс в процентах |
| `progress_message` | `String` nullable | Текстовое описание текущего шага |
| `started_at` | `DateTime` nullable | Время начала |
| `finished_at` | `DateTime` nullable | Время завершения |
| `items_scanned` | `Integer` default `0` | Просканировано товаров |
| `items_added` | `Integer` default `0` | Добавлено новых |
| `items_updated` | `Integer` default `0` | Обновлено |
| `error_message` | `Text` nullable | Текст ошибки (при `failed`) |
| `created_at` | `DateTime` default `utcnow` | Дата создания |

**Поля детального прогресса** (для `scan_all_stores`, добавлены миграцией `migrate_add_scan_job_progress_fields`):
| Поле | Тип | Описание |
|------|-----|----------|
| `total_stores` | `Integer` default `0` | Всего магазинов |
| `current_store_index` | `Integer` default `0` | Индекс текущего магазина |
| `current_store_code` | `String` nullable | Код текущего магазина |
| `current_store_address` | `String` nullable | Адрес текущего магазина |
| `total_categories` | `Integer` default `0` | Всего категорий |
| `current_category_index` | `Integer` default `0` | Индекс текущей категории |
| `current_category_name` | `String` nullable | Название текущей категории |
| `current_category_magnit_id` | `Integer` nullable | magnit_id текущей категории |
| `current_category_items_total` | `Integer` default `0` | Всего товаров в категории |
| `current_category_items_loaded` | `Integer` default `0` | Загружено товаров из категории |

---

## Логика цен

### Поля `previous_price` и `last_change_price` — в чём разница

Проект поддерживает **два режима отображения** изменения цен (чекбокс «Новая цена» в UI):

| Поле | Обновляется | Что хранит |
|------|-------------|-----------|
| `previous_price` | **при каждом сканировании** | Цену из **предыдущего скана** (даже если цена не изменилась) |
| `last_change_price` | **только при реальном изменении** цены (`abs(existing.price - current) > 0.01`) | Цену **непосредственно перед** последним реальным изменением |
| `price_change_percent` | при каждом скане (из `PriceHistory` предыдущего дня) | `round((prev - current) / prev * 100, 1)` |
| `last_change_date` | только при реальном изменении | Момент (скан), в котором изменение обнаружено |
| `last_price_change` | только при реальном изменении | То же, что `last_change_date` (используется списком скидок `/api/prices/decreased`) |

**Знак `price_change_percent`:**
- **`+15`** → цена **снизилась** на 15% (зелёная стрелка `↓` в UI)
- **`-11.8`** → цена **повысилась** на 11.8% (фиолетовая стрелка `↑` в UI)

Формула: `(previous_price - current_price) / previous_price * 100`. Положительное значение = снижение.

### Режимы отображения в UI

| Режим | Чекбокс | Источник данных | Тултип |
|-------|---------|-----------------|--------|
| **«Новая цена»** (включён по умолчанию) | ☑ | `price_change_percent`, `previous_price`, `last_price_change` | Остаток + дата сканирования |
| **«Последнее изменение»** | ☐ | пересчёт процента от `last_change_price`, `last_change_date` | Предыдущая цена + дата изменения |

### Сценарии

**Сценарий 1 — первое сканирование (100₽):**
```
price=100, previous_price=100, price_change_percent=NULL, last_change_price=NULL
```
Оба режима: `100₽` (без процента).

**Сценарий 2 — цена изменилась (100₽ → 120₽):**
```
price=120, previous_price=100, price_change_percent=-20, last_change_price=100, last_change_date=2026-05-31
```
- Режим 1: `120₽ (↑20%)` — изменение от предыдущего скана
- Режим 2: `120₽ (↑20%)` — последнее реальное изменение

**Сценарий 3 — цена не изменилась (120₽ → 120₽):**
```
price=120, previous_price=120, price_change_percent=-20 (не обновлено), last_change_price=100 (не обновлено)
```
- Режим 1: `120₽` (без процента) — цена не изменилась с предыдущего скана
- Режим 2: `120₽ (↑20%)` — показывается последнее реальное изменение

### Где вычисляется

- `CatalogScanner._save_products()` (`catalog_scanner.py`) — bulk INSERT/UPDATE, расчёт `price_change_percent` из последней записи `PriceHistory` **предыдущего дня** (`scan_date < today`).
- `CatalogScanner._upsert_price_history()` (`catalog_scanner.py`) — upsert записи за сегодня (одна на день).
- `last_change_price`/`last_change_date`/`last_price_change` обновляются только при `abs(existing.price - current_price) > 0.01`, то есть сравнением с **последней сохранённой ценой**. Изменение фиксируется ровно один раз: повторные сканы с той же ценой эти поля не трогают.
- Товар без цены в ответе API (`price` отсутствует или ≤ 0) пропускается в `MagnitAPIClient._parse_product` и не попадает ни в `products`, ни в `price_history`.

**Пример (100 → 80 → 80 → 70):**

| Скан | `price` до | `price` после | `last_change_price` | `last_change_date` |
|------|-----------|---------------|---------------------|--------------------|
| день N | 100 | 80 | 100 | N |
| день N+1 | 80 | 80 | 100 (без изменений) | N |
| день M | 80 | 70 | 80 | M |

> ⚠️ **Известное ограничение.** Прежняя версия кода сдвигала `last_change_date`/`last_price_change` при каждом скане, поэтому у уже накопленных записей эти значения могут быть неточными. Автоматически они не исправляются (нет надёжного источника) — значения выправятся при следующем реальном изменении цены товара.

---

## Миграции (`src/server/database.py`)

Все миграции вызываются из `init_db()` (`database.py:init_db`) и подчиняются одному контракту:

- Миграция-функция **либо успешно возвращается, либо бросает исключение**. Подавлять ошибки внутри неё нельзя.
- Успешная миграция **регистрируется** в таблице `schema_migrations` (модель `SchemaMigration`) и больше не выполняется.
- Миграция, завершившаяся ошибкой, **не регистрируется**: `_run_migration` откатывает транзакцию, пишет `WARNING` с именем миграции и traceback, сервер продолжает старт. При следующем запуске миграция повторяется.
- Проверки «колонка/индекс уже есть» делаются заранее (`_column_names()`, `IF NOT EXISTS`), а не перехватом ошибки `ALTER`.
- Удаление колонки (`DROP COLUMN`) сначала удаляет индексы, созданные через `CREATE INDEX` на этой колонке (`_drop_indexes_on_column`) — SQLite иначе отказывается.
- Вывод — через `logging`, не `print`.

Новую миграцию добавляйте функцией в `database.py` и вызовом `_run_migration(db, "<уникальное_имя>", func, ...)` в **конец** списка в `init_db()`.

| # | Имя в реестре | Функция | Назначение |
|---|---------------|---------|-----------|
| 1 | `simplify_price_tracking` | `migrate_simplify_price_tracking` | Добавить `previous_price`/`price_change_percent`, удалить поля акций (вместе с их индексами), удалить `daily_price_snapshot` |
| 2 | `add_last_change_fields` | `migrate_add_last_change_fields` | Добавить `last_change_price`/`last_change_date`, заполнить из `previous_price`/`last_price_change` |
| 3 | `add_product_indexes` | `migrate_add_product_indexes` | Индексы `uq_product_store`, `ix_product_price_change` (и `ix_product_last_scan`, если колонка `last_scan_found` уже есть) |
| 4 | `store_ids` | `migrate_store_ids` | Конвертация integer ID магазинов → MD5-хэши (по типу колонки) |
| 5 | `categories` | `migrate_categories` | Пересоздать `categories`, если в ней остались устаревшие колонки `category_id`/`store_code` |
| 6 | `add_shop_type` | `migrate_add_shop_type` | Добавить поле `shop_type` в `stores` |
| 7 | `fill_shop_type` | `migrate_fill_shop_type` | Заполнить `shop_type` из `store_type` через `STORE_TYPE_CODES` |
| 8 | `add_last_scan_found` | `migrate_add_last_scan_found` | Добавить поле `last_scan_found` в `products` |
| 9 | `add_scan_job_progress_fields` | `migrate_add_scan_job_progress_fields` | Добавить 10 полей прогресса в `scan_jobs` |
| 10 | `fix_previous_price` | `migrate_fix_previous_price` | Восстановить `previous_price`, испорченный старым кодом (он копировал `price` при каждом скане) |
| 11 | `create_price_history` | `migrate_create_price_history` | Создать `price_history` и заполнить начальными данными за сегодня из `products` |
| 12 | `backfill_price_history` | `migrate_backfill_price_history` | Восстановить `price_history` из `last_change_price`/`last_change_date` (синтетические записи за день до изменения) |
| 13 | `ensure_product_last_scan_index` | `migrate_ensure_product_last_scan_index` | Создать `ix_product_last_scan`, если его нет (на старых БД он не создавался: миграция 3 выполнялась раньше, чем появилась колонка, а её ошибка подавлялась) |
| 14 | `add_store_code_type_unique` | `migrate_add_store_code_type_unique` | Удалить дубликаты магазинов по паре (`store_code`, `store_type`) и создать уникальный индекс `uq_store_code_type` |
| 15 | `add_product_name_search` | `migrate_add_product_name_search` | Добавить `products.name_search` и заполнить `name.casefold()` для существующих товаров (батчами по 1000) |

> **Порядок** вызова в `init_db()` — по номерам. Миграции 1 и 11 связаны: миграция 1 больше не удаляет `price_history`, миграция 11 создаёт её и заполняет, если пуста.

---

## Очистка данных

| Метод | Где | Что удаляет | Порог |
|-------|-----|-------------|-------|
| `CatalogScanner.cleanup_stale_products(days_threshold=STALE_DAYS_DELETE)` | `catalog_scanner.py` | Товары с `last_seen < now - порог` для текущего `store_code` | **6 дней** (`STALE_DAYS_DELETE`) |
| `CatalogScanner.cleanup_price_history(days=30)` | `catalog_scanner.py` | Записи `PriceHistory` старше 30 дней | 30 дней (`PRICE_HISTORY_RETENTION_DAYS`) |

Жизненный цикл товара, которого нет в сканах (`constants.py`): `STALE_DAYS_VISIBLE` = 1 день после `last_seen` товар ещё показывается в API/UI → `STALE_DAYS_HIDDEN` = 5 дней скрыт, но хранится в БД → после суммы (`STALE_DAYS_DELETE` = 6 дней) удаляется.

Обе очистки вызываются автоматически **один раз за вызов** `scan_products()` (после `_mark_missing_products`). При сканировании магазина через `scan-all-stores` — один раз на магазин.

---

## Файлы данных

| Файл | Назначение |
|------|-----------|
| `src/data/magnit.db` | База данных SQLite (в `.gitignore`) |
| `src/data/categories.json` | Корневые категории: `[{id, title}]` — источник для `load_catalog_from_json.py` и `catalog_updater.py` |
| `src/data/stores.json` | Список магазинов-эталонов: `[{store_code, store_type, city, address, full_address, name}]` |

> `categories.json` — **плоский массив** `[{id, title}]`; `load_catalog_from_json.py` читает именно этот формат (через `catalog_updater.py:load_root_categories`).
