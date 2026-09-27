# Архитектурный обзор 2026-09-27

Анализ кодовой базы `src/server` на архитектурные ошибки и риски.
Приоритеты: 🔴 критично (баг, ломает работу), 🟠 важно (архитектурный долг),
🟡 желательно (безопасность/гигиена).

---

## 🔴 Критичные баги

### 1. Scheduler передаёт не те ID категорий

**Файл:** `src/server/scheduler.py` (`init_scheduler`)

```python
tracked_categories = db.query(Category).filter(Category.is_tracked == True).all()
category_ids = [cat.id for cat in tracked_categories]  # ← DB primary key
```

`category_ids` передаётся в `CatalogScanner.scan_products()`, который трактует
его как `magnit_id` (ID из API Магнита):

```python
# catalog_scanner.py, scan_products():
cat = self.db.query(Category).filter(Category.magnit_id == cat_magnit_id).first()
```

**Последствие:** ежедневное задание в 8:00 сканирует не те категории (или
никакие), если `Category.id ≠ Category.magnit_id`. После любых миграций,
пересоздающих таблицу категорий (`migrate_categories` пересоздаёт таблицу
с нумерацией с 1), рассинхрон гарантирован.

**Фикс:** `category_ids = [cat.magnit_id for cat in tracked_categories]`.

---

### 2. `scan_catalog_job` никогда не помечает задание как failed

**Файл:** `src/server/scheduler.py`

```python
job_id = None   # объявлен...
try:
    ...
    # ...но нигде не присваивается
except Exception as e:
    if job_id:   # ← всегда None, ветка мертва
```

**Последствие:** упавшее еженедельное сканирование каталога остаётся в статусе
`running` навсегда. Пользователь видит «зависшее» задание; `_cleanup_stale_jobs`
его не трогает (фильтр по `job_type == "stores"`), а `_mark_all_running_failed_on_startup`
исправит это только после перезапуска сервера.

**Фикс:** присваивать `job_id = job_categories.id` (и `job_products.id` на втором
этапе) сразу после `db.refresh()`, обрабатывать сбой каждого этапа отдельно.

---

### 3. Мёртвые страницы `/test-discount` и `/test-stores-loading`

**Файл:** `src/server/main.py`

Роуты рендерят шаблоны `test_discount.html` и `test_stores_loading.html`,
которых нет в `src/server/templates/` → гарантированный `TemplateNotFoundError`
(500) при открытии страниц.

**Фикс:** удалить оба роута (или восстановить шаблоны, если они нужны).

---

### 4. Дублирующий `POST /api/stores` перекрывает JSON-эндпоинт

**Файл:** `src/server/main.py`

`@app.post("/api/stores")` (HTMX-версия) регистрируется раньше роутера
`stores.router` и навсегда перекрывает `POST /api/stores` с валидацией через
`StoreCreate` (schemas.py). JSON-клиент получает HTML вместо JSON, а валидация
Pydantic не работает: `form["city"]` при отсутствии поля даёт KeyError → 500.

**Фикс:** удалить HTMX-роут из `main.py` (UI сейчас отправляет `fetch`-запросы,
а не HTMX-формы — подтверждено шаблонами), либо переименовать путь.

---

### 5. Relationship `Category.children` инвертирован

**Файл:** `src/server/models.py`

```python
children = relationship("Category", backref="parent", remote_side=[id])
```

`remote_side=[id]` означает many-to-one: атрибут `children` фактически
возвращает **родителя**, а backref `parent` — список **детей**. Имена
семантически перепутаны. Сейчас ничего не падает (код не использует эти
атрибуты — проверено поиском), но любой будущий код получит не то, что ожидал.

**Фикс:**

```python
children = relationship("Category", backref=backref("parent", remote_side=[id]))
# или идиоматично:
parent = relationship("Category", backref="children", remote_side=[id])
```

---

### 6. `_cleanup_stale_jobs` ложно убивает живые задания

**Файл:** `src/server/routes/stores.py`

Порог «зависания» — 2 минуты. Сканирование магазинов с rate limiting 0.3s
запрос легко длится дольше → живое задание помечается `failed`, но поток
продолжает работать параллельно с новым (двойной скан, двойная нагрузка на API).

**Фикс:** поднять порог (например, до 30 минут) или добавить heartbeat-поле
(`progress_message`/`started_at` обновляются потоком) и чистить по нему.

---

### 7. Scheduler не реагирует на смену магазина

**Файл:** `src/server/scheduler.py` + `routes/stores.py`

`init_scheduler(store_code)` фиксирует магазин один раз при старте. `POST
/api/stores/select` меняет `STORE_CODE` в `.env`, но планировщик продолжает
сканировать старый магазин до перезапуска сервера.

