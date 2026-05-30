import json
import logging
from datetime import UTC, datetime

from app.confluence.models import Datamart
from app.storage.sqlite import SQLite

logger = logging.getLogger(__name__)


class PageSnapshotRepository:
    def __init__(self, db: SQLite) -> None:
        self.db = db

    def get(self, datamart_page_id: str) -> tuple[dict[str, int], Datamart] | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "select version_map_json, extracted_data_json from page_snapshots where datamart_page_id = ?",
                (datamart_page_id,),
            ).fetchone()
            if not row:
                return None
            try:
                version_map = json.loads(row["version_map_json"])
                data_dict = json.loads(row["extracted_data_json"])
                return version_map, Datamart.model_validate(data_dict)
            except Exception as exc:
                logger.error("Failed to load page snapshot for %s: %s", datamart_page_id, exc)
                return None

    def upsert(self, datamart_page_id: str, version_map: dict[str, int], datamart: Datamart) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                insert into page_snapshots (datamart_page_id, version_map_json, extracted_data_json, updated_at)
                values (?, ?, ?, ?)
                on conflict(datamart_page_id) do update set
                    version_map_json = excluded.version_map_json,
                    extracted_data_json = excluded.extracted_data_json,
                    updated_at = excluded.updated_at
                """,
                (
                    datamart_page_id,
                    json.dumps(version_map),
                    datamart.model_dump_json(),
                    datetime.now(UTC).isoformat(),
                ),
            )

    def delete(self, datamart_page_id: str) -> None:
        with self.db.connect() as conn:
            conn.execute("delete from page_snapshots where datamart_page_id = ?", (datamart_page_id,))
