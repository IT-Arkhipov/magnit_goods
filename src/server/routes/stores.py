from fastapi import APIRouter, Depends, HTTPException, Query, Request, BackgroundTasks
from sqlalchemy.orm import Session
from typing import Optional
import os
import dotenv
from datetime import datetime

from sqlalchemy import or_
from src.server.database import get_db
from src.server.models import Store, ScanJob
from src.server.schemas import StoreCreate, StoreUpdate, StoreResponse, SelectStoreRequest, ScanStoresRequest

router = APIRouter(prefix="/api/stores", tags=["Магазины"])


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
def get_store(store_id: int, db: Session = Depends(get_db)):
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
def delete_store(store_id: int, db: Session = Depends(get_db)):
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
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Сканирование магазинов по городу/улице через API Магнита.
    """
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
        status="pending",
        created_at=datetime.utcnow(),
        progress=0,
        progress_message="Задание создано",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    def run_scan():
        job_db = db.query(ScanJob).filter(ScanJob.id == job.id).first()
        if not job_db:
            return

        job_db.status = "running"
        job_db.started_at = datetime.utcnow()
        db.commit()

        stores_api = None
        try:
            from src.server.services.magnit_api import StoresAPI

            stores_api = StoresAPI()

            def update_progress(progress: int, message: str):
                try:
                    job_update = db.query(ScanJob).filter(ScanJob.id == job.id).first()
                    if job_update:
                        job_update.progress = max(0, progress)
                        job_update.progress_message = message
                        db.commit()
                except:
                    pass

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

            # Сохраняем в БД
            added = 0
            updated = 0
            for store_data in stores_data:
                if not store_data.get("full_address"):
                    continue

                # Ищем по store_code
                existing = db.query(Store).filter(
                    Store.store_code == store_data["store_code"]
                ).first()

                if existing and req.force_update:
                    # Обновляем
                    existing.store_type = store_data.get("store_type", existing.store_type)
                    existing.city = store_data.get("city", existing.city)
                    existing.address = store_data.get("address", existing.address)
                    existing.full_address = store_data.get("full_address", existing.full_address)
                    existing.name = store_data.get("name", existing.name)
                    updated += 1
                elif not existing:
                    # Создаём новый
                    new_store = Store(
                        store_code=store_data["store_code"],
                        store_type=store_data.get("store_type", "Неизвестно"),
                        city=store_data.get("city", ""),
                        address=store_data.get("address", ""),
                        full_address=store_data.get("full_address", ""),
                        name=store_data.get("name"),
                    )
                    db.add(new_store)
                    added += 1

            db.commit()

            job_db.status = "completed"
            job_db.finished_at = datetime.utcnow()
            job_db.items_scanned = len(stores_data)
            job_db.items_added = added
            job_db.items_updated = updated
            job_db.progress = 100
            job_db.progress_message = f"Завершено: найдено {len(stores_data)}, добавлено {added}, обновлено {updated}"
            db.commit()

        except Exception as e:
            print(f"Ошибка сканирования: {e}")
            job_db.status = "failed"
            job_db.error_message = str(e)
            job_db.finished_at = datetime.utcnow()
            db.commit()
        finally:
            if stores_api:
                try:
                    stores_api.close()
                except:
                    pass

    background_tasks.add_task(run_scan)

    return {"job_id": job.id, "status": "pending"}


@router.post("/delete-batch", status_code=204)
def delete_stores_batch(
    req: dict,
    db: Session = Depends(get_db),
):
    """Удалить несколько магазинов по ID."""
    ids = req.get("ids", [])
    if not ids:
        raise HTTPException(status_code=400, detail="Список ID пуст")
    
    db.query(Store).filter(Store.id.in_(ids)).delete(synchronize_session=False)
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


@router.post("/scan-by-codes")
def scan_stores_by_codes(
    codes: str = Query(..., description="Список кодов магазинов через запятую"),
    store_type: Optional[str] = Query(None, description="Тип магазина для всех"),
    force_update: bool = Query(False),
    background_tasks: BackgroundTasks = None,
    db: Session = Depends(get_db),
):
    """
    Сканирование магазинов по списку кодов (фоновая задача).
    """
    # Парсим коды
    code_list = [c.strip() for c in codes.split(",") if c.strip()]
    if not code_list:
        raise HTTPException(status_code=400, detail="Список кодов пуст")

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
        status="pending",
        created_at=datetime.utcnow(),
        progress=0,
        progress_message=f"Задание создано: {len(code_list)} магазинов",
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    def run_scan():
        job_db = db.query(ScanJob).filter(ScanJob.id == job.id).first()
        if not job_db:
            return

        job_db.status = "running"
        job_db.started_at = datetime.utcnow()
        db.commit()

        selector = None
        try:
            from src.server.services.store_selector import MagnitStoreSelector

            selector = MagnitStoreSelector(headless=True)
            selector.start()

            def update_progress(progress: int, message: str):
                try:
                    job_update = db.query(ScanJob).filter(ScanJob.id == job.id).first()
                    if job_update:
                        job_update.progress = max(0, progress)
                        job_update.progress_message = message
                        db.commit()
                except:
                    pass

            update_progress(5, "Открытие страницы Магнита...")

            # Открываем страницу выбора магазина
            selector.open_store_selector()
            selector.select_mode_in_store()
            selector.click_select_store_button()

            added = 0
            updated = 0
            failed = 0
            total = len(code_list)

            for i, code in enumerate(code_list):
                progress = 10 + int((i / total) * 80)
                update_progress(progress, f"Сканирую магазин {code} ({i+1}/{total})...")

                try:
                    # Вводим код магазина в поле поиска
                    try:
                        selectors = [
                            "input[placeholder*='Адрес']",
                            "input[placeholder*='адрес']",
                            "input[placeholder*='Код']",
                            ".address-input",
                            "#address-input",
                        ]
                        for sel in selectors:
                            try:
                                input_field = selector.page.locator(sel).first
                                if input_field.is_visible(timeout=2000):
                                    input_field.fill(code)
                                    input_field.press("Enter")
                                    import time
                                    time.sleep(2)
                                    break
                            except:
                                continue
                    except Exception as e:
                        print(f"Ошибка ввода кода {code}: {e}")
                        failed += 1
                        continue

                    # Пытаемся получить данные магазина
                    store_items = selector.get_all_stores_from_list()

                    if store_items:
                        for store_data in store_items:
                            store_data["store_code"] = code
                            if store_type:
                                store_data["store_type"] = store_type

                            if not store_data.get("full_address"):
                                continue

                            # Ищем по store_code
                            existing = db.query(Store).filter(
                                Store.store_code == code
                            ).first()

                            if existing and force_update:
                                for key, value in store_data.items():
                                    if hasattr(existing, key) and value is not None:
                                        setattr(existing, key, value)
                                updated += 1
                            elif not existing:
                                new_store = Store(
                                    store_code=code,
                                    store_type=store_data.get("store_type", store_type or "Неизвестно"),
                                    city=store_data.get("city", "Неизвестно"),
                                    address=store_data.get("address", ""),
                                    full_address=store_data.get("full_address", ""),
                                    name=store_data.get("name", f"Магазин {code}"),
                                )
                                db.add(new_store)
                                added += 1

                            db.commit()
                    else:
                        # Если не нашли через список, создаём заглушку
                        existing = db.query(Store).filter(Store.store_code == code).first()
                        if not existing:
                            new_store = Store(
                                store_code=code,
                                store_type=store_type or "Неизвестно",
                                city="",
                                address="",
                                full_address="",
                                name=f"Магазин {code}",
                            )
                            db.add(new_store)
                            added += 1
                            db.commit()

                except Exception as e:
                    print(f"Ошибка сканирования магазина {code}: {e}")
                    failed += 1
                    continue

            update_progress(95, "Сохранение результатов...")
            db.commit()

            job_db.status = "completed"
            job_db.finished_at = datetime.utcnow()
            job_db.items_scanned = total
            job_db.items_added = added
            job_db.items_updated = updated
            job_db.progress = 100
            job_db.progress_message = f"Завершено: добавлено {added}, обновлено {updated}, ошибок {failed}"
            db.commit()

        except Exception as e:
            print(f"Ошибка сканирования: {e}")
            job_db.status = "failed"
            job_db.error_message = str(e)
            job_db.finished_at = datetime.utcnow()
            db.commit()
        finally:
            if selector:
                try:
                    selector.close()
                except:
                    pass

    background_tasks.add_task(run_scan)

    return {"job_id": job.id, "status": "pending", "codes_count": len(code_list)}
