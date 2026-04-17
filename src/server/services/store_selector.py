"""
Сервис выбора магазина через Playwright.
Автоматизирует выбор магазина на сайте magnit.ru.
"""
import time
import re
from typing import Optional
from playwright.sync_api import sync_playwright, Playwright, Page, Browser


class MagnitStoreSelector:
    """Автоматизация выбора магазина через Playwright."""

    def __init__(self, headless: bool = True):
        self.headless = headless
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None

    def start(self):
        """Запустить браузер."""
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=self.headless)
        context = self.browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="ru-RU",
        )
        self.page = context.new_page()

    def close(self):
        """Закрыть браузер."""
        if self.browser:
            self.browser.close()
        if self.playwright:
            self.playwright.stop()

    def open_store_selector(self):
        """Открыть страницу выбора магазина."""
        self.page.goto("https://magnit.ru/", wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)  # Ждём загрузки JS

    def select_mode_in_store(self):
        """
        Выбрать режим выбора магазина.
        На сайте может быть кнопка/переключатель режима выбора.
        """
        # Попытка найти и кликнуть кнопку выбора магазина
        try:
            # Различные возможные селекторы
            selectors = [
                "button:has-text('Выбрать магазин')",
                "a:has-text('Выбрать магазин')",
                "[data-test-id='store-selector']",
                ".store-selector-button",
            ]
            for selector in selectors:
                try:
                    btn = self.page.locator(selector).first
                    if btn.is_visible(timeout=2000):
                        btn.click()
                        time.sleep(1)
                        return True
                except:
                    continue
        except Exception as e:
            print(f"Предупреждение: не удалось выбрать режим: {e}")
        return False

    def click_select_store_button(self):
        """Кликнуть кнопку выбора магазина."""
        try:
            selectors = [
                "button:has-text('Выбрать')",
                ".store-select-btn",
                "[data-test-id='select-store']",
            ]
            for selector in selectors:
                try:
                    btn = self.page.locator(selector).first
                    if btn.is_visible(timeout=2000):
                        btn.click()
                        time.sleep(1)
                        return True
                except:
                    continue
        except Exception as e:
            print(f"Предупреждение: не удалось кликнуть кнопку выбора: {e}")
        return False

    def enter_address(self, address: str):
        """Ввести адрес для поиска магазина."""
        try:
            # Ищем поле ввода адреса
            selectors = [
                "input[placeholder*='Адрес']",
                "input[placeholder*='адрес']",
                "input[placeholder*='Город']",
                "input[name='address']",
                ".address-input",
                "#address-input",
            ]
            for selector in selectors:
                try:
                    input_field = self.page.locator(selector).first
                    if input_field.is_visible(timeout=2000):
                        input_field.fill(address)
                        input_field.press("Enter")
                        time.sleep(2)  # Ждём результатов
                        return True
                except:
                    continue
        except Exception as e:
            print(f"Ошибка ввода адреса: {e}")
        return False

    def select_store_type(self, store_type: str):
        """Выбрать тип магазина (Экстра, Мини, Семейный и т.д.)."""
        try:
            # Ищем чекбокс/кнопку типа магазина
            type_mapping = {
                "Все": ["Все", "All"],
                "Экстра": ["Экстра", "Extra"],
                "Мини": ["Мини", "Mini"],
                "Семейный": ["Семейный", "Family"],
                "Магнит": ["Магнит"],
                "Опт": ["Опт"],
                "Моя цена": ["Моя цена"],
                "Заряд": ["Заряд"],
            }

            labels = type_mapping.get(store_type, [store_type])
            for label in labels:
                selectors = [
                    f"label:has-text('{label}')",
                    f"button:has-text('{label}')",
                    f"input[value='{label}']",
                    f"[data-type='{label.lower()}']",
                ]
                for selector in selectors:
                    try:
                        el = self.page.locator(selector).first
                        if el.is_visible(timeout=1000):
                            el.click()
                            time.sleep(1)
                            return True
                    except:
                        continue
        except Exception as e:
            print(f"Ошибка выбора типа магазина: {e}")
        return False

    def get_all_stores_from_list(self) -> list[dict]:
        """
        Собрать все магазины из текущего списка.

        Возвращает:
            Список словарей с данными магазинов.
        """
        stores = []
        try:
            # Ищем элементы списка магазинов
            selectors = [
                ".store-item",
                ".stores-list-item",
                "[data-test-id='store-item']",
                ".store-card",
                "li.store",
            ]

            items = []
            for selector in selectors:
                items = self.page.locator(selector).all()
                if items:
                    break

            for item in items:
                try:
                    text = item.inner_text(timeout=1000)
                    store_data = self._parse_store_text(text)
                    if store_data:
                        stores.append(store_data)
                except:
                    continue
        except Exception as e:
            print(f"Ошибка сбора магазинов: {e}")

        return stores

    def _parse_store_text(self, text: str) -> Optional[dict]:
        """
        Распарсить текст элемента магазина.

        Пример текста:
        "Магнит Экстра
        Чувашская Республика - Чувашия, г Новочебоксарск, ул Строителей, зд 21"
        """
        lines = [line.strip() for line in text.strip().split('\n') if line.strip()]
        if len(lines) < 2:
            return None

        # Первая строка — название
        name = lines[0]

        # Остальное — адрес
        full_address = ', '.join(lines[1:])

        # Извлекаем город
        city = None
        city_patterns = [
            r',\s*г\s+([\w\-]+)',      # ', г Новочебоксарск'
            r',\s*г\.\s+([\w\-]+)',    # ', г. Новочебоксарск'
            r'\s+г\s+([\w\-]+)',       # ' г Новочебоксарск' (с пробелом перед)
            r'\s+г\.\s+([\w\-]+)',     # ' г. Новочебоксарск'
            r'г\s+([\w\-]+)',          # 'г Новочебоксарск'
            r'г\.\s+([\w\-]+)',        # 'г. Новочебоксарск'
        ]
        for pattern in city_patterns:
            match = re.search(pattern, full_address)
            if match:
                city = match.group(1)
                break

        if not city:
            # Если город не найден с предлогом "г", пробуем взять первую часть адреса до запятой
            parts = full_address.split(',')
            if len(parts) >= 1:
                first_part = parts[0].strip()
                # Если первая часть короткая (до 30 символов) и не содержит "республика", "область" - это город
                if len(first_part) < 30 and 'республика' not in first_part.lower() and 'область' not in first_part.lower():
                    city = first_part
                elif len(parts) > 1:
                    # Ищем в середине адреса (обычно город идёт после региона)
                    for part in parts:
                        part = part.strip()
                        if re.match(r'^[гГ]\.?\s*', part) or 'г ' in part or 'г. ' in part:
                            city_match = re.search(r'[гГ]\.?\s*([\w\-]+)', part)
                            if city_match:
                                city = city_match.group(1)
                                break
            if not city:
                city = "Неизвестно"

        return {
            "name": name,
            "full_address": full_address,
            "city": city,
            "address": full_address.split(city)[-1].strip().lstrip(',').strip() if city else full_address,
        }

    def extract_store_code_from_api(self) -> Optional[str]:
        """
        Попытаться извлечь store_code из сетевых запросов.
        Перехватываем запрос к API при выборе магазина.
        """
        # Можно использовать page.on("response") для перехвата
        # Но в sync API это сложнее, поэтому просто заглушка
        return None

    def run_full_scan(
        self,
        city: str,
        street: Optional[str] = None,
        store_types: list[str] = None,
        progress_callback=None,
    ) -> list[dict]:
        """
        Полный цикл сканирования магазинов.

        Args:
            city: Город
            street: Улица (опционально)
            store_types: Список типов магазинов
            progress_callback: Функция для обновления прогресса (progress, message)

        Returns:
            Список найденных магазинов
        """
        if store_types is None:
            store_types = ["Экстра", "Мини", "Семейный"]

        all_stores = []

        try:
            # 1. Открываем страницу
            self.open_store_selector()
            if progress_callback:
                progress_callback(5, "Открыта страница Магнита")

            # 2. Вводим адрес
            address = city
            if street:
                address += f", {street}"

            self.enter_address(address)
            if progress_callback:
                progress_callback(15, f"Введён адрес: {address}")

            # 3. Для каждого типа собираем магазины
            total_types = len(store_types)
            for i, stype in enumerate(store_types):
                progress = 20 + int((i / total_types) * 60)
                if progress_callback:
                    progress_callback(progress, f"Сканирую тип: {stype}")

                self.select_store_type(stype)
                time.sleep(2)  # Ждём обновления списка

                stores = self.get_all_stores_from_list()
                for store in stores:
                    store["store_type"] = stype
                    if store not in all_stores:
                        all_stores.append(store)

                # Сбрасываем фильтр
                self.select_store_type("Все")
                time.sleep(0.5)

            if progress_callback:
                progress_callback(90, "Сканирование завершено")

            # 4. Добавляем store_code (пока None, будет заполнено позже)
            for store in all_stores:
                store.setdefault("store_code", None)

            if progress_callback:
                progress_callback(100, f"Найдено {len(all_stores)} магазинов")

        except Exception as e:
            if progress_callback:
                progress_callback(-1, f"Ошибка: {str(e)}")
            raise

        return all_stores
