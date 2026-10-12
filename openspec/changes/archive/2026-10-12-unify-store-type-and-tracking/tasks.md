# Tasks

## 1. Контракт миграций (делается первым — дальше добавляются новые миграции)

- [x] 1.1 Переписать `_run_migration`: `try` вокруг вызова, `rollback` + `logger.warning` без регистрации при исключении (D10). Проверка: временно бросить исключение в одной миграции на копии БД → warning в логе, строки в `schema_migrations` нет, сервер стартовал; убрать исключение → после рестарта миграция зарегистрирована.
- [x] 1.2 Убрать внутренние «глушилки» из функций миграций, проверки «колонка уже есть» сделать через `inspect(engine)`, `print` → `logger` во всём `database.py`; исправить условие в `migrate_categories` (без колонки `code`). Проверка: старт на существующей БД — ни одна зарегистрированная миграция не выполняется, лог чистый; `ruff check src/`.
- [x] 1.3 Добавить миграцию `ensure_product_last_scan_index` в конец списка. Проверка: `DROP INDEX ix_product_last_scan` на копии БД → рестарт → `PRAGMA index_list(products)` содержит индекс.
- [x] 1.4 Обновить раздел миграций в `docs/DATABASE.md` (контракт «регистрация только при успехе», новые миграции). Проверка: список миграций в документе совпадает с `init_db()`.

## 2. Единый тип магазина и клиент API

- [x] 2.1 В `constants.py` добавить `DEFAULT_STORE_TYPE`, `get_configured_store_type()`, `resolve_store_type_code()` (D1). Проверка: в `python -c` для `"MM"`, `"Магнит"`, `"1"`, `None`, `"xyz"` получить `"1"` (последний — с warning), для `"MM_MINI"` и `"Мини"` — `"2"`.
- [x] 2.2 В `MagnitAPIClient` вынести построение payload в общий хелпер с `resolve_store_type_code`, добавить `fetch_category_raw(category_id)` с `_rate_limit_wait()` (D2). Проверка: при `logger` уровня DEBUG payload `search` и `fetch_category_raw` для магазина «Экстра» содержит `"storeType": "6"`.
- [x] 2.3 `CatalogScanner._fetch_category_data` делегирует `fetch_category_raw`. Проверка: при `POST /api/categories/scan` интервалы между запросами в DEBUG-логе ≥ 0.6 с.
- [x] 2.4 `CatalogUpdater` использует `MagnitAPIClient`, дефолты `210117`/`"9"` удалены; в `_fetch_and_update_categories_background` убрать ветку с `"6"` и вернуть ошибку при отсутствии магазина (D2). Проверка: `grep -rn "210117\|\"9\"\|\"6\"" src/server` не находит дефолтов типа/магазина; замена каталога без `STORE_CODE` и без магазинов → статус с ошибкой «не выбран магазин».
- [x] 2.5 Удалить из `catalog_scanner.py` дефолт `"Магнит"` в пользу `get_configured_store_type()`. Проверка: `ruff check src/`.

## 3. Отслеживаемые категории и синхронизация

- [x] 3.1 Добавить `get_tracked_category_magnit_ids(db)` и использовать её в `scan_products` (tracked_only), `scan_prices_in_store`, `scan_all_stores` (D3). Проверка: отметить корень через `PUT /api/categories/{root}/track?track=true` и две подкатегории → `POST /api/catalog/scan-prices` в логе сканирует ровно две категории.
- [x] 3.2 `scan_categories` обрабатывает все корни с `magnit_id` (D4). Проверка: после сохранения отметок на `/catalog` вызвать `POST /api/categories/scan?store_code=<код>` → `scanned` = числу корней, `is_tracked` подкатегорий сохранены.
- [x] 3.3 Переписать `load_catalog_from_json` на плоский массив через `load_root_categories_from_file`, исправить сообщения про `magnit_catalog.json` в `routes/catalog.py` (D5). Проверка: на пустой таблице `POST /api/categories/load-from-json` → `added` = числу элементов файла; повторный вызов → `added: 0`; переименованный файл → 404 с `categories.json`.
- [x] 3.4 Удалить пункт про формат `categories.json` из техдолга в `docs/DEVELOPMENT.md` и `AGENTS.md`, описать определение «отслеживаемых категорий» в `docs/SERVICES.md`. Проверка: документы соответствуют D3–D5.

