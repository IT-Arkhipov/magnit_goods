# Развёртывание и запуск

## Требования к окружению

- **Python:** 3.10+ (используются `dict[str, int]`, `str | int` в аннотациях)
- **ОС:** Windows / Linux / macOS (разработка ведётся на Windows)
- **Playwright:** для браузерной автоматизации требуется установить браузеры:
  ```bash
  playwright install chromium
  ```

## Установка зависимостей

```bash
cd D:\pythonProjects\magnit_goods
python -m venv venv
venv\Scripts\activate            # Windows
# source venv/bin/activate        # Linux/macOS
pip install -r requirements.txt
playwright install chromium
```

Содержимое `requirements.txt`:
- `fastapi`, `uvicorn[standard]`, `starlette` — web-стек
- `SQLAlchemy>=2.0`, `pydantic>=2.5` — ORM и валидация
- `APScheduler>=3.10` — планировщик
- `requests` — HTTP-клиент для API Магнита
- `playwright>=1.40` — браузерная автоматизация
- `python-dotenv>=1.0` — управление `.env`
- `Jinja2>=3.1` — шаблоны

---

## Переменные окружения (`.env`)

Файл `.env` в корне проекта. Пример — `.env.example`:

```env
STORE_CODE=992104
STORE_TYPE=Магнит
CORS_ORIGINS=*
```

| Переменная | Обязательная | По умолчанию | Назначение |
|-----------|--------------|--------------|-----------|
| `STORE_CODE` | для scheduler | — | Код магазина для автоматических заданий (напр. `992104`). Пусто — планировщик не запускается, пока магазин не выбран через `POST /api/stores/select` |
| `STORE_TYPE` | нет | `Магнит` | Тип магазина: русское название (`Магнит`, `Мини`, `Экстра`, ...), API-код (`MM`, `ME`, `MM_MINI`, `DG`, `GM`, `MO`, `MC`, `ZARYAD`) или числовой код (1–9, см. таблицу ниже). Нераспознанное значение → предупреждение в логе и `Магнит` |
| `CORS_ORIGINS` | нет | `*` | Разрешённые origins (CSV), напр. `http://localhost:8000,http://localhost:3000` |

> 🔴 **Не редактируйте `.env` вручную.** Используйте `POST /api/stores/select` — он атомарно обновляет `STORE_CODE` и `STORE_TYPE` (`routes/stores.py:select_store`). Ручное редактирование может рассинхронизировать состояние с БД.

**Как читается `.env`:**
- При старте сервер загружает `.env` из корня репозитория (`main.py`, `load_dotenv(override=False)`) **до** запуска планировщика. Запускать uvicorn с `--env-file` не нужно.
- Переменные, уже заданные в окружении процесса, приоритетнее значений из `.env`.
- `POST /api/stores/select` (при `update_env=true`) кроме записи в `.env` обновляет `os.environ` работающего процесса и перерегистрирует задания планировщика на выбранный магазин — перезапуск не требуется. Если планировщик не был запущен (при старте не было `STORE_CODE`), он запускается. Ответ содержит `scheduler_updated`.

### Типы магазинов (`constants.py`)

| Русское название | API-код | Числовой код |
|-----------------|---------|--------------|
| Магнит | `MM` | 1 |
| Мини | `MM_MINI` | 2 |
| М.Косметик | `DG` | 3 |
| Семейный | `GM` | 5 |
| Экстра | `ME` | 6 |
| Опт | `MO` | 7 |
| Заряд | `ZARYAD` | 8 |
| Моя цена | `MC` | 9 |

---

## Запуск сервера

### Вариант 1: через uvicorn (рекомендуется)
```bash
cd D:\pythonProjects\magnit_goods
python -m uvicorn src.server.main:app --host 0.0.0.0 --port 8000 --reload
```

### Вариант 2: через `main.py`
```bash
python -m src.server.main
```
(`main.py` — `uvicorn.run("src.server.main:app", host="0.0.0.0", port=8000, reload=True)`)

### Endpoints после запуска
| URL | Назначение |
|-----|-----------|
| http://localhost:8000 | Главная (выбор магазина) |
| http://localhost:8000/docs | Swagger UI |
| http://localhost:8000/catalog | Категории |
| http://localhost:8000/products | Товары |
| http://localhost:8000/jobs | Фоновые задания |
| http://localhost:8000/shopping-list | Список покупок |

---

## Что происходит при старте

