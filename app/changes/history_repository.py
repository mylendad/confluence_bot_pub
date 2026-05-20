from datetime import datetime

from app.changes.models import ChangeLogEntry
from app.storage.sqlite import SQLite


class HistoryRepository:
    def __init__(self, db: SQLite) -> None:
        self.db = db

    def add_many(self, entries: list[ChangeLogEntry]) -> None:
        with self.db.connect() as conn:
            for entry in entries:
                conn.execute(
                    """
                    insert or ignore into change_log(
                        id, datamart_name, datamart_code, entity_type, entity_name, change_type,
                        old_value, new_value, change_date, detected_at, source_url, s2t_file_name
                    ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        entry.id,
                        entry.datamart_name,
                        entry.datamart_code,
                        entry.entity_type,
                        entry.entity_name,
                        entry.change_type,
                        entry.old_value,
                        entry.new_value,
                        entry.change_date.isoformat(),
                        entry.detected_at.isoformat(),
                        entry.source_url,
                        entry.s2t_file_name,
                    ),
                )

    def list_changes(
        self, since: datetime | None = None, datamart_name: str | None = None
    ) -> list[ChangeLogEntry]:
        sql = "select * from change_log where 1=1"
        params: list[str] = []
        if since:
            sql += " and change_date >= ?"
            params.append(since.isoformat())
        if datamart_name:
            sql += " and datamart_name = ?"
            params.append(datamart_name)
        sql += " order by change_date desc"
        with self.db.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            ChangeLogEntry(
                id=row["id"],
                datamart_name=row["datamart_name"],
                datamart_code=row["datamart_code"],
                entity_type=row["entity_type"],
                entity_name=row["entity_name"],
                change_type=row["change_type"],
                old_value=row["old_value"],
                new_value=row["new_value"],
                change_date=datetime.fromisoformat(row["change_date"]),
                detected_at=datetime.fromisoformat(row["detected_at"]),
                source_url=row["source_url"],
                s2t_file_name=row["s2t_file_name"],
            )
            for row in rows
        ]
