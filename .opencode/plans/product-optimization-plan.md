# План оптимизации отображения и обновления товаров

**Дата:** 2026-04-18  
**Проект:** magnit_goods  
**Цель:** Оптимизировать сканирование, сохранение и отображение товаров

---

## Резюме требований

### Подтверждённые решения:
1. **Порядок сканирования:** Оставляем текущий (Магазин → Категория → Товары)
2. **Cleanup устаревших товаров:** Автоматически после каждого магазина (30+ дней)
3. **Прогресс-бар:** Детальный (магазин + категория + счётчики товаров)
4. **После сканирования:** Автоматическое перенаправление на /products (если успешно)
5. **Управление магазинами:** Уже реализовано, не требует изменений
6. **Страница products.html:** Независима от catalog.html, свой выбор магазинов

---

## Архитектура решения

### Текущий flow сканирования:
```
Пользователь → Кнопка "Сканировать товары" (catalog.html)
  ↓
POST /api/catalog/scan-all-stores?tracked_only=true
  ↓
FOR каждого отслеживаемого магазина (Store.is_active=True):
    FOR каждой отслеживаемой категории (Category.is_tracked=True):
        WHILE has_more товаров:
            ├─ API запрос Magnit (limit=32)
            ├─ Bulk save товаров (_save_products)
            └─ Обновить прогресс
    └─ Cleanup устаревших товаров (30+ дней)
  ↓
Перенаправление на /products (если status=completed)
```

---

## Изменения по файлам

### 1. `src/server/services/catalog_scanner.py`

#### 1.1. Оптимизация `_save_products()` (строки 374-571)

**Проблема:** N+1 запросов (для каждого товара отдельный SELECT), медленные COMMIT'ы

**Решение:**
- Один SELECT для всех product_ids (вместо N запросов)
- Bulk INSERT для новых товаров
- Bulk UPDATE для существующих товаров
- Bulk INSERT для истории цен
- Один COMMIT в конце

**Ожидаемый результат:** Ускорение в 5-10 раз для батчей 32+ товаров

**Псевдокод:**
```python
def _save_products(products, category_magnit_id):
    # 1. Получить категорию
    cat = db.query(Category).filter(magnit_id == category_magnit_id).first()
    
    # 2. Получить все существующие товары ОДНИМ запросом
    product_ids = [p["product_id"] for p in products]
    existing_products = db.query(Product).filter(
        Product.product_id.in_(product_ids),
        Product.store_code == self.store_code
    ).all()
    
    # 3. Разделить на INSERT и UPDATE
    to_insert = []
    to_update = []
    price_history_records = []
    
    for product_data in products:
        if product_id in existing_products:
            # Подготовить UPDATE
            to_update.append({...})
            if price_changed:
                price_history_records.append({...})
        else:
            # Подготовить INSERT
            to_insert.append({...})
            price_history_records.append({...})
    
    # 4. Bulk операции
    if to_insert:
        db.bulk_insert_mappings(Product, to_insert)
    if to_update:
        db.bulk_update_mappings(Product, to_update)
    if price_history_records:
        db.bulk_insert_mappings(PriceHistory, price_history_records)
    
    # 5. Сохранить снимки цен
    for product_data in products:
        self._save_price_snapshot(...)
    
    # 6. Один COMMIT
    db.commit()
    
    return added, updated, price_changes
```

---

#### 1.2. Добавить метод `cleanup_stale_products()` (после строки 619)

**Назначение:** Удалять товары, не обновлявшиеся 30+ дней

**Код:**
```python
def cleanup_stale_products(self, days_threshold: int = 30) -> int:
    """
    Удалить товары, которые не обновлялись N дней.
    
    Args:
        days_threshold: Количество дней без обновлений (по умолчанию 30)
        
    Returns:
        Количество удалённых товаров
    """
    from datetime import timedelta
    
    cutoff_date = datetime.utcnow() - timedelta(days=days_threshold)
    
    # Находим устаревшие товары для текущего магазина
    stale_products = self.db.query(Product).filter(
        Product.last_seen < cutoff_date,
        Product.store_code == self.store_code
    ).all()
    
    count = len(stale_products)
    
    if count > 0:
        print(f"DEBUG: Удаление {count} устаревших товаров для магазина {self.store_code}")
        
        for product in stale_products:
            self.db.delete(product)
        
        self.db.commit()
    
    return count
```

