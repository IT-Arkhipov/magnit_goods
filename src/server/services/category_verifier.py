"""
Сервис проверки и обновления категорий через Playwright.
"""

import json
import time
from pathlib import Path
from typing import Optional, Dict
from playwright.sync_api import sync_playwright, Page, Response

CATEGORIES_FILE = Path(__file__).parent.parent.parent / "data" / "categories.json"
MAGNIT_URL = "https://magnit.ru/"
API_ENDPOINT = "**/webgate/v2/goods/search"


class CategoryVerifier:
    def __init__(self, headless: bool = True):
        self.headless = headless
        self.captured_data: Dict[int, dict] = {}
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

    def verify_and_update(self) -> dict:
        categories_data = self.load_categories()
        root_categories = categories_data.get("root_categories", [])
        print(f"Загружено {len(root_categories)} корневых категорий")

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                locale="ru-RU",
            )
            self.page = context.new_page()
            self.page.on("response", self.handle_response)

            print("Opening magnit.ru...")
            self.page.goto(MAGNIT_URL, wait_until="domcontentloaded", timeout=60000)
            time.sleep(3)

            print("Кликаем Каталог...")
            catalog_button = self.page.locator('button:has-text("Каталог")').first
            catalog_button.click()
            time.sleep(2)

            for idx, category in enumerate(root_categories):
                cat_id = category["id"]
                cat_title = category["title"]
                print(
                    f"\n[{idx + 1}/{len(root_categories)}] {cat_title} (ID: {cat_id})"
                )

                try:
                    el = self.page.locator(f"text={cat_title}").first
                    if el.count() > 0:
                        el.click()
                        time.sleep(1)

                        link = self.page.locator(
                            'text="Все товары этой категории"'
                        ).first
                        if link.count() > 0:
                            link.click()
                            time.sleep(2)

                            if cat_id in self.captured_data:
                                cap = self.captured_data[cat_id]
                                if cap["api_title"] != cat_title:
                                    print(f"  ⚠️ '{cat_title}' → '{cap['api_title']}'")
                                    category["title"] = cap["api_title"]
                                else:
                                    print(f"  ✓ OK")
                                print(f"  Подкатегории: {len(cap['subcategories'])}")
                            else:
                                print(f"  ⚠️ API не перехвачен")

                        back = self.page.locator('button:has-text("Назад")').first
                        if back.count() > 0:
                            back.click()
                            time.sleep(1)
                    else:
                        print(f"  ⚠️ Не найдена")
                except Exception as e:
                    print(f"  ❌ {e}")

            browser.close()

        mismatches = [
            c
            for c in root_categories
            if c["id"] in self.captured_data
            and self.captured_data[c["id"]]["api_title"] != c["title"]
        ]
        if mismatches:
            categories_data["timestamp"] = time.strftime("%Y-%m-%d")
            self.save_categories(categories_data)
            print(f"\n✅ Обновлено {len(mismatches)} категорий")
        else:
            print("\n✅ Все актуальны")

        return {
            "total": len(root_categories),
            "checked": len(self.captured_data),
            "updated": len(mismatches),
        }
