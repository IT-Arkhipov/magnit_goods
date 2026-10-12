# Design

## Context

Мотивация — см. proposal.md; требования — в specs/. Текущее состояние, которое определяет подход:

- **Тип магазина.** Нормализация есть только внутри `MagnitAPIClient.search`. `CatalogScanner._fetch_category_data` и `CatalogUpdater.fetch_category_data` отправляют сырое значение, а у `CatalogUpdater` ещё и свой `requests.Session`.
- **Значения по умолчанию.** `"MM"` в `magnit_api.py`, `"Магнит"` в `catalog_scanner.py`, `"9"` и магазин `"210117"` в `catalog_updater.py`, `"6"` в fallback-ветке `routes/catalog.py`.
- **Формат `STORE_TYPE`.** `POST /api/stores/select` пишет в `.env` русское название — так же тип хранится в `stores.store_type`.
- **Отметки категорий.** `POST /api/categories/update-tracking` снимает `is_tracked` со всех корней, а `scan_categories` фильтрует по отмеченным корням.
- **Тип при сканировании.** `CatalogScanner.__init__` берёт тип первого магазина с данным кодом.
- **Миграции.** Функции глушат исключения внутри себя, поэтому `_run_migration` не видит сбоев.
- **Загрузка категорий.** `load_catalog_from_json` ждёт `data["root_categories"]`, а файл — плоский массив. `CatalogUpdater.load_root_categories_from_file` уже читает фактический формат.

## Goals / Non-Goals

**Goals:**
- Одна функция нормализации типа, один клиент API для всех запросов каталога, одно определение набора отслеживаемых категорий.
- Миграции, честно сообщающие о сбоях.

**Non-Goals:**
- Ключ товара `(product_id, store_code)` не меняется. Два магазина с одним кодом и разными типами по-прежнему делят строки `products`. Это отдельная задача с миграцией данных — фиксируем её в DEVELOPMENT.md как техдолг.
- Объединение дублирующих роутов `/categories/scan` и `/update-catalog`: шаг 4.2 PLAN_FIXES.
- Изменение формата `STORE_TYPE` в `.env`: русское название остаётся каноническим.

## Decisions

### D1. Нормализация типа — `constants.resolve_store_type_code`
```
resolve_store_type_code(value: str | None) -> str
```
Порядок разбора: API-код (`STORE_TYPE_MAP`) → русское название; русское название (`STORE_TYPE_CODES`) → `str(код)`; строка, совпадающая с одним из числовых кодов, → как есть. Если значение пустое, берётся `get_configured_store_type()`: `os.getenv("STORE_TYPE")` читается в момент вызова, а не при импорте, потому что `.env` загружается в `main.py`. Если не задано и оно — `DEFAULT_STORE_TYPE = "Магнит"`. Нераспознанное значение даёт warning в лог и `DEFAULT_STORE_TYPE`.
*Альтернатива:* хранить в БД API-коды. Отклонено: потребовало бы миграции `stores.store_type` и правок UI ради внутреннего формата.

### D2. Все запросы каталога — через `MagnitAPIClient`
Добавляем публичный метод `MagnitAPIClient.fetch_category_raw(category_id) -> dict | None`. Он вызывает `_rate_limit_wait()`, строит payload через `resolve_store_type_code` и возвращает сырой JSON с `category` и `fastCategoriesExtended`.
- `CatalogScanner._fetch_category_data` делегирует ему.
- `CatalogUpdater` вместо собственного `requests.Session` создаёт `MagnitAPIClient(store_code, store_type)`, и его `fetch_category_data` тоже делегирует.

Payload формирует общий приватный хелпер, чтобы `search` и `fetch_category_raw` не расходились.
Из `CatalogUpdater` удаляем дефолты `210117`/`"9"`. `_fetch_and_update_categories_background` выбирает магазин так: `STORE_CODE` из окружения → иначе первый активный магазин с его собственным `store_type` (ветка с `"6"` удаляется) → иначе статус ошибки «не выбран магазин».

### D3. Набор отслеживаемых категорий — `get_tracked_category_magnit_ids(db)`
Функция в `services/catalog_scanner.py` возвращает `magnit_id` категорий с `is_tracked=True AND parent_id IS NOT NULL AND magnit_id IS NOT NULL`, упорядоченные по `id`. Её используют:
- `CatalogScanner.scan_products` при `category_ids=None, tracked_only=True`;
- `scan_prices_in_store`;
- `scan_all_stores`;
- `scheduler` (через `scan_products(category_ids=None, tracked_only=True)`).

При `tracked_only=False` и `category_ids=None` поведение прежнее (все категории). Это явный режим полного скана, он вне контракта «отслеживаемых».

### D4. Синхронизация подкатегорий — все корни с `magnit_id`
В `scan_categories` фильтр `Category.is_tracked == True` убираем, остаётся `parent_id IS NULL AND magnit_id IS NOT NULL`. Код обновления и удаления подкатегорий уже не трогает `is_tracked` существующих детей.
*Альтернатива:* корни, у которых есть хотя бы один отмеченный ребёнок. Отклонено: новые подкатегории в неотмеченных корнях никогда бы не появились в UI.

### D5. `load_catalog_from_json` — только корни из плоского массива
Чтение файла переиспользует `CatalogUpdater.load_root_categories_from_file`; обработка подкатегорий удаляется, потому что в файле их нет. Upsert корней по `magnit_id` без изменения `is_tracked`. `FileNotFoundError` по-прежнему превращается в 404; сообщения и docstrings исправляются на `categories.json`. `print` заменяется на `logger`.

