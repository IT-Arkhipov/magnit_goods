# F401: удалить неиспользуемые импорты Request и time в routes/stores.py

## 1. Подготовка

- [x] 1.1 Подтвердить, что `Request` и `time` не используются в `src/server/routes/stores.py` (grep по всему проекту — только строки импорта)

## 2. Удаление импортов

- [x] 2.1 Изменить строку 1: `from fastapi import APIRouter, Depends, HTTPException, Query, Request` → `from fastapi import APIRouter, Depends, HTTPException, Query`
- [x] 2.2 Удалить строку 7: `import time`

## 3. Проверка

- [x] 3.1 Убедиться, что файл компилируется: `python -m py_compile src/server/routes/stores.py`
- [x] 3.2 Проверить загрузку приложения: `python -c "from src.server.main import app; print('ok')"` (модуль `src.server.app` не существует — приложение в `src.server.main`)
- [x] 3.3 Прогнать `python -m ruff check src/server/routes/stores.py` — F401 для `Request` и `time` отсутствуют