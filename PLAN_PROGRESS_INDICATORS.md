# План реализации двух прогресс-индикаторов для страницы Каталог

## Дата: 2026-04-19

## Цель
Реализовать два детальных прогресс-индикатора на странице /catalog:
1. Общий прогресс по магазинам и категориям
2. Детальный прогресс по текущей категории с количеством товаров

Дополнительно:
- Восстановление прогресса при возврате на страницу
- Глобальный индикатор активных задач в header
- Toast-уведомления при завершении сканирования
- Опциональный список категорий с их статусами

## Требования

### Индикатор 1: Общий прогресс
- Формат: \"Магазин: Ленина 15 (2/5) | Категория: Молоко (3/8)\"
- Расчет процента: (обработано_магазинов * категорий) / (всего_магазинов * категорий) * 100
- Показывает название магазина и категории

### Индикатор 2: Детальный прогресс по категории
- Формат: \"Молоко и молочные продукты: 150 из 500 товаров (30%)\"
- Источник totalCount: API Магнита возвращает pagination.totalCount
- Статистика: Новых, Обновлено, Всего (без эмодзи)

### Список категорий (опционально)
- Кнопка \"Показать детали по категориям\"
- Список с иконками статуса
- Прогресс по каждой категории

## Архитектура изменений

### Backend изменения

#### 1. models.py - Расширение ScanJob
Добавить поля:
- total_stores: int - Всего магазинов
- current_store_index: int - Текущий магазин (индекс)
- current_store_code: str - Код текущего магазина
- current_store_address: str - Адрес текущего магазина
- total_categories: int - Всего категорий
- current_category_index: int - Текущая категория (индекс)
- current_category_name: str - Название текущей категории
- current_category_magnit_id: int - magnit_id текущей категории
- current_category_items_total: int - Всего товаров в текущей категории
- current_category_items_loaded: int - Загружено товаров в текущей категории

#### 2. main.py - Миграция БД
Функция: migrate_add_scan_job_progress_fields()
- Проверяет наличие новых колонок
- Добавляет через ALTER TABLE если отсутствуют
- Запускается автоматически при старте сервера

#### 3. schemas.py - Обновление ScanJobResponse
Добавить все новые поля в Pydantic модель

#### 4. routes/jobs.py - Новый endpoint
GET /api/jobs/active
- Фильтр: status IN ['pending', 'running']
- Опциональный параметр: job_type
- Возвращает: list[ScanJobResponse]

#### 5. routes/catalog.py - Обновление run_scan_all()
Изменения в функции scan_all_stores:
- Инициализация: job.total_stores, job.total_categories
- В цикле по магазинам: обновление current_store_index, current_store_code, current_store_address
- В цикле по категориям: обновление current_category_index, current_category_name, current_category_magnit_id
- Вызов scan_products_with_progress вместо scan_products

#### 6. services/catalog_scanner.py - Новый метод
scan_products_with_progress():
- Принимает job_id
- После каждой страницы товаров обновляет:
  - current_category_items_total (из API totalCount)
  - current_category_items_loaded (накопительно)
- Commit после каждого обновления

### Frontend изменения

#### 1. templates/catalog.html - Два прогресс-бара

HTML структура:
`html
<!-- Индикатор 1: Общий прогресс -->
<div id=\"overall-progress\" style=\"display: none;\">
    <div style=\"margin-bottom: 8px;\">
        <strong>Общий прогресс:</strong>
        <span id=\"overall-progress-text\">Магазин 2/5 | Категория 3/8</span>
        <span id=\"overall-progress-percent\">45%</span>
    </div>
    <div class=\"progress-bar\">
        <div id=\"overall-progress-bar\" style=\"width: 45%;\"></div>
    </div>
</div>

<!-- Индикатор 2: Детальный прогресс по категории -->
<div id=\"category-progress\" style=\"display: none;\">
    <div style=\"margin-bottom: 8px;\">
        <strong id=\"category-name\">Молоко и молочные продукты</strong>
        <span id=\"category-progress-text\">150 из 500 товаров</span>
        <span id=\"category-progress-percent\">30%</span>
    </div>
    <div class=\"progress-bar\">
        <div id=\"category-progress-bar\" style=\"width: 30%;\"></div>
    </div>
    <div style=\"margin-top: 6px; font-size: 12px;\">
        Новых: <span id=\"category-added\">12</span> |
        Обновлено: <span id=\"category-updated\">8</span> |
        Всего: <span id=\"category-scanned\">150</span>
    </div>
</div>
`