## 4. Статистика и сканирование всех магазинов

- [x] 4.1 `get_products_stats`: `in_stock` считать как `in_stock AND quantity > 0`. Проверка: товар с `in_stock=1, quantity=0` не входит в `in_stock` ответа `GET /api/products/stats`.
- [x] 4.2 Добавить в `scan_products` колбэк `on_category_start`, перевести `scan_all_stores` на один вызов на магазин с обновлением прогресса из колбэка (D9). Проверка: на `/jobs` прогресс и имя текущей категории обновляются; в логе сообщение «Помечено отсутствующими…»/очистка встречается один раз на магазин; отмена во время скана останавливает задание.

## 5. Идентичность магазинов

- [x] 5.1 Добавить `UniqueConstraint` в `Store` и миграцию `add_store_code_type_unique` со схлопыванием дубликатов (D6). Проверка: на копии БД вставить дубликат (code, type) → рестарт → дубликат удалён с записью в логе, `PRAGMA index_list(stores)` содержит `uq_store_code_type`.
- [x] 5.2 `create_store`, `add_selected_stores`, `preview_stores` — дедупликация и `exists_in_db` по паре (code, type). Проверка: сценарии из `specs/store-registry` (409 на дубликат пары, создание того же кода с другим типом, `{"added": 1, "skipped": 1}`).
- [x] 5.3 `CatalogScanner.__init__` принимает `store_type`; `scan_all_stores`, планировщик и ручные эндпоинты (`/catalog/scan`, `/catalog/scan-prices`, `/prices/update` с необязательным `store_type`) передают тип, неоднозначность → 400 (D6). Проверка: два магазина с одним кодом → `POST /api/catalog/scan-prices?store_code=<код>` → 400; с `&store_type=Экстра` → скан с `storeType: "6"`.
- [x] 5.4 `update_store` отклоняет изменение `store_type`/`full_address` (D7). Проверка: `PUT /api/stores/{id}` с другим `store_type` → 400; с новым `name` → 200, `id` прежний.
- [x] 5.5 `PREVIEW_STORE_TYPES` в `constants.py`, `schemas.py` импортирует карты из `constants`, «Мигом» удалён, валидация типов в `preview_stores` (D8). Проверка: preview с `["Магнит","Заряд"]` → 400 с `Заряд`; preview из UI на `/` работает как раньше.
- [x] 5.6 Описать BREAKING-изменения `PUT /api/stores/{id}` и `POST /api/stores/preview`, новый параметр `store_type` и уникальность (code, type) в `docs/API.md`; добавить в `docs/DEVELOPMENT.md` техдолг про ключ `products(product_id, store_code)`; отметить шаги 2.2, 2.3, 4.3 в `docs/PLAN_FIXES_2026-09-27.md` как закрытые. Проверка: документы соответствуют D6–D8.

## 6. Интеграционная проверка

- [x] 6.1 Полный цикл в UI на копии рабочей БД: старт (миграции) → поиск и добавление магазинов → замена каталога → `POST /api/categories/scan` → отметить подкатегории → «Сканировать все магазины» → `/products` и статистика. Проверка: в логе нет ошибок, все запросы к API содержат числовой `storeType`, `ruff check src/` чист.

## Workflow follow-up

- Применять после `fix-data-integrity-bugs` (используются `finalize_job` и upsert категорий).
- Коммит только после согласования с пользователем, формат `фикс: ...` / `рефактор: ...`.
- Архивировать после проверки (`/opsx:archive`).
