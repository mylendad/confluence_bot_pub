from services.rag.handlers.base import BaseHandler
from services.rag.models import RAGAnswer


class AttributeUsageHandler(BaseHandler):
    def handle(self, question: str) -> RAGAnswer | None:
        token = self.query_parser.extract_attribute_name(question)
        if not token:
            return RAGAnswer(answer="Не удалось определить атрибут в вопросе.", sources=[])
        attrs = self.metadata_repo.find_attribute_usage(token)
        if not attrs:
            return RAGAnswer(answer=f"Данных по атрибуту `{token}` нет.", sources=[])
        marts = sorted({attr.datamart_name for attr in attrs})
        return RAGAnswer(
            answer=f"Атрибут `{token}` найден в витринах: " + ", ".join(marts),
            sources=[self._source(attr) for attr in attrs[:10]],
        )

class AttributeCompositionHandler(BaseHandler):
    def handle(self, question: str) -> RAGAnswer | None:
        datamart = self.query_parser.extract_datamart_name(question)
        attrs = (
            self.metadata_repo.list_attributes(datamart_name=datamart)
            if datamart
            else self.metadata_repo.list_attributes()
        )
        if not attrs:
            if datamart and self.metadata_repo.get_datamart(datamart):
                return RAGAnswer(
                    answer=f"Файл S2T для витрины `{datamart}` не найден на Confluence.", sources=[]
                )
            return RAGAnswer(answer="нет s2t на конфлюенсе.", sources=[])
        fields = [attr.target_field for attr in attrs if attr.target_field]
        return RAGAnswer(
            answer="Атрибутный состав: " + ", ".join(sorted(set(fields))[:100]),
            sources=[self._source(a) for a in attrs[:5]],
        )

class AttributeLogicHandler(BaseHandler):
    def handle(self, question: str) -> RAGAnswer | None:
        attrs = self.query_parser.attrs_from_question(question)
        if not attrs:
            return None
        lines = [
            f"{attr.target_field}: {attr.transformation_logic or 'логика не указана'}"
            for attr in attrs
        ]
        return RAGAnswer(answer="\n".join(lines), sources=[self._source(attr) for attr in attrs])

class SourceLineageHandler(BaseHandler):
    def handle(self, question: str) -> RAGAnswer | None:
        attrs = self.query_parser.attrs_from_question(question)
        if not attrs:
            datamart_name = self.query_parser.extract_datamart_name(question)
            if datamart_name:
                attrs = self.metadata_repo.list_attributes(datamart_name=datamart_name)
                if attrs:
                    sources_map: dict[str, set[str]] = {}
                    for attr in attrs:
                        src_sys = attr.source_schema or "Не указана"
                        src_tab = attr.source_table or "Не указана"
                        sources_map.setdefault(src_sys, set()).add(src_tab)

                    lines = [f"Источники данных для витрины `{datamart_name}`:"]
                    for sys, tables in sorted(sources_map.items()):
                        tables_str = ", ".join(sorted(tables))
                        lines.append(f"- Система `{sys}`: таблицы {tables_str}")

                    return RAGAnswer(
                        answer="\n".join(lines), sources=[self._source(a) for a in attrs[:5]]
                    )
            return None

        lines = [
            (
                f"{self._path(attr.target_schema, attr.target_table, attr.target_field)} <- "
                f"{self._path(attr.source_schema, attr.source_table, attr.source_field)}"
            )
            for attr in attrs
        ]
        return RAGAnswer(answer="\n".join(lines), sources=[self._source(attr) for attr in attrs])
