# Code Review — magnit_goods

> Дата: 2026-06-12  
> Охват: все файлы `src/server/` (routes, services, models, scheduler)  
> Направления: качество кода + производительность БД

---

## Итоговая оценка

| Категория | Оценка | Статус |
|-----------|--------|--------|
| Структура проекта | 7/10 | ⚠️ Есть нарушения |
| Качество кода | 6/10 | ⚠️ Средний |
| Производительность БД | 5/10 | 🔴 Критические проблемы |
| Обработка ошибок | 5/10 | ⚠️ Неполная |
| Безопасность | 6/10 | ⚠️ Есть риски |
| Поддерживаемость | 6/10 | ⚠️ Дублирование кода |

---

## 🔴 КРИТИЧЕСКИЕ ПРОБЛЕМЫ

### 1. N+1 запрос в `get_categories_tree` — убийца производительности

**Файл:** `src/server/routes/catalog.py`, строки 125–159  
**Серьёзность:** Критическая  
**Тип:** Производительность БД

**Описание:**  
`build_tree()` — рекурсивная функция, которая для каждого узла делает отдельный `SELECT` в БД. При 20 корневых категориях × 10 дочерних = **200+ запросов** за один HTTP-вызов.

```python
# ❌ ТЕКУЩИЙ КОД
def build_tree(category, parent_id=None):
    children = (
        db.query(Category)
        .filter(Category.parent_id == category.id)
        .order_by(Category.name)
        .all()
    )
    # для каждого child — снова build_tree() → снова SELECT
    for child in children:
        result["children"].append(build_tree(child, category.id))
```

**Исправление:**

```python
# ✅ Один SELECT, сборка дерева в памяти
@router.get("/categories/tree")
def get_categories_tree(db: Session = Depends(get_db)):
    all_cats = db.query(Category).order_by(Category.name).all()

    cat_map = {
        c.id: {
            "id": c.id,
            "name": c.name,
            "url": c.url,
            "magnit_id": c.magnit_id,
            "is_tracked": c.is_tracked,
            "product_count": c.product_count,
            "parent_id": c.parent_id,
            "children": [],
        }
        for c in all_cats
    }

    roots = []
    for cat in cat_map.values():
        if cat["parent_id"] is None:
            roots.append(cat)
        else:
            parent = cat_map.get(cat["parent_id"])
            if parent:
                parent["children"].append(cat)
    return roots
```

**Ожидаемый эффект:** сокращение с 200+ запросов до **1 запроса**.

---

### 2. 4 отдельных `COUNT` в `get_products_stats`

**Файл:** `src/server/routes/catalog.py`, строки 377–400  
**Серьёзность:** Критическая  
**Тип:** Производительность БД

**Описание:**  
Каждый вызов `/api/products/stats` выполняет 5 отдельных запросов к одной таблице.

```python
# ❌ ТЕКУЩИЙ КОД — 5 запросов
total = query.count()
in_stock = query.filter(Product.in_stock == True).count()
with_price_decrease = query.filter(Product.price_change_percent > 0).count()
with_price_increase = query.filter(Product.price_change_percent < 0).count()
last_update = query.order_by(Product.last_seen.desc()).first()
```

**Исправление:**

```python
# ✅ Один запрос с CASE WHEN
from sqlalchemy import func, case

row = db.query(
    func.count().label("total"),
    func.sum(case((Product.in_stock == True, 1), else_=0)).label("in_stock"),
    func.sum(case((Product.price_change_percent > 0, 1), else_=0)).label("with_price_decrease"),
    func.sum(case((Product.price_change_percent < 0, 1), else_=0)).label("with_price_increase"),
    func.max(Product.last_seen).label("last_update"),
).filter(
    Product.store_code == store_code if store_code else True
).one()

return {
    "total": row.total or 0,
    "in_stock": row.in_stock or 0,
    "with_price_decrease": row.with_price_decrease or 0,
    "with_price_increase": row.with_price_increase or 0,
    "last_update": row.last_update.isoformat() if row.last_update else None,
}
```

**Ожидаемый эффект:** 5 запросов → **1 запрос**.

---

