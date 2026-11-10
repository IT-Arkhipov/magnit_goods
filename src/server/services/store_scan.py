"""
Сканирование всех активных магазинов по отслеживаемым категориям.

Одна реализация для кнопки «Сканировать все магазины» (POST /api/catalog/scan-all-stores)
и ежедневного задания планировщика: создание задания ScanJob и сам обход магазинов
с прогрессом и отменой.
"""

import json
import logging
from datetime import datetime

from sqlalchemy.orm import Session

from src.server.database import SessionLocal
from src.server.models import Category, ScanJob, Store
from src.server.services.catalog_scanner import CatalogScanner, get_tracked_category_magnit_ids
from src.server.services.jobs import finalize_job

logger = logging.getLogger(__name__)

SCAN_ALL_STORES_JOB_TYPE = "scan_all_stores"


class NothingToScanError(ValueError):
    """Нет активных магазинов или отслеживаемых категорий."""


def create_scan_all_stores_job(db: Session) -> int:
    """Создать задание сканирования всех активных магазинов (status=pending).

    Raises:
        NothingToScanError: нет активных магазинов или отслеживаемых категорий.
    """
    stores_count = db.query(Store).filter(Store.is_active.is_(True)).count()
    if not stores_count:
        raise NothingToScanError("Нет магазинов в БД")
    cat_codes = get_tracked_category_magnit_ids(db)
    if not cat_codes:
        raise NothingToScanError("Нет отслеживаемых категорий")

    job = ScanJob(
        job_type=SCAN_ALL_STORES_JOB_TYPE,
        store_code=f"{stores_count} stores",
        category_ids=json.dumps(cat_codes),
        status="pending",
        created_at=datetime.utcnow(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job.id


def run_scan_all_stores(job_id: int) -> None:
    """Выполнить задание сканирования всех магазинов (в своей сессии БД).

    Магазины и отслеживаемые категории читаются в момент запуска. Каждый магазин
    сканируется со своим типом одним вызовом сканера; ошибка магазина не прерывает
    остальные. Отмена (`cancelled`) проверяется между магазинами и внутри сканера.
    """
    db = SessionLocal()
    try:
        job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
        # Отменено ещё до запуска — статус `cancelled` окончательный
        if not job or job.status == "cancelled":
            return

        stores = [
            (s.store_code, s.store_type, s.full_address)
            for s in db.query(Store).filter(Store.is_active.is_(True)).all()
        ]
        cat_codes = get_tracked_category_magnit_ids(db)

        job.status = "running"
        job.started_at = datetime.utcnow()
        job.progress = 0
        job.progress_message = "Запуск..."
        db.commit()

        total_scanned = total_added = total_updated = 0
        total_stores = len(stores)
        total_categories = len(cat_codes)
        total_operations = total_stores * total_categories
        cat_name_map = {
            magnit_id: name
            for magnit_id, name in db.query(Category.magnit_id, Category.name)
            .filter(Category.magnit_id.in_(cat_codes))
            .all()
        }

        for idx, (store_code, store_type, address) in enumerate(stores):
            # commit завершает транзакцию — иначе в WAL виден старый снимок и отмена не заметна
            db.commit()
            status_row = db.query(ScanJob.status).filter(ScanJob.id == job_id).first()
            if status_row and status_row[0] == "cancelled":
                _set_job_fields(db, job_id, progress_message="Отменено пользователем")
                return

            _set_job_fields(
                db, job_id,
                total_stores=total_stores,
                current_store_index=idx + 1,
                current_store_code=store_code,
                current_store_address=address,
                total_categories=total_categories,
                progress_message=f"🏪 {store_code}: {address}<br>📁 Магазин {idx + 1}/{total_stores}",
            )

            try:
                scanner = CatalogScanner(
                    db, store_code=store_code, store_type=store_type,
                    address=address, job_id=job_id,
                )
                try:
                    def on_category_start(cat_index, _cat_total, cat_code, _idx=idx,
                                          _store_code=store_code, _address=address):
                        """Прогресс по позиции в (магазин × категория)."""
                        done = _idx * total_categories + (cat_index - 1)
                        pct = int(done / total_operations * 100) if total_operations else 0
                        _set_job_fields(
                            db, job_id,
                            current_category_index=cat_index,
                            current_category_name=cat_name_map.get(cat_code, f"ID:{cat_code}"),
                            current_category_magnit_id=cat_code,
                            progress=pct,
                            progress_message=(
                                f"🏪 {_store_code}: {(_address or '')[:30]}...<br>"
                                f"📁 Категория {done + 1}/{total_operations}"
                            ),
                        )

                    # Один вызов на магазин: очистка устаревших товаров, истории цен и
                    # пометка отсутствующих выполняются один раз, а не после каждой категории
                    result = scanner.scan_products(
                        category_ids=cat_codes, on_category_start=on_category_start
                    )
                finally:
                    scanner.close()

                # Сканер увидел отмену — дальше по категориям и магазинам не идём
                if result.get("cancelled"):
                    _set_job_fields(db, job_id, progress_message="Отменено пользователем")
                    return

                total_scanned += result.get("scanned", 0)
                total_added += result.get("added", 0)
                total_updated += result.get("updated", 0)
                done_pct = int((idx + 1) * total_categories / total_operations * 100) if total_operations else 0
                _set_job_fields(
                    db, job_id,
                    items_scanned=total_scanned,
                    items_added=total_added,
                    items_updated=total_updated,
                    progress=done_pct,
                )
            except Exception as e:
                db.rollback()
                logger.exception(f"Ошибка сканирования магазина {store_code}")
                _set_job_fields(db, job_id, progress_message=f"Ошибка {store_code}: {e}")

        # Если задание отменили во время скана — остаётся cancelled
        finalize_job(
            db, job_id, "completed",
            progress=100,
            progress_message="Завершено",
            items_scanned=total_scanned,
            items_added=total_added,
            items_updated=total_updated,
        )
    except Exception as e:
        logger.exception("Ошибка задания сканирования всех магазинов")
        db.rollback()
        finalize_job(
            db, job_id, "failed",
            error_message=str(e),
            progress_message=f"Ошибка: {e}",
        )
    finally:
        db.close()


def _set_job_fields(db: Session, job_id: int, **fields) -> None:
    """Записать поля прогресса задания одним UPDATE + commit."""
    db.query(ScanJob).filter(ScanJob.id == job_id).update(fields)
    db.commit()
