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
│   │   └── magnit.db                  # SQLite БД (в .gitignore)
│   ├── scripts/
│   │   └── verify_categories.py       # Standalone-скрипт верификации категорий (Playwright)
│   └── server/                        # Основной пакет
│       ├── __init__.py
│       ├── main.py                    # Точка входа, lifespan, роуты страниц, утилитарные роуты
│       ├── database.py                # engine, SessionLocal, init_db(), 11 миграций
│       ├── models.py                  # Store, Category, Product, PriceHistory, ScanJob
│       ├── schemas.py                 # Pydantic-модели для API
│       ├── constants.py               # STORE_TYPE_CODES, STORE_TYPE_MAP, API_STORE_TYPE_CODE
│       ├── scheduler.py               # APScheduler: update_prices, scan_catalog
│       ├── routes/
│       │   ├── __init__.py
│       │   ├── stores.py              # /api/stores — CRUD, preview, add-selected, select
│       │   ├── jobs.py                # /api/jobs — статусы, отмена
│       │   ├── catalog.py             # /api/categories, /api/products, /api/catalog/*
│       │   └── prices.py              # /api/prices — decreased, update
│       ├── services/
│       │   ├── __init__.py
│       │   ├── magnit_api.py          # MagnitAPIClient (товары/категории), StoresAPI (магазины)
│       │   ├── catalog_scanner.py     # CatalogScanner — bulk-операции, история цен
│       │   ├── catalog_updater.py     # CatalogUpdater — полная замена каталога (is_tracked сохраняется)
│       │   ├── category_verifier.py   # CategoryVerifier — верификация через Playwright
│       │   ├── load_catalog_from_json.py  # Загрузка категорий из JSON
│       │   ├── notifications.py       # NotificationService — формирование отчётов/уведомлений
│       │   ├── product_opener.py      # open_product_with_store — Playwright (видимый браузер)
│       │   └── store_selector.py      # MagnitStoreSelector — Playwright-сканер магазинов
│       ├── utils/
│       │   ├── __init__.py
│       │   └── city_extractor.py      # extract_city_from_address — regex-извлечение города
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

Определён в `main.py:26` через `@asynccontextmanager lifespan(app)`.

```
┌─────────────────────────────────────────────────────────────┐
│ STARTUP (lifespan)                                          │
│                                                             │
│  1. init_db()                       [database.py:24]        │
│     ├─ Base.metadata.create_all()   — создать таблицы       │
│     └─ 11 миграций (идемпотентные)  — см. docs/DATABASE.md  │
│                                                             │
│  2. _mark_all_running_failed_on_startup()  [stores.py:39]   │
│     └─ Все ScanJob со статусом "running" → "failed"         │
│        (процесс был убит, задание зависло)                  │
│                                                             │
│  3. init_scheduler(store_code)      [scheduler.py:151]      │
│     └─ Если в .env есть STORE_CODE:                         │
│        ├─ update_prices  — ежедневно 8:00                   │
│        └─ scan_catalog   — воскресенье 6:00                 │
│           (daily_report закомментирован)                    │
│                                                             │
│  yield  ← приложение обрабатывает запросы                   │
│                                                             │
│ SHUTDOWN                                                     │
│  4. shutdown_scheduler()            [scheduler.py:214]      │
└─────────────────────────────────────────────────────────────┘
```

### Регистрация роутеров
В `main.py:81-84`:
```python
app.include_router(stores.router)     # /api/stores
app.include_router(jobs.router)       # /api/jobs
app.include_router(catalog.router)    # /api
app.include_router(prices.router)     # /api/prices
```
Порядок include влияет на приоритет при совпадении путей (см. заметку про `POST /api/stores` в `docs/API.md`).

### Настройка
- Логирование: `logging.basicConfig(level=INFO)` (`main.py:20`).
- CORS: `allow_origins` из env `CORS_ORIGINS` (по умолчанию `*`), `allow_methods=["*"]`, `allow_headers=["*"]` (`main.py:59-66`).
- Шаблоны: `Jinja2Templates(directory=src/server/templates)` (`main.py:70`).

---

## Потоки данных

### 1. Сканирование товаров (основной поток)

