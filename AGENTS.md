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
├── main.py              # Точка входа, lifespan, роуты страниц, утилитарные роуты
├── database.py          # engine, SessionLocal, init_db(), 11 миграций
├── models.py            # Store, Category, Product, PriceHistory, ScanJob
├── schemas.py           # Pydantic-модели для API
├── constants.py         # STORE_TYPE_CODES, STORE_TYPE_MAP, API_STORE_TYPE_CODE
├── scheduler.py         # APScheduler (update_prices, scan_catalog)
├── routes/
│   ├── stores.py        # /api/stores — CRUD, preview, add-selected, select (11 эндпоинтов)
│   ├── jobs.py          # /api/jobs — статусы, отмена (4 эндпоинта)
│   ├── catalog.py       # /api/categories, /api/products, /api/catalog/* (22 эндпоинта)
│   └── prices.py        # /api/prices — decreased, update (2 эндпоинта)
├── services/
│   ├── magnit_api.py            # MagnitAPIClient (товары/категории), StoresAPI (магазины)
│   ├── catalog_scanner.py       # CatalogScanner — bulk-операции, история цен
│   ├── catalog_updater.py       # CatalogUpdater — полная замена каталога (is_tracked сохраняется)
│   ├── category_verifier.py     # CategoryVerifier — верификация через Playwright
│   ├── load_catalog_from_json.py # Загрузка категорий из JSON
│   ├── notifications.py         # NotificationService — формирование отчётов
│   ├── product_opener.py        # open_product_with_store — Playwright (видимый браузер)
│   └── store_selector.py        # MagnitStoreSelector — Playwright-сканер магазинов
├── utils/
│   └── city_extractor.py        # extract_city_from_address — regex-извлечение города
└── templates/                   # Jinja2 HTML
    ├── base.html, stores.html, stores_table.html, catalog.html,
    ├── products.html, jobs.html, shopping_list.html
