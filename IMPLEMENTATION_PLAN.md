# План реализации: Веб-сервер выбора магазина Магнит

## 1. Обзор требований

### Функциональные требования

#### Модуль 1: Выбор магазина
- Поиск магазина по адресу (город + улица)
- Фильтрация по типу магазина (Экстра, Мини, Семейный и т.д.)
- Ручное управление списком магазинов/адресов
- Автоматический выбор магазина через Playwright
- Получение `store_code` и `store_type` для API запросов
- Сканирование всех магазинов города/улицы с сохранением в БД

#### Модуль 2: Каталог товаров и мониторинг цен
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
- Надёжность: локальная БД, бэкапы
- Удобство: веб-интерфейс + REST API
- Хранение истории цен: ~1000 товаров × 30 дней = ~30K записей

### Ограничения
- Небольшой трафик (один пользователь)
- Python-экосистема
- Локальный запуск (без облака)
- API Магнита может иметь лимиты запросов

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
│   Browser    │  ← Веб-интерфейс (Vue/HTMX) или REST API
└──────┬───────┘
       │
┌──────▼───────┐
│  FastAPI     │  ← Веб-сервер
│  Server      │
└──┬───┬───┬───┘
   │   │   │
   │   │   └──────────────────┐
   │   │                      │
   ▼   ▼                      ▼
