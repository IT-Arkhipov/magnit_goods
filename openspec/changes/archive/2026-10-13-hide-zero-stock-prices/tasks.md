# Tasks

## 1. Сравнение по магазинам

- [x] 1.1 Добавить в `products.html` хелпер `hasStock(priceInfo)` (`in_stock !== false && quantity > 0`), не применяемый при фильтре «Нет в наличии»; комментарий со ссылкой на `product_query.py:build_product_query`
- [x] 1.2 В `renderProductsList(products, selectedStores, allStorePrices, …)` собирать `productPrices` только из цен, прошедших `hasStock`
- [x] 1.3 То же в `renderSimpleList`
- [x] 1.4 В фильтре «экономия ≥ N%» учитывать только цены, прошедшие `hasStock`
- [x] 1.5 Убрать подмену `quantity=0` → «в наличии» в тултипах обоих рендеров

## 2. Проверка

- [x] 2.1 `ruff check src/` — без новых замечаний (бэкенд не менялся)
- [x] 2.2 Сравнение двух магазинов, товар с `quantity=0` в одном из них: ячейка «-», минимальная цена и экономия считаются без неё
- [x] 2.3 Фильтр «Нет в наличии»: цены с нулевым остатком видны
- [x] 2.4 Список покупок (`/shopping-list`): проверка наличия по-прежнему помечает отсутствующие товары
- [x] 2.5 `openspec validate hide-zero-stock-prices` проходит
