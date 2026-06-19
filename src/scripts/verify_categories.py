import json
import time
from playwright.sync_api import sync_playwright, Page, Response
from pathlib import Path
from typing import Optional

CATEGORIES_FILE = Path(__file__).parent.parent.parent / "data" / "categories.json"
MAGNIT_URL = "https://magnit.ru/"
API_ENDPOINT = "**/webgate/v2/goods/search"


class CategoryVerifier:
    def __init__(self):
        self.captured_data = {}
        self.page: Optional[Page] = None

    def load_categories(self) -> dict:
        with open(CATEGORIES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_categories(self, data: dict):
        with open(CATEGORIES_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def handle_response(self, response: Response):
        try:
            if API_ENDPOINT in response.url and response.request.method == "POST":
                post_data = response.request.post_data_json
                if post_data and "categories" in post_data:
                    category_id = post_data["categories"][0]
                    body = response.json()
                    if "category" in body:
                        api_category = body["category"]
                        fast_categories = body.get("fastCategoriesExtended", [])
                        self.captured_data[category_id] = {
                            "api_id": api_category.get("id"),
                            "api_title": api_category.get("title"),
                            "subcategories": [
                                {"id": sc.get("id"), "title": sc.get("title")}
                                for sc in fast_categories
                            ],
                        }
        except Exception:
            pass

    def run(self):
        categories_data = self.load_categories()
        root_categories = categories_data.get("root_categories", [])

        print(f"Загружено {len(root_categories)} корневых категорий")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )
            self.page = context.new_page()
            self.page.on("response", self.handle_response)

            print("Открываем magnit.ru...")
            self.page.goto(MAGNIT_URL, wait_until="networkidle")
            time.sleep(2)

            print("Кликаем по кнопке Каталог...")
            catalog_button = self.page.locator('button:has-text("Каталог")').first
            if catalog_button.count() == 0:
                catalog_button = self.page.locator('[class*="catalog"]').first

            catalog_button.click()
            time.sleep(2)

            sidebar = self.page.locator(
                '[class*="sidebar"], [class*="drawer"], [class*="panel"]'
            ).first
            time.sleep(1)

            for idx, category in enumerate(root_categories):
                cat_id = category["id"]
                cat_title = category["title"]
                print(
                    f"\n[{idx + 1}/{len(root_categories)}] Проверяем категорию: {cat_title} (ID: {cat_id})"
                )

                try:
                    category_element = self.page.locator(f"text={cat_title}").first
                    if category_element.count() > 0:
                        category_element.click()
                        time.sleep(1)

                        all_goods_link = self.page.locator(
                            'text="Все товары этой категории"'
                        ).first
                        if all_goods_link.count() > 0:
                            all_goods_link.click()
                            time.sleep(2)

                            if cat_id in self.captured_data:
                                captured = self.captured_data[cat_id]
                                api_id = captured["api_id"]
                                api_title = captured["api_title"]

                                if api_id != cat_id:
                                    print(
                                        f"  ⚠️ ID не совпадает: файл={cat_id}, API={api_id}"
                                    )
                                else:
                                    print(f"  ✓ ID совпадает: {api_id}")

                                if api_title != cat_title:
                                    print(
                                        f"  ⚠️ Название не совпадает: файл={cat_title}, API={api_title}"
                                    )
                                    category["title"] = api_title
                                else:
                                    print(f"  ✓ Название совпадает: {api_title}")

                                print(
                                    f"  Подкатегории ({len(captured['subcategories'])}):"
                                )
                                for sub in captured["subcategories"]:
                                    print(f"    - {sub['title']} (ID: {sub['id']})")
                            else:
                                print(f"  ⚠️ API запрос не перехвачен")
                        else:
                            print(f"  ⚠️ Не найдена ссылка 'Все товары этой категории'")
                    else:
                        print(f"  ⚠️ Категория '{cat_title}' не найдена в сайдбаре")

                    back_button = self.page.locator('button:has-text("Назад")').first
                    if back_button.count() == 0:
                        back_button = self.page.locator('[class*="back"]').first
                    if back_button.count() > 0:
                        back_button.click()
                        time.sleep(1)

                except Exception as e:
                    print(f"  ❌ Ошибка: {e}")

            browser.close()

        mismatches = [
            cat
            for cat in root_categories
            if cat["id"] in self.captured_data
            and self.captured_data[cat["id"]]["api_title"] != cat["title"]
        ]

        if mismatches:
            print(f"\n📝 Найдено {len(mismatches)} несоответствий в названиях")
            update = input("Обновить categories.json? (y/n): ").lower().strip()
            if update == "y":
                for cat in root_categories:
                    if cat["id"] in self.captured_data:
                        cat["title"] = self.captured_data[cat["id"]]["api_title"]

                categories_data["timestamp"] = time.strftime("%Y-%m-%d")
                self.save_categories(categories_data)
                print("✅ Файл обновлен")
        else:
            print("\n✅ Все категории актуальны")


if __name__ == "__main__":
    verifier = CategoryVerifier()
    verifier.run()
