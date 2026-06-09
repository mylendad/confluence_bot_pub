import json
import logging
import time
import urllib.parse
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

import httpx

from services.ingestion.confluence.exceptions import ConfluenceAuthError, ConfluenceError
from services.ingestion.confluence.models import ConfluencePage, S2TResource
from services.ingestion.confluence.urls import confluence_urljoin
from shared.config.config import Settings

logger = logging.getLogger(__name__)


class ConfluenceClient:
    """
    Клиент для взаимодействия с API Confluence.
    Обеспечивает получение страниц, вложений и выполнение поисковых запросов.
    """

    def __init__(self, settings: Settings, client: httpx.Client | None = None) -> None:
        """
        Инициализирует клиент Confluence.

        :param settings: Объект настроек приложения Settings.
        :param client: Внешний экземпляр httpx.Client (опционально).
        """
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

        logger.info("Initializing httpx.Client with base_url=%s and headers", settings.confluence_base_url)
        self.http = client or httpx.Client(
            base_url=settings.confluence_base_url,
            auth=auth,
            headers=headers,
            timeout=httpx.Timeout(30.0, connect=60.0),
            verify=settings.confluence_verify_ssl,
        )
        self._cache_get_page: dict[str, ConfluencePage] = {}
        self._cache_get_attachments: dict[str, list[S2TResource]] = {}

    @staticmethod
    def _auth_config(settings: Settings) -> tuple[tuple[str, str] | None, dict[str, str]]:
        """
        Конфигурирует параметры аутентификации на основе настроек.

        :param settings: Объект настроек.
        :return: Кортеж из параметров (user, password) для Basic Auth и словаря заголовков.
        """
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
        """
        Выполняет HTTP-запрос к API Confluence с обработкой повторных попыток и ограничений скорости.

        :param method: HTTP метод (GET, POST и т.д.).
        :param path: Относительный путь к ресурсу API.
        :param kwargs: Дополнительные аргументы для httpx.request.
        :return: Ответ httpx.Response.
        """
        if self.settings.confluence_request_delay > 0:
            time.sleep(self.settings.confluence_request_delay)

        max_retries = 5
        for attempt in range(max_retries):
            try:
                response = self.http.request(method, path, **kwargs)
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
                    logger.error("HTTP request failed after %d attempts: %s %s: %s", max_retries, method, path, exc)
                    raise ConfluenceError(f"HTTP request failed: {exc}") from exc
                wait = 2**attempt
                logger.warning("Request failed: %s. Retrying in %ds...", exc, wait)
                time.sleep(wait)
        
        raise ConfluenceError(f"Failed to execute {method} {path} after {max_retries} attempts")

    def _get(self, path: str, params: dict | None = None) -> dict:
        """
        Выполняет GET-запрос и возвращает JSON-ответ.

        :param path: Путь к ресурсу.
        :param params: Параметры запроса.
        :return: Словарь с данными ответа.
        """
        response = self._request("GET", path, params=params)

        if response.status_code in {401, 403}:
            auth_header = response.headers.get("WWW-Authenticate", "Not provided")
            server_header = response.headers.get("Server", "Unknown")
            logger.error(
                "Confluence Auth Error %s. URL: %s\nHeaders: %s\nWWW-Authenticate: %s\nServer: %s",
                response.status_code,
                response.url,
                dict(response.headers),
                auth_header,
                server_header,
            )
            if response.status_code == 401:
                msg = (
                    f"Confluence authentication failed (401). Server expects: {auth_header}. "
                    "If using Basic Auth, ensure credentials are correct. If using PAT, ensure "
                    "CONFLUENCE_AUTH_TYPE=token."
                )
            else:
                msg = "Confluence access forbidden (403). Check your account permissions or IP restrictions."
            
            raise ConfluenceAuthError(msg)

        if response.is_error:
            logger.error("Confluence request failed: %s %s", response.status_code, response.text[:200])
            raise ConfluenceError(f"Confluence request failed: {response.status_code}")
        return response.json()

    def _validate_download_response(self, response: httpx.Response, original_url: str):
        """
        Проверяет корректность ответа при скачивании файла.

        :param response: Ответ от сервера.
        :param original_url: Исходный URL скачивания.
        """
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
        """
        Получает информацию о странице по её ID.

        :param page_id: Идентификатор страницы.
        :return: Объект ConfluencePage.
        """
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
        """
        Ищет страницы с использованием языка запросов CQL.

        :param cql: Запрос на языке CQL.
        :return: Итератор по объектам ConfluencePage.
        """
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

    def find_page_by_title(self, title: str) -> ConfluencePage | None:
        """
        Находит страницу по точному совпадению заголовка с использованием CQL.

        :param title: Заголовок страницы.
        :return: Объект ConfluencePage или None, если страница не найдена.
        """
        cql = f'title = "{title}"'
        try:
            pages = list(self.search_pages(cql))
            return pages[0] if pages else None
        except Exception as exc:
            logger.warning("Failed to find page by title '%s': %s", title, exc)
            return None

    def get_children(self, page_id: str) -> list[ConfluencePage]:
        """
        Возвращает список дочерних страниц для указанной страницы.

        :param page_id: Идентификатор родительской страницы.
        :return: Список объектов ConfluencePage.
        """
        payload = self._get(
            f"/rest/api/content/{page_id}/child/page",
            {"expand": "body.storage,version,history.lastUpdated", "limit": 100},
        )
        return [self._page_from_payload(item) for item in payload.get("results", [])]

    def get_attachments(self, page_id: str) -> list[S2TResource]:
        """
        Возвращает список вложений для указанной страницы.

        :param page_id: Идентификатор страницы.
        :return: Список объектов S2TResource.
        """
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
        """
        Скачивает содержимое по указанному URL.

        :param url: URL для скачивания.
        :return: Бинарное содержимое файла.
        """
        logger.info("Downloading from URL: %s", url)
        if url.startswith("http"):
            response = self.http.get(url, follow_redirects=True)
        else:
            response = self._request("GET", url, follow_redirects=True)
            
        self._validate_download_response(response, original_url=url)
        if response.status_code in {401, 403}:
            raise ConfluenceAuthError(f"Attachment download forbidden: {response.status_code}")
        if response.is_error:
            raise ConfluenceError(f"Attachment download failed: {response.status_code}")
        return response.content

    def download_resource(self, resource: S2TResource, datamart_page_id: str | None = None) -> bytes:
        """
        Скачивает ресурс (вложение), используя прямой URL или REST API в качестве резервного механизма.

        :param resource: Объект ресурса S2TResource.
        :param datamart_page_id: Опциональный ID страницы витрины данных для поиска вложения.
        :return: Бинарное содержимое ресурса.
        """
        url = resource.download_url or resource.url
        if not url:
            raise ConfluenceError("Attachment download URL is absent")
        try:
            return self.download(url)
        except (ConfluenceAuthError, ConfluenceError) as exc:
            logger.warning("Direct download failed for %s, trying REST fallback. Error: %s", resource.file_name, exc)
            
            attachment_id = resource.id
            found_page_id = resource.page_id
            
            def normalize_name(name):
                if not name: return set()
                u = urllib.parse.unquote(name).strip().lower()
                return {u, u.replace("+", " "), u.replace("+", "_"), u.replace(" ", "_")}

            if not attachment_id:
                pages_to_check = []
                if resource.page_id: pages_to_check.append(resource.page_id)
                if datamart_page_id: pages_to_check.append(datamart_page_id)
                
                target_names = normalize_name(resource.file_name) | normalize_name(resource.title)
                
                for pid in pages_to_check:
                    try:
                        attachments = self.get_attachments(pid)
                        for att in attachments:
                            att_names = normalize_name(att.file_name) | normalize_name(att.title)
                            if any(tn in att_names for tn in target_names):
                                attachment_id = att.id
                                found_page_id = pid
                                break
                        if attachment_id: break
                    except Exception:
                        pass
            
            if not attachment_id or not found_page_id:
                raise ConfluenceError(f"Could not find ID for attachment '{resource.file_name}' to perform REST fallback.") from exc
                
            return self._download_attachment_via_rest(found_page_id, attachment_id, exc)

    def _download_attachment_via_rest(
        self, page_id: str, attachment_id: str, original_error: Exception
    ) -> bytes:
        """
        Скачивает вложение через эндпоинт REST API.

        :param page_id: Идентификатор страницы.
        :param attachment_id: Идентификатор вложения.
        :param original_error: Исходное исключение для сохранения контекста ошибки.
        :return: Бинарное содержимое вложения.
        """
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

    def get_pages_metadata_bulk(self, page_ids: list[str]) -> dict[str, ConfluencePage]:
        """
        Массово получает метаданные страниц по списку их идентификаторов.

        :param page_ids: Список ID страниц.
        :return: Словарь сопоставления ID страницы и объекта ConfluencePage.
        """
        if not page_ids:
            return {}
        
        result = {}
        chunk_size = 20
        for i in range(0, len(page_ids), chunk_size):
            chunk = page_ids[i : i + chunk_size]
            cql = f"id in ({','.join(chunk)})"
            try:
                pages = self.search_pages(cql)
                for page in pages:
                    result[page.id] = page
            except Exception as exc:
                logger.warning("Bulk metadata fetch failed for chunk %s: %s", chunk, exc)
                for pid in chunk:
                    try:
                        result[pid] = self.get_page(pid)
                    except Exception:
                        pass
        return result

    def check_health(self) -> dict:
        """
        Проверяет работоспособность и задержку соединения с Confluence.

        :return: Словарь с состоянием здоровья ("ok" или "error") и задержкой в мс.
        """
        start_time = time.time()
        try:
            self._get("/rest/api/content", {"limit": 1})
            latency = (time.time() - start_time) * 1000
            return {"status": "ok", "latency_ms": round(latency, 2)}
        except Exception as exc:
            return {"status": "error", "message": str(exc)}

    def iter_top_level_pages(self) -> Iterable[ConfluencePage]:
        """
        Итерируется по всем страницам верхнего уровня, определенным в настройках (через ID корня или ключ пространства).

        :return: Итератор объектов ConfluencePage.
        """
        if self.settings.confluence_root_page_id:
            root_id = self.settings.confluence_root_page_id
            cql = f"(id = {root_id} or ancestor = {root_id}) and type = page"
        else:
            cql = f'space="{self.settings.confluence_space_key}" and type=page'
        
        logger.info("Discovering pages using CQL: %s", cql)
        yield from self.search_pages(cql)

    def _page_from_payload(self, payload: dict) -> ConfluencePage:
        """
        Преобразует JSON-ответ API Confluence в объект модели ConfluencePage.

        :param payload: Словарь с данными ответа API.
        :return: Объект ConfluencePage.
        """
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
        """
        Парсит строку даты и времени из формата ISO, используемого Confluence.

        :param value: Строка даты и времени.
        :return: Объект datetime или None, если парсинг невозможен.
        """
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            logger.warning("Cannot parse Confluence datetime %s", value)
            return None
