# План упрощения отслеживания цен

## Цель
Упростить систему отслеживания цен товаров:
- Удалить акционные цены из API (не интересуют)
- Хранить только текущую цену и предыдущую цену
- Использовать только таблицу `Product` (без `PriceHistory` и `DailyPriceSnapshot`)
- Процент изменения со знаком: `+15%` = снижение, `-11.8%` = повышение

## Уточнения от пользователя
1. ✅ План подтверждён
2. Фильтр "Со скидкой" — это НЕ фильтр "Экономия" (min_savings)
3. ✅ Статистика: показывать `with_price_decrease`
4. ✅ Стрелки: `↓15%` (зелёный) / `↑11.8%` (фиолетовый)
5. ✅ Страница `/deals` — удалить

---

## Шаг 1: Модели данных (`models.py`)

### 1.1. Класс `Product` — удалить поля акций

**Удалить**:
```python
old_price = Column(Float, nullable=True)
discount_percent = Column(Integer, nullable=True)
is_promotion = Column(Boolean, default=False)
promo_end_date = Column(DateTime, nullable=True)
historical_discount_percent = Column(Float, nullable=True, index=True)
historical_old_price = Column(Float, nullable=True)
historical_price_date = Column(DateTime, nullable=True)
is_price_increase = Column(Boolean, default=False)
```

### 1.2. Класс `Product` — добавить поля отслеживания цен

**Добавить**:
```python
# Предыдущая цена (из предыдущего сканирования)
previous_price = Column(Float, nullable=True)

# Процент изменения (+ снижение, - повышение)
price_change_percent = Column(Float, nullable=True, index=True)
```

**Оставить без изменений**:
```python
last_price_change = Column(DateTime, nullable=True)  # уже есть
```

### 1.3. Удалить классы

**Удалить полностью**:
```python
class PriceHistory(Base):  # строки 146-158
    ...

class DailyPriceSnapshot(Base):  # строки 160-172
    ...
```

---

## Шаг 2: API клиент (`magnit_api.py`)

### 2.1. Метод `_parse_product()` (строки 222-314)

**Удалить блок парсинга акций** (строки 238-247):
```python
# УДАЛИТЬ:
promotion = item.get("promotion") or {}
old_price_raw = promotion.get("oldPrice") or item.get("oldPrice")
is_promotion = promotion.get("isPromotion", False)
discount_percent = promotion.get("discountPercent")
promo_end_date = promotion.get("endDate")

if old_price_raw:
    old_price_raw = old_price_raw / 100
```

**Удалить из return** (строки 281, 291-293):
```python
# УДАЛИТЬ:
"old_price": float(old_price_raw) if old_price_raw else None,
"is_promotion": is_promotion,
"discount_percent": discount_percent,
"promo_end_date": promo_end_date,
```

---

## Шаг 3: Сканер каталога (`catalog_scanner.py`)

### 3.1. Удалить импорты (строки 12-18)

**Удалить**:
```python
from src.server.models import (
    # ...
    PriceHistory,  # ← УДАЛИТЬ
    DailyPriceSnapshot,  # ← УДАЛИТЬ
)
```

### 3.2. Метод `_save_products()` — удалить расчёт исторических данных (строки 489-500)

**Удалить весь блок**:
```python
# УДАЛИТЬ:
from src.server.services.price_calculator import get_bulk_historical_prices
historical_data = get_bulk_historical_prices(products_for_hist, self.db, days_back=14)
```

### 3.3. Метод `_save_products()` — новая логика UPDATE (строки 519-591)

