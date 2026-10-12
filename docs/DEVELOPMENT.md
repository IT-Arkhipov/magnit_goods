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
- Логирование: используется `logging` (`logging.getLogger(__name__)`). `print()` остался только в Playwright-модулях (`store_selector.py`, `category_verifier.py`, `scripts/verify_categories.py`).
- **Поведение и документация меняются в одном изменении.** Изменили эндпоинт, миграцию, правило сканирования — поправьте `AGENTS.md` и затронутые файлы `docs/` сразу. Ссылайтесь на код как `файл:функция`, не по номерам строк (они устаревают).

### Структура
- **Роуты** (`routes/`) — только HTTP-слой: разбор параметров, вызов сервисов, форматирование ответа. Никакой бизнес-логики сканирования и выборки (выборка товаров — `services/product_query.py`).
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

Конструктор `Store.__init__` (`models.py`) автоматически вычисляет `id` и `shop_type` — но при ручном создании через `Store(id=..., ...)` передавайте корректный хэш.

### 2. Порядок endpoint definitions в FastAPI 🔴
FastAPI матчит маршруты в порядке регистрации. **Статические пути ДО параметрических:**

| Файл | Правильный порядок |
|------|-------------------|
| `catalog.py` | `/products` → `/products/stats` → `/products/multi-prices` → `/products/{product_id}` → `/{product_id}/history` |
| `jobs.py` | `/jobs` → `/jobs/active` → `/jobs/{job_id}` → `/{job_id}/cancel` |
| `stores.py` | `/stores/search` → `/stores/{store_id}` |

Если нарушить порядок — статический сегмент (`stats`, `multi-prices`, `active`, `search`) попадёт в path-параметр и приведёт к 422 (для `int`) или 404 (для `str`).

### 3. Rate limiting — НЕ убирать 🔴
- `MagnitAPIClient._rate_limit_wait()` (`magnit_api.py`): 0.5s + `random.uniform(0.1, 0.5)`. Через этого клиента идут **все** запросы каталога: товары (`search`), подкатегории (`fetch_category_raw`), в том числе из `CatalogUpdater` — собственного HTTP-клиента без ограничения частоты у него нет.
- `StoresAPI`: 0.3s.

API Магнита блокирует при превышении частоты запросов. Случайная пауза защищает от детектирования ботов.

### 4. `.env` — НЕ редактировать вручную 🔴
`.env` загружается при старте (`main.py`, `load_dotenv(override=False)`: переменные окружения процесса приоритетнее). Обновляется только через `POST /api/stores/select` (`routes/stores.py:select_store`), который меняет `STORE_CODE` и `STORE_TYPE` в файле, в `os.environ` работающего процесса и перерегистрирует задания планировщика — перезапуск не нужен. Ручное редактирование рассинхронизирует состояние с БД и планировщиком.

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

Итоговый статус `ScanJob` пишите через `services/jobs.py:finalize_job(db, job_id, status, **fields)`: он перечитывает задание из БД и **не затирает `cancelled`** (отмена приходит из другой сессии). Потоки (`threading.Thread`) запускайте через `utils/threads.py:run_logged` — иначе исключение потока теряется.

### 6. Bulk operations
`CatalogScanner._save_products()` (`catalog_scanner.py`) использует `bulk_insert_mappings` / `bulk_update_mappings` для `Product` и `PriceHistory`. **Не заменяйте** на построчные `db.add()` / `db.commit()` — потеряете производительность при 5000+ товаров.

### 7. Категории универсальные
Категории в `Category` **не привязаны** к конкретному магазину (`store_code` нет в таблице). Дерево общее для всех магазинов. Полная замена (`CatalogUpdater.replace_all_categories()`) — upsert по `magnit_id`: внутренние `id` и `is_tracked` существующих категорий **сохраняются**, поэтому `Product.category_id` остаётся валидным; удаляются только категории, которых нет в API. **Отслеживаемые** категории — подкатегории (`parent_id IS NOT NULL`) с `is_tracked`; единый набор для всех операций сканирования — `catalog_scanner.py:get_tracked_category_magnit_ids`.

