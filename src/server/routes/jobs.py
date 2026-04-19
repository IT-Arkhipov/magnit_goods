from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime

from src.server.database import get_db
from src.server.models import ScanJob
from src.server.schemas import ScanJobResponse

router = APIRouter(prefix="/api/jobs", tags=["Задания"])


@router.get("", response_model=list[ScanJobResponse])
def list_jobs(
    job_type: str | None = None,
    status: str | None = None,
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """Список заданий на сканирование."""
    q = db.query(ScanJob)
    if job_type:
        q = q.filter(ScanJob.job_type == job_type)
    if status:
        q = q.filter(ScanJob.status == status)
    return q.order_by(ScanJob.created_at.desc()).limit(limit).all()


@router.get("/active", response_model=list[ScanJobResponse])
def get_active_jobs(
    job_type: str | None = None,
    db: Session = Depends(get_db),
):
    """Список активных заданий (pending или running)."""
    q = db.query(ScanJob).filter(ScanJob.status.in_(["pending", "running"]))
    if job_type:
        q = q.filter(ScanJob.job_type == job_type)
    return q.order_by(ScanJob.created_at.desc()).all()


@router.get("/{job_id}", response_model=ScanJobResponse)
def get_job(job_id: int, db: Session = Depends(get_db)):
    """Статус конкретного задания."""
    job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Задание не найдено")
    return job


@router.post("/{job_id}/cancel")
def cancel_job(job_id: int, db: Session = Depends(get_db)):
    """Отменить задание."""
    job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Задание не найдено")
    print(f"DEBUG cancel: job_id={job_id}, status={job.status}")
    if job.status == "cancelled":
        return {"status": "cancelled", "message": "Уже отменено"}
    if job.status in ["completed", "failed"]:
        raise HTTPException(status_code=400, detail=f"Задание уже завершено (статус: {job.status})")
    job.status = "cancelled"
    job.finished_at = datetime.utcnow()
    job.error_message = "Отменено пользователем"
    db.commit()
    return {"status": "cancelled"}
