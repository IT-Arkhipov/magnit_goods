# KODA.md — инструкция для агентов

Проект: **magnit_goods** — FastAPI-сервер мониторинга цен в магазинах «Магнит».
Сканирует каталог через публичное API magnit.ru, отслеживает изменения цен, уведомляет об акциях.

> Полная документация — в `docs/`. Критические особенности для агентов — в `AGENTS.md`.
> Этот файл — оперативная шпаргалка: команды, конвенции, красные флаги.

---

## Запуск

```bash
cd D:\pythonProjects\magnit_goods
venv\Scripts\activate
python -m uvicorn src.server.main:app --host 0.0.0.0 --port 8000 --reload
```

- Веб-интерфейс: http://localhost:8000
- Swagger UI: http://localhost:8000/docs
- БД SQLite: `src/data/magnit.db` (создаётся автоматически через `init_db()`)

Первичная установка (только при пустом `venv`):
```bash
python -m venv venv && venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium
```

## Проверка изменений

```bash
ruff check src/          # линтер — запускать перед каждым коммитом
```

Тестовый фреймворк **не настроен**. Проверка — ручная через Swagger UI или веб-интерфейс:
- `GET /api/stores` — магазины
- `GET /api/products/stats?store_code=X` — статистика
- `POST /api/catalog/scan?store_code=X` — быстрое синхронное сканирование

---

## Структура

```
src/server/
├── main.py              # Точка входа, lifespan, роуты страниц
├── database.py          # engine, SessionLocal, init_db() + 12 миграций
├── models.py            # Store, Category, Product, PriceHistory, ScanJob + store_hash_id()
├── schemas.py           # Pydantic-модели API
├── constants.py         # типы магазинов
├── scheduler.py         # APScheduler: update_prices (8:00), scan_catalog (вс 6:00)
├── routes/              # stores.py, jobs.py, catalog.py, prices.py
├── services/            # magnit_api, catalog_scanner, catalog_updater,
│                        # category_verifier, notifications, product_opener,
│                        # store_selector, load_catalog_from_json
├── utils/city_extractor.py
└── templates/           # Jinja2
```

Слои: **routes** — только HTTP; **services** — бизнес-логика, про HTTP не знают; **models** — только таблицы.

---

## 🔴 Критические особенности (не нарушать)

1. **Store IDs — строки (MD5-хэши), не int.** Path-параметры объявлять `store_id: str`.
   Создание магазина — только через `store_hash_id(store_code, store_type, full_address)` или конструктор `Store(**data)`.

2. **Порядок endpoints в FastAPI.** Статические пути ДО параметрических:
   `/products/stats`, `/products/multi-prices` → до `/products/{product_id}`;
   `/jobs/active` → до `/jobs/{job_id}`; `/stores/search` → до `/stores/{store_id}`.

3. **Rate limiting НЕ убирать.** `magnit_api.py` — 0.5s + `random.uniform(0.1, 0.5)`; `StoresAPI` — 0.3s; `catalog_updater.py` — 0.5s. Иначе бан от API Магнита.

4. **`.env` не редактировать вручную.** Обновляется только через `POST /api/stores/select` (`routes/stores.py`). `store_selector.py` его **не** трогает.

5. **Фоновые задачи создают свою `SessionLocal()`.** Сессия из `Depends(get_db)` закрыта после HTTP-ответа. Внутри `BackgroundTasks` / `threading.Thread` — новая сессия с `try/except/finally` (commit / rollback / close).

6. **Bulk-операции не заменять построчными.** `CatalogScanner._save_products()` использует `bulk_insert_mappings` / `bulk_update_mappings` (5000+ товаров).

7. **Категории универсальные** — без привязки к магазину. При `replace_all_categories()` `is_tracked` сохраняется по `magnit_id`.

8. **Знак `price_change_percent`:** `+` = цена **снизилась** (зелёная ↓), `−` = **повысилась** (фиолетовая ↑).
   Формула: `(previous_price - current_price) / previous_price * 100`.

9. **SQLite + кириллица:** `LOWER()` не работает. Поиск — в Python через `casefold()`.

10. **Очистка:** `cleanup_stale_products(days_threshold=7)` — 7 дней, не 30.

---

## Конвенции

- Комментарии, docstrings и UI-тексты — **на русском**.
- Коммиты — русский, формат `<тип>: <описание>` (пример: `фикс: исправлен тип store_id в update_store`).
- 🔴 **Коммитить только после согласования с пользователем.** Перед коммитом: `git status`, `git diff HEAD`, `git log -n 3`.
- Импорты: сначала сторонние библиотеки, затем локальные (`from src.server...`).
- Логирование: `logging.getLogger(__name__)` (часть старых модулей ещё на `print()` — не расширять).
- Комментарии добавлять редко, только когда важно объяснить *зачем*.

---

## Переменные окружения

| Переменная | Назначение |
|-----------|-----------|
| `STORE_CODE` | код активного магазина (напр. `992104`) — используется scheduler'ом |
| `STORE_TYPE` | тип магазина (`MM` по умолчанию) |
| `GOODS_URL` | API endpoint (по умолчанию `https://magnit.ru/webgate/v1/goods`) |
| `CORS_ORIGINS` | разрешённые origins (CSV), по умолчанию `*` |

Образец: `.env.example`.

---

## Известные проблемы / техдолг

Подробно: `docs/DEVELOPMENT.md` → «Технический долг».

- `load_catalog_from_json.py` ожидает `data["root_categories"]`, но `categories.json` — плоский массив `[{id, title}]`.
- `query_product.py` ссылается на удалённое поле `historical_discount_percent` — упадёт при запуске.
- `POST /api/stores` в `main.py:158` (HTMX) перекрыт роутером и недостижим.
- Производительность: 4 COUNT в `get_products_stats`, `commit()` внутри циклов — см. `docs/code_review_2026-06-12.md`.

---

## Карта документации

| Файл | О чём |
|------|-------|
| `docs/ARCHITECTURE.md` | архитектура, потоки данных, жизненный цикл |
| `docs/API.md` | справочник всех эндпоинтов |
| `docs/DATABASE.md` | модели, индексы, миграции, логика отслеживания цен |
| `docs/SERVICES.md` | сервисный слой, rate limiting, bulk, Playwright |
| `docs/DEVELOPMENT.md` | конвенции, критические особенности, типичные ошибки, техдолг |
| `docs/DEPLOYMENT.md` | env-переменные, запуск, scheduler |
| `docs/USER_GUIDE.md` | работа с веб-интерфейсом |
| `AGENTS.md` | краткая инструкция для AI-агентов |