**Фикс:** в `select_store` после обновления `.env` пересоздавать задания
планировщика (`init_scheduler` идемпотентен благодаря `replace_existing=True`)
или читать магазин в момент запуска задания, а не при регистрации.

---

## 🟠 Архитектурные проблемы

### 8. Дублирование синхронизации категорий (DRY)

Логика «удалить/добавить/обновить подкатегории по данным API» реализована
**дважды**:

- `CatalogScanner.scan_categories()` — `src/server/services/catalog_scanner.py`
- `CatalogUpdater.update_category_from_api()` — `src/server/services/catalog_updater.py`

Код почти идентичен, но с разными заголовками HTTP и разным rate limiting.
`_fetch_category_data` скопирован в оба класса. Любая правка делается в двух
местах и рассинхронизируется.

**Рекомендация:** оставить одну реализацию в `CatalogScanner`; `CatalogUpdater`
сделать тонкой обёрткой или удалить.

### 9. Четыре роута делают одно и то же

`routes/catalog.py`:

- `POST /api/categories/scan`
- `POST /api/categories/update-catalog`
- `POST /api/categories/build-from-playwright` (алиас)
- `POST /api/categories/seed-from-playwright` (алиас алиаса)

Все вызывают один и тот же код. Это запутывает API и документацию Swagger.

**Рекомендация:** оставить один (`/categories/update-catalog`), остальные
удалить или пометить `deprecated=True` на переходный период.

### 10. Бизнес-логика в слое routes

`list_products` (`routes/catalog.py`) — ~100 строк логики жизненного цикла
stale-товаров, casefold-поиска, построения query. По собственной конвенции
проекта (KODA.md: «routes — только HTTP; services — бизнес-логика») это
нарушение слоёв. То же с логикой `select_store` (работа с `.env` прямо в роуте).

**Рекомендация:** вынести построение query и фильтры в
`services/product_query.py` (или в CatalogScanner), роут оставить тонким.

### 11. `Store.store_code` не уникален, FK отсутствует

`Product.store_code` — строка без FK на `stores`. При этом `Store.store_code`
имеет обычный индекс, не unique. Один и тот же код магазина может существовать
в нескольких типах магазинов → `CatalogScanner.__init__` делает
`.first()` по `store_code` и берёт **произвольный** `store_type`.

**Рекомендация:** уникальный составной индекс `(store_code, store_type)`
(миграция), а в `CatalogScanner` передавать `store_type` явно.

### 12. `_run_migration` считает успешной частично применённую миграцию

Миграции внутри подавляют ошибки (`except Exception: pass`, ранние `return`),
после чего `_run_migration` регистрирует их как выполненные. Если миграция
упала на середине, при следующем старте она будет пропущена — схема останется
частично применённой навсегда.

**Рекомендация:** миграции должны возвращать успех/провал и регистрироваться
только при успехе; провал — loud (лог + не регистрировать).

### 13. SQLite без WAL и busy_timeout

`create_engine(..., check_same_thread=False)` + фоновые сканы (scheduler,
threading.Thread) + HTTP-запросы параллельно → риск `database is locked`
без ожидания и ретрая.

**Рекомендация:** включить WAL и таймаут (одна строка):

```python
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30},
)
# + PRAGMA journal_mode=WAL через event listener
```

### 14. `commit()` внутри циклов

- `_update_job_progress` коммитит на каждую категорию и каждую страницу
  пагинации;
- `scan_categories` коммитит на каждую корневую категорию;
- `CatalogUpdater.update_all_categories` — аналогично.

Для 5000+ товаров это тысячи коммитов и лишних fsync.

**Рекомендация:** батчить прогресс (обновлять раз в N итераций) или
использовать отдельную короткую сессию только для прогресса.

### 15. Поиск загружает все товары в память

`list_products`: при наличии `search` выполняется
`_build_filtered_query().all()` — **все** товары магазина грузятся в Python,
фильтруются через `casefold()`, затем повторный запрос с
`IN (список из тысяч id)`. На 5000+ товарах это главное узкое место UI.

**Рекомендация:** хранить нормализованное поле `name_search` (casefold при
записи, LIKE по нему), либо SQLite-функцию `lower()` с ICU. Частично
пересекается с замечанием из `docs/code_review_2026-06-12.md`.

### 16. `self.db.expire_all()` на каждой итерации

`catalog_scanner.py` вызывает `expire_all()` перед каждой проверкой отмены
задания (на каждую страницу пагинации) — сбрасывает весь identity map сессии,
форсируя перечитывание всех объектов.

**Рекомендация:** проверять отмену отдельным лёгким запросом
(`db.query(ScanJob.status).filter(...)` с `.execution_options(...)` или
отдельной сессией) вместо инвалидации всей сессии.

