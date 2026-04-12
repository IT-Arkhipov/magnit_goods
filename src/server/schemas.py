from pydantic import BaseModel
from typing import Optional
from datetime import datetime


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
    id: int
    created_at: datetime

    model_config = {"from_attributes": True}


# ===== Scan Request =====

# Маппинг типов магазинов: API код → UI-лейбл
# Проверено через API Магнита: UI фильтр "Экстра" → storeTypeV2: ME
STORE_CODE_TO_TYPE = {
    "MM": "Магнит",
    "ME": "Экстра",
    "DG": "М.Косметик",
    "GM": "Гипермаркет",
    "MO": "Опт",
    "MC": "Моя цена",
    "ZARYAD": "Заряд",
}

# Обратный маппинг
STORE_TYPE_TO_CODE = {v: k for k, v in STORE_CODE_TO_TYPE.items()}


class ScanStoresRequest(BaseModel):
    city: str
    street: Optional[str] = None
    store_types: list[str] = ["Магнит", "Экстра", "М.Косметик"]
    force_update: bool = False

    def get_store_type_codes(self) -> list[str]:
        """Преобразовать типы в коды API."""
        codes = []
        for t in self.store_types:
            code = STORE_TYPE_TO_CODE.get(t)
            if code:
                codes.append(code)
        return codes if codes else list(STORE_TYPE_TO_CODE.values())


class SelectStoreRequest(BaseModel):
    city: str
    street: Optional[str] = None
    store_type: str
    update_env: bool = True


class DeleteStoresRequest(BaseModel):
    ids: list[int]


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

    model_config = {"from_attributes": True}
