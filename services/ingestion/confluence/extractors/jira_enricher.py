import logging
from datetime import datetime

from services.ingestion.confluence.jira_client import JiraClient
from services.ingestion.confluence.models import ReleaseChange

logger = logging.getLogger(__name__)

class JiraReleaseEnricher:
    def __init__(self, jira_client: JiraClient | None):
        self.jira_client = jira_client

    def enrich_release_changes(self, changes: list[ReleaseChange]) -> None:
        if not self.jira_client:
            logger.warning("JiraClient is None. Skipping Jira enrichment.")
            return
        field_mapping = self.jira_client.get_field_mapping()
        logger.info(f"Enriching {len(changes)} release changes with Jira data...")
        for change in changes:
            if not change.jira_key:
                continue
            logger.info(f"Fetching Jira issue: {change.jira_key}")
            try:
                issue = self.jira_client.get_issue(change.jira_key)
                if not issue:
                    continue
                fields = issue.get("fields", {})
                created = fields.get("created")
                if created:
                    try:
                        change.jira_created_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    except Exception as exc:
                        logger.warning("Failed to parse Jira created date %s: %s", created, exc)

                resolution_date = fields.get("resolutiondate")
                if resolution_date:
                    try:
                        change.jira_done_at = datetime.fromisoformat(
                            resolution_date.replace("Z", "+00:00")
                        )
                    except Exception as exc:
                        logger.warning("Failed to parse Jira resolution date %s: %s", resolution_date, exc)

                if not change.jira_done_at:
                    changelog = issue.get("changelog", {})
                    histories = changelog.get("histories", [])
                    histories.sort(key=lambda x: x.get("created", ""), reverse=True)

                    tag = (change.change_type or "").lower()
                    done_statuses = {
                        "сделан", "сделано", "done", "resolved", "решено",
                        "закрыт", "closed", "выполнено", "выполнен",
                        "завершено", "завершен", "готово", "готов",
                    }

                    for history in histories:
                        history_created = history.get("created")
                        found_done_in_this_history = False
                        for item in history.get("items", []):
                            field_name = (item.get("field") or "").lower()
                            status_name = (item.get("toString") or "").lower()

                            is_done_field = field_name in {"status", "resolution", "решение"}
                            is_tag_field = tag and field_name == tag

                            if (is_done_field or is_tag_field) and status_name in done_statuses:
                                found_done_in_this_history = True
                                break

                        if found_done_in_this_history and history_created:
                            try:
                                clean_date = history_created.replace("Z", "+00:00")
                                change.jira_done_at = datetime.fromisoformat(clean_date)
                                break
                            except Exception as exc:
                                logger.warning(
                                    "Failed to parse Jira history date %s: %s", history_created, exc
                                )

                tag = (change.change_type or "").lower()
                if tag:
                    tag_upper = tag.upper()
                    found_value = None
                    changelog = issue.get("changelog", {})
                    current_histories = changelog.get("histories", [])

                    for history in current_histories:
                        for item in history.get("items", []):
                            if (item.get("field") or "").upper() == tag_upper:
                                found_value = item.get("toString")
                                break
                        if found_value:
                            break

                    if not found_value and tag_upper in field_mapping:
                        field_id = field_mapping[tag_upper]
                        found_value = fields.get(field_id)

                    change.jira_last_activity_value = found_value
            except Exception as exc:
                logger.warning("Error fetching/enriching Jira issue %s: %s", change.jira_key, exc)