JavaScript функции:
- restoreProgressIfNeeded() - проверка активных задач при загрузке
- updateProgressBars(job) - обновление обоих индикаторов
- startPolling(jobId) - запуск polling с интервалом 2 секунды
- handleScanComplete(status, job) - обработка завершения

#### 2. templates/base.html - Глобальный индикатор и Toast

Глобальный индикатор в navbar:
`html
<span id=\"global-job-indicator\" style=\"display: none;\">
    <span class=\"spinner\"></span>
    <span id=\"job-count\">0</span>
</span>
`

Toast контейнер:
`html
<div id=\"toast-container\"></div>
`

JavaScript:
- startGlobalPolling() - проверка активных задач каждые 5 секунд
- checkCompletedJobs() - проверка завершённых задач для toast
- showToast(message, type, duration, actionButton) - показ уведомления

#### 3. Опциональный список категорий

HTML:
`html
<button onclick=\"toggleCategoriesStatusList()\">
    Показать детали по категориям
</button>

<div id=\"categories-status-list\" style=\"display: none;\">
    <div id=\"categories-status-items\">
        <!-- Динамически заполняется -->
    </div>
</div>
`

JavaScript:
- toggleCategoriesStatusList() - показать/скрыть список
- updateCategoriesStatusList(job) - обновление статусов категорий
- categoriesStatusMap - Map для хранения статусов

## Порядок реализации

### Этап 1: Backend (миграция и API)
1. Обновить models.py - добавить поля в ScanJob
2. Создать миграцию в main.py
3. Обновить schemas.py - ScanJobResponse
4. Добавить endpoint /api/jobs/active в routes/jobs.py
5. Протестировать миграцию и endpoint

### Этап 2: Backend (логика сканирования)
1. Обновить catalog_scanner.py - добавить scan_products_with_progress()
2. Обновить routes/catalog.py - изменить run_scan_all()
3. Протестировать обновление прогресса в БД

### Этап 3: Frontend (прогресс-бары)
1. Обновить catalog.html - добавить HTML для двух индикаторов
2. Реализовать updateProgressBars(job)
3. Реализовать restoreProgressIfNeeded()
4. Обновить startScanProducts() для использования новых индикаторов
5. Протестировать восстановление прогресса

### Этап 4: Frontend (глобальный индикатор и toast)
1. Обновить base.html - добавить глобальный индикатор
2. Добавить toast-компонент и стили
3. Реализовать startGlobalPolling()
4. Реализовать showToast()
5. Протестировать на всех страницах

### Этап 5: Опциональная фича (список категорий)
1. Добавить HTML для списка категорий
2. Реализовать toggleCategoriesStatusList()
3. Реализовать updateCategoriesStatusList()
4. Протестировать отображение статусов

## Технические детали

### API Response структура
`json
{
  \"id\": 123,
  \"status\": \"running\",
  \"progress\": 45,
  \"total_stores\": 5,
  \"current_store_index\": 2,
  \"current_store_code\": \"992104\",
  \"current_store_address\": \"г. Москва, ул. Ленина, 15\",
  \"total_categories\": 8,
  \"current_category_index\": 3,
  \"current_category_name\": \"Молоко и молочные продукты\",
  \"current_category_magnit_id\": 12345,
  \"current_category_items_total\": 500,
  \"current_category_items_loaded\": 150,
  \"items_scanned\": 450,
  \"items_added\": 50,
  \"items_updated\": 100
}
`

### Расчет процентов
**Общий прогресс:**
`javascript
const totalOperations = job.total_stores * job.total_categories;
const currentOperation = (job.current_store_index - 1) * job.total_categories + job.current_category_index;
const overallPercent = Math.round((currentOperation / totalOperations) * 100);
`

**Прогресс по категории:**
`javascript
const categoryPercent = job.current_category_items_total > 0
    ? Math.round((job.current_category_items_loaded / job.current_category_items_total) * 100)
    : 0;
`