### 3. `cleanup_stale_products` загружает все товары в память для удаления

**Файл:** `src/server/services/catalog_scanner.py`, строки 598–627  
**Серьёзность:** Критическая  
**Тип:** Производительность БД / Memory

**Описание:**  
Метод загружает все ORM-объекты в RAM, затем удаляет их по одному. При 10 000+ товарах — большой расход памяти и N SQL `DELETE`.

```python
# ❌ ТЕКУЩИЙ КОД — N объектов в памяти, N DELETE
stale_products = self.db.query(Product).filter(
    Product.last_seen < cutoff_date,
    Product.store_code == self.store_code
).all()
count = len(stale_products)
for product in stale_products:
    self.db.delete(product)  # отдельный DELETE для каждого
self.db.commit()
```

**Исправление:**

```python
# ✅ Один DELETE запрос
def cleanup_stale_products(self, days_threshold: int = 7) -> int:
    """Удалить товары, не обновлявшиеся N дней."""
    cutoff_date = datetime.utcnow() - timedelta(days=days_threshold)
    deleted = self.db.query(Product).filter(
        Product.last_seen < cutoff_date,
        Product.store_code == self.store_code,
    ).delete(synchronize_session=False)
    self.db.commit()
    if deleted > 0:
        print(f"Удалено {deleted} устаревших товаров для {self.store_code}")
    return deleted
```

**Ожидаемый эффект:** O(N) памяти → O(1), N DELETE → **1 DELETE**.

---

### 4. Закрытая FastAPI-сессия используется в фоновой задаче

**Файл:** `src/server/routes/prices.py`, строки 85–111  
**Серьёзность:** Критическая  
**Тип:** Корректность / Потенциальный краш

**Описание:**  
FastAPI закрывает зависимость `db` (сессию) после отправки HTTP-ответа. Фоновая задача `run_update()` запускается уже после этого, поэтому использует **закрытую сессию** → SQLAlchemy выбросит ошибку.

```python
# ❌ ТЕКУЩИЙ КОД — db уже закрыта к моменту выполнения
def run_update():
    job_db = db.query(ScanJob).filter(ScanJob.id == job.id).first()  # ошибка!
    ...

if background_tasks:
    background_tasks.add_task(run_update)
    return {"job_id": job.id, "status": "pending"}
```

**Исправление:**

```python
# ✅ Новая сессия внутри фоновой задачи
job_id = job.id  # сохраняем ID до закрытия сессии

def run_update():
    from src.server.database import SessionLocal
    bg_db = SessionLocal()
    try:
        job_db = bg_db.query(ScanJob).filter(ScanJob.id == job_id).first()
        if not job_db:
            return
        job_db.status = "running"
        job_db.started_at = datetime.utcnow()
        bg_db.commit()
        try:
            scanner = CatalogScanner(bg_db, store_code=store_code, job_id=job_id)
            result = scanner.scan_products(category_ids=cat_ids, tracked_only=tracked_only)
            scanner.close()
            job_db.status = "completed"
            job_db.finished_at = datetime.utcnow()
            job_db.items_scanned = result["scanned"]
            job_db.items_added = result["added"]
            job_db.items_updated = result["updated"]
            bg_db.commit()
        except Exception as e:
            job_db.status = "failed"
            job_db.error_message = str(e)
            job_db.finished_at = datetime.utcnow()
            bg_db.commit()
    finally:
        bg_db.close()
```

---

### 5. Отсутствует составной индекс `(product_id, store_code)`

**Файл:** `src/server/models.py`, строки 88–138  
**Серьёзность:** Критическая  
**Тип:** Производительность БД

**Описание:**  
`product_id` не имеет `index=True`. Каждый `bulk_update_mappings` и `_save_products` выполняет запрос вида:
```sql
SELECT * FROM products WHERE product_id IN (...) AND store_code = '...'
```
Без составного индекса SQLite делает **полный скан таблицы** при каждом сканировании.

```python
# ❌ ТЕКУЩИЙ КОД — нет индекса на product_id
product_id = Column(Integer, nullable=False)   # index отсутствует
store_code = Column(String, nullable=False, index=True)
```

**Исправление:**

