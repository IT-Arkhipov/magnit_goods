# magnit_goods

FastAPI-сервер для мониторинга цен в магазинах "Магнит". Сканирует каталог товаров, отслеживает цены, уведомляет об акциях.

> 📖 **Полная документация:** в каталоге `docs/`. Этот файл — краткая инструкция для AI-агентов с критическими особенностями. Подробности:
> - `docs/ARCHITECTURE.md` — архитектура и потоки данных
> - `docs/API.md` — справочник всех эндпоинтов
> - `docs/DATABASE.md` — модели, индексы, миграции
> - `docs/SERVICES.md` — сервисный слой
> - `docs/DEVELOPMENT.md` — конвенции и техдолг
> - `docs/DEPLOYMENT.md` — запуск и конфигурация
> - `docs/USER_GUIDE.md` — использование веб-интерфейса
>
> Ссылки на код в документации — вида `файл:функция` (номера строк быстро устаревают). Меняете поведение — правьте документ в том же изменении.

## Запуск

```bash
cd D:\pythonProjects\magnit_goods
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
python -m uvicorn src.server.main:app --host 0.0.0.0 --port 8000 --reload
```

- Swagger UI: http://localhost:8000/docs
- Главная: http://localhost:8000

## Архитектура

```
src/server/
├── main.py              # Точка входа, lifespan, загрузка .env, страницы, утилитарные роуты
├── database.py          # engine (WAL), SessionLocal, init_db(), 15 миграций
├── models.py            # Store, Category, Product, PriceHistory, ScanJob, SchemaMigration
├── schemas.py           # Pydantic-модели запросов и ответов API
├── constants.py         # типы магазинов (STORE_TYPE_*, resolve_store_type_code), STALE_DAYS_*
├── scheduler.py         # APScheduler (update_prices, scan_catalog), register_jobs()
├── routes/
│   ├── stores.py        # /api/stores — CRUD, preview, add-selected, select (11 эндпоинтов)
│   ├── jobs.py          # /api/jobs — статусы, отмена (4 эндпоинта)
│   ├── catalog.py       # /api/categories (9), /api/products (8), /api/catalog/* (3) — 20 эндпоинтов
│   └── prices.py        # /api/prices — decreased, update (2 эндпоинта)
├── services/
│   ├── magnit_api.py            # MagnitAPIClient (товары/категории), StoresAPI (магазины)
│   ├── catalog_scanner.py       # CatalogScanner — bulk-операции, история цен; get_tracked_category_magnit_ids
│   ├── catalog_updater.py       # CatalogUpdater — полная замена каталога (upsert по magnit_id)
│   ├── product_query.py         # выборка товаров для API: фильтры, поиск, сортировка, статистика
│   ├── jobs.py                  # finalize_job, mark_unfinished_jobs_failed — статусы заданий
│   ├── category_verifier.py     # CategoryVerifier — верификация через Playwright
│   ├── load_catalog_from_json.py # Загрузка корневых категорий из categories.json
│   ├── notifications.py         # NotificationService — отчёты (не подключён к планировщику)
│   ├── product_opener.py        # open_product_with_store — Playwright (видимый браузер)
│   └── store_selector.py        # MagnitStoreSelector — Playwright-сканер магазинов (не подключён)
├── utils/
│   ├── city_extractor.py        # extract_city_from_address — regex-извлечение города
│   └── threads.py               # run_logged — логирование ошибок фоновых потоков
└── templates/                   # Jinja2 HTML
    ├── base.html, stores.html, stores_table.html, catalog.html,
    ├── products.html, jobs.html, shopping_list.html
```

Дополнительно:
- `src/data/` — `categories.json`, `stores.json`, `magnit.db` (БД, в `.gitignore`, рядом файлы WAL `*.db-wal`, `*.db-shm`)
- `src/scripts/verify_categories.py` — standalone-скрипт верификации категорий (Playwright)

## База данных

- **SQLite**: `src/data/magnit.db` (в `.gitignore`), режим журнала **WAL**, `busy_timeout` 30 с (`database.py:_set_sqlite_pragma`)
- Создаётся автоматически при старте через `init_db()` (`database.py:init_db`)
- **Важно**: ID магазинов — строки (MD5-хэши), НЕ integers. Используй `store_hash_id()` из models.py:
  ```python
  from src.server.models import store_hash_id
  store_id = store_hash_id(store_code, store_type, full_address)  # 12 символов
  ```
