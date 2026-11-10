# Spec Delta

## REMOVED Requirements

### Requirement: Один основной эндпоинт синхронизации подкатегорий
**Reason**: `update-catalog` и `scan` не использовались интерфейсом и дублировали полную замену каталога.
**Migration**: `POST /api/categories/fetch-magnit-ids`.

### Requirement: Загрузка корневых категорий доступна по одному пути
**Reason**: `load-from-json` удалён; корни из `categories.json` читает полная замена каталога.
**Migration**: `POST /api/categories/fetch-magnit-ids`.

### Requirement: Синхронизация подкатегорий обрабатывает все корни
**Reason**: отдельная синхронизация подкатегорий удалена.
**Migration**: `POST /api/categories/fetch-magnit-ids`.

### Requirement: Загрузка корневых категорий из файла
**Reason**: эндпоинт удалён.
**Migration**: `POST /api/categories/fetch-magnit-ids` (корни берутся из `src/data/categories.json`).

## ADDED Requirements

### Requirement: Каталог обновляется только полной заменой
Категории SHALL обновляться только полной заменой каталога (`POST /api/categories/fetch-magnit-ids` и еженедельное задание планировщика). Эндпоинты `POST /api/categories/update-catalog`, `POST /api/categories/scan` и `POST /api/categories/load-from-json` SHALL отсутствовать.

#### Scenario: Вызов удалённого эндпоинта
- **WHEN** клиент вызывает `POST /api/categories/update-catalog`
- **THEN** ответ — 404 или 405, категории не изменяются

### Requirement: Полная замена каталога не выполняется параллельно
Пока идёт полная замена каталога, новый запуск SHALL NOT начинаться: `POST /api/categories/fetch-magnit-ids` SHALL возвращать `status: "in_progress"`, задание планировщика SHALL пропускаться.

#### Scenario: Двойной клик
- **WHEN** клиент дважды подряд вызывает `POST /api/categories/fetch-magnit-ids`
- **THEN** первый ответ — `started`, второй — `in_progress`, выполняется одна замена
