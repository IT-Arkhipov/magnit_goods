# База данных

СУБД: **SQLite**. Файл: `src/data/magnit.db` (в `.gitignore`).

Создаётся автоматически при старте через `init_db()` (`src/server/database.py:24`), которая вызывает `Base.metadata.create_all(bind=engine)` и затем выполняет миграции.

Engine и сессия:
- `engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})` — `database.py:10`
- `SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)` — `database.py:11`
- `get_db()` (`database.py:15`) — FastAPI-dependency: открывает сессию, отдаёт через `yield`, закрывает в `finally`.

> ⚠️ **Важно:** `check_same_thread=False` позволяет использовать один engine из разных потоков (фоновые задачи, scheduler). При этом каждая задача обязана создавать **свою** `SessionLocal()` — не переиспользовать сессию из FastAPI-dependency (она закрывается после HTTP-ответа).

---

## Модели (`src/server/models.py`)

### 1. `Store` — магазин Магнит (`models.py:28`)

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

**Генерация ID:** функция `store_hash_id(store_code, store_type, full_address)` (`models.py:22`) — `hashlib.md5(f"{code}|{type}|{addr}").hexdigest()[:12]`.

Конструктор `Store.__init__` (`models.py:46`) автоматически:
- вычисляет `id` через `store_hash_id`, если не передан явно;
- проставляет `shop_type` из `STORE_TYPE_CODES` по `store_type`, если не передан.

> 🔴 **Критично:** ID магазинов — **строки** (MD5-хэши), НЕ integers. FastAPI path-параметры для магазинов должны объявляться как `store_id: str`. Использовать `store_hash_id()` при ручном создании `Store`.

### 2. `Category` — категория каталога (`models.py:54`)

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

Связь: `children = relationship("Category", backref="parent", remote_side=[id])` — `models.py:70`. В БД хранится только `parent_id`; отношение `children` — ORM-удобство, **не использовать** для рекурсивных запросов (порождает N+1, см. `docs/code_review_2026-06-12.md`).

### 3. `Product` — товар, текущее состояние (`models.py:76`)

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

**Отслеживание цен:**
| Поле | Тип | Описание |
|------|-----|----------|
| `previous_price` | `Float` nullable | Цена из **предыдущего сканирования** |
| `price_change_percent` | `Float` index nullable | Процент изменения: **+** снижение, **−** повышение |
| `last_change_price` | `Float` nullable | Цена **до последнего реального изменения** |
| `last_change_date` | `DateTime` nullable | Дата последнего реального изменения |