---

#### 1.3. Вызов cleanup в `scan_products()` (после строки 360)

**Место:** В конце метода `scan_products()`, перед `return result`

**Код:**
```python
# Удаляем устаревшие товары (30+ дней без обновлений)
deleted = self.cleanup_stale_products(days_threshold=30)
result["deleted"] = deleted

if self.job_id:
    self._update_job_progress(98, f"Удалено устаревших товаров: {deleted}")

return result
```

---

### 2. `src/server/routes/catalog.py`

#### 2.1. Добавить endpoint `/api/products/stats` (после строки 695)

**Назначение:** Возвращать статистику по товарам для отображения на странице

**Возвращаемые данные:**
```json
{
    "total": 1234,
    "in_stock": 1100,
    "out_of_stock": 134,
    "with_discount": 456,
    "with_promotion": 234,
    "categories_count": 45,
    "last_update": "2026-04-18T10:30:00",
    "avg_price": 123.45,
    "price_changes_today": 23
}
```

**Параметры:**
- `store_code` (optional) — фильтр по магазину

**Код:**
```python
@router.get("/products/stats")
def get_products_stats(
    store_code: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    from sqlalchemy import func
    from datetime import date
    
    query = db.query(Product)
    if store_code:
        query = query.filter(Product.store_code == store_code)
    
    total = query.count()
    in_stock = query.filter(Product.in_stock == True).count()
    out_of_stock = total - in_stock
    with_discount = query.filter(Product.old_price.isnot(None)).count()
    with_promotion = query.filter(Product.is_promotion == True).count()
    
    # Последнее обновление
    last_product = query.order_by(Product.last_seen.desc()).first()
    last_update = last_product.last_seen.isoformat() if last_product else None
    
    # Средняя цена
    avg_price = db.query(func.avg(Product.price)).filter(
        Product.store_code == store_code if store_code else True
    ).scalar()
    
    # Изменения цен за сегодня
    today = date.today()
    price_changes_query = db.query(PriceHistory).filter(
        func.date(PriceHistory.recorded_at) == today
    )
    if store_code:
        price_changes_query = price_changes_query.filter(
            PriceHistory.store_code == store_code
        )
    price_changes_today = price_changes_query.count()
    
    # Количество категорий с товарами
    categories_query = db.query(Product.category_id).filter(
        Product.category_id.isnot(None)
    )
    if store_code:
        categories_query = categories_query.filter(Product.store_code == store_code)
    categories_count = categories_query.distinct().count()
    
    return {
        "total": total,
        "in_stock": in_stock,
        "out_of_stock": out_of_stock,
        "with_discount": with_discount,
        "with_promotion": with_promotion,
        "categories_count": categories_count,
        "last_update": last_update,
        "avg_price": round(avg_price, 2) if avg_price else 0,
        "price_changes_today": price_changes_today
    }
```

---

### 3. `src/server/templates/catalog.html`

#### 3.1. Улучшить детальный прогресс (строки 704-705)

**Текущий код:**
```javascript
progressBar.style.width = `${job.progress}%`;
progressPercent.textContent = `${job.progress}%`;
progressText.textContent = job.progress_message || 'Обработка...';
```

**Новый код:**
```javascript
progressBar.style.width = `${job.progress}%`;
progressBar.textContent = `${job.progress}%`; // Показываем % внутри бара
progressPercent.textContent = `${job.progress}%`;

// Детальный прогресс с иконками
let detailedProgress = job.progress_message || 'Обработка...';
if (job.items_scanned > 0) {
    detailedProgress += ` | 📦 ${job.items_scanned} товаров`;
}
if (job.items_added > 0) {
    detailedProgress += ` | ➕ ${job.items_added} новых`;
}
if (job.items_updated > 0) {
    detailedProgress += ` | 🔄 ${job.items_updated} обновлено`;
}

progressText.textContent = detailedProgress;
```

