"""
Маршруты для работы с категориями и товарами.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session
from typing import Optional

from src.server.database import get_db
from src.server.models import Category, Product

router = APIRouter(prefix="/api", tags=["Каталог"])


@router.get("/categories")
def list_categories(
    tracked: Optional[bool] = Query(None),
    parent_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """Список универсальных категорий с фильтрацией."""
    query = db.query(Category)
    if tracked is not None:
        query = query.filter(Category.is_tracked == tracked)
    if parent_id is not None:
        query = query.filter(Category.parent_id == parent_id)
    elif parent_id is None and tracked is None:
        # Только если не указаны оба параметра, фильтруем по корневым
        query = query.filter(Category.parent_id.is_(None))
    categories = query.order_by(Category.name).all()
    return [
        {
            "id": c.id,
            "code": c.code,
            "name": c.name,
            "url": c.url,
            "parent_id": c.parent_id,
            "is_tracked": c.is_tracked,
            "product_count": c.product_count,
            "last_scanned": c.last_scanned.isoformat() if c.last_scanned else None,
        }
        for c in categories
    ]


@router.post("/categories/scan")
def scan_categories(
    store_code: str = Query(..., description="Код магазина-источника"),
    db: Session = Depends(get_db),
):
    """
    Сканировать категории каталога (синхронно).
    Категории извлекаются через API MagnitAPIClient.
    """
    from src.server.services.catalog_scanner import CatalogScanner

    scanner = CatalogScanner(db, store_code=store_code)
    try:
        result = scanner.scan_categories()
        scanner.close()
        return {"status": "completed", **result}
    except Exception as e:
        scanner.close()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/categories/tree")
def get_categories_tree(db: Session = Depends(get_db)):
    """Получить дерево категорий с подкатегориями."""
    root_categories = (
        db.query(Category)
        .filter(Category.parent_id.is_(None))
        .order_by(Category.name)
        .all()
    )

    def build_tree(category):
        children = (
            db.query(Category)
            .filter(Category.parent_id == category.id)
            .order_by(Category.name)
            .all()
        )
        return {
            "id": category.id,
            "code": category.code,
            "name": category.name,
            "url": category.url,
            "is_tracked": category.is_tracked,
            "product_count": category.product_count,
            "children": [build_tree(child) for child in children],
        }

    return [build_tree(cat) for cat in root_categories]


@router.post("/categories/load-from-json")
def load_categories_from_json(db: Session = Depends(get_db)):
    """
    Загрузить категории из файла magnit_catalog.json.
    """
    from src.server.services.load_catalog_from_json import load_catalog_from_json

    try:
        result = load_catalog_from_json()
        return {"status": "completed", **result}
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail="Файл magnit_catalog.json не найден"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/categories/build-from-playwright")
def build_categories_from_playwright(
    db: Session = Depends(get_db),
):
    """
    Загрузить категории из файла magnit_catalog.json (алиас).
    """
    return load_categories_from_json(db)


@router.post("/categories/seed-from-playwright")
def seed_categories(db: Session = Depends(get_db)):
    """
    Заполнить категории данными из magnit_catalog.json (альтернативный эндпоинт).
    """
    return build_categories_from_playwright(db)


@router.put("/categories/{category_id}/track")
def toggle_category_tracking(
    category_id: int,
    track: bool = Query(True, description="True = отслеживать, False = не отслеживать"),
    db: Session = Depends(get_db),
):
    """Включить/выключить отслеживание категории."""
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Категория не найдена")

    category.is_tracked = track
    db.commit()
    db.refresh(category)

    return {
        "id": category.id,
        "code": category.code,
        "name": category.name,
        "is_tracked": category.is_tracked,
    }


@router.post("/categories/update-tracking")
def update_categories_tracking(
    category_ids: list[int] = Body(..., embed=True),
    db: Session = Depends(get_db),
):
    """Обновить отслеживание для списка категорий (включить выбранные, выключить остальные)."""
    # Сначала выключаем все
    db.query(Category).update({"is_tracked": False})

    # Включаем выбранные
    if category_ids:
        db.query(Category).filter(Category.id.in_(category_ids)).update(
            {"is_tracked": True}, synchronize_session=False
        )

    db.commit()

    tracked_count = db.query(Category).filter(Category.is_tracked == True).count()
    return {
        "status": "success",
        "tracked_count": tracked_count,
        "updated_ids": category_ids,
    }


@router.get("/products", response_model=list[dict])
def list_products(
    store_code: Optional[str] = Query(None),
    category_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    min_price: Optional[float] = Query(None),
    max_price: Optional[float] = Query(None),
    sort_by: str = Query("name", pattern="^(name|price|discount|last_seen)$"),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: Session = Depends(get_db),
):
    """Список товаров с фильтрацией и сортировкой."""
    query = db.query(Product)
    if store_code:
        query = query.filter(Product.store_code == store_code)
    if category_id:
        query = query.filter(Product.category_id == category_id)
    if search:
        query = query.filter(Product.name.like(f"%{search}%"))
    if min_price is not None:
        query = query.filter(Product.price >= min_price)
    if max_price is not None:
        query = query.filter(Product.price <= max_price)

    if sort_by == "price":
        query = query.order_by(Product.price.asc())
    elif sort_by == "discount":
        query = query.filter(Product.old_price.isnot(None)).order_by(
            Product.price.asc()
        )
    elif sort_by == "last_seen":
        query = query.order_by(Product.last_seen.desc())
    else:
        query = query.order_by(Product.name.asc())

    products = query.offset(offset).limit(limit).all()

    result = []
    for p in products:
        discount = None
        if p.old_price and p.old_price > 0:
            discount = round((p.old_price - p.price) / p.old_price * 100, 1)
        result.append(
            {
                "product_id": p.product_id,
                "name": p.name,
                "price": p.price,
                "old_price": p.old_price,
                "discount_percent": discount,
                "currency": p.currency,
                "unit": p.unit,
                "image_url": p.image_url,
                "in_stock": p.in_stock,
                "category_id": p.category_id,
                "store_code": p.store_code,
                "last_seen": p.last_seen.isoformat() if p.last_seen else None,
            }
        )
    return result


@router.get("/products/{product_id}", response_model=dict)
def get_product(
    product_id: int,
    store_code: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Детали конкретного товара."""
    query = db.query(Product).filter(Product.product_id == product_id)
    if store_code:
        query = query.filter(Product.store_code == store_code)
    product = query.first()
    if not product:
        raise HTTPException(status_code=404, detail="Товар не найден")

    discount = None
    if product.old_price and product.old_price > 0:
        discount = round(
            (product.old_price - product.price) / product.old_price * 100, 1
        )

    return {
        "product_id": product.product_id,
        "name": product.name,
        "price": product.price,
        "old_price": product.old_price,
        "discount_percent": discount,
        "currency": product.currency,
        "unit": product.unit,
        "image_url": product.image_url,
        "in_stock": product.in_stock,
        "category_id": product.category_id,
        "store_code": product.store_code,
        "first_seen": product.first_seen.isoformat() if product.first_seen else None,
        "last_seen": product.last_seen.isoformat() if product.last_seen else None,
        "last_price_change": product.last_price_change.isoformat()
        if product.last_price_change
        else None,
    }


