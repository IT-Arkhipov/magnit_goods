# План реализации: Магнит манИт — Веб-сервер для работы с магазинами Магнит

## 1. Обзор требований

### Функциональные требования

#### Модуль 1: Выбор магазина ✅ РЕАЛИЗОВАНО
- Поиск магазина по адресу (город + улица) через официальный API Магнита
- Фильтрация по типу магазина (Магнит, М.Косметик, Мини, Экстра, Опт, Моя цена, Заряд)
- Ручное управление списком магазинов (добавление, удаление, массовое удаление)
- Сканирование всех магазинов города/улицы с сохранением в БД
- Автозаполнение формы при вводе `store_code`
- Массовое удаление магазинов через чекбоксы
- Выбор магазина из БД → обновление `.env`

#### Модуль 2: Каталог товаров и мониторинг цен 🚧 В РАЗРАБОТКЕ
- Сканирование каталога товаров по категориям для выбранного магазина
- Сохранение информации: название, цена, категория, артикул, дата
- Выбор разделов каталога для отслеживания
- Сравнение цен по дням (история изменений)
- Предложения товаров со сниженными ценами (по категориям/наименованиям)
- Уведомления о значительном снижении цен
- Фильтрация товаров по цене, категории, динамике изменений

### Нефункциональные требования
- Простота: проект для одного разработчика
- Производительность: ответ API < 5 секунд
- Надёжность: локальная БД
- Удобство: веб-интерфейс + REST API
- Хранение истории цен: ~1000 товаров × 30 дней = ~30K записей

### Ограничения
- Небольшой трафик (один пользователь)
- Python-экосистема
- Локальный запуск (без облака)
- API Магнита может иметь лимиты запросов (rate limit ~0.3 сек)

---

## 2. Оценка ёмкости

### Модуль «Магазины»
```
Магазинов в базе: ~200-500
Размер БД: < 1MB
```

### Модуль «Каталог и цены»
```
Товаров для отслеживания: ~1000-5000
Категорий: ~50-100
Записей истории цен в день: ~5000
Записей истории за 30 дней: ~150,000
Записей истории за 1 год: ~1,800,000
Размер БД (1 год): ~50-100MB
Частота обновления цен: 1-2 раза в день
Время полного сканирования: ~10-30 минут (5000 товаров)
Память: < 512MB
```

**Вывод:** не нужен Kubernetes, Redis, очереди сообщений. Достаточно одного процесса FastAPI + SQLite.
Для асинхронного сканирования каталога — фоновые задачи через `BackgroundTasks` (FastAPI).

---

## 3. Архитектура

```
┌──────────────┐
│   Browser    │  ← Веб-интерфейс (Jinja2 + HTMX) или REST API
└─────────────┘
       │
┌──────▼───────┐
│  FastAPI     │  ← Веб-сервер (src/server/main.py)
│  Server      │
└──┬───┬───┬───┘
   │   │   │
   │   │   └──────────────────┐
   │   │                      │
   ▼   ▼                      ▼
┌───────┐              ┌──────────────┐
│SQLite │              │  API Магнита  │
│  DB   │              │  (REST calls) │
└───────┘              └──────────────┘
```

**Ключевое решение:** сканирование магазинов осуществляется через **прямые HTTP-запросы к API Магнита** (`POST /webgate/v1/stores-facade/search/detail`), а не через Playwright. Это значительно быстрее и надёжнее.

---

## 4. Хранение данных

**Решение:** SQLite без YAML-импорта.

YAML-импорт удалён — магазины сканируются напрямую через API Магнита и сохраняются в SQLite. Файл `magnit.db` хранится в `src/data/` и игнорируется в git.

---

## 5. Структура проекта

