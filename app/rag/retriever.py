import json
import re
from datetime import datetime, timedelta

from app.changes.history_repository import HistoryRepository
from app.rag.llm import AnswerGenerator, StubAnswerGenerator
from app.rag.models import RAGAnswer
from app.rag.vector_store import JsonVectorStore
from app.storage.metadata_repository import MetadataRepository
from app.utils.text_utils import normalize_text


class IntentClassifier:
    def classify(self, question: str) -> str:
        q = normalize_text(question)
        if (
            "витрин" in q
            and any(word in q for word in ["какие", "список", "есть"])
            and not any(word in q for word in ["атрибут", "измен", "релиз"])
        ):
            return "datamart_list"
        if "изменения в релизах" in q:
            return "release_changes"
        if any(
            phrase in q
            for phrase in [
                "заинтересованные со стороны бизнеса",
                "заинтересованное лица",
                "ссылка на мета",
                "ка фо",
                "карта данных",
                "смд",
                "кэ",
                "имя витрины в бд",
                "периодичность",
                "глубина",
                "процесс из реестра",
                "зарегистрированных процессов",
                "зарегестрированных процессов",
            ]
        ):
            return "datamart_fact"
        if any(word in q for word in ["владелец", "заинтересован", "ответствен"]):
            return "owner_lookup"
        if "измен" in q and ("год" in q or "период" in q):
            return "last_year_changes"
        if "атрибутный состав" in q or "какие атрибут" in q:
            return "attribute_composition"
        if "в каких витринах" in q and "атрибут" in q:
            return "attribute_usage"
        if any(word in q for word in ["источник", "lineage", "откуда"]):
            return "source_lineage"
        if any(word in q for word in ["логика", "преобразован", "расчет", "расчёт"]):
            return "transformation_logic"
        return "general_question"


