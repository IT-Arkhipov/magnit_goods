from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    Boolean,
    DateTime,
    Date,
    Text,
    ForeignKey,
)
from sqlalchemy.orm import relationship
from datetime import datetime
import hashlib

from src.server.database import Base


def store_hash_id(store_code: str, store_type: str, full_address: str) -> str:
    """Генерирует хэш-идентификатор магазина."""
    raw = f"{store_code}|{store_type}|{full_address}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


class Store(Base):
    """Магазин Магнит."""

    __tablename__ = "stores"

    id = Column(
        String(12), primary_key=True
    )  # хэш из store_code + store_type + full_address
    store_code = Column(String, nullable=False, index=True)
    store_type = Column(String, nullable=False, index=True)
    shop_type = Column(Integer, nullable=True, index=True)  # Числовой код типа магазина
    city = Column(String, nullable=False, index=True)
    address = Column(String, nullable=False)
    full_address = Column(String, nullable=False)
    name = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    STORE_TYPE_TO_SHOP_TYPE = {
        "Магнит": 1,
        "Мини": 2,
        "М.Косметик": 3,
        "Семейный": 5,
        "Экстра": 6,
        "Опт": 7,
        "Заряд": 8,
        "Моя цена": 9,
    }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not kwargs.get("id") and self.store_code and self.store_type and self.full_address:
            self.id = store_hash_id(self.store_code, self.store_type, self.full_address)
        if not kwargs.get("shop_type") and self.store_type:
            self.shop_type = self.STORE_TYPE_TO_SHOP_TYPE.get(self.store_type)


class Category(Base):
    """Категория каталога (универсальная, без привязки к магазину)."""

    __tablename__ = "categories"

    id = Column(Integer, primary_key=True, index=True)
    magnit_id = Column(Integer, nullable=True, index=True)  # ID из API Магнита
    name = Column(String, nullable=False)
    url = Column(String, nullable=False)
    parent_id = Column(Integer, ForeignKey("categories.id"), nullable=True, index=True)
    is_tracked = Column(Boolean, default=False, index=True)
    product_count = Column(Integer, default=0)
    last_scanned = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    children = relationship("Category", backref="parent", remote_side=[id])

    def __repr__(self):
        return f"<Category id={self.id} magnit_id={self.magnit_id} name={self.name}>"


class Product(Base):
    """Товар (текущее состояние)."""

    __tablename__ = "products"

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, nullable=False)
    name = Column(String, nullable=False)
    sku = Column(String, nullable=True)
    category_id = Column(Integer, ForeignKey("categories.id"), nullable=True, index=True)
    store_code = Column(String, nullable=False, index=True)
    
    # Relationships
    category = relationship("Category", backref="products")

    price = Column(Float, nullable=False, index=True)
    currency = Column(String, default="₽")
    unit = Column(String, nullable=True)
    image_url = Column(String, nullable=True)
    in_stock = Column(Boolean, default=True)

    # Остатки и доступность
    quantity = Column(Integer, default=0)  # Остаток на складе
    is_low_stock = Column(Boolean, nullable=True)  # Мало ли осталось
    pickup_only = Column(Boolean, default=False)  # Только самовывоз

    # Рейтинги и отзывы
    rating = Column(Float, nullable=True)  # Рейтинг товара
    scores_count = Column(Integer, default=0)  # Кол-во оценок
    comments_count = Column(Integer, default=0)  # Кол-во отзывов

    # SEO и каталог
    seo_code = Column(String, nullable=True)  # SEO-слаг
    service = Column(String, nullable=True)  # Сервис (core_mm, etc.)
    catalog_type = Column(String, nullable=True)  # Тип каталога

    # Параметры заказа
    min_order_qty = Column(Integer, default=1)  # Минимальное кол-во
    order_step_qty = Column(Integer, default=1)  # Шаг заказа

    # Весовые товары
    is_weighted = Column(Boolean, default=False)  # Весовой ли товар
    unit_price = Column(Float, nullable=True)  # Цена за кг/л

    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)
    last_price_change = Column(DateTime, nullable=True)
    last_scan_found = Column(DateTime, nullable=True)  # Дата последнего сканирования, когда товар был найден

    # Отслеживание цен
    previous_price = Column(Float, nullable=True)  # Предыдущая цена (из предыдущего сканирования)
    price_change_percent = Column(Float, nullable=True, index=True)  # Процент изменения (+ снижение, - повышение)


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

    total_stores = Column(Integer, default=0)
    current_store_index = Column(Integer, default=0)
    current_store_code = Column(String, nullable=True)
    current_store_address = Column(String, nullable=True)
    total_categories = Column(Integer, default=0)
    current_category_index = Column(Integer, default=0)
    current_category_name = Column(String, nullable=True)
    current_category_magnit_id = Column(Integer, nullable=True)
    current_category_items_total = Column(Integer, default=0)
    current_category_items_loaded = Column(Integer, default=0)
