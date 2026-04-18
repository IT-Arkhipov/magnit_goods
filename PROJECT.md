# magnit_goods — Проект мониторинга цен магазина «Магнит»

FastAPI-сервер для парсинга, отслеживания цен и товаров в розничных магазинах сети «Магнит».

---

## 📋 Содержание

1. [Обзор](#обзор)
2. [Технологический стек](#технологический-стек)
3. [Структура проекта](#структура-проекта)
4. [База данных](#база-данных)
5. [API Магнита](#api-магнита)
6. [Рабочий процесс](#рабочий-процесс)
7. [API endpoints](#api-endpoints)
8. [Запуск сервера](#запуск-сервера)
9. [Важные нюансы](#важные-нюансы)
10. [Статус разработки](#статус-разработки)

---

## Обзор

Проект предназначен для:
- **Поиска и управления магазинами** — поиск по адресу, добавление, выбор активного магазина
- **Каталога товаров** — загрузка категорий, сканирование товаров по категориям
- **Мониторинга цен** — отслеживание изменений цен, история, уведомления о скидках
- **Фоновых задач** — автоматическое обновление цен по расписанию

**Основной URL:** http://localhost:8000  
**Swagger UI:** http://localhost:8000/docs

---

## Технологический стек

| Компонент | Технология |
|-----------|------------|
| **Бэкенд** | Python 3.10+, FastAPI |
| **База данных** | SQLite + SQLAlchemy (ORM) |
| **Планировщик** | APScheduler |
| **Шаблоны** | Jinja2 |
| **HTTP клиент** | requests + Playwright (для API) |
| **Конфигурация** | python-dotenv |
| **Валидация** | Pydantic v2 |

---

## Структура проекта

```
magnit_goods/
├── .env                    # Конфигурация (STORE_CODE, STORE_TYPE, GOODS_URL)
├── requirements.txt        # Зависимости
├── src/
│   ├── data/
│   │   ├── magnit.db       # SQLite база данных (gitignored)
│   │   └── categories.json # Категории из API (для начальной загрузки)
│   └── server/
│       ├── main.py         # FastAPI приложение, роуты страниц, миграции
│       ├── database.py     # SQLAlchemy engine, session, Base
│       ├── models.py       # SQLAlchemy модели (Store, Category, Product, etc.)
│       ├── schemas.py      # Pydantic схемы для API
│       ├── scheduler.py    # APScheduler конфигурация
│       ├── routes/
│       │   ├── stores.py   # API магазинов (CRUD, поиск, выбор)
│       │   ├── catalog.py  # API категорий и товаров
│       │   ├── prices.py   # API истории цен и уведомлений
│       │   └── jobs.py     # API статусов заданий
│       └── services/
│           ├── magnit_api.py       # Клиент API Магнита
│           ├── catalog_scanner.py  # Сканирование каталога
│           ├── catalog_updater.py  # Обновление категорий из API
│           ├── price_tracker.py    # Трекинг цен
│           └── notifications.py    # Уведомления об акциях
└── docs/
    └── scan_jobs.md        # Документация по scan_jobs
```

---

## База данных

### Таблицы

| Таблица | Описание | Ключевые поля |
|---------|----------|---------------|
| **stores** | Магазины Магнит | `id` (MD5 хэш), `store_code`, `store_type`, `city`, `address`, `full_address`, `is_active` |
| **categories** | Универсальные категории | `id`, `magnit_id`, `name`, `url`, `parent_id`, `is_tracked`, `product_count` |
| **products** | Товары | `id`, `product_id`, `name`, `category_id`, `store_code`, `price`, `old_price`, `quantity`, `is_promotion` |
| **price_history** | История цен | `id`, `product_id`, `store_code`, `price`, `recorded_at`, `change_type` |
| **daily_price_snapshot** | Ежедневные снимки цен | `id`, `product_id`, `store_code`, `price`, `snapshot_date`, `discount_percent` |
| **scan_jobs** | Задания на сканирование | `id`, `job_type`, `store_code`, `status`, `progress`, `items_scanned`, `error_message` |

### Миграции

При запуске сервера выполняются автоматические миграции:
1. **`migrate_store_ids()`** — конвертация integer ID в MD5 хэш-идентификаторы (12 символов)
2. **`migrate_categories()`** — обновление структуры таблицы категорий
3. **`_mark_all_running_failed_on_startup()`** — сброс зависших заданий в статус `failed`

---

## API Магнита

### Endpoint для товаров и категорий

```
POST https://magnit.ru/webgate/v2/goods/search
```

**Payload:**
```json
{
  "sort": {"order": "desc", "type": "popularity"},
  "pagination": {"limit": 50, "offset": 0},
  "includeAdultGoods": true,
  "storeCode": "992104",
  "storeType": "MM",
  "catalogType": "1",
  "categories": [12345]  // Опционально: ID категорий
}
```

**Response:**
- `items` — список категорий или товаров
- `total` — общее количество
- `hasMore` — есть ли больше результатов
- `fastCategories` — категории (при поиске без category_ids)
- `fastCategoriesExtended` — расширенные подкатегории

### Endpoint для поиска магазинов

```
POST https://magnit.ru/webgate/v1/stores-facade/search/detail
```

**Payload:**
```json
{
  "query": "Москва, ул. Ленина 10",
  "storeTypeListV2": ["MM", "ME", "DG"],
  "limit": 50,
  "offset": 0
}
```

### Типы магазинов (STORE_TYPE_MAP)

| Код | Название |
|-----|----------|
| MM | Магнит |
| ME | Экстра |
| DG | М.Косметик |
| GM | Семейный |
| MO | Опт |
| MC | Моя цена | 9 |
| ZARYAD | Заряд |
| MM_MINI | Мини |

### Rate Limiting

- Задержка между запросами: **0.5 секунды**
- Реализовано в `MagnitAPIClient._rate_limit_wait()`

---

## Рабочий процесс

### 1. Настройка

```bash
# Скопировать пример конфигурации
cp .env.example .env

# Редактировать .env:
# STORE_CODE=992104
# STORE_TYPE=MM
# GOODS_URL=https://magnit.ru/webgate/v1/goods
```

### 2. Добавление магазинов

1. `POST /api/stores/preview` — поиск по адресу (возвращает превью без сохранения)
2. `POST /api/stores/add-selected` — сохранение выбранных магазинов в БД
3. `POST /api/stores/select` — выбор активного магазина → обновляет `.env`

### 3. Загрузка категорий

**Одноразовая инициализация:**
```bash
python src/server/services/load_catalog_from_json.py
```

Или через API:
```bash
curl -X POST "http://localhost:8000/api/categories/load-from-json"
```

### 4. Сканирование категорий

```bash
curl -X POST "http://localhost:8000/api/categories/update-catalog?store_code=992104"
```

Синхронизирует подкатегории из API (добавляет новые, обновляет существующие, удаляет устаревшие).

### 5. Сканирование товаров

```bash
# Сканировать товары из отслеживаемых категорий
curl -X POST "http://localhost:8000/api/catalog/scan?store_code=992104&tracked_only=true"

# Сканировать все магазины
curl -X POST "http://localhost:8000/api/catalog/scan-all-stores"
```

### 6. Автоматизация (APScheduler)

| Задание | Расписание | Описание |
|---------|------------|----------|
| `update_prices` | Каждый день в 8:00 | Обновление цен отслеживаемых товаров |
| `scan_catalog` | Каждое воскресенье в 6:00 | Полное сканирование каталога |
| `daily_report` | Каждый день в 20:00 | Генерация ежедневного отчёта |

---

## API endpoints

### Магазины

| Метод | Endpoint | Описание |
|-------|----------|----------|
| `GET` | `/api/stores` | Список всех магазинов (с фильтрами: city, store_type, is_active) |
| `POST` | `/api/stores` | Добавить магазин вручную |
| `GET` | `/api/stores/{store_id}` | Получить магазин по ID |
| `PUT` | `/api/stores/{store_id}` | Обновить магазин |
| `DELETE` | `/api/stores/{store_id}` | Удалить магазин |
| `GET` | `/api/stores/search?q=` | Поиск по адресу |
| `POST` | `/api/stores/preview` | Поиск магазинов через API (без сохранения) |
| `POST` | `/api/stores/add-selected` | Добавить выбранные магазины из preview |
| `POST` | `/api/stores/select` | Выбрать активный магазин → обновить .env |
| `POST` | `/api/stores/delete-batch` | Удалить несколько магазинов |

### Каталог

| Метод | Endpoint | Описание |
|-------|----------|----------|
| `GET` | `/api/categories` | Список категорий (фильтры: tracked, parent_id) |
| `GET` | `/api/categories/tree` | Дерево категорий |
| `POST` | `/api/categories/load-from-json` | Загрузить категории из JSON |
| `POST` | `/api/categories/update-catalog` | Синхронизация категорий из API |
| `PUT` | `/api/categories/{id}/track` | Вкл/выкл отслеживание категории |
| `POST` | `/api/categories/update-tracking` | Массовое обновление отслеживания |
| `GET` | `/api/products` | Список товаров (фильтры: store_code, category_id, price range) |
| `GET` | `/api/products/{product_id}` | Детали товара |
| `POST` | `/api/catalog/scan` | Сканировать товары (синхронно) |
| `POST` | `/api/catalog/scan-all-stores` | Сканировать все магазины (асинхронно) |
| `POST` | `/api/catalog/scan-prices` | Обновить цены в магазине |

### Задания

| Метод | Endpoint | Описание |
|-------|----------|----------|
| `GET` | `/api/jobs` | Список заданий |
| `GET` | `/api/jobs/{job_id}` | Статус задания |

### Страницы

| Метод | Endpoint | Описание |
|-------|----------|----------|
| `GET` | `/` | Главная — управление магазинами |
| `GET` | `/catalog` | Каталог категорий |
| `GET` | `/products` | Товары |
| `GET` | `/deals` | Скидки и акции |
| `GET` | `/jobs` | История заданий |

---

## Запуск сервера

### Из корня проекта

```bash
# Вариант 1: напрямую
python -m uvicorn src.server.main:app --host 0.0.0.0 --port 8000 --reload

# Вариант 2: через main.py
python src/server/main.py
```

### В фоновом режиме (Linux/Mac)

```bash
nohup python -m uvicorn src.server.main:app --host 0.0.0.0 --port 8000 > server.log 2>&1 &
```

### Проверка

```bash
# Swagger UI
open http://localhost:8000/docs

# Проверка здоровья
curl http://localhost:8000/docs
```

---

## Важные нюансы

### Store ID

- **Формат:** `MD5(store_code|store_type|full_address)[:12]`
- **Не auto-increment** — это строка из 12 символов
- **Функция:** `store_hash_id(store_code, store_type, full_address)`

### Rate Limiting

- **0.5 секунды** между запросами к API Магнита
- Никогда не удаляйте `_rate_limit_wait()` из `magnit_api.py` — API заблокирует запросы

### Зависшие задания

- При запуске сервера все задания со статусом `running` переводятся в `failed`
- Задания с `started_at > 2 мин назад` автоматически помечаются как зависшие

### .env файл

- Обновляется автоматически при вызове `/api/stores/select`
- Не редактировать вручную во время работы сервера

### Пути к файлам

- Сервер должен запускаться из корня проекта (`D:\pythonProjects\magnit_goods`)
- Пути к `.env` и `magnit.db` относительные от корня

---

## Статус разработки

### Завершено

- ✅ Модуль магазинов (CRUD, поиск, выбор) — 100%
- ✅ Модуль категорий (загрузка из JSON, синхронизация с API) — 80%
- ✅ Модуль товаров (сканирование, сохранение) — 70%
- ✅ История цен и ежедневные снимки — 60%
- ✅ APScheduler для фоновых задач — 50%

### В разработке

- ⏳ Уведомления о скидках
- ⏳ Полная асинхронность (BackgroundTasks для всех долгих операций)
- ⏳ Экспорт данных (CSV, Excel)

### Планы

- 📋 Мобильная версия UI
- 📋 Многоязычность (i18n)
- 📋 Интеграция с Telegram для уведомлений

---

## Документация по компонентам

- [scan_jobs.md](docs/scan_jobs.md) — Статусы заданий на сканирование

---

## Контакты

Внутренний проект для мониторинга цен сети «Магнит».
