"""
Сервис для открытия товаров в браузере с автоматическим выбором магазина.
Использует Playwright для автоматизации браузера.
"""

from playwright.sync_api import sync_playwright
import time


def open_product_with_store(product_url: str, store_code: str, store_type: str):
    """
    Открыть товар в браузере с автоматическим выбором магазина.
    
    Args:
        product_url: URL товара на magnit.ru
        store_code: Код магазина (например, "992104")
        store_type: Тип магазина (например, "Экстра", "Мини")
    """
    try:
        with sync_playwright() as p:
            # Запускаем браузер в обычном режиме (не headless)
            browser = p.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()
            
            print(f"Открываем magnit.ru для выбора магазина...")
            
            # Переходим на главную страницу Магнита
            page.goto("https://magnit.ru/", wait_until="domcontentloaded")
            time.sleep(2)
            
            # Ищем кнопку выбора магазина
            try:
                # Кликаем на кнопку "Выбрать магазин" или аналогичную
                store_button = page.locator('button:has-text("Выбрать магазин"), button:has-text("магазин"), a:has-text("Выбрать магазин")').first
                if store_button.is_visible(timeout=5000):
                    store_button.click()
                    time.sleep(2)
                    
                    # Вводим адрес или код магазина в поиск
                    search_input = page.locator('input[placeholder*="адрес"], input[placeholder*="Адрес"], input[type="text"]').first
                    if search_input.is_visible(timeout=5000):
                        search_input.fill(store_code)
                        time.sleep(2)
                        
                        # Кликаем на первый результат поиска
                        first_result = page.locator('button:has-text("Выбрать"), div[role="button"]').first
                        if first_result.is_visible(timeout=5000):
                            first_result.click()
                            time.sleep(2)
            except Exception as e:
                print(f"Не удалось автоматически выбрать магазин: {e}")
                print("Пользователь может выбрать магазин вручную")
            
            # Переходим на страницу товара
            print(f"Переходим на страницу товара: {product_url}")
            page.goto(product_url, wait_until="domcontentloaded")
            
            # Оставляем браузер открытым для пользователя
            print("Браузер открыт. Закройте его вручную когда закончите.")
            
            # Ждем, пока пользователь не закроет браузер
            # (не закрываем автоматически)
            
    except Exception as e:
        print(f"Ошибка при открытии товара в браузере: {e}")
