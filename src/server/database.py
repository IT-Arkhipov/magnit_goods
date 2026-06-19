import os
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker, declarative_base
from datetime import datetime, timedelta

# Путь к БД: src/data/magnit.db
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATABASE_URL = f"sqlite:///{os.path.join(PROJECT_ROOT, 'src', 'data', 'magnit.db')}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
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
    """Создать все таблицы при старте и выполнить миграции."""
    # Импортируем модели чтобы Base их знал
    from src.server.models import Store, Category, Product, PriceHistory, ScanJob  # noqa: F401
    Base.metadata.create_all(bind=engine)

    # Выполняем миграции
    db = SessionLocal()
    try:
        migrate_simplify_price_tracking(db)
        migrate_add_last_change_fields(db)
        migrate_add_product_indexes(db)
        migrate_store_ids()
        migrate_categories()
        migrate_add_shop_type()
        migrate_fill_shop_type()
        migrate_add_last_scan_found()
        migrate_add_scan_job_progress_fields()
        migrate_fix_previous_price(db)
        migrate_create_price_history(db)
    finally:
        db.close()


def migrate_simplify_price_tracking(db):
    """
    Упрощение отслеживания цен:
    1. Удалить поля акций из products
    2. Добавить поля previous_price, price_change_percent
    3. Удалить таблицы price_history, daily_price_snapshot
    """
    try:
        print("Миграция: упрощение отслеживания цен...")

        # Добавить новые поля в products
        try:
            db.execute(text("ALTER TABLE products ADD COLUMN previous_price FLOAT"))
            print("  + Добавлено поле previous_price")
        except Exception:
            print("  - Поле previous_price уже существует")

        try:
            db.execute(text("ALTER TABLE products ADD COLUMN price_change_percent FLOAT"))
            print("  + Добавлено поле price_change_percent")
        except Exception:
            print("  - Поле price_change_percent уже существует")

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
            try:
                db.execute(text(f"ALTER TABLE products DROP COLUMN {col}"))
                print(f"  + Удалено поле {col}")
            except Exception:
                print(f"  - Поле {col} уже удалено или не существует")

        # Удалить таблицы
        try:
            db.execute(text("DROP TABLE IF EXISTS price_history"))
            print("  + Таблица price_history удалена")
        except Exception as e:
            print(f"  ! Ошибка удаления price_history: {e}")

        try:
            db.execute(text("DROP TABLE IF EXISTS daily_price_snapshot"))
            print("  + Таблица daily_price_snapshot удалена")
        except Exception as e:
            print(f"  ! Ошибка удаления daily_price_snapshot: {e}")

        db.commit()
        print("+ Миграция завершена успешно")
    except Exception as e:
        db.rollback()
        print(f"ERROR migrate_simplify_price_tracking: {e}")
        import traceback
        traceback.print_exc()


def migrate_add_last_change_fields(db):
    """
    Добавить поля last_change_price и last_change_date для режима
    отображения последнего изменения цены.
    """
    try:
        print("Миграция: добавление полей last_change_price, last_change_date...")

        try:
            db.execute(text("ALTER TABLE products ADD COLUMN last_change_price FLOAT"))
            print("  + Добавлено поле last_change_price")
        except Exception:
            print("  - Поле last_change_price уже существует")

        try:
            db.execute(text("ALTER TABLE products ADD COLUMN last_change_date DATETIME"))
            print("  + Добавлено поле last_change_date")
        except Exception:
            print("  - Поле last_change_date уже существует")

        # Заполнить для существующих товаров с изменением цены
        result = db.execute(text("""
            UPDATE products
            SET last_change_price = previous_price,
                last_change_date = last_price_change
            WHERE price_change_percent IS NOT NULL
              AND last_change_price IS NULL
        """))
        updated = result.rowcount
        if updated > 0:
            print(f"  + Заполнено {updated} записей")

        db.commit()
        print("+ Миграция завершена")
    except Exception as e:
        db.rollback()
        print(f"ERROR migrate_add_last_change_fields: {e}")
        import traceback
        traceback.print_exc()


