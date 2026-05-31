import os
from sqlalchemy import create_engine, text
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
    """Создать все таблицы при старте."""
    # Импортируем модели чтобы Base их знал
    from src.server.models import Store, Category, Product, ScanJob  # noqa: F401
    Base.metadata.create_all(bind=engine)
    
    # Выполняем миграции
    db = SessionLocal()
    try:
        migrate_simplify_price_tracking(db)
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
        except Exception as e:
            print(f"  - Поле previous_price уже существует")
        
        try:
            db.execute(text("ALTER TABLE products ADD COLUMN price_change_percent FLOAT"))
            print("  + Добавлено поле price_change_percent")
        except Exception as e:
            print(f"  - Поле price_change_percent уже существует")
        
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
            except Exception as e:
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
