from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Text, ForeignKey
)
from sqlalchemy.orm import relationship
from datetime import datetime

from src.server.database import Base


class Store(Base):
    """Магазин Магнит."""
    __tablename__ = "stores"

    id = Column(Integer, primary_key=True, index=True)
    store_code = Column(String, unique=True, nullable=False, index=True)
    store_type = Column(String, nullable=False, index=True)
    city = Column(String, nullable=False, index=True)
    address = Column(String, nullable=False)
    full_address = Column(String, nullable=False)
    name = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Category(Base):
    """Категория каталога товаров."""
    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    category_id = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    parent_id = Column(Integer, nullable=True)
    store_code = Column(String, nullable=False, index=True)
    is_tracked = Column(Boolean, default=False, index=True)
    product_count = Column(Integer, default=0)
    last_scanned = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class Product(Base):
    """Товар (текущее состояние)."""
    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    sku = Column(String, nullable=True)
    category_id = Column(Integer, nullable=True, index=True)
    store_code = Column(String, nullable=False, index=True)

    price = Column(Float, nullable=False, index=True)
    old_price = Column(Float, nullable=True)
    currency = Column(String, default="₽")
    unit = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    in_stock = Column(Boolean, default=True)

    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    last_price_change = Column(DateTime, nullable=True)


class PriceHistory(Base):
    """История изменений цен."""
    __tablename__ = "price_history"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, nullable=False, index=True)
    store_code = Column(String, nullable=False)
    price = Column(Float, nullable=False)
    old_price = Column(Float, nullable=True)
    recorded_at = Column(DateTime, default=datetime.utcnow, index=True)
    change_type = Column(String, nullable=True)


class ScanJob(Base):
    """Задание на сканирование."""
    __tablename__ = "scan_jobs"

    id = Column(Integer, primary_key=True, index=True)
    job_type = Column(String, nullable=False)
    store_code = Column(String, nullable=True)
    category_ids = Column(Text, nullable=True)
    status = Column(String, default="pending")
    progress = Column(Integer, default=0)
    progress_message = Column(String, nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    items_scanned = Column(Integer, default=0)
    items_added = Column(Integer, default=0)
    items_updated = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
