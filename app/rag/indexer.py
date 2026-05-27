import json

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
        documents = [
            *[self._attribute_document(datamart, attribute) for attribute in attributes],
            *self._datamart_documents(datamart),
        ]
        self.document_repo.replace_for_datamart(datamart.name, documents)
        self.vector_store.replace_for_datamart(datamart.name, documents)
        return documents

    def rebuild_from_storage(self) -> list[RAGDocument]:
        attributes = self.metadata_repo.list_attributes()
        documents = [self._attribute_document(None, attribute) for attribute in attributes]
        for datamart in self.metadata_repo.list_datamarts():
            documents.extend(self._stored_datamart_documents(datamart))
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

    def _datamart_documents(self, datamart: Datamart) -> list[RAGDocument]:
        documents: list[RAGDocument] = []
        for fact in datamart.facts:
            text = (
                f"Витрина: {datamart.name}. Показатель: {fact.label}. "
                f"Значение: {fact.value}."
            )
            if fact.links:
                text += " Ссылки: " + "; ".join(
                    f"{link.get('title')}: {link.get('url')}" for link in fact.links
                )
            metadata = {
                "datamart_name": datamart.name,
                "source_type": "datamart_fact",
                "fact_key": fact.key,
                "fact_label": fact.label,
                "confluence_page_id": datamart.confluence_page_id,
                "confluence_url": datamart.confluence_url,
            }
            documents.append(
                RAGDocument(id=stable_hash(metadata | {"text": text}), text=text, metadata=metadata)
            )
        for change in datamart.release_changes:
            text_parts = [
                f"Витрина: {datamart.name}",
                "Изменения в релизах",
                f"Версия: {change.version or 'не указана'}",
                f"Jira: {change.jira_key or 'не указана'}",
                f"Название Jira: {change.jira_title or 'не указано'}",
                f"Тип: {change.change_type or 'не указан'}",
                f"Суть: {change.summary or 'не указана'}",
                f"Статус: {change.status or 'не указан'}",
            ]
            if change.jira_created_at:
                text_parts.append(f"Создана в Jira: {change.jira_created_at.date()}")
            if change.jira_last_activity_value:
                text_parts.append(f"Результат из Jira: {change.jira_last_activity_value}")
            
            text = ". ".join(text_parts) + "."
            metadata = {
                "datamart_name": datamart.name,
                "source_type": "release_change",
                "version": change.version,
                "jira_key": change.jira_key,
                "jira_created_at": change.jira_created_at.isoformat() if change.jira_created_at else None,
                "jira_last_activity_value": change.jira_last_activity_value,
                "change_type": change.change_type,
                "source_url": change.source_url,
                "confluence_url": datamart.confluence_url,
            }
            documents.append(
                RAGDocument(id=stable_hash(metadata | {"text": text}), text=text, metadata=metadata)
            )
        return documents

    def _stored_datamart_documents(self, row: dict) -> list[RAGDocument]:
        datamart = Datamart(
            name=row["name"],
            code=row.get("code"),
            confluence_page_id=row.get("confluence_page_id") or "",
            confluence_url=row.get("confluence_url") or "",
            stakeholders=[],
            facts=json.loads(row.get("facts_json") or "[]"),
            release_changes=json.loads(row.get("release_changes_json") or "[]"),
        )
        return self._datamart_documents(datamart)

    @staticmethod
    def _path(*parts: str | None) -> str:
        return ".".join(part for part in parts if part) or "не указано"
