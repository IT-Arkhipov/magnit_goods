# Архитектура

FastAPI-сервер для мониторинга цен в магазинах «Магнит». Сканирует каталог товаров через публичное API magnit.ru, отслеживает изменения цен, уведомляет об акциях.

## Технологический стек

| Слой | Технология |
|------|-----------|
| Web-фреймворк | FastAPI + Starlette |
| ASGI-сервер | Uvicorn |
| ORM | SQLAlchemy 2.x |
| Валидация | Pydantic 2.x |
| БД | SQLite (`src/data/magnit.db`) |
| Шаблоны | Jinja2 |
| Scheduler | APScheduler (BackgroundScheduler) |
| HTTP-клиент | requests |
| Браузерная автоматизация | Playwright (sync API) |
| .env | python-dotenv |

---

## Дерево модулей

```
magnit_goods/
├── src/
│   ├── __init__.py
│   ├── data/                          # Данные (в .gitignore — БД)
│   │   ├── categories.json            # Корневые категории: [{id, title}]
│   │   ├── stores.json                # Эталонные магазины
│   │   └── magnit.db                  # SQLite БД (в .gitignore; рядом файлы WAL *.db-wal, *.db-shm)
│   ├── scripts/
│   │   └── verify_categories.py       # Standalone-скрипт верификации категорий (Playwright)
│   └── server/                        # Основной пакет
│       ├── __init__.py
│       ├── main.py                    # Точка входа, загрузка .env, lifespan, страницы, утилитарные роуты
│       ├── database.py                # engine (WAL), SessionLocal, init_db(), 15 миграций
│       ├── models.py                  # Store, Category, Product, PriceHistory, ScanJob, SchemaMigration
│       ├── schemas.py                 # Pydantic-модели запросов и ответов API
│       ├── constants.py               # типы магазинов (STORE_TYPE_*, resolve_store_type_code), STALE_DAYS_*
│       ├── scheduler.py               # APScheduler: update_prices, scan_catalog; register_jobs()
│       ├── routes/
│       │   ├── __init__.py
│       │   ├── stores.py              # /api/stores — CRUD, preview, add-selected, select
│       │   ├── jobs.py                # /api/jobs — статусы, отмена
│       │   ├── catalog.py             # /api/categories, /api/products, /api/catalog/*
│       │   └── prices.py              # /api/prices — decreased, update
│       ├── services/
│       │   ├── __init__.py
│       │   ├── magnit_api.py          # MagnitAPIClient (товары/категории), StoresAPI (магазины)
│       │   ├── catalog_scanner.py     # CatalogScanner — bulk-операции, история цен; get_tracked_category_magnit_ids
│       │   ├── product_query.py       # Выборка товаров для API: фильтры, поиск, сортировка, статистика
│       │   ├── jobs.py                # finalize_job, mark_unfinished_jobs_failed — статусы заданий
│       │   ├── catalog_updater.py     # CatalogUpdater — полная замена каталога (upsert по magnit_id: id и is_tracked сохраняются)
│       │   ├── category_verifier.py   # CategoryVerifier — верификация через Playwright
│       │   ├── load_catalog_from_json.py  # Загрузка корневых категорий из categories.json
│       │   ├── notifications.py       # NotificationService — отчёты (не подключён к планировщику)
│       │   ├── product_opener.py      # open_product_with_store — Playwright (видимый браузер)
│       │   └── store_selector.py      # MagnitStoreSelector — Playwright-сканер магазинов (не подключён)
│       ├── utils/
│       │   ├── __init__.py
│       │   ├── city_extractor.py      # extract_city_from_address — regex-извлечение города
│       │   └── threads.py             # run_logged — логирование ошибок фоновых потоков
│       └── templates/                 # Jinja2 HTML
│           ├── base.html              # Базовый шаблон (навигация)
│           ├── stores.html            # Главная — управление магазинами
│           ├── stores_table.html      # HTMX-фрагмент таблицы магазинов
│           ├── catalog.html           # Категории (дерево, чекбоксы)
│           ├── products.html          # Товары с фильтрами, 2 режима цен
│           ├── jobs.html              # Фоновые задания
│           └── shopping_list.html     # Список покупок
├── docs/                              # Документация (этот каталог)
├── requirements.txt                   # Зависимости
├── .env / .env.example                # Конфигурация (в .gitignore)
├── .gitignore
├── AGENTS.md                          # Инструкция для AI-агентов
└── README.md                          # Точка входа в документацию
```

