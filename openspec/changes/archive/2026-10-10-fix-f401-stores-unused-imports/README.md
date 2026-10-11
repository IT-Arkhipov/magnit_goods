# fix-f401-stores-unused-imports

Удаление двух неиспользуемых импортов (F401) в `src/server/routes/stores.py` — единственном файле проекта, где ruff находит F401.

## Область

- `src/server/routes/stores.py:10` — `Request` импортируется, но не используется ни в одном обработчике
- `src/server/routes/stores.py:12` — `import time`; `time.` в файле не встречается

## Вне области

- Остальные 46 ошибок ruff (E741, F401 в других файлах, и т. д.) — не трогаются
- Логика обработчиков `/api/stores/*` — не изменяется

## Verification

1. `python -m py_compile src/server/routes/stores.py`
2. `python -c "from src.server.app import app; print('ok')"`
3. `python -m ruff check src/server/routes/stores.py` → F401 отсутствуют