### 17. Три разных дефолта `store_type` + захардкоженный магазин

- `magnit_api.py`: `os.getenv("STORE_TYPE", "MM")`
- `catalog_scanner.py`: fallback `"Магнит"`
- `catalog_updater.py`: `store_code="210117"`, `store_type="9"` —
  **захардкоженный конкретный магазин** в коде сервиса.

**Рекомендация:** единый источник дефолтов (`constants.py`), убрать
хардкод из `CatalogUpdater`.

### 18. `schemas.py` не используется для ответов API

Pydantic-модели описаны, но большинство эндпоинтов возвращают голые `dict`
(вручную собранные) — нет контракта API, легко забыть поле, Swagger не
отражает реальную структуру.

**Рекомендация:** описать response_model для ключевых эндпоинтов
(`products`, `categories`, `prices/decreased`).

### 19. Миграции на `print()` вместо `logging`

`database.py` целиком на `print()` — не попадает в форматированный лог,
не управляется уровнем. KODA.md это признаёт; миграции — самое шумное место.

**Рекомендация:** перевести `database.py` на `logging.getLogger(__name__)`.

---

## 🟡 Безопасность и гигиена

### 20. Open redirect в `/redirect-to-product`

`GET /redirect-to-product?url=...` редиректит на произвольный URL → классический
open redirect (фишинг-ссылки через доверенный домен).

**Рекомендация:** валидировать, что `url` начинается с `https://magnit.ru/`.

### 21. CORS по умолчанию `*`

`CORS_ORIGINS` по умолчанию `*` — приемлемо для локального инструмента,
но при выносе в сеть стоит задать явные origins (см. `.env.example`).

### 22. `!= None` вместо `is not None`

`routes/catalog.py` (`Category.parent_id != None`), `database.py`
(`Store.shop_type != None`) — ruff E711. Судя по наличию `# noqa: E712` в других
местах, линтер запускается не по всем путям или правила выборочны.

**Рекомендация:** заменить на `is not None` / `.isnot(None)`; проверить
`ruff check src/` целиком.

### 23. `threading.Thread` без обработки ошибок

`main.py` (`open-product-in-browser`) и фоновые задачи запускают потоки
«fire-and-forget»: исключение внутри потока не логируется и не влияет на
статус задания.

**Рекомендация:** оборачивать target в try/except с логированием.

---

## Сводка

| # | Проблема | Файл | Приоритет | Сложность |
|---|----------|------|-----------|-----------|
| 1 | Scheduler: `cat.id` вместо `cat.magnit_id` | scheduler.py | 🔴 | XS |
| 2 | `scan_catalog_job`: мёртвый `job_id` | scheduler.py | 🔴 | S |
| 3 | Мёртвые страницы /test-* | main.py | 🔴 | XS |
| 4 | Дубль POST /api/stores | main.py | 🔴 | XS |
| 5 | Инвертированный relationship children/parent | models.py | 🔴 | XS |
| 6 | Ложный fail живых заданий (2 мин) | routes/stores.py | 🔴 | S |
| 7 | Scheduler не видит смену магазина | scheduler.py + stores.py | 🔴 | M |
| 8 | Дубль синхронизации категорий | scanner/updater | 🟠 | M |
| 9 | 4 дублирующих роута категорий | routes/catalog.py | 🟠 | XS |
| 10 | Логика в слое routes | routes/catalog.py | 🟠 | M |
| 11 | store_code не уникален, нет FK | models.py + миграция | 🟠 | M |
| 12 | Ложная регистрация миграций | database.py | 🟠 | S |
| 12 | SQLite без WAL/timeout | database.py | 🟠 | XS |
| 14 | commit() в циклах | scanner/updater | 🟠 | S |
| 15 | Поиск грузит всё в память | routes/catalog.py | 🟠 | M |
| 16 | expire_all() на каждой итерации | catalog_scanner.py | 🟠 | S |
| 17 | Разные дефолты store_type, хардкод | несколько | 🟠 | S |
| 18 | Нет response_model | routes/* | 🟠 | M |
| 19 | print() в database.py | database.py | 🟠 | S |
| 20 | Open redirect | main.py | 🟡 | XS |
| 21 | CORS `*` по умолчанию | main.py | 🟡 | XS |
| 22 | `!= None` (E711) | catalog.py, database.py | 🟡 | XS |
| 23 | Потоки без обработки ошибок | main.py | 🟡 | S |

Известный техдолг из `docs/DEVELOPMENT.md` подтверждён: `load_catalog_from_json`
(ожидает `root_categories`, файл — плоский массив), `query_product.py`
(удалённое поле), производительность `get_products_stats`.