```
magnit_goods/
├── src/
│   ├── __init__.py
│   ├── server/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI приложение, lifespan, шаблоны
│   │   ├── database.py          # SQLAlchemy engine, сессии, init_db
│   │   ├── models.py            # ORM модели (Store, Category, Product, PriceHistory, ScanJob)
│   │   ├── schemas.py           # Pydantic схемы + маппинг типов
│   │   ├── scheduler.py         # APScheduler для планового обновления цен
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── stores.py        # CRUD + сканирование + выбор + массовое удаление
│   │   │   ├── catalog.py       # Категории, товары, сканирование каталога
│   │   │   ├── prices.py        # История цен, скидки, уведомления, аналитика
│   │   │   └── jobs.py          # Статус заданий
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── magnit_api.py    # StoresAPI (магазины) + MagnitAPIClient (каталог)
│   │   │   ├── store_selector.py # Playwright (резервный метод)
│   │   │   ├── catalog_scanner.py # Сканирование каталога
│   │   │   ├── price_tracker.py  # Отслеживание изменений цен
│   │   │   └── notifications.py  # Генерация уведомлений
│   │   └── templates/
│   │       ├── base.html         # Базовый шаблон с навигацией
│   │       ├── stores.html       # Управление магазинами (основная страница)
│   │       ├── stores_table.html # Таблица магазинов (включается)
│   │       ├── catalog.html      # Каталог категорий
│   │       ├── products.html     # Список товаров
│   │       ├── deals.html        # Товары со скидками
│   │       └── jobs.html         # Статус заданий
│   └── data/
│       ├── __init__.py
│       └── magnit.db            # SQLite БД (игнорируется в git)
├── docs/                        # Документация
├── venv/                        # Виртуальное окружение (игнорируется)
├── .env.example                 # Пример файла окружения
├── .gitignore
├── IMPLEMENTATION_PLAN.md       # Этот файл
├── QWEN.md                      # Контекст для AI-ассистента
├── README.md
└── requirements.txt
```

---

## 6. Схема данных (SQLite)

### Таблица 1: `stores` — Магазины

```sql
CREATE TABLE stores (
    id          VARCHAR(12) PRIMARY KEY,  -- хэш (MD5 первые 12 символов: store_code + store_type + full_address)
    store_code  TEXT    NOT NULL,         -- код магазина из API Магнита
    store_type  TEXT    NOT NULL,         -- Магнит, Семейный, Мини, Экстра...
    city        TEXT    NOT NULL,         -- Новочебоксарск
    address     TEXT    NOT NULL,         -- ул. Строителей, зд 21
    full_address TEXT   NOT NULL,         -- полный адрес для отображения
    name        TEXT,                     -- название/описание
    is_active   BOOLEAN DEFAULT 1,
    created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_stores_city ON stores(city);
CREATE INDEX idx_stores_type ON stores(store_type);
CREATE INDEX idx_stores_code ON stores(store_code);
```

> **ID магазина** — не автоинкремент, а хэш `MD5(f"{store_code}|{store_type}|{full_address}")[:12]`. Это гарантирует уникальность и идемпотентность: один и тот же магазин всегда получает один и тот же ID. Колонка ID скрыта в UI.

### Таблица 2: `categories` — Категории каталога

```sql
CREATE TABLE categories (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    category_id     INTEGER NOT NULL,       -- ID категории из API Магнита
    name            TEXT    NOT NULL,       -- "Молоко, сыр, яйца"
    parent_id       INTEGER,                -- ID родительской категории (NULL = корневая)
    store_code      TEXT    NOT NULL,       -- привязка к магазину
    is_tracked      BOOLEAN DEFAULT 0,      -- отслеживать ли товары этой категории
    product_count   INTEGER DEFAULT 0,      -- кол-во товаров в категории
    last_scanned    TIMESTAMP,              -- дата последнего сканирования
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(category_id, store_code)
);

CREATE INDEX idx_categories_store ON categories(store_code);
CREATE INDEX idx_categories_tracked ON categories(is_tracked);
```

### Таблица 3: `products` — Товары (текущее состояние)

