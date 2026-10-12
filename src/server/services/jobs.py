"""
Жизненный цикл фоновых заданий (ScanJob): финализация статуса и очистка при старте.
"""

import logging
from datetime import datetime

from sqlalchemy.orm import Session

from src.server.models import ScanJob

logger = logging.getLogger(__name__)


def finalize_job(db: Session, job_id: int, status: str, **fields) -> bool:
    """
    Перевести задание в итоговый статус, не затирая отмену.

    Статус `cancelled` — окончательный: отмена приходит из другой сессии
    (POST /api/jobs/{id}/cancel), поэтому перед записью задание перечитывается
    из БД. Если оно уже отменено, ничего не меняется.

    Args:
        db: сессия фоновой задачи
        job_id: ID задания
        status: новый статус (completed / failed)
        **fields: дополнительные поля ScanJob (items_scanned, error_message, ...)

    Returns:
        True — статус записан, False — задание не найдено или уже отменено.
    """
    # Завершаем текущую транзакцию, чтобы увидеть изменения из других сессий
    db.commit()
    job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
    if job is None:
        return False
    db.refresh(job)
    if job.status == "cancelled":
        return False

    job.status = status
    job.finished_at = datetime.utcnow()
    for key, value in fields.items():
        setattr(job, key, value)
    db.commit()
    return True


def mark_unfinished_jobs_failed(db: Session) -> int:
    """
    При старте сервера пометить все pending/running задания как failed
    (процесс был остановлен, фоновая работа потеряна).

    Returns:
        Количество помеченных заданий.
    """
    stale_jobs = (
        db.query(ScanJob).filter(ScanJob.status.in_(["pending", "running"])).all()
    )
    for job in stale_jobs:
        job.status = "failed"
        job.error_message = "Сервер был перезапущен, задание прервано"
        job.finished_at = datetime.utcnow()
    if stale_jobs:
        db.commit()
        logger.info(f"Помечено как failed: {len(stale_jobs)} зависших заданий")
    return len(stale_jobs)
