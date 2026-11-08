import logging
import os
from sqlalchemy import create_engine, event, func, text, inspect
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Путь к БД: src/data/magnit.db
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATABASE_URL = f"sqlite:///{os.path.join(PROJECT_ROOT, 'src', 'data', 'magnit.db')}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False, "timeout": 30},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _connection_record):
    """WAL: читатели не блокируются писателем; busy_timeout: запись ждёт блокировку, а не падает."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=30000")
    cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    """Dependency для FastAPI — предоставляет и закрывает сессию БД."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Создать все таблицы при старте и выполнить миграции.

    Каждая миграция выполняется ровно один раз за всю жизнь БД: после
    УСПЕШНОГО выполнения её имя регистрируется в таблице schema_migrations,
    и при последующих запусках она пропускается. Миграция, завершившаяся
    ошибкой, не регистрируется и повторяется при следующем старте.
    """
    from src.server.models import (  # noqa: F401
        Store,
        Category,
        Product,
        PriceHistory,
        ScanJob,
        SchemaMigration,
    )
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    try:
        _run_migration(db, "simplify_price_tracking", migrate_simplify_price_tracking, db)
        _run_migration(db, "add_last_change_fields", migrate_add_last_change_fields, db)
        _run_migration(db, "add_product_indexes", migrate_add_product_indexes, db)
        _run_migration(db, "store_ids", migrate_store_ids)
        _run_migration(db, "categories", migrate_categories)
        _run_migration(db, "add_shop_type", migrate_add_shop_type)
        _run_migration(db, "fill_shop_type", migrate_fill_shop_type)
        _run_migration(db, "add_last_scan_found", migrate_add_last_scan_found)
        _run_migration(db, "add_scan_job_progress_fields", migrate_add_scan_job_progress_fields)
        _run_migration(db, "fix_previous_price", migrate_fix_previous_price, db)
        _run_migration(db, "create_price_history", migrate_create_price_history, db)
        _run_migration(db, "backfill_price_history", migrate_backfill_price_history, db)
        _run_migration(db, "ensure_product_last_scan_index", migrate_ensure_product_last_scan_index)
        _run_migration(db, "add_store_code_type_unique", migrate_add_store_code_type_unique, db)
        _run_migration(db, "add_product_name_search", migrate_add_product_name_search, db)
        _run_migration(db, "add_product_store_type", migrate_add_product_store_type)
        _run_migration(db, "fix_store_shop_type", migrate_fix_store_shop_type, db)
    finally:
        db.close()


def _run_migration(db, name: str, func, *args, **kwargs):
    """Запустить миграцию, если она ещё не была выполнена.

    Контракт миграции: функция либо успешно возвращается, либо бросает
    исключение. Использует таблицу schema_migrations как реестр применённых
    миграций: регистрация — только при успехе. При ошибке пишется
    предупреждение, транзакция откатывается, миграция остаётся
    незарегистрированной (повторится при следующем старте), а сервер
    продолжает запуск.
    """
    from src.server.models import SchemaMigration

    applied = db.query(SchemaMigration).filter_by(name=name).first()
    if applied:
        return

    logger.info("Миграция: %s...", name)
    try:
        func(*args, **kwargs)
    except Exception as e:
        db.rollback()
        logger.warning(
            "Миграция %s не выполнена и будет повторена при следующем старте: %s",
            name, e, exc_info=True,
        )
        return

    try:
        db.add(SchemaMigration(name=name, applied_at=datetime.utcnow()))
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning("Не удалось зарегистрировать миграцию %s: %s", name, e)


def _column_names(table: str) -> set[str]:
    """Имена колонок таблицы (пустое множество, если таблицы нет)."""
    inspector = inspect(engine)
    if table not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


# Магазины по коду в порядке «самый ранний первым» — как при удалении дубликатов
# в migrate_add_store_code_type_unique
_STORE_TYPE_ROWS_SQL = (
    "SELECT store_code, store_type FROM stores ORDER BY store_code, created_at, rowid"
)


def _default_store_type_code() -> str:
    """Код типа для записей, у кода которых нет магазина в БД (тип по умолчанию)."""
    from src.server.constants import API_STORE_TYPE_CODE, DEFAULT_STORE_TYPE

    return API_STORE_TYPE_CODE[DEFAULT_STORE_TYPE]


def _store_type_code_map(rows) -> dict[str, str]:
    """Карта store_code → код типа магазина для заполнения существующих записей.

    rows — пары (store_code, store_type) из _STORE_TYPE_ROWS_SQL. Тип берётся
    из названия (store_type), а не из stores.shop_type: в старых БД shop_type
    бывает испорчен. Если у кода несколько магазинов разных типов, берётся
    самый ранний, а выбор пишется в лог. Кодов без магазина в карте нет —
    для них вызывающий использует _default_store_type_code().
    """
    from src.server.constants import resolve_store_type_code

    result: dict[str, str] = {}
    for store_code, store_type in rows:
        code = resolve_store_type_code(store_type)
        if store_code not in result:
            result[store_code] = code
        elif result[store_code] != code:
            logger.warning(
                "У кода магазина %s несколько типов: существующим записям назначен "
                "тип %s самого раннего магазина (тип %s пропущен)",
                store_code, result[store_code], code,
            )
    return result


def _history_store_type_fields(db):
    """Для старых миграций, пишущих в price_history: что писать в store_type_code.

    Возвращает (колонки Product для выборки, функцию строка-товара → dict доп.
    полей). Если в price_history колонки store_type_code нет (старая схема,
    её добавит migrate_add_product_store_type) — доп. полей нет. Иначе тип
    берётся из записи товара, если колонка уже есть в products, или из карты
    магазинов (_store_type_code_map) с типом по умолчанию.
    """
    from src.server.models import Product

    if "store_type_code" not in _column_names("price_history"):
        return [], lambda p: {}
    if "store_type_code" in _column_names("products"):
        return [Product.store_type_code], lambda p: {"store_type_code": p.store_type_code}
    type_map = _store_type_code_map(db.execute(text(_STORE_TYPE_ROWS_SQL)).fetchall())
    default_code = _default_store_type_code()
    return [], lambda p: {"store_type_code": type_map.get(p.store_code, default_code)}


def _drop_indexes_on_column(db, table: str, column: str):
    """Удалить созданные через CREATE INDEX индексы, в которые входит колонка."""
    # index_list: (seq, name, unique, origin, partial); origin 'c' — явный CREATE INDEX
    for row in db.execute(text(f"PRAGMA index_list({table})")).fetchall():
        index_name, origin = row[1], row[3]
        if origin != "c":
            continue
        indexed = [r[2] for r in db.execute(text(f"PRAGMA index_info({index_name})")).fetchall()]
        if column in indexed:
            db.execute(text(f"DROP INDEX {index_name}"))
            logger.info("  - Удалён индекс %s (колонка %s)", index_name, column)


def migrate_simplify_price_tracking(db):
    """
    Упрощение отслеживания цен:
    1. Удалить поля акций из products
    2. Добавить поля previous_price, price_change_percent
    3. Удалить устаревшую таблицу daily_price_snapshot

    Внимание: price_history НЕ удаляется — она пересоздаётся миграцией
    migrate_create_price_history и используется для по-дневной истории цен.
    """
    cols = _column_names("products")

    # Добавить новые поля в products
    for name in ("previous_price", "price_change_percent"):
        if name not in cols:
            db.execute(text(f"ALTER TABLE products ADD COLUMN {name} FLOAT"))
            logger.info("  + Добавлено поле %s", name)

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
        if col in cols:
            # SQLite не удаляет колонку, на которую ссылается индекс
            _drop_indexes_on_column(db, "products", col)
            db.execute(text(f"ALTER TABLE products DROP COLUMN {col}"))
            logger.info("  + Удалено поле %s", col)

    # Удалить устаревшую таблицу. price_history НЕ удаляем — см. docstring.
    db.execute(text("DROP TABLE IF EXISTS daily_price_snapshot"))

    db.commit()


def migrate_add_last_change_fields(db):
    """
    Добавить поля last_change_price и last_change_date для режима
    отображения последнего изменения цены.
    """
    cols = _column_names("products")

    if "last_change_price" not in cols:
        db.execute(text("ALTER TABLE products ADD COLUMN last_change_price FLOAT"))
        logger.info("  + Добавлено поле last_change_price")

    if "last_change_date" not in cols:
        db.execute(text("ALTER TABLE products ADD COLUMN last_change_date DATETIME"))
        logger.info("  + Добавлено поле last_change_date")

    # Заполнить для существующих товаров с изменением цены
    result = db.execute(text("""
        UPDATE products
        SET last_change_price = previous_price,
            last_change_date = last_price_change
        WHERE price_change_percent IS NOT NULL
          AND last_change_price IS NULL
    """))
    if result.rowcount > 0:
        logger.info("  + Заполнено %s записей", result.rowcount)

    db.commit()


def migrate_add_product_indexes(db):
    """Добавить составные индексы для ускорения операций с товарами."""
    cols = _column_names("products")

    db.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_product_store "
        "ON products(product_id, store_code)"
    ))
    db.execute(text(
        "CREATE INDEX IF NOT EXISTS ix_product_price_change "
        "ON products(store_code, price_change_percent)"
    ))

    # Колонка last_scan_found добавляется более поздней миграцией; индекс по ней
    # создаст migrate_ensure_product_last_scan_index.
    if "last_scan_found" in cols:
        db.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_product_last_scan "
            "ON products(store_code, last_scan_found)"
        ))

    db.commit()


def migrate_store_ids():
    """Конвертация integer ID в хэш-идентификаторы (однократно)."""
    from src.server.models import Store, store_hash_id

    inspector = inspect(engine)
    cols = [c["name"] for c in inspector.get_columns("stores")]
    if "id" not in cols:
        return  # таблица ещё не создана

    col_info = next(
        (c for c in inspector.get_columns("stores") if c["name"] == "id"), None
    )
    col_type = str(col_info["type"]).upper() if col_info else ""
    if "INT" not in col_type:
        return  # уже строка — миграция выполнена

    logger.info("Миграция: конвертация ID магазинов в хэш-формат...")

    # Чтение данных
    s1 = SessionLocal()
    try:
        rows = s1.query(Store).all()
        data = [
            (s.store_code, s.store_type, s.city, s.address, s.full_address, s.name)
            for s in rows
        ]
    finally:
        s1.close()

    # Пересоздание таблицы
    Store.__table__.drop(engine, checkfirst=True)
    Store.__table__.create(engine)

    # Вставка
    s2 = SessionLocal()
    try:
        now = datetime.utcnow()
        for sc, st, city, addr, fa, name in data:
            new_id = store_hash_id(sc, st, fa)
            s2.add(
                Store(
                    id=new_id,
                    store_code=sc,
                    store_type=st,
                    city=city,
                    address=addr,
                    full_address=fa,
                    name=name,
                    created_at=now,
                )
            )
        s2.commit()
        logger.info("Миграция завершена: %s магазинов", len(data))
    finally:
        s2.close()


def migrate_categories():
    """Пересоздать таблицу категорий, если у неё устаревшая структура.

    Устаревшая структура — наличие колонки category_id или store_code
    (категории тогда были привязаны к магазину). Актуальные категории
    универсальные: id, magnit_id, name, url, parent_id, ...
    """
    from src.server.models import Category

    cols = _column_names("categories")
    if not cols:
        return  # таблица ещё не создана

    if "category_id" in cols or "store_code" in cols:
        logger.info("Миграция: пересоздание таблицы категорий (устаревшая структура)...")
        Category.__table__.drop(engine, checkfirst=True)
        Category.__table__.create(engine)
        logger.info("Структура категорий обновлена. Загрузите каталог из JSON.")


def migrate_add_shop_type():
    """Добавить поле shop_type в таблицу stores (однократно)."""
    if "shop_type" not in _column_names("stores"):
        logger.info("Миграция: добавление поля shop_type в таблицу stores...")
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE stores ADD COLUMN shop_type INTEGER"))
            conn.commit()
        logger.info("Поле shop_type добавлено в таблицу stores")


def migrate_fill_shop_type():
    """Заполнить поле shop_type на основе store_type."""
    from src.server.models import Store
    from src.server.constants import STORE_TYPE_CODES

    db_session = SessionLocal()
    try:
        # Проверяем, есть ли уже заполненные значения
        filled_count = db_session.query(Store).filter(Store.shop_type.isnot(None)).count()
        if filled_count > 0:
            return  # уже заполнено

        logger.info("Миграция: заполнение поля shop_type...")

        for store_type, shop_type_code in STORE_TYPE_CODES.items():
            stores = db_session.query(Store).filter(Store.store_type == store_type).all()
            for store in stores:
                store.shop_type = shop_type_code
            if len(stores) > 0:
                logger.info(
                    "  Обновлено %s магазинов типа '%s' -> код %s",
                    len(stores), store_type, shop_type_code,
                )

        db_session.commit()
        logger.info("Поле shop_type успешно заполнено")
    except Exception:
        db_session.rollback()
        raise
    finally:
        db_session.close()


def migrate_add_last_scan_found():
    """Добавить поле last_scan_found в таблицу products (однократно)."""
    if "last_scan_found" not in _column_names("products"):
        logger.info("Миграция: добавление поля last_scan_found в таблицу products...")
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE products ADD COLUMN last_scan_found DATETIME"))
            conn.commit()
        logger.info("Поле last_scan_found добавлено в таблицу products")


def migrate_add_scan_job_progress_fields():
    """Добавить поля прогресса в таблицу scan_jobs."""
    cols = _column_names("scan_jobs")

    new_fields = [
        ("total_stores", "INTEGER DEFAULT 0"),
        ("current_store_index", "INTEGER DEFAULT 0"),
        ("current_store_code", "STRING"),
        ("current_store_address", "STRING"),
        ("total_categories", "INTEGER DEFAULT 0"),
        ("current_category_index", "INTEGER DEFAULT 0"),
        ("current_category_name", "STRING"),
        ("current_category_magnit_id", "INTEGER"),
        ("current_category_items_total", "INTEGER DEFAULT 0"),
        ("current_category_items_loaded", "INTEGER DEFAULT 0"),
    ]

    for field_name, field_type in new_fields:
        if field_name not in cols:
            logger.info("Миграция: добавление поля %s в таблицу scan_jobs...", field_name)
            with engine.connect() as conn:
                conn.execute(text(f"ALTER TABLE scan_jobs ADD COLUMN {field_name} {field_type}"))
                conn.commit()


def migrate_fix_previous_price(db):
    """Починить previous_price, испорченный старым кодом (он копировал price при каждом скане)."""
    logger.info("Миграция: восстановление previous_price для товаров с изменением цены...")

    # Восстанавливаем из last_change_price (там сохранена цена до последнего реального изменения)
    result = db.execute(text("""
        UPDATE products
        SET previous_price = last_change_price
        WHERE price_change_percent IS NOT NULL
          AND last_change_price IS NOT NULL
          AND ABS(previous_price - price) < 0.01
    """))
    fixed1 = result.rowcount

    # Для оставшихся — вычисляем из price_change_percent
    # Формула: old_price = price * 100 / (100 - price_change_percent)
    # Работает для обоих случаев:
    #   скидка 20%: 80 * 100 / 80 = 100
    #   повышение 25%: 100 * 100 / 125 = 80
    result = db.execute(text("""
        UPDATE products
        SET previous_price = ROUND(CAST(price AS FLOAT) * 100.0 / (100.0 - price_change_percent), 2)
        WHERE price_change_percent IS NOT NULL
          AND ABS(previous_price - price) < 0.01
    """))
    fixed2 = result.rowcount

    db.commit()
    total = fixed1 + fixed2
    if total > 0:
        logger.info("+ Восстановлено previous_price для %s товаров", total)
    else:
        logger.info("  - Нет товаров, требующих восстановления")


def migrate_create_price_history(db):
    """
    Создать таблицу price_history и заполнить начальными данными.
    Одна запись на день для каждого (product_id, store_code).
    """
    from datetime import date
    from src.server.models import PriceHistory, Product

    logger.info("Миграция: создание таблицы price_history...")

    # 1. Создать таблицу если не существует
    PriceHistory.__table__.create(engine, checkfirst=True)

    # 2. Проверить, есть ли данные (только id: в старой схеме нет поздних колонок)
    count = db.query(func.count(PriceHistory.id)).scalar()
    if count > 0:
        logger.info("  - В price_history уже есть %s записей, заполнение пропущено", count)
        return

    # 3. Заполнить начальными данными из текущих products (за сегодня)
    today = date.today()
    type_cols, type_fields = _history_store_type_fields(db)
    products = db.query(
        Product.product_id, Product.store_code, Product.price, Product.quantity, Product.in_stock,
        *type_cols,
    ).all()
    if not products:
        logger.info("  - Нет товаров в products для заполнения истории")
        return

    rows = [
        {
            "product_id": p.product_id,
            "store_code": p.store_code,
            "price": p.price,
            "quantity": p.quantity,
            "in_stock": p.in_stock,
            "scan_date": today,
            **type_fields(p),
        }
        for p in products
    ]
    db.bulk_insert_mappings(PriceHistory, rows)
    db.commit()
    logger.info("  + Заполнено %s начальных записей в price_history за %s", len(rows), today)


def migrate_backfill_price_history(db):
    """
    Восстановить price_history из last_change_price / last_change_date.

    Для каждого товара с заполненными last_change_price и last_change_date
    создаёт синтетическую запись в price_history за день до последнего
    изменения цены (scan_date = last_change_date - 1 день, price = last_change_price).
    Это даёт начальную точку для сравнения при следующем сканировании,
    если основная история была утеряна (например, из-за конфликта миграций).

    Идемпотентна: пропускает записи, которые уже есть в price_history.
    """
    from datetime import datetime
    from src.server.models import PriceHistory, Product

    logger.info("Миграция: восстановление price_history из last_change_price...")

    type_cols, type_fields = _history_store_type_fields(db)
    products = (
        db.query(
            Product.product_id,
            Product.store_code,
            Product.quantity,
            Product.in_stock,
            Product.last_change_price,
            Product.last_change_date,
            *type_cols,
        )
        .filter(
            Product.last_change_price.isnot(None),
            Product.last_change_date.isnot(None),
        )
        .all()
    )

    if not products:
        logger.info("  - Нет товаров с last_change_price для восстановления")
        return

    # Синтетическая запись: за день до last_change_date, цена = last_change_price
    synthetic_rows = []
    for p in products:
        if isinstance(p.last_change_date, datetime):
            change_date = p.last_change_date.date()
        else:
            change_date = p.last_change_date
        synthetic_date = change_date - timedelta(days=1)
        synthetic_rows.append({
            "product_id": p.product_id,
            "store_code": p.store_code,
            "price": p.last_change_price,
            "quantity": p.quantity,
            "in_stock": p.in_stock,
            "scan_date": synthetic_date,
            **type_fields(p),
        })

    # Существующие ключи истории для проверки дубликатов: (product_id, store_code,
    # scan_date) и тип магазина, если колонка уже есть
    with_type = "store_type_code" in _column_names("price_history")
    key_cols = [PriceHistory.product_id, PriceHistory.store_code, PriceHistory.scan_date]
    if with_type:
        key_cols.append(PriceHistory.store_type_code)
    existing_keys = {tuple(r) for r in db.query(*key_cols).all()}

    def row_key(r):
        key = (r["product_id"], r["store_code"], r["scan_date"])
        return key + (r["store_type_code"],) if with_type else key

    to_insert = [r for r in synthetic_rows if row_key(r) not in existing_keys]

    if to_insert:
        db.bulk_insert_mappings(PriceHistory, to_insert)
        db.commit()
        logger.info(
            "  + Восстановлено %s записей (пропущено %s существующих)",
            len(to_insert), len(synthetic_rows) - len(to_insert),
        )
    else:
        logger.info(
            "  - Нечего восстанавливать (все %s записей уже существуют)",
            len(synthetic_rows),
        )


def migrate_ensure_product_last_scan_index():
    """Создать индекс ix_product_last_scan, если его нет.

    На старых БД индекс не создавался: migrate_add_product_indexes выполнялась
    раньше, чем появилась колонка last_scan_found, а её ошибка подавлялась.
    """
    if "last_scan_found" not in _column_names("products"):
        raise RuntimeError("В таблице products нет колонки last_scan_found")
    with engine.connect() as conn:
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_product_last_scan "
            "ON products(store_code, last_scan_found)"
        ))
        conn.commit()


def migrate_add_store_code_type_unique(db):
    """Сделать пару (store_code, store_type) уникальной.

    Если в БД уже есть магазины-дубликаты пары, остаётся самый ранний
    (по created_at, затем по rowid), остальные удаляются с записью в лог.
    Товары не затрагиваются: они ключуются по store_code, а не по id магазина.
    """
    rows = db.execute(text(
        "SELECT rowid, id, store_code, store_type, full_address FROM stores "
        "ORDER BY store_code, store_type, created_at, rowid"
    )).fetchall()

    seen = set()
    for rowid, store_id, store_code, store_type, full_address in rows:
        key = (store_code, store_type)
        if key not in seen:
            seen.add(key)
            continue
        logger.warning(
            "Удалён дубликат магазина: code=%s type=%s id=%s address=%s",
            store_code, store_type, store_id, full_address,
        )
        db.execute(text("DELETE FROM stores WHERE rowid = :rowid"), {"rowid": rowid})

    db.execute(text(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_store_code_type "
        "ON stores(store_code, store_type)"
    ))
    db.commit()


def migrate_add_product_name_search(db):
    """Добавить products.name_search (name.casefold()) и заполнить для существующих товаров.

    Поиск по названию выполняется в SQL по этой колонке: SQLite LOWER() не работает
    с кириллицей, поэтому нормализованное название хранится отдельно.
    Заполнение — батчами по 1000 строк; повторный запуск дозаполняет только NULL.
    """
    if "name_search" not in _column_names("products"):
        db.execute(text("ALTER TABLE products ADD COLUMN name_search VARCHAR"))
        db.commit()
        logger.info("  + Добавлено поле name_search")

    total = 0
    while True:
        rows = db.execute(text(
            "SELECT id, name FROM products WHERE name_search IS NULL ORDER BY id LIMIT 1000"
        )).fetchall()
        if not rows:
            break
        db.execute(
            text("UPDATE products SET name_search = :ns WHERE id = :id"),
            [{"id": row[0], "ns": (row[1] or "").casefold()} for row in rows],
        )
        db.commit()
        total += len(rows)
    logger.info("  + name_search заполнен для %s товаров", total)


# Уникальные индексы старого ключа товара без типа магазина: мешают хранить один
# товар у магазинов одного кода и разных типов. uq_product_store создаёт
# migrate_add_product_indexes (в том числе на новой БД), uq_product_store_category
# остался в старых БД от ранних версий.
_LEGACY_PRODUCT_UNIQUE_INDEXES = ("uq_product_store", "uq_product_store_category")


def _table_columns(cur, table: str) -> list[str]:
    return [row[1] for row in cur.execute(f"PRAGMA table_info({table})").fetchall()]


def _sync_table_indexes(cur, table) -> None:
    """Привести индексы таблицы к объявленным в модели (имя, состав, уникальность).

    Индекс с тем же именем, но другим составом колонок или уникальностью
    пересоздаётся; отсутствующий — создаётся. Прочие индексы не трогаются.
    """
    from sqlalchemy.schema import CreateIndex

    existing = {}
    for row in cur.execute(f"PRAGMA index_list({table.name})").fetchall():
        name, unique = row[1], bool(row[2])
        cols = [r[2] for r in cur.execute(f"PRAGMA index_info({name})").fetchall()]
        existing[name] = (cols, unique)

    for index in table.indexes:
        wanted = ([c.name for c in index.columns], bool(index.unique))
        if existing.get(index.name) == wanted:
            continue
        if index.name in existing:
            cur.execute(f"DROP INDEX {index.name}")
            logger.info("  - Индекс %s пересоздаётся: %s → %s", index.name, existing[index.name], wanted)
        cur.execute(str(CreateIndex(index).compile(dialect=engine.dialect)))
        logger.info("  + Создан индекс %s %s", index.name, wanted[0])


def _rebuild_price_history_with_store_type(cur, default_code: str) -> None:
    """Пересобрать price_history по схеме модели с колонкой store_type_code.

    Уникальность старой таблицы встроена в CREATE TABLE (uq_price_history_day),
    SQLite не умеет её изменить — таблица переименовывается, создаётся заново,
    данные копируются с типом из временной карты _store_type_map.
    """
    from sqlalchemy.schema import CreateTable
    from src.server.models import PriceHistory

    table = PriceHistory.__table__
    before = cur.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
    old_cols = set(_table_columns(cur, "price_history"))

    cur.execute("ALTER TABLE price_history RENAME TO price_history_old")
    # Имена индексов в SQLite глобальны: явные индексы старой таблицы мешают
    # создать одноимённые у новой
    for row in cur.execute("PRAGMA index_list(price_history_old)").fetchall():
        if row[3] == "c":
            cur.execute(f"DROP INDEX {row[1]}")
    cur.execute(str(CreateTable(table).compile(dialect=engine.dialect)))

    copy_cols = [c.name for c in table.columns if c.name in old_cols and c.name != "store_type_code"]
    cols_sql = ", ".join(copy_cols)
    cur.execute(
        f"INSERT INTO price_history ({cols_sql}, store_type_code) "
        f"SELECT {', '.join('o.' + c for c in copy_cols)}, "
        "COALESCE((SELECT m.code FROM _store_type_map m WHERE m.store_code = o.store_code), ?) "
        "FROM price_history_old o",
        (default_code,),
    )
    after = cur.execute("SELECT COUNT(*) FROM price_history").fetchone()[0]
    if after != before:
        raise RuntimeError(f"price_history: скопировано {after} записей из {before}")
    cur.execute("DROP TABLE price_history_old")
    logger.info("  + price_history пересобрана: %s записей с типом магазина", after)


def _add_product_store_type_steps(cur) -> None:
    """Шаги migrate_add_product_store_type внутри открытой транзакции."""
    from src.server.models import PriceHistory, Product

    default_code = _default_store_type_code()
    type_map = _store_type_code_map(cur.execute(_STORE_TYPE_ROWS_SQL).fetchall())
    cur.execute("DROP TABLE IF EXISTS temp._store_type_map")
    cur.execute("CREATE TEMP TABLE _store_type_map (store_code TEXT PRIMARY KEY, code TEXT NOT NULL)")
    cur.executemany("INSERT INTO _store_type_map VALUES (?, ?)", list(type_map.items()))

    # products: колонка добавляется без пересборки (уникальность — отдельный индекс)
    if "store_type_code" not in _table_columns(cur, "products"):
        cur.execute("ALTER TABLE products ADD COLUMN store_type_code VARCHAR")
        cur.execute(
            "UPDATE products SET store_type_code = COALESCE("
            "(SELECT m.code FROM _store_type_map m WHERE m.store_code = products.store_code), ?)",
            (default_code,),
        )
        logger.info("  + products.store_type_code добавлен и заполнен")
    missing = cur.execute("SELECT COUNT(*) FROM products WHERE store_type_code IS NULL").fetchone()[0]
    if missing:
        raise RuntimeError(f"products: у {missing} записей не заполнен store_type_code")

    for name in _LEGACY_PRODUCT_UNIQUE_INDEXES:
        if cur.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name=?", (name,)).fetchone():
            cur.execute(f"DROP INDEX {name}")
            logger.info("  - Удалён устаревший уникальный индекс %s", name)

    if "store_type_code" not in _table_columns(cur, "price_history"):
        _rebuild_price_history_with_store_type(cur, default_code)

    _sync_table_indexes(cur, Product.__table__)
    _sync_table_indexes(cur, PriceHistory.__table__)
    cur.execute("DROP TABLE temp._store_type_map")


def migrate_add_product_store_type():
    """Добавить тип магазина (store_type_code) в ключ товаров и истории цен.

    Товары и история ключуются тройкой (product_id, store_code, store_type_code):
    магазины одного кода и разных типов больше не перезаписывают данные друг друга.
    Тип существующих записей — по stores.store_type (см. _store_type_code_map),
    для кодов без магазина — тип по умолчанию.

    Выполняется одной транзакцией на отдельном соединении: в pysqlite DDL
    (ALTER/CREATE/DROP) входит в транзакцию только при явном BEGIN, поэтому
    соединение переводится в ручной режим (isolation_level=None). При ошибке —
    ROLLBACK, схема и данные остаются прежними, исключение уходит в _run_migration.
    """
    raw = engine.raw_connection()
    try:
        conn = raw.driver_connection
        prev_isolation = conn.isolation_level
        conn.isolation_level = None
        cur = conn.cursor()
        try:
            cur.execute("BEGIN IMMEDIATE")
            try:
                _add_product_store_type_steps(cur)
                cur.execute("COMMIT")
            except Exception:
                cur.execute("ROLLBACK")
                raise
        finally:
            cur.close()
            conn.isolation_level = prev_isolation
    finally:
        raw.close()


def migrate_fix_store_shop_type(db):
    """Пересчитать stores.shop_type по названию типа (store_type).

    В старых БД shop_type бывал испорчен (у «Моя цена» — 3, код М.Косметик,
    вместо 9). Магазин с нераспознанным store_type не меняется — пишется
    предупреждение.
    """
    from src.server.constants import STORE_TYPE_CODES

    rows = db.execute(text("SELECT id, store_code, store_type, shop_type FROM stores")).fetchall()
    fixed = 0
    for store_id, store_code, store_type, shop_type in rows:
        code = STORE_TYPE_CODES.get(store_type)
        if code is None:
            logger.warning(
                "Магазин %s (код %s): неизвестный тип %r — shop_type не изменён",
                store_id, store_code, store_type,
            )
            continue
        if shop_type != code:
            db.execute(
                text("UPDATE stores SET shop_type = :code WHERE id = :id"),
                {"code": code, "id": store_id},
            )
            logger.info("  + Магазин %s (%s): shop_type %s → %s", store_code, store_type, shop_type, code)
            fixed += 1
    db.commit()
    logger.info("  + shop_type исправлен у %s магазинов", fixed)
