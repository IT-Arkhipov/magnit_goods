"""
Маршруты для работы с ценами, историей и уведомлениями.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime

from server.database import get_db
from server.models import ScanJob
from server.schemas import ScanJobResponse

router = APIRouter(prefix="/api/prices", tags=["Цены"])


@router.get("/decreased", response_model=list[dict])
def get_decreased_prices(
    store_code: Optional[str] = Query(None),
    category_id: Optional[int] = Query(None),
    min_discount_percent: float = Query(0.0, description="Минимальный процент скидки"),
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
):
    """Товары со сниженными ценами."""
    from server.services.price_tracker import PriceTracker

    if not store_code:
        raise HTTPException(status_code=400, detail="Необходимо указать store_code")

    tracker = PriceTracker(db, store_code)
    return tracker.get_decreased_prices(
        category_id=category_id,
        min_discount_percent=min_discount_percent,
        limit=limit,
    )


@router.get("/increased", response_model=list[dict])
def get_increased_prices(
    store_code: Optional[str] = Query(None),
    category_id: Optional[int] = Query(None),
    limit: int = Query(100, le=500),
    db: Session = Depends(get_db),
):
    """Товары с выросшими ценами."""
    from server.services.price_tracker import PriceTracker

    if not store_code:
        raise HTTPException(status_code=400, detail="Необходимо указать store_code")

    tracker = PriceTracker(db, store_code)
    return tracker.get_increased_prices(
        category_id=category_id,
        limit=limit,
    )


@router.get("/alerts", response_model=list[dict])
def get_price_alerts(
    store_code: Optional[str] = Query(None),
    min_discount_percent: float = Query(10.0, description="Минимальный процент изменения"),
    days: int = Query(7, description="За сколько дней показывать"),
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db),
):
    """Уведомления о значительных изменениях цен."""
    from server.services.price_tracker import PriceTracker

    if not store_code:
        raise HTTPException(status_code=400, detail="Необходимо указать store_code")

    tracker = PriceTracker(db, store_code)
    return tracker.get_alerts(
        min_discount_percent=min_discount_percent,
        days=days,
        limit=limit,
    )


@router.get("/statistics", response_model=dict)
def get_statistics(
    store_code: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Общая статистика по изменениям цен."""
    from server.services.price_tracker import PriceTracker

    if not store_code:
        raise HTTPException(status_code=400, detail="Необходимо указать store_code")

    tracker = PriceTracker(db, store_code)
    return tracker.get_statistics()


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
    from server.services.catalog_scanner import CatalogScanner

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


@router.get("/report/daily", response_model=dict)
def get_daily_report(
    store_code: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Ежедневный отчёт об изменениях цен."""
    from server.services.notifications import NotificationService

    if not store_code:
        raise HTTPException(status_code=400, detail="Необходимо указать store_code")

    notifier = NotificationService(db, store_code)
    return notifier.generate_daily_report()


@router.get("/history/{product_id}", response_model=dict)
def get_product_price_history(
    product_id: int,
    store_code: Optional[str] = Query(None),
    days: int = Query(30, description="Кол-во дней истории"),
    db: Session = Depends(get_db),
):
    """История цен конкретного товара."""
    from server.services.price_tracker import PriceTracker

    if not store_code:
        raise HTTPException(status_code=400, detail="Необходимо указать store_code")

    tracker = PriceTracker(db, store_code)
    history = tracker.get_price_history(product_id, days)

    if not history:
        raise HTTPException(status_code=404, detail="Товар не найден")

    return history
