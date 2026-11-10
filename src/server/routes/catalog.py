"""
Маршруты для работы с категориями и товарами.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, Body, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Optional
import threading
import logging

from src.server.database import get_db
from src.server.models import Category, Product, PriceHistory, Store
from src.server.schemas import ProductListItem, ProductStats
from src.server.services.catalog_scanner import (
    AmbiguousStoreError,
    get_tracked_category_magnit_ids,
    parse_store_ref,
    parse_store_refs,
    resolve_store_type,
    resolve_store_type_filter,
)
from src.server.services import product_query
from src.server.utils.threads import run_logged

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["Каталог"])

STORE_TYPE_QUERY_DESCRIPTION = "Тип магазина (обязателен, если у кода магазина в БД несколько типов)"
STORE_REFS_QUERY_DESCRIPTION = (
    "Магазины через запятую: `код` или `код|тип` (тип обязателен, если у кода в БД несколько типов)"
)


def _resolve_store_type_or_400(db: Session, store_code: str, store_type: Optional[str]) -> str:
    """Тип магазина для сканера; неоднозначный код → 400."""
    try:
        return resolve_store_type(db, store_code, store_type)
    except AmbiguousStoreError as e:
        raise HTTPException(status_code=400, detail=str(e))


def store_type_filter_or_400(
    db: Session, store_code: Optional[str], store_type: Optional[str]
) -> Optional[str]:
    """Код типа магазина для чтения товаров (resolve_store_type_filter).

    Неоднозначный код без типа и нераспознанный тип → 400. Используется и
    в routes/prices.py.
    """
    try:
        return resolve_store_type_filter(db, store_code, store_type)
    except AmbiguousStoreError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=f"store_type: {e}")


def _store_refs_or_400(db: Session, refs: list[str]) -> list[tuple[str, str, Optional[str]]]:
    """Элементы набора магазинов → (исходный элемент, код, код типа или None)."""
    result = []
    for ref in refs:
        code, store_type = parse_store_ref(ref)
        result.append((ref, code, store_type_filter_or_400(db, code, store_type)))
    return result


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
        Category.parent_id.isnot(None)
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

    tracked_count = db.query(Category).filter(Category.is_tracked == True).count()  # noqa: E712
    return {
        "status": "success",
        "tracked_count": tracked_count,
        "updated_ids": actual_child_ids,
    }


@router.get("/products", response_model=list[ProductListItem])
def list_products(
    store_code: Optional[str] = Query(None),
    store_type: Optional[str] = Query(None, description=STORE_TYPE_QUERY_DESCRIPTION),
    category_id: Optional[int] = Query(None),
    category_ids: Optional[str] = Query(None, description="Comma-separated category IDs"),
    search: Optional[str] = Query(None),
    min_price: Optional[float] = Query(None),
    max_price: Optional[float] = Query(None),
    sort_by: str = Query("name", pattern="^(name|price|last_seen)$"),
    limit: int = Query(100, le=1000),
    offset: int = Query(0),
    relax_stale: bool = Query(
        False,
        description="Расширить окно видимости устаревших товаров до STALE_DAYS_DELETE "
                    "(используется в режиме «Последнее изменение» чекбокса «Новая цена»).",
    ),
    include_out_of_stock: bool = Query(
        False,
        description="Включить товары, которых не вернул последний скан (in_stock=False). "
                    "По умолчанию (False) такие товары скрываются — они физически "
                    "отсутствуют в магазине, даже если по старому скану у них числится "
                    "скидка.",
    ),
    db: Session = Depends(get_db),
):
    """Список товаров с фильтрацией, поиском и сортировкой."""
    filters = product_query.ProductFilters(
        store_code=store_code,
        store_type_code=store_type_filter_or_400(db, store_code, store_type),
        category_id=category_id,
        category_ids=product_query.parse_category_ids(category_ids),
        min_price=min_price,
        max_price=max_price,
        search=search,
        relax_stale=relax_stale,
        include_out_of_stock=include_out_of_stock,
    )
    products = product_query.list_products(db, filters, sort_by=sort_by, limit=limit, offset=offset)
    return [product_query.product_to_list_item(p) for p in products]


@router.get("/products/stats", response_model=ProductStats)
def get_products_stats(
    store_code: Optional[str] = Query(None),
    store_type: Optional[str] = Query(None, description=STORE_TYPE_QUERY_DESCRIPTION),
    store_codes: Optional[str] = Query(None, description=STORE_REFS_QUERY_DESCRIPTION),
    db: Session = Depends(get_db),
):
    """Статистика товаров по магазину, набору магазинов или по всем."""
    stores = [
        (code, type_code)
        for _, code, type_code in _store_refs_or_400(db, parse_store_refs(store_codes))
    ]
    if store_code and store_code.strip():
        code = store_code.strip()
        stores.append((code, store_type_filter_or_400(db, code, store_type)))
    return product_query.get_products_stats(db, list(dict.fromkeys(stores)))


@router.get("/products/multi-prices")
def get_multi_store_prices(
    product_ids: str = Query(..., description="Comma-separated product IDs"),
    store_codes: str = Query(..., description=STORE_REFS_QUERY_DESCRIPTION),
    db: Session = Depends(get_db),
):
    """Цены товаров в нескольких магазинах.

    Ответ: {product_id: {элемент store_codes как в запросе: {цена, остаток, …}}}.
    """
    pid_list = [int(x.strip()) for x in product_ids.split(',') if x.strip().isdigit()]
    refs = _store_refs_or_400(db, parse_store_refs(store_codes))

    if not pid_list or not refs:
        return {}

    products = db.query(Product).filter(
        Product.product_id.in_(pid_list),
        product_query.store_condition([(code, type_code) for _, code, type_code in refs]),
    ).all()

    result = {}
    for p in products:
        for ref, code, type_code in refs:
            if code != p.store_code or (type_code and type_code != p.store_type_code):
                continue
            result.setdefault(p.product_id, {})[ref] = {
            "price": p.price,
            "previous_price": p.previous_price,
            "price_change_percent": p.price_change_percent,
            "last_change_price": p.last_change_price,
            "in_stock": p.in_stock,
            "quantity": p.quantity,
            "last_seen": p.last_seen.isoformat() if p.last_seen else None,
            "last_change_date": p.last_change_date.isoformat() if p.last_change_date else None,
            "seo_code": p.seo_code,
            # Тип магазина записи (а не stores.shop_type) — для ссылки на товар
            "shop_type": int(p.store_type_code),
            "store_type_code": p.store_type_code,
        }

    return result


@router.get("/products/{product_id}", response_model=dict)
def get_product(
    product_id: int,
    store_code: Optional[str] = Query(None),
    store_type: Optional[str] = Query(None, description=STORE_TYPE_QUERY_DESCRIPTION),
    db: Session = Depends(get_db),
):
    """Детали конкретного товара."""
    query = db.query(Product).filter(Product.product_id == product_id)
    if store_code:
        query = query.filter(Product.store_code == store_code)
    store_type_code = store_type_filter_or_400(db, store_code, store_type)
    if store_type_code:
        query = query.filter(Product.store_type_code == store_type_code)
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
        "store_type_code": product.store_type_code,
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
    store_type: Optional[str] = Query(None, description=STORE_TYPE_QUERY_DESCRIPTION),
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
    store_type_code = store_type_filter_or_400(db, store_code, store_type)
    if store_type_code:
        query = query.filter(PriceHistory.store_type_code == store_type_code)
    rows = query.order_by(
        PriceHistory.scan_date.desc(),
        PriceHistory.store_code.asc(),
        PriceHistory.store_type_code.asc(),
    ).all()

    return [
        {
            "scan_date": r.scan_date.isoformat() if r.scan_date else None,
            "store_code": r.store_code,
            "store_type_code": r.store_type_code,
            "price": r.price,
            "quantity": r.quantity,
            "in_stock": r.in_stock,
        }
        for r in rows
    ]


@router.post("/catalog/scan")
def scan_products(
    store_code: str = Query(..., description="Код магазина"),
    store_type: Optional[str] = Query(None, description=STORE_TYPE_QUERY_DESCRIPTION),
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

    logger.debug("DEBUG: Creating CatalogScanner...")
    scanner = CatalogScanner(
        db,
        store_code=store_code,
        store_type=_resolve_store_type_or_400(db, store_code, store_type),
    )
    logger.debug("DEBUG: CatalogScanner created successfully")

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
    background_tasks: BackgroundTasks,
    tracked_only: bool = Query(True, description="Только отслеживаемые категории (другие значения не поддерживаются)"),
    db: Session = Depends(get_db),
):
    """
    Сканировать товары из ВСЕХ активных магазинов по отслеживаемым категориям.
    Запускает фоновое задание, возвращает job_id для polling.
    """
    from src.server.services.store_scan import (
        NothingToScanError,
        create_scan_all_stores_job,
        run_scan_all_stores,
    )

    try:
        job_id = create_scan_all_stores_job(db)
    except NothingToScanError as e:
        raise HTTPException(status_code=400, detail=str(e))

    stores_count = db.query(Store).filter(Store.is_active.is_(True)).count()
    background_tasks.add_task(run_scan_all_stores, job_id)
    return {"job_id": job_id, "status": "pending", "stores_count": stores_count}


@router.post("/catalog/scan-prices")
def scan_prices_in_store(
    store_code: str = Query(..., description="Код магазина для сканирования цен"),
    store_type: Optional[str] = Query(None, description=STORE_TYPE_QUERY_DESCRIPTION),
    db: Session = Depends(get_db),
):
    """
    Обновить цены для отслеживаемых товаров в указанном магазине.
    Сканирует все отслеживаемые категории и обновляет цены/товары.
    """
    from src.server.services.catalog_scanner import CatalogScanner

    cat_ids = get_tracked_category_magnit_ids(db)
    if not cat_ids:
        raise HTTPException(status_code=400, detail="Нет отслеживаемых категорий")

    scanner = CatalogScanner(
        db,
        store_code=store_code,
        store_type=_resolve_store_type_or_400(db, store_code, store_type),
    )
    try:
        result = scanner.scan_products(category_ids=cat_ids, tracked_only=False)
        scanner.close()
        return {"status": "completed", **result}
    except Exception as e:
        scanner.close()
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/categories/fetch-magnit-ids")
def fetch_magnit_category_ids_endpoint():
    """
    Запустить полную замену каталога категорий из API Магнита (фоновый поток).
    Статус — GET /api/categories/fetch-magnit-ids/status.
    """
    from src.server.services.catalog_updater import (
        end_catalog_update,
        get_catalog_update_status,
        run_catalog_update,
        try_begin_catalog_update,
    )

    if not try_begin_catalog_update():
        status = get_catalog_update_status()
        return {
            "status": "in_progress",
            "message": "Обновление уже в процессе",
            "progress": {"processed": status["processed"], "total": status["total"]},
        }

    thread = threading.Thread(target=run_logged, args=(run_catalog_update,), daemon=True)
    try:
        thread.start()
    except Exception:
        end_catalog_update()
        raise

    return {
        "status": "started",
        "message": "Обновление каталога запущено. Это может занять несколько минут.",
    }


@router.get("/categories/fetch-magnit-ids/status")
def get_fetch_status():
    """Получить статус обновления каталога."""
    from src.server.services.catalog_updater import get_catalog_update_status

    return get_catalog_update_status()


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
    except HTTPException:
        raise
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/products/clear-by-store")
def clear_products_by_store(
    store_code: str = Query(..., description="Код магазина"),
    store_type: Optional[str] = Query(None, description=STORE_TYPE_QUERY_DESCRIPTION),
    db: Session = Depends(get_db)
):
    """Удалить все товары магазина (код и тип; другой тип с тем же кодом не трогается)."""
    store_type_code = store_type_filter_or_400(db, store_code, store_type)
    try:
        query = db.query(Product).filter(Product.store_code == store_code)
        if store_type_code:
            query = query.filter(Product.store_type_code == store_type_code)
        count = query.delete(synchronize_session=False)
        db.commit()
        return {
            "status": "success",
            "message": f"Удалено {count} товаров для магазина {store_code}",
            "deleted_count": count
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=str(e))