### Обработка edge cases

1. **Возврат на страницу во время сканирования:**
   - Проверка активных задач при DOMContentLoaded
   - Восстановление UI состояния (кнопки, прогресс-бары)
   - Запуск polling с текущего job_id

2. **Множественные активные задачи:**
   - Показываем только первую активную задачу
   - Глобальный индикатор показывает общее количество

3. **Отмена задачи:**
   - Polling обнаруживает status='cancelled'
   - Останавливает интервал
   - Скрывает прогресс-бары
   - Показывает сообщение об отмене

4. **Ошибка во время сканирования:**
   - Polling обнаруживает status='failed'
   - Показывает error_message
   - Скрывает прогресс-бары

5. **Категория без товаров:**
   - totalCount = 0
   - Показываем "0 из 0 товаров"
   - Процент = 0%

6. **API не вернул totalCount:**
   - Используем значение по умолчанию 0
   - Показываем только загруженные товары без процента

### Производительность

1. **Частота обновлений:**
   - Локальный polling на /catalog: каждые 2 секунды
   - Глобальный polling в header: каждые 5 секунд
   - Обновление БД: после каждой страницы товаров (32 товара)

2. **Оптимизация запросов:**
   - Один SELECT для проверки статуса задачи
   - Bulk UPDATE для прогресса (не создаём новые записи)
   - Commit только при изменении значений

3. **Кэширование:**
   - localStorage для completedJobs (предотвращение дублирования toast)
   - Очистка старых записей (старше 1 часа)

## Тестирование

### Сценарии тестирования

1. **Базовый сценарий:**
   - Запустить сканирование на /catalog
   - Проверить отображение обоих прогресс-баров
   - Дождаться завершения
   - Проверить финальное сообщение

2. **Восстановление прогресса:**
   - Запустить сканирование
   - Перейти на другую страницу
   - Вернуться на /catalog
   - Проверить восстановление прогресса

3. **Глобальный индикатор:**
   - Запустить сканирование
   - Перейти на /products
   - Проверить отображение индикатора в header
   - Кликнуть на индикатор → переход на /catalog

4. **Toast-уведомления:**
   - Запустить сканирование
   - Перейти на /products
   - Дождаться завершения
   - Проверить появление toast
   - Кликнуть \"Перейти к товарам\"

5. **Отмена сканирования:**
   - Запустить сканирование
   - Нажать \"Остановить\"
   - Проверить корректное завершение
   - Проверить скрытие прогресс-баров

6. **Список категорий:**
   - Запустить сканирование
   - Нажать \"Показать детали по категориям\"
   - Проверить отображение статусов
   - Проверить обновление в реальном времени

## Файлы для изменения

### Backend (7 файлов)
1. src/server/models.py
2. src/server/main.py
3. src/server/schemas.py
4. src/server/routes/jobs.py
5. src/server/routes/catalog.py
6. src/server/services/catalog_scanner.py
7. src/server/services/magnit_api.py (без изменений, уже возвращает totalCount)

### Frontend (2 файла)
1. src/server/templates/catalog.html
2. src/server/templates/base.html

## Риски и ограничения

1. **Миграция БД:**
   - Риск: Ошибка при добавлении колонок
   - Митигация: Проверка существования колонок перед ALTER TABLE

2. **Производительность:**
   - Риск: Частые UPDATE запросов могут замедлить БД
   - Митигация: Обновление только при изменении значений

3. **Совместимость:**
   - Риск: Старые задачи без новых полей
   - Митигация: Значения по умолчанию (0, NULL)

4. **UI перегрузка:**
   - Риск: Слишком много информации на экране
   - Митигация: Опциональный список категорий (скрыт по умолчанию)

## Следующие шаги

После реализации базового функционала можно добавить:
1. Фильтрация активных задач по типу (scan_all_stores, update_catalog)
2. История завершённых задач с детальной статистикой
3. Экспорт результатов сканирования в CSV/JSON
4. Уведомления через WebSocket (вместо polling)
5. Прогресс-бар для обновления каталога (fetch-magnit-ids)

---

**Конец плана**