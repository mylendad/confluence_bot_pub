import logging
import re
from datetime import datetime
from urllib.parse import unquote, urljoin, urlparse

from bs4 import BeautifulSoup

from app.config import Settings
from app.confluence.client import ConfluenceClient
from app.confluence.models import ConfluencePage, Datamart, ParseResult, S2TResource, Stakeholder
from app.utils.date_utils import parse_date_from_text
from app.utils.text_utils import fuzzy_contains, normalize_text

logger = logging.getLogger(__name__)

OWNER_LABELS = [
    "заинтересованные лица",
    "заинтересовпнные лица",
    "владельцы",
    "ответственные",
    "контакты",
]
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
SUPPORTED_S2T_SUFFIXES = (".xlsx", ".xls", ".csv")
LATEST_MARKERS = {"новый", "new", "latest", "актуальный"}


class ConfluenceParser:
    def __init__(self, client: ConfluenceClient, settings: Settings) -> None:
        self.client = client
        self.settings = settings

    def parse(self, dry_run: bool = False) -> ParseResult:
        result = ParseResult()
        pattern = normalize_text(self.settings.datamart_page_pattern)
        for page in self.client.iter_top_level_pages():
            if pattern not in normalize_text(page.title):
                continue
            logger.info("Found datamart page %s", page.title)
            datamart = self.parse_datamart_page(page)
            if dry_run:
                logger.info(
                    "Dry run datamart=%s stakeholders=%s s2t=%s",
                    datamart.name,
                    len(datamart.stakeholders),
                    datamart.s2t_resource,
                )
            result.datamarts.append(datamart)
        return result

    def parse_datamart_page(self, page: ConfluencePage) -> Datamart:
        html = page.body_html or ""
        stakeholders = self.extract_stakeholders(html)
        candidates = self.find_s2t_candidates(page, html)
        selected = self.choose_latest_s2t(candidates)
        return Datamart(
            name=page.title,
            confluence_page_id=page.id,
            confluence_url=page.url,
            page_version=page.version,
            page_version_when=page.version_when,
            page_last_modified=page.last_modified,
            page_history_last_updated=page.history_last_updated,
            stakeholders=stakeholders,
            s2t_resource=selected,
        )

    def extract_stakeholders(self, html: str) -> list[Stakeholder]:
        soup = BeautifulSoup(html, "html.parser")
        stakeholders: list[Stakeholder] = []
        for row in soup.find_all("tr"):
            cells = [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
            if len(cells) >= 2 and fuzzy_contains(cells[0], OWNER_LABELS):
                stakeholders.extend(self._stakeholders_from_text(cells[1], row))
        if stakeholders:
            return stakeholders
        text = soup.get_text("\n", strip=True)
        lines = text.splitlines()
        for idx, line in enumerate(lines):
            if fuzzy_contains(line, OWNER_LABELS):
                block = " ".join(lines[idx + 1 : idx + 5])
                stakeholders.extend(self._stakeholders_from_text(block, None))
                break
        return stakeholders

    def find_s2t_candidates(self, page: ConfluencePage, html: str) -> list[S2TResource]:
        attachments = self.client.get_attachments(page.id)
        candidates: list[S2TResource] = []
        attachment_index = self._attachment_index(attachments)
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
            if self._looks_like_s2t(title) or self._looks_like_s2t(href or ""):
                file_name = self._file_name_from_url(href)
                resource_title = file_name or title
                self._append_new_resources(
                    candidates,
                    [
                        self._enrich_resource(
                            S2TResource(
                                title=resource_title,
                                url=urljoin(page.url, href) if href else None,
                                file_name=file_name or resource_title,
                                resource_type="link",
                                file_date=parse_date_from_text(resource_title),
                                updated_at=page.updated_at,
                            ),
                            attachment_index,
                        )
                    ],
                )
        self._append_new_resources(candidates, attachments)
        for child in self.client.get_children(page.id):
            if self._looks_like_s2t(child.title):
                child_attachments = self.client.get_attachments(child.id)
                child_attachment_index = self._attachment_index(child_attachments)
                if child.body_html:
                    child_soup = BeautifulSoup(child.body_html, "html.parser")
                    self._append_new_resources(
                        candidates,
                        self._enrich_resources(
                            self._extract_s2t_table_resources(child, child_soup),
                            child_attachment_index,
                        ),
                    )
                self._append_new_resources(candidates, child_attachments)
                self._append_new_resources(
                    candidates,
                    [
                        S2TResource(
                            title=child.title,
                            url=child.url,
                            resource_type="page",
                            file_name=child.title,
                            file_date=parse_date_from_text(child.title),
                            updated_at=child.updated_at,
                            page_id=child.id,
                        )
                    ],
                )
        for candidate in candidates:
            candidate.file_date = candidate.file_date or parse_date_from_text(candidate.title)
        return candidates

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
                for index, cell in enumerate(cells):
                    table_date = parse_date_from_text(cell.get_text(" ", strip=True))
                    if not table_date:
                        continue
                    resources.extend(
                        self._resources_from_neighbor_links(
                            page=page,
                            cells=cells,
                            index=index,
                            file_date=table_date,
                            resource_type="table_link",
                            row_number=row_number,
                        )
                    )
        return resources

    def choose_latest_s2t(self, candidates: list[S2TResource]) -> S2TResource | None:
        if not candidates:
            logger.warning("S2T resource was not found")
            return None
        for candidate in candidates:
            candidate.file_date = candidate.file_date or parse_date_from_text(candidate.title)

        def key(item: S2TResource) -> tuple[int, datetime, int]:
            priority = 1 if item.resource_type == "table_latest_row" else 0
            if item.file_date:
                dt = datetime.combine(item.file_date, datetime.min.time())
            else:
                dt = item.updated_at or datetime.min
            return priority, dt, item.version or 0

        selected = max(candidates, key=key)
        if not selected.file_date and selected.resource_type != "table_latest_row":
            logger.warning(
                "S2T date is absent in title, fallback to updated_at/version for %s", selected.title
            )
        return selected

    def _looks_like_s2t(self, value: str) -> bool:
        return any(
            normalize_text(pattern) in normalize_text(value)
            for pattern in self.settings.s2t_patterns
        )

    def _looks_like_s2t_file(self, href: str, title: str) -> bool:
        value = normalize_text(f"{href} {title}")
        return value.endswith(SUPPORTED_S2T_SUFFIXES) or any(
            suffix in value for suffix in SUPPORTED_S2T_SUFFIXES
        )

    def _latest_non_empty_row_resource(
        self, page: ConfluencePage, rows
    ) -> S2TResource | None:
        for row_number, row in reversed(list(enumerate(rows, start=1))):
            if not row.get_text(" ", strip=True):
                continue
            for link in row.find_all("a"):
                href = link.get("href")
                file_name = self._file_name_from_url(href)
                title = file_name or link.get_text(" ", strip=True) or href or ""
                if href and self._looks_like_s2t_file(href, title):
                    return S2TResource(
                        title=title,
                        url=urljoin(page.url, href),
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
                file_name = self._file_name_from_url(href)
                title = file_name or link.get_text(" ", strip=True) or href or ""
                if href and self._looks_like_s2t_file(href, title):
                    resources.append(
                        S2TResource(
                            title=title,
                            url=urljoin(page.url, href),
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
            url=urljoin(page.url, f"/download/attachments/{page.id}/{file_name}"),
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
        known = {resource.resource_key for resource in target}
        for resource in resources:
            if resource.resource_key in known:
                continue
            target.append(resource)
            known.add(resource.resource_key)

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
            self._file_name_from_url(resource.download_url),
            self._file_name_from_url(resource.url),
            resource.download_url,
            resource.url,
        ):
            key = self._attachment_lookup_key(value)
            if key and key in attachment_index:
                return attachment_index[key]
        return None

    def _attachment_index(self, attachments: list[S2TResource]) -> dict[str, S2TResource]:
        index: dict[str, S2TResource] = {}
        for attachment in attachments:
            for value in (
                attachment.file_name,
                attachment.title,
                self._file_name_from_url(attachment.download_url),
                self._file_name_from_url(attachment.url),
                attachment.download_url,
                attachment.url,
            ):
                key = self._attachment_lookup_key(value)
                if key:
                    index[key] = attachment
        return index

    @staticmethod
    def _attachment_lookup_key(value: str | None) -> str | None:
        if not value:
            return None
        return unquote(value).strip().casefold()

    @staticmethod
    def _file_name_from_url(url: str | None) -> str | None:
        if not url:
            return None
        path = urlparse(url).path
        if not path or path.endswith("/"):
            return None
        return unquote(path.rsplit("/", 1)[-1])

    @staticmethod
    def _table_has_latest_marker(rows) -> bool:
        for row in rows:
            tokens = normalize_text(row.get_text(" ", strip=True)).split()
            if any(marker in tokens for marker in LATEST_MARKERS):
                return True
        return False

    @staticmethod
    def _neighbor_cells(cells, index: int):
        start = max(0, index - 1)
        end = min(len(cells), index + 2)
        return [cells[i] for i in range(start, end) if i != index]

    def _stakeholders_from_text(self, text: str, row) -> list[Stakeholder]:
        emails = EMAIL_RE.findall(text)
        names = [
            part.strip(" ,;")
            for part in re.split(r"[,;\n]", EMAIL_RE.sub("", text))
            if part.strip(" ,;")
        ]
        links = []
        if row is not None:
            links = [a.get("href") for a in row.find_all("a") if a.get("href")]
        if not emails and not names:
            return []
        size = max(len(emails), len(names), 1)
        return [
            Stakeholder(
                name=names[i] if i < len(names) else None,
                email=emails[i] if i < len(emails) else None,
                profile_url=links[i] if i < len(links) else None,
            )
            for i in range(size)
        ]