```sql
CREATE TABLE products (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id      INTEGER NOT NULL,       -- ID товара из API
    name            TEXT    NOT NULL,       -- "Молоко Простоквашино 3.2%"
    sku             TEXT,                   -- артикул/SKU
    category_id     INTEGER,                -- ссылка на categories.id
    store_code      TEXT    NOT NULL,       -- привязка к магазину

    -- Текущие данные
    price           REAL    NOT NULL,       -- текущая цена
    old_price       REAL,                   -- старая цена (если есть скидка)
    currency        TEXT    DEFAULT '₽',
    unit            TEXT,                   -- "шт", "кг", "л"
    image_url       TEXT,                   -- URL картинки
    in_stock        BOOLEAN DEFAULT 1,      -- есть ли в наличии

    -- Метаданные
    first_seen      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- когда впервые обнаружен
    last_seen       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,  -- когда последний раз виден
    last_price_change TIMESTAMP,            -- дата последнего изменения цены

    UNIQUE(product_id, store_code)
);

CREATE INDEX idx_products_store ON products(store_code);
CREATE INDEX idx_products_category ON products(category_id);
CREATE INDEX idx_products_price ON products(price);
CREATE INDEX idx_products_last_seen ON products(last_seen);
```

### Таблица 4: `price_history` — История изменений цен

```sql
CREATE TABLE price_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id      INTEGER NOT NULL,       -- ссылка на products.product_id
    store_code      TEXT    NOT NULL,
    price           REAL    NOT NULL,       -- цена на момент записи
    old_price       REAL,                   -- старая цена (если была скидка)
    recorded_at     TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    change_type     TEXT,                   -- 'initial', 'increased', 'decreased', 'unchanged'
    FOREIGN KEY (product_id) REFERENCES products(product_id)
);

CREATE INDEX idx_price_history_product ON price_history(product_id, store_code);
CREATE INDEX idx_price_history_recorded ON price_history(recorded_at);
```

### Таблица 5: `scan_jobs` — Задания на сканирование

```sql
CREATE TABLE scan_jobs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    job_type        TEXT    NOT NULL,       -- 'stores', 'catalog', 'prices'
    store_code      TEXT,                   -- для каких магазинов
    category_ids    TEXT,                   -- JSON список категорий (для catalog/prices)
    status          TEXT    DEFAULT 'pending',  -- pending, running, completed, failed
    progress        INTEGER DEFAULT 0,      -- прогресс 0-100
    progress_message TEXT,                  -- сообщение о текущем этапе
    started_at      TIMESTAMP,
    finished_at     TIMESTAMP,
    items_scanned   INTEGER DEFAULT 0,
    items_added     INTEGER DEFAULT 0,
    items_updated   INTEGER DEFAULT 0,
    error_message   TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 7. API Endpoints

### REST API

#### Модуль 1: Магазины ✅

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/api/stores` | Список всех магазинов (фильтр: `?city=...&store_type=...`) |
| `POST` | `/api/stores` | Добавить магазин |
| `PUT` | `/api/stores/{id}` | Обновить магазин |
| `DELETE` | `/api/stores/{id}` | Удалить магазин (`{id}` — хэш-строка) |
| `GET` | `/api/stores/search` | Поиск по адресу (`?q=Новочебоксарск+Строителей`) |
| `POST` | `/api/stores/scan` | **Сканирование магазинов по городу/улице через API Магнита** (синхронно) |
| `POST` | `/api/stores/select` | Выбор магазина из БД по адресу и типу |
| `POST` | `/api/stores/delete-batch` | Массовое удаление по списку ID (строки) |
| `GET` | `/api/stores/by-code/{store_code}` | Получить магазин по коду (автозаполнение формы) |

