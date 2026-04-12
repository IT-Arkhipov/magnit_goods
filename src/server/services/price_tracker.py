"""
Сервис отслеживания изменений цен.
Сравнивает текущие цены с предыдущими, генерирует уведомления.
"""
from sqlalchemy.orm import Session
from sqlalchemy import func, and_
from datetime import datetime, timedelta
from typing import Optional

from src.server.models import Product, PriceHistory, Category, ScanJob


class PriceTracker:
    """Отслеживание и анализ изменений цен."""

    def __init__(self, db: Session, store_code: Optional[str] = None):
        self.db = db
        self.store_code = store_code

    def get_decreased_prices(
        self,
        category_id: Optional[int] = None,
        min_discount_percent: float = 0.0,
        limit: int = 100,
    ) -> list[dict]:
        """
        Получить товары со сниженными ценами.

        Args:
            category_id: Фильтр по категории
            min_discount_percent: Минимальный процент скидки
            limit: Лимит результатов

        Returns:
            Список товаров со сниженными ценами
        """
        # Подзапрос для получения последней записи истории
        latest_history = (
            self.db.query(
                PriceHistory.product_id,
                func.max(PriceHistory.recorded_at).label("max_recorded_at")
            )
            .filter(PriceHistory.change_type == "decreased")
            .group_by(PriceHistory.product_id)
            .subquery()
        )

        query = (
            self.db.query(Product, PriceHistory)
            .join(
                latest_history,
                and_(
                    Product.product_id == latest_history.c.product_id,
                    Product.last_price_change.isnot(None),
                )
            )
            .join(
                PriceHistory,
                and_(
                    PriceHistory.product_id == Product.product_id,
                    PriceHistory.recorded_at == latest_history.c.max_recorded_at,
                    PriceHistory.change_type == "decreased",
                )
            )
            .filter(Product.store_code == self.store_code)
        )

        if category_id:
            query = query.filter(Product.category_id == category_id)

        results = query.order_by(PriceHistory.price.desc()).limit(limit).all()

        deals = []
        for product, history in results:
            previous_price = history.price
            current_price = product.price

            if previous_price > 0:
                discount_percent = round(
                    (previous_price - current_price) / previous_price * 100, 1
                )
            else:
                discount_percent = 0

            if discount_percent >= min_discount_percent:
                deals.append({
                    "product_id": product.product_id,
                    "name": product.name,
                    "current_price": current_price,
                    "previous_price": previous_price,
                    "discount_amount": round(previous_price - current_price, 2),
                    "discount_percent": discount_percent,
                    "category_id": product.category_id,
                    "image_url": product.image_url,
                    "in_stock": product.in_stock,
                    "last_price_change": product.last_price_change,
                })

        # Сортируем по проценту скидки
        deals.sort(key=lambda x: x["discount_percent"], reverse=True)
        return deals

    def get_increased_prices(
        self,
        category_id: Optional[int] = None,
        limit: int = 100,
    ) -> list[dict]:
        """
        Получить товары с выросшими ценами.

        Args:
            category_id: Фильтр по категории
            limit: Лимит результатов

        Returns:
            Список товаров с повышенными ценами
        """
        latest_history = (
            self.db.query(
                PriceHistory.product_id,
                func.max(PriceHistory.recorded_at).label("max_recorded_at")
            )
            .filter(PriceHistory.change_type == "increased")
            .group_by(PriceHistory.product_id)
            .subquery()
        )

        query = (
            self.db.query(Product, PriceHistory)
            .join(
                latest_history,
                and_(
                    Product.product_id == latest_history.c.product_id,
                    Product.last_price_change.isnot(None),
                )
            )
            .join(
                PriceHistory,
                and_(
                    PriceHistory.product_id == Product.product_id,
                    PriceHistory.recorded_at == latest_history.c.max_recorded_at,
                    PriceHistory.change_type == "increased",
                )
            )
            .filter(Product.store_code == self.store_code)
        )

        if category_id:
            query = query.filter(Product.category_id == category_id)

        results = query.order_by(PriceHistory.price.desc()).limit(limit).all()

        increased = []
        for product, history in results:
            previous_price = history.price
            current_price = product.price

            if previous_price > 0:
                increase_percent = round(
                    (current_price - previous_price) / previous_price * 100, 1
                )
            else:
                increase_percent = 0

            increased.append({
                "product_id": product.product_id,
                "name": product.name,
                "current_price": current_price,
                "previous_price": previous_price,
                "increase_amount": round(current_price - previous_price, 2),
                "increase_percent": increase_percent,
                "category_id": product.category_id,
                "last_price_change": product.last_price_change,
            })

        increased.sort(key=lambda x: x["increase_percent"], reverse=True)
        return increased

    def get_price_history(
        self,
        product_id: int,
        days: int = 30,
    ) -> dict:
        """
        Получить историю цен для конкретного товара.

        Args:
            product_id: ID товара
            days: Кол-во дней истории

        Returns:
            Данные для графика истории цен
        """
        product = self.db.query(Product).filter(
            Product.product_id == product_id,
            Product.store_code == self.store_code,
        ).first()

        if not product:
            return None

        cutoff_date = datetime.utcnow() - timedelta(days=days)

        history_records = (
            self.db.query(PriceHistory)
            .filter(
                PriceHistory.product_id == product_id,
                PriceHistory.recorded_at >= cutoff_date,
            )
            .order_by(PriceHistory.recorded_at.asc())
            .all()
        )

        history = []
        for record in history_records:
            history.append({
                "date": record.recorded_at.isoformat(),
                "price": record.price,
                "old_price": record.old_price,
                "change_type": record.change_type,
            })

        # Статистика
        prices = [h["price"] for h in history]
        stats = {
            "product": product.name,
            "current_price": product.price,
            "min_price": min(prices) if prices else product.price,
            "max_price": max(prices) if prices else product.price,
            "avg_price": round(sum(prices) / len(prices), 2) if prices else product.price,
            "history": history,
        }

        return stats

    def get_alerts(
        self,
        min_discount_percent: float = 10.0,
        days: int = 7,
        limit: int = 50,
    ) -> list[dict]:
        """
        Получить уведомления о значительных изменениях цен.

        Args:
            min_discount_percent: Минимальный процент изменения
            days: За какие дни показывать
            limit: Лимит результатов

        Returns:
            Список уведомлений
        """
        cutoff_date = datetime.utcnow() - timedelta(days=days)

        # Получаем все изменения цен за период
        changes = (
            self.db.query(PriceHistory, Product)
            .join(
                Product,
                and_(
                    Product.product_id == PriceHistory.product_id,
                    Product.store_code == self.store_code,
                )
            )
            .filter(
                PriceHistory.recorded_at >= cutoff_date,
                PriceHistory.change_type.in_(["decreased", "increased"]),
            )
            .order_by(PriceHistory.recorded_at.desc())
            .limit(limit * 2)  # Берём с запасом, потом отфильтруем
            .all()
        )

        alerts = []
        for history, product in changes:
            # Находим предыдущую цену
            if history.change_type == "decreased" and history.price > 0:
                # Для decreased: history.price — это СТАРАЯ цена, product.price — НОВАЯ
                current_price = product.price
                previous_price = history.price
                change_percent = round(
                    (previous_price - current_price) / previous_price * 100, 1
                )

                if change_percent >= min_discount_percent:
                    alerts.append({
                        "type": "decreased",
                        "product_id": product.product_id,
                        "name": product.name,
                        "current_price": current_price,
                        "previous_price": previous_price,
                        "change_percent": change_percent,
                        "date": history.recorded_at.isoformat(),
                        "image_url": product.image_url,
                    })

        alerts.sort(key=lambda x: x["change_percent"], reverse=True)
        return alerts[:limit]

    def get_statistics(self) -> dict:
        """
        Получить общую статистику по ценам.

        Returns:
            Статистика по изменениям цен
        """
        # Товаров в базе
        total_products = (
            self.db.query(Product)
            .filter(Product.store_code == self.store_code)
            .count()
        )

        # Сниженные цены за последние 7 дней
        decreased_7d = (
            self.db.query(PriceHistory)
            .filter(
                PriceHistory.change_type == "decreased",
                PriceHistory.recorded_at >= datetime.utcnow() - timedelta(days=7),
            )
            .distinct(PriceHistory.product_id)
            .count()
        )

        # Повышенные цены за последние 7 дней
        increased_7d = (
            self.db.query(PriceHistory)
            .filter(
                PriceHistory.change_type == "increased",
                PriceHistory.recorded_at >= datetime.utcnow() - timedelta(days=7),
            )
            .distinct(PriceHistory.product_id)
            .count()
        )

        return {
            "total_products": total_products,
            "decreased_last_7_days": decreased_7d,
            "increased_last_7_days": increased_7d,
            "stable": total_products - decreased_7d - increased_7d,
        }
