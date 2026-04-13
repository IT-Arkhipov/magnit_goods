# Магнит манИт — Веб-сервер для работы с магазинами Магнит

## Обзор проекта

Python FastAPI веб-сервер для поиска, сканирования и управления магазинами сети «Магнит». Позволяет находить магазины по адресу через официальный API Магнита, сохранять их в локальную SQLite базу данных, и управлять списком магазинов через веб-интерфейс.

**Проект в разработке** — модули каталога товаров, мониторинга цен и уведомлений запланированы (см. `IMPLEMENTATION_PLAN.md`).

## Технологический стек

| Компонент | Технология |
|-----------|-----------|
| Backend | FastAPI 0.115 + Uvicorn |
| БД | SQLite + SQLAlchemy 2.0 |
| ORM-модели | `Store` (id=хэш MD5), `Category`, `Product`, `PriceHistory`, `ScanJob` |
| API Магнита | `requests` (прямые HTTP-запросы к `webgate/v1/stores-facade/search/detail`) |
| UI | Jinja2 шаблоны + JavaScript |
| Планировщик | APScheduler (для автообновления цен) |
| Браузер-автоматизация | Playwright (резервный метод) |

## Структура проекта

```
magnit_goods/
├── src/
│   ├── server/
│   │   ├── main.py              # Точка входа FastAPI
│   │   ├── database.py          # SQLAlchemy engine, сессии, инициализация БД
│   │   ├── models.py            # ORM-модели (Store, Category, Product, PriceHistory, ScanJob)
│   │   ├── schemas.py           # Pydantic-схемы (StoreCreate, ScanStoresRequest, и т.д.)
│   │   ├── scheduler.py         # APScheduler — автообновление цен
│   │   ├── routes/              # REST API endpoints
│   │   │   ├── stores.py        # CRUD магазинов, сканирование, выбор
│   │   │   ├── catalog.py       # Категории и товары
│   │   │   ├── prices.py        # История цен, скидки, уведомления
│   │   │   └── jobs.py          # Статус фоновых заданий
│   │   ├── services/            # Бизнес-логика
│   │   │   ├── magnit_api.py    # Клиент для API Магнита (StoresAPI + MagnitAPIClient)
│   │   │   ├── store_selector.py # Playwright-автоматизация выбора магазина
│   │   │   ├── catalog_scanner.py # Сканирование каталога
│   │   │   ├── price_tracker.py  # Отслеживание изменений цен
│   │   │   └── notifications.py  # Генерация уведомлений
│   │   └── templates/           # HTML-шаблоны (Jinja2)
│   └── data/
│       └── magnit.db            # SQLite база данных (игнорируется в git)
├── docs/                        # Документация
├── .env.example                 # Пример файла окружения
├── requirements.txt             # Python-зависимости
├── IMPLEMENTATION_PLAN.md       # Детальный план реализации
└── QWEN.md                      # Этот файл
```

## Запуск

### Установка зависимостей

```bash
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt
playwright install chromium
```

### Настройка

Скопируйте `.env.example` в `.env` и укажите параметры:

```
STORE_CODE=992104
STORE_TYPE=Мини
GOODS_URL=https://magnit.ru/webgate/v1/goods
```

### Запуск сервера

```bash
cd D:\pythonProjects\magnit_goods
venv\Scripts\python.exe -m uvicorn src.server.main:app --host 0.0.0.0 --port 8000 --reload
```

Сервер будет доступен по адресу **http://localhost:8000**

- Веб-интерфейс: http://localhost:8000/
- Swagger-документация: http://localhost:8000/docs

## API Endpoints