```

Дополнительно:
- `src/data/` — `categories.json`, `stores.json`, `magnit.db` (БД, в `.gitignore`)
- `src/scripts/verify_categories.py` — standalone-скрипт верификации категорий (Playwright)

## База данных

- **SQLite**: `src/data/magnit.db` (в `.gitignore`)
- Создаётся автоматически при старте через `init_db()` (`database.py:24`)
- **Важно**: ID магазинов — строки (MD5-хэши), НЕ integers. Используй `store_hash_id()` из models.py:
  ```python
  from src.server.models import store_hash_id
  store_id = store_hash_id(store_code, store_type, full_address)  # 12 символов
  ```

## Модели

| Модель | Назначение |
|--------|-----------|
| `Store` | Магазин (id=MD5 hash, shop_type — числовой код) |
| `Category` | Категория каталога (универсальная, без привязки к магазину; parent_id иерархия) |
| `Product` | Товар (идентифицируется парой product_id+store_code; текущая цена, остатки, отслеживание цен) |
| `PriceHistory` | История цен по дням (одна запись на день для product_id+store_code) |
| `ScanJob` | Фоновое задание (status: pending/running/completed/failed/cancelled) |

Поля отслеживания цен в `Product`: `price`, `previous_price`, `price_change_percent` (+ снижение, − повышение), `last_price_change`, `last_change_price`, `last_change_date`.

> `DailyPriceSnapshot` и поля акций (`old_price`, `discount_percent`, `is_promotion`, `promo_end_date`, `historical_*`) удалены миграцией `migrate_simplify_price_tracking`.

## Миграции (выполняются при каждом старте, 11 шт.)

Подробности: `docs/DATABASE.md`. Вызываются из `init_db()` (`database.py:24`):

1. `migrate_simplify_price_tracking` — удалить поля акций, добавить `previous_price`/`price_change_percent`
2. `migrate_add_last_change_fields` — добавить `last_change_price`/`last_change_date`
3. `migrate_add_product_indexes` — составные индексы для products
4. `migrate_store_ids` — конвертация integer ID → MD5-хэши
5. `migrate_categories` — обновление структуры category table
6. `migrate_add_shop_type` — добавить поле shop_type
7. `migrate_fill_shop_type` — заполнить shop_type из store_type
8. `migrate_add_last_scan_found` — добавить поле last_scan_found
9. `migrate_add_scan_job_progress_fields` — 10 полей прогресса в scan_jobs
10. `migrate_fix_previous_price` — восстановить previous_price, испорченный старым кодом
11. `migrate_create_price_history` — создать price_history (упрощённая, по дням)

## API endpoints (актуальные пути)

> ⚠️ **Пути ниже — актуальные.** В старой версии AGENTS.md были ошибки (`/api/products/scan` → реально `/api/catalog/scan`, `/api/prices/alerts` → `/api/prices/decreased`, `/api/prices/history/{id}` → `/api/products/{id}/history`). Полный справочник: `docs/API.md`.

### Магазины (`/api/stores`, 11 эндпоинтов)
- `GET /api/stores` — список (фильтры: city, store_type, is_active)
- `POST /api/stores` — создать (JSON StoreCreate)
- `GET /api/stores/search?q=...` — поиск
- `GET /api/stores/{store_id}` — по ID (строка!)
- `PUT /api/stores/{store_id}` — обновить (store_id: str)
- `DELETE /api/stores/{store_id}` — удалить
- `POST /api/stores/select` — выбрать магазин → обновить .env
- `POST /api/stores/preview` — поиск через API Магнита без сохранения
- `POST /api/stores/add-selected` — сохранить выбранные из preview
- `POST /api/stores/delete-batch` — удалить несколько
- `GET /api/stores/by-code/{store_code}` — по store_code

### Категории (`/api/categories`, 11 эндпоинтов)
- `GET /api/categories` — список (фильтры: tracked, parent_id)
- `POST /api/categories/scan` — сканировать подкатегории из API
- `POST /api/categories/update-catalog` — аналог /scan с логированием
- `GET /api/categories/tree` — дерево категорий с children
- `POST /api/categories/load-from-json` — из categories.json
- `POST /api/categories/build-from-playwright` — алиас load-from-json
- `POST /api/categories/seed-from-playwright` — алиас
- `PUT /api/categories/{category_id}/track` — включить/выключить отслеживание
- `POST /api/categories/update-tracking` — обновить список
- `POST /api/categories/fetch-magnit-ids` — ⭐ полная замена каталога (фоновой нитью)
- `GET /api/categories/fetch-magnit-ids/status` — статус фоновой замены

### Товары (`/api/products`, 8 эндпоинтов)
- `GET /api/products` — список с фильтрами и сортировкой
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

### Цены (`/api/prices`, 2 эндпоинта)
- `GET /api/prices/decreased` — товары со сниженными ценами
- `POST /api/prices/update` — ⭐ фоновое обновление цен

### Задания (`/api/jobs`, 4 эндпоинта)
- `GET /api/jobs` — список
- `GET /api/jobs/active` — активные (ДО `/{job_id}`)
- `GET /api/jobs/{job_id}` — статус
- `POST /api/jobs/{job_id}/cancel` — отменить

### Роуты в main.py
- Веб-страницы: `/`, `/catalog`, `/products`, `/jobs`, `/shopping-list`, `/test-discount`, `/test-stores-loading`
- `GET /redirect-to-product` — редирект с установкой cookies
- `GET /open-product-in-browser` — открыть товар через Playwright (threading.Thread)

## Rate Limiting

- **MagnitAPIClient**: 0.5s + случайная пауза 0.1-0.5s (`_rate_limit_wait()` — `magnit_api.py:63`)
- **StoresAPI**: 0.3s
- **CatalogUpdater**: 0.5s
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

Запускается через `init_scheduler(store_code)` (`scheduler.py:151`):

| Job ID | Расписание | Функция |
|-------|-----------|---------|
| `update_prices` | Ежедневно 8:00 | `update_prices_job()` (`scheduler.py:21`) |
| `scan_catalog` | Воскресенье 6:00 | `scan_catalog_job()` (`scheduler.py:77`) |
| `daily_report` | Ежедневно 20:00 | **Закомментирован** (`scheduler.py:201`) |

## Критические особенности

1. **API endpoint order**: статические пути ДО параметрических. `/api/products/stats` и `/api/products/multi-prices` ДОЛЖНЫ быть определены ДО `/api/products/{product_id}`. `/api/jobs/active` — ДО `/api/jobs/{job_id}`. См. `docs/API.md`.
2. **Store IDs**: всегда строки (MD5), не integers. Path-параметры: `store_id: str`.
3. **.env**: обновляется только через `POST /api/stores/select` (`stores.py:164`) — НЕ редактировать вручную. `store_selector.py` НЕ обновляет .env (это Playwright-сканер).
4. **Фоновые задачи**: создают **свою `SessionLocal()`** внутри (FastAPI-сессия закрыта после HTTP-ответа). См. `docs/DEVELOPMENT.md`.
5. **Bulk operations**: `_save_products()` использует `bulk_insert_mappings()` / `bulk_update_mappings()` — не заменять на построчные.
6. **Очистка**: `cleanup_stale_products(days_threshold=7)` (7 дней, НЕ 30), `cleanup_price_history(days=30)`.
7. **Знак price_change_percent**: `+` = снижение (зелёная ↓), `−` = повышение (фиолетовая ↑). Формула: `(prev - current) / prev * 100`.
8. **Категории универсальные**: без привязки к магазину. При полной замене (`replace_all_categories`) флаг `is_tracked` сохраняется по `magnit_id`.
9. **SQLite + кириллица**: `LOWER()` не работает с кириллицей — поиск в Python через `casefold()`.

## Env vars

```
STORE_CODE=     # код магазина (напр. "992104") — для scheduler
STORE_TYPE=     # тип (русское название "Магнит" или API-код "MM"; по умолчанию "MM")
GOODS_URL=      # API endpoint (по умолчанию: https://magnit.ru/webgate/v1/goods)
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

## Известные расхождения / техдолг

См. `docs/DEVELOPMENT.md` → "Технический долг":
- `load_catalog_from_json.py` ожидает `data["root_categories"]`, но `categories.json` — плоский массив `[{id, title}]`
- `query_product.py` ссылается на удалённое поле `historical_discount_percent`
- Дублирование `POST /api/stores` в `main.py:158` (перекрыто роутером)
- N+1 / 4 COUNT / print(DEBUG) — см. `docs/code_review_2026-06-12.md`

---

**Работа с git**
**Важно**: все коммиты с изменениями кода обязательно подтверждать у пользователя!
