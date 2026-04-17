"""
Полная проверка соответствия категорий в categories.json и magnit.db.
"""
import sqlite3
import json

# Подключение к БД
conn = sqlite3.connect('src/data/magnit.db')
cursor = conn.cursor()

# Получаем все категории из БД
cursor.execute('SELECT id, magnit_id, name, parent_id FROM categories ORDER BY id')
db_categories = cursor.fetchall()

# Создаем словари для быстрого доступа
by_magnit_id = {cat[1]: {'id': cat[0], 'name': cat[2], 'parent_id': cat[3]} for cat in db_categories if cat[1]}

# Загружаем JSON
with open('src/data/categories.json', 'r', encoding='utf-8') as f:
    json_data = json.load(f)

# Собираем все magnit_id из JSON
json_magnit_ids = set()
json_categories_map = {}

for entry in json_data:
    root_cat = entry.get('category', {})
    root_magnit_id = root_cat.get('id')
    root_name = root_cat.get('title')
    json_magnit_ids.add(root_magnit_id)
    json_categories_map[root_magnit_id] = {'name': root_name, 'type': 'root'}
    
    for subcat in entry.get('fastCategoriesExtended', []):
        sub_magnit_id = subcat.get('id')
        sub_name = subcat.get('title')
        json_magnit_ids.add(sub_magnit_id)
        json_categories_map[sub_magnit_id] = {'name': sub_name, 'type': 'sub'}

print("=== Статистика ===")
print(f"Категорий в JSON: {len(json_magnit_ids)}")
print(f"Категорий в БД: {len(by_magnit_id)}")

# Проверка:哪些 в JSON но нет в БД
only_in_json = json_magnit_ids - set(by_magnit_id.keys())
if only_in_json:
    print(f"\n⚠ Только в JSON ({len(only_in_json)}):")
    for mid in sorted(only_in_json):
        info = json_categories_map[mid]
        print(f"  {info['type']}: {mid} - {info['name']}")
else:
    print("\n✓ Все категории из JSON есть в БД")

# Проверка:哪些 в БД но нет в JSON
only_in_db = set(by_magnit_id.keys()) - json_magnit_ids
if only_in_db:
    print(f"\n⚠ Только в БД ({len(only_in_db)}):")
    for mid in sorted(only_in_db):
        print(f"  {mid} - {by_magnit_id[mid]['name']}")
else:
    print("✓ Все категории в БД есть в JSON")

# Проверка имен
name_mismatches = []
for mid in json_magnit_ids & set(by_magnit_id.keys()):
    json_name = json_categories_map[mid]['name']
    db_name = by_magnit_id[mid]['name']
    if json_name != db_name:
        name_mismatches.append((mid, json_name, db_name))

if name_mismatches:
    print(f"\n⚠ Расхождения в именах ({len(name_mismatches)}):")
    for mid, json_name, db_name in name_mismatches:
        print(f"  {mid}: JSON='{json_name}' vs DB='{db_name}'")
else:
    print("✓ Все имена категорий совпадают")

print("\n=== Итог ===")
if not only_in_json and not only_in_db and not name_mismatches:
    print("categories.json и magnit.db полностью синхронизированы!")
else:
    print("Есть расхождения, см. выше")

conn.close()