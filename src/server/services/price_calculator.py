"""
Сервис для расчета исторических скидок на основе данных из БД.
"""

from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from src.server.models import PriceHistory, DailyPriceSnapshot


def get_historical_old_price(
    product_id: int,
    store_code: str,
    current_price: float,
    db: Session,
    days_back: int = 14
) -> dict | None:
    """
    Получить последнюю историческую цену товара за указанный период.
    
    Логика:
    1. Ищем в PriceHistory (детальная история изменений)
    2. Если не нашли - ищем в DailyPriceSnapshot (ежедневные снимки)
    3. Возвращаем только если старая цена > текущей (реальная скидка)
    
    Args:
        product_id: ID товара
        store_code: Код магазина
        current_price: Текущая цена товара
        db: Сессия БД
        days_back: Глубина поиска в днях (по умолчанию 14)
    
    Returns:
        {
            "old_price": float,
            "discount_percent": float,
            "price_date": str (ISO format),
            "source": "price_history" | "daily_snapshot"
        } или None если нет исторической скидки
    """
    cutoff_date = datetime.utcnow() - timedelta(days=days_back)
    
    # Ищем в PriceHistory самую раннюю запись за период
    old_record = (
        db.query(PriceHistory)
        .filter(
            PriceHistory.product_id == product_id,
            PriceHistory.store_code == store_code,
            PriceHistory.recorded_at >= cutoff_date
        )
        .order_by(PriceHistory.recorded_at.asc())
        .first()
    )
    
    # Если нашли запись и цена изменилась - возвращаем изменение
    if old_record and old_record.price != current_price:
        change_percent = round((current_price - old_record.price) / old_record.price * 100, 1)
        return {
            "old_price": old_record.price,
            "discount_percent": abs(change_percent),
            "is_increase": change_percent > 0,  # True если цена выросла
            "price_date": old_record.recorded_at.isoformat(),
            "source": "price_history"
        }
    
    # Шаг 2: Ищем в DailyPriceSnapshot самую раннюю запись за период
    snapshot = (
        db.query(DailyPriceSnapshot)
        .filter(
            DailyPriceSnapshot.product_id == product_id,
            DailyPriceSnapshot.store_code == store_code,
            DailyPriceSnapshot.snapshot_date >= cutoff_date.date()
        )
        .order_by(DailyPriceSnapshot.snapshot_date.asc())
        .first()
    )
    
    # Если нашли запись и цена изменилась - возвращаем изменение
    if snapshot and snapshot.price != current_price:
        change_percent = round((current_price - snapshot.price) / snapshot.price * 100, 1)
        return {
            "old_price": snapshot.price,
            "discount_percent": abs(change_percent),
            "is_increase": change_percent > 0,  # True если цена выросла
            "price_date": snapshot.snapshot_date.isoformat(),
            "source": "daily_snapshot"
        }
    
    return None


def get_bulk_historical_prices(
    products: list[dict],
    db: Session,
    days_back: int = 14
) -> dict:
    """
    Bulk-запрос для получения исторических цен множества товаров.
    
    Args:
        products: Список товаров [{"product_id": int, "store_code": str, "current_price": float}]
        db: Сессия БД
        days_back: Глубина поиска в днях
    
    Returns:
        {
            product_id: {old_price, discount_percent, price_date, source} | None
        }
    """
    result = {}
    
    for p in products:
        hist_data = get_historical_old_price(
            p["product_id"],
            p["store_code"],
            p["current_price"],
            db,
            days_back
        )
        # Используем комбинированный ключ: product_id:store_code
        key = f"{p['product_id']}:{p['store_code']}"
        result[key] = hist_data
    
    return result
