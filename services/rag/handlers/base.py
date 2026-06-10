from abc import ABC, abstractmethod

from services.rag.models import RAGAnswer


class BaseHandler(ABC):
    def __init__(self, metadata_repo, vector_store, history_repo, answer_generator, query_parser):
        self.metadata_repo = metadata_repo
        self.vector_store = vector_store
        self.history_repo = history_repo
        self.answer_generator = answer_generator
        self.query_parser = query_parser

    @abstractmethod
    def handle(self, question: str) -> RAGAnswer | None:
        pass

    def _source(self, attr) -> dict:
        return {
            "datamart": attr.datamart_name,
            "owner": attr.owner,
            "s2t_file": attr.s2t_file_name,
            "s2t_file_date": str(attr.s2t_file_date) if attr.s2t_file_date else None,
            "target_field": attr.target_field,
            "source_field": attr.source_field,
        }

    def _path(self, *parts: str | None) -> str:
        return ".".join(part for part in parts if part) or "-"

    def filter_attrs_by_datamart(self, attrs, datamart_name: str):
        return [
            attr
            for attr in attrs
            if self.query_parser.matches_datamart(attr.datamart_name, datamart_name, attr.datamart_code)
        ]
