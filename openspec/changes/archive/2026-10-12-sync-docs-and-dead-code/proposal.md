# Proposal

## Why

Инструкции для агентов (`AGENTS.md`, `CLAUDE.md`) и документация в `docs/` расходятся с кодом. Они описывают удалённые роуты, несуществующий файл `query_product.py`, неиспользуемую переменную `GOODS_URL`, неверный срок удаления устаревших товаров и запуск миграций «при каждом старте». Ссылки вида `file:line` давно разъехались с кодом. Кроме того, в коде осталось несколько неиспользуемых функций и констант. Агенты и разработчики принимают решения по этим документам, поэтому расхождения порождают новые ошибки (пункты 18–20 анализа 2026-10-12).

## What Changes

- **AGENTS.md**:
  - удалить `/test-discount`, `/test-stores-loading` и упоминание дублирующего `POST /api/stores` в `main.py`;
  - заменить «миграции выполняются при каждом старте» на описание реестра `schema_migrations`, после чего дублирующее уточнение в `CLAUDE.md` удалить;
  - исправить срок удаления устаревших товаров на `STALE_DAYS_DELETE` (6 дней) с описанием жизненного цикла из `constants.py`;
  - удалить из техдолга несуществующий `query_product.py`.
- **docs/** (`ARCHITECTURE.md`, `API.md`, `DATABASE.md`, `DEVELOPMENT.md`, `DEPLOYMENT.md`, `SERVICES.md`, `PORTING.md`) — те же исправления. Отдельно:
  - статус замены каталога хранится в памяти процесса, а не в `ScanJob` (поправить и `CLAUDE.md`);
  - удалить `GOODS_URL`.
- **`.env.example`** — удалить `GOODS_URL`, оставить `STORE_CODE`, `STORE_TYPE`, `CORS_ORIGINS` с комментариями о допустимых значениях.
- **Ссылки на код** во всех документах — формат `файл:функция` вместо `файл:строка`.
- **Удалить неиспользуемый код**:
  - `_cleanup_stale_jobs` (`routes/stores.py`);
  - `REVERSE_STORE_TYPE_MAP` (`constants.py`);
  - `MagnitAPIClient.set_store_code`;
  - `CatalogUpdater.update_all_categories`;
  - сервисную функцию `catalog_updater.update_catalog_from_api`.
- **Пометить как неиспользуемые, не удаляя**: `NotificationService` (для закомментированного `daily_report`) и `store_selector.py` (Playwright-сканер) — запись в `docs/DEVELOPMENT.md`.
- **Docstrings** эндпоинтов загрузки категорий: `magnit_catalog.json` → `categories.json`.

Поведение API, схема БД и бизнес-логика не меняются.

## Capabilities

### New Capabilities
Нет.

### Modified Capabilities
Нет. Изменение затрагивает только документацию и неиспользуемый код и объявляет `skip_specs: true`.

## Impact

- Документы: `AGENTS.md`, `CLAUDE.md`, `.env.example`, `docs/*.md`. Исторические ревью `docs/code_review_*.md` не правятся — это снимки на дату.
- Код (только удаление неиспользуемого): `routes/stores.py`, `constants.py`, `services/magnit_api.py`, `services/catalog_updater.py`, docstrings в `routes/catalog.py`.
- Применять последним — после `fix-data-integrity-bugs`, `unify-store-type-and-tracking`, `harden-runtime-reliability` и `refactor-product-query-and-category-api`, чтобы документация описывала итоговое поведение.
- Объединение дублирующих роутов категорий не входит — шаг 4.2 `docs/PLAN_FIXES_2026-09-27.md`.
