import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

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
    from src.server.models import Store, Category, Product, PriceHistory, ScanJob  # noqa: F401
    Base.metadata.create_all(bind=engine)