- **Магазин идентифицируется парой (`store_code`, `store_type`)** — она уникальна (`uq_store_code_type`). Один код может быть у магазинов разных типов, но `Product` ключуется только `(product_id, store_code)` — см. `docs/DEVELOPMENT.md` (техдолг №1).

## Модели

| Модель | Назначение |
|--------|-----------|
| `Store` | Магазин (id=MD5 hash, shop_type — числовой код) |
| `Category` | Категория каталога (универсальная, без привязки к магазину; parent_id иерархия) |
| `Product` | Товар (идентифицируется парой product_id+store_code; текущая цена, остатки, отслеживание цен, `name_search` для поиска) |
| `PriceHistory` | История цен по дням (одна запись на день для product_id+store_code) |
| `ScanJob` | Фоновое задание (status: pending/running/completed/failed/cancelled) |
| `SchemaMigration` | Реестр выполненных миграций (`schema_migrations`) |

Поля отслеживания цен в `Product`: `price`, `previous_price`, `price_change_percent` (+ снижение, − повышение), `last_price_change`, `last_change_price`, `last_change_date`.

> `DailyPriceSnapshot` и поля акций (`old_price`, `discount_percent`, `is_promotion`, `promo_end_date`, `historical_*`) удалены миграцией `migrate_simplify_price_tracking`.

## Миграции (реестр `schema_migrations`, 15 шт.)

Подробности: `docs/DATABASE.md`. Вызываются из `init_db()` через `_run_migration(db, "<имя>", func, ...)`.

**Контракт:** миграция выполняется **один раз** и регистрируется в `schema_migrations` **только при успехе**. Функция либо возвращается, либо бросает исключение (внутри ошибки не глушить); при сбое — `WARNING` в логе, миграция не регистрируется и повторяется при следующем старте. Новую миграцию добавляйте функцией в `database.py` и вызовом `_run_migration(...)` с уникальным именем в **конец** списка. Не запрашивайте в миграциях всю сущность (`db.query(Product)`) — колонки, добавленные позже, ещё могут отсутствовать; выбирайте нужные колонки.

Имена по порядку: `simplify_price_tracking`, `add_last_change_fields`, `add_product_indexes`, `store_ids`, `categories`, `add_shop_type`, `fill_shop_type`, `add_last_scan_found`, `add_scan_job_progress_fields`, `fix_previous_price`, `create_price_history`, `backfill_price_history`, `ensure_product_last_scan_index`, `add_store_code_type_unique`, `add_product_name_search`.

## API endpoints (актуальные пути)

> ⚠️ **Пути ниже — актуальные.** Полный справочник: `docs/API.md`.

### Магазины (`/api/stores`, 11 эндпоинтов)
- `GET /api/stores` — список (фильтры: city, store_type, is_active)
- `POST /api/stores` — создать (JSON StoreCreate); 409, если такая пара (код, тип) уже есть
- `GET /api/stores/search?q=...` — поиск
- `GET /api/stores/{store_id}` — по ID (строка!)
- `PUT /api/stores/{store_id}` — обновить; нельзя менять `store_type` и `full_address` (400)
- `DELETE /api/stores/{store_id}` — удалить
- `POST /api/stores/select` — выбрать магазин → обновить .env, окружение процесса и планировщик
- `POST /api/stores/preview` — поиск через API Магнита без сохранения (400 при неподдерживаемом типе)
- `POST /api/stores/add-selected` — сохранить выбранные из preview
- `POST /api/stores/delete-batch` — удалить несколько
- `GET /api/stores/by-code/{store_code}` — по store_code

### Категории (`/api/categories`, 9 эндпоинтов)
- `GET /api/categories` — список (фильтры: tracked, parent_id)
- `POST /api/categories/scan` — **устарел**, алиас `update-catalog`
- `POST /api/categories/update-catalog` — синхронизировать подкатегории всех корней с API (основной)
- `GET /api/categories/tree` — дерево категорий с children
- `POST /api/categories/load-from-json` — корневые категории из categories.json
- `PUT /api/categories/{category_id}/track` — включить/выключить отслеживание
- `POST /api/categories/update-tracking` — обновить список (отмечаются только подкатегории)
- `POST /api/categories/fetch-magnit-ids` — ⭐ полная замена каталога (фоновой нитью)
- `GET /api/categories/fetch-magnit-ids/status` — статус фоновой замены

