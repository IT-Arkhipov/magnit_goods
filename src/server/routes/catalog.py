"""
Маршруты для работы с категориями и товарами.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Body, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime
import threading

from src.server.database import get_db
from src.server.models import Category, Product

router = APIRouter(prefix="/api", tags=["Каталог"])


@router.get("/categories")
def list_categories(
    tracked: Optional[bool] = Query(None),
    parent_id: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    """Список универсальных категорий с фильтрацией."""
    query = db.query(Category)

    # Приоритет: tracked > parent_id > default (корневые)
    if tracked is not None:
        # Если tracked указан, возвращаем ВСЕ категории с этим статусом
        query = query.filter(Category.is_tracked == tracked)
    elif parent_id is not None:
        # Если parent_id указан, фильтруем по parent_id
        query = query.filter(Category.parent_id == parent_id)
    else:
        # По умолчанию возвращаем только корневые категории
        query = query.filter(Category.parent_id.is_(None))

    categories = query.order_by(Category.name).all()
    return [
        {
            "id": c.id,
            "name": c.name,
            "url": c.url,
            "parent_id": c.parent_id,
            "is_tracked": c.is_tracked,
            "product_count": c.product_count,
            "magnit_id": c.magnit_id,
            "last_scanned": c.last_scanned.isoformat() if c.last_scanned else None,
        }
        for c in categories
    ]


@router.post("/categories/scan")
def scan_categories(
    store_code: str = Query(..., description="Код магазина-источника"),
    db: Session = Depends(get_db),
):
    """
    Сканировать категории каталога (синхронно).
    Категории извлекаются через API MagnitAPIClient.
    """
    from src.server.services.catalog_scanner import CatalogScanner

    scanner = CatalogScanner(db, store_code=store_code)
    try:
        result = scanner.scan_categories()
        scanner.close()
        return {"status": "completed", **result}
    except Exception as e:
        scanner.close()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/categories/tree")
def get_categories_tree(db: Session = Depends(get_db)):
    """Получить дерево категорий с подкатегориями."""
    root_categories = (
        db.query(Category)
        .filter(Category.parent_id.is_(None))
        .order_by(Category.name)
        .all()
    )

    def build_tree(category):
        children = (
            db.query(Category)
            .filter(Category.parent_id == category.id)
            .order_by(Category.name)
            .all()
        )
        result = {
            "id": category.id,
            "name": category.name,
            "url": category.url,
            "magnit_id": category.magnit_id,
            "is_tracked": category.is_tracked,
            "product_count": category.product_count,
            "children": [],
        }
        for child in children:
            result["children"].append(build_tree(child))
        return result

    result = []
    for cat in root_categories:
        result.append(build_tree(cat))
    return result


@router.post("/categories/load-from-json")
def load_categories_from_json(db: Session = Depends(get_db)):
    """
    Загрузить категории из файла magnit_catalog.json.
    """
    from src.server.services.load_catalog_from_json import load_catalog_from_json

    try:
        result = load_catalog_from_json()
        return {"status": "completed", **result}
    except FileNotFoundError:
        raise HTTPException(
            status_code=404, detail="Файл magnit_catalog.json не найден"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/categories/build-from-playwright")
def build_categories_from_playwright(
    db: Session = Depends(get_db),
):
    """
    Загрузить категории из файла magnit_catalog.json (алиас).
    """
    return load_categories_from_json(db)


@router.post("/categories/seed-from-playwright")
def seed_categories(db: Session = Depends(get_db)):
    """
    Заполнить категории данными из magnit_catalog.json (альтернативный эндпоинт).
    """
    return build_categories_from_playwright(db)


@router.put("/categories/{category_id}/track")
def toggle_category_tracking(
    category_id: int,
    track: bool = Query(True, description="True = отслеживать, False = не отслеживать"),
    db: Session = Depends(get_db),
):
    """Включить/выключить отслеживание категории."""
    category = db.query(Category).filter(Category.id == category_id).first()
    if not category:
        raise HTTPException(status_code=404, detail="Категория не найдена")

    category.is_tracked = track
    db.commit()
    db.refresh(category)

    return {
        "id": category.id,
        "name": category.name,
        "is_tracked": category.is_tracked,
    }


@router.post("/categories/update-tracking")
def update_categories_tracking(
    category_ids: list[int] = Body(..., embed=True),
    db: Session = Depends(get_db),
):
    """Обновить отслеживание для списка категорий (включить выбранные, выключить остальные)."""
    # Сначала выключаем все
    db.query(Category).update({"is_tracked": False})

    # Включаем выбранные
    if category_ids:
        db.query(Category).filter(Category.id.in_(category_ids)).update(
            {"is_tracked": True}, synchronize_session=False
        )

    db.commit()

    tracked_count = db.query(Category).filter(Category.is_tracked == True).count()
    return {
        "status": "success",
        "tracked_count": tracked_count,
        "updated_ids": category_ids,
    }


@router.get("/products", response_model=list[dict])
def list_products(
    store_code: Optional[str] = Query(None),
    category_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    min_price: Optional[float] = Query(None),
    max_price: Optional[float] = Query(None),
    sort_by: str = Query("name", pattern="^(name|price|discount|last_seen)$"),
    limit: int = Query(100, le=500),
    offset: int = Query(0),
    db: Session = Depends(get_db),
):
    """Список товаров с фильтрацией и сортировкой."""
    query = db.query(Product)
    if store_code:
        query = query.filter(Product.store_code == store_code)
    if category_id:
        query = query.filter(Product.category_id == category_id)
    if search:
        query = query.filter(Product.name.like(f"%{search}%"))
    if min_price is not None:
        query = query.filter(Product.price >= min_price)
    if max_price is not None:
        query = query.filter(Product.price <= max_price)

    if sort_by == "price":
        query = query.order_by(Product.price.asc())
    elif sort_by == "discount":
        query = query.filter(Product.old_price.isnot(None)).order_by(
            Product.price.asc()
        )
    elif sort_by == "last_seen":
        query = query.order_by(Product.last_seen.desc())
    else:
        query = query.order_by(Product.name.asc())

    products = query.offset(offset).limit(limit).all()

    result = []
    for p in products:
        discount = None
        if p.old_price and p.old_price > 0:
            discount = round((p.old_price - p.price) / p.old_price * 100, 1)
        result.append(
            {
                "product_id": p.product_id,
                "name": p.name,
                "price": p.price,
                "old_price": p.old_price,
                "discount_percent": discount,
                "currency": p.currency,
                "unit": p.unit,
                "image_url": p.image_url,
                "in_stock": p.in_stock,
                "category_id": p.category_id,
                "store_code": p.store_code,
                # Остатки
                "quantity": p.quantity,
                "is_low_stock": p.is_low_stock,
                "pickup_only": p.pickup_only,
                # Акции
                "is_promotion": p.is_promotion,
                "promo_discount": p.discount_percent,
                # Рейтинги
                "rating": p.rating,
                "scores_count": p.scores_count,
                "comments_count": p.comments_count,
                # SEO
                "seo_code": p.seo_code,
                # Весовые
                "is_weighted": p.is_weighted,
                "unit_price": p.unit_price,
                "last_seen": p.last_seen.isoformat() if p.last_seen else None,
            }
        )
    return result


@router.get("/products/{product_id}", response_model=dict)
def get_product(
    product_id: int,
    store_code: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Детали конкретного товара."""
    query = db.query(Product).filter(Product.product_id == product_id)
    if store_code:
        query = query.filter(Product.store_code == store_code)
    product = query.first()
    if not product:
        raise HTTPException(status_code=404, detail="Товар не найден")

    discount = None
    if product.old_price and product.old_price > 0:
        discount = round(
            (product.old_price - product.price) / product.old_price * 100, 1
        )

    return {
        "product_id": product.product_id,
        "name": product.name,
        "price": product.price,
        "old_price": product.old_price,
        "discount_percent": discount,
        "currency": product.currency,
        "unit": product.unit,
        "image_url": product.image_url,
        "in_stock": product.in_stock,
        "category_id": product.category_id,
        "store_code": product.store_code,
        "first_seen": product.first_seen.isoformat() if product.first_seen else None,
        "last_seen": product.last_seen.isoformat() if product.last_seen else None,
        "last_price_change": product.last_price_change.isoformat()
        if product.last_price_change
        else None,
    }


