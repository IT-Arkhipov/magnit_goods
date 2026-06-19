"""Утилиты для извлечения города/населённого пункта из адреса."""
import re

# Символы для паттернов
G_CYRILLIC = "\u0433"  # г
G_CAPITAL = "\u0413"   # Г
S_CYRILLIC = "\u0441"  # с (село)
S_CAPITAL = "\u0421"   # С (Село)


def extract_city_from_address(full_address: str) -> str:
    """Извлечь город/населённый пункт из полного адреса.
    
    Возвращает:
    - Город (если есть "г" или "г.")
    - Село (если есть "с" или "С")
    - None, если не удалось извлечь (для сёл без явного указания)
    """
    if not full_address:
        return None
    
    # Убираем почтовый индекс из начала
    addr = re.sub(r"^\d+[\s,]*", "", full_address.strip())
    
    # Паттерны для города (г/Г)
    # Захватываем всё до следующей запятой (многословные города)
    city_patterns = [
        rf",\s*{G_CYRILLIC}\s+([^,]+)",      # ', г Город'
        rf",\s*{G_CYRILLIC}\.\s+([^,]+)",    # ', г. Город'
        rf"^[^,]*{G_CYRILLIC}\s+([^,]+)",    # 'г Город, ...' в начале
        rf"^[^,]*{G_CYRILLIC}\.\s+([^,]+)",  # 'г. Город, ...' в начале
        rf",\s*([^,]+?)\s+{G_CYRILLIC}[,\s]",       # ', Город г'
        rf",\s*([^,]+?)\s+{G_CYRILLIC}\.[,\s]",     # ', Город г.'
        rf",\s*{G_CAPITAL}\s+([^,]+)",       # ', Г Город'
        rf",\s*{G_CAPITAL}\.\s+([^,]+)",     # ', Г. Город'
        rf"^[^,]*{G_CAPITAL}\s+([^,]+)",     # 'Г Город, ...'
        rf"^[^,]*{G_CAPITAL}\.\s+([^,]+)",   # 'Г. Город, ...'
        rf",\s*([^,]+?)\s+{G_CAPITAL}[,\s]", # ', Город Г'
        rf",\s*([^,]+?)\s+{G_CAPITAL}\.[,\s]",  # ', Город Г.'
    ]
    
    for pat in city_patterns:
        m = re.search(pat, addr)
        if m:
            candidate = m.group(1).strip()
            # Обрезаем trailing пробелы и разделители
            candidate = candidate.rstrip(",; ")
            if candidate.isdigit() or len(candidate) > 30 or not candidate:
                continue
            lower = candidate.lower()
            if lower.startswith(("ул", "дом", "д ", "д.", "корп", "корпус", "стр", "строение", "офис")):
                continue
            return candidate
    
    # Паттерны для села/деревни (с/С) - ищем после запятой
    # Сначала ищем "Село с" в формате ", Село с"
    village_patterns = [
        rf",\s*([^\s,;]+(?:\s+[^\s,;]+)?)\s+{S_CYRILLIC}\s*[,;\s]",  # ", Село с" или ", Село с."
        rf",\s*([^\s,;]+(?:\s+[^\s,;]+)?)\s+{S_CYRILLIC}\.\s*[,;\s]", # ", Село с."
        rf",\s*{S_CYRILLIC}\s+([^\s,;]+(?:\s+[^\s,;]+)?)[,;\s]",      # ", с Село"
        rf",\s*{S_CYRILLIC}\.\s+([^\s,;]+(?:\s+[^\s,;]+)?)[,;\s]",    # ", с. Село"
        rf",\s*([^\s,;]+(?:\s+[^\s,;]+)?)\s+{S_CAPITAL}\s*[,;\s]",    # ", Село С"
        rf",\s*([^\s,;]+(?:\s+[^\s,;]+)?)\s+{S_CAPITAL}\.\s*[,;\s]",  # ", Село С."
        rf",\s*{S_CAPITAL}\s+([^\s,;]+(?:\s+[^\s,;]+)?)[,;\s]",       # ", С Село"
        rf",\s*{S_CAPITAL}\.\s+([^\s,;]+(?:\s+[^\s,;]+)?)[,;\s]",     # ", С. Село"
    ]
    
    for pat in village_patterns:
        m = re.search(pat, addr)
        if m:
            candidate = m.group(1).strip()
            if candidate.isdigit() or len(candidate) > 30 or not candidate:
                continue
            lower = candidate.lower()
            # Пропускаем, если это район (р-н) или другое не населённый пункт
            if lower.endswith("р-н") or lower.endswith("район"):
                continue
            if lower.startswith(("ул", "дом", "д ", "д.", "корп", "корпус", "стр", "строение", "офис")):
                continue
            return candidate
    
    # Если не найдено ни города, ни села с явным указанием типа — возвращаем None
    return None