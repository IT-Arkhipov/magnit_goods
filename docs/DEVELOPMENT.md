# Разработка

## Конвенции

### Язык
- **Комментарии и docstrings:** русский.
- **Коммиты:** русский формат `<тип>: <описание>`. Примеры: `фича: добавлен endpoint /api/prices/decreased`, `фикс: исправлен тип store_id в update_store`.
- **UI-тексты:** русский.

### Git
- 🔴 **Все коммиты с изменениями кода обязательно согласовывать с пользователем.** Не коммитить самостоятельно.
- Перед коммитом: `git status`, `git diff`, `git log --oneline -10`. Стейджить только intended-файлы, никогда не коммитить секреты.
- Не обновлять git config, не пропускать хуки, не force-push, не создавать пустые коммиты без явного запроса.

### Стиль кода
- Линтер: **ruff** (в проекте есть `.ruff_cache/`). Запускайте `ruff check` перед коммитом.
- НЕ добавляйте комментарии, если явно не просят.
- Импорты: сторонние библиотеки → локальные модули (`from src.server...`).
- Логирование: используется `logging` (`logging.getLogger(__name__)`). Часть старых модулей ещё использует `print()` — постепенно заменяется.

### Структура
- **Роуты** (`routes/`) — только HTTP-слой: валидация, вызов сервисов, форматирование ответа. Никакой бизнес-логики сканирования.
- **Сервисы** (`services/`) — бизнес-логика, работа с БД и внешними API. Не знают про HTTP.
- **Модели** (`models.py`) — только описание таблиц и `store_hash_id()`. Без логики.
- **Константы** (`constants.py`) — общие для нескольких модулей (типы магазинов).

---

## Критические особенности

### 1. Store IDs — строки (MD5-хэши), НЕ integers 🔴
ID магазинов — 12-символьные MD5-хэши из `store_code + store_type + full_address`. FastAPI path-параметры для магазинов должны объявляться как `store_id: str`, не `int`.

```python
from src.server.models import store_hash_id
store_id = store_hash_id(store_code, store_type, full_address)  # 12 символов
```

Конструктор `Store.__init__` (`models.py:46`) автоматически вычисляет `id` и `shop_type` — но при ручном создании через `Store(id=..., ...)` передавайте корректный хэш.

### 2. Порядок endpoint definitions в FastAPI 🔴
FastAPI матчит маршруты в порядке регистрации. **Статические пути ДО параметрических:**

| Файл | Правильный порядок |
|------|-------------------|
| `catalog.py` | `/products` → `/products/stats` → `/products/multi-prices` → `/products/{product_id}` → `/{product_id}/history` |
| `jobs.py` | `/jobs` → `/jobs/active` → `/jobs/{job_id}` → `/{job_id}/cancel` |
| `stores.py` | `/stores/search` → `/stores/{store_id}` |

Если нарушить порядок — статический сегмент (`stats`, `multi-prices`, `active`, `search`) попадёт в path-параметр и приведёт к 422 (для `int`) или 404 (для `str`).

### 3. Rate limiting — НЕ убирать 🔴
- `MagnitAPIClient._rate_limit_wait()` (`magnit_api.py:63`): 0.5s + `random.uniform(0.1, 0.5)`.
- `StoresAPI`: 0.3s.
- `CatalogUpdater._rate_limit_wait()` (`catalog_updater.py:38`): 0.5s.

API Магнита блокирует при превышении частоты запросов. Случайная пауза защищает от детектирования ботов.

### 4. `.env` — НЕ редактировать вручную 🔴
Обновляется только через `POST /api/stores/select` (`routes/stores.py:164`), который атомарно меняет `STORE_CODE` и `STORE_TYPE` через `dotenv.load_dotenv()`. Ручное редактирование рассинхронизирует состояние с БД.

> `store_selector.py` **не обновляет `.env`** — это Playwright-сканер магазинов. Фактическое обновление — только в `routes/stores.py`.

### 5. Фоновые задачи — своя сессия БД 🔴
FastAPI закрывает сессию из `Depends(get_db)` **после** отправки HTTP-ответа. Внутри `BackgroundTasks` и `threading.Thread` создавайте **новую `SessionLocal()`** и закрывайте в `finally`:

```python
def run_update():
    from src.server.database import SessionLocal
    bg_db = SessionLocal()
    try:
        # ... работа с bg_db ...
        bg_db.commit()
    except Exception:
        bg_db.rollback()
    finally:
        bg_db.close()
```

### 6. Bulk operations
`CatalogScanner._save_products()` (`catalog_scanner.py:435`) использует `bulk_insert_mappings` / `bulk_update_mappings` для `Product` и `PriceHistory`. **Не заменяйте** на построчные `db.add()` / `db.commit()` — потеряете производительность при 5000+ товаров.

### 7. Категории универсальные
Категории в `Category` **не привязаны** к конкретному магазину (`store_code` нет в таблице). Дерево общее для всех магазинов. При полной замене через `CatalogUpdater.replace_all_categories()` флаг `is_tracked` **сохраняется** по `magnit_id`.

### 8. Знак `price_change_percent`
- **Положительное** значение (`+15`) = цена **снизилась** (зелёная стрелка `↓` в UI).
- **Отрицательное** (`-11.8`) = цена **повысилась** (фиолетовая стрелка `↑`).

Формула: `(previous_price - current_price) / previous_price * 100`.