Подробное описание:
- `routes/` → `docs/API.md`
- `services/` → `docs/SERVICES.md`
- Модели и БД → `docs/DATABASE.md`

---

## Жизненный цикл приложения

Определён в `main.py` через `@asynccontextmanager lifespan(app)`. Файл `.env` загружается при импорте `main.py` (`load_dotenv(override=False)`: переменные окружения процесса приоритетнее) — до чтения `STORE_CODE`/`CORS_ORIGINS`.

```
┌─────────────────────────────────────────────────────────────┐
│ STARTUP (lifespan)                                          │
│                                                             │
│  1. init_db()                       (database.py)           │
│     ├─ Base.metadata.create_all()   — создать таблицы       │
│     └─ 15 миграций — реестр schema_migrations,              │
│        регистрация только при успехе (docs/DATABASE.md)     │
│                                                             │
│  2. mark_unfinished_jobs_failed()   (services/jobs.py)      │
│     └─ Все ScanJob со статусом "pending"/"running" → "failed"│
│        (процесс был остановлен, задание потеряно)           │
│                                                             │
│  3. init_scheduler(store_code)      (scheduler.py)          │
│     └─ Если задан STORE_CODE → register_jobs():             │
│        ├─ update_prices  — ежедневно 8:00                   │
│        └─ scan_catalog   — воскресенье 6:00                 │
│           (daily_report закомментирован)                    │
│                                                             │
│  yield  ← приложение обрабатывает запросы                   │
│                                                             │
│ SHUTDOWN                                                     │
│  4. shutdown_scheduler()            (scheduler.py)          │
└─────────────────────────────────────────────────────────────┘
```

### Регистрация роутеров
В `main.py`:
```python
app.include_router(stores.router)     # /api/stores
app.include_router(jobs.router)       # /api/jobs
app.include_router(catalog.router)    # /api
app.include_router(prices.router)     # /api/prices
```
Порядок include влияет на приоритет при совпадении путей; порядок объявления эндпоинтов внутри роутеров критичен — см. `docs/API.md`.

### Настройка
- Логирование: `logging.basicConfig(level=INFO)` (`main.py`).
- CORS: `allow_origins` из env `CORS_ORIGINS` (по умолчанию `*`), `allow_methods=["*"]`, `allow_headers=["*"]` (`main.py`).
- Шаблоны: `Jinja2Templates(directory=src/server/templates)` (`main.py`).

---

## Потоки данных

### 1. Сканирование товаров (основной поток)

```
Пользователь (UI / Swagger)
        │
        │  POST /api/catalog/scan?store_code=X[&store_type=...]
        ▼
routes/catalog.py:scan_products
        │  тип магазина: явный → единственный в БД для кода → из конфигурации;
        │  код у нескольких типов без store_type → 400
        │  создаёт CatalogScanner(db, store_code, store_type)
        ▼
CatalogScanner.scan_products()        (services/catalog_scanner.py)
        │
        │  категории: переданные ИЛИ отслеживаемые подкатегории
        │  (get_tracked_category_magnit_ids); для каждой категории:
        │  проверка отмены (_is_cancelled — чтение колонки status)
        ▼
MagnitAPIClient.search(category_ids=[magnit_id], limit, offset)
        │                             (services/magnit_api.py)
        │  rate_limit 0.5s + random 0.1-0.5s
        │  POST https://magnit.ru/webgate/v2/goods/search
        │  storeType — числовой код (resolve_store_type_code)
        │  retry: до 3 попыток, пауза 2 и 4 сек между ними
        ▼
_parse_product() — цена из копеек в рубли (/100); товар без цены пропускается
        │
        ▼
CatalogScanner._save_products()       (catalog_scanner.py)
        │  ┌─ 1 SELECT существующих товаров по (product_id IN, store_code)
        │  ├─ 1 SELECT истории цен предыдущего дня
        │  ├─ bulk_insert_mappings(Product, to_insert)   (+ name_search)
        │  ├─ bulk_update_mappings(Product, to_update)
        │  ├─ _upsert_price_history() — одна запись на день
        │  └─ 1 COMMIT
        ▼
после всех категорий (один раз за вызов):
_mark_missing_products() + cleanup_stale_products(6 дней) + cleanup_price_history(30 дней)
        │
        ▼
Фоновые запуски (scan-all-stores, prices/update, scheduler) — прогресс в ScanJob
(запись не чаще 2 с, итог — services/jobs.py:finalize_job)
```

