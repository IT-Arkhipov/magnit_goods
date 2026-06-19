"""
Общие константы проекта.
"""

# Жизненный цикл товара, который не находится в сканировании:
# - STALE_DAYS_VISIBLE дней после last_seen товар ещё показывается в API/UI
# - Далее STALE_DAYS_HIDDEN дней товар скрыт (не отображается, но хранится в БД)
# - После суммы (STALE_DAYS_VISIBLE + STALE_DAYS_HIDDEN) дней товар удаляется
STALE_DAYS_VISIBLE: int = 1
STALE_DAYS_HIDDEN: int = 5
STALE_DAYS_DELETE: int = STALE_DAYS_VISIBLE + STALE_DAYS_HIDDEN  # 6

# Числовые коды типов магазинов (для API и БД)
STORE_TYPE_CODES: dict[str, int] = {
    "Магнит": 1,
    "Мини": 2,
    "М.Косметик": 3,
    "Семейный": 5,
    "Экстра": 6,
    "Опт": 7,
    "Заряд": 8,
    "Моя цена": 9,
}

# API код → русское название
STORE_TYPE_MAP: dict[str, str] = {
    "MM": "Магнит",
    "ME": "Экстра",
    "DG": "М.Косметик",
    "GM": "Семейный",
    "MO": "Опт",
    "MC": "Моя цена",
    "ZARYAD": "Заряд",
    "MM_MINI": "Мини",
}

# Обратный маппинг: UI-лейбл → API код
REVERSE_STORE_TYPE_MAP: dict[str, str] = {v: k for k, v in STORE_TYPE_MAP.items()}

# Маппинг для API запросов (лейбл → числовой код)
API_STORE_TYPE_CODE: dict[str, str] = {
    name: str(code)
    for name, code in STORE_TYPE_CODES.items()
}
