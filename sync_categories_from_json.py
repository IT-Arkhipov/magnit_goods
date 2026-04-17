"""
Синхронизация категорий из categories.json с базой данных magnit.db.

Алгоритм:
1. Удалить из БД все категории, которых нет в JSON файле
2. Для каждой корневой категории из JSON:
   - Отправить POST запрос к API magnit.ru
   - Обновить/добавить корневую категорию (сравнить название)
   - Добавить/обновить подкатегории из fastCategoriesExtended
"""

import json
import requests
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from datetime import datetime

from src.server.database import SessionLocal, engine, Base
from src.server.models import Category


# Путь к файлу с категориями
CATEGORIES_JSON_PATH = "src/data/categories.json"

# API endpoint
API_URL = "https://magnit.ru/webgate/v2/goods/search"

# Payload шаблон (storeCode и storeType могут быть конфигурируемыми)
PAYLOAD_TEMPLATE = {
    "sort": {"order": "desc", "type": "popularity"},
    "pagination": {"limit": 32, "offset": 0},
    "categories": [],  # Будет заменено на ID категории
    "includeAdultGoods": True,
    "storeCode": "992104",
    "storeType": "6",
    "catalogType": "1"
}


def load_categories_from_json(filepath: str) -> list:
    """Загрузить категории из JSON файла."""
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)


def fetch_category_data_from_api(category_id: int) -> dict | None:
    """
    Отправить запрос к API Магнита для получения данных категории.
    Возвращает ответ или None при ошибке.
    """
    payload = PAYLOAD_TEMPLATE.copy()
    payload["categories"] = [category_id]
    
    try:
        response = requests.post(API_URL, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"Ошибка при запросе к API для категории {category_id}: {e}")
        return None


def sync_categories():
    """Основная функция синхронизации категорий."""
    # Загружаем категории из JSON
    json_data = load_categories_from_json(CATEGORIES_JSON_PATH)
    
    # Создаем словарь ID категорий из JSON для быстрого поиска
    json_category_ids = set()
    for item in json_data:
        root_cat = item.get("category", {})
        if root_cat and "id" in root_cat:
            json_category_ids.add(root_cat["id"])
        
        # Добавляем также ID подкатегорий
        for subcat in item.get("fastCategoriesExtended", []):
            if "id" in subcat:
                json_category_ids.add(subcat["id"])
    
    print(f"Всего уникальных ID категорий в JSON: {len(json_category_ids)}")
    
    # Подключаемся к БД
    db = SessionLocal()
    
    try:
        # Шаг 1: Удалить категории, которых нет в JSON
        print("\n=== Шаг 1: Удаление категорий, которых нет в JSON ===")
        
        # Получаем все категории из БД
        all_categories = db.query(Category).all()
        db_category_ids = {cat.magnit_id for cat in all_categories if cat.magnit_id is not None}
        
        # Категории для удаления
        to_delete = db_category_ids - json_category_ids
        
        if to_delete:
            print(f"Категорий для удаления: {len(to_delete)}")
            # Удаляем сначала подкатегории (у которых есть parent_id)
            deleted_count = 0
            for cat in all_categories:
                if cat.magnit_id in to_delete:
                    db.delete(cat)
                    deleted_count += 1
            db.commit()
            print(f"Удалено записей: {deleted_count}")
        else:
            print("Нет категорий для удаления")
        
        # Шаг 2: Обработать каждую корневую категорию из JSON
        print("\n=== Шаг 2: Синхронизация категорий ===")
        
        for item in json_data:
            root_cat = item.get("category", {})
            if not root_cat or "id" not in root_cat:
                continue
            
            root_id = root_cat["id"]
            root_title = root_cat.get("title", "")
            
            print(f"\nОбработка корневой категории: {root_title} (ID: {root_id})")
            
            # Получаем данные из API
            api_response = fetch_category_data_from_api(root_id)
            
            # Проверяем название корневой категории в ответе API
            api_root_title = root_title  # по умолчанию берем из JSON
            
            if api_response and "categories" in api_response:
                api_categories = api_response["categories"]
                for api_cat in api_categories:
                    if api_cat.get("id") == root_id:
                        api_root_title = api_cat.get("title", root_title)
                        break
            
            # Обновляем или создаем корневую категорию
            existing_cat = db.query(Category).filter(Category.magnit_id == root_id).first()
            
            if existing_cat:
                # Обновляем название если отличается
                if existing_cat.name != api_root_title:
                    print(f"  Обновляем название: '{existing_cat.name}' -> '{api_root_title}'")
                    existing_cat.name = api_root_title
                existing_cat.url = existing_cat.url or f"/catalog/{root_id}"
            else:
                # Создаем новую
                new_cat = Category(
                    magnit_id=root_id,
                    name=api_root_title,
                    url=f"/catalog/{root_id}",
                    parent_id=None,
                    is_tracked=True,
                    created_at=datetime.utcnow()
                )
                db.add(new_cat)
                print(f"  Создана новая категория: {api_root_title}")
            
            # Получаем подкатегории из fastCategoriesExtended
            subcategories = item.get("fastCategoriesExtended", [])
            print(f"  Подкатегорий: {len(subcategories)}")
            
            for subcat in subcategories:
                sub_id = subcat.get("id")
                sub_title = subcat.get("title", "")
                
                if not sub_id:
                    continue
                
                # Проверяем существование подкатегории
                existing_sub = db.query(Category).filter(Category.magnit_id == sub_id).first()
                
                if existing_sub:
                    # Обновляем название если отличается
                    if existing_sub.name != sub_title:
                        print(f"    Обновляем подкатегорию: '{existing_sub.name}' -> '{sub_title}'")
                        existing_sub.name = sub_title
                else:
                    # Создаем новую подкатегорию
                    # Сначала получаем корневую категорию для parent_id
                    db_root = db.query(Category).filter(Category.magnit_id == root_id).first()
                    parent_id = db_root.id if db_root else None
                    
                    new_sub = Category(
                        magnit_id=sub_id,
                        name=sub_title,
                        url=f"/catalog/{sub_id}",
                        parent_id=parent_id,
                        is_tracked=True,
                        created_at=datetime.utcnow()
                    )
                    db.add(new_sub)
                    print(f"    Создана подкатегория: {sub_title}")
        
        # Финальная коммит
        db.commit()
        print("\n=== Синхронизация завершена ===")
        
        # Выводим статистику
        all_cats = db.query(Category).all()
        root_cats = [c for c in all_cats if c.parent_id is None]
        sub_cats = [c for c in all_cats if c.parent_id is not None]
        
        print(f"Всего категорий в БД: {len(all_cats)}")
        print(f"Корневых категорий: {len(root_cats)}")
        print(f"Подкатегорий: {len(sub_cats)}")
        
    except Exception as e:
        db.rollback()
        print(f"Ошибка при синхронизации: {e}")
        raise
    finally:
        db.close()


if __name__ == "__main__":
    sync_categories()