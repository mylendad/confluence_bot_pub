import json
from datetime import datetime

from app.confluence.models import Datamart
from app.s2t.models import S2TAttribute
from app.storage.sqlite import SQLite
from app.utils.hashing import stable_hash


class MetadataRepository:
    def __init__(self, db: SQLite) -> None:
        self.db = db

    def upsert_datamart(self, datamart: Datamart) -> None:
        with self.db.connect() as conn:
            conn.execute(
                """
                insert into datamarts(
                    name, code, confluence_page_id, confluence_url, stakeholders_json,
                    facts_json, release_changes_json, updated_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(name) do update set
                    code=excluded.code,
                    confluence_page_id=excluded.confluence_page_id,
                    confluence_url=excluded.confluence_url,
                    stakeholders_json=excluded.stakeholders_json,
                    facts_json=excluded.facts_json,
                    release_changes_json=excluded.release_changes_json,
                    updated_at=excluded.updated_at
                """,
                (
                    datamart.name,
                    datamart.code,
                    datamart.confluence_page_id,
                    datamart.confluence_url,
                    json.dumps([s.model_dump(mode='json') for s in datamart.stakeholders], ensure_ascii=False),
                    json.dumps([f.model_dump(mode='json') for f in datamart.facts], ensure_ascii=False),
                    json.dumps(
                        [c.model_dump(mode='json') for c in datamart.release_changes],
                        ensure_ascii=False,
                    ),
                    datetime.utcnow().isoformat(),
                ),
            )

    def upsert_attributes(self, attributes: list[S2TAttribute]) -> None:
        with self.db.connect() as conn:
            for attribute in attributes:
                self._upsert_attribute(conn, attribute)

    def replace_attributes_for_datamart(
        self, datamart_name: str, attributes: list[S2TAttribute]
    ) -> None:
        with self.db.connect() as conn:
            conn.execute("delete from attributes where datamart_name = ?", (datamart_name,))
            for attribute in attributes:
                self._upsert_attribute(conn, attribute)

    def list_attributes(self, datamart_name: str | None = None) -> list[S2TAttribute]:
        sql = "select payload_json from attributes"
        params: tuple[str, ...] = ()
        if datamart_name:
            sql += " where datamart_name = ?"
            params = (datamart_name,)
        with self.db.connect() as conn:
            return [
                S2TAttribute.model_validate(json.loads(row["payload_json"]))
                for row in conn.execute(sql, params)
            ]

    def find_attribute_usage(self, attribute_name: str) -> list[S2TAttribute]:
        needle = attribute_name.lower()
        with self.db.connect() as conn:
            rows = conn.execute("select payload_json from attributes").fetchall()
        attrs = [S2TAttribute.model_validate(json.loads(row["payload_json"])) for row in rows]
        return [
            attr
            for attr in attrs
            if needle in {(attr.target_field or "").lower(), (attr.source_field or "").lower()}
        ]

    def get_datamart(self, name: str) -> dict | None:
        with self.db.connect() as conn:
            row = conn.execute(
                "select * from datamarts where lower(name)=lower(?)", (name,)
            ).fetchone()
        return dict(row) if row else None

    def list_datamarts(self) -> list[dict]:
        with self.db.connect() as conn:
            rows = conn.execute("select * from datamarts").fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _upsert_attribute(conn, attribute: S2TAttribute) -> None:
        payload = attribute.model_dump(mode="json")
        conn.execute(
            """
            insert into attributes(
                attribute_key, datamart_name, payload_json, content_hash, parsed_at
            )
            values (?, ?, ?, ?, ?)
            on conflict(attribute_key) do update set
                datamart_name=excluded.datamart_name,
                payload_json=excluded.payload_json,
                content_hash=excluded.content_hash,
                parsed_at=excluded.parsed_at
            """,
            (
                attribute.attribute_key,
                attribute.datamart_name,
                json.dumps(payload, ensure_ascii=False),
                stable_hash(payload),
                attribute.parsed_at.isoformat(),
            ),
        )
