# PORTING.md — экспорт под «Магнит Косметик»

> Цель: заставить проект мониторить каталог сети **Магнит Косметик** (внутр. тип
> `М.Косметик` / API-код `DG` / числовой код `3`).
> Статус анализа: **API аналогичное** (`/webgate/v2/goods/search`, `/webgate/v1/stores-facade/search/detail`).

---

## 🔑 Главный вывод

Проект **уже умеет «М.Косметик»** на уровне кода: в `constants.py` тип определён
(`"М.Косметик": 3`, `"DG": "М.Косметик"`), а `MagnitAPIClient` прокидывает
`store_type` в payload без изменений. Значит задача — **не переписать клиент**,
а решить вопрос **изоляции данных** и **деревьев категорий**.

Есть два принципиально разных сценария. Выбор зависит от одного вопроса:
**нужно ли мониторить «Магнит у дома» и «Косметик» одновременно?**

| | Сценарий А: один сервер, оба типа | Сценарий Б: отдельный экземпляр |
|---|---|---|
| Когда выбирать | Нужен единый UI, сравнение цен | Косметик живёт отдельно |
| Риск | 🔴 Конфликт категорий (см. ниже) | 🟢 Минимальный |
| Объём работ | Средний (нужен рефакторинг категорий) | Низкий (копия + конфиг) |

---

## 🟢 Сценарий Б (рекомендую): отдельный экземпляр

Клонируем проект в соседнюю папку (`magnit_cosmetic`), поднимаем на другом
порту со своей БД. Код меняется минимально.

### Шаг 1. Клонирование
```
D:\pythonProjects\magnit_cosmetic\      # копия без .git и venv
src\data\magnit.db                       # УДАЛИТЬ — БД начнётся с нуля
src\data\categories.json                 # ЗАМЕНИТЬ на дерево Косметика (шаг 3)
.env                                      # свой (шаг 2)
```
Порт в `main.py` / uvicorn: `8001`.

### Шаг 2. `.env`
```
STORE_CODE=<код магазина Косметик>     # из /api/stores/preview
STORE_TYPE=DG                          # API-код; либо "М.Косметик"
GOODS_URL=https://magnit.ru/webgate/v2/goods/search
CORS_ORIGINS=*
```
> `STORE_TYPE` можно задать и как `DG`, и как `М.Косметик` — `MagnitAPIClient.search()`
> нормализует оба варианта через `STORE_TYPE_MAP` → `API_STORE_TYPE_CODE`.

### Шаг 3. Категории — ключевой шаг
У «Косметика» **своё дерево категорий** (косметика/бытовая химия ≠ продуктовое).
`categories.json` сейчас — продуктовое дерево. Порядок получения актуального:

1. Добавить в БД любой магазин Косметик (`POST /api/stores/preview` → `/add-selected`).
2. Вызвать `POST /api/categories/fetch-magnit-ids` — он дёргает
   `CatalogUpdater.replace_all_categories()` с `store_type` из `.env` и
   перезапишет `categories` + `categories.json` деревом Косметика.
3. Проверить `GET /api/categories/tree`.

⚠️ Перед шагом 3 файл `categories.json` — **корневой источник** для
`CatalogUpdater.load_root_categories_from_file()`. Если он остался продуктовый,
апдейтер будет тянуть продуктовые `magnit_id`, которых у Косметика нет
(ответы `invalid_service_pair`). Поэтому сначала — чистый `fetch-magnit-ids`
на пустой БД с `store_type=DG`.

### Шаг 4. Проверить захардкоженные дефолты (не критично, но почистить)
| Файл | Что | На что |
|---|---|---|
| `services/catalog_updater.py` | `store_code="210117"`, `store_type="9"` (это «Моя цена»!) | `store_type="DG"` |
| `services/category_verifier.py` | `MAGNIT_URL`, `API_ENDPOINT` | совпадают — ОК |
| `services/store_selector.py` | `type_mapping` без «М.Косметик» | добавить `"М.Косметик": ["Косметик","М.Косметик"]` |

`store_selector.py` — legacy (Playwright-выбор магазина); основной путь —
`StoresAPI` через `/api/stores/preview`, который тип уже поддерживает.

---

## 🔴 Сценарий А: один сервер, оба типа

Возможен, потому что `store_type` хранится в таблице `stores`, а
`CatalogScanner` читает тип из БД по `store_code`
(`catalog_scanner.py:60-64`). Товары уже разделены по `store_code`
(uniqueness `uq_product_store`). **Но категории — узкое место:**

### Проблема: категории универсальные
`Category` не привязан к магазину/типу. `replace_all_categories()` делает
`db.query(Category).delete()` — **затирает всё дерево**. Если гонять апдейтер
то для «Магнит», то для «Косметик», они перезаписывают друг друга, а
`Product.category_id` начинает ссылаться на чужие категории.

### Что нужно доработать (порядок)
1. **Мигрировать `Category` под тип сети.** Добавить колонку
   `network` (`"magnit"` / `"kosmetik"`) или `store_type`; уникальный индекс
   `(magnit_id, network)`; миграцию в `database.py` (по образцу существующих 12).
2. **Пропустить `network` в `CatalogUpdater`** — `replace_all_categories(network=...)`
   чистит/пишет только свой сегмент.
3. **`_save_products`** — искать категорию по `(magnit_id, network)`, а не только
   по `magnit_id` (`catalog_scanner.py:_save_products`).
4. **`GET /api/categories*`** — фильтр по сети (из активного магазина).
5. UI-селекторы магазинов — показывать категориное дерево своего типа.

