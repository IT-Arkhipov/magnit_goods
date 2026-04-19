# magnit_goods

FastAPI-сервер для мониторинга цен в магазинах "Магнит". Сканирует каталог товаров, отслеживает цены, уведомляет об акциях.

## Запуск

```bash
cd D:\pythonProjects\magnit_goods
python -m uvicorn src.server.main:app --host 0.0.0.0 --port 8000 --reload
```

- Swagger UI: http://localhost:8000/docs
- Главная: http://localhost:8000

## Архитектура

```
src/server/
├── main.py           # Точка входа, миграции при старте, роуты страниц
├── database.py       # SQLAlchemy engine, session, init_db()
├── models.py        # Store, Category, Product, PriceHistory, ScanJob, DailyPriceSnapshot
├── schemas.py      # Pydantic модели
├── scheduler.py    # APScheduler (ежедневные задания)
├── routes/
│   ├── stores.py   # /api/stores — CRUD, preview, add, select
│   ├── catalog.py # /api/categories, /api/products*, /api/products/{id}
│   ├── prices.py  # /api/prices/history, /api/prices/alerts
│   └── jobs.py    # /api/jobs — статус фоновых задач
├── services/
│   ├── magnit_api.py      # MagnitAPIClient (rate limit 0.5s)
│   ├── catalog_scanner.py # Сканирование категорий/товаров
│   ├── catalog_updater.py # Обновление каталога (replace_all)
│   ├── price_tracker.py   # Отслеживание цен, алерты
│   ├── notifications.py   # Уведомления
│   └── load_catalog_from_json.py # Загрузка корневых категорий
└── templates/     # Jinja2 HTML-шаблоны
    ├── base.html, stores.html, catalog.html, products.html, deals.html, jobs.html
```

## База данных

- ** SQLite**: `src/data/magnit.db` (в .gitignore)
- Создаётся автоматически при старте через `init_db()`
- **Важно**: ID магазинов — строки (MD5-хэши), НЕ integers. Используй `store_hash_id()` из models.py:
  ```python
  from src.server.models import store_hash_id
  store_id = store_hash_id(store_code, store_type, full_address)  # 12 символов
  ```

## Модели

| Модель | Назначение |
|--------|-----------|
| `Store` | Магазин (id=MD5 hash) |
| `Category` | Категория каталога (parent_id иерархия) |
| `Product` | Товар с текущей ценой, остатками, акциями |
| `PriceHistory` | История изменений цен |
| `DailyPriceSnapshot` | Ежедневный снимок цены |
| `ScanJob` | Фоновое задание (status: pending/running/completed/failed) |

## Миграции (выполняются при каждом старте)

- `migrate_store_ids()` — конвертирует integer ID → MD5-хэши
- `migrate_categories()` — обновляет структуру category table
- `migrate_add_shop_type()` — добавляет поле shop_type
- `migrate_fill_shop_type()` — заполняет shop_type из store_type
- `migrate_add_last_scan_found()` — добавляет поле last_scan_found

## API endpoints

### Магазины
- `GET /api/stores` — список магазинов
- `POST /api/stores` — создать магазин
- `GET /api/stores/search?q=...` — поиск
- `POST /api/stores/preview` — предпросмотр (без сохранения)
- `POST /api/stores/add-selected` — сохранить ��ыбранные
- `POST /api/stores/select` — выбрать магазин (обновляет .env)
- `DELETE /api/stores` — удалить магазины

### Категории
- `GET /api/categories` — дерево категорий
- `POST /api/categories/scan` — сканировать из API
- `PUT /api/categories/tracking` — обновить is_tracked

### Товары
- `GET /api/products?store_code=X` — список товаров
- `GET /api/products/stats?store_code=X` — статистика
- `GET /api/products/{id}` — детали товара
- `POST /api/products/scan` — сканировать товары
- `GET /api/products/multi-prices?product_ids=...&store_codes=...` — цены из нескольких магазинов

### Цены
- `GET /api/prices/history/{product_id}` — история цен
- `GET /api/prices/alerts?store_code=X` — алерты (скидки)

### Задания
- `GET /api/jobs` — список заданий
- `GET /api/jobs/{id}` — статус задания

## Rate Limiting

- **0.5s задержка** между запросами в `MagnitAPIClient`
- Реализовано через `_rate_limit_wait()` — НЕ убирать
- API Магнита заблокирует при превышении

## Веб-страницы

| URL | Описание |
|-----|----------|
| `/` | Главная (выбор магазина) |
| `/stores` | Управление магазинами |
| `/catalog` | Категории (дерево, чекбоксы) |
| `/products` | Товары с фильтрами |
| `/deals` | Акции и скидки |
| `/jobs` | Фоновые задания |

## Scheduler (APScheduler)

Запускается через `init_scheduler(store_code)`:

| Job ID | Расписание | Функция |
|-------|-----------|---------|
| `update_prices` | Ежедневно 8:00 | `update_prices_job()` |
| `scan_catalog` | Воскресенье 6:00 | `scan_catalog_job()` |
| `daily_report` | Ежедневно 20:00 | `generate_daily_report_job()` |

## Критические особенности

1. **API endpoint order**: `/api/products/stats` ДОЛЖЕН быть определён ДО `/api/products/{product_id}`
2. **Обновление каталога**: полная замена категорий из API, сохраняется `is_tracked` для совпадающих `magnit_id`
3. **.env**: автоматически обновляется через `/api/stores/select` — НЕ редактировать вручную
4. **Store IDs**: всегда строки (MD5), не integers
5. **Bulk operations**: `_save_products()` использует `bulk_insert_mappings()` / `bulk_update_mappings()`
6. **Очистка**: `cleanup_stale_products(days=30)` удаляет товары без обновлений

## Env vars

```
STORE_CODE=     # код магазина (напр. "992104")
STORE_TYPE=     # тип (напр. "Мини", "Магнит", "Экстра")
GOODS_URL=      # API endpoint (по умолчанию: https://magnit.ru/webgate/v1/goods)
```

## Язык

- Комментарии и docstrings: русский
- Коммиты: русский формат `<тип>: <описание>`
- **Коммитить только после согласования с пользователем**

## Тестирование

Ручное через Swagger UI или веб-интерфейс. Тестовый фреймворк не настроен.

## Распространённые ошибки

- Не использовать `store_hash_id()` при создании Store
- Убирать rate limiting — получить бан от API
- Забывать что категории универсальные (без привязки к конкретному магазину)
- ��арушать порядок endpoint definitions в FastAPI