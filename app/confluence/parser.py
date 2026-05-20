import logging
import re
from datetime import datetime
from urllib.parse import urljoin

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
        candidates = self.client.get_attachments(page.id)
        soup = BeautifulSoup(html, "html.parser")
        candidates.extend(self._extract_s2t_table_resources(page, soup))
        for link in soup.find_all("a"):
            title = link.get_text(" ", strip=True) or link.get("href", "")
            href = link.get("href")
            if self._looks_like_s2t(title) or self._looks_like_s2t(href or ""):
                candidates.append(
                    S2TResource(
                        title=title,
                        url=href,
                        file_name=title,
                        resource_type="link",
                        file_date=parse_date_from_text(title),
                        updated_at=page.updated_at,
                    )
                )
        for child in self.client.get_children(page.id):
            if self._looks_like_s2t(child.title):
                if child.body_html:
                    child_soup = BeautifulSoup(child.body_html, "html.parser")
                    candidates.extend(self._extract_s2t_table_resources(child, child_soup))
                candidates.extend(self.client.get_attachments(child.id))
                candidates.append(
                    S2TResource(
                        title=child.title,
                        url=child.url,
                        resource_type="page",
                        file_name=child.title,
                        file_date=parse_date_from_text(child.title),
                        updated_at=child.updated_at,
                        page_id=child.id,
                    )
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
                title = link.get_text(" ", strip=True) or href or ""
                if href and self._looks_like_s2t_file(href, title):
                    return S2TResource(
                        title=title,
                        url=urljoin(page.url, href),
                        file_name=title,
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
                title = link.get_text(" ", strip=True) or href or ""
                if href and self._looks_like_s2t_file(href, title):
                    resources.append(
                        S2TResource(
                            title=title,
                            url=urljoin(page.url, href),
                            file_name=title,
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