Объём: ~1 миграция + правки в `catalog_updater.py`, `catalog_scanner.py`,
`routes/catalog.py`, шаблонах. Это реальный рефакторинг, не «галочка».

---

## Чек-лист «что вообще завязано на Магнит» (инвентарь)

Полный список точек, если понадобится менять контракт API:

- **`constants.py`** — `STORE_TYPE_CODES`, `STORE_TYPE_MAP`, `API_STORE_TYPE_CODE`.
  Косметик уже есть (`DG`/`3`). ✅
- **`services/magnit_api.py`**
  - `MagnitAPIClient.search()` → `POST /webgate/v2/goods/search`, payload:
    `storeCode`, `storeType`, `catalogType:"1"`, `categories[]`, `pagination`,
    `includeAdultGoods`. Разбор: `items[]` (товары) / `fastCategoriesExtended`
    (подкатегории) / `pagination.nextOffset`.
  - `_parse_product()` — цены в **копейках** (`/100`), поля `price`, `orderProperties`,
    `ratings`, `weighted`, `gallery[0].url`, `seoCode`, `service`.
  - `StoresAPI.search_stores()` → `POST /webgate/v1/stores-facade/search/detail`,
    разбор `data[].externalId.storeCode`, `storeTypeV2`.
  - Заголовки (`Referer/Origin: magnit.ru`, `X-Client-Name: magnit`, `X-New-Magnit`).
  - Rate limiting: 0.5s + random(0.1–0.5) — **не убирать**.
- **`services/catalog_scanner.py`** — `scan_categories()` / `scan_products()`;
  тип берётся из БД по `store_code`; обработка `invalid_service_pair` (категория
  недоступна типу) — уже есть, это и есть защита при смешении типов. ✅
- **`services/catalog_updater.py`** — захардкожен `base_url`, дефолты `store_code`/`store_type`.
- **`services/category_verifier.py`, `store_selector.py`, `product_opener.py`** —
  Playwright + селекторы magnit.ru (legacy-путь, для Косметика не обязателен).
- **`main.py`** — `/redirect-to-product` ставит cookies `shopCode`, `x_shop_type`;
  `title="Магнит Goods"`; `/open-product-in-browser`.
- **`.env`** — `STORE_CODE`, `STORE_TYPE`.

---

## ⚠️ Открытые вопросы (проверить живьём ДО портирования)

Эти вещи нельзя узнать из кода — только перехватом реальных запросов сайта
(DevTools → Network на magnit.ru с выбранным магазином Косметик):

1. **`catalogType`** 🔴 — в payload жёстко зашит `"1"` в трёх местах:
   `magnit_api.py` (`search()`), `catalog_scanner.py` (`_fetch_category_data()`),
   `catalog_updater.py` (`fetch_category_data()`). У Косметика каталог может
   иметь другой `catalogType`. Если значение иное — API вернёт пустые категории.
   Проверка: открыть сайт с магазином Косметик, найти запрос
   `/webgate/v2/goods/search`, посмотреть `catalogType` в payload.
2. **Формат URL товара** 🔴 — захардкожен в `templates/products.html` (3 места):
   `https://magnit.ru/product/{product_id}-{seoCode}?shopCode=...&shopType={shop_type}`.
   Домен общий, но путь/параметры для Косметика не проверены. Проверка: открыть
   любой товар Косметика на сайте, сравнить URL.
3. **Ответ API для `storeType=DG`** 🟠 — что реально возвращают
   `fastCategoriesExtended` (дерево категорий) и `items` (товары), цены в
   копейках ли, есть ли `externalId.storeCode` в `stores-facade`. Проверка:
   один ручной POST через Swagger или curl с кодом реального магазина.

---

## Smoke-тест после портирования (Сценарий Б)

Порядок проверки, каждый шаг должен пройти до следующего:

1. Сервер стартует, в логах — 12 миграций, `init_scheduler` с кодом Косметика.
2. `GET /api/stores` — пусто (чистая БД).
3. `POST /api/stores/preview` с `store_types=["М.Косметик"]` — вернулись
   магазины с типом «М.Косметик» (не «Магнит»!). Если вернулись продуктовые —
   проблема в `STORE_TYPE`/`storeTypeListV2`.
4. `POST /api/stores/add-selected` — магазин сохранён, `shop_type=3`.
5. `POST /api/categories/fetch-magnit-ids` → статус → `GET /api/categories/tree` —
   дерево **косметическое** (шампуни/кремы, НЕ «Молочная продукция»).
6. Отметить 1–2 категории tracked → `POST /api/catalog/scan?store_code=X` —
   товары сохранились, цены адекватные (не 0, не копейки).
7. `GET /api/products/stats?store_code=X` — счётчики сходятся со сканом.
8. На `/products` — ссылка товара ведёт на корректную страницу magnit.ru
   с выбранным магазином Косметик (проверка п.2 из открытых вопросов).
9. `POST /api/catalog/scan-prices?store_code=X` повторно — `price_change_percent`
   считается корректно.

---

## Рекомендация

Для «Косметик» с аналогичным API начинайте со **Сценария Б**: копья проект →
`.env` с `STORE_TYPE=DG` → чистая БД → `fetch-magnit-ids` → `preview/add-selected`
магазина → `catalog/scan`. Код правится на ~5 строк (дефолты + `type_mapping`).
К сценарию А переходить только если принципиально нужен общий UI и сравнение цен
двух сетей — тогда обязательна миграция `Category.network`.
