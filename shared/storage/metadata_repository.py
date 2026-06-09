import json
from datetime import datetime

from services.ingestion.confluence.models import Datamart
from services.ingestion.s2t.models import S2TAttribute
from shared.storage.sqlite import SQLite
from shared.utils.hashing import stable_hash


class MetadataRepository:
    """
    Репозиторий для управления метаданными витрин данных и их атрибутов в SQLite.
    """

    def __init__(self, db: SQLite) -> None:
        """
        Инициализирует MetadataRepository.
        :param db: Объект SQLite для взаимодействия с базой данных.
        """
        self.db = db

    def upsert_datamart(self, datamart: Datamart) -> None:
        """
        Добавляет или обновляет информацию о витрине данных.
        :param datamart: Объект Datamart с информацией о витрине.
        """
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
                    json.dumps(
                        [s.model_dump(mode="json") for s in datamart.stakeholders],
                        ensure_ascii=False,
                    ),
                    json.dumps(
                        [f.model_dump(mode="json") for f in datamart.facts], ensure_ascii=False
                    ),
                    json.dumps(
                        [c.model_dump(mode="json") for c in datamart.release_changes],
                        ensure_ascii=False,
                    ),
                    datetime.utcnow().isoformat(),
                ),
            )

    def upsert_attributes(self, attributes: list[S2TAttribute]) -> None:
        """
        Добавляет или обновляет список атрибутов.
        :param attributes: Список объектов S2TAttribute.
        """
        with self.db.connect() as conn:
            for attribute in attributes:
                self._upsert_attribute(conn, attribute)

    def replace_attributes_for_datamart(
        self, datamart_name: str, attributes: list[S2TAttribute]
    ) -> None:
        """
        Удаляет старые атрибуты витрины и вставляет новые.
        :param datamart_name: Название витрины данных.
        :param attributes: Список новых атрибутов S2TAttribute.
        """
        with self.db.connect() as conn:
            conn.execute("delete from attributes where datamart_name = ?", (datamart_name,))
            for attribute in attributes:
                self._upsert_attribute(conn, attribute)

    def list_attributes(self, datamart_name: str | None = None) -> list[S2TAttribute]:
        """
        Возвращает список атрибутов, опционально фильтруя по витрине.
        :param datamart_name: Название витрины для фильтрации.
        :return: Список объектов S2TAttribute.
        """
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
        """
        Ищет использование атрибута по его имени (в источнике или приемнике).
        :param attribute_name: Имя атрибута для поиска.
        :return: Список объектов S2TAttribute, где встречается данное имя.
        """
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
        """
        Возвращает данные о витрине по её имени.
        :param name: Название витрины.
        :return: Словарь с данными витрины или None, если не найдена.
        """
        with self.db.connect() as conn:
            row = conn.execute(
                "select * from datamarts where lower(name)=lower(?)", (name,)
            ).fetchone()
        return dict(row) if row else None

    def delete_datamart(self, name: str) -> None:
        """
        Удаляет витрину и все её атрибуты.
        :param name: Название витрины для удаления.
        """
        with self.db.connect() as conn:
            conn.execute("delete from attributes where datamart_name = ?", (name,))
            conn.execute("delete from datamarts where name = ?", (name,))

    def clear_stale_datamarts(self, active_names: list[str]) -> int:
        """
        Удаляет все витрины, которых нет в списке активных.
        :param active_names: Список названий актуальных витрин.
        :return: Количество удаленных витрин.
        """
        if not active_names:
            return 0
        placeholders = ",".join("?" for _ in active_names)
        with self.db.connect() as conn:
            # Delete attributes first due to potential dependencies
            conn.execute(
                f"delete from attributes where datamart_name not in ({placeholders})", active_names
            )
            cursor = conn.execute(
                f"delete from datamarts where name not in ({placeholders})", active_names
            )
            return cursor.rowcount

    def list_datamarts(self) -> list[dict]:
        """
        Возвращает список всех витрин данных.
        :return: Список словарей с данными витрин.
        """
        with self.db.connect() as conn:
            rows = conn.execute("select * from datamarts").fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _upsert_attribute(conn, attribute: S2TAttribute) -> None:
        """
        Вспомогательный метод для вставки или обновления атрибута.
        :param conn: Соединение с базой данных.
        :param attribute: Объект S2TAttribute для вставки.
        """
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
