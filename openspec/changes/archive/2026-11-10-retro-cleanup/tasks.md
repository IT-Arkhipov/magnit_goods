# Tasks

## 1. Режим «Последнее изменение»
- [x] 1.1 `last_change_price` в ответе `multi-prices`
- [x] 1.2 `priceChangeForMode` в products.html: таблица, запасной список, фильтр экономии, окно сравнения
- [x] 1.3 Удалён мёртвый загрузчик и рендер товаров

## 2. Планировщик и категории
- [x] 2.1 `services/store_scan.py`: создание и выполнение сканирования всех магазинов (роут и планировщик)
- [x] 2.2 Статус полной замены каталога перенесён в `catalog_updater.py`, флаг берётся под блокировкой
- [x] 2.3 Планировщик: `scan_all_stores` 8:00, `update_catalog` вс 6:00, без `STORE_CODE`
- [x] 2.4 Удалены `update-catalog`, `scan`, `load-from-json`, `scan_categories`, разбор категорий в `search`

## 3. Playwright
- [x] 3.1 Удалены `/redirect-to-product`, `/open-product-in-browser`, `product_opener.py`, `verify_categories.py`, зависимость playwright

## 4. Данные магазинов
- [x] 4.1 `delete_store_products` при удалении магазина (одиночном и пакетном)
- [x] 4.2 Миграция `cleanup_orphan_store_products`

## 5. Прочее
- [x] 5.1 `MagnitAPIError` и повтор только временных ошибок
- [x] 5.2 Документация и спецификации
