"""
Планировщик фоновых задач через APScheduler.
Автоматическое обновление цен, сканирование каталога.
"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
import logging
import os

from src.server.database import SessionLocal
from src.server.models import ScanJob
from src.server.services.catalog_scanner import CatalogScanner
from src.server.services.jobs import finalize_job

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def _configured_store_type():
    """STORE_TYPE из окружения (его выставляет POST /api/stores/select) или None —
    тогда сканер определит тип по БД и откажется, если у кода несколько типов."""
    return os.getenv("STORE_TYPE") or None


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
        scanner = CatalogScanner(
            db, store_code=store_code, store_type=_configured_store_type(), job_id=job_id
        )
        result = scanner.scan_products(
            category_ids=category_ids,
            tracked_only=True,
        )

        # Обновляем задание (отменённое задание остаётся cancelled)
        if finalize_job(
            db, job_id, "completed",
            items_scanned=result["scanned"],
            items_added=result["added"],
            items_updated=result["updated"],
        ):
            logger.info("[Scheduler] Обновление цен завершено")
        else:
            logger.info("[Scheduler] Обновление цен отменено")

        scanner.close()

    except Exception as e:
        logger.error(f"[Scheduler] Ошибка обновления цен: {e}")
        if job_id:
            finalize_job(db, job_id, "failed", error_message=str(e))
    finally:
        db.close()


def scan_catalog_job(store_code: str):
    """
    Задание: полное сканирование каталога.
    Запускается еженедельно.
    """
    db = SessionLocal()

    try:
        logger.info(
            f"[Scheduler] Запуск сканирования каталога для магазина {store_code}"
        )

        # Фаза 1: сканируем категории
        job_categories = ScanJob(
            job_type="catalog",
            store_code=store_code,
            status="running",
            started_at=datetime.utcnow(),
        )
        db.add(job_categories)
        db.commit()
        db.refresh(job_categories)

        scanner = CatalogScanner(
            db, store_code=store_code, store_type=_configured_store_type(), job_id=job_categories.id
        )
        try:
            cat_result = scanner.scan_categories()
        except Exception as e:
            logger.error(f"[Scheduler] Ошибка сканирования категорий: {e}")
            finalize_job(db, job_categories.id, "failed", error_message=str(e))
            return
        finally:
            scanner.close()

        if not finalize_job(
            db, job_categories.id, "completed",
            items_scanned=cat_result["scanned"],
            items_added=cat_result["added"],
        ):
            logger.info("[Scheduler] Сканирование каталога отменено")
            return

        logger.info(f"[Scheduler] Категории: {cat_result}")

        # Фаза 2: сканируем товары из отслеживаемых категорий
        job_products = ScanJob(
            job_type="prices",
            store_code=store_code,
            status="running",
            started_at=datetime.utcnow(),
        )
        db.add(job_products)
        db.commit()
        db.refresh(job_products)

        scanner = CatalogScanner(
            db, store_code=store_code, store_type=_configured_store_type(), job_id=job_products.id
        )
        try:
            prod_result = scanner.scan_products(tracked_only=True)
        except Exception as e:
            logger.error(f"[Scheduler] Ошибка сканирования товаров: {e}")
            finalize_job(db, job_products.id, "failed", error_message=str(e))
            return
        finally:
            scanner.close()

        finalize_job(
            db, job_products.id, "completed",
            items_scanned=prod_result["scanned"],
            items_added=prod_result["added"],
            items_updated=prod_result["updated"],
        )

        logger.info(f"[Scheduler] Товары: {prod_result}")

    finally:
        db.close()



def register_jobs(store_code: str):
    """
    Зарегистрировать (или перерегистрировать) задания планировщика для магазина
    и запустить планировщик, если он ещё не запущен.

    Повторный вызов безопасен: задания заменяются (`replace_existing=True`) —
    так смена магазина через POST /api/stores/select применяется без перезапуска.

    Отслеживаемые категории задания читают в момент запуска, а не при
    регистрации, поэтому новые отметки в UI учитываются сразу.

    Args:
        store_code: Код магазина для которого запускаем задания
    """
    logger.info(f"[Scheduler] Регистрация заданий для магазина {store_code}")

    # Обновление цен — каждый день в 8:00
    scheduler.add_job(
        update_prices_job,
        CronTrigger(hour=8, minute=0),
        args=[store_code],
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
    # scheduler.add_job(
    #     generate_daily_report_job,
    #     CronTrigger(hour=20, minute=0),
    #     args=[store_code],
    #     id="daily_report",
    #     name="Ежедневный отчёт",
    #     replace_existing=True,
    # )

    if not scheduler.running:
        scheduler.start()
        logger.info("[Scheduler] Планировщик запущен")


def init_scheduler(store_code: str):
    """Инициализировать планировщик при старте приложения."""
    register_jobs(store_code)


def shutdown_scheduler():
    """Остановить планировщик."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("[Scheduler] Планировщик остановлен")