### Товары (`/api/products`, 8 эндпоинтов)
- `GET /api/products` — список с фильтрами, поиском и сортировкой
- `GET /api/products/stats` — статистика (ВНИМАНИЕ: ДО `{product_id}`)
- `GET /api/products/multi-prices` — цены из нескольких магазинов (ДО `{product_id}`)
- `GET /api/products/{product_id}` — детали товара
- `GET /api/products/{product_id}/history` — история цен по дням
- `DELETE /api/products/clear` — удалить все
- `DELETE /api/products/clear-by-categories` — удалить по категориям
- `DELETE /api/products/clear-by-store` — удалить по магазину

### Сканирование (`/api/catalog`, 3 эндпоинта)
- `POST /api/catalog/scan` — синхронно сканировать товары
- `POST /api/catalog/scan-all-stores` — ⭐ фоновое сканирование всех магазинов
- `POST /api/catalog/scan-prices` — обновить цены в магазине

Эндпоинты сканирования принимают необязательный `store_type`; он **обязателен**, если у кода магазина в БД несколько типов (иначе 400).

### Цены (`/api/prices`, 2 эндпоинта)
- `GET /api/prices/decreased` — товары со сниженными ценами
- `POST /api/prices/update` — ⭐ фоновое обновление цен

### Задания (`/api/jobs`, 4 эндпоинта)
- `GET /api/jobs` — список
- `GET /api/jobs/active` — активные (ДО `/{job_id}`)
- `GET /api/jobs/{job_id}` — статус
- `POST /api/jobs/{job_id}/cancel` — отменить

### Роуты в main.py
- Веб-страницы: `/`, `/catalog`, `/products`, `/jobs`, `/shopping-list`
- `GET /redirect-to-product` — редирект с установкой cookies (только `https://magnit.ru/...`, иначе 400)
- `GET /open-product-in-browser` — открыть товар через Playwright (threading.Thread через `run_logged`; та же проверка адреса)

## Rate Limiting

- **MagnitAPIClient**: 0.5s + случайная пауза 0.1-0.5s (`MagnitAPIClient._rate_limit_wait`). Через него идут **все** запросы каталога, включая подкатегории (`fetch_category_raw`) и `CatalogUpdater`
- **StoresAPI**: 0.3s
- 🔴 **НЕ убирать** — API Магнита заблокирует

## Веб-страницы

| URL | Описание |
|-----|----------|
| `/` | Магазины (добавление, выбор, удаление) |
| `/catalog` | Категории (дерево, чекбоксы, сканирование) |
| `/products` | Товары (фильтры, 2 режима цен, сравнение по магазинам, список покупок) |
| `/shopping-list` | Список покупок (проверка наличия, экспорт) |
| `/jobs` | Фоновые задания (статусы, прогресс, отмена) |

## Scheduler (APScheduler)

Запускается через `init_scheduler(store_code)` (`scheduler.py:init_scheduler`) → `register_jobs(store_code)`. `register_jobs` безопасно вызывается повторно (`replace_existing=True`) — `POST /api/stores/select` использует его, чтобы перенацелить задания на новый магазин без перезапуска. Отслеживаемые категории задания читают в момент запуска.

| Job ID | Расписание | Функция |
|-------|-----------|---------|
| `update_prices` | Ежедневно 8:00 | `scheduler.py:update_prices_job` |
| `scan_catalog` | Воскресенье 6:00 | `scheduler.py:scan_catalog_job` |
| `daily_report` | Ежедневно 20:00 | **Закомментирован** (`register_jobs`) |

## Критические особенности