```
Пользователь (UI / Swagger)
        │
        │  POST /api/catalog/scan?store_code=X
        ▼
routes/catalog.py:scan_products
        │
        │  создаёт CatalogScanner(db, store_code, job_id?)
        ▼
CatalogScanner.scan_products()        [services/catalog_scanner.py:213]
        │
        │  для каждой отслеживаемой категории:
        ▼
MagnitAPIClient.search(category_ids=[magnit_id], limit, offset)
        │                             [services/magnit_api.py:73]
        │  rate_limit 0.5s + random 0.1-0.5s
        │  POST https://magnit.ru/webgate/v2/goods/search
        │  retry: 3 попытки, backoff 2/4/8 сек
        ▼
_parse_product() — цена из копеек в рубли (/100)
        │
        ▼
CatalogScanner._save_products()       [catalog_scanner.py:435]
        │  ┌─ 1 SELECT существующих товаров по (product_id IN, store_code)
        │  ├─ 1 SELECT истории цен предыдущего дня
        │  ├─ bulk_insert_mappings(Product, to_insert)
        │  ├─ bulk_update_mappings(Product, to_update)
        │  ├─ _upsert_price_history() — одна запись на день
        │  └─ 1 COMMIT
        ▼
cleanup_stale_products(7 дней) + cleanup_price_history(30 дней)
        │
        ▼
Обновление ScanJob: progress, items_scanned/added/updated
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
StoresAPI.search_stores(query, store_types)  [magnit_api.py:369]
        │  rate_limit 0.3s
        │  для каждого типа магазина — отдельный запрос:
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
        │
        ▼
POST /api/stores/select  →  обновление .env (STORE_CODE, STORE_TYPE)
```

### 3. Полная замена каталога (фоновой нитью)

```
POST /api/categories/fetch-magnit-ids
        │
        │  threading.Thread(daemon=True)
        ▼
_fetch_and_update_categories_background()  [catalog.py:785]
        │  под _catalog_update_lock:
        │  _catalog_update_status["in_progress"] = True
        ▼
CatalogUpdater.replace_all_categories()    [catalog_updater.py:228]
        │  1. Загрузить корневые из categories.json
        │  2. Собрать все категории из API (корневые + подкатегории)
        │  3. При ошибках API → откат, БД не меняется
        │  4. Сохранить old_tracked_status = {magnit_id: is_tracked}
        │  5. db.query(Category).delete()  — полная очистка
        │  6. Вставить корневые (flush) → подкатегории (parent_id)
        │     is_tracked восстанавливается из old_tracked_status
        ▼
_catalog_update_status: in_progress=False, {total, processed, updated, errors}
        │
        │  клиент опрашивает:
        │  GET /api/categories/fetch-magnit-ids/status
```

### 4. Scheduler (автоматические задания)

```
init_scheduler(store_code)  [scheduler.py:151]
        │
        ├─ CronTrigger(hour=8, minute=0) → update_prices_job(store_code, category_ids)
        │       │
        │       └─ CatalogScanner.scan_products(tracked_only=True)
        │              → создаёт ScanJob(job_type="prices")
        │
        └─ CronTrigger(day_of_week="sun", hour=6, minute=0) → scan_catalog_job(store_code)
                ├─ scan_categories()  → ScanJob(job_type="catalog")
                └─ scan_products(tracked_only=True)  → ScanJob(job_type="prices")

        (daily_report в 20:00 — закомментирован, scheduler.py:201)
```

---

## Фоновые задачи и потоки

Два механизма запуска долгих операций:

| Механизм | Где используется | Сессия БД |
|----------|-----------------|-----------|
| `BackgroundTasks` (FastAPI) | `scan-all-stores`, `prices/update` | Создаёт **новую `SessionLocal()`** внутри (FastAPI-сессия уже закрыта) |
| `threading.Thread` (daemon) | `fetch-magnit-ids`, `open-product-in-browser` | Создаёт свою `SessionLocal()` или не работает с БД |

> 🔴 **Критично:** никогда не используйте сессию из `Depends(get_db)` внутри фоновой задачи — она закрывается после отправки HTTP-ответа. Всегда создавайте новую `SessionLocal()` и закрывайте в `finally`.

### Проверка отмены
Фоновые сканирования (`scan-all-stores`, `prices/update`) проверяют `ScanJob.status == "cancelled"` перед каждой итерацией. Отмена инициируется через `POST /api/jobs/{job_id}/cancel`. В `CatalogScanner.scan_products()` перед проверкой вызывается `self.db.expire_all()` для сброса кэша сессии.

### Глобальное состояние
- `_catalog_update_status` (`catalog.py:774`) + `_catalog_update_lock` (`catalog.py:782`, `threading.Lock`) — статус фоновой замены каталога.

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
- **Роуты** не содержат бизнес-логики сканирования — только валидацию, вызов сервисов, форматирование ответа.
- **Сервисы** не знают про HTTP — работают с `Session` и внешними API.
- **Модели** не содержат логики — только описание таблиц и `store_hash_id()`.
- **`.env`** обновляется только через `POST /api/stores/select` (`routes/stores.py:164`), не вручную и не в `store_selector.py`.

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
