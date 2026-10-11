# Tasks: исправить оставшиеся 38 ошибок ruff в src/

## 1. Подготовка

- [x] 1.1 Зафиксировать baseline: `ruff check src/ --output-format=concise` — сохранить вывод (38 ошибок) для сверки после правок

## 2. Автофикс F401 + F541 (25×)

- [x] 2.1 Прогнать `ruff check src/ --select F401,F541 --fix` и проверить `git diff`: удалены только неиспользуемые импорты и префиксы `f` у f-string без плейсхолдеров, логика не тронута
- [x] 2.2 Проверить `ruff check src/ --select F401,F541` — 0 сообщений, и `python -m py_compile` для всех изменённых файлов (`src/server/database.py`, `src/server/routes/catalog.py`, `src/server/routes/prices.py`, `src/server/scheduler.py`, `src/server/services/catalog_scanner.py`, `src/server/services/catalog_updater.py`, `src/server/services/magnit_api.py`, `src/scripts/verify_categories.py`, `src/server/services/category_verifier.py`, `src/server/services/product_opener.py`) проходит

## 3. F841: удалить мёртвые присваивания (2×)

- [x] 3.1 В `src/server/services/catalog_scanner.py` удалить строку `yesterday = today - timedelta(days=1)` (в функции расчёта previous_day_prices) и проверить `ruff check src/server/services/catalog_scanner.py --select F841` — 0 сообщений
- [x] 3.2 В `src/server/services/magnit_api.py` удалить строку `product_name = item.get("name") or item.get("title", "")` и проверить `ruff check src/server/services/magnit_api.py --select F841` — 0 сообщений

## 4. E722: bare except → except Exception (5×)

- [x] 4.1 В `src/server/services/store_selector.py` заменить все пять `except:` (в блоках перебора Playwright-элементов: выбор рецепта, клик кнопки, ввод адреса, выбор типа магазина, сбор магазинов) на `except Exception:` и проверить `ruff check src/server/services/store_selector.py --select E722` — 0 сообщений, `python -m py_compile` проходит

## 5. E711/E712: noqa для SQL-выражений SQLAlchemy (6×)

- [x] 5.1 В `src/server/database.py` (`Store.shop_type != None` в count-проверке заполненных магазинов) добавить `# noqa: E711` на строку сравнения колонки и проверить `ruff check src/server/database.py --select E711` — 0 сообщений
- [x] 5.2 В `src/server/routes/catalog.py` добавить `# noqa: E711` на два фильтра `Category.parent_id != None` (в проверке child_ids и в tracked_cats) и `# noqa: E712` на три SQL-сравнения с True (`Category.is_tracked == True` в count, `case((Product.in_stock == True, 1), ...)`, `Store.is_active == True` в выборе активного магазина) — SQL-выражения не менять; проверить `ruff check src/server/routes/catalog.py --select E711,E712` — 0 сообщений
- [x] 5.3 Проверить компиляцию `python -m py_compile src/server/database.py src/server/routes/catalog.py`

## 6. Итоговая верификация

- [x] 6.1 Прогнать `ruff check src/` — 0 сообщений (exit 0)
- [x] 6.2 Проверить загрузку приложения: `python -c "import src.server.main"` — без ImportError/SyntaxError (apscheduler может отсутствовать в окружении — это предсуществующая проблема, не блокирует: проверить `python -m py_compile src/server/main.py` и импорт затронутых модулей `python -c "import src.server.routes.catalog, src.server.routes.prices, src.server.scheduler, src.server.services.store_selector, src.server.services.catalog_scanner, src.server.services.magnit_api"`)

## Workflow follow-up

- Закоммитить правки по классам (F401+F541 → F841 → E722 → E711/E712) согласно design.md § Decisions.5
- Архивировать изменение после подтверждения reviewer'ом
