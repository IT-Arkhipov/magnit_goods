import sqlite3

conn = sqlite3.connect('src/data/magnit.db')
cursor = conn.cursor()
cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='categories'")
result = cursor.fetchone()
print(result[0] if result else "Table not found")
conn.close()
