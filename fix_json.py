import re

# 1. Update metadata_repository.py
file_path = 'app/storage/metadata_repository.py'
with open(file_path, 'r') as f:
    content = f.read()

# We need to change .model_dump() to .model_dump(mode="json")
content = content.replace("s.model_dump()", "s.model_dump(mode='json')")
content = content.replace("f.model_dump()", "f.model_dump(mode='json')")
content = content.replace("c.model_dump()", "c.model_dump(mode='json')")

with open(file_path, 'w') as f:
    f.write(content)
print("Updated app/storage/metadata_repository.py")

# 2. Update metadata_sync_service.py
file_path = 'app/sync/metadata_sync_service.py'
with open(file_path, 'r') as f:
    content = f.read()

content = content.replace("c.model_dump()", "c.model_dump(mode='json')")

with open(file_path, 'w') as f:
    f.write(content)
print("Updated app/sync/metadata_sync_service.py")