**Заменить на**:
```python
if existing:
    # UPDATE: проверяем изменение цены
    old_price_val = existing.price
    new_price_val = current_price
    
    # Обновляем поля
    update_data = {
        "id": existing.id,
        "name": product_data.get("name", existing.name),
        "price": new_price_val,
        "category_id": db_category_id,
        "sku": product_data.get("sku", existing.sku),
        "unit": product_data.get("unit", existing.unit),
        "image_url": product_data.get("image_url", existing.image_url),
        "in_stock": product_data.get("in_stock", existing.in_stock),
        "last_seen": now,
        "last_scan_found": now,
        "quantity": product_data.get("quantity", existing.quantity),
        "is_low_stock": product_data.get("is_low_stock", existing.is_low_stock),
        "pickup_only": product_data.get("pickup_only", existing.pickup_only),
        "rating": product_data.get("rating", existing.rating),
        "scores_count": product_data.get("scores_count", existing.scores_count),
        "comments_count": product_data.get("comments_count", existing.comments_count),
        "seo_code": product_data.get("seo_code", existing.seo_code),
        "service": product_data.get("service", existing.service),
        "catalog_type": product_data.get("catalog_type", existing.catalog_type),
        "min_order_qty": product_data.get("min_order_qty", existing.min_order_qty),
        "order_step_qty": product_data.get("order_step_qty", existing.order_step_qty),
        "is_weighted": product_data.get("is_weighted", existing.is_weighted),
        "unit_price": product_data.get("unit_price", existing.unit_price),
    }
    
    # Проверяем изменение цены
    if abs(old_price_val - new_price_val) > 0.01:
        # Цена изменилась!
        change_percent = round((old_price_val - new_price_val) / old_price_val * 100, 1)
        update_data["previous_price"] = old_price_val
        update_data["price_change_percent"] = change_percent
        update_data["last_price_change"] = now
    
    to_update.append(update_data)
```

**Удалить**:
- Все упоминания `current_old_price`
- Все упоминания `promo_end_date`
- Блок записи в `price_history_records` (строки 538-547)
- Блок обновления `historical_*` полей (строки 584-589)

### 3.4. Метод `_save_products()` — новая логика INSERT (строки 592-653)

**Заменить на**:
```python
else:
    # INSERT: новый товар
    to_insert.append({
        "product_id": product_id,
        "name": product_data.get("name", "Без названия"),
        "sku": product_data.get("sku"),
        "category_id": db_category_id,
        "store_code": self.store_code,
        "price": current_price,
        "currency": "₽",
        "unit": product_data.get("unit", "шт"),
        "image_url": product_data.get("image_url"),
        "in_stock": product_data.get("in_stock", True),
        # Остатки
        "quantity": product_data.get("quantity", 0),
        "is_low_stock": product_data.get("is_low_stock"),
        "pickup_only": product_data.get("pickup_only", False),
        # Рейтинги
        "rating": product_data.get("rating"),
        "scores_count": product_data.get("scores_count", 0),
        "comments_count": product_data.get("comments_count", 0),
        # SEO
        "seo_code": product_data.get("seo_code"),
        "service": product_data.get("service"),
        "catalog_type": product_data.get("catalog_type"),
        # Параметры заказа
        "min_order_qty": product_data.get("min_order_qty", 1),
        "order_step_qty": product_data.get("order_step_qty", 1),
        # Весовые
        "is_weighted": product_data.get("is_weighted", False),
        "unit_price": product_data.get("unit_price"),
        # Временные метки
        "first_seen": now,
        "last_seen": now,
        "last_scan_found": now,
        # Отслеживание цен
        "previous_price": None,
        "price_change_percent": None,
        "last_price_change": None,
    })
```

**Удалить**:
- Все упоминания `old_price`, `is_promotion`, `discount_percent`, `promo_end_date`
- Все упоминания `historical_*` полей
- Блок записи в `price_history_records` (строки 644-653)

### 3.5. Удалить блоки работы с историей (строки 655-687)

**Удалить**:
```python
# УДАЛИТЬ строки 669-687:
# 5. Bulk INSERT для истории цен
price_changes = 0
if price_history_records:
    self.db.bulk_insert_mappings(PriceHistory, price_history_records)
    ...

# 6. Сохраняем снимки цен
for product_data in products:
    self._save_price_snapshot(...)
```

**Изменить return** (строка 687):
```python
# Было:
return added, updated, price_changes

# Станет:
return added, updated, 0  # price_changes больше не используется
```

### 3.6. Удалить метод `_save_price_snapshot()` (строки 689-734)

**Удалить полностью**.

---

## Шаг 4: Миграция БД (`database.py`)

### 4.1. Добавить новую миграцию

