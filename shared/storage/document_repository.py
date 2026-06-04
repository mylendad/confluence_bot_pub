import json

from services.rag.models import RAGDocument
from shared.storage.sqlite import SQLite
from shared.utils.hashing import stable_hash


class DocumentRepository:
    """
    Репозиторий для управления документами RAG в базе данных SQLite.
    """
    def __init__(self, db: SQLite) -> None:
        """
        Инициализирует DocumentRepository.
        :param db: Объект SQLite для взаимодействия с базой данных.
        """
        self.db = db

    def replace_all(self, documents: list[RAGDocument]) -> None:
        """
        Удаляет все существующие документы и вставляет новые.
        :param documents: Список объектов RAGDocument для вставки.
        """
        with self.db.connect() as conn:
            conn.execute("delete from documents")
            for doc in documents:
                self._insert_document(conn, doc)

    def replace_for_datamart(self, datamart_name: str, documents: list[RAGDocument]) -> None:
        """
        Заменяет документы для конкретной витрины данных.
        :param datamart_name: Название витрины данных.
        :param documents: Список новых документов для этой витрины.
        """
        with self.db.connect() as conn:
            conn.execute(
                "delete from documents where json_extract(metadata_json, '$.datamart_name') = ?",
                (datamart_name,),
            )
            # Deduplicate documents in memory first to be safe
            seen_ids = set()
            unique_docs = []
            for doc in documents:
                if doc.id not in seen_ids:
                    unique_docs.append(doc)
                    seen_ids.add(doc.id)
            
            for doc in unique_docs:
                self._insert_document(conn, doc)

    def list_documents(self) -> list[RAGDocument]:
        """
        Возвращает список всех документов из базы данных.
        :return: Список объектов RAGDocument.
        """
        with self.db.connect() as conn:
            rows = conn.execute("select * from documents").fetchall()
        return [
            RAGDocument(id=row["id"], text=row["text"], metadata=json.loads(row["metadata_json"]))
            for row in rows
        ]

    @staticmethod
    def _insert_document(conn, doc: RAGDocument) -> None:
        """
        Вспомогательный метод для вставки документа в базу данных.
        :param conn: Соединение с базой данных.
        :param doc: Объект RAGDocument для вставки.
        """
        payload = doc.metadata
        conn.execute(
            """
            insert or replace into documents(id, text, metadata_json, content_hash)
            values (?, ?, ?, ?)
            """,
            (
                doc.id,
                doc.text,
                json.dumps(payload, ensure_ascii=False),
                stable_hash(doc.text),
            ),
        )
