"""
Сервис генерации уведомлений об изменениях цен.
"""

from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Optional

from src.server.models import Product, Category


class NotificationService:
    """Генерация и управление уведомлениями."""

    def __init__(self, db: Session, store_code: Optional[str] = None):
        self.db = db
        self.store_code = store_code

    def generate_daily_report(self) -> dict:
        """
        Сгенерировать ежедневный отчёт об изменениях цен.

        Returns:
            {
                "date": "...",
                "summary": {...},
                "top_deals": [...],
                "new_products": [...],
            }
        """
        today = datetime.utcnow().date()
        yesterday = today - timedelta(days=1)

        # Изменения за вчера (по last_price_change)
        decreased = (
            self.db.query(Product)
            .filter(
                Product.store_code == self.store_code,
                Product.price_change_percent > 0,
                Product.last_price_change >= datetime.combine(yesterday, datetime.min.time()),
                Product.last_price_change < datetime.combine(today, datetime.min.time()),
            )
            .count()
        )
        increased = (
            self.db.query(Product)
            .filter(
                Product.store_code == self.store_code,
                Product.price_change_percent < 0,
                Product.last_price_change >= datetime.combine(yesterday, datetime.min.time()),
                Product.last_price_change < datetime.combine(today, datetime.min.time()),
            )
            .count()
        )

        # Новые товары за вчера
        new_products_count = (
            self.db.query(Product)
            .filter(
                Product.first_seen >= datetime.combine(yesterday, datetime.min.time()),
                Product.first_seen < datetime.combine(today, datetime.min.time()),
            )
            .count()
        )

        # Топ-5 скидок
        top_deals = (
            self.db.query(Product)
            .filter(
                Product.store_code == self.store_code,
                Product.price_change_percent >= 10.0,
                Product.last_price_change.isnot(None),
            )
            .order_by(Product.price_change_percent.desc())
            .limit(5)
            .all()
        )

        return {
            "date": yesterday.isoformat(),
            "summary": {
                "total_changes": decreased + increased,
                "price_decreases": decreased,
                "price_increases": increased,
                "new_products": new_products_count,
            },
            "top_deals": [
                {
                    "product_id": p.product_id,
                    "name": p.name,
                    "price": p.price,
                    "previous_price": p.previous_price,
                    "change_percent": p.price_change_percent,
                    "image_url": p.image_url,
                }
                for p in top_deals
            ],
        }

    def check_new_products_in_tracked_categories(self, days: int = 1) -> list[dict]:
        """
        Проверить новые товары в отслеживаемых категориях.

        Args:
            days: За сколько дней искать

        Returns:
            Список новых товаров
        """
        cutoff = datetime.utcnow() - timedelta(days=days)

        # Получаем отслеживаемые категории
        tracked_categories = (
            self.db.query(Category)
            .filter(
                Category.is_tracked == True,  # noqa: E712
            )
            .all()
        )

        if not tracked_categories:
            return []

        category_ids = [cat.id for cat in tracked_categories]

        # Ищем новые товары
        new_products = (
            self.db.query(Product)
            .filter(
                Product.category_id.in_(category_ids),
                Product.first_seen >= cutoff,
                Product.store_code == self.store_code,
            )
            .order_by(Product.first_seen.desc())
            .all()
        )

        return [
            {
                "product_id": p.product_id,
                "name": p.name,
                "price": p.price,
                "category_id": p.category_id,
                "image_url": p.image_url,
                "first_seen": p.first_seen.isoformat(),
            }
            for p in new_products
        ]

    def check_out_of_stock_to_available(self, days: int = 1) -> list[dict]:
        """
        Проверить товары, которые появились в наличии.

        Args:
            days: За сколько дней искать

        Returns:
            Список товаров
        """
        cutoff = datetime.utcnow() - timedelta(days=days)

        # Товары, которые сейчас в наличии и были обновлены недавно
        products = (
            self.db.query(Product)
            .filter(
                Product.in_stock == True,  # noqa: E712
                Product.last_seen >= cutoff,
                Product.store_code == self.store_code,
            )
            .all()
        )

        # Проверяем, были ли они ранее отсутствуют
        notifications = []
        for product in products:
            # Упрощённая логика — просто возвращаем товары в наличии
            notifications.append(
                {
                    "product_id": product.product_id,
                    "name": product.name,
                    "price": product.price,
                    "image_url": product.image_url,
                    "last_seen": product.last_seen.isoformat(),
                }
            )

        return notifications[:20]  # Ограничиваем

    def format_alert_message(self, alert_type: str, data: dict) -> str:
        """
        Форматировать текст уведомления.

        Args:
            alert_type: Тип уведомления (deal, new_product, in_stock)
            data: Данные уведомления

        Returns:
            Текст уведомления
        """
        if alert_type == "deal":
            return (
                f"🔥 Скидка! {data['name']}\n"
                f"Было: {data.get('previous_price', '?')}₽\n"
                f"Стало: {data['current_price']}₽\n"
                f"Экономия: {data.get('price_change_percent', 0)}%"
            )
        elif alert_type == "new_product":
            return f"🆕 Новый товар: {data['name']} — {data['price']}₽"
        elif alert_type == "in_stock":
            return f"✅ В наличии: {data['name']} — {data['price']}₽"
        else:
            return str(data)