**Добавить функцию** (после существующих миграций):
```python
def migrate_simplify_price_tracking():
    """
    Упрощение отслеживания цен:
    1. Удалить поля акций из products
    2. Добавить поля previous_price, price_change_percent
    3. Удалить таблицы price_history, daily_price_snapshot
    """
    db = SessionLocal()
    try:
        print("Миграция: упрощение отслеживания цен...")
        
        # Добавить новые поля в products
        try:
            db.execute(text("ALTER TABLE products ADD COLUMN previous_price FLOAT"))
            print("  ✓ Добавлено поле previous_price")
        except Exception as e:
            print(f"  - Поле previous_price уже существует")
        
        try:
            db.execute(text("ALTER TABLE products ADD COLUMN price_change_percent FLOAT"))
            print("  ✓ Добавлено поле price_change_percent")
        except Exception as e:
            print(f"  - Поле price_change_percent уже существует")
        
        # Удалить старые поля из products
        columns_to_drop = [
            "old_price",
            "discount_percent",
            "is_promotion",
            "promo_end_date",
            "historical_discount_percent",
            "historical_old_price",
            "historical_price_date",
            "is_price_increase",
        ]
        
        for col in columns_to_drop:
            try:
                db.execute(text(f"ALTER TABLE products DROP COLUMN {col}"))
                print(f"  ✓ Удалено поле {col}")
            except Exception as e:
                print(f"  - Поле {col} уже удалено или не существует")
        
        # Удалить таблицы
        try:
            db.execute(text("DROP TABLE IF EXISTS price_history"))
            print("  ✓ Таблица price_history удалена")
        except Exception as e:
            print(f"  ! Ошибка удаления price_history: {e}")
        
        try:
            db.execute(text("DROP TABLE IF EXISTS daily_price_snapshot"))
            print("  ✓ Таблица daily_price_snapshot удалена")
        except Exception as e:
            print(f"  ! Ошибка удаления daily_price_snapshot: {e}")
        
        db.commit()
        print("✓ Миграция завершена успешно")
    except Exception as e:
        db.rollback()
        print(f"ERROR migrate_simplify_price_tracking: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()
```

### 4.2. Вызвать миграцию в `init_db()`

**Найти функцию `init_db()`** и добавить вызов:
```python
def init_db():
    # ... существующие миграции ...
    migrate_simplify_price_tracking()
```

---

## Шаг 5: API endpoints — Каталог (`routes/catalog.py`)

### 5.1. Endpoint `GET /api/products` (строки 260-390)

**Удалить параметр `min_savings`** (строка 265):
```python
# УДАЛИТЬ:
min_savings: Optional[float] = Query(None),
```

**Удалить фильтр по min_savings** (строки 286-290):
```python
# УДАЛИТЬ:
if min_savings is not None:
    query = query.filter(
        Product.historical_discount_percent >= min_savings,
        Product.is_price_increase == False
    )
```

**Закомментировать сортировку "discount"** (строки 335-338):
```python
# ЗАКОММЕНТИРОВАТЬ:
# elif sort_by == "discount":
#     query = query.filter(Product.old_price.isnot(None)).order_by(
#         Product.price.asc(), Product.name.asc()
#     )
```

**Изменить формирование ответа** (строки 346-390):

**Удалить**:
```python
# УДАЛИТЬ строки 348-350:
discount = p.historical_discount_percent
old_price = p.historical_old_price
```

**Изменить result.append** (строки 352-390):
```python
result.append({
    "product_id": p.product_id,
    "name": p.name,
    "price": p.price,
    "previous_price": p.previous_price,  # ← ИЗМЕНЕНО
    "price_change_percent": p.price_change_percent,  # ← ИЗМЕНЕНО
    "last_price_change": p.last_price_change.isoformat() if p.last_price_change else None,  # ← ДОБАВЛЕНО
    "currency": p.currency,
    "unit": p.unit,
    "image_url": p.image_url,
    "in_stock": p.in_stock,
    "category_id": p.category_id,
    "store_code": p.store_code,
    "category_name": p.category.name if p.category else None,
    "category_parent_id": p.category.parent_id if p.category else None,
    "quantity": p.quantity,
    "is_low_stock": p.is_low_stock,
    "pickup_only": p.pickup_only,
    "rating": p.rating,
    "scores_count": p.scores_count,
    "comments_count": p.comments_count,
    "seo_code": p.seo_code,
    "service": p.service,
    "catalog_type": p.catalog_type,
    "min_order_qty": p.min_order_qty,
    "order_step_qty": p.order_step_qty,
    "is_weighted": p.is_weighted,
    "unit_price": p.unit_price,
    "first_seen": p.first_seen.isoformat() if p.first_seen else None,
    "last_seen": p.last_seen.isoformat() if p.last_seen else None,
})
```

