
import sqlite3
import json

db_path = "data/confluence.db"
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row
cursor = conn.cursor()

print("--- Table Info ---")
for row in cursor.execute("PRAGMA table_info(s2t_state)"):
    print(dict(row))

print("\n--- Current Data (top 1) ---")
row = cursor.execute("SELECT * FROM s2t_state LIMIT 1").fetchone()
if row:
    d = dict(row)
    # Truncate long fields
    if "metadata_json" in d: d["metadata_json"] = d["metadata_json"][:100] + "..."
    print(d)
else:
    print("No data in s2t_state")

conn.close()
