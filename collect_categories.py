"""
Скрипт для сбора категорий с magnit.ru через API
Использует requests вместо aiohttp
"""

import json
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import os

# Список категорий для сбора (от "Алкоголь" до "Вода и напитки")
CATEGORIES_TO_COLLECT = [
    ("Алкоголь", 47161),
    ("Готовая еда", 65055),
    ("Молочный прилавок", 63963),
    ("Овощи и фрукты", 63905),
    ("Хлеб и выпечка", 65001),
    ("Бакалея", 64121),
    ("Консервы", 64199),
    ("Птица, мясо", 64243),
    ("Рыба, морепродукты", 4998),
    ("Заморозка", 64467),
    ("Сладости", 64697),
    ("Снеки", 63829),
    ("Чай, кофе, какао", 63873),
    ("Вода и напитки", 63791)
]

def create_session():
    """Создает session с retry policy"""
    session = requests.Session()
    retry = Retry(
        total=3,
        backoff_factor=0.3,
        status_forcelist=[500, 502, 503, 504]
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount('https://', adapter)
    
    # Заголовки как у браузера
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Origin': 'https://magnit.ru',
        'Referer': 'https://magnit.ru/'
    })
    
    return session

def get_category_data(session, category_id):
    """Получает данные категории через API"""
    url = "https://magnit.ru/webgate/v2/goods/search"
    
    payload = {
        "sort": {"order": "desc", "type": "popularity"},
        "pagination": {"limit": 32, "offset": 0},
        "categories": [category_id],
        "includeAdultGoods": True,
        "storeCode": "992104",
        "storeType": "6",
        "catalogType": "1"
    }
    
    try:
        response = session.post(url, json=payload, timeout=30)
        if response.status_code == 200:
            return response.json()
        else:
            print(f"  Статус ответа: {response.status_code}")
    except Exception as e:
        print(f"  Ошибка запроса для категории {category_id}: {e}")
    
    return None

def collect_categories():
    """Собирает данные о категориях с magnit.ru"""
    
    categories_data = []
    session = create_session()
    
    for category_name, category_id in CATEGORIES_TO_COLLECT:
        print(f"Обработка категории: {category_name} (ID: {category_id})")
        
        data = get_category_data(session, category_id)
        
        if data and 'category' in data:
            category_info = {
                'category': data.get('category'),
                'fastCategoriesExtended': data.get('fastCategoriesExtended', []),
                'containerConfig': data.get('containerConfig'),
                'correctedTerm': data.get('correctedTerm'),
                'fastCategories': data.get('fastCategories', [])
            }
            categories_data.append(category_info)
            print(f"  ✓ Данные сохранены для категории: {category_info['category'].get('title')}")
            print(f"  Подкатегорий: {len(category_info['fastCategoriesExtended'])}")
        else:
            print(f"  ✗ Нет данных для категории {category_name}")
    
    # Сохраняем данные в JSON файл
    output_path = os.path.join(os.path.dirname(__file__), 'src', 'data', 'categories.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(categories_data, f, ensure_ascii=False, indent=2)
    
    print(f"\n✓ Всего сохранено категорий: {len(categories_data)}")
    print(f"✓ Файл сохранен: {output_path}")
    
    return categories_data

if __name__ == '__main__':
    collect_categories()