#### Модуль 2: Каталог и цены 🚧

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/api/categories` | Список категорий (`?store_code=...&tracked=1`) |
| `POST` | `/api/categories/scan` | Сканирование каталога → сохранение категорий |
| `PUT` | `/api/categories/{id}/track` | Включить/выключить отслеживание категории |
| `GET` | `/api/products` | Список товаров (`?store_code=...&category_id=...&sort=price`) |
| `GET` | `/api/products/{id}` | Детали товара + история цен |
| `GET` | `/api/products/{id}/history` | История цен товара за период |
| `POST` | `/api/catalog/scan` | Сканирование товаров выбранных категорий (фоновая задача) |
| `POST` | `/api/prices/update` | Обновление цен для отслеживаемых товаров (фоновая задача) |
| `GET` | `/api/prices/decreased` | **Товары со сниженными ценами** |
| `GET` | `/api/prices/increased` | Товары с выросшими ценами |
| `GET` | `/api/prices/alerts` | Уведомления о значительных изменениях цен |
| `GET` | `/api/prices/statistics` | Общая статистика |
| `GET` | `/api/jobs` | Статус заданий на сканирование |
| `GET` | `/api/jobs/{job_id}` | Статус конкретного задания |

### `POST /api/stores/scan` — сканирование магазинов через API (синхронно)

**Запрос:**
```json
{
  "city": "Новочебоксарск",
  "street": "ул. Строителей",
  "store_types": ["Магнит", "Мини", "Семейный", "Экстра", "Моя цена"],
  "force_update": false
}
```

**Ответ (после завершения, ~10-60 сек):**
```json
{
  "job_id": 42,
  "status": "completed",
  "items_scanned": 120,
  "items_added": 115
}
```

> Сканирование выполняется **синхронно** в рамках одного HTTP-запроса. API Магнита может возвращать дубликаты — они автоматически фильтруются по `store_code`.

### `POST /api/stores/select` — выбор магазина из БД

**Запрос:**
```json
{
  "city": "Новочебоксарск",
  "street": "ул. Строителей",
  "store_type": "М.Косметик",
  "update_env": true
}
```

**Ответ:**
```json
{
  "store_code": "932177",
  "store_type": "М.Косметик",
  "name": "Магнит М.Косметик",
  "address": "Чувашская Республика - Чувашия, г Новочебоксарск, ул Винокурова, зд 117",
  "city": "Новочебоксарск",
  "env_updated": true
}
```

---

## 8. Маппинг типов магазинов

Проверено через Playwright на странице magnit.ru/shops (кнопки фильтрации → `storeTypeListV2` в запросе):

| API код | UI-лейбл | Описание |
|---------|----------|----------|
| `MM` | Магнит | Стандартный магазин |
| `MM_MINI` | Мини | Магнит Мини |
| `GM` | Семейный | Семейный (ранее «Гипермаркет») |
| `ME` | Экстра | Магнит Экстра |
| `MO` | Опт | Магнит Опт |
| `MC` | Моя цена | Магнит «Моя цена» |
| `ZARYAD` | Заряд | Магнит Заряд |
| `DG` | М.Косметик | Магнит Косметик |
| `DARKSTORE` | Мигом | Даркстор / Мигом |

**Чекбоксы сканирования по умолчанию:** Магнит, Мини, Семейный, Экстра, Моя цена.

---

## 9. Data Flow

### Сценарий 1: Сканирование магазинов через API Магнита (синхронно)

```
Пользователь → Вводит: город, улица, типы магазинов → POST /api/stores/scan

1. Сервер создаёт ScanJob (status='running')
2. Создаёт StoresAPI клиент
3. POST /webgate/v1/stores-facade/search/detail с пагинацией (до 20 страниц)
4. Парсит ответ: store_code, store_type, full_address, city
5. Дедупликация по store_code (API может возвращать дубли)
6. Пакетная вставка новых магазинов в БД (add_all)
7. Обновляет ScanJob: status='completed', items_scanned, items_added
8. Возвращает ответ клиенту: { job_id, status, items_scanned, items_added }
```

### Сценарий 2: Выбор магазина из БД

```
Пользователь → Вводит: город, улица, тип → POST /api/stores/select