### 2. Поиск и добавление магазинов

```
Пользователь вводит город/улицу
        │
        │  POST /api/stores/preview  (ScanStoresRequest)
        ▼
routes/stores.py:preview_stores
        │
        ▼
StoresAPI.search_stores(query, store_types)  (magnit_api.py)
        │  rate_limit 0.3s
        │  один запрос со всеми выбранными типами:
        │  POST https://magnit.ru/webgate/v1/stores-facade/search/detail
        ▼
extract_city_from_address()  [utils/city_extractor.py]
        │  regex: ", г Город" / ", г. Город" / обратные формы / сёла
        ▼
{total_found, stores: [StorePreviewItem с exists_in_db]}
        │
        │  пользователь выбирает → POST /api/stores/add-selected
        ▼
add_selected_stores()  →  Store(id=store_hash_id(...), shop_type=STORE_TYPE_CODES[...])
        │  дубликат — только пара (store_code, store_type)
        │
        ▼
POST /api/stores/select  →  .env + os.environ (STORE_CODE, STORE_TYPE)
        └─ scheduler.register_jobs(store_code) — задания переезжают на новый магазин без перезапуска
```

### 3. Полная замена каталога (фоновой нитью)

```
POST /api/categories/fetch-magnit-ids
        │
        │  threading.Thread(daemon=True)
        ▼
_fetch_and_update_categories_background()  (routes/catalog.py, через run_logged)
        │  под _catalog_update_lock:
        │  _catalog_update_status["in_progress"] = True
        ▼
CatalogUpdater.replace_all_categories()    (services/catalog_updater.py)
        │  1. Загрузить корневые из categories.json
        │  2. Собрать все категории из API (корневые + подкатегории)
        │  3. При ошибках API → откат, БД не меняется
        │  4. Upsert по magnit_id: корневые (flush) → подкатегории (parent_id);
        │     id и is_tracked существующих категорий сохраняются
        │  5. Удалить категории, которых нет в API (товары удалённых → category_id=NULL)
        ▼
_catalog_update_status (в памяти процесса, не ScanJob): in_progress=False, {total, processed, updated, errors}
        │
        │  клиент опрашивает:
        │  GET /api/categories/fetch-magnit-ids/status
```

### 4. Scheduler (автоматические задания)

```
init_scheduler(store_code)  (scheduler.py)  →  register_jobs(store_code)
        │   повторный вызов безопасен (replace_existing=True): его же вызывает
        │   POST /api/stores/select при смене магазина
        │
        ├─ CronTrigger(hour=8, minute=0) → update_prices_job(store_code)
        │       │
        │       └─ CatalogScanner.scan_products(tracked_only=True)
        │              → ScanJob(job_type="prices"); отслеживаемые категории
        │                читаются в момент запуска
        │
        └─ CronTrigger(day_of_week="sun", hour=6, minute=0) → scan_catalog_job(store_code)
                ├─ scan_categories()  → ScanJob(job_type="catalog")
                └─ scan_products(tracked_only=True)  → ScanJob(job_type="prices")

        Тип магазина — из STORE_TYPE (его выставляет /api/stores/select);
        если у кода несколько типов и STORE_TYPE не задан — задание завершается failed.
        (daily_report в 20:00 — закомментирован в register_jobs)
```

