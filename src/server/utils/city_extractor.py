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
    
    # ===== Fallback: город без типа "г" =====
    # Формат: "Регион, Город, Улица, Дом" или "Город, Улица, Дом"
    # Город — элемент, не являющийся регионом/улицей/домом.
    STREET_PREFIXES = (
        "ул", "улица", "проспект", "пр-т", "бульвар", "б-р",
        "переулок", "пер", "набережная", "наб", "площадь", "пл",
        "шоссе", "ш", "проезд", "тупик", "мкр", "микрорайон",
    )
    REGION_SUFFIXES = ("республика", "край", "область", "р-н", "район")
    parts = [p.strip() for p in addr.split(",")]

    def _is_valid_city(c: str) -> bool:
        if not c or c.isdigit() or len(c) > 30:
            return False
        lo = c.lower()
        if any(lo.startswith(p) for p in STREET_PREFIXES):
            return False
        if any(lo.startswith(p) for p in ("д ", "дом", "корп", "корпус", "стр", "строение", "офис")):
            return False
        if lo.endswith(("р-н", "район")):
            return False
        if any(s in lo for s in REGION_SUFFIXES):
            return False
        return True

    # Пробуем parts[0] (город без региона), потом parts[1] (город после региона)
    for idx in (0, 1):
        if idx < len(parts):
            candidate = parts[idx].strip()
            if _is_valid_city(candidate):
                return candidate

    return None