┌───────┐              ┌──────────────┐
│SQLite │              │  Playwright   │
│  DB   │              │  (авто-клик)  │
└───────┘              └──────────────┘
```

---

## 4. Варианты хранения адресов

### Вариант 1: SQLite (рекомендуется)
- **Плюсы:** встроенный, не требует установки, SQL-запросы, транзакции
- **Минусы:** один писатель, но для нашего случая не критично
- **Когда:** основной вариант, если нужно искать по городу/улице/типу

### Вариант 2: JSON-файл
- **Плюсы:** проще некуда, легко редактировать вручную
- **Минусы:** нет индексов, медленный поиск, нет транзакций
- **Когда:** если магазинов < 50 и не нужен поиск

### Вариант 3: CSV/Excel
- **Плюсы:** удобно заполнять из таблицы
- **Минусы:** не подходит для runtime-запросов
- **Когда:** для первичного заполнения, потом импорт в SQLite

### Вариант 4: YAML-конфиг
- **Плюсы:** человекочитаемый, версионируется в git
- **Минусы:** не масштабируется
- **Когда:** если список магазинов почти не меняется

### Итоговая рекомендация
**SQLite + YAML-импорт**: данные хранятся в SQLite для быстрого поиска, а YAML используется для начального заполнения и версионирования в git.

---

## 5. Структура проекта

```
magnit_goods/
├── server/
│   ├── __init__.py
│   ├── main.py              # FastAPI приложение
│   ├── database.py          # SQLAlchemy + SQLite
│   ├── models.py            # ORM модели (Store, Category, Product, PriceHistory, ScanJob)
│   ├── schemas.py           # Pydantic схемы
│   ├── scheduler.py         # APScheduler для планового обновления цен
│   ├── routes/
│   │   ├── __init__.py
│   │   ├── stores.py        # CRUD магазинов + сканирование
│   │   ├── catalog.py       # Категории, товары, цены
│   │   ├── prices.py        # История цен, уведомления, аналитика
│   │   ├── jobs.py          # Статус заданий
│   │   └── web.py           # HTML-страницы (HTMX)
│   ├── services/
│   │   ├── __init__.py
│   │   ├── magnit_api.py    # Клиент для API Магнита (requests)
│   │   ├── store_selector.py # MagnitStoreSelector (Playwright)
│   │   ├── catalog_scanner.py # Сканирование каталога
│   │   ├── price_tracker.py  # Отслеживание изменений цен
│   │   └── notifications.py  # Генерация уведомлений
│   └── templates/
│       ├── base.html
│       ├── stores.html       # Управление магазинами
│       ├── catalog.html      # Каталог категорий
│       ├── products.html     # Список товаров
│       ├── price_history.html # История цен + график
│       └── deals.html        # Товары со скидками
├── data/
│   ├── stores.yaml           # Справочник магазинов
│   └── import_stores.py      # Импорт YAML → SQLite
├── migrations/               # Alembic миграции
├── backups/                  # Автоматические бэкапы SQLite
├── .env
├── requirements.txt
└── PLAN.md
```

---

## 6. Схема данных (SQLite)

### Таблица 1: `stores` — Магазины

```sql
CREATE TABLE stores (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    store_code  TEXT    NOT NULL UNIQUE,  -- код магазина для API
    store_type  TEXT    NOT NULL,         -- Экстра, Мини, Семейный...
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

#### Модуль 1: Магазины

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/api/stores` | Список всех магазинов (фильтр: `?city=...&type=...`) |
| `POST` | `/api/stores` | Добавить магазин |
| `PUT` | `/api/stores/{id}` | Обновить магазин |
| `DELETE` | `/api/stores/{id}` | Удалить магазин |
| `GET` | `/api/stores/search` | Поиск по адресу (`?q=Новочебоксарск+Строителей`) |
| `POST` | `/api/scan` | Сканирование магазинов по городу/улице → сохранение в БД |
| `POST` | `/api/select` | Выбор магазина из БД по адресу и типу |

#### Модуль 2: Каталог и цены

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
| `GET` | `/api/jobs` | Статус заданий на сканирование |

#### Общие

| Метод | Путь | Описание |
|-------|------|----------|
| `GET` | `/api/env` | Текущие `.env` значения |
| `POST` | `/api/import` | Импорт из YAML/CSV |

### `POST /api/scan` — сканирование магазинов

**Запрос:**
```json
{
  "city": "Новочебоксарск",
  "street": "ул. Строителей",
  "store_types": ["Экстра", "Мини", "Семейный"],
  "force_update": false
}
```

**Ответ:**
```json
{
  "scanned": 15,
  "added": 12,
  "updated": 3,
  "stores": [
    {
      "store_code": "12345",
      "store_type": "Экстра",
      "name": "Магнит Экстра",
      "full_address": "Чувашская Республика, г Новочебоксарск, ул Строителей, зд 21",
      "city": "Новочебоксарск",
      "street": "ул Строителей"
    }
  ]
}
```

### `POST /api/select` — выбор магазина из БД

**Запрос:**
```json
{
  "city": "Новочебоксарск",
  "street": "ул. Строителей",
  "store_type": "Экстра",
  "update_env": true
}
```

**Ответ:**
```json
{
  "store_code": "12345",
  "store_type": "Экстра",
  "name": "Магнит Экстра",
  "address": "Чувашская Республика - Чувашия, г Новочебоксарск, ул Строителей, зд 21",
  "city": "Новочебоксарск",
  "env_updated": true
}
```

---

## 8. Data Flow

### Сценарий 1: Выбор магазина из базы данных по адресу и типу

```
Пользователь → Вводит: город, улица, тип магазина → POST /api/select

1. Сервер принимает запрос:
   {
     "city": "Новочебоксарск",
     "street": "ул. Строителей",   -- опционально
     "store_type": "Экстра",
     "update_env": true
   }

2. Поиск в SQLite:
   ├── Если указана улица:
   │     SELECT * FROM stores
   │     WHERE city = 'Новочебоксарск'
   │       AND full_address LIKE '%ул. Строителей%'
   │       AND store_type = 'Экстра'
   │       AND is_active = 1
   │     LIMIT 1;
   │
   └── Если улица НЕ указана:
         SELECT * FROM stores
         WHERE city = 'Новочебоксарск'
           AND store_type = 'Экстра'
           AND is_active = 1
         LIMIT 1;

3. Результат:
   ├── Магазин найден в БД:
   │   ├── Возвращаем store_code, store_type, address
   │   ├── Если update_env=true → обновляем .env
   │   └── Готово (Playwright НЕ запускается)
   │
   └── Магазин НЕ найден:
       ├── Вариант А: вернуть 404 "Магазин не найден в базе"
       └── Вариант Б: запустить Playwright для поиска (см. Сценарий 2)
```

### Сценарий 2: Сканирование магазинов по городу/улице с добавлением в БД

> **Ключевая особенность:** сканирование магазинов — долгая операция (2-5 минут на город), поэтому
> оно запускается как **фоновая задача** через `BackgroundTasks`, а клиент отслеживает прогресс через `GET /api/jobs/{job_id}`.

#### 2.1. Архитектура взаимодействия

```
┌──────────┐      POST /api/scan       ┌───────────┐
│ Browser  │ ─────────────────────────> │  FastAPI   │
│  (UI)    │ <────────────────────────  │  Server    │
│          │   {job_id: 42} (сразу!)    │            │
│          │                            │            │
│          │   GET /api/jobs/42         │  ┌─────────▼──────────┐
│          │ ─────────────────────────> │  │ BackgroundTask      │
│          │ <────────────────────────  │  │  scan_stores()      │
│          │   {status: running,        │  │                     │
│            progress: 60%}             │  │  ┌───────────────┐  │
│          │                            │  │  │  Playwright   │  │
│          │   GET /api/jobs/42         │  │  │  (headless)   │  │
│          │ ─────────────────────────> │  │  └───────┬───────┘  │
│          │ <────────────────────────  │  │          │          │
│          │   {status: completed,      │  │  ┌───────▼───────┐  │
│            stores: [...]}             │  │  │  SQLite DB    │  │
└──────────┘                            │  │  │  INSERT stores│  │
                                        │  │  └───────────────┘  │
                                        │  └─────────────────────┘
                                        └───────────┘
```

#### 2.2. Пошаговый flow

**ШАГ 1: Клиент发起 сканирование**

```
POST /api/scan
{
  "city": "Новочебоксарск",
  "street": null,
  "store_types": ["Экстра", "Мини", "Семейный"],
  "force_update": false
}
```

Сервер:
1. Валидирует входные данные (Pydantic)
2. Проверяет, нет ли уже запущенного задания `job_type='stores'` с `status='running'`
3. Создаёт запись в `scan_jobs`:
   ```sql
   INSERT INTO scan_jobs (job_type, store_code, status, created_at)
   VALUES ('stores', NULL, 'pending', CURRENT_TIMESTAMP);
   ```
4. Запускает фоновую задачу: `BackgroundTasks.add(scan_stores_background, job_id, params)`
5. **Сразу** возвращает `{job_id: 42, status: "pending"}`

**ШАГ 2: Фоновая задача запускается**

```python
async def scan_stores_background(job_id: int, params: ScanRequest):
    db = SessionLocal()
    try:
        # 2.1. Обновляем статус
        db.execute(update(scan_jobs).where(scan_jobs.c.id == job_id)
                   .values(status="running", started_at=datetime.now()))
        db.commit()

        # 2.2. Запускаем Playwright в отдельном потоке
        result = await asyncio.to_thread(run_playwright_scan, params, db, job_id)

        # 2.3. Успех
        db.execute(update(scan_jobs).where(scan_jobs.c.id == job_id).values(
            status="completed",
            finished_at=datetime.now(),
            items_scanned=result["scanned"],
            items_added=result["added"],
            items_updated=result["updated"]
        ))
        db.commit()

    except Exception as e:
        # 2.4. Ошибка
        db.execute(update(scan_jobs).where(scan_jobs.c.id == job_id).values(
            status="failed",
            error_message=str(e),
            finished_at=datetime.now()
        ))
        db.commit()
    finally:
        db.close()
```

**ШАГ 3: Playwright сканирует**

```python
def run_playwright_scan(params: ScanRequest, db, job_id: int) -> dict:
    selector = MagnitStoreSelector(headless=True)
    selector.start()

    try:
        # 3.1. Открыть панель выбора
        selector.open_store_selector()
        selector.select_mode_in_store()
        selector.click_select_store_button()

        # 3.2. Ввести адрес
        address = params.city
        if params.street:
            address += f", {params.street}"
        selector.enter_address(address)

        found_stores = []
        total_types = len(params.store_types)

        # 3.3. Для каждого типа магазина
        for i, stype in enumerate(params.store_types):
            # Обновляем прогресс в БД (опционально)
            progress = int((i / total_types) * 100)
            update_job_progress(db, job_id, progress, f"Сканирую тип: {stype}")

            # Выбрать тип
            selector.select_store_type(stype)
            time.sleep(1)  # ждём обновления списка

            # Собрать все магазины
            items = selector.get_all_stores_from_list()
            for item in items:
                store_data = parse_store_item(item, stype, params.city)
                found_stores.append(store_data)

            # Сбросить фильтр
            selector.select_store_type("Все")
            time.sleep(0.5)

        # 3.4. Сохранить в БД
        added = 0
        updated = 0
        for store in found_stores:
            if params.force_update:
                db.execute(upsert(stores, store))
                updated += 1
            else:
                if db.execute(insert_ignore(stores, store)):
                    added += 1

        return {"scanned": len(found_stores), "added": added, "updated": updated}

    finally:
        selector.close()
```

**ШАГ 4: Клиент отслеживает прогресс**

```
GET /api/jobs/42

Ответ (во время выполнения):
{
  "job_id": 42,
  "job_type": "stores",
  "status": "running",
  "progress": 60,
  "progress_message": "Сканирую тип: Семейный",
  "started_at": "2026-04-12T10:00:00",
  "items_scanned": 8,
  "items_added": 6,
  "items_updated": 2
}

Ответ (после завершения):
{
  "job_id": 42,
  "status": "completed",
  "finished_at": "2026-04-12T10:03:15",
  "items_scanned": 15,
  "items_added": 12,
  "items_updated": 3,
  "stores": [
    {"store_code": "12345", "store_type": "Экстра", "full_address": "..."},
    ...
  ]
}
```

#### 2.3. Обновление прогресса в реальном времени

Есть два варианта:

**Вариант А: Периодический polling (рекомендую)**

Клиент каждые 2 секунды делает `GET /api/jobs/{job_id}` и обновляет прогресс-бар.

```javascript
// HTMX + Alpine.js
setInterval(() => {
    htmx.ajax('GET', `/api/jobs/${jobId}`, {target: '#job-status'});
}, 2000);
```

Плюсы: просто, надёжно, не нужно держать соединение.
Минусы: небольшая задержка обновления.

**Вариант Б: Server-Sent Events (SSE)**

Сервер стримит события:

```python
@app.get("/api/jobs/{job_id}/stream")
async def job_stream(job_id: int):
    async def event_generator():
        while True:
            job = db.query(ScanJob).get(job_id)
            yield f"data: {job.to_json()}\n\n"
            if job.status in ("completed", "failed"):
                break
            await asyncio.sleep(1)
    return EventSourceResponse(event_generator())
```

Плюсы: реальное время, нет лишних запросов.
Минусы: сложнее реализация, нужно держать соединение.

**Рекомендация:** начать с polling (Вариант А). Если нужно плавнее — перейти на SSE.

#### 2.4. Обработка ошибок

| Ошибка | Поведение |
|--------|-----------|
| magnit.ru недоступен | `status=failed`, `error_message="Сайт недоступен"` |
| Playwright упал (crash) | `status=failed`, `error_message="Playwright error: ..."` |
| Таймаут элемента (>15 сек) | Retry 2 раза → `status=failed` |
| Адрес не найден на карте | `status=completed`, `items_scanned=0`, предупреждение |
| Дубликат магазина | `INSERT OR IGNORE` → пропускается (или UPDATE если `force_update`) |
| Уже запущено сканирование | `409 Conflict: "Сканирование уже выполняется"` |

#### 2.5. UI для сканирования

```
┌──────────────────────────────────────────────────────────┐
│              Сканирование магазинов                       │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  Город:  [Новочебоксарск          ▼]                     │
│  Улица:  [                       ]  (необязательно)      │
│                                                          │
│  Типы магазинов:                                         │
│  ☑ Экстра   ☑ Мини   ☐ Семейный   ☐ Магнит              │
│  ☐ Опт   ☐ Моя цена   ☐ Заряд                           │
│                                                          │
│  ☑ Обновить существующие записи (upsert)                 │
│                                                          │
│          [ ▶ Начать сканирование ]                       │
│                                                          │
├──────────────────────────────────────────────────────────┤
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │  Задание #42  ● Выполняется...                     │  │
│  │  ████████████████░░░░░░░░  60%                     │  │
│  │  Сканирую тип: Семейный                            │  │
│  │  Найдено: 8 | Добавлено: 6 | Обновлено: 2          │  │
│  │  Запущено: 12.04.2026 10:00:00                     │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │  № │ Тип      │ Адрес                  │ Код      │  │
│  ├────────────────────────────────────────────────────┤  │
│  │  1 │ Экстра   │ ул. Строителей, 21     │ 12345    │  │
│  │  2 │ Экстра   │ ул. Ленина, 5          │ 12346    │  │
│  │  3 │ Мини     │ ул. Мира, 10           │ 12347    │  │
│  │  ...                                               │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

#### 2.6. Парсинг данных магазина

Из элемента списка на сайте magnit.ru извлекаем:

```
Текст элемента:
"Магнит Экстра
Чувашская Республика - Чувашия, г Новочебоксарск, ул Строителей, зд 21"
        ↓
store_type = "Экстра"          (из выбранного фильтра)
name = "Магнит Экстра"         (первая строка)
full_address = "Чувашская Республика - Чувашия, г Новочебоксарск, ул Строителей, зд 21"
city = "Новочебоксарск"        (regex: г\s*(\w+))
address = "ул Строителей, зд 21"  (всё после города)
store_code = ???               (извлекается из API при выборе или из БД)
```

> **Проблема:** `store_code` не отображается на сайте напрямую.
>
> **Решение 1:** После выбора магазина через Playwright — перехватить запрос к API и извлечь `storeCode` из body.
>
> **Решение 2:** Использовать API Магнита: по адресу найти магазин и получить код.
>
> **Решение 3:** Если код не удалось получить — оставить пустым, обновить позже через API.

---

## 9. Data Flow — Модуль каталога и цен

### Сценарий 3: Сканирование каталога (категории + товары)

```
Пользователь → Выбрал магазин → Запустил сканирование каталога → POST /api/catalog/scan

1. Сервер запускает фоновую задачу (BackgroundTasks):
   ├── Создаёт запись в scan_jobs: status='pending'
   └── Возвращает job_id клиенту сразу

2. Фоновая задача выполняет:
   ├── Обновляет job: status='running'
   │
   ├── ШАГ А: Сканирование категорий
   │   ├── Через API Магнита (или Playwright) получаем все категории:
   │   │   POST https://magnit.ru/webgate/v1/goods/filters
   │   │   Body: {"storeCodes": ["12345"], "catalogType": "1"}
   │   ├── Парсим ответ: categoryID, name, productCount
   │   ├── Сохраняем в categories (INSERT OR IGNORE)
   │   └── Для каждой категории: is_tracked = False (по умолчанию)
   │
   ├── ШАГ Б: Сканирование товаров по отслеживаемым категориям
   │   ├── Для каждой категории с is_tracked=True:
   │   │   ├── Запрашиваем товары (пагинация, LIMIT=50):
   │   │   │   POST https://magnit.ru/webgate/v1/goods
   │   │   │   Body: {
   │   │   │     "categories": [4884, 64591, ...],
   │   │   │     "storeCode": "12345",
   │   │   │     "pagination": {"limit": 50, "offset": 0},
   │   │   │     "sort": {"type": "popularity", "order": "desc"}
   │   │   │   }
   │   │   ├── Для каждого товара:
   │   │   │   ├── Если товар новый → INSERT в products
   │   │   │   ├── Если существующий → UPDATE price, last_seen
   │   │   │   ├── Если цена изменилась → INSERT в price_history
   │   │   │   └── Определяем change_type:
   │   │   │       - 'initial' (первый раз)
   │   │   │       - 'decreased' (цена снизилась)
   │   │   │       - 'increased' (цена выросла)
   │   │   │       - 'unchanged' (без изменений)
   │   │   └── Обновляем category.product_count, category.last_scanned
   │   │
   │   └── Пауза между запросами (rate limiting): 0.5-1 сек
   │
   └── ШАГ В: Завершение
       ├── Обновляем job: status='completed', items_scanned=N
       └── Генерируем уведомления о сниженных ценах

3. Клиент проверяет статус: GET /api/jobs/{job_id}
   └── Когда status='completed' → показывает результаты
```

### Сценарий 4: Получение товаров со сниженными ценами

```
Пользователь → GET /api/prices/decreased?store_code=12345&category_id=4884

1. SQL-запрос:
   SELECT p.*, ph.price as previous_price,
          (ph.price - p.price) as discount_amount,
          ROUND((ph.price - p.price) / ph.price * 100, 1) as discount_percent
   FROM products p
   JOIN price_history ph ON p.product_id = ph.product_id
   WHERE p.store_code = '12345'
     AND p.category_id = 4884
     AND p.last_price_change IS NOT NULL
     AND ph.change_type = 'decreased'
     AND ph.recorded_at = (
         SELECT MAX(recorded_at) FROM price_history
         WHERE product_id = p.product_id
     )
   ORDER BY discount_percent DESC;

2. Возвращаем отсортированный список:
   {
     "products": [
       {
         "name": "Молоко Простоквашино 3.2%",
         "current_price": 79.90,
         "previous_price": 99.90,
         "discount_amount": 20.00,
         "discount_percent": 20.0,
         "category": "Молоко, сыр, яйца"
       }
     ]
   }
```

### Сценарий 5: История цен товара

```
Пользователь → GET /api/products/{product_id}/history?days=30

1. SQL-запрос:
   SELECT price, old_price, recorded_at, change_type
   FROM price_history
   WHERE product_id = {product_id}
     AND recorded_at >= date('now', '-30 days')
   ORDER BY recorded_at ASC;

2. Возвращаем данные для графика:
   {
     "product": "Молоко Простоквашино 3.2%",
     "current_price": 79.90,
     "min_price": 69.90,
     "max_price": 109.90,
     "avg_price": 89.50,
     "history": [
       {"date": "2026-03-13", "price": 99.90, "change": "unchanged"},
       {"date": "2026-03-20", "price": 89.90, "change": "decreased"},
       {"date": "2026-04-01", "price": 79.90, "change": "decreased"}
     ]
   }
```

### Сценарий 6: Плановое обновление цен (по расписанию)

```
APScheduler → каждый день в 08:00 → обновить цены

1. Находим все отслеживаемые категории:
   SELECT DISTINCT store_code, category_id
   FROM categories
   WHERE is_tracked = 1;

2. Для каждой (store_code, category_id):
   ├── Запрашиваем товары из API Магнита
   ├── Сравниваем цены с текущими в products
   ├── Записываем изменения в price_history
   └── Обновляем products.last_price_change

3. Генерируем уведомления:
   ├── Товары со скидкой > 10%
   ├── Товары, которых не было в наличии, теперь есть
   └── Новые товары в отслеживаемых категориях
```

---

## 10. Стратегия масштабирования

Для данного проекта **не нужно** масштабирование. Но если понадобится:

| Рост | Решение |
|------|---------|
| Много запросов | Playwright → headless-кластер |
| Много пользователей | Docker + PostgreSQL |
| Несколько регионов | API Gateway + репликация БД |

---

## 10. Отказоустойчивость

- **Playwright падает:** таймауты, повторные попытки, фоллбэк на SQLite
- **SQLite повреждается:** бэкап при каждом запуске
- **Сайт magnit.ru недоступен:** кешированные данные из БД

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
| Backend | **FastAPI** | Быстро, Pydantic, async, BackgroundTasks, автодокументация |
| БД | **SQLite** | Встроенный, не требует установки |
| ORM | **SQLAlchemy 2.0** | Типизированный, миграции через Alembic |
| Выбор магазина | **Playwright** | Уже используется в проекте |
| API Магнита | **requests** | Каталог через REST API (быстрее Playwright) |
| UI | **HTMX + Jinja2** | Минимум JS, простой интерфейс |
| Графики цен | **Chart.js** | Лёгкий, рисует графики на клиенте |
| Конфиг | **python-dotenv** | Уже в проекте |
| Миграции | **Alembic** | Стандарт для SQLAlchemy |
| Расписание | **APScheduler** | Плановое обновление цен |
| User-Agent | **fake-useragent** | Уже в проекте |

---

## 13. Веб-интерфейс

### Страница 1: Магазины (`/stores`)

1. **Форма поиска магазина:**
   - Поле «Город» (autocomplete)
   - Поле «Улица» (autocomplete)
   - Выпадающий список «Тип магазина»
   - Кнопка «Найти»

2. **Сканирование магазинов:**
   - Город + улица + чекбоксы типов
   - Кнопка «Начать сканирование»
   - Прогресс-бар + таблица результатов

3. **Таблица магазинов:**
   - Список с фильтрацией по городу/типу
   - Кнопка «Выбрать» → обновляет `.env`

### Страница 2: Каталог (`/catalog`)

1. **Дерево категорий:**
   - Раскрывающееся дерево (родительские → дочерние)
   - Переключатель «Отслеживать» у каждой категории
   - Колонки: название, кол-во товаров, дата сканирования

2. **Кнопки:**
   - «Обновить категории» — сканировать каталог
   - «Сканировать товары» — запустить сканирование отслеживаемых категорий

### Страница 3: Товары (`/products`)

1. **Фильтры:**
   - Категория (dropdown)
   - Диапазон цен (min-max)
   - Сортировка: по цене, по названию, по скидке

2. **Таблица товаров:**
   - Картинка, название, текущая цена, старая цена (зачёркнута)
   - Процент скидки (красный бейдж)
   - Кнопка «История цен» → модальное окно с графиком

### Страница 4: Скидки (`/deals`)

1. **Товары со сниженными ценами:**
   - Карточки товаров: картинка, название, было/стало, % скидки
   - Группировка по категориям
   - Фильтр: минимальная скидка (%)

2. **Уведомления:**
   - Список последних изменений цен
   - Фильтр: только снижения > 10%

### Страница 5: Задания (`/jobs`)

- Таблица заданий: тип, статус, прогресс, дата
- Кнопка «Запустить сейчас» для каждого типа

---

## 14. Trade-offs

| Решение | Компромисс | Обоснование |
|---------|-----------|-------------|
| SQLite вместо PostgreSQL | Ограниченная запись | 1 пользователь, нет конкуренции |
| HTMX вместо React | Меньше интерактивности | Не нужен SPA, быстрее разработка |
| Playwright для магазинов, requests для каталога | Два подхода | Каталог — через API (быстрее), магазины — Playwright (нет API) |
| Фоновые задачи (BackgroundTasks) вместо Celery | Нет очередей, нет retry | Для 1 пользователя достаточно |
| APScheduler вместо cron | Привязка к процессу | Проще, не требует внешней системы |
| price_history отдельной таблицой | Дублирование данных | Можно удалять старую историю, не трогая products |
| Без Docker | Привязка к ОС | Быстрее старт разработки |

---

## 15. Стратегия развёртывания

### Фаза 1 (MVP) — База данных и CRUD магазинов
- FastAPI сервер с SQLite
- Модель `Store` (store_code, store_type, city, address, full_address, name)
- REST API для CRUD магазинов (`/api/stores`)
- Простой HTML+HTMX интерфейс для просмотра/добавления магазинов
- Ручной импорт из YAML

### Фаза 2 — Сканирование магазинов
- Интеграция Playwright для сканирования (`POST /api/scan`)
- Алгоритм обхода всех типов магазинов для города/улицы
- Извлечение данных: название, адрес, город, улица, store_code
- Сохранение найденных магазинов в SQLite
- UI-форма для сканирования с чекбоксами типов

### Фаза 3 — Выбор магазина и авто-обновление
- Эндпоинт `POST /api/select` — выбор из БД по адресу и типу
- Автоматическое обновление `.env` при выборе
- Фоллбэк: если магазин не найден в БД → предложение отсканировать
- Кеширование Playwright-сессии

### Фаза 4 — Сканирование каталога
- Модель `Category` + `Product` + `PriceHistory`
- Клиент для API Магнита (`magnit_api.py`) — requests, без Playwright
- Эндпоинт `POST /api/categories/scan` — получить все категории
- Эндпоинт `POST /api/catalog/scan` — сканировать товары (фоновая задача)
- UI: дерево категорий с переключателями «Отслеживать»

### Фаза 5 — Мониторинг цен
- Эндпоинт `POST /api/prices/update` — обновление цен (фоновая задача)
- Эндпоинт `GET /api/prices/decreased` — товары со сниженными ценами
- Эндпоинт `GET /api/products/{id}/history` — история цен + график
- APScheduler: ежедневное обновление цен
- Уведомления о значительных снижениях (>10%)

### Фаза 6 — Улучшения UI
- Поиск с автодополнением (город → улица)
- Экспорт/импорт CSV
- Пагинация и фильтрация
- Графики истории цен (Chart.js или lightweight-charts)
- Статистика: сколько магазинов/товаров, динамика цен
- Страница «Скидки» с карточками товаров
