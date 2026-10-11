from fastapi import FastAPI, Request, Depends, Query, BackgroundTasks
from starlette.responses import HTMLResponse, RedirectResponse
from starlette.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from sqlalchemy.orm import Session
import os
import logging

from src.server.database import init_db, get_db, SessionLocal
from src.server.models import Store
from src.server.routes import stores, jobs, catalog, prices
from src.server.scheduler import init_scheduler, shutdown_scheduler
from sqlalchemy import text


# === Настройка логирования ===
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Управление жизненным циклом приложения."""
    # Инициализация БД и миграции
    init_db()

    # Очистка зависших заданий от предыдущего запуска
    from src.server.routes.stores import _mark_all_running_failed_on_startup
    db_session = SessionLocal()
    try:
        _mark_all_running_failed_on_startup(db_session)
    finally:
        db_session.close()

    # Инициализация планировщика
    store_code = os.getenv("STORE_CODE")
    if store_code:
        init_scheduler(store_code)

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

ALLOWED_ORIGINS = os.getenv("CORS_ORIGINS", "*").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
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