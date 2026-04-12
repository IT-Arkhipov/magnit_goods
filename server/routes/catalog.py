"""
Маршруты для работы с категориями и товарами.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime

from server.database import get_db
from server.models import Category, Product, ScanJob
from server.schemas import ScanJobResponse

router = APIRouter(prefix="/api", tags=["Каталог"])


@router.get("/categories", response_model=list[dict])
def list_categories(
    store_code: Optional[str] = Query(None),
    tracked: Optional[bool] = Query(None),
    parent_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """Список категорий с фильтрацией."""
    query = db.query(Category)

    if store_code:
        query = query.filter(Category.store_code == store_code)
    if tracked is not None:
        query = query.filter(Category.is_tracked == tracked)
    if parent_id is not None:
        query = query.filter(Category.parent_id == parent_id)
    else:
        # Показываем только корневые если parent_id не указан явно
        query = query.filter(Category.parent_id.is_(None))

    return query.order_by(Category.name).all()


@router.post("/categories/scan")
def scan_categories(
    store_code: str = Query(..., description="Код магазина"),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
):
    """
    Сканировать категории каталога (фоновая задача).
    """
    from server.services.catalog_scanner import CatalogScanner

    # Создаём задание
    job = ScanJob(
        job_type="catalog",
        store_code=store_code,
        status="pending",
        created_at=datetime.utcnow(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Запускаем фоновую задачу
    def run_scan():
        job_db = db.query(ScanJob).filter(ScanJob.id == job.id).first()
        if not job_db:
            return
        job_db.status = "running"
        job_db.started_at = datetime.utcnow()
        db.commit()

        try:
            scanner = CatalogScanner(db, store_code=store_code, job_id=job.id)
            result = scanner.scan_categories()
            scanner.close()

            job_db.status = "completed"
            job_db.finished_at = datetime.utcnow()
            job_db.items_scanned = result["scanned"]
            job_db.items_added = result["added"]
            job_db.items_updated = result["updated"]
            db.commit()
        except Exception as e:
            job_db.status = "failed"
            job_db.error_message = str(e)
            job_db.finished_at = datetime.utcnow()
            db.commit()

    if background_tasks:
        background_tasks.add_task(run_scan)
        return {"job_id": job.id, "status": "pending"}
    else:
        # Синхронный режим для тестирования
        run_scan()
        return {"job_id": job.id, "status": "completed"}


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
        "category_id": category.id,
        "name": category.name,
        "is_tracked": category.is_tracked,
    }


@router.get("/products", response_model=list[dict])
def list_products(
    store_code: Optional[str] = Query(None),
    category_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    min_price: Optional[float] = Query(None),
    max_price: Optional[float] = Query(None),
    sort_by: str = Query("name", regex="^(name|price|discount|last_seen)$"),
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

    # Сортировка
    if sort_by == "price":
        query = query.order_by(Product.price.asc())
    elif sort_by == "discount":
        # Товары со скидкой сначала
        query = query.filter(Product.old_price.isnot(None)).order_by(Product.price.asc())
    elif sort_by == "last_seen":
        query = query.order_by(Product.last_seen.desc())
    else:
        query = query.order_by(Product.name.asc())

    products = query.offset(offset).limit(limit).all()

    # Форматируем ответ
    result = []
    for p in products:
        discount = None
        if p.old_price and p.old_price > 0:
            discount = round((p.old_price - p.price) / p.old_price * 100, 1)

        result.append({
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
            "last_seen": p.last_seen.isoformat() if p.last_seen else None,
        })

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
        discount = round((product.old_price - product.price) / product.old_price * 100, 1)

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
        "first_seen": product.first_seen.isoformat() if product.first_seen else None,
        "last_seen": product.last_seen.isoformat() if product.last_seen else None,
        "last_price_change": product.last_price_change.isoformat() if product.last_price_change else None,
    }


@router.post("/catalog/scan")
def scan_products(
    store_code: str = Query(..., description="Код магазина"),
    category_ids: Optional[str] = Query(None, description="Список ID категорий через запятую"),
    tracked_only: bool = Query(True, description="Только отслеживаемые категории"),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
):
    """
    Сканировать товары из категорий (фоновая задача).
    """
    from server.services.catalog_scanner import CatalogScanner

    # Парсим category_ids
    cat_ids = None
    if category_ids:
        try:
            cat_ids = [int(x.strip()) for x in category_ids.split(",")]
        except ValueError:
            raise HTTPException(status_code=400, detail="Неверный формат category_ids")

    # Создаём задание
    job = ScanJob(
        job_type="prices",
        store_code=store_code,
        category_ids=str(cat_ids) if cat_ids else None,
        status="pending",
        created_at=datetime.utcnow(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    def run_scan():
        job_db = db.query(ScanJob).filter(ScanJob.id == job.id).first()
        if not job_db:
            return
        job_db.status = "running"
        job_db.started_at = datetime.utcnow()
        db.commit()

        try:
            scanner = CatalogScanner(db, store_code=store_code, job_id=job.id)
            result = scanner.scan_products(
                category_ids=cat_ids,
                tracked_only=tracked_only,
            )
            scanner.close()

            job_db.status = "completed"
            job_db.finished_at = datetime.utcnow()
            job_db.items_scanned = result["scanned"]
            job_db.items_added = result["added"]
            job_db.items_updated = result["updated"]
            db.commit()
        except Exception as e:
            job_db.status = "failed"
            job_db.error_message = str(e)
            job_db.finished_at = datetime.utcnow()
            db.commit()

    if background_tasks:
        background_tasks.add_task(run_scan)
        return {"job_id": job.id, "status": "pending"}
    else:
        run_scan()
        return {"job_id": job.id, "status": "completed"}
