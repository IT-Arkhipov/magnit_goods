# Design

## Context

Правило наличия уже реализовано на сервере: `product_query.py:build_product_query` без `include_out_of_stock` фильтрует `in_stock IS TRUE AND quantity > 0`, `get_products_stats` считает наличие так же. Страница `/products` запрашивает отсутствующие товары только при фильтре «Нет в наличии».

Утечка — в режиме сравнения. Цены магазинов берутся из `GET /api/products/multi-prices` (`routes/catalog.py:get_multi_store_prices`), который отдаёт все строки. В `products.html`:
- `renderProductsList(products, selectedStores, allStorePrices, storeInfoMap, listDiv)` собирает `productPrices` из `allStorePrices` только по условию `if (priceInfo)`, а затем на тех же данных строит `minPrice`, `savingsPercent` и ячейки;
- `renderSimpleList` (fallback) делает то же самое;
- фильтр «экономия ≥ N%» собирает цены из `allStorePrices` по условию `priceInfo.price`;
- тултип подменяет `quantity=0` подписью «в наличии», если `in_stock !== false`.

Примечание: в файле две функции `renderProductsList`; объявление ниже (~стр. 2154) перекрывает верхнее (~стр. 1051), поэтому правки делаются в нижнем.

## Goals / Non-Goals

**Goals:**
- Не показывать и не учитывать в сравнении цены магазинов без остатка.
- Убрать подпись «в наличии» для нулевого остатка.

**Non-Goals:**
- Не менять `multi-prices`, `product_query.py`, `get_products_stats()` и контракт API.
- Не удалять дублирующую верхнюю `renderProductsList` (отдельная чистка).
- Не трогать список покупок (`base.html:validateShoppingList`).

## Decisions

**1. Один предикат на фронтенде.** Добавить в `products.html` хелпер `hasStock(priceInfo)` = `priceInfo && priceInfo.in_stock !== false && priceInfo.quantity > 0`. При `stockFilter === 'out_of_stock'` предикат не применяется. Повторяет серверное правило `build_product_query`.

**2. Фильтровать при сборке `productPrices`.** В обоих рендерах заменить `if (priceInfo)` на проверку предиката. Тогда ячейка, минимальная цена, подсветка и экономия автоматически используют только цены с остатком, а для отсеянного магазина работает уже существующая ветка «-».

**3. Фильтр экономии использует тот же предикат.**

**4. Тултип.** Убрать подмену `quantity=0` → «в наличии»: такие цены больше не рендерятся, а при фильтре «Нет в наличии» правдивее показать «0».

**Альтернатива — фильтровать в `multi-prices` на сервере.** Отклонена: сломает `validateShoppingList`, который отличает «нет в наличии» от «не найден» по возвращённой строке с `quantity=0`.

## Risks / Trade-offs

**[Risk] Товар есть в выдаче магазина A, но во всех остальных отсутствует** → строка остаётся, в ячейках других магазинов «-». Это ожидаемо.
**[Risk] Правило на фронте разойдётся с серверным** → предикат в одном месте с комментарием-ссылкой на `build_product_query`.

## Migration Plan

Только шаблон: изменить `products.html`, перезагрузить страницу. Откат — вернуть файл.

## Open Questions

- Показывать ли вместо «-» отдельную метку «нет в наличии»? Отложено.