1. **API endpoint order**: статические пути ДО параметрических. `/api/products/stats` и `/api/products/multi-prices` ДОЛЖНЫ быть определены ДО `/api/products/{product_id}`. `/api/jobs/active` — ДО `/api/jobs/{job_id}`. См. `docs/API.md`.
2. **Store IDs**: всегда строки (MD5), не integers. Path-параметры: `store_id: str`.
3. **.env**: загружается при старте (`main.py`, `load_dotenv(override=False)` — переменные окружения процесса приоритетнее). Обновляется только через `POST /api/stores/select` (`stores.py:select_store`) — НЕ редактировать вручную; выбор применяется сразу: `os.environ` и задания планировщика обновляются без перезапуска. `store_selector.py` НЕ обновляет .env (это Playwright-сканер).
4. **Фоновые задачи**: создают **свою `SessionLocal()`** внутри (FastAPI-сессия закрыта после HTTP-ответа). Статус `cancelled` окончательный: итоговый статус пишите через `finalize_job` (`services/jobs.py`), а не присваиванием. См. `docs/DEVELOPMENT.md`.
5. **Bulk operations**: `_save_products()` использует `bulk_insert_mappings()` / `bulk_update_mappings()` — не заменять на построчные.
6. **Очистка**: `cleanup_stale_products(days_threshold=STALE_DAYS_DELETE)` — **6 дней** (`constants.py`: 1 день товар виден после `last_seen`, затем 5 дней скрыт, затем удаляется), `cleanup_price_history(days=30)`.
7. **Знак price_change_percent**: `+` = снижение (зелёная ↓), `−` = повышение (фиолетовая ↑). Формула: `(prev - current) / prev * 100`.
8. **Категории универсальные**: без привязки к магазину. При полной замене (`replace_all_categories`) категории обновляются по `magnit_id` (upsert) — `id` и `is_tracked` сохраняются, привязка товаров не рвётся. **Отслеживаемые** = подкатегории с `is_tracked`; единый набор — `get_tracked_category_magnit_ids()`.
9. **SQLite + кириллица**: `LOWER()` не работает с кириллицей — поиск по названию идёт по колонке `Product.name_search` (`name.casefold()`, заполняется при сохранении товара); `%`/`_` в запросе экранируются.
10. **Тип магазина в запросах к API**: только через `resolve_store_type_code()` (`constants.py`) — принимает API-код, русское название или число и отдаёт числовой код; значение по умолчанию — `DEFAULT_STORE_TYPE`. Не хардкодить коды магазинов/типов.

## Env vars

```
STORE_CODE=     # код магазина (напр. "992104") — для scheduler
STORE_TYPE=     # тип: русское название ("Магнит"), API-код ("MM") или число; по умолчанию "Магнит"
CORS_ORIGINS=   # разрешённые origins (CSV), по умолчанию "*"
```

## Язык

- Комментарии и docstrings: русский
- Коммиты: русский формат `<тип>: <описание>`
- **Коммитить только после согласования с пользователем!**

## Тестирование

Ручное через Swagger UI или веб-интерфейс. Тестовый фреймворк не настроен. Линтер: `ruff check src/`.

## Распространённые ошибки

- Не использовать `store_hash_id()` при создании Store
- Убирать rate limiting — получить бан от API
- Забывать что категории универсальные (без привязки к конкретному магазину)
- Нарушать порядок endpoint definitions в FastAPI
- Использовать `store_id: int` вместо `str` в path-параметрах
- Использовать сессию из `Depends(get_db)` внутри `BackgroundTasks` (она уже закрыта)
- Редактировать `.env` вручную вместо `POST /api/stores/select`
- Присваивать `job.status = "completed"` напрямую — затрёт отмену (использовать `finalize_job`)
- Глушить ошибки внутри миграции — она зарегистрируется как выполненная

## Известные расхождения / техдолг

См. `docs/DEVELOPMENT.md` → "Технический долг":
- Ключ товара `(product_id, store_code)` не включает тип магазина (техдолг №1)
- `NotificationService` и `store_selector.py` не подключены (см. `docs/DEVELOPMENT.md`)
- `print` остался только в Playwright-модулях (`store_selector.py`, `category_verifier.py`, `scripts/verify_categories.py`)
- Остальное — см. `docs/DEVELOPMENT.md` (раздел «Замечания из code review»)

---

**Работа с git**
**Важно**: все коммиты с изменениями кода обязательно подтверждать у пользователя!
