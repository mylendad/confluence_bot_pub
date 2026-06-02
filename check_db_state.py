import json
from pathlib import Path
from app.storage.sqlite import SQLite
from app.storage.metadata_repository import MetadataRepository

db = SQLite(Path("data/confluence.db"))
repo = MetadataRepository(db)

rows = repo.list_datamarts()
print(f"Total datamarts in confluence.db: {len(rows)}")
for row in rows:
    print(f"- {row['name']}")
    facts = json.loads(row['facts_json'])
    for f in facts:
        if f['key'] in ('data_location', 'data_category'):
            print(f"  FOUND: {f['key']} = {f['value']}")