```python
# ✅ Добавить __table_args__ с составным индексом и UniqueConstraint
from sqlalchemy import UniqueConstraint, Index

class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        UniqueConstraint("product_id", "store_code", name="uq_product_store"),
        Index("ix_product_store_lookup", "product_id", "store_code"),
        Index("ix_product_price_change", "store_code", "price_change_percent"),
        Index("ix_product_last_scan", "store_code", "last_scan_found"),
    )
    
    # Убрать index=True с отдельного store_code (уже покрыт составным)
    product_id = Column(Integer, nullable=False)
    store_code = Column(String, nullable=False)
```

**Миграция** (добавить в `database.py`):

```python
def migrate_add_product_indexes(db):
    """Добавить составные индексы для ускорения операций с товарами."""
    try:
        db.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_product_store "
            "ON products(product_id, store_code)"
        ))
        db.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_product_price_change "
            "ON products(store_code, price_change_percent)"
        ))
        db.commit()
        print("+ Индексы для products добавлены")
    except Exception as e:
        print(f"- Ошибка добавления индексов: {e}")
        db.rollback()
```

---

## 🟠 ВАЖНЫЕ ПРОБЛЕМЫ

### 6. Дублирование константы `STORE_TYPE_TO_SHOP_TYPE` в трёх местах

**Серьёзность:** Важная  
**Тип:** Поддерживаемость / DRY

Один и тот же словарь определён в трёх местах:

| Файл | Имя переменной | Строки |
|------|----------------|--------|
| `src/server/models.py` | `Store.STORE_TYPE_TO_SHOP_TYPE` | 43–52 |
| `src/server/routes/stores.py` | `STORE_TYPE_TO_SHOP_TYPE` | 316–325 |
| `src/server/services/magnit_api.py` | `API_STORE_TYPE_CODE` | 327–336 |

**Исправление:** создать `src/server/constants.py`:

```python
# src/server/constants.py

# Числовые коды типов магазинов (для API и БД)
STORE_TYPE_CODES: dict[str, int] = {
    "Магнит": 1,
    "Мини": 2,
    "М.Косметик": 3,
    "Семейный": 5,
    "Экстра": 6,
    "Опт": 7,
    "Заряд": 8,
    "Моя цена": 9,
}

# API код → русское название
STORE_TYPE_MAP: dict[str, str] = {
    "MM": "Магнит",
    "ME": "Экстра",
    "DG": "М.Косметик",
    "GM": "Семейный",
    "MO": "Опт",
    "MC": "Моя цена",
    "ZARYAD": "Заряд",
    "MM_MINI": "Мини",
}
```

---

### 7. Миграции в `main.py` выполняются на уровне модуля

**Файл:** `src/server/main.py`, строки 20–221  
**Серьёзность:** Важная  
**Тип:** Архитектура / SRP

**Описание:**  
6 функций миграции вызываются при импорте модуля `main.py`. Это нарушает Single Responsibility Principle и делает невозможным импорт `main` в тестах без побочных эффектов.

```python
# ❌ Выполняются при импорте
init_db()
migrate_store_ids()
migrate_categories()
migrate_add_shop_type()
migrate_fill_shop_type()
migrate_add_last_scan_found()
migrate_add_scan_job_progress_fields()
```

**Исправление:**
1. Перенести все функции миграции в `database.py`
2. Вызывать через `lifespan` или единую `init_db()`:

```python
# src/server/database.py
def init_db():
    from src.server.models import Store, Category, Product, ScanJob
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        _migrate_simplify_price_tracking(db)
        _migrate_add_last_change_fields(db)
        _migrate_store_ids(db)
        _migrate_categories(db)
        _migrate_add_shop_type(db)
        _migrate_fill_shop_type(db)
        _migrate_add_last_scan_found(db)
        _migrate_add_scan_job_progress_fields(db)
        _migrate_add_product_indexes(db)
    finally:
        db.close()

# src/server/main.py
@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()  # единственная точка входа
    ...
    yield
    shutdown_scheduler()
```

---

### 8. `_mark_all_running_failed_on_startup` игнорирует большинство типов заданий