---

## Фоновые задачи и потоки

Два механизма запуска долгих операций:

| Механизм | Где используется | Сессия БД |
|----------|-----------------|-----------|
| `BackgroundTasks` (FastAPI) | `scan-all-stores`, `prices/update` | Создаёт **новую `SessionLocal()`** внутри (FastAPI-сессия уже закрыта) |
| `threading.Thread` (daemon) через `utils/threads.py:run_logged` | `fetch-magnit-ids`, `open-product-in-browser` | Создаёт свою `SessionLocal()` или не работает с БД; ошибки потока пишутся в лог с traceback |

> 🔴 **Критично:** никогда не используйте сессию из `Depends(get_db)` внутри фоновой задачи — она закрывается после отправки HTTP-ответа. Всегда создавайте новую `SessionLocal()` и закрывайте в `finally`.

### Проверка отмены
Сканер проверяет статус задания перед каждой категорией и каждым запросом страницы: `CatalogScanner._is_cancelled()` читает одну колонку `ScanJob.status` (без загрузки сущности и `expire_all()`; предварительный `commit()` завершает транзакцию, чтобы в режиме WAL увидеть отмену из другой сессии). `scan-all-stores` дополнительно проверяет статус между магазинами. Отмена инициируется через `POST /api/jobs/{job_id}/cancel`.

Статус `cancelled` окончательный: итоговый статус фоновых заданий пишет `services/jobs.py:finalize_job`, который перечитывает задание и не перезаписывает отмену.

### Конкурентный доступ к БД
SQLite работает в режиме WAL с `busy_timeout` 30 с (`database.py:_set_sqlite_pragma`): чтение из HTTP-запросов не блокируется записью сканера, а конкурирующая запись ждёт освобождения блокировки, а не падает с `database is locked`.

### Глобальное состояние
- `_catalog_update_status` + `_catalog_update_lock` (`threading.Lock`) в `routes/catalog.py` — статус фоновой замены каталога; хранится **в памяти процесса** (не в `ScanJob`) и сбрасывается при перезапуске.

---

## Слои и ответственности

```
┌──────────────────────────────────────────────────────────┐
│ HTTP-роуты (routes/)                                     │
│  Валидация, парсинг параметров, вызов сервисов, ответ    │
│  Фоновые задачи (BackgroundTasks, threading)             │
└──────────────────────────────┬───────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────┐
│ Сервисы (services/)                                      │
│  Бизнес-логика: API-клиенты, сканеры, bulk-операции      │
│  Playwright-автоматизация, формирование уведомлений      │
└──────────────────────────────┬───────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────┐
│ Модели (models.py) + БД (database.py)                    │
│  SQLAlchemy ORM, миграции, сессии                        │
└──────────────────────────────────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────┐
│ Внешние системы                                          │
│  magnit.ru API (goods/search, stores-facade)             │
│  magnit.ru браузер (Playwright)                          │
└──────────────────────────────────────────────────────────┘
```

### Что где НЕ живёт
- **Роуты** не содержат бизнес-логики сканирования и выборки — только разбор параметров, вызов сервисов (`product_query`, `CatalogScanner`, ...) и форматирование ответа.
- **Сервисы** не знают про HTTP — работают с `Session` и внешними API.
- **Модели** не содержат логики — только описание таблиц и `store_hash_id()`.
- **`.env`** обновляется только через `POST /api/stores/select` (`routes/stores.py`), не вручную и не в `store_selector.py`.

---

## Связанные документы

- `docs/API.md` — все эндпоинты с параметрами
- `docs/DATABASE.md` — модели, индексы, миграции, логика цен
- `docs/SERVICES.md` — детальное описание сервисов
- `docs/DEPLOYMENT.md` — запуск, env, scheduler
- `docs/DEVELOPMENT.md` — конвенции, критические особенности
- `docs/USER_GUIDE.md` — использование веб-интерфейса
- `docs/scan_jobs.md` — зачем нужны статусы заданий
- `docs/code_review_2026-06-12.md` — отчёт ревью с проблемами производительности
