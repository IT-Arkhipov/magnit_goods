from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from server.database import get_db
from server.models import ScanJob
from server.schemas import ScanJobResponse

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


@router.get("/{job_id}", response_model=ScanJobResponse)
def get_job(job_id: int, db: Session = Depends(get_db)):
    """Статус конкретного задания."""
    job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Задание не найдено")
    return job
