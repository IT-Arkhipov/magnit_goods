# Proposal

## Why

`ruff check src/` сообщает F401 (unused imports) в `src/server/routes/stores.py`: `fastapi.Request` и `time` импортируются, но нигде в модуле не используются. Неиспользуемые импорты накапливают шум в lint-выводе и постепенно маскируют реальные предупреждения.

## What Changes

- Удалить неиспользуемый импорт `Request` из модуля `routes/stores`
- Удалить неиспользуемый импорт `time` из модуля `routes/stores`

Поведение API и контракты обработчиков не меняются: оба имени не встречаются ни в одном обработчике, ни в одном helper-вызове внутри модуля.

## Capabilities

### New Capabilities
None.

### Modified Capabilities
None.

## Impact

- Модуль `src/server/routes/stores.py` — только удаление двух строк импорта
- Нет изменений в поведении, схемах или интерфейсе
- Нулевой риск: имена не используются нигде в модуле