# Design

## Context

Мотивация — см. proposal.md, требования — в specs/. Текущее состояние:

- `database.py`: `create_engine(DATABASE_URL, connect_args={"check_same_thread": False})`. Журнал SQLite по умолчанию (`DELETE`): писатель блокирует читателей. Таймаут драйвера `sqlite3` — 5 с.
- Пишут в БД параллельно:
  - фоновые задачи `BackgroundTasks` (`scan-all-stores`, `/prices/update`);
  - поток полной замены каталога;
  - `BackgroundScheduler`.
- `CatalogScanner.scan_products` перед каждой категорией и каждой попыткой запроса страницы делает `self.db.expire_all()`, затем перечитывает `ScanJob` целиком. `scan_all_stores` делает то же перед каждым магазином.
- `_update_job_progress` и `_update_job_progress_full` коммитят при каждом вызове (на каждую категорию и каждую страницу).
- `open_product_in_browser` запускает `threading.Thread` без обёртки. `open_product_with_store` ловит исключения сам, но пишет их через `print`.
- `/redirect-to-product` и `/open-product-in-browser` из текущих шаблонов не вызываются: UI строит ссылки на magnit.ru напрямую.

## Goals / Non-Goals

**Goals:**
- Убрать ошибки блокировки при обычной нагрузке: один пользователь, фоновый скан, планировщик.
- Сократить число коммитов и перечитываний во время скана, не меняя результатов.

**Non-Goals:**
- Переход на другую СУБД или пул соединений с ограничением писателей.
- Удаление неиспользуемых `/redirect-to-product` и `/open-product-in-browser`: решение за владельцем, сейчас — только защита.

## Decisions

### D1. PRAGMA через событие `connect`
```python
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False, "timeout": 30})

@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _record):
    cur = dbapi_connection.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA busy_timeout=30000")
    cur.close()
```
`journal_mode=WAL` сохраняется в файле БД, но выполнять его на каждом соединении безопасно и дёшево. `busy_timeout` действует только в рамках соединения, поэтому событие обязательно.
*Альтернатива:* `NullPool` или сериализация писателей через lock. Отклонено: WAL решает основную проблему (читатели против писателя) без изменения архитектуры.

### D2. Проверка отмены — запрос колонки статуса
Хелпер `CatalogScanner._is_cancelled()`:
```python
row = self.db.query(ScanJob.status).filter(ScanJob.id == self.job_id).first()
return bool(row) and row[0] == "cancelled"
```
Запрос колонки, а не сущности, не использует identity map и всегда читает значение из БД. Видимость свежего значения обеспечивается тем, что каждая страница заканчивается `commit()` (`_save_products`), так что следующий запрос начинает новую транзакцию и новый снимок WAL. Перед первой проверкой, когда коммитов ещё не было, хелпер вызывает `self.db.commit()`: это дёшево, если изменений нет. `expire_all()` удаляется в обоих местах сканера. В `scan_all_stores` проверка выполняется той же формой запроса.
Имя категории для сообщения прогресса берётся из одного словаря `magnit_id → name`, загруженного до цикла, вместо запроса `Category` на каждую категорию.

### D3. Троттлинг прогресса
В `CatalogScanner` поле `_last_progress_ts` (`time.monotonic()`) и константа `PROGRESS_MIN_INTERVAL = 2.0` с.
- `_update_job_progress(message, force=False)` и `_update_job_progress_full(force=False, **fields)` при `force=False` и интервале меньше 2 с не пишут в БД, а сохраняют последние значения в `self._pending_progress`.
- Ближайший вызов после истечения интервала или вызов с `force=True` записывает накопленные значения одним `UPDATE` + `commit`.
- `force=True` передаётся для сообщений о старте, недоступной категории, отмене, ошибке и итоге скана. Перед возвратом из `scan_products` накопленный прогресс сбрасывается принудительно.

Интервал 2 с выбран так, чтобы с запасом укладываться в требование «не реже 5 с»: страница API занимает около 0.6–1.5 с с учётом rate limiting.
*Альтернатива:* писать прогресс в память процесса (как `_catalog_update_status`). Отклонено: `/jobs` читает прогресс из `ScanJob`, а задания могут идти из планировщика.

### D4. Проверка ссылок на Магнит
Функция `_is_magnit_url(url) -> bool` в `main.py`: `urllib.parse.urlsplit`, схема `https`, `hostname == "magnit.ru"`. Проверяется именно `hostname`, потому что проверка префикса строки пропускает `https://magnit.ru.evil.example`. Её используют оба эндпоинта, при неуспехе — `HTTPException(400, "Допустимы только ссылки на magnit.ru")`.

### D5. Обёртка потоков
Функция `run_logged(target, *args, **kwargs)` в `utils/threads.py` (общая для `main.py` и `routes/catalog.py`, поэтому не приватная в `main.py`): `try: target(...) except Exception: logger.exception(...)`. Ею запускаются поток `open_product_in_browser` и поток `fetch-magnit-ids`. В `product_opener.py` `print` заменяется на `logger`; внешний `except` сам пишет traceback через `logger.exception` и не пробрасывает исключение — иначе одна ошибка попала бы в лог дважды. Обёртка страхует от исключений, не пойманных внутри функции.

## Risks / Trade-offs

- [WAL на сетевых дисках работает некорректно] → БД лежит локально (`src/data/magnit.db`), это ограничение описывается в `docs/DEPLOYMENT.md`.
- [Файлы `-wal`/`-shm` при ручном копировании БД] → копировать при остановленном сервере или через `sqlite3 .backup`; записать в `docs/DEPLOYMENT.md`.
- [Прогресс в UI обновляется реже] → не реже раза в 2 с, итоговые сообщения пишутся сразу.
- [BREAKING для `/redirect-to-product` со сторонним URL] → UI его не использует; внешних клиентов не известно.

## Migration Plan

Перезапуск сервера: первое соединение переводит БД в WAL. Откат — `git revert`. БД остаётся в WAL, это совместимо со старым кодом. Вернуть журнал можно командой `PRAGMA journal_mode=DELETE` при остановленном сервере.
