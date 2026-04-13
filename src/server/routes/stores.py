from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from typing import Optional
import os
import dotenv
from datetime import datetime, timedelta
import time

from sqlalchemy import or_
from src.server.database import get_db
from src.server.models import Store, ScanJob
from src.server.schemas import StoreCreate, StoreUpdate, StoreResponse, SelectStoreRequest, ScanStoresRequest, DeleteStoresRequest

router = APIRouter(prefix="/api/stores", tags=["Магазины"])


def _cleanup_stale_jobs(db: Session):
    """Перевести зависшие running-задания в failed (started_at > 2 мин назад)."""
    stale_cutoff = datetime.utcnow() - timedelta(minutes=2)
    stale_jobs = db.query(ScanJob).filter(
        ScanJob.job_type == "stores",
        ScanJob.status == "running",
        ScanJob.started_at < stale_cutoff,
    ).all()
    for job in stale_jobs:
        job.status = "failed"
        job.error_message = "Задание зависло и было автоматически отменено"
        job.finished_at = datetime.utcnow()
    if stale_jobs:
        db.commit()


def _mark_all_running_failed_on_startup(db: Session):
    """При старте сервера пометить все running задания как failed (процесс был убит)."""
    stale_jobs = db.query(ScanJob).filter(
        ScanJob.job_type == "stores",
        ScanJob.status == "running",
    ).all()
    for job in stale_jobs:
        job.status = "failed"
        job.error_message = "Сервер был перезапущен, задание прервано"
        job.finished_at = datetime.utcnow()
    if stale_jobs:
        db.commit()


@router.get("", response_model=list[StoreResponse])
def list_stores(
    city: Optional[str] = Query(None, description="Фильтр по городу"),
    store_type: Optional[str] = Query(None, description="Фильтр по типу"),
    is_active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
):
    """Список всех магазинов с фильтрацией."""
    q = db.query(Store)
    if city:
        q = q.filter(Store.city.like(f"%{city}%"))
    if store_type:
        q = q.filter(Store.store_type == store_type)
    if is_active is not None:
        q = q.filter(Store.is_active == is_active)
    return q.order_by(Store.city, Store.name).all()


@router.post("", response_model=StoreResponse, status_code=201)
def create_store(store: StoreCreate, db: Session = Depends(get_db)):
    """Добавить магазин вручную."""
    existing = db.query(Store).filter(Store.store_code == store.store_code).first()
    if existing:
        raise HTTPException(status_code=409, detail="Магазин с таким store_code уже существует")
    db_store = Store(**store.model_dump())
    db.add(db_store)
    db.commit()
    db.refresh(db_store)
    return db_store


@router.get("/search", response_model=list[StoreResponse])
def search_stores(
    q: str = Query(..., description="Поисковый запрос (город, улица, название)"),
    db: Session = Depends(get_db),
):
    """Поиск магазина по адресу."""
    pattern = f"%{q}%"
    results = db.query(Store).filter(
        Store.is_active == True,  # noqa: E712
        or_(
            Store.city.like(pattern),
            Store.full_address.like(pattern),
            Store.name.like(pattern),
        )
    ).limit(20).all()
    return results


@router.get("/{store_id}", response_model=StoreResponse)
def get_store(store_id: str, db: Session = Depends(get_db)):
    """Получить магазин по ID."""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Магазин не найден")
    return store


@router.put("/{store_id}", response_model=StoreResponse)
def update_store(store_id: int, data: StoreUpdate, db: Session = Depends(get_db)):
    """Обновить магазин."""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Магазин не найден")
    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(store, key, value)
    db.commit()
    db.refresh(store)
    return store


@router.delete("/{store_id}", status_code=204)
def delete_store(store_id: str, db: Session = Depends(get_db)):
    """Удалить магазин."""
    store = db.query(Store).filter(Store.id == store_id).first()
    if not store:
        raise HTTPException(status_code=404, detail="Магазин не найден")
    db.delete(store)
    db.commit()
    return None


