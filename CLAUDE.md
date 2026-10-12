# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Основная инструкция для AI-агентов ведётся в `AGENTS.md` (общая для всех агентов) и подключается ниже целиком — правки вносить туда, а не дублировать здесь.

@AGENTS.md

## Дополнительно для Claude Code

### Команды

```bash
# Запуск сервера (из корня репозитория, venv активирован)
python -m uvicorn src.server.main:app --host 0.0.0.0 --port 8000 --reload

# Линтер
ruff check src/
ruff check src/server/routes/catalog.py   # один файл
```

Автотестов нет — проверка вручную через Swagger UI (`/docs`) или веб-интерфейс. Модули импортируются как пакет `src.server...`, поэтому всё запускать из корня репозитория.

### Как устроен старт приложения

При импорте `main.py` загружается `.env` (`load_dotenv(override=False)`). Затем `main.py:lifespan` → `init_db()` (`create_all` + миграции из `database.py`, правила миграций — в `AGENTS.md`) → `mark_unfinished_jobs_failed()` (зависшие `pending`/`running` задания → `failed`) → `init_scheduler(STORE_CODE)`, если `STORE_CODE` задан.

### Поток данных (сводка)

API Магнита (`services/magnit_api.py`, с rate limiting) → `CatalogScanner` (bulk insert/update в `products`, запись в `price_history`, пересчёт `previous_price`/`price_change_percent`) → роуты `routes/*` и Jinja2-шаблоны. Длительные операции (сканирование всех магазинов, обновление цен) запускаются в фоне и отражают прогресс в `ScanJob`, который читает страница `/jobs`. Полная замена каталога категорий (`POST /api/categories/fetch-magnit-ids`) идёт в отдельном потоке, а её статус хранится **в памяти процесса** (`_catalog_update_status` в `routes/catalog.py`, `GET /api/categories/fetch-magnit-ids/status`), а не в `ScanJob`. Подробно — `docs/ARCHITECTURE.md`.

### Прочее

- Каталоги `.agents/`, `.kilo/`, `.koda/`, `.opencode/`, `opencode_temp/`, `openspec/`, PNG-скриншоты в корне — артефакты других агентов/сессий, не часть приложения.
- Перед изменением кода сверяйся с `docs/DEVELOPMENT.md` (техдолг) и `docs/DEVELOPMENT.md` (замечания из code review).