### Магазины (`/api/stores`)

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/api/stores` | Список всех магазинов (фильтры: `?city=...&store_type=...`), сортировка по адресу |
| `POST` | `/api/stores` | Добавить магазин вручную |
| `GET` | `/api/stores/search?q=...` | Поиск по адресу |
| `POST` | `/api/stores/preview` | Предварительный поиск (без сохранения), возвращает список с чекбоксами |
| `POST` | `/api/stores/add-selected` | Добавить выбранные из preview в БД |
| `POST` | `/api/stores/select` | Выбрать магазин из БД → обновить `.env` |
| `GET` | `/api/stores/by-code/{store_code}` | Получить магазин по коду (автозаполнение формы) |
| `DELETE` | `/api/stores/{id}` | Удалить магазин (`id` — хэш-строка) |
| `POST` | `/api/stores/delete-batch` | Массовое удаление по списку ID (хэш-строки) |

### Задания (`/api/jobs`)

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/api/jobs` | Список заданий на сканирование |
| `GET` | `/api/jobs/{job_id}` | Статус конкретного задания |

### Каталог (`/api`)

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/api/categories` | Список категорий |
| `POST` | `/api/categories/scan` | Сканировать категории (фоновая задача) |
| `GET` | `/api/products` | Список товаров |
| `POST` | `/api/catalog/scan` | Сканировать товары (фоновая задача) |

### Цены (`/api/prices`)

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/api/prices/decreased` | Товары со сниженными ценами |
| `GET` | `/api/prices/increased` | Товары с повышенными ценами |
| `GET` | `/api/prices/alerts` | Уведомления о значительных изменениях |
| `GET` | `/api/prices/statistics` | Общая статистика |
| `GET` | `/api/prices/history/{product_id}` | История цен товара |
| `POST` | `/api/prices/update` | Обновить цены (фоновая задача) |

## Типы магазинов

Маппинг API-кодов в UI-лейблы (проверено через Playwright на magnit.ru/shops):

| API код | UI-лейбл |
|---------|----------|
| `MM` | Магнит |
| `MM_MINI` | Мини |
| `GM` | Семейный |
| `ME` | Экстра |
| `MO` | Опт |
| `MC` | Моя цена |
| `ZARYAD` | Заряд |
| `DG` | М.Косметик |
| `DARKSTORE` | Мигом |

**Чекбоксы сканирования по умолчанию:** Магнит, Мини, Семейный, Экстра, Моя цена.

## Разработка

### Ветка

Основная разработка ведётся в ветке `feature/store-address-scan`.

### Стиль кода

- Python 3.10+
- Type hints используются повсеместно
- Pydantic v2 для схем
- SQLAlchemy 2.0 синтаксис
- Русскоязычные комментарии и docstrings

### Коммиты

Коммиты на русском языке, формат:
```
<тип>: <краткое описание>

<детали при необходимости>
```

Типы: `feat`, `fix`, `refactor`, `chore`, `ui`, `docs`

## Известные ограничения

- API Магнита может иметь лимиты на частоту запросов (rate limit ~0.3 сек между запросами)
- Сканирование выполняется синхронно — запрос может занимать 10-60 секунд
- Маппинг типов основан на данных с сайта magnit.ru и может потребовать обновления
- Модули каталога и мониторинга цен — в разработке (см. `IMPLEMENTATION_PLAN.md`)

## Особенности реализации

### ID магазинов
- Используется хэш `MD5(store_code|store_type|full_address)[:12]` вместо автоинкремента
- Гарантирует уникальность и идемпотентность: один магазин = один ID
- Колонка ID скрыта в UI таблицы

### Сканирование
- Двухшаговый процесс: `POST /api/stores/preview` → показ результатов → `POST /api/stores/add-selected`
- Пользователь выбирает нужные магазины из preview через чекбоксы
- Существующие магазины подсвечиваются серым с пометкой «(уже в базе)»
- Дедупликация по `store_code` внутри preview
- Пагинация API ограничена 20 страницами (защита от зацикливания)

### Список магазинов
- Сортировка по полному адресу (`COLLATE NOCASE`)
- Прокрутка: max-height 480px (~10 строк видны), далее вертикальный скролл
- Раздел «Сканировать по кодам» удалён