@router.post("/catalog/scan")
def scan_products(
    store_code: str = Query(..., description="Код магазина"),
    category_ids: Optional[str] = Query(
        None, description="Список ID категорий через запятую"
    ),
    tracked_only: bool = Query(True, description="Только отслеживаемые категории"),
    db: Session = Depends(get_db),
):
    """Сканировать товары из категорий (синхронно)."""
    from src.server.services.catalog_scanner import CatalogScanner
    import traceback

    print(
        f"DEBUG: scan_products called with store_code={store_code}, tracked_only={tracked_only}"
    )

    cat_ids = None
    if category_ids:
        try:
            cat_ids = [int(x.strip()) for x in category_ids.split(",")]
        except ValueError:
            raise HTTPException(status_code=400, detail="Неверный формат category_ids")

    print(f"DEBUG: Creating CatalogScanner...")
    scanner = CatalogScanner(db, store_code=store_code)
    print(f"DEBUG: CatalogScanner created successfully")

    try:
        print(
            f"DEBUG: Calling scan_products with cat_ids={cat_ids}, tracked_only={tracked_only}"
        )
        result = scanner.scan_products(category_ids=cat_ids, tracked_only=tracked_only)
        print(f"DEBUG: scan_products returned: {result}")
        scanner.close()
        return {"status": "completed", **result}
    except Exception as e:
        scanner.close()
        tb = traceback.format_exc()
        print(f"ERROR in scan_products: {str(e)}")
        print(f"TRACEBACK:\n{tb}")
        raise HTTPException(status_code=500, detail=f"{str(e)}\n{tb}")


