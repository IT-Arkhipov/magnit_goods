# Tasks

## 1. Удаление неиспользуемого кода

- [x] 1.1 Для каждого имени (`_cleanup_stale_jobs`, `REVERSE_STORE_TYPE_MAP`, `set_store_code`, `update_all_categories`, `catalog_updater.update_catalog_from_api`) выполнить `grep -rn` по репозиторию без каталогов агентов. Удалить те, у которых нет использований (D2). Проверка: `grep` по удалённым именам в `src/` пуст, `ruff check src/` чист, сервер стартует.
- [x] 1.2 Исправить docstrings и сообщения эндпоинтов загрузки категорий в `routes/catalog.py`: `magnit_catalog.json` → `categories.json`. Проверка: `grep -rn "magnit_catalog" src/` пуст.

## 2. AGENTS.md и CLAUDE.md

- [x] 2.1 В `AGENTS.md`:
  - удалить тестовые роуты и упоминание дубля `POST /api/stores`;
  - переписать раздел миграций (реестр `schema_migrations`, актуальный список из `init_db()`);
  - срок очистки — `STALE_DAYS_DELETE` (6 дней) с жизненным циклом из `constants.py`;
  - удалить `query_product.py` из техдолга;
  - удалить `GOODS_URL` из env vars;
  - ссылки перевести в формат `файл:функция` (D1).

  Проверка: каждый упомянутый роут есть в `src/server`, каждое упомянутое имя находится `grep`.
- [x] 2.2 В `CLAUDE.md` удалить уточнение про миграции (теперь в AGENTS.md) и исправить фразу о прогрессе замены каталога в `ScanJob` (D3). Проверка: в CLAUDE.md нет утверждений, противоречащих AGENTS.md.

## 3. docs/ и .env.example

- [x] 3.1 `docs/API.md`, `docs/ARCHITECTURE.md`: удалить тестовые роуты, описать статус замены каталога в памяти процесса, ссылки — `файл:функция`. Проверка: список роутов совпадает с `GET /openapi.json` (пути) плюс страницы из `main.py`.
- [x] 3.2 `docs/DATABASE.md`, `docs/DEVELOPMENT.md`, `docs/SERVICES.md`:
  - срок очистки — 6 дней (`STALE_DAYS_DELETE`);
  - удалить `query_product.py` из техдолга;
  - пометить `NotificationService` и `store_selector.py` как неподключённые;
  - добавить правило «поведение и документация меняются в одном изменении»;
  - ссылки — `файл:функция`.

  Проверка: `grep -rn "query_product\|7 дней" docs/*.md` находит совпадения только в `code_review_*.md`.
- [x] 3.3 `docs/DEPLOYMENT.md`, `docs/PORTING.md`, `.env.example`: удалить `GOODS_URL`, описать `STORE_CODE`/`STORE_TYPE`/`CORS_ORIGINS` с допустимыми значениями. Проверка: `grep -rn GOODS_URL . --include=*.md --include=.env.example` без каталогов агентов пуст.

## 4. Итоговая проверка

- [x] 4.1 Финальный проход: `grep -rnE "\.py:[0-9]+" AGENTS.md CLAUDE.md docs/*.md`, без `code_review_*` и `PLAN_FIXES_*`. Проверка: совпадений нет; `ruff check src/` чист; сервер стартует, страницы `/`, `/catalog`, `/products`, `/jobs`, `/shopping-list` открываются.

## Workflow follow-up

- Применять последним из трёх изменений цикла.
- Коммит только после согласования с пользователем, формат `документация: ...` / `чистка: ...`.
- Архивировать после проверки (`/opsx:archive`).