**Файл:** `src/server/routes/stores.py`, строки 35–46  
**Серьёзность:** Важная  
**Тип:** Корректность

**Описание:**  
При старте сервера помечаются как `failed` только задания с `job_type == "stores"`. Задания типов `"prices"`, `"catalog"`, `"scan_all_stores"` остаются в статусе `"running"` навсегда.

```python
# ❌ ТЕКУЩИЙ КОД — пропускает 3 типа заданий
stale_jobs = db.query(ScanJob).filter(
    ScanJob.job_type == "stores",  # ← только один тип!
    ScanJob.status == "running",
).all()
```

**Исправление:**

```python
# ✅ Все запущенные задания помечаем как прерванные
def _mark_all_running_failed_on_startup(db: Session):
    """При старте сервера пометить ВСЕ running-задания как failed."""
    stale_jobs = db.query(ScanJob).filter(
        ScanJob.status == "running",
    ).all()
    for job in stale_jobs:
        job.status = "failed"
        job.error_message = "Сервер был перезапущен, задание прервано"
        job.finished_at = datetime.utcnow()
    if stale_jobs:
        db.commit()
        print(f"Помечено как failed: {len(stale_jobs)} заданий")
```

---

### 9. `update_store` — неверный тип параметра `store_id`

**Файл:** `src/server/routes/stores.py`, строка 108  
**Серьёзность:** Важная  
**Тип:** Корректность / Типизация

```python
# ❌ store_id объявлен как int, но Store.id — строка (MD5-хэш 12 символов)
def update_store(store_id: int, data: StoreUpdate, db: Session = Depends(get_db)):
```

FastAPI попытается преобразовать URL-параметр в `int`, что вызовет ошибку `422 Unprocessable Entity` для любого хэш-ID.

```python
# ✅
def update_store(store_id: str, data: StoreUpdate, db: Session = Depends(get_db)):
```

---

### 10. `scan_all_stores` — SELECT на каждую категорию в двойном цикле

**Файл:** `src/server/routes/catalog.py`, строки 621–629  
**Серьёзность:** Важная  
**Тип:** Производительность БД

**Описание:**  
В цикле по магазинам × категориям для каждой категории делается `SELECT` в БД за её названием. При 50 категориях и 10 магазинах = **500 лишних запросов**.

```python
# ❌ ТЕКУЩИЙ КОД — SELECT внутри двойного цикла
for cat_idx, cat_code in enumerate(cat_codes):
    cat_obj = bg_db.query(Category).filter(Category.magnit_id == cat_code).first()
    if cat_obj:
        job_db.current_category_name = cat_obj.name
```

**Исправление:**

```python
# ✅ Загрузить маппинг один раз до цикла
cat_name_map = {
    cat.magnit_id: cat.name
    for cat in bg_db.query(Category.magnit_id, Category.name)
                     .filter(Category.magnit_id.in_(cat_codes))
                     .all()
}

for cat_idx, cat_code in enumerate(cat_codes):
    job_db.current_category_name = cat_name_map.get(cat_code, f"ID:{cat_code}")
    job_db.current_category_magnit_id = cat_code
```

---

### 11. `list_products` — `category_ids` парсится дважды

**Файл:** `src/server/routes/catalog.py`, строки 275–303  
**Серьёзность:** Важная  
**Тип:** Качество кода / DRY

```python
# ❌ ТЕКУЩИЙ КОД — одинаковый парсинг в двух разных блоках
if category_ids:
    cat_id_list = [int(x.strip()) for x in category_ids.split(',') if x.strip().isdigit()]
    ...
# ... 20 строк позже ...
if category_ids:
    cat_id_list = [int(x.strip()) for x in category_ids.split(',') if x.strip().isdigit()]
    scan_query = scan_query.filter(Product.category_id.in_(cat_id_list))
```

**Исправление:** распарсить один раз в начале функции:

```python
# ✅ В начале функции
cat_id_list: list[int] = []
if category_ids:
    cat_id_list = [int(x.strip()) for x in category_ids.split(',') if x.strip().isdigit()]

# Затем использовать cat_id_list везде
```

---

## 🟡 ЗАМЕЧАНИЯ

