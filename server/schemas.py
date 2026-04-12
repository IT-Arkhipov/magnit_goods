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

class ScanStoresRequest(BaseModel):
    city: str
    street: Optional[str] = None
    store_types: list[str] = ["Экстра", "Мини", "Семейный"]
    force_update: bool = False


class SelectStoreRequest(BaseModel):
    city: str
    street: Optional[str] = None
    store_type: str
    update_env: bool = True


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
