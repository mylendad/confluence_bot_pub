import json
from datetime import datetime, timedelta

from services.rag.handlers.base import BaseHandler
from services.rag.models import RAGAnswer
from shared.utils.text_utils import normalize_text


class LastYearChangesHandler(BaseHandler):
    def handle(self, question: str) -> RAGAnswer | None:
        until = datetime.utcnow()
        since = self._changes_period_start(question, until)
        requested_datamart = self.query_parser.extract_datamart_name(question)
        changes = self.history_repo.list_changes(since=since)
        if requested_datamart:
            changes = [
                change
                for change in changes
                if self.query_parser.matches_datamart(
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
                    f"- {change.change_date.date()}: {change.datamart_name} — {change.entity_name}"
                )
        other_changes = [change for change in changes if change.change_type not in labels]
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

    def _changes_period_start(self, question: str, until: datetime) -> datetime:
        q = normalize_text(question)
        if ("текущ" in q or "этот" in q) and "год" in q:
            return datetime(until.year, 1, 1)
        return until - timedelta(days=365)


class ReleaseChangesHandler(BaseHandler):
    def handle(self, question: str) -> RAGAnswer | None:
        datamarts = self.query_parser.datamarts_from_question(question)
        matching: list[tuple[dict, dict]] = []
        for datamart in datamarts:
            for change in json.loads(datamart.get("release_changes_json") or "[]"):
                matching.append((datamart, change))
        if not matching:
            return RAGAnswer(answer="Изменения в релизах для витрины не найдены.", sources=[])

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
                parts.append(f"- Дата решения: {jira_done}")
            parts.append(f"- Статус/Результат (Jira): {jira_status}")
            parts.append(f"- Источник: [Confluence]({conf_url})")

            lines.append("\n".join(parts))
            lines.append("")

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
