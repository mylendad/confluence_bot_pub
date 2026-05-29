import json
import logging
import time
from collections.abc import Iterable
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import httpx

from app.config import Settings
from app.confluence.exceptions import ConfluenceAuthError, ConfluenceError
from app.confluence.models import ConfluencePage, S2TResource
from app.confluence.urls import confluence_urljoin

logger = logging.getLogger(__name__)


class ConfluenceClient:
    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        self.settings = settings
        auth, headers = self._auth_config(settings)

        headers = headers or {}
        if settings.confluence_user_agent:
            headers["User-Agent"] = settings.confluence_user_agent
        if settings.confluence_cookie_file:
            try:
                cookie_path = Path(settings.confluence_cookie_file)
                if cookie_path.is_file():
                    headers["Cookie"] = cookie_path.read_text().strip()
                else:
                    logger.warning("Cookie file not found at: %s", cookie_path)
            except Exception as exc:
                logger.error(
                    "Failed to read cookie file %s: %s", settings.confluence_cookie_file, exc
                )

        if settings.confluence_extra_headers:
            try:
                extra_headers = json.loads(settings.confluence_extra_headers)
                headers.update(extra_headers)
            except json.JSONDecodeError:
                logger.error(
                    "Failed to parse CONFLUENCE_EXTRA_HEADERS as JSON: %s",
                    settings.confluence_extra_headers,
                )

        logger.info("Initializing httpx.Client with headers: %s", headers)
        self._client = client or httpx.Client(
            base_url=settings.confluence_base_url,
            auth=auth,
            headers=headers,
            timeout=30,
            verify=settings.confluence_verify_ssl,
        )
        self._cache_get_page = {}
        self._cache_get_children = {}
        self._cache_get_attachments = {}

    @staticmethod
    def _auth_config(settings: Settings) -> tuple[tuple[str, str] | None, dict[str, str]]:
        auth_type = settings.confluence_auth_type.lower().strip()
        token = settings.confluence_auth_token
        username = settings.confluence_username
        headers: dict[str, str] = {"Accept": "application/json"}

        if token and not token.isascii():
            raise ConfluenceAuthError(
                "CONFLUENCE_TOKEN/CONFLUENCE_API_TOKEN must contain only ASCII characters. "
                "Check .env: the token may still be a placeholder or copied with extra text."
            )

        if auth_type in {"bearer", "pat", "token"}:
            if token:
                headers["Authorization"] = f"Bearer {token}"
            return None, headers

        if auth_type == "basic":
            return (username, token) if username and token else None, headers

        if username and token:
            return (username, token), headers
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return None, headers

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        if self.settings.confluence_request_delay > 0:
            time.sleep(self.settings.confluence_request_delay)

        max_retries = 5
        for attempt in range(max_retries):
            try:
                response = self._client.request(method, path, **kwargs)
                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", 2**attempt))
                    logger.warning(
                        "Rate limited (429) on %s. Retrying after %ds (attempt %d/%d)...",
                        path,
                        retry_after,
                        attempt + 1,
                        max_retries,
                    )
                    time.sleep(retry_after)
                    continue
                return response
            except httpx.RequestError as exc:
                if attempt == max_retries - 1:
                    raise
                wait = 2**attempt
                logger.warning("Request error %s. Retrying after %ds...", exc, wait)
                time.sleep(wait)

        return response

    def _get(self, path: str, params: dict[str, str | int] | None = None) -> dict:
        logger.info("Making GET request to %s", path)
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
            {"expand": "body.storage,version,history.lastUpdated,_links"},
        )
        page = self._page_from_payload(payload)
        self._cache_get_page[page_id] = page
        return page

    def get_children(self, page_id: str) -> list[ConfluencePage]:
        if page_id in self._cache_get_children:
            return self._cache_get_children[page_id]
        payload = self._get(
            f"/rest/api/content/{page_id}/child/page",
            {"expand": "body.storage,version,history.lastUpdated,_links", "limit": 100},
        )
        children = [self._page_from_payload(item) for item in payload.get("results", [])]
        self._cache_get_children[page_id] = children
        return children

    def search_pages(self, cql: str) -> list[ConfluencePage]:
        payload = self._get(
            "/rest/api/content/search",
            {"cql": cql, "expand": "body.storage,version,history.lastUpdated,_links"},
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

    def download_resource(self, resource: S2TResource) -> bytes:
        url = resource.download_url or resource.url
        if not url:
            raise ConfluenceError("Attachment download URL is absent")
        try:
            return self.download(url)
        except (ConfluenceAuthError, ConfluenceError) as exc:
            if not resource.page_id:
                raise
            
            attachment_id = resource.id
            if not attachment_id:
                # If we don't have the ID (e.g. parsed from a raw link), try to fetch it
                try:
                    logger.info("Fetching attachment ID for fallback: %s", resource.file_name)
                    attachments = self.get_attachments(resource.page_id)
                    for att in attachments:
                        if att.file_name == resource.file_name or att.title == resource.title:
                            attachment_id = att.id
                            break
                except Exception as lookup_exc:
                    logger.warning("Failed to lookup attachment ID: %s", lookup_exc)
            
            if not attachment_id:
                raise
                
            return self._download_attachment_via_rest(resource.page_id, attachment_id, exc)

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
