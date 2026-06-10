import logging
from datetime import UTC, datetime

from bs4 import BeautifulSoup

from services.ingestion.confluence.client import ConfluenceClient
from services.ingestion.confluence.extractors.utils import (
    LATEST_MARKERS,
    SUPPORTED_S2T_SUFFIXES,
    attachment_lookup_key,
    file_name_from_url,
)
from services.ingestion.confluence.models import ConfluencePage, S2TResource
from services.ingestion.confluence.urls import confluence_urljoin
from shared.utils.date_utils import parse_date_from_text
from shared.utils.text_utils import normalize_text

logger = logging.getLogger(__name__)

class S2TDiscovery:
    def __init__(self, client: ConfluenceClient, settings):
        self.client = client
        self.settings = settings

    def find_s2t_candidates(
        self, page: ConfluencePage, visited_versions: dict[str, int] | None = None
    ) -> list[S2TResource]:
        return self._find_s2t_recursive(
            page, depth=0, visited=set(), visited_versions=visited_versions
        )

    def choose_latest_s2t(self, candidates: list[S2TResource]) -> S2TResource | None:
        if not candidates:
            logger.warning("S2T resource was not found")
            return None

        def key(item: S2TResource) -> tuple[int, int, datetime, int]:
            has_download = 1 if item.download_url else 0
            priority = 1 if item.resource_type == "table_latest_row" else 0
            if item.file_date:
                dt = datetime.combine(item.file_date, datetime.min.time(), tzinfo=UTC)
            else:
                dt = self._comparable_datetime(item.updated_at)
            row_number = item.version or 0
            return has_download, priority, dt, row_number

        selected = max(candidates, key=key)
        if not selected.file_date and selected.resource_type != "table_latest_row":
            logger.warning(
                "S2T date is absent in title, fallback to updated_at/version for %s", selected.title
            )
        return selected

    def _comparable_datetime(self, value: datetime | None) -> datetime:
        if not value:
            return datetime.min.replace(tzinfo=UTC)
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def _find_s2t_recursive(
        self,
        page: ConfluencePage,
        depth: int,
        visited: set[str],
        visited_versions: dict[str, int] | None = None,
    ) -> list[S2TResource]:
        if page.id in visited or depth > 5:
            return []
        visited.add(page.id)
        if visited_versions is not None and page.version:
            visited_versions[page.id] = page.version

        logger.info(
            "Recursively searching for S2T files on page '%s' (depth %d)", page.title, depth
        )

        html = page.body_html
        if html is None:
            try:
                full_page = self.client.get_page(page.id)
                html = full_page.body_html if full_page and full_page.body_html else ""
                if visited_versions is not None and full_page and full_page.version:
                    visited_versions[full_page.id] = full_page.version
            except Exception as exc:
                logger.warning("Failed to fetch page body for %s: %s", page.id, exc)
                html = ""

        candidates: list[S2TResource] = []
        attachments = self.client.get_attachments(page.id)
        self._append_new_resources(candidates, attachments)
        attachment_index = self._attachment_index(attachments)

        if html:
            soup = BeautifulSoup(html, "html.parser")
            self._append_new_resources(
                candidates,
                self._enrich_resources(
                    self._extract_s2t_table_resources(page, soup), attachment_index
                ),
            )

            for link in soup.find_all("a"):
                title = link.get_text(" ", strip=True) or link.get("href", "")
                href = link.get("href")
                if not href:
                    continue

                parent_text = link.parent.get_text(" ", strip=True) if link.parent else ""

                if "/download/attachments/" in href and (
                    self._looks_like_s2t_file(href, title)
                    or self._looks_like_s2t(title)
                    or self._looks_like_s2t(parent_text)
                ):
                    file_name = file_name_from_url(href)
                    resource_title = file_name or title
                    self._append_new_resources(
                        candidates,
                        [
                            self._enrich_resource(
                                S2TResource(
                                    title=resource_title,
                                    url=confluence_urljoin(page.url, href),
                                    file_name=file_name or resource_title,
                                    resource_type="link",
                                    file_date=parse_date_from_text(resource_title),
                                    updated_at=page.updated_at,
                                ),
                                attachment_index,
                            )
                        ],
                    )
                elif ("pageId=" in href or "/display/" in href) and self._looks_like_s2t(
                    f"{title} {parent_text}"
                ):
                    try:
                        from services.ingestion.confluence.extractors.utils import page_id_from_url
                        child_page_id = page_id_from_url(href)
                        if child_page_id and child_page_id not in visited:
                            child_page = self.client.get_page(child_page_id)
                            if child_page:
                                recursive_files = self._find_s2t_recursive(
                                    child_page,
                                    depth + 1,
                                    visited,
                                    visited_versions=visited_versions,
                                )
                                self._append_new_resources(candidates, recursive_files)
                    except Exception as exc:
                        logger.warning(
                            "Failed to fetch or process linked page %s: %s", href, exc
                        )

            for attachment_name in self._attachment_references(soup):
                self._append_new_resources(
                    candidates,
                    [
                        self._enrich_resource(
                            self._resource_from_attachment_reference(
                                page=page,
                                file_name=attachment_name,
                                resource_type="body_reference",
                                row_number=0,
                            ),
                            attachment_index,
                        )
                    ],
                )

        try:
            for child in self.client.get_children(page.id):
                if self._looks_like_s2t(child.title):
                    recursive_files = self._find_s2t_recursive(
                        child, depth + 1, visited, visited_versions=visited_versions
                    )
                    self._append_new_resources(candidates, recursive_files)
        except Exception as exc:
            logger.warning("Failed to iterate children of %s: %s", page.id, exc)

        file_candidates = [
            c
            for c in candidates
            if c.file_name and c.file_name.lower().endswith(SUPPORTED_S2T_SUFFIXES)
        ]

        for candidate in file_candidates:
            candidate.file_date = candidate.file_date or parse_date_from_text(candidate.title)

        return file_candidates

    def _extract_s2t_table_resources(
        self, page: ConfluencePage, soup: BeautifulSoup
    ) -> list[S2TResource]:
        resources: list[S2TResource] = []
        tables = soup.find_all("table") or [soup]
        for table in tables:
            rows = table.find_all("tr")
            if self._table_has_latest_marker(rows):
                latest = self._latest_non_empty_row_resource(page, rows)
                if latest:
                    resources.append(latest)

            for row_number, row in enumerate(rows, start=1):
                cells = row.find_all(["th", "td"])

                table_date = None
                date_cell_index = -1
                for i, cell in enumerate(cells):
                    table_date = parse_date_from_text(cell.get_text(" ", strip=True))
                    if table_date:
                        date_cell_index = i
                        break

                if table_date and date_cell_index >= 0:
                    resources.extend(
                        self._resources_from_neighbor_links(
                            page=page,
                            cells=cells,
                            index=date_cell_index,
                            file_date=table_date,
                            resource_type="table_link",
                            row_number=row_number,
                        )
                    )
                else:
                    for link in row.find_all("a"):
                        href = link.get("href")
                        if not href:
                            continue
                        title = link.get_text(" ", strip=True)
                        if self._looks_like_s2t_file(href, title) or self._looks_like_s2t(title):
                            resources.append(
                                S2TResource(
                                    title=title,
                                    url=confluence_urljoin(page.url, href),
                                    file_name=file_name_from_url(href) or title,
                                    resource_type="table_generic_link",
                                    updated_at=page.updated_at,
                                    version=row_number,
                                    page_id=page.id,
                                )
                            )
        return resources

    def _looks_like_s2t(self, value: str) -> bool:
        return any(
            normalize_text(pattern) in normalize_text(value)
            for pattern in self.settings.s2t_patterns
        )

    def _has_s2t_extension(self, value: str) -> bool:
        return any(suffix in value.lower() for suffix in SUPPORTED_S2T_SUFFIXES)

    def _looks_like_s2t_file(self, href: str, title: str) -> bool:
        lowered = f"{href} {title}".lower()
        if not self._has_s2t_extension(lowered):
            return False
        return self._looks_like_s2t(lowered)

    def _latest_non_empty_row_resource(self, page: ConfluencePage, rows) -> S2TResource | None:
        for row_number, row in reversed(list(enumerate(rows, start=1))):
            if not row.get_text(" ", strip=True):
                continue
            for link in row.find_all("a"):
                href = link.get("href")
                file_name = file_name_from_url(href)
                title = file_name or link.get_text(" ", strip=True) or href or ""
                if href and self._has_s2t_extension(href or title):
                    return S2TResource(
                        title=title,
                        url=confluence_urljoin(page.url, href),
                        file_name=file_name or title,
                        resource_type="table_latest_row",
                        updated_at=page.updated_at,
                        version=row_number,
                        page_id=page.id,
                    )
            for attachment in self._attachment_references(row):
                return self._resource_from_attachment_reference(
                    page=page,
                    file_name=attachment,
                    resource_type="table_latest_row",
                    row_number=row_number,
                )
        return None

    def _resources_from_neighbor_links(
        self,
        page: ConfluencePage,
        cells,
        index: int,
        file_date,
        resource_type: str,
        row_number: int,
    ) -> list[S2TResource]:
        resources: list[S2TResource] = []
        for link_cell in self._neighbor_cells(cells, index):
            for link in link_cell.find_all("a"):
                href = link.get("href")
                file_name = file_name_from_url(href)
                title = file_name or link.get_text(" ", strip=True) or href or ""
                if href and self._has_s2t_extension(href or title):
                    resources.append(
                        S2TResource(
                            title=title,
                            url=confluence_urljoin(page.url, href),
                            file_name=file_name or title,
                            resource_type=resource_type,
                            file_date=file_date,
                            updated_at=page.updated_at,
                            version=row_number,
                            page_id=page.id,
                        )
                    )
            for attachment in self._attachment_references(link_cell):
                resources.append(
                    self._resource_from_attachment_reference(
                        page=page,
                        file_name=attachment,
                        resource_type=resource_type,
                        row_number=row_number,
                        file_date=file_date,
                    )
                )
        return resources

    def _resource_from_attachment_reference(
        self,
        page: ConfluencePage,
        file_name: str,
        resource_type: str,
        row_number: int,
        file_date=None,
    ) -> S2TResource:
        return S2TResource(
            title=file_name,
            url=confluence_urljoin(page.url, f"/download/attachments/{page.id}/{file_name}"),
            file_name=file_name,
            resource_type=resource_type,
            file_date=file_date,
            updated_at=page.updated_at,
            version=row_number,
            page_id=page.id,
        )

    def _attachment_references(self, node) -> list[str]:
        names: list[str] = []
        for tag in node.find_all():
            attrs = {str(key).lower(): str(value) for key, value in tag.attrs.items()}
            file_name = attrs.get("ri:filename") or attrs.get("filename")
            if file_name and self._looks_like_s2t_file(file_name, file_name):
                names.append(file_name)
        return names

    def _append_new_resources(
        self, target: list[S2TResource], resources: list[S2TResource]
    ) -> None:
        target_by_key = {resource.resource_key: i for i, resource in enumerate(target)}
        for resource in resources:
            if resource.resource_key in target_by_key:
                idx = target_by_key[resource.resource_key]
                if (
                    target[idx].resource_type == "attachment"
                    and resource.resource_type != "attachment"
                ):
                    target[idx] = resource
                continue
            target.append(resource)
            target_by_key[resource.resource_key] = len(target) - 1

    def _enrich_resources(
        self, resources: list[S2TResource], attachment_index: dict[str, S2TResource]
    ) -> list[S2TResource]:
        return [self._enrich_resource(resource, attachment_index) for resource in resources]

    def _enrich_resource(
        self, resource: S2TResource, attachment_index: dict[str, S2TResource]
    ) -> S2TResource:
        attachment = self._find_attachment(resource, attachment_index)
        if not attachment:
            return resource
        return resource.model_copy(
            update={
                "id": attachment.id,
                "title": attachment.title or resource.title,
                "url": attachment.url or resource.url,
                "file_name": attachment.file_name or resource.file_name,
                "updated_at": attachment.updated_at or resource.updated_at,
                "version": attachment.version,
                "version_when": attachment.version_when,
                "file_size": attachment.file_size,
                "download_url": attachment.download_url,
                "media_type": attachment.media_type,
                "page_id": attachment.page_id or resource.page_id,
            }
        )

    def _find_attachment(
        self, resource: S2TResource, attachment_index: dict[str, S2TResource]
    ) -> S2TResource | None:
        for value in (
            resource.file_name,
            resource.title,
            file_name_from_url(resource.download_url),
            file_name_from_url(resource.url),
            resource.download_url,
            resource.url,
        ):
            key = attachment_lookup_key(value)
            if key and key in attachment_index:
                return attachment_index[key]
        return None

    def _attachment_index(self, attachments: list[S2TResource]) -> dict[str, S2TResource]:
        index: dict[str, S2TResource] = {}
        for attachment in attachments:
            for value in (
                attachment.file_name,
                attachment.title,
                file_name_from_url(attachment.download_url),
                file_name_from_url(attachment.url),
                attachment.download_url,
                attachment.url,
            ):
                key = attachment_lookup_key(value)
                if key:
                    index[key] = attachment
        return index

    def _table_has_latest_marker(self, rows) -> bool:
        for row in rows:
            tokens = normalize_text(row.get_text(" ", strip=True)).split()
            if any(marker in tokens for marker in LATEST_MARKERS):
                return True
        return False

    def _neighbor_cells(self, cells, index: int):
        start = max(0, index - 1)
        end = min(len(cells), index + 2)
        return [cells[i] for i in range(start, end) if i != index]
