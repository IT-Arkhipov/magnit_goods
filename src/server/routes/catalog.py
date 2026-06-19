"""
Маршруты для работы с категориями и товарами.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Body, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime
import threading
import os
import logging

from src.server.database import get_db
from src.server.models import Category, Product, PriceHistory, Store

logger = logging.getLogger(__name__)

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
    Сканировать подкатегории из API Магнита (синхронно).

    Логика:
    1. Получает все категории из API
    2. Добавляет новые подкатегории
    3. Обновляет существующие
    4. Удаляет подкатегории, которых нет в API (полная синхронизация)

    Корневые категории из JSON не удаляются.
    """
    import os
    from src.server.services.catalog_scanner import CatalogScanner

    store_type = os.getenv("STORE_TYPE", "MM")
    scanner = CatalogScanner(db, store_code=store_code, store_type=store_type)
    try:
        result = scanner.scan_categories()
        scanner.close()
        return {"status": "completed", **result}
    except Exception as e:
        scanner.close()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/categories/update-catalog")
def update_catalog_from_api(
    store_code: str = Query(..., description="Код магазина для получения подкатегорий"),
    db: Session = Depends(get_db),
):
    """
    Обновить каталог - сканировать подкатегории из API Магнита (синхронно).

    Это основной endpoint для обновления каталога вручную.
    Получает подкатегории из API и синхронизирует с БД.

    Возвращает:
    {
        "status": "completed",
        "scanned": количество категорий из API,
        "added": добавлено новых подкатегорий,
        "updated": обновлено существующих,
        "deleted": удалено устаревших подкатегорий
    }
    """
    import os
    from src.server.services.catalog_scanner import CatalogScanner

    logger.debug(f"DEBUG: Обновление каталога для магазина {store_code}")

    store_type = os.getenv("STORE_TYPE", "MM")
    scanner = CatalogScanner(db, store_code=store_code, store_type=store_type)
    try:
        result = scanner.scan_categories()
        scanner.close()
        logger.debug(f"DEBUG: Обновление каталога завершено: {result}")
        return {"status": "completed", **result}
    except Exception as e:
        scanner.close()
        logger.error(f"ERROR: Ошибка при обновлении каталога: {e}")
        import traceback

        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/categories/tree")
def get_categories_tree(db: Session = Depends(get_db)):
    """Получить дерево категорий с подкатегориями."""
    all_cats = db.query(Category).order_by(Category.name).all()

    cat_map = {
        c.id: {
            "id": c.id,
            "name": c.name,
            "url": c.url,
            "magnit_id": c.magnit_id,
            "is_tracked": c.is_tracked,
            "product_count": c.product_count,
            "parent_id": c.parent_id,
            "children": [],
        }
        for c in all_cats
    }

    roots = []
    for cat in cat_map.values():
        if cat["parent_id"] is None:
            roots.append(cat)
        else:
            parent = cat_map.get(cat["parent_id"])
            if parent:
                parent["children"].append(cat)
    return roots


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
    """Обновить отслеживание для списка категорий (только дочерние)."""
    # Фильтруем - оставляем только дочерние категории (с parent_id)
    child_ids = [cid for cid in category_ids if cid is not None]
    actual_child_ids = db.query(Category.id).filter(
        Category.id.in_(child_ids),
        Category.parent_id != None
    ).all()
    actual_child_ids = [c.id for c in actual_child_ids]
    
    # Сначала выключаем все
    db.query(Category).update({"is_tracked": False})

    # Включаем только дочерние
    if actual_child_ids:
        db.query(Category).filter(Category.id.in_(actual_child_ids)).update(
            {"is_tracked": True}, synchronize_session=False
        )

    db.commit()

    tracked_count = db.query(Category).filter(Category.is_tracked == True).count()
    return {
        "status": "success",
        "tracked_count": tracked_count,
        "updated_ids": actual_child_ids,
    }


