# Tasks

## 1. Поиск товаров и удаление по категориям

- [x] 1.1 В `routes/catalog.py:list_products` при `search` строить второй запрос по `Product.id.in_(...)` найденных кандидатов (D1). Проверка: товар есть в двух магазинах → `GET /api/products?store_code=A&search=<часть названия>` возвращает только запись магазина A; с `include_out_of_stock=false` отсутствующие товары не возвращаются.
- [x] 1.2 В `clear_products_by_categories` пробрасывать `HTTPException` до общего `except` (D7). Проверка: `DELETE /api/products/clear-by-categories?category_ids=abc` → 400, число товаров не изменилось.

## 2. Полная замена каталога — upsert по magnit_id

- [x] 2.1 Переписать шаги 4–6 `CatalogUpdater.replace_all_categories` на upsert по `magnit_id` в одной транзакции: обновление и создание корней, затем детей, обнуление `Product.category_id` и удаление исчезнувших категорий, статистика `added/updated/deleted/total` (D2). Проверка: запомнить `id` нескольких категорий и `category_id` нескольких товаров → `POST /api/categories/fetch-magnit-ids` → после завершения ID и `is_tracked` совпадают, `GET /api/products?category_ids=<id>` возвращает те же товары.
- [x] 2.2 Проверить путь ошибки: временно подставить в `categories.json` несуществующий `id` корня → статус замены показывает ошибку, `SELECT count(*), max(id) FROM categories` не изменились; вернуть файл.
- [x] 2.3 Обновить описание замены каталога в `docs/SERVICES.md` и `docs/API.md` (upsert вместо delete+insert, стабильные ID). Проверка: в документах не осталось упоминаний «очистить таблицу категорий».

## 3. Жизненный цикл заданий

- [x] 3.1 Создать `src/server/services/jobs.py` с `finalize_job(db, job_id, status, **fields)` и `mark_unfinished_jobs_failed(db)` (фильтр `pending` + `running`) (D3); удалить `_mark_all_running_failed_on_startup` из `routes/stores.py`, вызвать новую функцию в `main.py:lifespan`. Проверка: вставить в `scan_jobs` строку со `status='pending'` → перезапуск → строка в `failed`, `GET /api/jobs/active` её не возвращает.
- [x] 3.2 `CatalogScanner.scan_products` при отмене возвращает статистику с `"cancelled": True`. Проверка: `ruff check src/`; в логах отменённого скана виден возврат с флагом.
- [x] 3.3 Использовать `finalize_job` в `routes/prices.py:run_update` (успех и ошибка), `scheduler.update_prices_job`, обеих фазах `scheduler.scan_catalog_job` и в финале `scan_all_stores`. Проверка: `POST /api/prices/update?store_code=<код>` → сразу `POST /api/jobs/{id}/cancel` → после остановки `GET /api/jobs/{id}` показывает `cancelled`; то же для `scan-all-stores`.

## 4. Семантика изменения цены

- [x] 4.1 В `CatalogScanner._save_products` заменить блок `last_change_*` на сравнение с `existing.price` (D4); логику `previous_price`/`price_change_percent` не трогать. Проверка (через SQLite-клиент): выставить у товара `price=100, last_change_price=NULL` → скан, где API возвращает 80 → `last_change_price=100`, `last_change_date`=сегодня; повторный скан → поля не изменились.
- [x] 4.2 В `MagnitAPIClient._parse_product` возвращать `None` с warning, если цена отсутствует или ≤ 0 (D5). Проверка: в логах скана появляются warning'и для таких позиций; `SELECT count(*) FROM products WHERE price = 0` после скана не растёт.
- [x] 4.3 Описать в `docs/DATABASE.md` (поля отслеживания цен) новую семантику `last_change_*` и известное ограничение: старые даты не исправляются. Проверка: раздел соответствует таблице примера из design.md.

## 5. Конфигурация и планировщик

- [x] 5.1 В `main.py` вызвать `load_dotenv(<корень>/.env, override=False)` до чтения переменных (D6). Проверка: убрать `STORE_CODE` из окружения, оставить в `.env` → при старте в логе `[Scheduler] Планировщик запущен`.
- [x] 5.2 Разделить `init_scheduler` на `register_jobs(store_code)` и запуск; `update_prices_job` читает отслеживаемые категории в момент запуска (передаётся `category_ids=None`). Проверка: `ruff check src/`; `scheduler.get_jobs()` (лог при регистрации) показывает два задания с нужным `store_code`.
- [x] 5.3 В `select_store` после записи `.env` обновить `os.environ` и вызвать `register_jobs` с запуском планировщика при необходимости. Проверка: `POST /api/stores/select` для другого магазина → в логе перерегистрация заданий с новым кодом, без перезапуска сервера.
- [x] 5.4 Обновить `docs/DEPLOYMENT.md` и `AGENTS.md` (раздел про `.env`): `.env` читается при старте, смена магазина применяется без перезапуска; отметить шаг 3.1 в `docs/PLAN_FIXES_2026-09-27.md` как закрытый этим изменением. Проверка: описания совпадают с поведением из 5.1–5.3.

## 6. Интеграционная проверка

- [x] 6.1 Полный цикл в UI: выбрать магазин → замена каталога → отметить категории → «Сканировать все магазины» → поиск на `/products` → история цен товара. Проверка: ошибок в логе нет, поиск ограничен выбранным магазином, `ruff check src/` чист.
  - Примечание: прогон на живом API (копия БД): замена каталога 80/80, скан 4 магазинов `completed` (3776 товаров), поиск ограничен магазином, история цен на месте, `ruff check src/` чист. В журнале одна ошибка — таймаут magnit.ru (`Read timed out`), повтор scanner'а успешен; отмечено как допустимое по решению владельца. Клики в браузере не проверялись — проверены HTTP-эндпоинты, которыми пользуется UI.

## Workflow follow-up

- Коммит только после согласования с пользователем (AGENTS.md), формат `фикс: ...`.
- Архивировать изменение после проверки (`/opsx:archive`).