def migrate_add_product_indexes(db):
    """Добавить составные индексы для ускорения операций с товарами."""
    try:
        print("Миграция: добавление индексов для products...")

        try:
            db.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_product_store "
                "ON products(product_id, store_code)"
            ))
            print("  + Индекс uq_product_store добавлен")
        except Exception:
            print("  - Индекс uq_product_store уже существует")

        try:
            db.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_product_price_change "
                "ON products(store_code, price_change_percent)"
            ))
            print("  + Индекс ix_product_price_change добавлен")
        except Exception:
            print("  - Индекс ix_product_price_change уже существует")

        try:
            db.execute(text(
                "CREATE INDEX IF NOT EXISTS ix_product_last_scan "
                "ON products(store_code, last_scan_found)"
            ))
            print("  + Индекс ix_product_last_scan добавлен")
        except Exception:
            print("  - Индекс ix_product_last_scan уже существует")

        db.commit()
        print("+ Миграция индексов завершена")
    except Exception as e:
        db.rollback()
        print(f"ERROR migrate_add_product_indexes: {e}")
        import traceback
        traceback.print_exc()


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

    print("Миграция: конвертация ID магазинов в хэш-формат...", flush=True)

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
        print(f"Миграция завершена: {len(data)} магазинов", flush=True)
    finally:
        s2.close()


def migrate_categories():
    """Обновить структуру таблицы категорий (добавить code, url, убрать category_id)."""
    from src.server.models import Category

    inspector = inspect(engine)

    # Проверяем, есть ли таблица
    if "categories" not in inspector.get_table_names():
        return  # таблица ещё не создана

    cols = [c["name"] for c in inspector.get_columns("categories")]

    # Если структура уже правильная, ничего не делаем
    if "code" in cols and "url" in cols and "parent_id" in cols:
        return  # структура уже обновлена

    # Если есть старое поле category_id, нужна миграция
    if "category_id" in cols and "code" not in cols:
        print("Миграция: обновление структуры категорий...", flush=True)

        # Удаляем старую таблицу
        Category.__table__.drop(engine, checkfirst=True)
        Category.__table__.create(engine)

        print("Структура категорий обновлена. Загрузите каталог из JSON.", flush=True)
        return

    # Если есть store_code, убираем его
    if "store_code" in cols:
        print("Миграция: удаление store_code из категорий...", flush=True)
        Category.__table__.drop(engine, checkfirst=True)
        Category.__table__.create(engine)
        print("Миграция категорий завершена", flush=True)


def migrate_add_shop_type():
    """Добавить поле shop_type в таблицу stores (однократно)."""
    inspector = inspect(engine)
    cols = [c["name"] for c in inspector.get_columns("stores")]

    if "shop_type" not in cols:
        print("Миграция: добавление поля shop_type в таблицу stores...", flush=True)
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE stores ADD COLUMN shop_type INTEGER"))
            conn.commit()
        print("Поле shop_type добавлено в таблицу stores", flush=True)


def migrate_fill_shop_type():
    """Заполнить поле shop_type на основе store_type."""
    from src.server.models import Store
    from src.server.constants import STORE_TYPE_CODES

    db_session = SessionLocal()
    try:
        # Проверяем, есть ли уже заполненные значения
        filled_count = db_session.query(Store).filter(Store.shop_type != None).count()
        if filled_count > 0:
            return  # уже заполнено

        print("Миграция: заполнение поля shop_type...", flush=True)

        for store_type, shop_type_code in STORE_TYPE_CODES.items():
            stores = db_session.query(Store).filter(Store.store_type == store_type).all()
            for store in stores:
                store.shop_type = shop_type_code
            if len(stores) > 0:
                print(f"  Обновлено {len(stores)} магазинов типа '{store_type}' -> код {shop_type_code}", flush=True)

        db_session.commit()
        print("Поле shop_type успешно заполнено", flush=True)
    except Exception as e:
        print(f"Ошибка при заполнении shop_type: {e}", flush=True)
        db_session.rollback()
    finally:
        db_session.close()