@router.post("/select")
def select_store(
    req: SelectStoreRequest,
    db: Session = Depends(get_db),
):
    """Выбрать магазин из БД по адресу и типу → обновить .env."""
    # Строим запрос
    query = db.query(Store).filter(
        Store.is_active == True,  # noqa: E712
        Store.city.like(f"%{req.city}%"),
        Store.store_type == req.store_type,
    )

    if req.street:
        query = query.filter(Store.full_address.like(f"%{req.street}%"))

    store = query.first()

    if not store:
        raise HTTPException(
            status_code=404,
            detail="Магазин не найден в базе. Попробуйте сначала отсканировать магазины."
        )

    # Обновляем .env если нужно
    env_updated = False
    if req.update_env:
        env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), '.env')
        dotenv.load_dotenv(env_path)

        env_vars = {
            'STORE_CODE': store.store_code,
            'STORE_TYPE': store.store_type,
        }

        # Читаем текущий .env
        env_content = {}
        if os.path.exists(env_path):
            with open(env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, value = line.split('=', 1)
                        env_content[key.strip()] = value.strip()

        # Обновляем переменные
        env_content.update(env_vars)

        # Записываем обратно
        with open(env_path, 'w', encoding='utf-8') as f:
            for key, value in env_content.items():
                f.write(f"{key}={value}\n")

        env_updated = True

    return {
        "store_code": store.store_code,
        "store_type": store.store_type,
        "name": store.name,
        "address": store.full_address,
        "city": store.city,
        "env_updated": env_updated,
    }


@router.post("/scan")
def scan_stores(
    req: ScanStoresRequest,
    db: Session = Depends(get_db),
):
    """
    Сканирование магазинов по городу/улице через API Магнита (синхронно).
    """
    # Очистка зависших заданий
    _cleanup_stale_jobs(db)

    # Проверяем нет ли уже запущенного задания
    running_job = db.query(ScanJob).filter(
        ScanJob.job_type == "stores",
        ScanJob.status == "running",
    ).first()

    if running_job:
        raise HTTPException(
            status_code=409,
            detail="Сканирование уже выполняется"
        )

    # Создаём задание
    job = ScanJob(
        job_type="stores",
        store_code=None,
        status="running",
        created_at=datetime.utcnow(),
        started_at=datetime.utcnow(),
        progress=0,
        progress_message="Запуск сканирования",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    stores_api = None
    try:
        from src.server.services.magnit_api import StoresAPI

        stores_api = StoresAPI()

        def update_progress(progress: int, message: str):
            try:
                jp = db.query(ScanJob).filter(ScanJob.id == job.id).first()
                if jp:
                    jp.progress = max(0, progress)
                    jp.progress_message = message
                    db.commit()
            except Exception:
                db.rollback()

        # Формируем поисковый запрос
        query = req.city
        if req.street:
            query += f" {req.street}"

        # Получаем коды типов для API
        type_codes = req.get_store_type_codes()

        # Сканируем через API
        stores_data = stores_api.search_all_stores(
            query=query,
            store_types=type_codes,
            page_size=50,
            progress_callback=update_progress,
        )

        # Сохраняем в БД — пакетная обработка для скорости
        print(f"[scan #{job.id}] Сохранение {len(stores_data)} магазинов...", flush=True)

        # Дедупликация по store_code (API может возвращать дубли)
        seen_codes = {}
        for sd in stores_data:
            code = sd.get("store_code")
            if code and code not in seen_codes:
                seen_codes[code] = sd
        unique_stores = list(seen_codes.values())
        print(f"[scan #{job.id}] Уникальных магазинов: {len(unique_stores)}", flush=True)

        # Получаем все существующие store_code одним запросом
        existing_codes = {row[0]: row[1] for row in db.query(Store.store_code, Store.id).all()}

        to_insert = []
        to_update = []
        for store_data in unique_stores:
            if not store_data.get("full_address"):
                continue
            code = store_data["store_code"]
            if code in existing_codes:
                if req.force_update:
                    to_update.append({
                        "id": existing_codes[code],
                        "store_type": store_data.get("store_type"),
                        "city": store_data.get("city", ""),
                        "address": store_data.get("address", ""),
                        "full_address": store_data.get("full_address", ""),
                        "name": store_data.get("name"),
                    })
            else:
                to_insert.append(Store(
                    store_code=code,
                    store_type=store_data.get("store_type", "Неизвестно"),
                    city=store_data.get("city", ""),
                    address=store_data.get("address", ""),
                    full_address=store_data.get("full_address", ""),
                    name=store_data.get("name"),
                ))

        # Пакетное добавление
        if to_insert:
            db.add_all(to_insert)
            added = len(to_insert)
            print(f"[scan #{job.id}] Вставка {added} магазинов...", flush=True)
            db.commit()
            print(f"[scan #{job.id}] Вставка завершена", flush=True)
        else:
            added = 0

        # Пакетное обновление
        if to_update:
            from sqlalchemy import update as sa_update
            for item in to_update:
                stmt = sa_update(Store).where(Store.id == item["id"]).values(
                    store_type=item["store_type"],
                    city=item["city"],
                    address=item["address"],
                    full_address=item["full_address"],
                    name=item["name"],
                )
                db.execute(stmt)
            updated = len(to_update)
            db.commit()
            print(f"[scan #{job.id}] Обновление {updated} магазинов завершено", flush=True)
        else:
            updated = 0

        job.status = "completed"
        job.finished_at = datetime.utcnow()
        job.items_scanned = len(unique_stores)
        job.items_added = added
        job.items_updated = updated
        job.progress = 100
        job.progress_message = f"Завершено: найдено {len(unique_stores)}, добавлено {added}, обновлено {updated}"
        db.commit()

    except Exception as e:
        print(f"Ошибка сканирования: {e}")
        job.status = "failed"
        job.error_message = str(e)
        job.finished_at = datetime.utcnow()
        db.commit()
    finally:
        if stores_api:
            try:
                stores_api.close()
            except Exception:
                pass

    return {"job_id": job.id, "status": job.status, "items_scanned": job.items_scanned, "items_added": job.items_added}


@router.post("/delete-batch", status_code=204)
def delete_stores_batch(
    req: DeleteStoresRequest,
    db: Session = Depends(get_db),
):
    """Удалить несколько магазинов по ID."""
    if not req.ids:
        raise HTTPException(status_code=400, detail="Список ID пуст")

    db.query(Store).filter(Store.id.in_(req.ids)).delete(synchronize_session=False)
    db.commit()
    return None


@router.get("/by-code/{store_code}", response_model=StoreResponse)
def get_store_by_code(
    store_code: str,
    db: Session = Depends(get_db),
):
    """Получить магазин по store_code (для автозаполнения формы)."""
    store = db.query(Store).filter(Store.store_code == store_code).first()
    if not store:
        raise HTTPException(status_code=404, detail="Магазин с таким кодом не найден в базе")
    return store
