"""
Общие константы проекта.
"""

import logging
import os

logger = logging.getLogger(__name__)

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

# Маппинг для API запросов (лейбл → числовой код)
API_STORE_TYPE_CODE: dict[str, str] = {
    name: str(code)
    for name, code in STORE_TYPE_CODES.items()
}

# Типы магазинов, доступные в поиске магазинов (POST /api/stores/preview).
# «Опт» и «Заряд» API поиска магазинов не поддерживает.
PREVIEW_STORE_TYPES: list[str] = [
    "Магнит", "Мини", "Семейный", "Экстра", "Моя цена", "М.Косметик",
]

# Тип магазина по умолчанию (русское название), если его нельзя определить
# ни из записи магазина, ни из конфигурации. Единый для всего проекта.
DEFAULT_STORE_TYPE: str = "Магнит"

_NUMERIC_STORE_TYPE_CODES = set(API_STORE_TYPE_CODE.values())


def get_configured_store_type() -> str:
    """Тип магазина из окружения (STORE_TYPE) или DEFAULT_STORE_TYPE.

    Читается в момент вызова, а не при импорте: .env загружается в main.py
    уже после импорта этого модуля, а POST /api/stores/select меняет
    переменную в работающем процессе.
    """
    return os.getenv("STORE_TYPE") or DEFAULT_STORE_TYPE


def resolve_store_type_code(value: str | int | None = None) -> str:
    """Привести тип магазина к числовому коду для запросов к API Магнита.

    Принимает API-код (``MM``, ``MM_MINI``), русское название (``Магнит``,
    ``Мини``) или числовой код (``1``). Пустое значение заменяется типом из
    конфигурации (:func:`get_configured_store_type`). Нераспознанное значение
    даёт предупреждение и код типа по умолчанию.
    """
    raw = str(value).strip() if value is not None else ""
    if not raw:
        raw = get_configured_store_type().strip()

    name = STORE_TYPE_MAP.get(raw) or STORE_TYPE_MAP.get(raw.upper()) or raw
    if name in API_STORE_TYPE_CODE:
        return API_STORE_TYPE_CODE[name]
    if name in _NUMERIC_STORE_TYPE_CODES:
        return name

    logger.warning(
        "Неизвестный тип магазина %r — используется %r", raw, DEFAULT_STORE_TYPE
    )
    return API_STORE_TYPE_CODE[DEFAULT_STORE_TYPE]