0. При импорте `main.py` загружается `.env` (`load_dotenv(override=False)`).
1. `init_db()` — создание таблиц + 15 миграций. Каждая выполняется один раз и регистрируется в `schema_migrations` только при успехе; упавшая миграция даёт `WARNING` в логе и повторяется при следующем старте. См. `docs/DATABASE.md`.
2. `mark_unfinished_jobs_failed()` (`services/jobs.py`) — все зависшие `ScanJob` со статусами `pending` и `running` помечаются `failed` (процесс был остановлен).
3. `init_scheduler(store_code)` — если задан `STORE_CODE`, запускаются автоматические задания.

---

## Scheduler (APScheduler)

`BackgroundScheduler` (`src/server/scheduler.py`). Запускается в `lifespan` (`main.py`), останавливается в `shutdown_scheduler()` (`main.py`).

| Job ID | Расписание | Функция | Что делает |
|--------|-----------|---------|-----------|
| `update_prices` | Ежедневно 08:00 | `update_prices_job()` (`scheduler.py`) | Обновление цен для отслеживаемых категорий. Создаёт `ScanJob(job_type="prices")`. |
| `scan_catalog` | Воскресенье 06:00 | `scan_catalog_job()` (`scheduler.py`) | Полное сканирование: сначала категории (`ScanJob(job_type="catalog")`), затем товары (`ScanJob(job_type="prices")`). |
| `daily_report` | Ежедневно 20:00 | — | **Закомментирован** (`scheduler.py`). Формирование отчёта через `NotificationService`. |

Расписание задаётся через `CronTrigger`:
```python
CronTrigger(hour=8, minute=0)                      # update_prices
CronTrigger(day_of_week="sun", hour=6, minute=0)   # scan_catalog
```

Отслеживаемые категории задания читают из БД **в момент запуска** (`catalog_scanner.py:get_tracked_category_magnit_ids`), поэтому новые отметки в UI учитываются без перезапуска. Тип магазина берётся из `STORE_TYPE`; если у кода магазина в БД несколько типов и `STORE_TYPE` не задан — задание завершится `failed`. `register_jobs()` можно вызывать повторно (его использует `POST /api/stores/select`).

> Scheduler работает в отдельном потоке (`BackgroundScheduler`). Каждое задание создаёт **свою `SessionLocal()`** и закрывает в `finally` (`scheduler.py`).

---

## База данных

- **Путь:** `src/data/magnit.db` (SQLite, в `.gitignore`)
- **Создание:** автоматически при старте через `init_db()`
- **Миграции:** 15 штук; каждая выполняется один раз и регистрируется в `schema_migrations` при успехе. См. `docs/DATABASE.md`.
- **Режим журнала — WAL.** При каждом подключении включаются `PRAGMA journal_mode=WAL` и `busy_timeout=30000` (`database.py:_set_sqlite_pragma`): HTTP-запросы на чтение не блокируются фоновой записью сканера, а конкурирующая запись ждёт до 30 с вместо ошибки `database is locked`. Рядом с БД появляются служебные файлы `magnit.db-wal` и `magnit.db-shm` (в `.gitignore`).
- **WAL требует локального диска.** Не размещайте `src/data/` на сетевой папке (SMB/NFS) — WAL там работает некорректно.
- **Backup:** остановите сервер и копируйте `magnit.db` **вместе с** `magnit.db-wal` (если он есть) либо сделайте копию на живой БД командой `sqlite3 src/data/magnit.db ".backup 'backup.db'"`. Копирование одного `magnit.db` при работающем сервере может потерять последние записи.
- **Откат режима:** при остановленном сервере `sqlite3 src/data/magnit.db "PRAGMA journal_mode=DELETE"`.

---

## Производственные замечания

- **CORS:** по умолчанию `allow_origins=["*"]`. Для продакшна ограничьте через `CORS_ORIGINS`.
- **Rate limiting:** 0.5s в `MagnitAPIClient` + случайная пауза 0.1-0.5s. **Не убирайте** — API Магнита блокирует. См. `docs/SERVICES.md`.
- **SQLite:** подходит для однопользовательского приложения. При высокой нагрузке рассмотрите PostgreSQL.
- **Логи:** `logging.basicConfig(level=INFO)` в `main.py`. Уровень можно изменить.
- **Playwright:** `product_opener.py` запускает **видимое окно браузера** — не работает на серверах без дисплея. Для headless-режима используйте `category_verifier.py` и `store_selector.py` (параметр `headless=True`).