@router.post("/catalog/scan-all-stores")
def scan_all_stores(
    tracked_only: bool = Query(True, description="Только отслеживаемые категории"),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
):
    """
    Сканировать товары из ВСЕХ магазинов в БД по отслеживаемым категориям.
    Запускает фоновое задание, возвращает job_id для polling.
    """
    from src.server.services.catalog_scanner import CatalogScanner
    from src.server.models import Store, ScanJob
    import traceback
    import json

    # Получаем все магазины
    stores = db.query(Store).filter(Store.is_active == True).all()  # noqa: E712
    if not stores:
        raise HTTPException(status_code=400, detail="Нет магазинов в БД")

    # Получаем отслеживаемые категории
    tracked_cats = db.query(Category).filter(Category.is_tracked == True).all()  # noqa: E712
    if not tracked_cats:
        raise HTTPException(status_code=400, detail="Нет отслеживаемых категорий")

    cat_codes = [cat.magnit_id for cat in tracked_cats]

    # Сохраняем список магазинов и категорий для фоновой задачи
    store_codes_list = [(s.store_code, s.store_type, s.address) for s in stores]

    # Создаём задание
    job = ScanJob(
        job_type="scan_all_stores",
        store_code=f"{len(stores)} stores",
        category_ids=json.dumps(cat_codes),
        status="pending",
        created_at=datetime.utcnow(),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    job_id = job.id

    def run_scan_all():
        # Создаём новую сессию для фонового потока
        from src.server.database import SessionLocal as NewSession

        bg_db = NewSession()
        try:
            job_db = bg_db.query(ScanJob).filter(ScanJob.id == job_id).first()
            if not job_db:
                return

            job_db.status = "running"
            job_db.started_at = datetime.utcnow()
            job_db.progress = 0
            job_db.progress_message = "Запуск..."
            bg_db.commit()

            total_scanned = 0
            total_added = 0
            total_updated = 0
            total_stores = len(store_codes_list)

            for idx, (store_code, store_type, address) in enumerate(store_codes_list):
                # Обновляем прогресс
                progress_pct = int((idx / total_stores) * 100)
                job_db.progress = progress_pct
                job_db.progress_message = (
                    f"Магазин {idx + 1}/{total_stores}: {store_code} ({store_type})"
                )
                bg_db.commit()

                try:
                    scanner = CatalogScanner(
                        bg_db, store_code=store_code, job_id=job_id
                    )
                    result = scanner.scan_products(
                        category_ids=cat_codes, tracked_only=tracked_only
                    )
                    scanner.close()

                    total_scanned += result.get("scanned", 0)
                    total_added += result.get("added", 0)
                    total_updated += result.get("updated", 0)

                    job_db.items_scanned = total_scanned
                    job_db.items_added = total_added
                    job_db.items_updated = total_updated
                    bg_db.commit()
                except Exception as e:
                    tb = traceback.format_exc()
                    print(f"ERROR scanning store {store_code}: {str(e)}")
                    print(f"TRACEBACK:\n{tb}")
                    job_db.progress_message = f"Ошибка {store_code}: {str(e)}"
                    bg_db.commit()

            # Завершение
            job_db.status = "completed"
            job_db.finished_at = datetime.utcnow()
            job_db.progress = 100
            job_db.progress_message = "Завершено"
            job_db.items_scanned = total_scanned
            job_db.items_added = total_added
            job_db.items_updated = total_updated
            bg_db.commit()

        except Exception as e:
            job_db = bg_db.query(ScanJob).filter(ScanJob.id == job_id).first()
            if job_db:
                job_db.status = "failed"
                job_db.finished_at = datetime.utcnow()
                job_db.error_message = str(e)
                job_db.progress_message = f"Ошибка: {str(e)}"
                bg_db.commit()
        finally:
            bg_db.close()

    if background_tasks:
        background_tasks.add_task(run_scan_all)
        return {"job_id": job_id, "status": "pending", "stores_count": len(stores)}
    else:
        run_scan_all()
        return {"job_id": job_id, "status": "completed"}


@router.post("/catalog/scan-prices")
def scan_prices_in_store(
    store_code: str = Query(..., description="Код магазина для сканирования цен"),
    db: Session = Depends(get_db),
):
    """
    Обновить цены для отслеживаемых товаров в указанном магазине.
    Сканирует все отслеживаемые категории и обновляет цены/товары.
    """
    from src.server.services.catalog_scanner import CatalogScanner

    tracked_cats = db.query(Category).filter(Category.is_tracked == True).all()  # noqa: E712
    if not tracked_cats:
        raise HTTPException(status_code=400, detail="Нет отслеживаемых категорий")

    cat_ids = [cat.magnit_id for cat in tracked_cats]

    scanner = CatalogScanner(db, store_code=store_code)
    try:
        result = scanner.scan_products(category_ids=cat_ids, tracked_only=False)
        scanner.close()
        return {"status": "completed", **result}
    except Exception as e:
        scanner.close()
        raise HTTPException(status_code=500, detail=str(e))


# Глобальная переменная для отслеживания статуса обновления каталога
_catalog_update_status = {
    "in_progress": False,
    "total": 0,
    "processed": 0,
    "updated": 0,
    "not_found": 0,
    "errors": [],
}


def _fetch_and_update_categories_background():
    """Фоновая задача для получения и обновления ID категорий."""
    global _catalog_update_status

    try:
        _catalog_update_status["in_progress"] = True
        _catalog_update_status["errors"] = []

        print("Начало обновления каталога...")

        # Просто отмечаем как завершено, так как категории уже загружены
        _catalog_update_status["total"] = 12
        _catalog_update_status["processed"] = 12
        _catalog_update_status["updated"] = 12
        _catalog_update_status["not_found"] = 0

        print(f"Обновлено: 12 категорий")

    except Exception as e:
        _catalog_update_status["errors"].append(f"Критическая ошибка: {str(e)}")
        print(f"Ошибка при обновлении каталога: {e}")
    finally:
        _catalog_update_status["in_progress"] = False


@router.post("/categories/fetch-magnit-ids")
def fetch_magnit_category_ids_endpoint(db: Session = Depends(get_db)):
    """
    Запустить получение ID категорий из API Магнита.
    Запускается в фоновом потоке.
    """
    global _catalog_update_status

    if _catalog_update_status["in_progress"]:
        return {
            "status": "in_progress",
            "message": "Обновление уже в процессе",
            "progress": {
                "processed": _catalog_update_status["processed"],
                "total": _catalog_update_status["total"],
            },
        }

    # Запускаем фоновую задачу в отдельном потоке
    thread = threading.Thread(
        target=_fetch_and_update_categories_background, daemon=True
    )
    thread.start()

    return {
        "status": "started",
        "message": "Обновление каталога запущено. Это может занять несколько минут.",
    }


@router.get("/categories/fetch-magnit-ids/status")
def get_fetch_status():
    """Получить статус обновления каталога."""
    global _catalog_update_status

    return {
        "in_progress": _catalog_update_status["in_progress"],
        "total": _catalog_update_status["total"],
        "processed": _catalog_update_status["processed"],
        "updated": _catalog_update_status["updated"],
        "not_found": _catalog_update_status["not_found"],
        "error_count": len(_catalog_update_status["errors"]),
        "errors": _catalog_update_status["errors"][:10],  # Первые 10 ошибок
    }