**Удалить из ответа**:
- `old_price`
- `discount_percent`
- `historical_old_price`
- `historical_price_date`
- `is_price_increase`
- `is_promotion`
- `promo_discount`

### 5.2. Endpoint `GET /api/products/stats` (строки 395-416)

**Изменить расчёт статистики** (строки 405-406):

**Было**:
```python
with_discount = query.filter(Product.old_price.isnot(None)).count()
with_promotion = query.filter(Product.is_promotion == True).count()
```

**Станет**:
```python
with_price_decrease = query.filter(Product.price_change_percent > 0).count()
with_price_increase = query.filter(Product.price_change_percent < 0).count()
```

**Изменить return** (строки 410-416):

**Было**:
```python
return {
    "total": total,
    "in_stock": in_stock,
    "with_discount": with_discount,
    "with_promotion": with_promotion,
    "last_update": ...,
}
```

**Станет**:
```python
return {
    "total": total,
    "in_stock": in_stock,
    "with_price_decrease": with_price_decrease,
    "with_price_increase": with_price_increase,
    "last_update": last_update.last_seen.isoformat() if last_update and last_update.last_seen else None,
}
```

### 5.3. Endpoint `GET /api/products/{product_id}` (строки 440-490)

**Удалить расчёт скидки** (строки 476-478):
```python
# УДАЛИТЬ:
if product.old_price and product.old_price > 0:
    discount = round(...)
```

**Изменить return** (строки 480-490):

**Удалить из ответа**:
```python
# УДАЛИТЬ:
"old_price": product.old_price,
"discount_percent": discount,
"is_promotion": product.is_promotion,
```

**Добавить в ответ**:
```python
# ДОБАВИТЬ:
"previous_price": product.previous_price,
"price_change_percent": product.price_change_percent,
"last_price_change": product.last_price_change.isoformat() if product.last_price_change else None,
```

---

## Шаг 6: API endpoints — Цены (`routes/prices.py`)

### 6.1. Удалить endpoints

**Удалить полностью**:
```python
# УДАЛИТЬ строки 195-245:
@router.get("/prices/history/{product_id}")
def get_price_history(...):
    ...

# УДАЛИТЬ строки 248-299:
@router.post("/historical-bulk")
def get_historical_prices_bulk(...):
    ...
```

### 6.2. Переписать endpoint `GET /api/prices/decreased`

**Было** (использует `PriceHistory`):
```python
@router.get("/prices/decreased")
def get_decreased_prices(...):
    # Использует PriceHistory
    ...
```

**Станет** (использует `Product.price_change_percent`):
```python
@router.get("/prices/decreased")
def get_decreased_prices(
    store_code: Optional[str] = Query(None),
    min_discount_percent: float = Query(10.0),
    limit: int = Query(50),
    db: Session = Depends(get_db),
):
    """
    Получить товары с понижением цены.
    Использует price_change_percent из Product.
    """
    code = store_code
    if not code:
        raise HTTPException(status_code=400, detail="Необходимо указать store_code")
    
    products = (
        db.query(Product)
        .filter(
            Product.store_code == code,
            Product.price_change_percent >= min_discount_percent,
            Product.last_price_change.isnot(None),
        )
        .order_by(Product.price_change_percent.desc())
        .limit(limit)
        .all()
    )
    
    return [
        {
            "product_id": p.product_id,
            "name": p.name,
            "price": p.price,
            "previous_price": p.previous_price,
            "change_percent": p.price_change_percent,
            "last_price_change": p.last_price_change.isoformat(),
            "image_url": p.image_url,
        }
        for p in products
    ]
```

### 6.3. Удалить endpoint `GET /api/prices/alerts`

**Удалить полностью** (использует `price_tracker.py`).

---

## Шаг 7: Удалить модули

### 7.1. Удалить файлы:
```
src/server/services/price_calculator.py
src/server/services/price_tracker.py
```

---

## Шаг 8: UI — Страница товаров (`templates/products.html`)

### 8.1. Закомментировать сортировку "По скидке" (строка 306)

**Было**:
```html
<option value="discount">По скидке</option>
```

**Станет**:
```html
<!-- <option value="discount">По скидке</option> -->
```

### 8.2. Закомментировать фильтр "Со скидкой" (строка 322)

**Было**:
```html
<option value="discount">Со скидкой</option>
```

**Станет**:
```html
<!-- <option value="discount">Со скидкой</option> -->
```

### 8.3. Обновить отображение цены (строки 1108-1133)