> Семантика `previous_price` и `last_change_price` различается — см. раздел [Логика цен](#логика-цен) ниже.

**Индексы и ограничения** (`__table_args__`, `models.py:80`):
| Имя | Тип | Колонки |
|-----|-----|---------|
| `uq_product_store` | UNIQUE | `(product_id, store_code)` |
| `ix_product_store_lookup` | INDEX | `(product_id, store_code)` |
| `ix_product_price_change` | INDEX | `(store_code, price_change_percent)` |
| `ix_product_last_scan` | INDEX | `(store_code, last_scan_found)` |

Составной индекс `(product_id, store_code)` ускоряет `bulk_update_mappings` и выборки «свежих» товаров по магазину.

### 4. `PriceHistory` — история цен по дням (`models.py:138`)

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

**Индексы и ограничения** (`models.py:142`):
| Имя | Тип | Колонки |
|-----|-----|---------|
| `uq_price_history_day` | UNIQUE | `(product_id, store_code, scan_date)` |
| `ix_price_history_lookup` | INDEX | `(product_id, store_code, scan_date)` |

Хранение: retention **30 дней** (`PRICE_HISTORY_RETENTION_DAYS` в `catalog_scanner.py:24`). Очистка — `CatalogScanner.cleanup_price_history()` (`catalog_scanner.py:730`).

> **История изменений модели:** ранее в проекте была отдельная таблица `DailyPriceSnapshot` и поля акций (`old_price`, `discount_percent`, `is_promotion`, `promo_end_date`, `historical_*`). Они удалены миграцией `migrate_simplify_price_tracking` (см. `PLAN_SIMPLIFY_PRICE_TRACKING.md`). Затем `PriceHistory` была **восстановлена** миграцией `migrate_create_price_history` для по-дневной истории.

### 5. `ScanJob` — задание на сканирование (`models.py:157`)

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

Проект поддерживает **два режима отображения** изменения цен (чекбокс «Новая цена» в UI, см. `PLAN_TWO_PRICE_MODES.md`):

| Поле | Обновляется | Что хранит |
|------|-------------|-----------|
| `previous_price` | **при каждом сканировании** | Цену из **предыдущего скана** (даже если цена не изменилась) |
| `last_change_price` | **только при реальном изменении** цены (`abs(diff) > 0.01`) | Цену **до последнего реального изменения** |
| `price_change_percent` | при каждом скане (из `PriceHistory` предыдущего дня) | `round((prev - current) / prev * 100, 1)` |
| `last_change_date` | только при реальном изменении | Дату последнего реального изменения |

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

- `CatalogScanner._save_products()` (`catalog_scanner.py:435`) — bulk INSERT/UPDATE, расчёт `price_change_percent` из последней записи `PriceHistory` **предыдущего дня** (`scan_date < today`).
- `CatalogScanner._upsert_price_history()` (`catalog_scanner.py:656`) — upsert записи за сегодня (одна на день).
- `last_change_price`/`last_change_date` обновляются только при `abs(existing.last_change_price - current_price) > 0.01`.

---

## Миграции (`src/server/database.py`)

Все миграции вызываются из `init_db()` (`database.py:24`) **при каждом старте**. Идемпотентны — проверяют состояние и пропускают, если уже выполнены.

| # | Функция | Строка | Назначение |
|---|---------|--------|-----------|
| 1 | `migrate_simplify_price_tracking` | `database.py:48` | Упрощение отслеживания цен: добавить `previous_price`/`price_change_percent`, удалить поля акций (`old_price`, `discount_percent`, `is_promotion`, `promo_end_date`, `historical_*`, `is_price_increase`), удалить таблицы `price_history`/`daily_price_snapshot` |
| 2 | `migrate_add_last_change_fields` | `database.py:112` | Добавить `last_change_price`/`last_change_date`, заполнить из существующих `previous_price`/`last_price_change` |
| 3 | `migrate_add_product_indexes` | `database.py:153` | Создать составные индексы `uq_product_store`, `ix_product_price_change`, `ix_product_last_scan` |
| 4 | `migrate_store_ids` | `database.py:194` | Конвертация integer ID магазинов → MD5-хэши (однократно, по типу колонки) |
| 5 | `migrate_categories` | `database.py:251` | Обновление структуры `categories`: добавить `code`/`url`/`parent_id`, убрать `category_id`/`store_code` |
| 6 | `migrate_add_shop_type` | `database.py:286` | Добавить поле `shop_type` в `stores` |
| 7 | `migrate_fill_shop_type` | `database.py:299` | Заполнить `shop_type` из `store_type` через `STORE_TYPE_CODES` |
| 8 | `migrate_add_last_scan_found` | `database.py:329` | Добавить поле `last_scan_found` в `products` |
| 9 | `migrate_add_scan_job_progress_fields` | `database.py:342` | Добавить 10 полей прогресса в `scan_jobs` |
| 10 | `migrate_fix_previous_price` | `database.py:369` | Восстановить `previous_price`, испорченный старым кодом (он копировал `price` при каждом скане). Источник: `last_change_price`, формула `price * 100 / (100 - price_change_percent)` |
| 11 | `migrate_create_price_history` | `database.py:416` | Создать таблицу `price_history` и заполнить начальными данными за сегодня из `products` |

> **Порядок вызова** в `init_db()`: 1→2→3→4→5→6→7→8→9→10→11. Миграции 1 и 11 связаны: первая удаляет старую `price_history`, последняя создаёт новую с упрощённой структурой.

---

## Очистка данных

| Метод | Файл:строка | Что удаляет | Порог |
|-------|------------|-------------|-------|
| `CatalogScanner.cleanup_stale_products(days_threshold=7)` | `catalog_scanner.py:707` | Товары с `last_seen < now - 7 дней` для текущего `store_code` | **7 дней** |
| `CatalogScanner.cleanup_price_history(days=30)` | `catalog_scanner.py:730` | Записи `PriceHistory` старше 30 дней | 30 дней (`PRICE_HISTORY_RETENTION_DAYS`) |

> ⚠️ В `AGENTS.md` ранее указывалось 30 дней для `cleanup_stale_products` — фактически в коде **7 дней**. Вызывается автоматически в конце `scan_products()` (`catalog_scanner.py:414`).

---

## Файлы данных

| Файл | Назначение |
|------|-----------|
| `src/data/magnit.db` | База данных SQLite (в `.gitignore`) |
| `src/data/categories.json` | Корневые категории: `[{id, title}]` — источник для `load_catalog_from_json.py` и `catalog_updater.py` |
| `src/data/stores.json` | Список магазинов-эталонов: `[{store_code, store_type, city, address, full_address, name}]` |

> ⚠️ **Расхождение:** `load_catalog_from_json.py:52` читает `data["root_categories"]`, но фактический `categories.json` — **плоский массив** `[{id, title}]` (без ключа `root_categories`). Это потенциальный баг — отмечен в `docs/DEVELOPMENT.md` как техдолг.
