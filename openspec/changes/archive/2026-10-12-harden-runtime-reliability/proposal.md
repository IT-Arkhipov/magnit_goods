# Proposal

## Why

После исправлений из `fix-data-integrity-bugs` и `unify-store-type-and-tracking` в `docs/PLAN_FIXES_2026-09-27.md` остаются невыполненные шаги о надёжности и безопасности во время работы сервера:
- SQLite без WAL и `busy_timeout`: параллельно фоновым сканам HTTP-запросы получают `database is locked`.
- Ошибки в fire-and-forget потоках теряются.
- `/redirect-to-product` — открытый редирект.
- Сканер на каждой странице пагинации сбрасывает identity map сессии и коммитит прогресс, из-за чего скан замедляется в разы.

Это шаги 2.1, 3.2, 5.2, 5.3 и 6.1 плана.

## What Changes

- **SQLite**: при каждом подключении включаются режим WAL и `busy_timeout` 30 с; таймаут драйвера — 30 с (шаг 2.1).
- **Фоновые потоки**: исключения в потоке открытия товара через Playwright (`/open-product-in-browser`) и в потоке полной замены каталога логируются с traceback (шаг 3.2).
- **Ссылки на товар**:
  - **BREAKING:** `GET /redirect-to-product` принимает только `https://magnit.ru/...`, иначе — 400 (шаг 6.1);
  - тот же контроль у `GET /open-product-in-browser`, чтобы локальный браузер не открывал произвольные адреса.
- **Проверка отмены в сканере** — лёгким запросом статуса задания, без `expire_all()` (шаг 5.2).
- **Прогресс задания** записывается не чаще одного раза в 2 секунды. Обязательные сообщения (старт, отмена, финал, ошибки) записываются всегда (шаг 5.3).

## Capabilities

### New Capabilities
- `database-access`: требования к работе с SQLite при конкурентном доступе HTTP-запросов и фоновых заданий.
- `product-links`: переход к товару на сайте Магнита — редирект с установкой cookies магазина и открытие товара во внешнем браузере.

### Modified Capabilities
Нет — в `openspec/specs/` пока нет спецификаций. Требования к отмене и прогрессу заданий добавляются как ADDED в `scan-jobs`, которую вводит изменение `fix-data-integrity-bugs`.

## Impact

- `src/server/database.py` — `create_engine` и обработчик события `connect`.
- `src/server/main.py` — `redirect_to_product`, `open_product_in_browser`.
- `src/server/routes/catalog.py` — `_fetch_and_update_categories_background`, проверка отмены в `scan_all_stores`.
- `src/server/services/catalog_scanner.py` — `_update_job_progress`, проверка отмены.
- Файлы `magnit.db-wal` и `magnit.db-shm` рядом с БД — добавить в `.gitignore`.
- Зависимостей не добавляется. Применять после `fix-data-integrity-bugs`: используется её `scan-jobs`, правятся те же функции.
