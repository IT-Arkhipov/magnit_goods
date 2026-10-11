# Proposal

## Why

`ruff check src/` сообщает 38 оставшихся ошибок линтера после того, как первые два цикла (F401 в `routes/stores.py`, F841 в сайдбаре) сократили исходный список с 40. Неисправленные предупреждения накапливают шум в lint-выводе, маскируют реальные проблемы и мешают включить ruff в регулярную практику проверки кода.

## What Changes

- **F401 (16×, auto-fixable)** — удалить неиспользуемые импорты в 8 модулях: `database.py`, `routes/catalog.py` (func, traceback), `routes/prices.py` (Body, date, timedelta, ScanJobResponse), `scheduler.py` (Session), `services/catalog_scanner.py` (func, os, traceback ×2), `services/catalog_updater.py` (os, Store), `services/magnit_api.py` (REVERSE_STORE_TYPE_MAP)
- **F541 (11×, auto-fixable)** — убрать префикс `f` у f-string без плейсхолдеров в `scripts/verify_categories.py`, `routes/catalog.py`, `scheduler.py`, `services/catalog_scanner.py`, `services/category_verifier.py`, `services/product_opener.py`
- **E711 (3×)** — заменить сравнения `== None` / `!= None` на `is None` / `is not None` в `database.py`, `routes/catalog.py` (×2)
- **E712 (3×)** — заменить `== True` на истинностные проверки (`Category.is_tracked`, `Product.in_stock`, `Store.is_active`) в `routes/catalog.py`
- **F841 (2×)** — удалить присваивания неиспользуемых локальных переменных `yesterday` (`catalog_scanner.py`) и `product_name` (`magnit_api.py`)
- **E722 (5×)** — заменить bare `except:` на `except Exception:` в `services/store_selector.py` (строки 67, 88, 114, 150, 186)

Все правки — чистая стилистика/гигиена кода; поведение API, контракты обработчиков и бизнес-логика не меняются.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
None.

Правки не изменяют специфицируемое поведение системы (чистый lint-фикс) — изменение объявляет `skip_specs: true`.

## Impact

- 11 модулей в `src/` — только локальные правки строк, на которые указывает ruff
- `services/store_selector.py` — единственная правка с содержательным нюансом (E722): bare `except` → `except Exception` меняет множество перехватываемых исключений (KeyboardInterrupt/SystemExit больше не проглатываются); это намеренное улучшение, детально обоснованное в design.md
- `routes/catalog.py` — правки E711/E712 в SQLAlchemy-запросах: для SQL-выражений `col == None` компилируется в `IS NULL` корректно, поэтому замена выполняется только там, где сравнение идёт с Python-значением, а не с колонкой (см. design.md)
- Никаких изменений зависимостей, схем БД, конфигурации или внешних интерфейсов