@router.get("/products", response_model=list[dict])
def list_products(
    store_code: Optional[str] = Query(None),
    category_id: Optional[int] = Query(None),
    category_ids: Optional[str] = Query(None, description="Comma-separated category IDs"),
    search: Optional[str] = Query(None),
    min_price: Optional[float] = Query(None),
     max_price: Optional[float] = Query(None),
     sort_by: str = Query("name", pattern="^(name|price|last_seen)$"),
     limit: int = Query(100, le=1000),
     offset: int = Query(0),
     db: Session = Depends(get_db),
):
    """Список товаров с фильтрацией и сортировкой."""
    from sqlalchemy.orm import joinedload
    from datetime import timedelta
    from sqlalchemy import func

    # Распарсиваем category_ids один раз
    cat_id_list: list[int] = []
    if category_ids:
        cat_id_list = [int(x.strip()) for x in category_ids.split(',') if x.strip().isdigit()]

    def _build_filtered_query():
        """Строит query с базовыми фильтрами (без search и пагинации)."""
        q = db.query(Product).options(joinedload(Product.category))
        if store_code:
            q = q.filter(Product.store_code == store_code)
        if category_id:
            q = q.filter(Product.category_id == category_id)
        if cat_id_list:
            q = q.filter(Product.category_id.in_(cat_id_list))
        if min_price is not None:
            q = q.filter(Product.price >= min_price)
        if max_price is not None:
            q = q.filter(Product.price <= max_price)

        # Скрываем товары, которых не было в сканах дольше STALE_DAYS_VISIBLE дней.
        # Жизненный цикл устаревшего товара: STALE_DAYS_VISIBLE (видим) →
        # STALE_DAYS_HIDDEN (скрыт) → STALE_DAYS_DELETE (удалён).
        from src.server.constants import STALE_DAYS_VISIBLE
        visible_cutoff = datetime.utcnow().date() - timedelta(days=STALE_DAYS_VISIBLE)
        q = q.filter(Product.last_seen >= visible_cutoff)
        return q

    if search and search.strip():
        # SQLite LOWER() не работает с не-ASCII символами (кириллица, немецкий и т.д.),
        # поэтому используем casefold() (Unicode-aware) и фильтруем в Python.
        search_cf = search.casefold().strip()
        candidates = _build_filtered_query().all()
        matching_ids = [
            p.product_id for p in candidates
            if search_cf in (p.name or "").casefold()
        ]
        if not matching_ids:
            return []
        query = db.query(Product).options(joinedload(Product.category)).filter(
            Product.product_id.in_(matching_ids)
        )
    else:
        query = _build_filtered_query()

    if sort_by == "price":
        query = query.order_by(Product.price.asc(), Product.name.asc())
    elif sort_by == "last_seen":
        query = query.order_by(Product.last_seen.desc(), Product.name.asc())
    else:
        query = query.order_by(Product.name.asc())

    products = query.offset(offset).limit(limit).all()

    result = []
    for p in products:
        result.append(
            {
                "product_id": p.product_id,
                "name": p.name,
                "price": p.price,
                "previous_price": p.previous_price,
                "price_change_percent": p.price_change_percent,
                "last_price_change": p.last_price_change.isoformat() if p.last_price_change else None,
                "last_change_price": p.last_change_price,
                "last_change_date": p.last_change_date.isoformat() if p.last_change_date else None,
                "currency": p.currency,
                "unit": p.unit,
                "image_url": p.image_url,
                "in_stock": p.in_stock,
                "category_id": p.category_id,
                "store_code": p.store_code,
                # Категория с информацией о родителе
                "category_name": p.category.name if p.category else None,
                "category_parent_id": p.category.parent_id if p.category else None,
                # Остатки
                "quantity": p.quantity,
                "is_low_stock": p.is_low_stock,
                "pickup_only": p.pickup_only,
                # Рейтинги
                "rating": p.rating,
                "scores_count": p.scores_count,
                "comments_count": p.comments_count,
                # SEO
                "seo_code": p.seo_code,
                # Весовые
                "is_weighted": p.is_weighted,
                "unit_price": p.unit_price,
                "first_seen": p.first_seen.isoformat() if p.first_seen else None,
                "last_seen": p.last_seen.isoformat() if p.last_seen else None,
            }
        )
    return result


