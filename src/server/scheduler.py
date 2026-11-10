"""
Планировщик фоновых задач через APScheduler.

Задания делают то же, что кнопки в UI: сканирование всех активных магазинов
(как «Сканировать все магазины») и полная замена каталога категорий
(как «Обновить каталог»). Магазины и отслеживаемые категории читаются
в момент запуска задания.
"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import logging

from src.server.database import SessionLocal
from src.server.services.catalog_updater import run_catalog_update, try_begin_catalog_update
from src.server.models import ScanJob
from src.server.services.store_scan import (
    SCAN_ALL_STORES_JOB_TYPE,
    NothingToScanError,
    create_scan_all_stores_job,
    run_scan_all_stores,
)

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def scan_all_stores_job():
    """Задание: сканирование всех активных магазинов. Ежедневно."""
    db = SessionLocal()
    try:
        # Скан, запущенный из UI или прошлым запуском, ещё идёт — второй не нужен
        active = db.query(ScanJob.id).filter(
            ScanJob.job_type == SCAN_ALL_STORES_JOB_TYPE,
            ScanJob.status.in_(["pending", "running"]),
        ).first()
        if active:
            logger.info(f"[Scheduler] Сканирование уже идёт (задание {active[0]}) — пропущено")
            return
        job_id = create_scan_all_stores_job(db)
    except NothingToScanError as e:
        logger.info(f"[Scheduler] Сканирование магазинов пропущено: {e}")
        return
    finally:
        db.close()

    logger.info(f"[Scheduler] Сканирование всех магазинов, задание {job_id}")
    run_scan_all_stores(job_id)


def update_catalog_job():
    """Задание: полная замена каталога категорий. Еженедельно, до утреннего сканирования."""
    if not try_begin_catalog_update():
        logger.info("[Scheduler] Замена каталога уже идёт — пропущена")
        return
    stats = run_catalog_update()
    logger.info(f"[Scheduler] Каталог: {stats.get('status')}")


def init_scheduler():
    """Зарегистрировать задания и запустить планировщик (при старте приложения)."""
    # Сканирование всех магазинов — каждый день в 8:00
    scheduler.add_job(
        scan_all_stores_job,
        CronTrigger(hour=8, minute=0),
        id="scan_all_stores",
        name="Сканирование всех магазинов",
        replace_existing=True,
    )
    # Обновление каталога — каждое воскресенье в 6:00 (сканирование — в 8:00)
    scheduler.add_job(
        update_catalog_job,
        CronTrigger(day_of_week="sun", hour=6, minute=0),
        id="update_catalog",
        name="Обновление каталога",
        replace_existing=True,
    )
    if not scheduler.running:
        scheduler.start()
        logger.info("[Scheduler] Планировщик запущен")


def shutdown_scheduler():
    """Остановить планировщик."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("[Scheduler] Планировщик остановлен")