---

#### 3.2. Автоматическое перенаправление на /products (после строки 720)

**Место:** После отображения итогов сканирования

**Код:**
```javascript
if (job.status === 'completed') {
    clearInterval(pollingInterval);

    // Показываем результаты
    let summary = `
        ✓ Сканирование завершено!<br>
        Магазинов: ${stores.length}<br>
        Категорий: ${trackedCategories.length}<br>
        Товаров просканировано: ${job.items_scanned || 0}<br>
        Товаров добавлено: ${job.items_added || 0}<br>
        Товаров обновлено: ${job.items_updated || 0}
    `;

    scanStatus.innerHTML = `<div class="badge badge-success">${summary}</div>`;

    // Автоматическое перенаправление через 3 секунды
    setTimeout(() => {
        window.location.href = '/products';
    }, 3000);
}
```

---

### 4. `src/server/templates/products.html`

#### 4.1. Добавить панель статистики (после строки 35)

**HTML:**
```html
<!-- Панель статистики -->
<div class="card">
    <h3>📊 Статистика товаров</h3>
    <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-top: 12px;">
        <div class="stat-card">
            <div class="stat-value" id="statTotal">-</div>
            <div class="stat-label">Всего товаров</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" id="statInStock">-</div>
            <div class="stat-label">В наличии</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" id="statDiscount">-</div>
            <div class="stat-label">Со скидкой</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" id="statPromo">-</div>
            <div class="stat-label">Акции</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" id="statAvgPrice">-</div>
            <div class="stat-label">Средняя цена</div>
        </div>
        <div class="stat-card">
            <div class="stat-value" id="statLastUpdate">-</div>
            <div class="stat-label">Обновлено</div>
        </div>
    </div>
</div>

<style>
.stat-card {
    background: #f8f9fa;
    padding: 16px;
    border-radius: 8px;
    border: 1px solid #e0e0e0;
    text-align: center;
    transition: transform 0.2s, box-shadow 0.2s;
}
.stat-card:hover {
    transform: translateY(-2px);
    box-shadow: 0 4px 8px rgba(0,0,0,0.1);
}
.stat-value {
    font-size: 24px;
    font-weight: bold;
    color: #2196f3;
    margin-bottom: 4px;
}
.stat-label {
    font-size: 12px;
    color: #666;
    text-transform: uppercase;
}
</style>
```

---

#### 4.2. Добавить дополнительные фильтры (после строки 63)

**HTML:**
```html
<div class="form-group">
    <label>Наличие</label>
    <select id="stockFilter">
        <option value="">Все</option>
        <option value="in_stock">В наличии</option>
        <option value="out_of_stock">Нет в наличии</option>
        <option value="low_stock">Мало осталось</option>
    </select>
</div>

<div class="form-group">
    <label>Акции</label>
    <select id="promoFilter">
        <option value="">Все</option>
        <option value="discount">Со скидкой</option>
        <option value="promotion">Акции</option>
    </select>
</div>

<div class="form-group">
    <label>Цена от</label>
    <input type="number" id="minPrice" placeholder="0" min="0">
</div>

<div class="form-group">
    <label>Цена до</label>
    <input type="number" id="maxPrice" placeholder="1000" min="0">
</div>
```

---

#### 4.3. Добавить JavaScript функции (в конец <script>)

