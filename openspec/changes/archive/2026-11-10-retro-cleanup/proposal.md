# Proposal

## Why

Ретроспектива 2026-11-10 показала: часть кода не используется интерфейсом и разошлась с документацией, а часть доработок жила в мёртвом коде. Режим «Последнее изменение» не работал в таблице товаров (логика была в подменённой функции), планировщик сканировал один магазин из `.env` и ни разу не срабатывал, товары удалённых магазинов не чистились.

## What Changes

- Режим «Последнее изменение» работает в таблице `/products`, фильтре экономии и окне сравнения (единая функция `priceChangeForMode`); `multi-prices` отдаёт `last_change_price`.
- Планировщик сканирует все активные магазины (ежедневно) и делает полную замену каталога (еженедельно); не зависит от `STORE_CODE`. `POST /api/stores/select` больше не трогает планировщик, поле `scheduler_updated` удалено.
- **BREAKING** удалены неиспользуемые интерфейсом эндпоинты: `POST /api/categories/update-catalog`, `POST /api/categories/scan`, `POST /api/categories/load-from-json`, `GET /redirect-to-product`, `GET /open-product-in-browser`; удалены зависимость Playwright, `product_opener.py`, `verify_categories.py`.
- Удаление магазина удаляет его товары и историю цен; миграция `cleanup_orphan_store_products` убирает накопленные.
- Сканер не повторяет запросы при детерминированных ошибках API (4xx, кроме 429).
- Полная замена каталога не запускается дважды одновременно.

## Capabilities

### New Capabilities
- нет

### Modified Capabilities
- `category-catalog`: обновление категорий — только полной заменой; защита от параллельного запуска
- `product-links`: остаются только прямые ссылки на сайт Магнита
- `runtime-config`: планировщик сканирует все магазины, выбор магазина задаёт источник каталога
- `scan-jobs`: сценарий отмены задания планировщика — для сканирования всех магазинов
- `store-registry`: удаление магазина удаляет его данные
- `product-catalog`: режим «Последнее изменение» в таблице
- `magnit-api-client`: повтор запросов только при временных ошибках

## Impact

`routes/catalog.py`, `routes/stores.py`, `routes/prices.py`, `main.py`, `scheduler.py`, новый `services/store_scan.py`, `services/catalog_updater.py` (статус замены), `catalog_scanner.py`, `magnit_api.py`, `database.py` (миграция), шаблоны `products.html`, `base.html`, `stores.html`; `requirements.txt` (без playwright); документация.