class RAGRetriever:
    def __init__(
        self,
        metadata_repo: MetadataRepository,
        vector_store: JsonVectorStore,
        history_repo: HistoryRepository,
        answer_generator: AnswerGenerator | None = None,
    ) -> None:
        self.metadata_repo = metadata_repo
        self.vector_store = vector_store
        self.history_repo = history_repo
        self.answer_generator = answer_generator or StubAnswerGenerator()
        self.intent_classifier = IntentClassifier()

    def answer(self, question: str) -> RAGAnswer:
        intent = self.intent_classifier.classify(question)
        if intent == "datamart_list":
            return self._datamart_list()
        if intent == "datamart_fact":
            return self._datamart_fact(question)
        if intent == "release_changes":
            return self._release_changes(question)
        if intent == "owner_lookup":
            return self._owner_lookup(question)
        if intent == "attribute_usage":
            return self._attribute_usage(question)
        if intent == "attribute_composition":
            return self._attribute_composition(question)
        if intent == "last_year_changes":
            return self._last_year_changes(question)
        if intent == "transformation_logic":
            exact = self._attribute_logic(question)
            if exact:
                return exact
        if intent == "source_lineage":
            exact = self._source_lineage(question)
            if exact:
                return exact
        if intent in {"source_lineage", "transformation_logic", "general_question"}:
            return self._vector_answer(question)
        return self._vector_answer(question)

    def _owner_lookup(self, question: str) -> RAGAnswer:
        attrs = self.metadata_repo.list_attributes()
        if not attrs:
            return RAGAnswer(
                answer="Данных по владельцам нет. Сначала распарсьте S2T и соберите RAG.",
                sources=[],
            )

        requested_datamart = self._extract_datamart_name(question)
        if requested_datamart:
            matched = self._filter_attrs_by_datamart(attrs, requested_datamart)
            if not matched:
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
            lines.append(f"- {owner}: {', '.join(sorted(set(fields)))}")
        return RAGAnswer(
            answer="\n".join(lines),
            sources=[self._source(attr) for attr in attrs if attr.owner][:10],
        )

    def _attribute_usage(self, question: str) -> RAGAnswer:
        token = question.strip().split()[-1].strip(" ?\"'")
        attrs = self.metadata_repo.find_attribute_usage(token)
        if not attrs:
            return RAGAnswer(answer=f"Данных по атрибуту `{token}` нет.", sources=[])
        marts = sorted({attr.datamart_name for attr in attrs})
        return RAGAnswer(
            answer="Атрибут найден в витринах: " + ", ".join(marts),
            sources=[self._source(attr) for attr in attrs[:10]],
        )

    def _attribute_composition(self, question: str) -> RAGAnswer:
        datamart = self._extract_datamart_name(question)
        attrs = (
            self.metadata_repo.list_attributes(datamart_name=datamart)
            if datamart
            else self.metadata_repo.list_attributes()
        )
        if not attrs:
            return RAGAnswer(answer="Данных по атрибутному составу нет.", sources=[])
        fields = [attr.target_field for attr in attrs if attr.target_field]
        return RAGAnswer(
            answer="Атрибутный состав: " + ", ".join(sorted(set(fields))[:100]),
            sources=[self._source(a) for a in attrs[:5]],
        )

    def _last_year_changes(self, question: str) -> RAGAnswer:
        until = datetime.utcnow()
        since = self._changes_period_start(question, until)
        requested_datamart = self._extract_datamart_name(question)
        changes = self.history_repo.list_changes(since=since)
        if requested_datamart:
            changes = [
                change
                for change in changes
                if self._matches_datamart(
                    change.datamart_name, requested_datamart, change.datamart_code
                )
            ]
        if not changes:
            scope = f" по витрине `{requested_datamart}`" if requested_datamart else ""
            return RAGAnswer(
                answer=(
                    f"За период {since.date()} - {until.date()} изменений{scope} "
                    "в локальной истории не найдено."
                ),
                sources=[],
            )

        labels = {
            "added": "Добавлены атрибуты",
            "removed": "Удалены атрибуты",
            "modified": "Изменены атрибуты",
        }
        lines = [f"Изменения за период {since.date()} - {until.date()}:"]
        for change_type, label in labels.items():
            typed_changes = [change for change in changes if change.change_type == change_type]
            if not typed_changes:
                continue
            lines.append(f"{label}:")
            for change in typed_changes[:20]:
                lines.append(
                    f"- {change.change_date.date()}: {change.datamart_name} — "
                    f"{change.entity_name}"
                )
        other_changes = [
            change for change in changes if change.change_type not in labels
        ]
        if other_changes:
            lines.append("Прочие изменения:")
            for change in other_changes[:20]:
                lines.append(
                    f"- {change.change_date.date()}: {change.datamart_name} — "
                    f"{change.entity_name} ({change.change_type})"
                )
        return RAGAnswer(
            answer="\n".join(lines), sources=[c.model_dump(mode="json") for c in changes[:10]]
        )

    def _datamart_list(self) -> RAGAnswer:
        datamarts = self.metadata_repo.list_datamarts()
        if not datamarts:
            return RAGAnswer(
                answer="Витрины не найдены. Сначала выполните `update-rag` или `parse-s2t`.",
                sources=[],
            )
        names = sorted({datamart["name"] for datamart in datamarts if datamart.get("name")})
        return RAGAnswer(
            answer="Доступные витрины:\n" + "\n".join(f"- {name}" for name in names),
            sources=[
                {
                    "datamart": datamart.get("name"),
                    "confluence_url": datamart.get("confluence_url"),
                }
                for datamart in datamarts[:10]
            ],
        )

    def _datamart_fact(self, question: str) -> RAGAnswer:
        fact_key = self._fact_key_from_question(question)
        datamarts = self._datamarts_from_question(question)
        matching: list[tuple[dict, dict]] = []
        for datamart in datamarts:
            for fact in json.loads(datamart.get("facts_json") or "[]"):
                if fact_key and fact.get("key") != fact_key:
                    continue
                if not self._fact_matches_question(fact, question):
                    continue
                matching.append((datamart, fact))

        if not matching:
            return RAGAnswer(
                answer="Данных по этому вопросу на главной странице витрины не найдено.",
                sources=[],
            )

        lines = []
        for datamart, fact in matching:
            value = fact.get("value") or "-"
            links = fact.get("links") or []
            if links:
                link_text = "; ".join(
                    f"{link.get('title') or link.get('url')}: {link.get('url')}"
                    for link in links
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
                }
                for datamart, fact in matching[:10]
            ],
        )

    def _release_changes(self, question: str) -> RAGAnswer:
        datamarts = self._datamarts_from_question(question)
        matching: list[tuple[dict, dict]] = []
        for datamart in datamarts:
            for change in json.loads(datamart.get("release_changes_json") or "[]"):
                matching.append((datamart, change))
        if not matching:
            return RAGAnswer(answer="Изменения в релизах для витрины не найдены.", sources=[])

        lines = ["Изменения в релизах:"]
        for datamart, change in matching[:30]:
            parts = [
                f"{datamart.get('name')}",
                f"версия {change.get('version') or '-'}",
                f"Jira {change.get('jira_key') or '-'}",
                f"тип {change.get('change_type') or '-'}",
            ]
            if change.get("status"):
                parts.append(f"статус {change['status']}")
            summary = change.get("summary") or change.get("jira_title") or "-"
            lines.append(f"- {', '.join(parts)}: {summary}")
        return RAGAnswer(
            answer="\n".join(lines),
            sources=[
                {
                    "datamart": datamart.get("name"),
                    "source_url": change.get("source_url") or datamart.get("confluence_url"),
                    "version": change.get("version"),
                    "jira_key": change.get("jira_key"),
                }
                for datamart, change in matching[:10]
            ],
        )

    def _attribute_logic(self, question: str) -> RAGAnswer | None:
        attrs = self._attrs_from_question(question)
        if not attrs:
            return None
        lines = [
            f"{attr.target_field}: {attr.transformation_logic or 'логика не указана'}"
            for attr in attrs
        ]
        return RAGAnswer(answer="\n".join(lines), sources=[self._source(attr) for attr in attrs])

    def _source_lineage(self, question: str) -> RAGAnswer | None:
        attrs = self._attrs_from_question(question)
        if not attrs:
            return None
        lines = [
            (
                f"{self._path(attr.target_schema, attr.target_table, attr.target_field)} <- "
                f"{self._path(attr.source_schema, attr.source_table, attr.source_field)}"
            )
            for attr in attrs
        ]
        return RAGAnswer(answer="\n".join(lines), sources=[self._source(attr) for attr in attrs])

    def _attrs_from_question(self, question: str):
        for token in reversed(question.replace("?", " ").replace('"', " ").split()):
            token = token.strip(" .,;:'`()[]{}")
            if "_" in token or token.isidentifier():
                attrs = self.metadata_repo.find_attribute_usage(token)
                if attrs:
                    return attrs
        return []

    def _vector_answer(self, question: str) -> RAGAnswer:
        docs = self.vector_store.search(question, k=5)
        if not docs:
            return RAGAnswer(
                answer="Данных для ответа нет. Сначала распарсьте S2T и соберите RAG.", sources=[]
            )
        context = "\n".join(item.document.text for item in docs)
        try:
            answer = self.answer_generator.generate(question, context)
        except Exception as exc:
            answer = f"Не удалось вызвать LLM для генеративного ответа: {exc}"
        return RAGAnswer(
            answer=answer,
            sources=[item.document.metadata for item in docs],
        )

    @staticmethod
    def _changes_period_start(question: str, until: datetime) -> datetime:
        q = normalize_text(question)
        if ("текущ" in q or "этот" in q) and "год" in q:
            return datetime(until.year, 1, 1)
        return until - timedelta(days=365)

    def _datamarts_from_question(self, question: str) -> list[dict]:
        datamarts = self.metadata_repo.list_datamarts()
        requested_datamart = self._extract_datamart_name(question)
        if not requested_datamart:
            return datamarts
        return [
            datamart
            for datamart in datamarts
            if self._matches_datamart(
                datamart.get("name"), requested_datamart, datamart.get("code")
            )
        ]

    @staticmethod
    def _fact_key_from_question(question: str) -> str | None:
        q = normalize_text(question)
        checks = [
            (
                "business_stakeholders",
                ["заинтересованные со стороны бизнеса", "заинтересованное лица"],
            ),
            ("meta_links", ["ссылка на мета", "мета", "ка фо", "карта данных", "смд"]),
            ("ke", ["кэ"]),
            ("db_name", ["имя витрины в бд", "витрина в бд"]),
            ("periodicity", ["периодичность"]),
            ("depth", ["глубина"]),
            (
                "bank_process",
                [
                    "процесс из реестра",
                    "зарегистрированных процессов",
                    "зарегестрированных процессов",
                ],
            ),
        ]
        for key, aliases in checks:
            if any(alias in q for alias in aliases):
                return key
        return None

    @staticmethod
    def _fact_matches_question(fact: dict, question: str) -> bool:
        q = normalize_text(question)
        label = normalize_text(fact.get("label") or "")
        if fact.get("key") != "meta_links":
            return True
        requested = [item for item in ("мета", "ка фо", "карта данных", "смд") if item in q]
        if not requested:
            return True
        return any(item in label for item in requested)

    @staticmethod
    def _extract_datamart_name(question: str) -> str | None:
        patterns = [
            r"по\s+витрин[еы]\s+(.+)$",
            r"витрина\s+(.+)$",
            r"витрин[еы]\s+(.+)$",
        ]
        for pattern in patterns:
            match = re.search(pattern, question, flags=re.IGNORECASE)
            if not match:
                continue
            value = match.group(1).strip(" ?:.,;\"'")
            value = re.sub(r"\s+с\s+датами$", "", value, flags=re.IGNORECASE).strip()
            if not value or value.lower() in {"за год", "за последний год", "изменения"}:
                return None
            if normalize_text(value) in {"в бд", "в базе данных"}:
                return None
            if pattern.startswith("витрина"):
                return f"Витрина {value}"
            return value
        return None

    @staticmethod
    def _filter_attrs_by_datamart(attrs, datamart_name: str):
        return [
            attr
            for attr in attrs
            if RAGRetriever._matches_datamart(
                attr.datamart_name, datamart_name, attr.datamart_code
            )
        ]

    @staticmethod
    def _matches_datamart(
        actual_name: str | None, requested_name: str, actual_code: str | None = None
    ) -> bool:
        requested = normalize_text(requested_name)
        actual = normalize_text(actual_name or "")
        code = normalize_text(actual_code or "")
        return requested in actual or actual in requested or requested == code

    @staticmethod
    def _source(attr) -> dict:
        return {
            "datamart": attr.datamart_name,
            "owner": attr.owner,
            "s2t_file": attr.s2t_file_name,
            "s2t_file_date": str(attr.s2t_file_date) if attr.s2t_file_date else None,
            "target_field": attr.target_field,
            "source_field": attr.source_field,
        }

    @staticmethod
    def _path(*parts: str | None) -> str:
        return ".".join(part for part in parts if part) or "-"
