import json
import logging
import time
import urllib.parse
from collections.abc import Iterable
from datetime import datetime

import httpx

from app.config import Settings
from app.confluence.exceptions import ConfluenceAuthError, ConfluenceError
from app.confluence.models import ConfluencePage, S2TResource
from app.confluence.urls import confluence_urljoin

logger = logging.getLogger(__name__)


class ConfluenceClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.http = httpx.Client(
            auth=(settings.confluence_username, settings.confluence_api_token),
            timeout=httpx.Timeout(30.0, connect=60.0),
        )
        self._cache_get_page: dict[str, ConfluencePage] = {}
        self._cache_get_attachments: dict[str, list[S2TResource]] = {}

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        url = confluence_urljoin(self.settings.confluence_base_url, path)
        try:
            response = self.http.request(method, url, **kwargs)
            return response
        except httpx.HTTPError as exc:
            logger.error("HTTP request failed: %s %s: %s", method, url, exc)
            raise ConfluenceError(f"HTTP request failed: {exc}")

    def _get(self, path: str, params: dict | None = None) -> dict:
        response = self._request("GET", path, params=params)

        if response.status_code in {401, 403}:
            raise ConfluenceAuthError(f"Confluence authentication failed: {response.status_code}")
        if response.is_error:
            raise ConfluenceError(f"Confluence request failed: {response.status_code}")
        return response.json()

    def _validate_download_response(self, response: httpx.Response, original_url: str):
        logger.info(
            "Validating download response. final_url=%s, status_code=%s",
            response.url,
            response.status_code,
        )
        if "login.action" in str(response.url):
            raise ConfluenceAuthError(
                f"Attachment download redirected to login page, check permissions for: "
                f"{original_url}"
            )

        content_type = response.headers.get("Content-Type", "").lower()
        if "text/html" in content_type and "application/json" not in content_type:
            raise ConfluenceError(
                f"Expected a file download, but received HTML content from: {original_url}"
            )

    def get_page(self, page_id: str) -> ConfluencePage:
        if page_id in self._cache_get_page:
            return self._cache_get_page[page_id]
        payload = self._get(
            f"/rest/api/content/{page_id}",
            {"expand": "body.storage,version,history.lastUpdated"},
        )
        page = self._page_from_payload(payload)
        self._cache_get_page[page_id] = page
        return page

    def search_pages(self, cql: str) -> Iterable[ConfluencePage]:
        limit = 50
        start = 0
        while True:
            payload = self._get(
                "/rest/api/content/search",
                {
                    "cql": cql,
                    "expand": "body.storage,version,history.lastUpdated",
                    "limit": limit,
                    "start": start,
                },
            )
            results = payload.get("results", [])
            for item in results:
                yield self._page_from_payload(item)
            if len(results) < limit:
                break
            start += limit

    def get_children(self, page_id: str) -> list[ConfluencePage]:
        payload = self._get(
            f"/rest/api/content/{page_id}/child/page",
            {"expand": "body.storage,version,history.lastUpdated", "limit": 100},
        )
        return [self._page_from_payload(item) for item in payload.get("results", [])]

    def get_attachments(self, page_id: str) -> list[S2TResource]:
        if page_id in self._cache_get_attachments:
            return self._cache_get_attachments[page_id]

        payload = self._get(
            f"/rest/api/content/{page_id}/child/attachment",
            {"expand": "version,metadata,_links", "limit": 100},
        )
        resources: list[S2TResource] = []
        for item in payload.get("results", []):
            title = item.get("title", "")
            links = item.get("_links", {})
            download_url = confluence_urljoin(
                self.settings.confluence_base_url, links.get("download", "")
            )
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
        self._cache_get_attachments[page_id] = resources
        return resources

    def download(self, url: str) -> bytes:
        logger.info("Downloading from URL: %s", url)
        response = self._request("GET", url, follow_redirects=True)
        self._validate_download_response(response, original_url=url)
        if response.status_code in {401, 403}:
            raise ConfluenceAuthError(f"Attachment download forbidden: {response.status_code}")
        if response.is_error:
            raise ConfluenceError(f"Attachment download failed: {response.status_code}")
        return response.content

    def download_resource(self, resource: S2TResource, datamart_page_id: str | None = None) -> bytes:
        url = resource.download_url or resource.url
        if not url:
            raise ConfluenceError("Attachment download URL is absent")
        try:
            return self.download(url)
        except (ConfluenceAuthError, ConfluenceError) as exc:
            logger.warning("Direct download failed for %s, trying REST fallback. Error: %s", resource.file_name, exc)
            if not resource.page_id and not datamart_page_id:
                raise
            
            attachment_id = resource.id
            found_page_id = resource.page_id
            
            def normalize_name(name):
                if not name: return ""
                # Unquote and replace both + and %20 with space for fuzzy comparison
                # But ALSO keep the original for exact match
                u = urllib.parse.unquote(name).strip().lower()
                return [u, u.replace("+", " ")]

            if not attachment_id:
                # Try to fetch from the immediate sub-page
                pages_to_check = []
                if resource.page_id: pages_to_check.append(resource.page_id)
                if datamart_page_id and datamart_page_id != resource.page_id:
                    pages_to_check.append(datamart_page_id)

                target_names = normalize_name(resource.file_name) + normalize_name(resource.title)
                
                for pid in pages_to_check:
                    try:
                        logger.info("Fetching attachments from page %s to find ID for %s", pid, resource.file_name)
                        attachments = self.get_attachments(pid)
                        for att in attachments:
                            att_names = normalize_name(att.file_name) + normalize_name(att.title)
                            if any(tn in att_names for tn in target_names):
                                attachment_id = att.id
                                found_page_id = pid
                                logger.info("Found attachment ID %s on page %s.", attachment_id, pid)
                                break
                        if attachment_id: break
                    except Exception as lookup_exc:
                        logger.warning("Failed to lookup attachments on page %s: %s", pid, lookup_exc)
            
            if not attachment_id or not found_page_id:
                raise ConfluenceError(f"Could not find ID for attachment '{resource.file_name}' on pages {resource.page_id} or {datamart_page_id} to perform REST fallback.") from exc
                
            return self._download_attachment_via_rest(found_page_id, attachment_id, exc)

    def _download_attachment_via_rest(
        self, page_id: str, attachment_id: str, original_error: Exception
    ) -> bytes:
        url = f"/rest/api/content/{page_id}/child/attachment/{attachment_id}/download"
        logger.info("Downloading from URL (REST fallback): %s", url)
        response = self._request("GET", url, follow_redirects=True)
        self._validate_download_response(response, original_url=url)
        if response.status_code in {401, 403}:
            raise ConfluenceAuthError(
                "Attachment download forbidden via direct URL and REST fallback: "
                f"{response.status_code}"
            ) from original_error
        if response.is_error:
            raise ConfluenceError(
                f"Attachment REST download failed: {response.status_code}"
            ) from original_error
        return response.content

    def check_health(self) -> dict:
        start_time = time.time()
        try:
            self._get("/rest/api/content", {"limit": 1})
            latency = (time.time() - start_time) * 1000
            return {"status": "ok", "latency_ms": round(latency, 2)}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

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
            url=confluence_urljoin(self.settings.confluence_base_url, webui),
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
