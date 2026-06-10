from services.rag.handlers.base import BaseHandler
from services.rag.models import RAGAnswer


class OwnerLookupHandler(BaseHandler):
    def handle(self, question: str) -> RAGAnswer | None:
        attrs = self.metadata_repo.list_attributes()
        if not attrs:
            return RAGAnswer(
                answer="Данных по владельцам нет. Сначала распарсьте S2T и соберите RAG.",
                sources=[],
            )

        requested_datamart = self.query_parser.extract_datamart_name(question)
        if requested_datamart:
            matched = self.filter_attrs_by_datamart(attrs, requested_datamart)
            if not matched:
                if self.metadata_repo.get_datamart(requested_datamart):
                    return RAGAnswer(
                        answer=f"Для витрины `{requested_datamart}` файл S2T не найден.",
                        sources=[],
                    )
                available = ", ".join(sorted({attr.datamart_name for attr in attrs}))
                return RAGAnswer(
                    answer=(
                        f"Данных по витрине `{requested_datamart}` нет. "
                        f"Доступные витрины: {available or '-'}"
                    ),
                    sources=[],
                )
            attrs = matched

        owner_to_fields: dict[str, list[str]] = {}
        for attr in attrs:
            if not attr.owner:
                continue
            target = self._path(attr.target_schema, attr.target_table, attr.target_field)
            owner_to_fields.setdefault(attr.owner, []).append(target)

        if not owner_to_fields:
            mart = f" по витрине `{requested_datamart}`" if requested_datamart else ""
            return RAGAnswer(
                answer=f"В S2T не указан владелец или ответственный{mart}.",
                sources=[self._source(attr) for attr in attrs[:5]],
            )

        lines = ["Ответственные из S2T:"]
        for owner, fields in sorted(owner_to_fields.items()):
            field_summary = (
                f"{len(fields)} полей" if len(fields) > 5 else ", ".join(sorted(set(fields)))
            )
            lines.append(f"- {owner}: {field_summary}")
        return RAGAnswer(
            answer="\n".join(lines),
            sources=[self._source(attr) for attr in attrs if attr.owner][:10],
        )
