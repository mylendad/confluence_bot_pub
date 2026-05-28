import json
import sqlite3

conn = sqlite3.connect("data/app.db")
conn.row_factory = sqlite3.Row
cursor = conn.cursor()
rows = cursor.execute("SELECT name, release_changes_json FROM datamarts WHERE release_changes_json IS NOT NULL AND release_changes_json != '[]'").fetchall()

found_done = False
print(f"Found {len(rows)} datamarts with release changes.")
for row in rows:
    changes = json.loads(row["release_changes_json"])
    for change in changes:
        if change.get("jira_done_at"):
            print(f"Datamart: {row['name']} | Jira: {change.get('jira_key')} | Done At: {change.get('jira_done_at')}")
            found_done = True
            break
    if found_done:
        break

if not found_done:
    print("No jira_done_at dates found in the database.")
    if rows:
        print("\nSample of parsed changes:")
        changes = json.loads(rows[0]["release_changes_json"])
        for c in changes[:3]:
            print(json.dumps(c, indent=2, ensure_ascii=False))
conn.close()