**Было**:
```javascript
const oldPrice = p.historical_old_price || null;
const discount = p.discount_percent !== null ? p.discount_percent : 0;

const priceText = discount !== 0 
    ? (discount > 0 
        ? `${p.price} ₽ <span style="color:#9c27b0;">(+${discount}%)</span>`
        : `${p.price} ₽ <span style="color:#28a745;">(-${Math.abs(discount)}%)</span>`)
    : `${p.price} ₽`;
```

**Станет**:
```javascript
const changePercent = p.price_change_percent !== null && p.price_change_percent !== undefined ? p.price_change_percent : 0;
const previousPrice = p.previous_price || null;

const priceText = changePercent !== 0 
    ? (changePercent > 0 
        ? `${p.price} ₽ <span style="color:#28a745;">(↓${changePercent}%)</span>`  // снижение - зелёный
        : `${p.price} ₽ <span style="color:#9c27b0;">(↑${Math.abs(changePercent)}%)</span>`)  // повышение - фиолетовый
    : `${p.price} ₽`;
```

### 8.4. Закомментировать фильтр по акциям (строки 1797-1799)

**Было**:
```javascript
if (promoFilter === 'discount') {
    return p.discount_percent !== null && !p.is_price_increase && p.discount_percent > 0;
}
```

**Станет**:
```javascript
// if (promoFilter === 'discount') {
//     return p.price_change_percent > 0;
// }
```

### 8.5. Обновить статистику (строка 1639)

**Было**:
```javascript
statDiscount.textContent = stats.with_discount;
```

**Станет**:
```javascript
statDiscount.textContent = stats.with_price_decrease || 0;
```

---

## Шаг 9: UI — Удалить страницу "Акции" (`templates/deals.html`)

### 9.1. Удалить файл:
```
src/server/templates/deals.html
```

### 9.2. Удалить роут в `main.py`

**Найти и удалить**:
```python
@app.get("/deals", response_class=HTMLResponse)
async def deals_page(request: Request):
    return templates.TemplateResponse("deals.html", {"request": request})
```

### 9.3. Удалить ссылку из навигации (`templates/base.html`)

**Найти и удалить**:
```html
<a href="/deals">Акции</a>
```

---

## Итоговая структура данных

### Таблица `Product`:
```
Поля для отслеживания цен:
- price (Float) — текущая цена
- previous_price (Float) — предыдущая цена
- price_change_percent (Float) — процент изменения (+ снижение, - повышение)
- last_price_change (DateTime) — дата последнего изменения

Удалённые поля:
- old_price, discount_percent, is_promotion, promo_end_date
- historical_discount_percent, historical_old_price, historical_price_date, is_price_increase
```

### Удалённые таблицы:
- `PriceHistory`
- `DailyPriceSnapshot`

### Удалённые модули:
- `src/server/services/price_calculator.py`
- `src/server/services/price_tracker.py`

### Удалённые страницы:
- `/deals` (templates/deals.html)

---

## Проверка и тестирование

### После реализации проверить:

1. **Миграция БД**:
   - Запустить сервер
   - Проверить логи миграции
   - Проверить структуру таблицы `products` (должны быть `previous_price`, `price_change_percent`)
   - Проверить что таблицы `price_history` и `daily_price_snapshot` удалены

2. **Сканирование товаров**:
   - Запустить сканирование через `/api/products/scan`
   - Проверить что товары сохраняются без ошибок
   - Проверить что `previous_price` и `price_change_percent` = NULL для новых товаров

3. **Изменение цены**:
   - Вручную изменить цену товара в БД
   - Запустить повторное сканирование
   - Проверить что `previous_price` и `price_change_percent` обновились

4. **API endpoints**:
   - `GET /api/products` — проверить что возвращает `previous_price`, `price_change_percent`
   - `GET /api/products/stats` — проверить что возвращает `with_price_decrease`, `with_price_increase`
   - `GET /api/products/{id}` — проверить детали товара
   - `GET /api/prices/decreased` — проверить список товаров с понижением цены

5. **UI**:
   - Открыть `/products`
   - Проверить отображение цен со стрелками (↓15% зелёный, ↑11.8% фиолетовый)
   - Проверить статистику (должна показывать `with_price_decrease`)
   - Проверить что фильтр "Со скидкой" закомментирован
   - Проверить что страница `/deals` удалена (404)
