import re

# 1. Update metadata_sync_service.py
file_path = 'app/sync/metadata_sync_service.py'
with open(file_path, 'r') as f:
    content = f.read()

old_metadata = """            "file_name": resource.file_name,
        }"""

new_metadata = """            "file_name": resource.file_name,
            "release_changes_hash": str(hash(str([c.model_dump() for c in datamart.release_changes]))),
        }"""

if old_metadata in content:
    content = content.replace(old_metadata, new_metadata)
    with open(file_path, 'w') as f:
        f.write(content)
    print("Updated metadata_sync_service.py")

# 2. Update incremental_updater.py
file_path = 'app/sync/incremental_updater.py'
with open(file_path, 'r') as f:
    content = f.read()

old_updater = """        if not content_changed:
            self.state_repo.upsert(
                resource_key=resource_key,
                datamart_name=snapshot.datamart.name,
                page_id=resource.page_id,
                resource_type=resource.resource_type,
                title=resource.title,
                file_name=file_name,
                url=url,
                metadata=snapshot.metadata,
                metadata_hash=snapshot.metadata_hash,
                content_hash=content_hash,
                synced=True,
                updated_at=resource.updated_at,
            )
            return IncrementalUpdateItem(
                datamart_name=snapshot.datamart.name,
                resource_key=resource_key,
                file_name=file_name,
                metadata_changed=True,
                reasons=[*decision.reasons, "content hash unchanged"],
                will_download=True,
                will_parse=False,
                will_reindex=False,
                content_changed=False,
                content_hash=content_hash,
            )"""

new_updater = """        if not content_changed:
            old_attrs = self.metadata_repo.list_attributes(datamart_name=snapshot.datamart.name)
            documents = self.indexer.update_datamart(snapshot.datamart, old_attrs)
            self.state_repo.upsert(
                resource_key=resource_key,
                datamart_name=snapshot.datamart.name,
                page_id=resource.page_id,
                resource_type=resource.resource_type,
                title=resource.title,
                file_name=file_name,
                url=url,
                metadata=snapshot.metadata,
                metadata_hash=snapshot.metadata_hash,
                content_hash=content_hash,
                synced=True,
                updated_at=resource.updated_at,
            )
            return IncrementalUpdateItem(
                datamart_name=snapshot.datamart.name,
                resource_key=resource_key,
                file_name=file_name,
                metadata_changed=True,
                reasons=[*decision.reasons, "content hash unchanged but metadata updated"],
                will_download=True,
                will_parse=False,
                will_reindex=True,
                content_changed=False,
                content_hash=content_hash,
            )"""

if old_updater in content:
    content = content.replace(old_updater, new_updater)
    with open(file_path, 'w') as f:
        f.write(content)
    print("Updated incremental_updater.py")

