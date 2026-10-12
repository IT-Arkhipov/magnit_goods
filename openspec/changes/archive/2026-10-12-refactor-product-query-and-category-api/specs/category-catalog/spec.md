# Spec Delta

## Purpose

Определяет хранение дерева категорий Магнита и набор эндпоинтов для его синхронизации и загрузки.

## ADDED Requirements

### Requirement: Один основной эндпоинт синхронизации подкатегорий
Синхронизация подкатегорий SHALL выполняться через `POST /api/categories/update-catalog`. `POST /api/categories/scan` SHALL оставаться рабочим с тем же результатом, но SHALL быть помечен в OpenAPI как устаревший.

#### Scenario: Устаревший эндпоинт
- **WHEN** клиент вызывает `POST /api/categories/scan?store_code=<код>`
- **THEN** ответ совпадает по структуре и результату с `POST /api/categories/update-catalog?store_code=<код>`, а в `/docs` эндпоинт отмечен как deprecated

### Requirement: Загрузка корневых категорий доступна по одному пути
Загрузка корневых категорий из файла SHALL быть доступна только по `POST /api/categories/load-from-json`; прежние алиасы `build-from-playwright` и `seed-from-playwright` SHALL отсутствовать.

#### Scenario: Вызов удалённого алиаса
- **WHEN** клиент вызывает `POST /api/categories/build-from-playwright`
- **THEN** ответ — 404 или 405, категории не изменяются