### 12. Избыточные `print(f"DEBUG: ...")` во всей кодовой базе

**Серьёзность:** Низкая  
**Тип:** Качество кода / Логирование

Проект использует `print()` вместо стандартного `logging`. Это означает:
- Нет уровней логирования (DEBUG/INFO/WARNING/ERROR)
- Нельзя отключить DEBUG-вывод без правки кода
- Нет форматирования с timestamp и контекстом

Файлы с наибольшим количеством `print(DEBUG)`:

| Файл | Примерное кол-во |
|------|-----------------|
| `magnit_api.py` | ~15 |
| `catalog_scanner.py` | ~20 |
| `routes/catalog.py` | ~15 |
| `routes/stores.py` | ~10 |

**Исправление** (пример для `magnit_api.py`):

```python
# В начале каждого модуля
import logging
logger = logging.getLogger(__name__)

# Заменить print на logger
logger.debug("POST %s, payload=%s", url, payload)
logger.warning("Ошибка парсинга товара: %s", e)
logger.error("Критическая ошибка: %s", e, exc_info=True)
```

Настройка в `main.py`:

```python
import logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)
```

---

### 13. Двойной `import os` в `main.py`

**Файл:** `src/server/main.py`, строки 8 и 16  
**Серьёзность:** Низкая  
**Тип:** Стиль кода

```python
import os    # строка 8
...
import os    # строка 16 — дублирование
```

Удалить второй `import os`.

---

### 14. `random` импортируется внутри метода `_rate_limit_wait`

**Файл:** `src/server/services/magnit_api.py`, строки 60 и 387  
**Серьёзность:** Низкая  
**Тип:** Стиль кода

```python
def _rate_limit_wait(self):
    ...
    import random          # ❌ импорт внутри функции
    time.sleep(random.uniform(0.1, 0.5))
```

Перенести `import random` на уровень модуля.

---

### 15. `_catalog_update_status` — глобальное изменяемое состояние без блокировки

**Файл:** `src/server/routes/catalog.py`, строки 723–731  
**Серьёзность:** Низкая  
**Тип:** Потокобезопасность

При одновременных запросах к `/categories/fetch-magnit-ids` возможна race condition.

```python
# ❌ Нет синхронизации
_catalog_update_status = {"in_progress": False, ...}

def _fetch_and_update_categories_background():
    _catalog_update_status["in_progress"] = True  # не атомарно
```

**Исправление:**

```python
import threading
_catalog_update_lock = threading.Lock()

def _fetch_and_update_categories_background():
    with _catalog_update_lock:
        _catalog_update_status["in_progress"] = True
    ...
    with _catalog_update_lock:
        _catalog_update_status["in_progress"] = False
```

---

### 16. Комментарий не совпадает со значением параметра

**Файл:** `src/server/services/catalog_scanner.py`, строки 600–603

```python
def cleanup_stale_products(self, days_threshold: int = 7) -> int:
    """
    Args:
        days_threshold: Количество дней без обновлений (по умолчанию 30)
        #                                                            ^^^
        # ❌ в docstring написано 30, но значение по умолчанию = 7
    """
```

**Исправление:** обновить docstring:

```python
    """
    Args:
        days_threshold: Количество дней без обновлений (по умолчанию 7)
    """
```

---

### 17. `CORS allow_origins=["*"]` без документирования

**Файл:** `src/server/main.py`, строки 254–259

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # любой origin
)
```

Для локального инструмента допустимо, но должно быть явно задокументировано. Рекомендуется ограничить хотя бы для продакшн-развёртывания:

```python
ALLOWED_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:8000").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)
```

---

### 18. `db.commit()` внутри цикла обновления подкатегорий

**Файл:** `src/server/services/catalog_updater.py`, строки 113–135  
**Файл:** `src/server/services/catalog_scanner.py`, строки 120–166

```python
# ❌ commit внутри цикла — снижает производительность
for magnit_id, child in current_ids.items():
    if magnit_id not in api_ids:
        db.delete(child)
        deleted += 1

db.commit()  # ок