@router.get("/products/stats")
def get_products_stats(
    store_code: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Статистика товаров."""
    from sqlalchemy import func, case

    query_filter = Product.store_code == store_code if store_code else True

    row = db.query(
        func.count().label("total"),
        func.sum(case((Product.in_stock == True, 1), else_=0)).label("in_stock"),
        func.sum(case((Product.price_change_percent > 0, 1), else_=0)).label("with_price_decrease"),
        func.sum(case((Product.price_change_percent < 0, 1), else_=0)).label("with_price_increase"),
        func.max(Product.last_seen).label("last_update"),
    ).filter(query_filter).one()

    return {
        "total": row.total or 0,
        "in_stock": row.in_stock or 0,
        "with_price_decrease": row.with_price_decrease or 0,
        "with_price_increase": row.with_price_increase or 0,
        "last_update": row.last_update.isoformat() if row.last_update else None,
    }


@router.get("/products/multi-prices")
def get_multi_store_prices(
    product_ids: str = Query(..., description="Comma-separated product IDs"),
    store_codes: str = Query(..., description="Comma-separated store codes"),
    db: Session = Depends(get_db),
):
    """Получение цен товаров из нескольких магазинов."""
    from src.server.models import Store
    
    pid_list = [int(x.strip()) for x in product_ids.split(',') if x.strip().isdigit()]
    store_list = [x.strip() for x in store_codes.split(',') if x.strip()]
    
    if not pid_list or not store_list:
        return {}
    
    # Получаем информацию о магазинах (shop_type)
    stores = db.query(Store).filter(Store.store_code.in_(store_list)).all()
    store_shop_type_map = {s.store_code: s.shop_type for s in stores}
    
    products = db.query(Product).filter(
        Product.product_id.in_(pid_list),
        Product.store_code.in_(store_list)
    ).all()
    
    result = {}
    for p in products:
        if p.product_id not in result:
            result[p.product_id] = {}
        result[p.product_id][p.store_code] = {
            "price": p.price,
            "previous_price": p.previous_price,
            "price_change_percent": p.price_change_percent,
            "in_stock": p.in_stock,
            "quantity": p.quantity,
            "last_seen": p.last_seen.isoformat() if p.last_seen else None,
            "last_change_date": p.last_change_date.isoformat() if p.last_change_date else None,
            "seo_code": p.seo_code,
            "shop_type": store_shop_type_map.get(p.store_code),
        }
    
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

    return {
        "product_id": product.product_id,
        "name": product.name,
        "price": product.price,
        "previous_price": product.previous_price,
        "price_change_percent": product.price_change_percent,
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
        "last_change_price": product.last_change_price,
        "last_change_date": product.last_change_date.isoformat()
        if product.last_change_date
        else None,
    }


@router.get("/products/{product_id}/history")
def get_product_price_history(
    product_id: int,
    store_code: Optional[str] = Query(None),
    days: int = Query(30, ge=1, le=365, description="Количество дней истории"),
    db: Session = Depends(get_db),
):
    """История цен товара (по дням)."""
    from datetime import date, timedelta

    cutoff = date.today() - timedelta(days=days)
    query = db.query(PriceHistory).filter(
        PriceHistory.product_id == product_id,
        PriceHistory.scan_date >= cutoff,
    )
    if store_code:
        query = query.filter(PriceHistory.store_code == store_code)
    rows = query.order_by(PriceHistory.scan_date.desc(), PriceHistory.store_code.asc()).all()

    return [
        {
            "scan_date": r.scan_date.isoformat() if r.scan_date else None,
            "store_code": r.store_code,
            "price": r.price,
            "quantity": r.quantity,
            "in_stock": r.in_stock,
        }
        for r in rows
    ]


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

    logger.debug(
        f"DEBUG: scan_products called with store_code={store_code}, tracked_only={tracked_only}"
    )

    cat_ids = None
    if category_ids:
        try:
            cat_ids = [int(x.strip()) for x in category_ids.split(",")]
        except ValueError:
            raise HTTPException(status_code=400, detail="Неверный формат category_ids")

    logger.debug(f"DEBUG: Creating CatalogScanner...")
    scanner = CatalogScanner(db, store_code=store_code)
    logger.debug(f"DEBUG: CatalogScanner created successfully")

    try:
        logger.debug(
            f"DEBUG: Calling scan_products with cat_ids={cat_ids}, tracked_only={tracked_only}"
        )
        result = scanner.scan_products(category_ids=cat_ids, tracked_only=tracked_only)
        logger.debug(f"DEBUG: scan_products returned: {result}")
        scanner.close()
        return {"status": "completed", **result}
    except Exception as e:
        scanner.close()
        tb = traceback.format_exc()
        logger.error(f"ERROR in scan_products: {str(e)}")
        logger.error(f"TRACEBACK:\n{tb}")
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

    # Получаем отслеживаемые категории (только дочерние, не корневые)
    tracked_cats = db.query(Category).filter(
        Category.is_tracked == True,  # noqa: E712
        Category.parent_id != None
    ).all()
    if not tracked_cats:
        raise HTTPException(status_code=400, detail="Нет отслеживаемых категорий (только дочерние)")

    cat_codes = [cat.magnit_id for cat in tracked_cats]

    # Сохраняем список магазинов для фоновой задачи
    store_codes_list = [(s.store_code, s.full_address) for s in stores]

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
            total_categories = len(cat_codes)
            total_operations = total_stores * total_categories
            current_operation = 0

            for idx, (store_code, address) in enumerate(store_codes_list):
                bg_db.expire_all()
                job_db = bg_db.query(ScanJob).filter(ScanJob.id == job_id).first()
                if job_db and job_db.status == "cancelled":
                    job_db.progress_message = "Отменено пользователем"
                    bg_db.commit()
                    return
                
                # Обновляем прогресс по магазинам
                job_db.total_stores = total_stores
                job_db.current_store_index = idx + 1
                job_db.current_store_code = store_code
                job_db.current_store_address = address
                job_db.total_categories = total_categories
                
                # Показать магазин ДО начала сканирования
                job_db.progress_message = f"🏪 {store_code}: {address}<br>📁 Магазин {idx + 1}/{total_stores}"
                bg_db.commit()
                
                try:
                    scanner = CatalogScanner(
                        bg_db, store_code=store_code, address=address, job_id=job_id
                    )

                    # Загружаем маппинг категорий один раз до цикла
                    cat_name_map = {
                        cat.magnit_id: cat.name
                        for cat in bg_db.query(Category.magnit_id, Category.name)
                        .filter(Category.magnit_id.in_(cat_codes))
                        .all()
                    }

                    # Сканируем по одной категории за раз для обновления прогресса
                    for cat_idx, cat_code in enumerate(cat_codes):
                        # Обновляем прогресс по категориям
                        job_db.current_category_index = cat_idx + 1

                        # Используем предзагруженный маппинг категорий
                        job_db.current_category_name = cat_name_map.get(cat_code, f"ID:{cat_code}")
                        job_db.current_category_magnit_id = cat_code

                        bg_db.commit()
                        
                        result = scanner.scan_products(
                            category_ids=[cat_code], tracked_only=tracked_only
                        )
                        
                        # Обновляем прогресс по товарам (после сканирования category)
                        # Примечание: для точного прогресса нужен totalCount из API
                        job_db.current_category_items_loaded = result.get("scanned", 0)
                        job_db.current_category_items_total = result.get("scanned", 0)
                        
                        # После каждой категории обновляем прогресс
                        current_operation += 1
                        progress_pct = int((current_operation / total_operations) * 100) if total_operations > 0 else 0
                        job_db.progress = progress_pct
                        job_db.progress_message = f"🏪 {store_code}: {address[:30]}...<br>📁 Категория {current_operation}/{total_operations}"
                        bg_db.commit()
                        
                        total_scanned += result.get("scanned", 0)
                        total_added += result.get("added", 0)
                        total_updated += result.get("updated", 0)
                    
                    scanner.close()

                    job_db.items_scanned = total_scanned
                    job_db.items_added = total_added
                    job_db.items_updated = total_updated
                    bg_db.commit()
                except Exception as e:
                    logger.error(f"ERROR scanning store {store_code}: {str(e)}")
                    job_db.progress_message = f"Ошибка {store_code}: {str(e)}"
                    bg_db.commit()

            job_db = bg_db.query(ScanJob).filter(ScanJob.id == job_id).first()
            if job_db and job_db.status == "cancelled":
                return
                
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
_catalog_update_lock = threading.Lock()


def _fetch_and_update_categories_background():
    """Фоновая задача для полной замены каталога категорий."""
    from src.server.services.catalog_updater import replace_catalog_from_api
    from src.server.database import SessionLocal

    global _catalog_update_status

    try:
        with _catalog_update_lock:
            _catalog_update_status["in_progress"] = True
            _catalog_update_status["errors"] = []

        logger.info("Начало полной замены каталога из API Магнита...")

        # Используем код магазина из .env
        store_code = os.getenv("STORE_CODE")
        store_type = os.getenv("STORE_TYPE")

        logger.debug(f"DEBUG: STORE_CODE={store_code}, STORE_TYPE={store_type}")

        if store_code and store_type:
            logger.debug(f"DEBUG: Using store_code={store_code}, store_type={store_type}")
            stats = replace_catalog_from_api(
                store_code=store_code, store_type=store_type
            )
        else:
            logger.debug("DEBUG: No STORE_CODE/STORE_TYPE in env, trying to get from DB")
            # Получаем первый активный магазин для запроса
            db = SessionLocal()
            store = db.query(Store).filter(Store.is_active == True).first()
            db.close()
            if store:
                logger.debug(
                    f"DEBUG: Found active store: {store.store_code}, type: {store.store_type}"
                )
                stats = replace_catalog_from_api(
                    store_code=store.store_code, store_type=os.getenv("STORE_TYPE", "6")
                )
            else:
                logger.debug("DEBUG: No active stores found, using defaults")
                stats = replace_catalog_from_api()

        logger.debug(f"DEBUG: replace_catalog_from_api returned: {stats}")

        # Проверяем статус ответа
        if stats.get("status") == "error":
            # Ошибка при получении данных из API
            with _catalog_update_lock:
                _catalog_update_status["errors"] = stats.get("errors", ["Unknown error"])
            logger.error(
                f"Ошибка при получении данных из API: {_catalog_update_status['errors']}"
            )
            return

        # Успешная замена
        with _catalog_update_lock:
            _catalog_update_status["total"] = stats.get("total", 0)
            _catalog_update_status["processed"] = stats.get("total", 0)  # все обработаны
            _catalog_update_status["updated"] = stats.get("updated", 0)
            _catalog_update_status["not_found"] = (
                0  # при полной замене не удаляем по-старому
            )

            if stats.get("errors"):
                _catalog_update_status["errors"] = stats["errors"]

        logger.info(
            f"Каталог заменён: Всего {stats.get('total', 0)} категорий, "
            f"Добавлено: {stats.get('added', 0)}, Восстановлено is_tracked: {stats.get('updated', 0)}"
        )

    except Exception as e:
        with _catalog_update_lock:
            _catalog_update_status["errors"].append(f"Критическая ошибка: {str(e)}")
        logger.error(f"Ошибка при замене каталога: {e}")
        logger.exception("Traceback")
    finally:
        with _catalog_update_lock:
            _catalog_update_status["in_progress"] = False


@router.post("/categories/fetch-magnit-ids")
def fetch_magnit_category_ids_endpoint(db: Session = Depends(get_db)):
    """
    Запустить получение ID категорий из API Магнита.
    Запускается в фоновом потоке.
    """
    global _catalog_update_status

    with _catalog_update_lock:
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

    with _catalog_update_lock:
        return {
            "in_progress": _catalog_update_status["in_progress"],
            "total": _catalog_update_status["total"],
            "processed": _catalog_update_status["processed"],
            "updated": _catalog_update_status["updated"],
            "not_found": _catalog_update_status["not_found"],
            "error_count": len(_catalog_update_status["errors"]),
            "errors": _catalog_update_status["errors"][:10],  # Первые 10 ошибок
        }


@router.delete("/products/clear")
def clear_all_products(db: Session = Depends(get_db)):
    """Удалить все товары из БД."""
    try:
        count = db.query(Product).delete()
        db.commit()
        return {
            "status": "success",
            "message": f"Удалено {count} товаров",
            "deleted_count": count
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/products/clear-by-categories")
def clear_products_by_categories(
    category_ids: str = Query(..., description="Comma-separated category IDs"),
    db: Session = Depends(get_db)
):
    """Удалить товары для конкретных категорий."""
    try:
        cat_id_list = [int(x.strip()) for x in category_ids.split(',') if x.strip().isdigit()]
        if not cat_id_list:
            raise HTTPException(status_code=400, detail="Неверный формат category_ids")
        
        count = db.query(Product).filter(Product.category_id.in_(cat_id_list)).delete()
        db.commit()
        return {
            "status": "success",
            "message": f"Удалено {count} товаров из {len(cat_id_list)} категорий",
            "deleted_count": count
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/products/clear-by-store")
def clear_products_by_store(
    store_code: str = Query(..., description="Код магазина"),
    db: Session = Depends(get_db)
):
    """Удалить все товары для конкретного магазина."""
    try:
        count = db.query(Product).filter(Product.store_code == store_code).delete()
        db.commit()
        return {
            "status": "success",
            "message": f"Удалено {count} товаров для магазина {store_code}",
            "deleted_count": count
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
