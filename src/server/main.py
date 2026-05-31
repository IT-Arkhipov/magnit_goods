from fastapi import FastAPI, Request, Depends, Query, BackgroundTasks
from starlette.responses import HTMLResponse, FileResponse, RedirectResponse
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
from src.server.models import Store, Category, store_hash_id
from sqlalchemy import inspect


def migrate_store_ids():
    """Конвертация integer ID в хэш-идентификаторы (однократно)."""
    inspector = inspect(engine)
    cols = [c["name"] for c in inspector.get_columns("stores")]
    if "id" not in cols:
        return  # таблица ещё не создана

    col_info = next(
        (c for c in inspector.get_columns("stores") if c["name"] == "id"), None
    )
    col_type = str(col_info["type"]).upper() if col_info else ""
    if "INT" not in col_type:
        return  # уже строка — миграция выполнена

    print("Миграция: конвертация ID магазинов в хэш-формат...", flush=True)

    # Чтение данных
    s1 = SessionLocal()
    try:
        rows = s1.query(Store).all()
        data = [
            (s.store_code, s.store_type, s.city, s.address, s.full_address, s.name)
            for s in rows
        ]
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
            s2.add(
                Store(
                    id=new_id,
                    store_code=sc,
                    store_type=st,
                    city=city,
                    address=addr,
                    full_address=fa,
                    name=name,
                    created_at=now,
                )
            )
        s2.commit()
        print(f"Миграция завершена: {len(data)} магазинов", flush=True)
    finally:
        s2.close()


migrate_store_ids()


def migrate_categories():
    """Обновить структуру таблицы категорий (добавить code, url, убрать category_id)."""
    inspector = inspect(engine)

    # Проверяем, есть ли таблица
    if "categories" not in inspector.get_table_names():
        return  # таблица ещё не создана

    cols = [c["name"] for c in inspector.get_columns("categories")]

    # Если структура уже правильная, ничего не делаем
    if "code" in cols and "url" in cols and "parent_id" in cols:
        return  # структура уже обновлена

    # Если есть старое поле category_id, нужна миграция
    if "category_id" in cols and "code" not in cols:
        print("Миграция: обновление структуры категорий...", flush=True)

        # Удаляем старую таблицу
        Category.__table__.drop(engine, checkfirst=True)
        Category.__table__.create(engine)

        print("Структура категорий обновлена. Загрузите каталог из JSON.", flush=True)
        return

    # Если есть store_code, убираем его
    if "store_code" in cols:
        print("Миграция: удаление store_code из категорий...", flush=True)
        Category.__table__.drop(engine, checkfirst=True)
        Category.__table__.create(engine)
        print("Миграция категорий завершена", flush=True)


migrate_categories()

# === Миграция: добавление поля shop_type в таблицу stores ===
def migrate_add_shop_type():
    """Добавить поле shop_type в таблицу stores (однократно)."""
    inspector = inspect(engine)
    cols = [c["name"] for c in inspector.get_columns("stores")]
    
    if "shop_type" not in cols:
        print("Миграция: добавление поля shop_type в таблицу stores...", flush=True)
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE stores ADD COLUMN shop_type INTEGER"))
            conn.commit()
        print("Поле shop_type добавлено в таблицу stores", flush=True)

migrate_add_shop_type()

# === Миграция: заполнение поля shop_type для известных типов магазинов ===
def migrate_fill_shop_type():
    """Заполнить поле shop_type на основе store_type."""
    db_session = SessionLocal()
    try:
        # Маппинг store_type на числовые коды (из magnit_api.py)
        shop_type_mapping = {
            "Магнит": 1,
            "Мини": 2,
            "М.Косметик": 3,
            "Семейный": 5,
            "Экстра": 6,
            "Опт": 7,
            "Заряд": 8,
            "Моя цена": 9,
        }
        
        # Проверяем, есть ли уже заполненные значения
        filled_count = db_session.query(Store).filter(Store.shop_type != None).count()
        if filled_count > 0:
            return  # уже заполнено
        
        print("Миграция: заполнение поля shop_type...", flush=True)
        
        for store_type, shop_type_code in shop_type_mapping.items():
            stores = db_session.query(Store).filter(Store.store_type == store_type).all()
            for store in stores:
                store.shop_type = shop_type_code
            if len(stores) > 0:
                print(f"  Обновлено {len(stores)} магазинов типа '{store_type}' -> код {shop_type_code}", flush=True)
        
        db_session.commit()
        print("Поле shop_type успешно заполнено", flush=True)
    except Exception as e:
        print(f"Ошибка при заполнении shop_type: {e}", flush=True)
        db_session.rollback()
    finally:
        db_session.close()

