# Tasks

## 1. Эталон ответов до изменений

- [x] 1.1 Сохранить в scratch-каталог (вне репозитория) ответы `GET /api/products?store_code=<код>&limit=20`, `...&search=молоко`, `...&search=МОЛОКО&sort_by=price`, `GET /api/products/stats?store_code=<код>`, `GET /api/prices/decreased?store_code=<код>&min_discount_percent=1`. Проверка: пять JSON-файлов с непустыми ответами.

## 2. Нормализованное название

- [x] 2.1 Добавить `Product.name_search` и миграцию `add_product_name_search` с заполнением батчами (D1). Проверка: после рестарта `SELECT count(*) FROM products WHERE name_search IS NULL` = 0; повторный рестарт миграцию не выполняет.
- [x] 2.2 Записывать `name_search` в `_save_products` (insert и update) (D1). Проверка: через SQLite-клиент изменить `name_search` у товара на мусор → скан магазина → значение снова равно `casefold(name)`.

## 3. Сервис выборки товаров

- [x] 3.1 Создать `services/product_query.py` (`ProductFilters`, `build_product_query`, `list_products`, `product_to_list_item`, `get_products_stats`) с поиском через `name_search LIKE` и экранированием `%`, `_`, `\` (D1, D2). Проверка: `ruff check src/`; поиск `search=%` не возвращает все товары подряд, а только содержащие `%`.
- [x] 3.2 Перевести роуты `list_products` и `get_products_stats` на сервис. Проверка: ответы совпадают с эталонами из 1.1 (сравнение JSON); сценарий пагинации поиска из `specs/product-catalog` выполняется; время ответа `search=молоко` меньше, чем до изменений.

## 4. Схемы ответов

- [x] 4.1 Описать `ProductListItem`, `ProductStats`, `DecreasedPriceItem` в `schemas.py` и подключить `response_model` к трём эндпоинтам (D3). Проверка: ответы совпадают с эталонами из 1.1 по ключам и значениям, в ответе нет `name_search`; в `/docs` у трёх эндпоинтов отображаются схемы.
- [x] 4.2 Проверить страницы `/products` (фильтры, поиск, режимы цен, сравнение магазинов) и `/shopping-list`. Проверка: в консоли браузера нет ошибок, данные отображаются как до изменений.

## 5. Категории

- [x] 5.1 Удалить `update_category_from_api`, `update_all_categories`, `update_catalog_from_api` из `catalog_updater.py` после проверки `grep` (D4). Проверка: `grep -rn "update_category_from_api\|update_all_categories" src/` пуст; `POST /api/categories/fetch-magnit-ids` работает.
- [x] 5.2 Ввести общую `_sync_subcategories`, пометить `/categories/scan` как `deprecated=True`, удалить алиасы `build-from-playwright`/`seed-from-playwright` (D5). Проверка: `/categories/scan` и `/categories/update-catalog` возвращают одинаковые ответы для одного магазина; `POST /api/categories/build-from-playwright` → 404/405; в `/docs` `scan` отмечен как deprecated.
- [x] 5.3 Заменить `!= None` на `.isnot(None)` и удалить соответствующие `# noqa: E711` (D6). Проверка: `grep -rn "!= None" src/server` пуст, `ruff check src/` чист.

## 6. Документация и итоговая проверка

- [x] 6.1 Обновить `docs/API.md` (удалённые алиасы — BREAKING, deprecated `/categories/scan`, схемы ответов), `docs/DATABASE.md` (`name_search`, миграция), `docs/SERVICES.md` (`product_query`); отметить шаги 4.1, 4.2, 5.1, 6.2, 6.3, 6.4 в `docs/PLAN_FIXES_2026-09-27.md` как закрытые. Проверка: документы соответствуют D1–D6.
- [x] 6.2 Итог: `ruff check src/` чист, сервер стартует, полный цикл (замена каталога → синхронизация подкатегорий → скан → поиск на `/products`) без ошибок в логе.

## Workflow follow-up

- Применять после `fix-data-integrity-bugs`, `unify-store-type-and-tracking`, `harden-runtime-reliability`; до `sync-docs-and-dead-code`.
- Коммит только после согласования с пользователем, формат `оптим: ...` / `рефактор: ...`.
- Архивировать после проверки (`/opsx:archive`).