### 8. Знак `price_change_percent`
- **Положительное** значение (`+15`) = цена **снизилась** (зелёная стрелка `↓` в UI).
- **Отрицательное** (`-11.8`) = цена **повысилась** (фиолетовая стрелка `↑`).

Формула: `(previous_price - current_price) / previous_price * 100`.

### 9. SQLite и кириллица
`LOWER()` в SQLite **не работает** с кириллицей. Поиск по названию идёт по колонке `Product.name_search` (`name.casefold()`, заполняется при сохранении товара и миграцией `add_product_name_search`) — `services/product_query.py`. Не переносите поиск на `LIKE LOWER(name)`; при новом пути записи товаров не забывайте заполнять `name_search`. Спецсимволы `%`, `_`, `\` в поисковом запросе экранируются.

### 10. Подключение к SQLite: потоки и WAL
Engine создаётся с `connect_args={"check_same_thread": False, "timeout": 30}` (`database.py`) — один engine для разных потоков (scheduler, фоновые задачи). Но **каждая задача создаёт свою сессию**, не делит сессию между потоками. При каждом подключении включаются `journal_mode=WAL` и `busy_timeout` 30 с (`_set_sqlite_pragma`): чтение не блокируется записью сканера, конкурирующая запись ждёт. Файлы `magnit.db-wal`/`-shm` в `.gitignore`.

### 11. Тип магазина в запросах к API
Только через `constants.py:resolve_store_type_code()` (API-код / русское название / число → числовой код). Не хардкодите коды магазинов и типов. Один код магазина может быть у нескольких типов — сканирование тогда требует явного `store_type` (`catalog_scanner.py:resolve_store_type`).

### 12. Миграции
Миграция выполняется один раз и регистрируется в `schema_migrations` **только при успехе**; внутри функции ошибки не глушатся (подробно — `docs/DATABASE.md`). Старые миграции не должны запрашивать всю сущность (`db.query(Product)`): колонки, добавленные позже, в старой БД могут отсутствовать.

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
| Отменённое задание стало `completed` | Статус присвоен напрямую после работы | Писать итог через `finalize_job` |
| Товар не находится поиском | Запись товара в обход `_save_products` — не заполнен `name_search` | Заполнять `name_search = name.casefold()` |
| Миграция «выполнена», а колонки/индекса нет | Ошибка внутри миграции была подавлена | Бросать исключение — `_run_migration` не зарегистрирует её и повторит |

---

## Технический долг и известные расхождения

### Активные расхождения в коде

#### 1. Ключ товара не включает тип магазина
`Product` идентифицируется парой (`product_id`, `store_code`) (`uq_product_store`). Магазины одного кода и разных типов (допустимы: уникальна пара `store_code`+`store_type`) делят строки в `products` и `price_history`: каждый скан перезаписывает данные другого типа. Сканирование в таком случае требует явного `store_type` (иначе 400), но данные смешиваются.

**Решение:** добавить тип магазина (или `Store.id`) в ключ `products`/`price_history` с миграцией данных; пока — не заводить два магазина с одним кодом и сканировать только один из них.

#### 2. Не подключённые модули
- `services/notifications.py` (`NotificationService`) — формирование отчётов; не вызывается: `daily_report` в планировщике закомментирован.
- `services/store_selector.py` (`MagnitStoreSelector`) — Playwright-сканер магазинов; роуты его не используют (поиск магазинов идёт через `StoresAPI`).

Модули не удалены: за ними стоят возможные сценарии (ежедневные отчёты, браузерный поиск магазинов). Решение об их судьбе — за владельцем проекта.

### Замечания из code review

Полный отчёт: `docs/code_review_2026-06-12.md`. Нерешённое:

| # | Проблема | Файл | Приоритет |
|---|---------|------|-----------|
| 1 | `commit()` внутри циклов обновления подкатегорий | `catalog_scanner.py` (`scan_categories`) | 🟡 |
| 2 | `print()` вместо `logging` в Playwright-модулях | `store_selector.py`, `category_verifier.py`, `scripts/verify_categories.py` | 🟡 |

Остальные пункты ревью (N+1 в дереве категорий, 4 COUNT в статистике товаров и др.) закрыты: дерево собирается одним SELECT, статистика — одним запросом с `CASE`.

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