migrate_fill_shop_type()

# === Миграция: добавление поля last_scan_found в таблицу products ===
def migrate_add_last_scan_found():
    """Добавить поле last_scan_found в таблицу products (однократно)."""
    inspector = inspect(engine)
    cols = [c["name"] for c in inspector.get_columns("products")]
    
    if "last_scan_found" not in cols:
        print("Миграция: добавление поля last_scan_found в таблицу products...", flush=True)
        with engine.connect() as conn:
            conn.execute(text("ALTER TABLE products ADD COLUMN last_scan_found DATETIME"))
            conn.commit()
        print("Поле last_scan_found добавлено в таблицу products", flush=True)

migrate_add_last_scan_found()

# === Миграция: добавление полей прогресса в таблицу scan_jobs ===
def migrate_add_scan_job_progress_fields():
    """Добавить поля прогресса в таблицу scan_jobs."""
    inspector = inspect(engine)
    cols = [c["name"] for c in inspector.get_columns("scan_jobs")]
    
    new_fields = [
        ("total_stores", "INTEGER DEFAULT 0"),
        ("current_store_index", "INTEGER DEFAULT 0"),
        ("current_store_code", "STRING"),
        ("current_store_address", "STRING"),
        ("total_categories", "INTEGER DEFAULT 0"),
        ("current_category_index", "INTEGER DEFAULT 0"),
        ("current_category_name", "STRING"),
        ("current_category_magnit_id", "INTEGER"),
        ("current_category_items_total", "INTEGER DEFAULT 0"),
        ("current_category_items_loaded", "INTEGER DEFAULT 0"),
    ]
    
    for field_name, field_type in new_fields:
        if field_name not in cols:
            print(f"Миграция: добавление поля {field_name} в таблицу scan_jobs...", flush=True)
            with engine.connect() as conn:
                conn.execute(text(f"ALTER TABLE scan_jobs ADD COLUMN {field_name} {field_type}"))
                conn.commit()
            print(f"Поле {field_name} добавлено в таблицу scan_jobs", flush=True)

migrate_add_scan_job_progress_fields()

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
    stores_list = (
        db.query(Store)
        .order_by(text("store_type COLLATE NOCASE, full_address COLLATE NOCASE"))
        .all()
    )
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


@app.get("/test-discount", response_class=HTMLResponse)
async def page_test_discount(request: Request):
    return render_template(
        "test_discount.html",
        {"request": request},
    )


@app.get("/test-stores-loading", response_class=HTMLResponse)
async def page_test_stores_loading(request: Request):
    return render_template(
        "test_stores_loading.html",
        {"request": request},
    )



@app.get("/jobs", response_class=HTMLResponse)
async def page_jobs(request: Request, db: Session = Depends(get_db)):
    stores = db.query(Store).filter(Store.is_active == True).all()  # noqa: E712
    return render_template(
        "jobs.html",
        {"request": request, "page": "jobs", "stores": stores},
    )


@app.get("/shopping-list", response_class=HTMLResponse)
async def page_shopping_list(request: Request):
    """Страница списка покупок."""
    return render_template(
        "shopping_list.html",
        {"request": request, "page": "shopping-list"},
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
    stores_list = (
        db.query(Store)
        .order_by(text("store_type COLLATE NOCASE, full_address COLLATE NOCASE"))
        .all()
    )
    return templates.TemplateResponse(
        name="stores_table.html",
        context={"request": request, "stores": stores_list},
    )


@app.get("/redirect-to-product")
async def redirect_to_product(
    url: str = Query(...),
    shop_code: str = Query(...),
    x_shop_type: str = Query(...),
):
    """Промежуточный редирект для установки cookies перед переходом на magnit.ru"""
    response = RedirectResponse(url=url)
    response.set_cookie("shopCode", shop_code, max_age=3600, path="/")
    response.set_cookie("x_shop_type", x_shop_type, max_age=3600, path="/")
    return response


@app.get("/open-product-in-browser")
async def open_product_in_browser(
    product_url: str = Query(...),
    store_code: str = Query(...),
    store_type: str = Query(...),
    background_tasks: BackgroundTasks = None,
):
    """Открыть товар в браузере с автоматическим выбором магазина через Playwright"""
    from src.server.services.product_opener import open_product_with_store
    
    # Запускаем в фоне, чтобы не блокировать ответ
    import threading
    thread = threading.Thread(
        target=open_product_with_store,
        args=(product_url, store_code, store_type)
    )
    thread.start()
    
    return {"status": "opening", "message": "Открываем товар в браузере..."}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("src.server.main:app", host="0.0.0.0", port=8000, reload=True)
