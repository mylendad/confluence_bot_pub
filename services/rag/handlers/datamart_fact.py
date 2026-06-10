import json

from services.rag.handlers.base import BaseHandler
from services.rag.models import RAGAnswer
from shared.utils.text_utils import normalize_text


class DatamartFactHandler(BaseHandler):
    def handle(self, question: str) -> RAGAnswer | None:
        fact_key = self._fact_key_from_question(question)
        datamarts = self.query_parser.datamarts_from_question(question)

        if not datamarts:
            requested_name = self.query_parser.extract_datamart_name(question)
            if requested_name:
                return RAGAnswer(
                    answer=f"Витрина `{requested_name}` найдена, но данных по запросу на её странице нет.",
                    sources=[],
                )
            return RAGAnswer(
                answer="Не удалось определить витрину. Пожалуйста, укажите точное название.",
                sources=[],
            )

        matching: list[tuple[dict, dict]] = []
        for datamart in datamarts:
            facts = json.loads(datamart.get("facts_json") or "[]")
            found = False
            for fact in facts:
                if fact_key and fact.get("key") == fact_key:
                    matching.append((datamart, fact))
                    found = True

            if not found:
                for fact in facts:
                    if self._fact_matches_question(fact, question):
                        matching.append((datamart, fact))

        if not matching:
            marts_str = ", ".join([d.get("name") for d in datamarts])
            return RAGAnswer(
                answer=f"Для {marts_str} запрошенные данные не найдены на главной странице или в чек-листе.",
                sources=[],
            )

        lines = []
        for datamart, fact in matching:
            value = fact.get("value") or "-"
            links = fact.get("links") or []
            if links:
                link_text = "; ".join(
                    f"{link.get('title') or link.get('url')}: {link.get('url')}" for link in links
                )
                value = f"{value} ({link_text})"
            lines.append(f"{datamart.get('name')}: {fact.get('label')} — {value}")
        return RAGAnswer(
            answer="\n".join(lines),
            sources=[
                {
                    "datamart": datamart.get("name"),
                    "confluence_url": datamart.get("confluence_url"),
                    "fact_key": fact.get("key"),
                    "fact_label": fact.get("label"),
                    "s2t_file": "-",
                }
                for datamart, fact in matching[:10]
            ],
        )

    def _fact_key_from_question(self, question: str) -> str | None:
        q = normalize_text(question)
        checks = [
            ("business_stakeholders", ["заинтересованные со стороны бизнеса", "заинтересованные лица"]),
            ("meta_links", ["ссылка на мета", "мета", "ка фо", "карта данных", "смд"]),
            ("ke", ["кэ"]),
            ("db_name", ["имя витрины в бд", "витрина в бд"]),
            ("periodicity", ["периодичность"]),
            ("depth", ["глубина"]),
            ("bank_process", ["процесс из реестра", "зарегистрированных процессов", "зарегестрированных процессов"]),
            ("data_location", ["расположение данных", "место публикации"]),
            ("data_category", ["категория данных"]),
        ]
        for key, aliases in checks:
            if any(alias in q for alias in aliases):
                return key
        return None

    def _fact_matches_question(self, fact: dict, question: str) -> bool:
        q = normalize_text(question)
        label = normalize_text(fact.get("label") or "")
        key = fact.get("key")

        aliases_map = {
            "data_location": ["расположение данных", "место публикации", "где лежат", "где хранятся"],
            "data_category": ["категория данных", "категория продукта", "какие данные"],
            "business_stakeholders": ["заинтересованные", "бизнес лица", "стейкхолдеры"],
            "db_name": ["имя в бд", "название в бд", "таблица в бд"],
        }

        if label and label in q:
            return True
        if key in aliases_map:
            for alias in aliases_map[key]:
                if alias in q:
                    return True
        if key == "meta_links":
            requested = [item for item in ("мета", "ка фо", "карта данных", "смд") if item in q]
            if requested and any(item in label for item in requested):
                return True
        return False
