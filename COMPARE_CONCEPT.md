# Новая концепция сравнения товаров по магазинам

## Требования

### 1. Выбор нескольких магазинов для сравнения
- Чекбокс-список сохранённых магазинов (из `stores.json` или через API `/api/stores`)
- Можно выбрать 2-5 магазинов для сравнения одновременно
- Выбранные магазины сохраняются в localStorage/sessionStorage
- Индикатор количества выбранных магазинов в навигации

### 2. Группировка товаров по категориям
- Акордеон: категории сворачиваются/разворачиваются по клику
- Внутри каждой категории — список товаров
- Счётчик товаров в каждой категории
- Возможность свернуть/развернуть все категории одной кнопкой

### 3. Таблица сравнения товаров
- Заголовок таблицы: **Категория | Товар | Магазин 1 | Магазин 2 | Магазин 3 | ...**
- Для каждого магазина отображается:
  - Цена
  - Наличие (в наличии/нет)
  - Скидка (если есть)
- Подсветка лучшей цены (самая низкая цена выделяется зелёным)
- Если товар отсутствует в магазине — серая ячейка с надписью "Нет"

### 4. Детальное сравнение товара
- Кнопка "Сравнить" у каждого товара в списке
- Модальное окно с детальной информацией:
  - Текущая цена в каждом выбранном магазине
  - История цен (график или таблица)
  - Разница в цене между магазинами (мин/макс)
  - Ссылка на товар в конкретном магазине (если есть)

## Техническая реализация

### Изменения в frontend (products.html)

#### 1. Панель выбора магазинов
```html
<div class="card">
    <h3>Выберите магазины для сравнения</h3>
    <div id="storesSelector">
        <!-- Чекбоксы магазинов генерируются JS -->
    </div>
    <button class="btn btn-primary" onclick="applyStoreComparison()">Применить</button>
    <span id="selectedStoresCount" class="badge">Выбрано: 0</span>
</div>
```

#### 2. Группировка по категориям (аккордеон)
```html
<div id="categoriesAccordion">
    <!-- Каждая категория: -->
    <div class="accordion-item">
        <div class="accordion-header" onclick="toggleCategory('cat1')">
            <span>🍞 Хлеб и выпечка (15)</span>
            <span class="toggle-icon">▼</span>
        </div>
        <div class="accordion-content" id="cat1">
            <!-- Товары категории -->
        </div>
    </div>
</div>
```

#### 3. Таблица сравнения
```html
<table id="comparisonTable">
    <thead>
        <tr>
            <th>Товар</th>
            <th>Магазин 1</th>
            <th>Магазин 2</th>
            <th>Магазин 3</th>
            <th>Действия</th>
        </tr>
    </thead>
    <tbody>
        <!-- Товары с ценами по магазинам -->
    </tbody>
</table>
```

#### 4. Модальное окно детального сравнения
```html
<div id="detailCompareModal" style="display: none;">
    <h3>Детальное сравнение: {productName}</h3>
    <div id="detailCompareContent">
        <!-- Таблица с ценами и историей -->
    </div>
    <button onclick="closeDetailCompareModal()">Закрыть</button>
</div>
```

### JavaScript-функции

#### Загрузка списка магазинов
```javascript
async function loadStoresForComparison() {
    const response = await fetch('/api/stores?limit=100');
    const stores = await response.json();
    // Генерация чекбоксов
}
```

#### Применение выбранных магазинов
```javascript
function applyStoreComparison() {
    const selected = getSelectedStores();
    localStorage.setItem('compareStores', JSON.stringify(selected));
    loadProductsByStores(selected);
}
```

#### Загрузка товаров по выбранным магазинам
```javascript
async function loadProductsByStores(storeCodes) {
    // Параллельная загрузка товаров из всех магазинов
    // Группировка по категориям
    // Отрисовка таблицы сравнения
}
```

#### Переключение категорий (аккордеон)
```javascript
function toggleCategory(categoryId) {
    const content = document.getElementById(categoryId);
    const icon = event.target.querySelector('.toggle-icon');
    
    if (content.style.display === 'none') {
        content.style.display = 'block';
        icon.textContent = '▼';
    } else {
        content.style.display = 'none';
        icon.textContent = '▶';
    }
}
```

#### Детальное сравнение товара
```javascript
async function showDetailCompare(productId, productName) {
    const selectedStores = getSelectedStores();
    // Загрузка данных о товаре в каждом магазине
    // Загрузка истории цен
    // Отрисовка модального окна
}
```

### Стили (CSS)

```css
/* Акордеон категорий */
.accordion-item {
    border: 1px solid #ddd;
    margin-bottom: 8px;
    border-radius: 4px;
}

.accordion-header {
    background: #f8f9fa;
    padding: 12px;
    cursor: pointer;
    display: flex;
    justify-content: space-between;
    font-weight: bold;
}

.accordion-content {
    display: none;
    padding: 12px;
}

/* Подсветка лучшей цены */
.best-price {
    background-color: #d4edda;
    font-weight: bold;
}

/* Отсутствие товара */
.no-stock {
    color: #999;
    font-style: italic;
}
```

## API-эндпоинты (используем существующие)

- `GET /api/stores` — список всех магазинов
- `GET /api/products?store_code={code}&category_id={id}` — товары магазина
- `GET /api/products/{id}?store_code={code}` — товар в конкретном магазине
- `GET /api/prices/daily-history/{id}?store_code={code}&days=30` — история цен

## Этапы реализации

1. **Фаза 1**: Панель выбора магазинов + сохранение в localStorage
2. **Фаза 2**: Группировка товаров по категориям (аккордеон)
3. **Фаза 3**: Таблица сравнения товаров по выбранным магазинам
4. **Фаза 4**: Детальное модальное окно сравнения с историей цен
5. **Фаза 5**: Подсветка лучшей цены, UX-улучшения

## Примечания

- Максимум 5 магазинов для сравнения (чтобы таблица не была слишком широкой)
- Использовать параллельные запросы (`Promise.all`) для скорости
- Кэшировать данные в sessionStorage для повторных запросов
- Добавить индикатор загрузки при загрузке данных из нескольких магазинов
