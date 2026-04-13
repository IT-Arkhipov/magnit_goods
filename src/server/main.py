from fastapi import FastAPI, Request, Depends
from starlette.responses import HTMLResponse, FileResponse
from starlette.templating import Jinja2Templates, _TemplateResponse as TemplateResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from sqlalchemy.orm import Session
from typing import Optional
import os

from src.server.database import engine, init_db, get_db
from src.server.models import Store
from src.server.schemas import StoreCreate
from src.server.routes import stores, jobs, catalog, prices
from src.server.scheduler import init_scheduler, shutdown_scheduler
from sqlalchemy import text
import os


# === Инициализация БД ===
init_db()

# === Миграция: конвертация integer ID в хэш-идентификаторы ===
from src.server.database import SessionLocal, engine
from src.server.models import Store, store_hash_id
from sqlalchemy import inspect

def migrate_store_ids():
    """Конвертация integer ID в хэш-идентификаторы (однократно)."""
    inspector = inspect(engine)
    cols = [c["name"] for c in inspector.get_columns("stores")]
    if "id" not in cols:
        return  # таблица ещё не создана

    col_info = next((c for c in inspector.get_columns("stores") if c["name"] == "id"), None)
    col_type = str(col_info["type"]).upper() if col_info else ""
    if "INT" not in col_type:
        return  # уже строка — миграция выполнена

    print("Миграция: конвертация ID магазинов в хэш-формат...", flush=True)

    # Чтение данных
    s1 = SessionLocal()
    try:
        rows = s1.query(Store).all()
        data = [(s.store_code, s.store_type, s.city, s.address, s.full_address, s.name) for s in rows]
    finally:
        s1.close()

    # Пересоздание таблицы
    Store.__table__.drop(engine, checkfirst=True)
    Store.__table__.create(engine)

    # Вставка
    s2 = SessionLocal()
    try:
        from datetime import datetime as dt
        now = dt.utcnow()
        for sc, st, city, addr, fa, name in data:
            new_id = store_hash_id(sc, st, fa)
            s2.add(Store(
                id=new_id, store_code=sc, store_type=st,
                city=city, address=addr, full_address=fa, name=name,
                created_at=now,
            ))
        s2.commit()
        print(f"Миграция завершена: {len(data)} магазинов", flush=True)
    finally:
        s2.close()

migrate_store_ids()

# === Очистка зависших заданий от предыдущего запуска ===
from src.server.routes.stores import _mark_all_running_failed_on_startup

db_session = SessionLocal()
try:
    _mark_all_running_failed_on_startup(db_session)
finally:
    db_session.close()

# === Инициализация планировщика ===
store_code = os.getenv("STORE_CODE")
if store_code:
    init_scheduler(store_code)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения."""
    yield
    # Завершение работы
    shutdown_scheduler()


# === FastAPI приложение ===
app = FastAPI(
    title="Магнит Goods",
    description="Веб-сервер для выбора магазинов и мониторинга цен",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Шаблоны
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

# Функция для рендеринга шаблонов
def render_template(template_name: str, context: dict):
    """Рендер шаблона с правильным контекстом."""
    template = templates.env.get_template(template_name)
    return HTMLResponse(content=template.render(**context))

# === Роуты API ===
app.include_router(stores.router)
app.include_router(jobs.router)
app.include_router(catalog.router)
app.include_router(prices.router)


# === Веб-страницы ===

@app.get("/", response_class=HTMLResponse)
async def page_stores(request: Request, db: Session = Depends(get_db)):
    """Главная — управление магазинами."""
    stores_list = db.query(Store).order_by(text("store_type COLLATE NOCASE, full_address COLLATE NOCASE")).all()
    return render_template(
        "stores.html",
        {"request": request, "page": "stores", "stores": stores_list},
    )


@app.get("/catalog", response_class=HTMLResponse)
async def page_catalog(request: Request, db: Session = Depends(get_db)):
    stores = db.query(Store).filter(Store.is_active == True).all()  # noqa: E712
    return render_template(
        "catalog.html",
        {"request": request, "page": "catalog", "stores": stores},
    )


@app.get("/products", response_class=HTMLResponse)
async def page_products(request: Request, db: Session = Depends(get_db)):
    stores = db.query(Store).filter(Store.is_active == True).all()  # noqa: E712
    return render_template(
        "products.html",
        {"request": request, "page": "products", "stores": stores},
    )


@app.get("/deals", response_class=HTMLResponse)
async def page_deals(request: Request, db: Session = Depends(get_db)):
    stores = db.query(Store).filter(Store.is_active == True).all()  # noqa: E712
    return render_template(
        "deals.html",
        {"request": request, "page": "deals", "stores": stores},
    )


@app.get("/jobs", response_class=HTMLResponse)
async def page_jobs(request: Request, db: Session = Depends(get_db)):
    stores = db.query(Store).filter(Store.is_active == True).all()  # noqa: E712
    return render_template(
        "jobs.html",
        {"request": request, "page": "jobs", "stores": stores},
    )


# Заглушки для HTMX POST
@app.post("/api/stores")
async def create_store_htmx(
    request: Request,
    db: Session = Depends(get_db),
):
    """HTMX-совместимое создание магазина (form data)."""
    form = await request.form()
    store_data = StoreCreate(
        store_code=form["store_code"],
        store_type=form["store_type"],
        city=form["city"],
        address=form["address"],
        full_address=form["full_address"],
        name=form.get("name"),
    )
    existing = db.query(Store).filter(Store.store_code == store_data.store_code).first()
    if existing:
        return HTMLResponse("Магазин с таким кодом уже существует", status_code=409)
    db_store = Store(**store_data.model_dump())
    db.add(db_store)
    db.commit()
    db.refresh(db_store)
    # Вернуть обновлённую таблицу
    stores_list = db.query(Store).order_by(text("store_type COLLATE NOCASE, full_address COLLATE NOCASE")).all()
    return templates.TemplateResponse(
        name="stores_table.html",
        context={"request": request, "stores": stores_list},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.server.main:app", host="0.0.0.0", port=8000, reload=True)
