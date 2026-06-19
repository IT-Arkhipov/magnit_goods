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
GOODS_URL=https://magnit.ru/webgate/v1/goods
CORS_ORIGINS=*
```

| Переменная | Обязательная | По умолчанию | Назначение |
|-----------|--------------|--------------|-----------|
| `STORE_CODE` | для scheduler | — | Код магазина для автоматических заданий (напр. `992104`) |
| `STORE_TYPE` | нет | `MM` | Тип магазина: русское название (`Магнит`, `Мини`, `Экстра`) или API-код (`MM`, `ME`, `MM_MINI`, `DG`, `GM`, `MO`, `MC`, `ZARYAD`) |
| `GOODS_URL` | нет | `https://magnit.ru/webgate/v1/goods` | Эндпоинт API товаров |
| `CORS_ORIGINS` | нет | `*` | Разрешённые origins (CSV), напр. `http://localhost:8000,http://localhost:3000` |

> 🔴 **Не редактируйте `.env` вручную.** Используйте `POST /api/stores/select` — он атомарно обновляет `STORE_CODE` и `STORE_TYPE` через `dotenv.load_dotenv()` (`routes/stores.py:164`). Ручное редактирование может рассинхронизировать состояние с БД.

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
(`main.py:226` — `uvicorn.run("src.server.main:app", host="0.0.0.0", port=8000, reload=True)`)

### Endpoints после запуска
| URL | Назначение |
|-----|-----------|
| http://localhost:8000 | Главная (выбор магазина) |
| http://localhost:8000/docs | Swagger UI |
| http://localhost:8000/stores | Управление магазинами |
| http://localhost:8000/catalog | Категории |
| http://localhost:8000/products | Товары |
| http://localhost:8000/jobs | Фоновые задания |
| http://localhost:8000/shopping-list | Список покупок |

---

## Что происходит при старте

1. `init_db()` — создание таблиц + 11 миграций (идемпотентные). См. `docs/DATABASE.md`.
2. `_mark_all_running_failed_on_startup()` — все зависшие `ScanJob` со статусом `running` помечаются `failed` (процесс был убит).
3. `init_scheduler(store_code)` — если в `.env` есть `STORE_CODE`, запускаются автоматические задания.

---

## Scheduler (APScheduler)

`BackgroundScheduler` (`src/server/scheduler.py`). Запускается в `lifespan` (`main.py:43`), останавливается в `shutdown_scheduler()` (`main.py:48`).

| Job ID | Расписание | Функция | Что делает |
|--------|-----------|---------|-----------|
| `update_prices` | Ежедневно 08:00 | `update_prices_job()` (`scheduler.py:21`) | Обновление цен для отслеживаемых категорий. Создаёт `ScanJob(job_type="prices")`. |
| `scan_catalog` | Воскресенье 06:00 | `scan_catalog_job()` (`scheduler.py:77`) | Полное сканирование: сначала категории (`ScanJob(job_type="catalog")`), затем товары (`ScanJob(job_type="prices")`). |
| `daily_report` | Ежедневно 20:00 | — | **Закомментирован** (`scheduler.py:201`). Формирование отчёта через `NotificationService`. |

Расписание задаётся через `CronTrigger`:
```python
CronTrigger(hour=8, minute=0)                      # update_prices
CronTrigger(day_of_week="sun", hour=6, minute=0)   # scan_catalog
```

`init_scheduler` получает список отслеживаемых категорий (`Category.is_tracked == True`) из БД и передаёт их в `update_prices_job` (`scheduler.py:165-178`).

> Scheduler работает в отдельном потоке (`BackgroundScheduler`). Каждое задание создаёт **свою `SessionLocal()`** и закрывает в `finally` (`scheduler.py:26`, `:74`).

---

## База данных

- **Путь:** `src/data/magnit.db` (SQLite, в `.gitignore`)
- **Создание:** автоматически при старте через `init_db()`
- **Миграции:** 11 штук, выполняются при каждом старте (идемпотентные). См. `docs/DATABASE.md`.
- **Backup:** для резервного копирования остановите сервер и скопируйте `magnit.db`.

---

## Производственные замечания

- **CORS:** по умолчанию `allow_origins=["*"]`. Для продакшна ограничьте через `CORS_ORIGINS`.
- **Rate limiting:** 0.5s в `MagnitAPIClient` + случайная пауза 0.1-0.5s. **Не убирайте** — API Магнита блокирует. См. `docs/SERVICES.md`.
- **SQLite:** подходит для однопользовательского приложения. При высокой нагрузке рассмотрите PostgreSQL.
- **Логи:** `logging.basicConfig(level=INFO)` в `main.py:20`. Уровень можно изменить.
- **Playwright:** `product_opener.py` запускает **видимое окно браузера** — не работает на серверах без дисплея. Для headless-режима используйте `category_verifier.py` и `store_selector.py` (параметр `headless=True`).
