import logging
from collections.abc import Iterable
from datetime import datetime
from urllib.parse import urljoin

import httpx

from app.config import Settings
from app.confluence.exceptions import ConfluenceAuthError, ConfluenceError
from app.confluence.models import ConfluencePage, S2TResource

logger = logging.getLogger(__name__)


class ConfluenceClient:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.settings = settings
        auth = None
        if settings.confluence_username and settings.confluence_api_token:
            auth = (settings.confluence_username, settings.confluence_api_token)
        self._client = client or httpx.Client(
            base_url=settings.confluence_base_url, auth=auth, timeout=30
        )

    def _get(self, path: str, params: dict[str, str | int] | None = None) -> dict:
        response = self._client.get(path, params=params)
        if response.status_code in {401, 403}:
            raise ConfluenceAuthError("Confluence authentication failed")
        if response.is_error:
            raise ConfluenceError(f"Confluence request failed: {response.status_code}")
        return response.json()

    def get_page(self, page_id: str) -> ConfluencePage:
        payload = self._get(
            f"/rest/api/content/{page_id}",
            {"expand": "body.storage,version,history.lastUpdated,_links"},
        )
        return self._page_from_payload(payload)

    def get_children(self, page_id: str) -> list[ConfluencePage]:
        payload = self._get(
            f"/rest/api/content/{page_id}/child/page",
            {"expand": "body.storage,version,history.lastUpdated,_links", "limit": 100},
        )
        return [self._page_from_payload(item) for item in payload.get("results", [])]

    def search_pages(self, cql: str) -> list[ConfluencePage]:
        payload = self._get(
            "/rest/api/content/search",
            {"cql": cql, "expand": "body.storage,version,history.lastUpdated,_links"},
        )
        return [self._page_from_payload(item) for item in payload.get("results", [])]

    def get_attachments(self, page_id: str) -> list[S2TResource]:
        payload = self._get(
            f"/rest/api/content/{page_id}/child/attachment",
            {"expand": "version,metadata,_links", "limit": 100},
        )
        resources: list[S2TResource] = []
        for item in payload.get("results", []):
            title = item.get("title", "")
            links = item.get("_links", {})
            download_url = urljoin(self.settings.confluence_base_url, links.get("download", ""))
            version = item.get("version", {})
            metadata = item.get("metadata", {})
            media_type = item.get("mediaType") or metadata.get("mediaType")
            file_size = item.get("fileSize") or metadata.get("fileSize")
            resources.append(
                S2TResource(
                    id=str(item.get("id")) if item.get("id") else None,
                    title=title,
                    file_name=title,
                    resource_type="attachment",
                    url=download_url,
                    download_url=download_url,
                    updated_at=self._parse_datetime(version.get("when")),
                    version_when=self._parse_datetime(version.get("when")),
                    version=version.get("number"),
                    file_size=int(file_size) if file_size is not None else None,
                    media_type=media_type,
                    page_id=page_id,
                )
            )
        return resources

    def download(self, url: str) -> bytes:
        response = self._client.get(url)
        if response.is_error:
            raise ConfluenceError(f"Attachment download failed: {response.status_code}")
        return response.content

    def iter_top_level_pages(self) -> Iterable[ConfluencePage]:
        if self.settings.confluence_root_page_id:
            yield from self.get_children(self.settings.confluence_root_page_id)
            return
        cql = f'space="{self.settings.confluence_space_key}" and type=page'
        yield from self.search_pages(cql)

    def _page_from_payload(self, payload: dict) -> ConfluencePage:
        links = payload.get("_links", {})
        webui = links.get("webui", "")
        version = payload.get("version", {})
        history_last_updated = payload.get("history", {}).get("lastUpdated", {})
        version_when = self._parse_datetime(version.get("when"))
        return ConfluencePage(
            id=str(payload["id"]),
            title=payload.get("title", ""),
            url=urljoin(self.settings.confluence_base_url, webui),
            body_html=payload.get("body", {}).get("storage", {}).get("value"),
            updated_at=version_when,
            version=version.get("number"),
            version_when=version_when,
            last_modified=version_when,
            history_last_updated=self._parse_datetime(history_last_updated.get("when")),
        )

    @staticmethod
    def _parse_datetime(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            logger.warning("Cannot parse Confluence datetime %s", value)
            return None
