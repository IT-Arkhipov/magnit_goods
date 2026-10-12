"""
Маршруты для работы с ценами.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime

from src.server.database import get_db
from src.server.models import ScanJob, Product
from src.server.schemas import DecreasedPriceItem
from src.server.services.catalog_scanner import AmbiguousStoreError, resolve_store_type
from src.server.services.jobs import finalize_job

router = APIRouter(prefix="/api/prices", tags=["Цены"])


@router.get("/decreased", response_model=list[DecreasedPriceItem])
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
            # Не уведомлять о скидках на товары, которых уже нет в магазине
            # (API перестал их возвращать в последнем скане → in_stock=False).
            Product.in_stock == True,  # noqa: E712
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
    store_type: Optional[str] = Query(
        None, description="Тип магазина (обязателен, если у кода магазина в БД несколько типов)"
    ),
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

    # Тип магазина определяем до создания задания: неоднозначный код → 400, а не упавшее задание
    try:
        resolved_store_type = resolve_store_type(db, store_code, store_type)
    except AmbiguousStoreError as e:
        raise HTTPException(status_code=400, detail=str(e))

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
    job_id = job.id

    def run_update():
        from src.server.database import SessionLocal
        bg_db = SessionLocal()
        try:
            job_db = bg_db.query(ScanJob).filter(ScanJob.id == job_id).first()
            # Отменено ещё до запуска — статус `cancelled` окончательный
            if not job_db or job_db.status == "cancelled":
                return
            job_db.status = "running"
            job_db.started_at = datetime.utcnow()
            bg_db.commit()

            try:
                scanner = CatalogScanner(
                    bg_db, store_code=store_code, store_type=resolved_store_type, job_id=job_id
                )
                result = scanner.scan_products(
                    category_ids=cat_ids,
                    tracked_only=tracked_only,
                )
                scanner.close()

                finalize_job(
                    bg_db, job_id, "completed",
                    items_scanned=result["scanned"],
                    items_added=result["added"],
                    items_updated=result["updated"],
                )
            except Exception as e:
                finalize_job(bg_db, job_id, "failed", error_message=str(e))
        finally:
            bg_db.close()

    if background_tasks:
        background_tasks.add_task(run_update)
        return {"job_id": job.id, "status": "pending"}
    else:
        run_update()
        return {"job_id": job.id, "status": "completed"}