**Функция загрузки статистики:**
```javascript
async function loadProductStats() {
    const storeCode = document.getElementById('storeCode').value;
    if (!storeCode) {
        const selectedStores = getSelectedStores();
        if (selectedStores.length === 0) return;
        storeCode = selectedStores[0];
    }
    
    try {
        const response = await fetch(`/api/products/stats?store_code=${encodeURIComponent(storeCode)}`);
        const stats = await response.json();
        
        document.getElementById('statTotal').textContent = stats.total;
        document.getElementById('statInStock').textContent = stats.in_stock;
        document.getElementById('statDiscount').textContent = stats.with_discount;
        document.getElementById('statPromo').textContent = stats.with_promotion;
        document.getElementById('statAvgPrice').textContent = stats.avg_price + ' ₽';
        
        if (stats.last_update) {
            const date = new Date(stats.last_update);
            const formatted = date.toLocaleString('ru-RU', {
                day: '2-digit',
                month: '2-digit',
                hour: '2-digit',
                minute: '2-digit'
            });
            document.getElementById('statLastUpdate').textContent = formatted;
        } else {
            document.getElementById('statLastUpdate').textContent = 'Нет данных';
        }
    } catch (e) {
        console.error('Ошибка загрузки статистики:', e);
    }
}
```

**Улучшенная функция loadProducts с фильтрами:**
```javascript
async function loadProducts() {
    // Получаем значения фильтров
    const stockFilter = document.getElementById('stockFilter')?.value || '';
    const promoFilter = document.getElementById('promoFilter')?.value || '';
    const minPrice = document.getElementById('minPrice')?.value || '';
    const maxPrice = document.getElementById('maxPrice')?.value || '';
    
    // ... существующий код загрузки ...
    
    // Клиентская фильтрация
    if (stockFilter === 'in_stock') {
        products = products.filter(p => p.in_stock);
    } else if (stockFilter === 'out_of_stock') {
        products = products.filter(p => !p.in_stock);
    } else if (stockFilter === 'low_stock') {
        products = products.filter(p => p.is_low_stock);
    }

    if (promoFilter === 'discount') {
        products = products.filter(p => p.old_price && p.old_price > p.price);
    } else if (promoFilter === 'promotion') {
        products = products.filter(p => p.is_promotion);
    }
    
    // ... остальной код рендеринга ...
    
    // Обновляем статистику после загрузки
    loadProductStats();
}
```

**Обработчики событий:**
```javascript
document.addEventListener('DOMContentLoaded', () => {
    loadStoresForComparison();
    
    // Загружаем статистику при загрузке
    setTimeout(loadProductStats, 1000);
    
    // Обновляем статистику каждые 30 секунд
    setInterval(loadProductStats, 30000);
    
    // Обработчики для фильтров
    document.getElementById('stockFilter')?.addEventListener('change', loadProducts);
    document.getElementById('promoFilter')?.addEventListener('change', loadProducts);
    
    // Debounce для фильтров цены
    const debouncedLoad = debounce(loadProducts, 500);
    document.getElementById('minPrice')?.addEventListener('input', debouncedLoad);
    document.getElementById('maxPrice')?.addEventListener('input', debouncedLoad);
});

// Debounce helper
function debounce(func, wait) {
    let timeout;
    return function executedFunction(...args) {
        const later = () => {
            clearTimeout(timeout);
            func(...args);
        };
        clearTimeout(timeout);
        timeout = setTimeout(later, wait);
    };
}
```

---

### 5. `AGENTS.md`

#### 5.1. Добавить секцию "Обновление товаров в БД" (после строки 124)

```markdown
## Обновление товаров в БД

### Оптимизация производительности
- `_save_products()` использует bulk операции:
  - `bulk_insert_mappings()` для новых товаров
  - `bulk_update_mappings()` для существующих товаров
  - `bulk_insert_mappings()` для истории цен
- Один SELECT для всех товаров вместо N+1 запросов
- Один COMMIT в конце вместо множественных
- **Производительность:** ~5-10x быстрее для батчей 50+ товаров

### Автоматическая очистка
- `cleanup_stale_products(days=30)` удаляет товары без обновлений 30+ дней
- Вызывается автоматически после сканирования каждого магазина
- Предотвращает накопление устаревших данных

### Статистика товаров
- **Endpoint:** `GET /api/products/stats?store_code=X`
- **Возвращает:** total, in_stock, with_discount, avg_price, last_update, price_changes_today
- Обновляется автоматически каждые 30 секунд на странице /products

### UI Features
- Автоматическое перенаправление на /products после успешного сканирования
- Детальный прогресс-бар с иконками (📦 товаров | ➕ новых | 🔄 обновлено)
- Фильтры: наличие, акции, диапазон цен
- Панель статистики с ключевыми метриками
- Независимый выбор магазинов для сравнения на /products
```

