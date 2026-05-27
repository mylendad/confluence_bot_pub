import logging
from datetime import datetime
from functools import lru_cache

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class JiraClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.base_url = settings.jira_base_url.rstrip("/")
        self.client = httpx.Client(
            verify=settings.jira_verify_ssl,
            timeout=30.0,
        )
        self._setup_auth()

    def _setup_auth(self) -> None:
        token = self.settings.jira_token or self.settings.jira_api_token
        if token:
            self.client.headers["Authorization"] = f"Bearer {token}"
        elif self.settings.jira_username and self.settings.jira_token:
            self.client.auth = (self.settings.jira_username, self.settings.jira_token)

    def get_issue(self, issue_key: str) -> dict | None:
        url = f"{self.base_url}/rest/api/2/issue/{issue_key}"
        params = {"expand": "changelog"}
        try:
            response = self.client.get(url, params=params)
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            logger.warning("Failed to fetch Jira issue %s: %s", issue_key, exc)
            return None

    @lru_cache(maxsize=1)
    def get_field_mapping(self) -> dict[str, str]:
        url = f"{self.base_url}/rest/api/2/field"
        try:
            response = self.client.get(url)
            response.raise_for_status()
            return {f["name"].upper(): f["id"] for f in response.json()}
        except Exception as exc:
            logger.warning("Failed to fetch Jira fields: %s", exc)
            return {}

    def close(self) -> None:
        self.client.close()