### 9. SQLite и кириллица
`LOWER()` в SQLite **не работает** с кириллицей. Поиск по `search` в `list_products` (`catalog.py:249`) выполняется в Python через `casefold()` (Unicode-aware). Не пытайтесь перенести поиск в SQL `LIKE LOWER()`.

### 10. `check_same_thread=False`
Engine создаётся с `connect_args={"check_same_thread": False}` (`database.py:10`) — один engine для разных потоков (scheduler, фоновые задачи). Но **каждая задача создаёт свою сессию**, не делит сессию между потоками.

---

## Типичные ошибки

| Ошибка | Причина | Решение |
|--------|---------|---------|
| 422 Unprocessable Entity для `/api/stores/{id}` | `store_id: int` вместо `str` | Объявлять `store_id: str` |
| 422 для `/api/products/stats` | Эндпоинт определён ПОСЛЕ `/api/products/{product_id}` | Перенести `stats` ДО параметрического |
| SQLAlchemy error в фоновой задаче | Используется закрытая сессия из `get_db` | Создать `SessionLocal()` внутри задачи |
| Бан API Магнита | Убрали rate limiting | Вернуть `_rate_limit_wait()` |
| Рассинхрон `.env` и БД | Ручное редактирование `.env` | Использовать `POST /api/stores/select` |
| N+1 запросов в дереве категорий | Рекурсивный `build_tree` с SELECT на каждый узел | Один SELECT + сборка в памяти (см. `code_review_2026-06-12.md`) |
| `Integer` для `shop_type` не заполняется | Создание `Store` без использования конструктора | Использовать `Store(**data)` (конструктор проставит `shop_type`) |

---

## Технический долг и известные расхождения

### Активные расхождения в коде

#### 1. `load_catalog_from_json.py` ожидает другой формат `categories.json`
`load_catalog_from_json.py:52` читает `data["root_categories"]`, но фактический `src/data/categories.json` — **плоский массив** `[{id, title}]` без ключа `root_categories`. Эндпоинты `POST /api/categories/load-from-json`, `/build-from-playwright`, `/seed-from-playwright` могут не работать с текущим файлом.

**Решение:** либо привести `categories.json` к формату `{"root_categories": [{id, title}]}`, либо исправить чтение в `load_catalog_from_json.py` на плоский массив.

#### 2. `query_product.py` использует устаревшие поля
`query_product.py:11` ссылается на `historical_discount_percent`, который удалён миграцией `migrate_simplify_price_tracking`. Скрипт упадёт при запуске.

**Решение:** удалить `historical_discount_percent` из SELECT.

#### 3. Дублирование `POST /api/stores` в `main.py`
`main.py:158` (`create_store_htmx`) определён для HTMX form-data, но `app.include_router(stores.router)` (`main.py:81`) регистрирует `create_store` (`stores.py:71`) раньше — HTMX-вариант **перекрыт и недостижим**.

**Решение:** либо удалить HTMX-заглушку, либо вынести на отдельный путь (`/api/stores/htmx`).

### Замечания из code review

Полный отчёт: `docs/code_review_2026-06-12.md`. Ключевые нерешённые проблемы:

| # | Проблема | Файл | Приоритет |
|---|---------|------|-----------|
| 1 | N+1 в `get_categories_tree` (рекурсивные SELECT) — хотя в `catalog.py:128` сейчас реализация с одним SELECT, проверьте | `routes/catalog.py` | 🔴 |
| 2 | 4 COUNT в `get_products_stats` вместо одного с CASE WHEN | `routes/catalog.py:388` | 🟠 |
| 3 | `print(DEBUG)` вместо `logging` в части модулей | несколько файлов | 🟡 |
| 4 | `commit()` внутри циклов обновления подкатегорий | `catalog_updater.py`, `catalog_scanner.py` | 🟡 |

### Исторические планы
- `PLAN_SIMPLIFY_PRICE_TRACKING.md` — упрощение отслеживания цен (выполнено).
- `PLAN_TWO_PRICE_MODES.md` — два режима отображения цен (выполнено).

---

## Тестирование

Тестовый фреймворк **не настроен**. Ручное тестирование через:
- **Swagger UI:** http://localhost:8000/docs
- **Веб-интерфейс:** http://localhost:8000

Полезные эндпоинты для проверки:
- `GET /api/stores` — список магазинов
- `GET /api/categories` — категории
- `GET /api/products/stats?store_code=X` — статистика
- `POST /api/catalog/scan?store_code=X` — синхронное сканирование (быстрая проверка)

### Проверка после изменений
1. Запустить сервер, проверить логи миграций.
2. Проверить структуру БД: `sqlite3 src/data/magnit.db ".schema products"`.
3. Для изменений цен: вручную изменить цену в БД, запустить `POST /api/catalog/scan-prices?store_code=X`, проверить `previous_price` / `price_change_percent`.
4. Для UI: `/products` — проверить стрелки `↓`/`↑`, переключение чекбокса «Новая цена».

---

## Команды

```bash
# Запуск
python -m uvicorn src.server.main:app --host 0.0.0.0 --port 8000 --reload

# Линтинг
ruff check src/

# Установка браузеров Playwright
playwright install chromium

# Проверка БД
sqlite3 src/data/magnit.db ".tables"
sqlite3 src/data/magnit.db ".schema products"
sqlite3 src/data/magnit.db "SELECT * FROM stores LIMIT 5;"
```