---

## Ожидаемые результаты

### Производительность
- ✅ Ускорение сохранения товаров в 5-10 раз
- ✅ Снижение нагрузки на БД (меньше запросов)
- ✅ Автоматическая очистка устаревших данных

### UX улучшения
- ✅ Детальный прогресс с иконками и счётчиками
- ✅ Автоматическое перенаправление на /products
- ✅ Панель статистики в реальном времени
- ✅ Дополнительные фильтры (наличие, акции, цена)
- ✅ Независимое управление магазинами на разных страницах

### Надёжность
- ✅ Bulk операции уменьшают риск частичных сохранений
- ✅ Cleanup предотвращает накопление мусора
- ✅ Детальный прогресс помогает отслеживать проблемы

---

## Порядок реализации

1. **Оптимизация БД** (catalog_scanner.py)
   - Переписать `_save_products()` с bulk операциями
   - Добавить `cleanup_stale_products()`
   - Вызвать cleanup в `scan_products()`

2. **API endpoints** (routes/catalog.py)
   - Добавить `GET /api/products/stats`

3. **UI улучшения catalog.html**
   - Детальный прогресс-бар
   - Автоматическое перенаправление

4. **UI улучшения products.html**
   - Панель статистики
   - Дополнительные фильтры
   - JavaScript функции

5. **Документация** (AGENTS.md)
   - Обновить секцию про обновление товаров

---

## Тестирование

### Сценарии для проверки:

1. **Сканирование товаров:**
   - Выбрать 2-3 магазина как отслеживаемые
   - Выбрать 2-3 категории как отслеживаемые
   - Нажать "Сканировать товары"
   - Проверить детальный прогресс
   - Убедиться в перенаправлении на /products

2. **Bulk операции:**
   - Засечь время сканирования 100+ товаров
   - Сравнить с текущей реализацией
   - Ожидаемое ускорение: 5-10x

3. **Cleanup устаревших товаров:**
   - Создать тестовые товары с last_seen = 40 дней назад
   - Запустить сканирование
   - Проверить, что старые товары удалены

4. **Статистика:**
   - Открыть /products
   - Проверить загрузку статистики
   - Проверить автообновление каждые 30 сек

5. **Фильтры:**
   - Проверить фильтр "В наличии"
   - Проверить фильтр "Со скидкой"
   - Проверить фильтр по цене (от/до)

---

## Риски и ограничения

### Риски:
1. **Bulk операции могут не работать с некоторыми версиями SQLAlchemy**
   - Решение: Проверить версию, использовать fallback на обычные операции

2. **Cleanup может удалить товары, которые временно отсутствуют**
   - Решение: 30 дней — достаточный порог, но можно увеличить до 60

3. **Автоматическое перенаправление может раздражать пользователя**
   - Решение: Добавить кнопку "Остаться на странице" или увеличить задержку

### Ограничения:
1. **Объём данных:** Оптимизация рассчитана на до 1000 товаров (как указано)
2. **Параллелизация:** Не реализована (оставляем последовательное сканирование)
3. **Клиентская фильтрация:** Фильтры по наличию/акциям работают на клиенте (не в SQL)

---

## Следующие шаги

После утверждения плана:
1. Создать ветку `feature/product-optimization`
2. Реализовать изменения по порядку (1-5)
3. Протестировать каждый этап
4. Создать PR с описанием изменений
5. После мерджа обновить документацию

---

**Статус:** Готов к утверждению  
**Автор:** OpenCode AI  
**Дата создания:** 2026-04-18
