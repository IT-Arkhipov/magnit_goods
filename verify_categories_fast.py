import json
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

CATEGORIES_FILE = Path("src/data/categories.json")
MAGNIT_URL = "https://magnit.ru/"
API_ENDPOINT = "**/webgate/v2/goods/search"

captured_data = {}


def handle_response(response):
    try:
        if API_ENDPOINT in response.url and response.request.method == "POST":
            post_data = response.request.post_data_json
            if post_data and "categories" in post_data:
                category_id = post_data["categories"][0]
                body = response.json()
                if "category" in body:
                    api_category = body["category"]
                    fast_categories = body.get("fastCategoriesExtended", [])
                    captured_data[category_id] = {
                        "api_id": api_category.get("id"),
                        "api_title": api_category.get("title"),
                        "subcategories": [
                            {"id": sc.get("id"), "title": sc.get("title")}
                            for sc in fast_categories
                        ],
                    }
    except Exception:
        pass


with open(CATEGORIES_FILE, "r", encoding="utf-8") as f:
    categories_data = json.load(f)

root_categories = categories_data.get("root_categories", [])
print(f"Loaded {len(root_categories)} root categories")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        locale="ru-RU",
    )
    page = context.new_page()
    page.on("response", handle_response)

    print("Opening magnit.ru...")
    page.goto(MAGNIT_URL, wait_until="domcontentloaded", timeout=60000)
    time.sleep(2)

    print("Clicking Catalog...")
    catalog_button = page.locator('button:has-text("Каталог")').first
    catalog_button.click()
    time.sleep(2)

    for idx, category in enumerate(root_categories):
        cat_id = category["id"]
        cat_title = category["title"]
        print(f"[{idx + 1}/{len(root_categories)}] {cat_title} (ID: {cat_id})")

        try:
            el = page.locator(f"text={cat_title}").first
            if el.count() > 0:
                el.click()
                time.sleep(0.5)

                link = page.locator('text="Все товары этой категории"').first
                if link.count() > 0:
                    link.click()
                    time.sleep(1)

                    if cat_id in captured_data:
                        cap = captured_data[cat_id]
                        if cap["api_title"] != cat_title:
                            print(f"  MISMATCH: '{cat_title}' -> '{cap['api_title']}'")
                            category["title"] = cap["api_title"]
                        else:
                            print(f"  OK")
                    else:
                        print(f"  API not captured")

                back = page.locator('button:has-text("Назад")').first
                if back.count() > 0:
                    back.click()
                    time.sleep(0.5)
            else:
                print(f"  NOT FOUND")
        except Exception as e:
            print(f"  ERROR: {str(e)[:100]}")

    browser.close()

mismatches = [
    c
    for c in root_categories
    if c["id"] in captured_data and captured_data[c["id"]]["api_title"] != c["title"]
]
if mismatches:
    categories_data["timestamp"] = time.strftime("%Y-%m-%d")
    with open(CATEGORIES_FILE, "w", encoding="utf-8") as f:
        json.dump(categories_data, f, ensure_ascii=False, indent=2)
    print(f"\nUpdated {len(mismatches)} categories")
else:
    print("\nAll categories are up to date")

print("Done")
