# Tasks

## 1. SQLite: WAL и busy_timeout

- [x] 1.1 В `database.py` добавить `timeout: 30` в `connect_args` и обработчик `connect` с `PRAGMA journal_mode=WAL` и `busy_timeout=30000` (D1). Проверка: после старта `PRAGMA journal_mode` в `sqlite3 src/data/magnit.db` возвращает `wal`.
- [x] 1.2 Добавить `src/data/*.db-wal` и `src/data/*.db-shm` в `.gitignore`; описать WAL, локальное хранение БД и правило резервного копирования в `docs/DEPLOYMENT.md` и `docs/DATABASE.md`. Проверка: `git status` не показывает `-wal`/`-shm` после работы сервера.
- [x] 1.3 Проверить конкурентный доступ: запустить `POST /api/catalog/scan-all-stores` и параллельно в цикле (например, `curl` в PowerShell-цикле 60 с) вызывать `GET /api/products` и `GET /api/jobs/active`. Проверка: все ответы 200, в логе нет `database is locked`.

## 2. Сканер: отмена и прогресс

- [x] 2.1 Добавить `CatalogScanner._is_cancelled()` и заменить обе связки `expire_all()` + перечитывание `ScanJob`; имя категории брать из словаря, загруженного до цикла (D2). Аналогично переделать проверку отмены в `scan_all_stores`. Проверка: `grep -rn expire_all src/server` пуст (кроме `services/jobs.py`, если там используется); отмена во время скана большой категории останавливает запросы — в DEBUG-логе после отмены не более одного `POST .../goods/search`.
- [x] 2.2 Ввести троттлинг `_update_job_progress` / `_update_job_progress_full` с `force` и сбросом накопленного прогресса при выходе (D3); проставить `force=True` для обязательных сообщений. Проверка: при опросе `GET /api/jobs/{id}` раз в секунду сообщение меняется не реже раза в 5 с, итоговое «Товары сохранены: N шт.» появляется сразу; число коммитов за скан (счётчик в DEBUG-логе или `PRAGMA wal_checkpoint` статистика) заметно меньше прежнего.
- [x] 2.3 Сравнить результат скана до и после: на копии БД просканировать один магазин старым и новым кодом. Проверка: `items_scanned/added/updated` и число записей `price_history` за день совпадают.

## 3. Ссылки на товар и фоновые потоки

- [x] 3.1 Добавить `_is_magnit_url` и проверку в `redirect_to_product` и `open_product_in_browser` (D4). Проверка: `url=https://evil.example/` и `url=https://magnit.ru.evil.example/` → 400 без `Set-Cookie`; `https://magnit.ru/product/123` → 307 с cookies; `product_url=file:///C:/` → 400.
- [x] 3.2 Добавить `run_logged` (`utils/threads.py`) и запускать через неё потоки открытия товара и замены каталога; `print` в `product_opener.py` → `logger`, исключение пробрасывать после логирования (D5). Проверка: вызвать `/open-product-in-browser` с недостижимым `https://magnit.ru/...` при выключенной сети или без установленного Chromium → traceback в логе, сервер отвечает на следующие запросы.
- [x] 3.3 Описать ограничение ссылок в `docs/API.md` (раздел роутов `main.py`); отметить шаги 2.1, 3.2, 5.2, 5.3, 6.1 в `docs/PLAN_FIXES_2026-09-27.md` как закрытые. Проверка: документ соответствует D4.

## 4. Итоговая проверка

- [x] 4.1 `ruff check src/` чист; сервер стартует; полный цикл «Сканировать все магазины» с наблюдением на `/jobs` и отменой второго запуска проходит без ошибок в логе.

## Workflow follow-up

- Применять после `fix-data-integrity-bugs` (общие функции сканера и `scan-jobs`).
- Коммит только после согласования с пользователем, формат `фикс: ...` / `оптим: ...`.
- Архивировать после проверки (`/opsx:archive`).
