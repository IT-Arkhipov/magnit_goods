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
from src.server.schemas import StoreCreate, StoreUpdate, StoreResponse, SelectStoreRequest, ScanStoresRequest, DeleteStoresRequest, StorePreviewItem, AddSelectedStoresRequest
from src.server.services.magnit_api import STORE_TYPE_MAP

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


@router.post("/preview")
def preview_stores(
    req: ScanStoresRequest,
    db: Session = Depends(get_db),
):
    """Предварительный поиск магазинов без сохранения в БД."""
    # Получаем существующие store_code для подсветки
    existing_codes = {row[0] for row in db.query(Store.store_code).all()}

    stores_api = None
    try:
        from src.server.services.magnit_api import StoresAPI, STORE_TYPE_MAP
        stores_api = StoresAPI()

        # Формируем запрос: город + улица (если есть)
        query = req.city
        if req.street:
            query += f", {req.street}"

        type_codes = req.get_store_type_codes()

        # Ищем через API (без сохранения)
        try:
            result = stores_api.search_stores(
                query=query,
                store_types=type_codes,
                limit=50,
                offset=0,
            )
            stores_data = result.get("stores", [])
            print(f"DEBUG preview_stores: Получено {len(stores_data)} магазинов из API")
        except Exception as api_error:
            print(f"ERROR preview_stores: {api_error}")
            raise HTTPException(
                status_code=502,
                detail=f"Ошибка API Магнита: {str(api_error)}"
            )

        # Дедупликация по store_code и преобразование формата
        seen = {}
        for sd in stores_data:
            # API возвращает: externalId.storeCode, storeTypeV2, address, cityFiasId
            external_id = sd.get("externalId", {})
            code = external_id.get("storeCode") or sd.get("store_code")
            if not code:
                print(f"DEBUG: Пропущен магазин без кода: {sd.get('address')}")
                continue
            
            # Преобразуем формат API в наш формат
            # storeTypeV2: "GM" -> STORE_TYPE_MAP.get("GM") = "Семейный"
            store_type_api = sd.get("storeTypeV2") or sd.get("storeType", "")
            # Удаляем префикс "STORE_TYPE_" если есть
            if store_type_api.startswith("STORE_TYPE_"):
                store_type_api = store_type_api[11:]
            
            store_type_name = STORE_TYPE_MAP.get(store_type_api, store_type_api)
            print(f"DEBUG: Магазин {code}, тип API: {store_type_api}, тип UI: {store_type_name}")
            
            store_info = {
                "store_code": code,
                "store_type": store_type_name,
                "city": sd.get("city", ""),  # Может потребоваться извлечение из cityFiasId
                "address": sd.get("address", ""),
                "full_address": sd.get("address", ""),
                "name": sd.get("name"),
            }
            
            if code not in seen:
                seen[code] = store_info

        print(f"DEBUG: Всего уникальных магазинов: {len(seen)}")

        # Формируем превью
        preview = []
        for sd in seen.values():
            if not sd.get("full_address"):
                print(f"DEBUG: Пропущен магазин без адреса: {sd}")
                continue
            preview.append(StorePreviewItem(
                store_code=sd["store_code"],
                store_type=sd["store_type"],
                city=sd["city"],
                address=sd["address"],
                full_address=sd["full_address"],
                name=sd.get("name"),
                exists_in_db=sd["store_code"] in existing_codes,
            ))

        print(f"DEBUG preview_stores: Сформировано {len(preview)} магазинов для превью")
        return {"total_found": len(preview), "stores": preview}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Внутренняя ошибка сервера: {str(e)}"
        )
    finally:
        if stores_api:
            try:
                stores_api.close()
            except Exception:
                pass


@router.post("/add-selected")
def add_selected_stores(
    req: AddSelectedStoresRequest,
    db: Session = Depends(get_db),
):
    """Добавить выбранные магазины из preview в БД."""
    existing_codes = {row[0] for row in db.query(Store.store_code).all()}

    to_add = []
    skipped = 0
    for s in req.stores:
        if s.store_code in existing_codes:
            skipped += 1
        else:
            to_add.append(Store(
                store_code=s.store_code,
                store_type=s.store_type,
                city=s.city,
                address=s.address,
                full_address=s.full_address,
                name=s.name,
            ))

    if to_add:
        db.add_all(to_add)
        db.commit()

    return {"added": len(to_add), "skipped": skipped}


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
