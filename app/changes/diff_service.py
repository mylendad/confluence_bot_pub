import json
from datetime import datetime

from app.changes.models import ChangeLogEntry
from app.s2t.models import S2TAttribute
from app.utils.hashing import stable_hash

IMPORTANT_FIELDS = [
    "source_schema",
    "source_table",
    "source_field",
    "join_condition",
    "where_condition",
    "group_by",
    "transformation_logic",
    "target_field_description",
    "refresh_frequency",
]


class DiffService:
    def diff_attributes(
        self,
        old: list[S2TAttribute],
        new: list[S2TAttribute],
        source_url: str | None = None,
    ) -> list[ChangeLogEntry]:
        old_by_key = {item.attribute_key: item for item in old}
        new_by_key = {item.attribute_key: item for item in new}
        changes: list[ChangeLogEntry] = []
        now = datetime.utcnow()

        for key, item in new_by_key.items():
            if key not in old_by_key:
                changes.append(
                    self._entry(item, "added", None, item.model_dump(mode="json"), now, source_url)
                )

        for key, item in old_by_key.items():
            if key not in new_by_key:
                changes.append(
                    self._entry(
                        item, "removed", item.model_dump(mode="json"), None, now, source_url
                    )
                )

        for key, new_item in new_by_key.items():
            old_item = old_by_key.get(key)
            if not old_item:
                continue
            old_value = {field: getattr(old_item, field) for field in IMPORTANT_FIELDS}
            new_value = {field: getattr(new_item, field) for field in IMPORTANT_FIELDS}
            if old_value != new_value:
                changes.append(
                    self._entry(new_item, "modified", old_value, new_value, now, source_url)
                )
        return changes

    def _entry(
        self,
        item: S2TAttribute,
        change_type: str,
        old_value: object,
        new_value: object,
        now: datetime,
        source_url: str | None,
    ) -> ChangeLogEntry:
        payload = {
            "key": item.attribute_key,
            "change_type": change_type,
            "old": old_value,
            "new": new_value,
            "detected_at": now.isoformat(),
        }
        return ChangeLogEntry(
            id=stable_hash(payload),
            datamart_name=item.datamart_name,
            datamart_code=item.datamart_code,
            entity_type="attribute",
            entity_name=item.target_field or item.attribute_key,
            change_type=change_type,
            old_value=json.dumps(old_value, ensure_ascii=False, default=str)
            if old_value is not None
            else None,
            new_value=json.dumps(new_value, ensure_ascii=False, default=str)
            if new_value is not None
            else None,
            change_date=now,
            detected_at=now,
            source_url=source_url,
            s2t_file_name=item.s2t_file_name,
        )