@router.post("/catalog/scan")
def scan_products(
    store_code: str = Query(..., description="Код магазина"),
    category_ids: Optional[str] = Query(
        None, description="Список ID категорий через запятую"
    ),
    tracked_only: bool = Query(True, description="Только отслеживаемые категории"),
    db: Session = Depends(get_db),
):
    """Сканировать товары из категорий (синхронно)."""
    from src.server.services.catalog_scanner import CatalogScanner

    cat_ids = None
    if category_ids:
        try:
            cat_ids = [int(x.strip()) for x in category_ids.split(",")]
        except ValueError:
            raise HTTPException(status_code=400, detail="Неверный формат category_ids")

    scanner = CatalogScanner(db, store_code=store_code)
    try:
        result = scanner.scan_products(category_ids=cat_ids, tracked_only=tracked_only)
        scanner.close()
        return {"status": "completed", **result}
    except Exception as e:
        scanner.close()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/catalog/scan-prices")
def scan_prices_in_store(
    store_code: str = Query(..., description="Код магазина для сканирования цен"),
    db: Session = Depends(get_db),
):
    """
    Обновить цены для отслеживаемых товаров в указанном магазине.
    Сканирует все отслеживаемые категории и обновляет цены/товары.
    """
    from src.server.services.catalog_scanner import CatalogScanner

    tracked_cats = db.query(Category).filter(Category.is_tracked == True).all()  # noqa: E712
    if not tracked_cats:
        raise HTTPException(status_code=400, detail="Нет отслеживаемых категорий")

    cat_ids = [cat.category_id for cat in tracked_cats]

    scanner = CatalogScanner(db, store_code=store_code)
    try:
        result = scanner.scan_products(category_ids=cat_ids, tracked_only=False)
        scanner.close()
        return {"status": "completed", **result}
    except Exception as e:
        scanner.close()
        raise HTTPException(status_code=500, detail=str(e))