1. Поиск в SQLite:
   SELECT * FROM stores
   WHERE city LIKE '%{city}%'
     AND (street IS NULL OR full_address LIKE '%{street}%')
     AND store_type = '{store_type}'
   LIMIT 1;

2. Магазин найден → возвращаем store_code, store_type, address
3. Если update_env=true → обновляем .env (STORE_CODE, STORE_TYPE)
```

### Сценарий 3: Автозаполнение формы по store_code

```
Пользователь → Вводит store_code в форму → onblur → GET /api/stores/by-code/{code}

1. Если магазин найден в БД → автозаполняем все поля формы
2. Если не найден → пользователь заполняет вручную
```

### Сценарий 4: Массовое удаление магазинов

```
Пользователь → Отмечает чекбоксы → «Удалить выбранные (N)» → POST /api/stores/delete-batch

1. Отправляем POST /api/stores/delete-batch { ids: [1, 2, 3] }
2. DELETE FROM stores WHERE id IN (1, 2, 3)
3. Обновляем таблицу на странице
```

---

## 10. Отказоустойчивость

- **API Магнита недоступен:** retry с экспоненциальной задержкой, фоллбэк на Playwright
- **SQLite повреждается:** бэкап при каждом запуске
- **Сайт magnit.ru недоступен:** кешированные данные из БД
- **Rate limiting:** пауза 0.3 сек между запросами к API Магнита

---

## 11. Безопасность

- `.env` не коммитится (`.gitignore`)
- SQLite файл — локальный, доступ только с localhost
- Если сервер публичный: авторизация, HTTPS
- Валидация всех входных данных через Pydantic

---

## 12. Технологический стек

| Компонент | Технология | Почему |
|-----------|-----------|--------|
| Backend | **FastAPI 0.115** | Быстро, Pydantic, async, BackgroundTasks, автодокументация |
| БД | **SQLite** | Встроенный, не требует установки |
| ORM | **SQLAlchemy 2.0** | Типизированный |
| Сканер магазинов | **requests → API Магнита** | Быстрее и надёжнее Playwright |
| API Магнита | **requests** | Прямые HTTP-запросы к webgate/v1 |
| UI | **Jinja2 + HTMX** | Минимум JS, простой интерфейс |
| Конфиг | **python-dotenv** | Загрузка .env |
| Расписание | **APScheduler** | Плановое обновление цен |

---

## 13. Веб-интерфейс

### Страница 1: Магазины (`/`) ✅

1. **Форма добавления магазина:**
   - Поле «Код магазина» (store_code) — при вводе данные подтягиваются из БД
   - Поле «Тип» (dropdown)
   - Поле «Город»
   - Поля «Адрес» и «Полный адрес»
   - Поле «Название»
   - Кнопка «Добавить магазин»

2. **Сканирование по адресу:**
   - Поле «Город»
   - Поле «Улица» (опционально)
   - Чекбоксы типов (по умолчанию: Магнит, Мини, Семейный, Экстра, Моя цена)
   - Кнопка «Сканировать» → синхронный запрос с ожиданием ответа

3. **Таблица магазинов:**
   - Чекбокс «Выбрать все» в заголовке
   - Чекбоксы у каждой строки
   - Колонки: Тип, Город, Адрес, Код, Действия (без ID)
   - Сортировка по адресу (полному тексту)
   - Прокрутка: max-height 480px (~10 строк), далее вертикальный скролл
   - Кнопка «Удалить выбранные (N)» — появляется при выборе

### Страница 2: Каталог (`/catalog`) 🚧

1. **Дерево категорий:**
   - Раскрывающееся дерево (родительские → дочерние)
   - Переключатель «Отслеживать» у каждой категории
   - Колонки: название, кол-во товаров, дата сканирования

2. **Кнопки:**
   - «Обновить категории» — сканировать каталог
   - «Сканировать товары» — запустить сканирование отслеживаемых категорий

### Страница 3: Товары (`/products`) 🚧

1. **Фильтры:**
   - Категория (dropdown)
   - Диапазон цен (min-max)
   - Сортировка: по цене, по названию, по скидке

2. **Таблица товаров:**
   - Картинка, название, текущая цена, старая цена (зачёркнута)
   - Процент скидки (красный бейдж)
   - Кнопка «История цен» → модальное окно с графиком

### Страница 4: Скидки (`/deals`) 🚧

1. **Товары со сниженными ценами:**
   - Карточки товаров: картинка, название, было/стало, % скидки
   - Группировка по категориям
   - Фильтр: минимальная скидка (%)

2. **Уведомления:**
   - Список последних изменений цен
   - Фильтр: только снижения > 10%

### Страница 5: Задания (`/jobs`) 🚧

- Таблица заданий: тип, статус, прогресс, дата
- Кнопка «Запустить сейчас» для каждого типа

---

## 14. Trade-offs

| Решение | Компромисс | Обоснование |
|---------|-----------|-------------|
| SQLite вместо PostgreSQL | Ограниченная запись | 1 пользователь, нет конкуренции |
| Jinja2 + HTMX вместо React | Меньше интерактивности | Не нужен SPA, быстрее разработка |
| Прямой API вместо Playwright для магазинов | Зависимость от внутреннего API | В 10-100x быстрее, стабильнее |
| Синхронное сканирование | Блокировка запроса (~10-60 сек) | Для 1 пользователя достаточно, нет проблем с фоном |
| APScheduler вместо cron | Привязка к процессу | Проще, не требует внешней системы |
| price_history отдельной таблицой | Дублирование данных | Можно удалять старую историю, не трогая products |
| Без Docker | Привязка к ОС | Быстрее старт разработки |
| ID как хэш вместо автоинкремента | Нечитаемые ID | Идемпотентность, уникальность, нет коллизий |

---

## 15. Стратегия развёртывания

### Фаза 1 (MVP) — База данных и CRUD магазинов ✅ ВЫПОЛНЕНО
- FastAPI сервер с SQLite
- Модель `Store` (id=хэш, store_code, store_type, city, address, full_address, name)
- REST API для CRUD магазинов (`/api/stores`), ID — строка-хэш
- HTML+Jinja2 интерфейс для просмотра/добавления магазинов
- Сканирование через API Магнита (`POST /api/stores/scan`, **синхронно**)
- Выбор магазина из БД (`POST /api/stores/select`)
- Автозаполнение формы (`GET /api/stores/by-code/{code}`)
- Массовое удаление (`POST /api/stores/delete-batch`)
- Список магазинов: сортировка по адресу, прокрутка, скрытый ID
- Маппинг типов: актуализирован по данным magnit.ru/shops
- Дедупликация по `store_code` при сканировании

### Фаза 2 — Сканирование каталога 🚧
- Модель `Category` + `Product` + `PriceHistory`
- Клиент для API Магнита (`magnit_api.py`) — requests, без Playwright
- Эндпоинт `POST /api/categories/scan` — получить все категории
- Эндпоинт `POST /api/catalog/scan` — сканировать товары (фоновая задача)
- UI: дерево категорий с переключателями «Отслеживать»

### Фаза 3 — Мониторинг цен 🚧
- Эндпоинт `POST /api/prices/update` — обновление цен (фоновая задача)
- Эндпоинт `GET /api/prices/decreased` — товары со сниженными ценами
- Эндпоинт `GET /api/products/{id}/history` — история цен + график
- APScheduler: ежедневное обновление цен
- Уведомления о значительных снижениях (>10%)

### Фаза 4 — Улучшения UI 🚧
- Поиск с автодополнением (город → улица)
- Экспорт/импорт CSV
- Пагинация и фильтрация
- Графики истории цен (Chart.js или lightweight-charts)
- Статистика: сколько магазинов/товаров, динамика цен
- Страница «Скидки» с карточками товаров
