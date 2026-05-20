from app.confluence.models import Datamart
from app.rag.models import RAGDocument
from app.rag.vector_store import JsonVectorStore
from app.s2t.models import S2TAttribute
from app.storage.document_repository import DocumentRepository
from app.storage.metadata_repository import MetadataRepository
from app.utils.hashing import stable_hash


class RAGIndexer:
    def __init__(
        self,
        metadata_repo: MetadataRepository,
        document_repo: DocumentRepository,
        vector_store: JsonVectorStore,
    ) -> None:
        self.metadata_repo = metadata_repo
        self.document_repo = document_repo
        self.vector_store = vector_store

    def index_datamart(
        self, datamart: Datamart, attributes: list[S2TAttribute]
    ) -> list[RAGDocument]:
        return self.update_datamart(datamart, attributes)

    def update_datamart(
        self, datamart: Datamart, attributes: list[S2TAttribute]
    ) -> list[RAGDocument]:
        self.metadata_repo.upsert_datamart(datamart)
        self.metadata_repo.replace_attributes_for_datamart(datamart.name, attributes)
        documents = [self._attribute_document(datamart, attribute) for attribute in attributes]
        self.document_repo.replace_for_datamart(datamart.name, documents)
        self.vector_store.replace_for_datamart(datamart.name, documents)
        return documents

    def rebuild_from_storage(self) -> list[RAGDocument]:
        attributes = self.metadata_repo.list_attributes()
        documents = [self._attribute_document(None, attribute) for attribute in attributes]
        self.document_repo.replace_all(documents)
        self.vector_store.replace_all(documents)
        return documents

    def _attribute_document(
        self, datamart: Datamart | None, attribute: S2TAttribute
    ) -> RAGDocument:
        source_path = self._path(
            attribute.source_schema,
            attribute.source_table,
            attribute.source_field,
        )
        description = (
            attribute.business_description
            or attribute.target_field_description
            or "не указано"
        )
        text_parts = [
            f"Витрина: {attribute.datamart_name}",
            f"Код: {attribute.datamart_code or 'не указан'}",
            f"Целевая таблица: {self._path(attribute.target_schema, attribute.target_table)}",
            f"Поле: {attribute.target_field or 'не указано'}",
            f"Ответственный: {attribute.owner or 'не указан'}",
            f"Источник: {source_path}",
            f"Логика: {attribute.transformation_logic or 'не указана'}",
            f"Описание: {description}",
        ]
        if attribute.join_condition:
            text_parts.append(f"Join: {attribute.join_condition}")
        if attribute.where_condition:
            text_parts.append(f"Where: {attribute.where_condition}")
        if attribute.group_by:
            text_parts.append(f"Group by: {attribute.group_by}")
        text = ". ".join(text_parts) + "."
        metadata = {
            "datamart_name": attribute.datamart_name,
            "datamart_code": attribute.datamart_code,
            "owner": attribute.owner,
            "stakeholders": [s.model_dump() for s in datamart.stakeholders] if datamart else [],
            "source_type": "s2t",
            "confluence_page_id": datamart.confluence_page_id if datamart else None,
            "confluence_url": datamart.confluence_url if datamart else None,
            "s2t_file_name": attribute.s2t_file_name,
            "s2t_file_date": str(attribute.s2t_file_date) if attribute.s2t_file_date else None,
            "parsed_at": attribute.parsed_at.isoformat(),
            "updated_at": attribute.parsed_at.isoformat(),
            "attribute_name": attribute.target_field,
            "target_schema": attribute.target_schema,
            "target_table": attribute.target_table,
            "target_field": attribute.target_field,
            "source_schema": attribute.source_schema,
            "source_table": attribute.source_table,
            "source_field": attribute.source_field,
            "change_date": None,
            "change_type": "unknown",
        }
        return RAGDocument(id=stable_hash(metadata | {"text": text}), text=text, metadata=metadata)

    @staticmethod
    def _path(*parts: str | None) -> str:
        return ".".join(part for part in parts if part) or "не указано"