def migrate_add_last_scan_found():
    """Добавить поле last_scan_found в таблицу products (однократно)."""
    inspector = inspect(engine)
    cols = [c["name"] for c in inspector.get_columns("products")]

    if "last_scan_found" not in cols:
        print("Миграция: добавление поля last_scan_found в таблицу products...", flush=True)
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE products ADD COLUMN last_scan_found DATETIME"))
            conn.commit()
        print("Поле last_scan_found добавлено в таблицу products", flush=True)


def migrate_add_scan_job_progress_fields():
    """Добавить поля прогресса в таблицу scan_jobs."""
    inspector = inspect(engine)
    cols = [c["name"] for c in inspector.get_columns("scan_jobs")]

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
            print(f"Миграция: добавление поля {field_name} в таблицу scan_jobs...", flush=True)
            with engine.connect() as conn:
                conn.execute(text(f"ALTER TABLE scan_jobs ADD COLUMN {field_name} {field_type}"))
                conn.commit()
            print(f"Поле {field_name} добавлено в таблицу scan_jobs", flush=True)


def migrate_fix_previous_price(db):
    """Починить previous_price, испорченный старым кодом (он копировал price при каждом скане)."""
    try:
        print("Миграция: восстановление previous_price для товаров с изменением цены...")

        # Восстанавливаем из last_change_price (там сохранена цена до последнего реального изменения)
        fixed1 = 0
        try:
            result = db.execute(text("""
                UPDATE products
                SET previous_price = last_change_price
                WHERE price_change_percent IS NOT NULL
                  AND last_change_price IS NOT NULL
                  AND ABS(previous_price - price) < 0.01
            """))
            fixed1 = result.rowcount
        except Exception:
            pass

        # Для оставшихся — вычисляем из price_change_percent
        # Формула: old_price = price * 100 / (100 - price_change_percent)
        # Работает для обоих случаев:
        #   скидка 20%: 80 * 100 / 80 = 100
        #   повышение 25%: 100 * 100 / 125 = 80
        fixed2 = 0
        try:
            result = db.execute(text("""
                UPDATE products
                SET previous_price = ROUND(CAST(price AS FLOAT) * 100.0 / (100.0 - price_change_percent), 2)
                WHERE price_change_percent IS NOT NULL
                  AND ABS(previous_price - price) < 0.01
            """))
            fixed2 = result.rowcount
        except Exception:
            pass

        db.commit()
        total = fixed1 + fixed2
        if total > 0:
            print(f"+ Восстановлено previous_price для {total} товаров")
        else:
            print("  - Нет товаров, требующих восстановления")
    except Exception as e:
        db.rollback()
        print(f"ERROR migrate_fix_previous_price: {e}")


def migrate_create_price_history(db):
    """
    Создать таблицу price_history и заполнить начальными данными.
    Одна запись на день для каждого (product_id, store_code).
    """
    from datetime import date
    from src.server.models import PriceHistory, Product
    from sqlalchemy import inspect as sa_inspect

    try:
        print("Миграция: создание таблицы price_history...")

        # 1. Создать таблицу если не существует
        PriceHistory.__table__.create(engine, checkfirst=True)

        # 2. Проверить, есть ли данные
        count = db.query(PriceHistory).count()
        if count > 0:
            print(f"  - В price_history уже есть {count} записей, заполнение пропущено")
            return

        # 3. Заполнить начальными данными из текущих products (за сегодня)
        today = date.today()
        products = db.query(Product).all()
        if not products:
            print("  - Нет товаров в products для заполнения истории")
            return

        rows = [
            {
                "product_id": p.product_id,
                "store_code": p.store_code,
                "price": p.price,
                "quantity": p.quantity,
                "in_stock": p.in_stock,
                "scan_date": today,
            }
            for p in products
        ]
        db.bulk_insert_mappings(PriceHistory, rows)
        db.commit()
        print(f"  + Заполнено {len(rows)} начальных записей в price_history за {today}")
    except Exception as e:
        db.rollback()
        print(f"ERROR migrate_create_price_history: {e}")
        import traceback
        traceback.print_exc()
