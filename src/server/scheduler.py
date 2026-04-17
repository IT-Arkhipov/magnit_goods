"""
Планировщик фоновых задач через APScheduler.
Автоматическое обновление цен, сканирование каталога.
"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session
from datetime import datetime
import logging

from src.server.database import SessionLocal
from src.server.models import ScanJob, Category
from src.server.services.catalog_scanner import CatalogScanner
from src.server.services.price_tracker import PriceTracker
from src.server.services.notifications import NotificationService

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def update_prices_job(store_code: str, category_ids: list[int] = None):
    """
    Задание: обновление цен для отслеживаемых товаров.
    Запускается ежедневно.
    """
    db = SessionLocal()
    job_id = None

    try:
        logger.info(f"[Scheduler] Запуск обновления цен для магазина {store_code}")

        # Создаём запись о задании
        job = ScanJob(
            job_type="prices",
            store_code=store_code,
            category_ids=str(category_ids) if category_ids else None,
            status="running",
            started_at=datetime.utcnow(),
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        job_id = job.id

        # Сканируем товары
        scanner = CatalogScanner(db, store_code=store_code, job_id=job_id)
        result = scanner.scan_products(
            category_ids=category_ids,
            tracked_only=True,
        )

        # Обновляем задание
        job.status = "completed"
        job.finished_at = datetime.utcnow()
        job.items_scanned = result["scanned"]
        job.items_added = result["added"]
        job.items_updated = result["updated"]
        db.commit()

        # Генерируем уведомления
        tracker = PriceTracker(db, store_code)
        alerts = tracker.get_alerts(min_discount_percent=10.0, days=1)
        logger.info(f"[Scheduler] Обновление цен завершено. Уведомления: {len(alerts)}")

        scanner.close()

    except Exception as e:
        logger.error(f"[Scheduler] Ошибка обновления цен: {e}")
        if job_id:
            job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
            if job:
                job.status = "failed"
                job.error_message = str(e)
                job.finished_at = datetime.utcnow()
                db.commit()
    finally:
        db.close()


def scan_catalog_job(store_code: str):
    """
    Задание: полное сканирование каталога.
    Запускается еженедельно.
    """
    db = SessionLocal()
    job_id = None

    try:
        logger.info(
            f"[Scheduler] Запуск сканирования каталога для магазина {store_code}"
        )

        # Сканируем категории
        job_categories = ScanJob(
            job_type="catalog",
            store_code=store_code,
            status="running",
            started_at=datetime.utcnow(),
        )
        db.add(job_categories)
        db.commit()
        db.refresh(job_categories)

        scanner = CatalogScanner(db, store_code=store_code, job_id=job_categories.id)
        cat_result = scanner.scan_categories()

        job_categories.status = "completed"
        job_categories.finished_at = datetime.utcnow()
        job_categories.items_scanned = cat_result["scanned"]
        job_categories.items_added = cat_result["added"]
        db.commit()

        logger.info(f"[Scheduler] Категории: {cat_result}")

        # Сканируем товары из отслеживаемых категорий
        job_products = ScanJob(
            job_type="prices",
            store_code=store_code,
            status="running",
            started_at=datetime.utcnow(),
        )
        db.add(job_products)
        db.commit()
        db.refresh(job_products)

        scanner = CatalogScanner(db, store_code=store_code, job_id=job_products.id)
        prod_result = scanner.scan_products(tracked_only=True)

        job_products.status = "completed"
        job_products.finished_at = datetime.utcnow()
        job_products.items_scanned = prod_result["scanned"]
        job_products.items_added = prod_result["added"]
        job_products.items_updated = prod_result["updated"]
        db.commit()

        logger.info(f"[Scheduler] Товары: {prod_result}")

        scanner.close()

    except Exception as e:
        logger.error(f"[Scheduler] Ошибка сканирования каталога: {e}")
        if job_id:
            job = db.query(ScanJob).filter(ScanJob.id == job_id).first()
            if job:
                job.status = "failed"
                job.error_message = str(e)
                job.finished_at = datetime.utcnow()
                db.commit()
    finally:
        db.close()


def generate_daily_report_job(store_code: str):
    """
    Задание: генерация ежедневного отчёта.
    """
    db = SessionLocal()
    try:
        notifier = NotificationService(db, store_code)
        report = notifier.generate_daily_report()
        logger.info(f"[Scheduler] Ежедневный отчёт: {report['summary']}")
    except Exception as e:
        logger.error(f"[Scheduler] Ошибка генерации отчёта: {e}")
    finally:
        db.close()


def init_scheduler(store_code: str):
    """
    Инициализировать планировщик с заданиями.

    Args:
        store_code: Код магазина для которого запускаем задания
    """
    if scheduler.running:
        logger.info("[Scheduler] Планировщик уже запущен")
        return

    logger.info(f"[Scheduler] Инициализация планировщика для магазина {store_code}")

    # Получаем отслеживаемые категории
    db = SessionLocal()
    try:
        tracked_categories = (
            db.query(Category)
            .filter(
                Category.is_tracked == True,  # noqa: E712
            )
            .all()
        )
        category_ids = (
            [cat.id for cat in tracked_categories] if tracked_categories else None
        )
    finally:
        db.close()

    # Обновление цен — каждый день в 8:00
    scheduler.add_job(
        update_prices_job,
        CronTrigger(hour=8, minute=0),
        args=[store_code, category_ids],
        id="update_prices",
        name="Обновление цен",
        replace_existing=True,
    )

    # Сканирование каталога — каждое воскресенье в 6:00
    scheduler.add_job(
        scan_catalog_job,
        CronTrigger(day_of_week="sun", hour=6, minute=0),
        args=[store_code],
        id="scan_catalog",
        name="Сканирование каталога",
        replace_existing=True,
    )

    # Ежедневный отчёт — каждый день в 20:00
    scheduler.add_job(
        generate_daily_report_job,
        CronTrigger(hour=20, minute=0),
        args=[store_code],
        id="daily_report",
        name="Ежедневный отчёт",
        replace_existing=True,
    )

    scheduler.start()
    logger.info("[Scheduler] Планировщик запущен")


def shutdown_scheduler():
    """Остановить планировщик."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("[Scheduler] Планировщик остановлен")
