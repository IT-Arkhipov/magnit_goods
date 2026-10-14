"""
Выборка товаров для API: фильтры, окно видимости устаревших и отсутствующих
товаров, поиск по названию, сортировка, пагинация, статистика.

Роуты только разбирают параметры запроса и вызывают эти функции — поэтому
обычный список и поиск проходят один путь и не могут разойтись в фильтрах.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import case, func
from sqlalchemy.orm import Query, Session, joinedload

from src.server.constants import STALE_DAYS_DELETE, STALE_DAYS_VISIBLE
from src.server.models import Product


@dataclass
class ProductFilters:
    """Параметры выборки товаров."""

    store_code: Optional[str] = None
    category_id: Optional[int] = None
    category_ids: list[int] = field(default_factory=list)
    min_price: Optional[float] = None
    max_price: Optional[float] = None
    search: Optional[str] = None
    # Расширить окно видимости устаревших товаров до STALE_DAYS_DELETE
    # (режим «Последнее изменение»)
    relax_stale: bool = False
    # Включить товары, которых нет в наличии (in_stock=False или остаток 0)
    include_out_of_stock: bool = False


def parse_category_ids(value: Optional[str]) -> list[int]:
    """'1, 2,abc,3' → [1, 2, 3] (нечисловые элементы отбрасываются)."""
    if not value:
        return []
    return [int(x.strip()) for x in value.split(",") if x.strip().isdigit()]


def _like_pattern(term: str) -> str:
    """Подстрока для LIKE ... ESCAPE '\\': спецсимволы %, _ и \\ — обычные символы."""
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def build_product_query(db: Session, filters: ProductFilters) -> Query:
    """Query товаров со всеми фильтрами (без сортировки и пагинации)."""
    q = db.query(Product).options(joinedload(Product.category))

    if filters.store_code:
        q = q.filter(Product.store_code == filters.store_code)
    if filters.category_id:
        q = q.filter(Product.category_id == filters.category_id)
    if filters.category_ids:
        q = q.filter(Product.category_id.in_(filters.category_ids))
    if filters.min_price is not None:
        q = q.filter(Product.price >= filters.min_price)
    if filters.max_price is not None:
        q = q.filter(Product.price <= filters.max_price)

    # Скрываем товары, которых не было в сканах дольше STALE_DAYS_VISIBLE дней.
    # Жизненный цикл устаревшего товара: STALE_DAYS_VISIBLE (видим) →
    # STALE_DAYS_HIDDEN (скрыт) → STALE_DAYS_DELETE (удалён).
    # При relax_stale=True (режим «Последнее изменение») расширяем окно до
    # STALE_DAYS_DELETE, чтобы показывать товары со снижением на старом скане.
    visible_days = STALE_DAYS_DELETE if filters.relax_stale else STALE_DAYS_VISIBLE
    visible_cutoff = datetime.utcnow().date() - timedelta(days=visible_days)
    q = q.filter(Product.last_seen >= visible_cutoff)

    # Скрываем отсутствующие товары: учитываем оба признака — in_stock=False
    # (API Магнита перестал возвращать товар) и quantity=0 (товар в каталоге,
    # но с нулевым остатком). Логика идентична validateShoppingList (base.html),
    # чтобы список товаров и список покупок не расходились в оценке наличия.
    if not filters.include_out_of_stock:
        q = q.filter(Product.in_stock.is_(True), Product.quantity > 0)

    # Поиск: SQLite LOWER() не работает с кириллицей, поэтому ищем по
    # name_search (name.casefold(), заполняется при сохранении товара).
    if filters.search and filters.search.strip():
        term = filters.search.casefold().strip()
        q = q.filter(Product.name_search.like(_like_pattern(term), escape="\\"))

    return q


def list_products(
    db: Session,
    filters: ProductFilters,
    sort_by: str = "name",
    limit: int = 100,
    offset: int = 0,
) -> list[Product]:
    """Товары по фильтрам с сортировкой и пагинацией."""
    query = build_product_query(db, filters)

    if sort_by == "price":
        query = query.order_by(Product.price.asc(), Product.name.asc())
    elif sort_by == "last_seen":
        query = query.order_by(Product.last_seen.desc(), Product.name.asc())
    else:
        query = query.order_by(Product.name.asc())

    return query.offset(offset).limit(limit).all()


def product_to_list_item(p: Product) -> dict:
    """Элемент ответа GET /api/products (контракт полей зафиксирован схемой ProductListItem)."""
    return {
        "product_id": p.product_id,
        "name": p.name,
        "price": p.price,
        "previous_price": p.previous_price,
        "price_change_percent": p.price_change_percent,
        "last_price_change": p.last_price_change.isoformat() if p.last_price_change else None,
        "last_change_price": p.last_change_price,
        "last_change_date": p.last_change_date.isoformat() if p.last_change_date else None,
        "currency": p.currency,
        "unit": p.unit,
        "image_url": p.image_url,
        "in_stock": p.in_stock,
        "category_id": p.category_id,
        "store_code": p.store_code,
        # Категория с информацией о родителе
        "category_name": p.category.name if p.category else None,
        "category_parent_id": p.category.parent_id if p.category else None,
        # Остатки
        "quantity": p.quantity,
        "is_low_stock": p.is_low_stock,
        "pickup_only": p.pickup_only,
        # Рейтинги
        "rating": p.rating,
        "scores_count": p.scores_count,
        "comments_count": p.comments_count,
        # SEO
        "seo_code": p.seo_code,
        # Весовые
        "is_weighted": p.is_weighted,
        "unit_price": p.unit_price,
        "first_seen": p.first_seen.isoformat() if p.first_seen else None,
        "last_seen": p.last_seen.isoformat() if p.last_seen else None,
    }


def get_products_stats(
    db: Session,
    store_codes: Optional[list[str]] = None,
) -> dict:
    """Сводная статистика товаров по набору магазинов (пустой набор — по всем).

    Все счётчики — по уникальным product_id: товар, продаваемый в нескольких
    магазинах набора, считается один раз. Одиночный магазин и вызов без
    магазина считаются теми же выражениями.
    """
    # «В наличии» — по тому же правилу, что и список товаров: in_stock и остаток > 0
    available = (Product.in_stock.is_(True)) & (Product.quantity > 0)

    def distinct_ids(condition):
        # product_id только для строк, подходящих под условие (иначе NULL)
        return func.count(func.distinct(case((condition, Product.product_id), else_=None)))

    query = db.query(
        func.count(func.distinct(Product.product_id)).label("total"),
        distinct_ids(available).label("in_stock"),
        # Снижение учитывается, только если товар в этом же магазине в наличии
        distinct_ids(available & (Product.price_change_percent > 0)).label("with_price_decrease"),
        distinct_ids(Product.price_change_percent < 0).label("with_price_increase"),
        func.max(Product.last_seen).label("last_update"),
    )
    if store_codes:
        query = query.filter(Product.store_code.in_(store_codes))
    row = query.one()

    return {
        "total": row.total or 0,
        "in_stock": row.in_stock or 0,
        "with_price_decrease": row.with_price_decrease or 0,
        "with_price_increase": row.with_price_increase or 0,
        "last_update": row.last_update.isoformat() if row.last_update else None,
    }
