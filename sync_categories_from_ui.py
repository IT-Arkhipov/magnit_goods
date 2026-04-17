import json
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

CATEGORIES_FILE = Path("src/data/categories.json")
MAGNIT_URL = "https://magnit.ru/"
API_ENDPOINT = "**/webgate/v2/goods/search"

captured_data = {}
ui_categories = []


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

file_categories = {cat["id"]: cat for cat in categories_data.get("root_categories", [])}
print(f"V fayle: {len(file_categories)} kategoriy")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(
        viewport={"width": 1920, "height": 1080}, locale="ru-RU"
    )
    page = context.new_page()
    page.on("response", handle_response)
    print("Otkryvaem...")
    page.goto(MAGNIT_URL, wait_until="domcontentloaded", timeout=60000)
    time.sleep(2)
    catalog_button = page.locator('button:has-text("Каталог")').first
    catalog_button.click()
    time.sleep(3)
    sidebar = page.locator('[class*="sidebar"], [class*="drawer"], nav').first
    sidebar.wait_for(timeout=10000)
    time.sleep(1)
    category_items = page.locator('[class*="category"], [class*="item"], li').all()
    print(f"Naydeno {len(category_items)} elementov")
    for item in category_items[:20]:
        try:
            text = item.text_content().strip()
            if text and len(text) < 50:
                link = item.locator("a, button").first
                if link.count() > 0:
                    ui_categories.append({"title": text})
                    print(f"  UI: {text}")
        except Exception:
            pass
    browser.close()

file_ids = set(file_categories.keys())
ui_titles = {cat["title"] for cat in ui_categories}
file_titles = {cat["title"] for cat in file_categories.values()}
missing = ui_titles - file_titles
print(f"\nMissing in file: {len(missing)}")
for t in missing:
    print(f"  + {t}")
if missing:
    new_id = max(file_ids) + 1 if file_ids else 1
    for title in sorted(missing):
        categories_data["root_categories"].append({"id": new_id, "title": title})
        new_id += 1
    categories_data["total"] = len(categories_data["root_categories"])
    categories_data["timestamp"] = time.strftime("%Y-%m-%d")
    with open(CATEGORIES_FILE, "w", encoding="utf-8") as f:
        json.dump(categories_data, f, ensure_ascii=False, indent=2)
    print(f"Updated: +{len(missing)}")
else:
    print("All OK")
