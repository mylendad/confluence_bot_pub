import json
from dataclasses import dataclass
from datetime import datetime

from app.storage.sqlite import SQLite


@dataclass(frozen=True)
class S2TState:
    resource_key: str
    datamart_name: str
    page_id: str | None
    resource_type: str | None
    title: str | None
    file_name: str | None
    url: str | None
    metadata: dict
    metadata_hash: str
    content_hash: str | None
    last_checked_at: datetime
    last_synced_at: datetime | None
    updated_at: datetime | None


class S2TStateRepository:
    def __init__(self, db: SQLite) -> None:
        self.db = db

    def get(self, resource_key: str) -> S2TState | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "select * from s2t_state where resource_key = ?", (resource_key,)
            ).fetchone()
        return self._row_to_state(row) if row else None

    def upsert(
        self,
        *,
        resource_key: str,
        datamart_name: str,
        page_id: str | None,
        resource_type: str | None,
        title: str | None,
        file_name: str | None,
        url: str | None,
        metadata: dict,
        metadata_hash: str,
        content_hash: str | None,
        synced: bool,
        updated_at: datetime | None,
    ) -> None:
        now = datetime.utcnow()
        synced_at = now if synced else None
        with self.db.connect() as conn:
            previous = conn.execute(
                "select last_synced_at from s2t_state where resource_key = ?", (resource_key,)
            ).fetchone()
            if previous and not synced:
                synced_at_text = previous["last_synced_at"]
            else:
                synced_at_text = synced_at.isoformat() if synced_at else None
            conn.execute(
                """
                insert into s2t_state(
                    resource_key, datamart_name, page_id, resource_type, title, file_name,
                    url, metadata_json, metadata_hash, content_hash, last_checked_at,
                    last_synced_at, updated_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(resource_key) do update set
                    datamart_name=excluded.datamart_name,
                    page_id=excluded.page_id,
                    resource_type=excluded.resource_type,
                    title=excluded.title,
                    file_name=excluded.file_name,
                    url=excluded.url,
                    metadata_json=excluded.metadata_json,
                    metadata_hash=excluded.metadata_hash,
                    content_hash=excluded.content_hash,
                    last_checked_at=excluded.last_checked_at,
                    last_synced_at=excluded.last_synced_at,
                    updated_at=excluded.updated_at
                """,
                (
                    resource_key,
                    datamart_name,
                    page_id,
                    resource_type,
                    title,
                    file_name,
                    url,
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True, default=str),
                    metadata_hash,
                    content_hash,
                    now.isoformat(),
                    synced_at_text,
                    updated_at.isoformat() if updated_at else None,
                ),
            )

    def list_all(self) -> list[S2TState]:
        with self.db.connect() as conn:
            rows = conn.execute("select * from s2t_state").fetchall()
        return [self._row_to_state(row) for row in rows]

    @staticmethod
    def _row_to_state(row) -> S2TState:
        return S2TState(
            resource_key=row["resource_key"],
            datamart_name=row["datamart_name"],
            page_id=row["page_id"],
            resource_type=row["resource_type"],
            title=row["title"],
            file_name=row["file_name"],
            url=row["url"],
            metadata=json.loads(row["metadata_json"]),
            metadata_hash=row["metadata_hash"],
            content_hash=row["content_hash"],
            last_checked_at=datetime.fromisoformat(row["last_checked_at"]),
            last_synced_at=datetime.fromisoformat(row["last_synced_at"])
            if row["last_synced_at"]
            else None,
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
        )
