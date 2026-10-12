from pydantic import BaseModel
from typing import Optional
from datetime import datetime
from src.server.constants import PREVIEW_STORE_TYPES, STORE_TYPE_MAP


# ===== Store =====


class StoreBase(BaseModel):
    store_code: str
    store_type: str
    city: str
    address: str
    full_address: str
    name: Optional[str] = None
    is_active: bool = True


class StoreCreate(StoreBase):
    pass


class StoreUpdate(BaseModel):
    store_type: Optional[str] = None
    city: Optional[str] = None
    address: Optional[str] = None
    full_address: Optional[str] = None
    name: Optional[str] = None
    is_active: Optional[bool] = None


class StoreResponse(StoreBase):
    id: str
    created_at: datetime

    model_config = {"from_attributes": True}


# ===== Scan Request =====

# Типы для поиска магазинов: UI-лейбл → API код (только PREVIEW_STORE_TYPES)
STORE_TYPE_TO_CODE = {
    v: k for k, v in STORE_TYPE_MAP.items() if v in PREVIEW_STORE_TYPES
}


class ScanStoresRequest(BaseModel):
    city: str
    street: Optional[str] = None
    store_types: list[str] = ["Магнит", "Экстра", "М.Косметик"]
    force_update: bool = False

    def unsupported_store_types(self) -> list[str]:
        """Переданные типы, которых нет в списке поддерживаемых для поиска."""
        return [t for t in self.store_types if t not in STORE_TYPE_TO_CODE]

    def get_store_type_codes(self) -> list[str]:
        """Преобразовать типы в коды API."""
        codes = []
        for t in self.store_types:
            code = STORE_TYPE_TO_CODE.get(t)
            if code:
                codes.append(code)
        return codes if codes else list(STORE_TYPE_TO_CODE.values())


class StorePreviewItem(BaseModel):
    """Один магазин из результатов preview (ещё не в БД)."""

    store_code: str
    store_type: str
    city: str
    address: str
    full_address: str
    name: Optional[str] = None
    exists_in_db: bool = False  # подсветка существующих


class AddSelectedStoresRequest(BaseModel):
    """Добавить выбранные магазины из preview."""

    stores: list[StorePreviewItem]


class SelectStoreRequest(BaseModel):
    city: str
    street: Optional[str] = None
    store_type: str
    update_env: bool = True


class DeleteStoresRequest(BaseModel):
    ids: list[str]


# ===== ScanJob =====


class ScanJobResponse(BaseModel):
    id: int
    job_type: str
    store_code: Optional[str] = None
    status: str
    progress: int = 0
    progress_message: Optional[str] = None
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None
    items_scanned: int = 0
    items_added: int = 0
    items_updated: int = 0
    error_message: Optional[str] = None
    created_at: datetime
    total_stores: int = 0
    current_store_index: int = 0
    current_store_code: Optional[str | int] = None
    current_store_address: Optional[str] = None
    total_categories: int = 0
    current_category_index: int = 0
    current_category_name: Optional[str] = None
    current_category_magnit_id: Optional[int] = None
    current_category_items_total: int = 0
    current_category_items_loaded: int = 0

    model_config = {"from_attributes": True}


# ===== Categories =====


class UpdateCategoriesTrackingRequest(BaseModel):
    """Запрос на обновление отслеживания категорий."""

    category_ids: list[int]


# ===== Products / Prices (схемы ответов; имена и набор полей фиксируют контракт с UI) =====


class ProductListItem(BaseModel):
    """Элемент ответа GET /api/products."""

    product_id: int
    name: str
    price: float
    previous_price: Optional[float] = None
    price_change_percent: Optional[float] = None
    last_price_change: Optional[str] = None
    last_change_price: Optional[float] = None
    last_change_date: Optional[str] = None
    currency: Optional[str] = None
    unit: Optional[str] = None
    image_url: Optional[str] = None
    in_stock: Optional[bool] = None
    category_id: Optional[int] = None
    store_code: str
    category_name: Optional[str] = None
    category_parent_id: Optional[int] = None
    quantity: Optional[int] = None
    is_low_stock: Optional[bool] = None
    pickup_only: Optional[bool] = None
    rating: Optional[float] = None
    scores_count: Optional[int] = None
    comments_count: Optional[int] = None
    seo_code: Optional[str] = None
    is_weighted: Optional[bool] = None
    unit_price: Optional[float] = None
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None


class ProductStats(BaseModel):
    """Ответ GET /api/products/stats."""

    total: int
    in_stock: int
    with_price_decrease: int
    with_price_increase: int
    last_update: Optional[str] = None


class DecreasedPriceItem(BaseModel):
    """Элемент ответа GET /api/prices/decreased."""

    product_id: int
    name: str
    price: float
    previous_price: Optional[float] = None
    change_percent: float
    last_price_change: str
    image_url: Optional[str] = None
