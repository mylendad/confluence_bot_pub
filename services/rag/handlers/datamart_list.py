import re

from services.rag.handlers.base import BaseHandler
from services.rag.models import RAGAnswer
from shared.utils.text_utils import normalize_text


class DatamartListHandler(BaseHandler):
    def handle(self, question: str) -> RAGAnswer | None:
        datamarts = self.metadata_repo.list_datamarts()
        if not datamarts:
            return RAGAnswer(
                answer="Витрины не найдены. Сначала выполните `update-rag` или `parse-s2t`.",
                sources=[],
            )

        junk_patterns = [
            r"\bтз\b", r"техническ[ои][еи] задани[ея]", r"чек лист", r"препятствия",
            r"функциональное решение", r"функцональное решение", r"страниц[аы] для 2лс",
            r"копия", r"изменения в релизах", r"s2t\s*-", r"прокси-витрина", r"stage",
        ]
        combined_junk = "|".join(junk_patterns)

        filtered_names = []
        for dm in datamarts:
            name = dm.get("name", "")
            if not name:
                continue

            if "inner" in name.lower():
                filtered_names.append(name)
                continue

            norm_name = normalize_text(name)
            if re.search(combined_junk, norm_name):
                continue

            if re.search(r"тз\s*-|тз\s*--|s2t\s*-", name.lower()):
                continue

            filtered_names.append(name)

        lines = ["Доступные витрины:"]
        for name in sorted(set(filtered_names)):
            lines.append(f"- {name}")

        return RAGAnswer(
            answer="\n".join(lines),
            sources=[],
        )