for sub in subcats_from_api:
    if sub_id in current_ids:
        if child.name != sub_name:
            child.name = sub_name
            db.commit()  # ❌ commit на каждое изменение названия
```

**Исправление:** накопить изменения, один `commit` в конце:

```python
for sub in subcats_from_api:
    if sub_id in current_ids:
        if child.name != sub_name:
            child.name = sub_name
            updated += 1
    else:
        new_child = Category(...)
        db.add(new_child)
        added += 1

db.commit()  # ✅ один commit в конце
```

---

## 📊 Сводная таблица по файлам

| Файл | Найдено проблем | Приоритет |
|------|----------------|-----------|
| `routes/catalog.py` | 5 | 🔴 Критический |
| `services/catalog_scanner.py` | 3 | 🔴 Критический |
| `routes/prices.py` | 1 | 🔴 Критический |
| `models.py` | 1 | 🔴 Критический |
| `main.py` | 4 | 🟠 Важный |
| `routes/stores.py` | 2 | 🟠 Важный |
| `services/magnit_api.py` | 2 | 🟡 Замечание |
| `services/catalog_updater.py` | 1 | 🟡 Замечание |
| `scheduler.py` | 0 | ✅ Нет замечаний |

---

## 🚀 Приоритетный план исправлений

### Sprint 1 — Критические (1–2 дня)

| # | Задача | Файл | Эффект |
|---|--------|------|--------|
| 1 | Добавить составной индекс `(product_id, store_code)` | `models.py` | Ускорение bulk-операций |
| 2 | Исправить `prices.py` — новая сессия в фоновой задаче | `routes/prices.py` | Устранение краша |
| 3 | Исправить `cleanup_stale_products` — один DELETE | `catalog_scanner.py` | O(N) → O(1) памяти |
| 4 | Исправить `get_products_stats` — один запрос | `routes/catalog.py` | 5 запросов → 1 |

### Sprint 2 — Важные (2–3 дня)

| # | Задача | Файл | Эффект |
|---|--------|------|--------|
| 5 | Исправить `get_categories_tree` — один запрос вместо N+1 | `routes/catalog.py` | 200+ → 1 запрос |
| 6 | Исправить `_mark_all_running_failed_on_startup` — убрать фильтр | `routes/stores.py` | Корректность при перезапуске |
| 7 | Исправить тип `store_id: int → str` в `update_store` | `routes/stores.py` | Устранение 422 ошибки |
| 8 | Предзагрузка маппинга категорий в `scan_all_stores` | `routes/catalog.py` | N×M → 1 запрос |
| 9 | Вынести `STORE_TYPE_*` в `constants.py` | несколько файлов | Устранение дублирования |

### Sprint 3 — Рефакторинг (3–5 дней)

| # | Задача | Файл | Эффект |
|---|--------|------|--------|
| 10 | Заменить `print(DEBUG)` на `logging` | все файлы | Управление уровнями лога |
| 11 | Перенести миграции из `main.py` в `database.py` | `main.py`, `database.py` | Тестируемость, SRP |
| 12 | Убрать `import os` дубль | `main.py` | Чистота кода |
| 13 | Защитить `_catalog_update_status` через `threading.Lock` | `routes/catalog.py` | Потокобезопасность |
| 14 | Убрать `commit()` из цикла обновления подкатегорий | `catalog_updater.py`, `catalog_scanner.py` | Производительность |

---

## Производительность БД — итоговый чек-лист

```
Текущее состояние:
  ✅ bulk_insert_mappings / bulk_update_mappings в _save_products
  ✅ Один SELECT всех товаров перед сохранением (нет N+1 при записи)
  ✅ Индексы на store_code, price, category_id
  ✅ Rate limiting (0.5s) для защиты API

  ❌ N+1 в get_categories_tree (рекурсивные запросы)
  ❌ 4 COUNT запроса в get_products_stats вместо одного
  ❌ Нет составного индекса (product_id, store_code)
  ❌ cleanup_stale_products загружает всё в память
  ❌ scan_all_stores: 500 лишних SELECT по категориям
  ❌ db.commit() внутри циклов обновления подкатегорий
  ❌ Фоновая задача prices.py использует закрытую сессию
```
