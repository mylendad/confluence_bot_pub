import json
import re
from datetime import datetime, timedelta

from app.changes.history_repository import HistoryRepository
from app.rag.llm import AnswerGenerator, StubAnswerGenerator
from app.rag.models import RAGAnswer
from app.rag.vector_store import JsonVectorStore
from app.storage.metadata_repository import MetadataRepository
from app.utils.text_utils import fuzzy_contains, normalize_text


class IntentClassifier:
    def classify(self, question: str) -> str:
        q = normalize_text(question)
        if (
            "витрин" in q
            and any(word in q for word in ["какие", "список", "есть"])
            and not any(word in q for word in ["атрибут", "измен", "релиз", "epk_id", "_id"])
        ):
            return "datamart_list"

        # "Изменения за период/год/даты" -> структурированная история (из БД)
        if "измен" in q and any(
            word in q for word in ["период", "дата", "датам", "история", "год", "текущ"]
        ):
            # Но если прямо упомянут "релиз", то все же Confluence
            if "релиз" not in q:
                return "last_year_changes"

        # Приоритет для "Изменений в релизах" (Confluence)
        if "релиз" in q or ("измен" in q and any(word in q for word in ["год", "последн"])):
            return "release_changes"

        if any(
            phrase in q
            for phrase in [
                "заинтересованные со стороны бизнеса",
                "заинтересованные лица",
                "заинтересованное лицо",
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

        if any(word in q for word in ["владелец", "ответствен"]):
            return "owner_lookup"
        if "заинтересован" in q:
            if any(p in q for p in ["бизнес", "лиц", "сторон"]):
                return "datamart_fact"
            if "витрин" in q:
                return "datamart_fact"
            return "owner_lookup"
        if "атрибутный состав" in q or "какие атрибут" in q:
            return "attribute_composition"
        if ("в каких витринах" in q or "где есть" in q) and any(
            c in q for c in ["epk_id", "_id", "_dt", "_cd"]
        ):
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
            field_summary = (
                f"{len(fields)} полей" if len(fields) > 5 else ", ".join(sorted(set(fields)))
            )
            lines.append(f"- {owner}: {field_summary}")
        return RAGAnswer(
            answer="\n".join(lines),
            sources=[self._source(attr) for attr in attrs if attr.owner][:10],
        )

    def _attribute_usage(self, question: str) -> RAGAnswer:
        token = self._extract_attribute_name(question)
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

        # Sort by version/date descending. Try to use jira_done_at if version is not a date.
        def sort_key(item):
            _, c = item
            v = c.get("version") or ""
            d = c.get("jira_done_at") or ""
            return v, d

        matching.sort(key=sort_key, reverse=True)

        lines = ["Изменения в релизах (от новых к старым):"]
        for datamart, change in matching[:30]:
            version = change.get("version") or "Без версии"
            change_type = (change.get("change_type") or "изменение").upper()
            summary = change.get("summary") or change.get("jira_title") or "-"

            jira_key = change.get("jira_key")
            jira_created = change.get("jira_created_at")
            if jira_created and isinstance(jira_created, str):
                try:
                    jira_created = datetime.fromisoformat(jira_created).date()
                except Exception:
                    pass

            jira_done = change.get("jira_done_at")
            if jira_done and isinstance(jira_done, str):
                try:
                    jira_done = datetime.fromisoformat(jira_done).date()
                except Exception:
                    pass

            jira_status = change.get("jira_last_activity_value") or change.get("status") or "-"

            # Try to get jira_base_url from settings if available
            jira_base_url = "https://jira.example.ru"
            if hasattr(self.answer_generator, "settings"):
                jira_base_url = getattr(
                    self.answer_generator.settings, "jira_base_url", jira_base_url
                )

            jira_url = f"{jira_base_url.rstrip('/')}/browse/{jira_key}" if jira_key else None
            conf_url = change.get("source_url") or datamart.get("confluence_url")

            parts = [
                f"**Релиз {version}**",
                f"- Тип: {change_type}",
                f"- Суть: {summary}",
            ]
            if jira_key:
                parts.append(
                    f"- Задача Jira: [{jira_key}]({jira_url})"
                    if jira_url
                    else f"- Задача Jira: {jira_key}"
                )
            if jira_created:
                parts.append(f"- Создана в Jira: {jira_created}")
            if jira_done:
                parts.append(f"- Выполнена в Jira: {jira_done}")
            parts.append(f"- Статус/Результат (Jira): {jira_status}")
            parts.append(f"- Источник: [Confluence]({conf_url})")

            lines.append("\n".join(parts))
            lines.append("")  # Spacer

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
                answer="Данных для ответа нет. Сначала распарсьте S2T и соберите RAG.",
                sources=[],
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
            q = normalize_text(question)
            # If they mention specific keywords, it's a specific query. 
            # If we didn't extract a name, don't dump everything.
            is_broad = any(w in q for w in ["все", "список", "какие", "каждый", "каждой"])
            
            # If the query contains "витрина", it's almost certainly a specific query.
            if "витрин" in q and not is_broad:
                # If they ask "какие витрины", it's broad. 
                # But if they ask "Заинтересованные по витрине Карта Ветерана", it's specific.
                if any(w in q for w in ["какие", "есть", "список"]):
                    return datamarts
                return []
            
            is_specific = any(
                p in q
                for p in [
                    "заинтересован",
                    "владелец",
                    "ответствен",
                    "релиз",
                    "измен",
                    "атрибут",
                ]
            )
            if is_specific and not is_broad:
                return []
            
            if is_broad:
                return datamarts
            
            return []
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
                ["заинтересованные со стороны бизнеса", "заинтересованные лица"],
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
    def _extract_attribute_name(question: str) -> str | None:
        q = question.replace("?", " ").replace("!", " ").replace('"', " ").replace("'", " ")
        tokens = q.split()
        for token in reversed(tokens):
            token = token.strip(" .,;:'`()[]{}")
            if not token:
                continue
            if "_" in token or token.isidentifier():
                if len(token) > 2:
                    return token
        return None

    def _extract_datamart_name(self, question: str) -> str | None:
        q_norm = normalize_text(question)
        datamarts = self.metadata_repo.list_datamarts()
        names = sorted(
            [dm.get("name") for dm in datamarts if dm.get("name")],
            key=len,
            reverse=True,
        )

        # 1. First try exact match of known names (or names without 'Витрина' prefix)
        for name in names:
            norm_name = normalize_text(name)
            if not norm_name:
                continue
            if norm_name in q_norm:
                return name
            # Handle query without "Витрина" prefix
            short_name = re.sub(r"^витрина\s+", "", norm_name).strip()
            if short_name and len(short_name) > 3 and short_name in q_norm:
                return name

        # 2. Try regex extraction with stop-word lookahead to handle multi-word names
        stop_words = [
            "заинтересован",
            "атрибут",
            "измен",
            "релиз",
            "владелец",
            "ответствен",
            "ссылка",
            "мета",
            "ка фо",
            "карта данных", 
            "смд",
            "кэ",
            "имя",
            "периодич",
            "глубина",
            "процесс",
            "рейтинг",
            "отчет",
            "отчёт",
            "бизнес",
        ]
        stop_pattern = "|".join(stop_words)
        patterns = [
            rf"по\s+витрин[еы]\s+(.+?)(?=\s+(?:{stop_pattern})|$)",
            rf"витрина\s+(.+?)(?=\s+(?:{stop_pattern})|$)",
            rf"витрин[еы]\s+(.+?)(?=\s+(?:{stop_pattern})|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, question, flags=re.IGNORECASE)
            if match:
                value = match.group(1).strip(" ?:.,;\"'")
                value = re.sub(r"\s+с\s+датами$", "", value, flags=re.IGNORECASE).strip()
                if value and value.lower() not in {"за год", "за последний год", "изменения"}:
                    if pattern.startswith("витрина") and not value.lower().startswith("витрина"):
                        return f"Витрина {value}"
                    return value

        # 3. Last word fuzzy match
        words = question.split()
        if words:
            last_word = words[-1].strip(" ?:.,;\"'")
            if len(last_word) > 4 and last_word.lower() not in {"бизнеса", "лица", "лицо"}:
                for name in names:
                    if fuzzy_contains(name, [last_word], threshold=0.85):
                        return name
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
    def _normalize_cx(text: str) -> str:
        # Normalize both Cyrillic and Latin C/X to Latin C/X
        return (
            text.replace("С", "C").replace("с", "c").replace("Х", "X").replace("х", "x")
        )

    @staticmethod
    def _matches_datamart(
        actual_name: str | None, requested_name: str, actual_code: str | None = None
    ) -> bool:
        requested = RAGRetriever._normalize_cx(normalize_text(requested_name))
        actual = RAGRetriever._normalize_cx(normalize_text(actual_name or ""))
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