### D6. Идентичность магазина
- В модели `Store`: `UniqueConstraint("store_code", "store_type", name="uq_store_code_type")`.
- Миграция `add_store_code_type_unique`: находит группы дубликатов, оставляет строку с минимальным `created_at` (при равенстве — минимальный `rowid`), остальные удаляет с логированием, затем выполняет `CREATE UNIQUE INDEX IF NOT EXISTS uq_store_code_type ON stores(store_code, store_type)`.
- `create_store`, `add_selected_stores`, `preview_stores` проверяют существование по паре. Preview дедуплицирует по `(code, type_name)`.
- `CatalogScanner.__init__(..., store_type=None)`: если тип передан явно, используется он. Если не передан и магазин с таким кодом один — берётся его тип. Если таких магазинов несколько — `ValueError("Несколько магазинов с кодом X, укажите store_type")`. Если ни одного — `get_configured_store_type()`.
- `scan_all_stores` передаёт `store.store_type`. `POST /api/catalog/scan`, `/catalog/scan-prices`, `/prices/update` получают необязательный query-параметр `store_type`; на неоднозначность отвечают 400. Планировщик передаёт `get_configured_store_type()`.

### D7. `PUT /api/stores/{id}`
Если в теле есть `store_type` или `full_address`, отличные от текущих, — 400 «Нельзя изменить тип или адрес — удалите и добавьте магазин заново». Совпадающие значения допускаются, поэтому идемпотентный PUT целиком работает. `id` и `shop_type` не пересчитываются: они не могут измениться.
*Альтернатива:* пересчитывать `id`, то есть менять PK. Отклонено: ID используется в UI и `delete-batch`, менять PK в SQLAlchemy-сессии хрупко.

### D8. Типы для preview
`constants.PREVIEW_STORE_TYPES = ["Магнит", "Мини", "Семейный", "Экстра", "Моя цена", "М.Косметик"]`. `STORE_TYPE_TO_CODE` в `schemas.py` строится из `constants.STORE_TYPE_MAP`, отфильтрованной по этому списку; фантомный «Мигом» удаляется. Валидация выполняется в `preview_stores` (400 со списком неподдерживаемых), а не pydantic-валидатором: тот вернул бы 422. Если список пуст, используются все типы из `PREVIEW_STORE_TYPES`.

### D9. `scan_all_stores` — один вызов `scan_products` на магазин
`scan_products` получает необязательный колбэк `on_category_start(index, total, magnit_id)`, который вызывается перед каждой категорией. `scan_all_stores` в нём обновляет `current_category_*` и общий `progress` (`(store_idx * total_cats + index) / total_ops`). Пометка отсутствующих товаров и очистка выполняются в конце `scan_products`, то есть один раз на магазин. Проверку отмены между магазинами оставляем; внутри магазина её делает `scan_products`.

### D10. Контракт миграций
- Функция миграции либо успешно возвращается, либо бросает исключение. Внутренние «глушилки» (`except: print(...)` вокруг всей функции) удаляются.
- Ожидаемые идемпотентные случаи («колонка уже есть») проверяются через `inspect(engine)` до `ALTER`, а не через перехват ошибки.
- `_run_migration` оборачивает вызов в `try`: при исключении делает `db.rollback()`, пишет `logger.warning("Миграция %s не выполнена: %s", ...)` и не регистрирует миграцию. При успехе — регистрирует.
- Все `print` в `database.py` переходят на `logger`.
- Новые миграции в конце списка: `ensure_product_last_scan_index` (`CREATE INDEX IF NOT EXISTS ix_product_last_scan ...`) и `add_store_code_type_unique`.
- В `migrate_categories` условие «структура уже правильная» переписывается без несуществующей колонки `code`: пересоздание выполняется только при наличии устаревших `category_id` или `store_code`.

## Risks / Trade-offs

- **Схлопывание дубликатов магазинов удаляет строки.** → Сохраняется самая ранняя запись, удалённые пишутся в лог полностью (code, type, address). Товары не затрагиваются: они ключуются по `store_code`.
- **BREAKING-изменения API** (`PUT /stores`, `preview`). → Текущий UI не меняет тип или адрес через PUT и шлёт в preview только поддерживаемые типы, поэтому проверяем UI вручную. Изменения описываются в `docs/API.md`.
- **Миграции, ранее «успешные» при сбое, остаются зарегистрированными.** → Новый контракт действует только для ещё не выполненных миграций. Именно поэтому недостающий индекс создаётся отдельной новой миграцией, а не повтором старой.
- **Неоднозначный `store_code` в ручных эндпоинтах теперь даёт 400.** → Сообщение подсказывает передать `store_type`. UI вызывает только `scan-all-stores`, где тип известен.
- **Синхронизация всех корней увеличивает число запросов к API** (около 20 корней × 0.6–1 с). → Приемлемо для еженедельного задания и ручного запуска.

## Migration Plan

1. Развёртывание — перезапуск сервера. При старте выполняются две новые миграции. По логу проверить, были ли удалены дубликаты магазинов.
2. Откат — `git revert`. Уникальный индекс `uq_store_code_type` остаётся в БД и совместим со старым кодом: старый код дедуплицировал строже, только по коду.
