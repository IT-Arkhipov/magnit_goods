"""
Маршруты для работы с ценами.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks, Body
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime, date, timedelta

from src.server.database import get_db
from src.server.models import ScanJob, Product
from src.server.schemas import ScanJobResponse

router = APIRouter(prefix="/api/prices", tags=["Цены"])


@router.get("/decreased", response_model=list[dict])
def get_decreased_prices(
    store_code: Optional[str] = Query(None),
    min_discount_percent: float = Query(10.0, description="Минимальный процент снижения"),
    limit: int = Query(50, le=500),
    db: Session = Depends(get_db),
):
    """Товары со сниженными ценами."""
    if not store_code:
        raise HTTPException(status_code=400, detail="Необходимо указать store_code")

    products = (
        db.query(Product)
        .filter(
            Product.store_code == store_code,
            Product.price_change_percent >= min_discount_percent,
            Product.last_price_change.isnot(None),
        )
        .order_by(Product.price_change_percent.desc())
        .limit(limit)
        .all()
    )

    return [
        {
            "product_id": p.product_id,
            "name": p.name,
            "price": p.price,
            "previous_price": p.previous_price,
            "change_percent": p.price_change_percent,
            "last_price_change": p.last_price_change.isoformat(),
            "image_url": p.image_url,
        }
        for p in products
    ]


@router.post("/update")
def update_prices(
    store_code: str = Query(..., description="Код магазина"),
    category_ids: Optional[str] = Query(None, description="Список ID категорий через запятую"),
    tracked_only: bool = Query(True),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
):
    """
    Обновить цены для отслеживаемых товаров (фоновая задача).
    """
    from src.server.services.catalog_scanner import CatalogScanner

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

    def run_update():
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
        background_tasks.add_task(run_update)
        return {"job_id": job.id, "status": "pending"}
    else:
        run_update()
        return {"job_id": job.id, "status": "completed"}
