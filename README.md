# magnit_goods

FastAPI-сервер для мониторинга цен в магазинах «Магнит». Сканирует каталог товаров через публичное API magnit.ru, отслеживает изменения цен, уведомляет об акциях.

## Возможности

- **Поиск и добавление магазинов** через API Магнита по городу/улице
- **Дерево категорий** с выбором отслеживаемых для сканирования
- **Сканирование товаров** с bulk-операциями (5000+ товаров за раз)
- **Отслеживание цен** с двумя режимами отображения изменений:
  - «Новая цена» — изменение от предыдущего сканирования
  - «Последнее изменение» — последнее реальное изменение цены
- **Сравнение цен** одного товара в нескольких магазинах
- **Список покупок** с проверкой наличия и экспортом
- **Фоновые задания** с прогрессом и возможностью отмены
- **Автоматические задания** (scheduler): ежедневное обновление цен, еженедельное сканирование каталога
- **Открытие товара в браузере** через Playwright с автоматическим выбором магазина

## Быстрый старт

```bash
cd D:\pythonProjects\magnit_goods
python -m venv venv
venv\Scripts\activate            # Windows
# source venv/bin/activate        # Linux/macOS
pip install -r requirements.txt
playwright install chromium
python -m uvicorn src.server.main:app --host 0.0.0.0 --port 8000 --reload
```

После запуска:
- **Веб-интерфейс:** http://localhost:8000
- **Swagger UI:** http://localhost:8000/docs

## Технологии

| Слой | Технология |
|------|-----------|
| Web-фреймворк | FastAPI + Starlette |
| ASGI-сервер | Uvicorn |
| ORM | SQLAlchemy 2.x |
| Валидация | Pydantic 2.x |
| БД | SQLite |
| Шаблоны | Jinja2 |
| Scheduler | APScheduler |
| HTTP-клиент | requests |
| Браузерная автоматизация | Playwright |

## Архитектура

```
src/server/
├── main.py              # Точка входа, lifespan, роуты страниц
├── database.py          # engine, SessionLocal, init_db(), 11 миграций
├── models.py            # Store, Category, Product, PriceHistory, ScanJob
├── constants.py         # типы магазинов
├── scheduler.py         # APScheduler: update_prices, scan_catalog
├── routes/              # HTTP-эндпоинты (39 API + 10 роутов в main.py)
├── services/            # 8 модулей: API-клиенты, сканеры, Playwright, уведомления
├── utils/               # Извлечение города из адреса
└── templates/           # Jinja2 HTML
```

Подробности: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

## Документация

| Документ | Содержание |
|----------|-----------|
| [docs/USER_GUIDE.md](docs/USER_GUIDE.md) | Использование веб-интерфейса: магазины, каталог, товары, список покупок, задания |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Архитектура, дерево модулей, потоки данных, жизненный цикл |
| [docs/API.md](docs/API.md) | Полный справочник всех 39+ эндпоинтов с параметрами и ответами |
| [docs/DATABASE.md](docs/DATABASE.md) | Модели, индексы, 11 миграций, логика отслеживания цен |
| [docs/SERVICES.md](docs/SERVICES.md) | Детальное описание 8 сервисов, rate limiting, bulk-операции, Playwright |
| [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) | Переменные окружения, запуск, scheduler, конфигурация |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | Конвенции, критические особенности, типичные ошибки, техдолг |
| [docs/scan_jobs.md](docs/scan_jobs.md) | Зачем нужны статусы фоновых заданий |
| [docs/code_review_2026-06-12.md](docs/code_review_2026-06-12.md) | Отчёт ревью кода с проблемами производительности |
| [AGENTS.md](AGENTS.md) | Краткая инструкция для AI-агентов с критическими особенностями |

## Основной рабочий процесс

1. **Добавить магазины** (`/`) — поиск по городу, preview, сохранение выбранных
2. **Выбрать активный магазин** — обновит `.env` (для scheduler)
3. **Настроить каталог** (`/catalog`) — обновить дерево, отметить отслеживаемые категории
4. **Сканировать товары** — фоновая задача, прогресс на `/jobs`
5. **Анализировать цены** (`/products`) — фильтры, два режима отображения, сравнение по магазинам
6. **Список покупок** (`/shopping-list`) — проверка наличия, экспорт

См. подробное руководство: [`docs/USER_GUIDE.md`](docs/USER_GUIDE.md)

## Ключевые особенности

- **Store IDs** — MD5-хэши (строки), не integers. Path-параметры: `store_id: str`.
- **Rate limiting** 0.5s + случайная пауза — НЕ убирать, API Магнита блокирует.
- **`.env`** обновляется только через `POST /api/stores/select`, не вручную.
- **Фоновые задачи** создают свою `SessionLocal()` — не используют закрытую FastAPI-сессию.
- **Bulk-операции** в `_save_products()` — не заменять на построчные.
- **Знак `price_change_percent`**: `+` = снижение (зелёная ↓), `−` = повышение (фиолетовая ↑).

Полный список критических особенностей: [`docs/DEVELOPMENT.md`](docs/DEVELOPMENT.md)

## Линтинг

```bash
ruff check src/
```

## Лицензия

Частный проект.
