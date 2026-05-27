import logging
import re
import time
from datetime import UTC, datetime
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup

from app.config import Settings
from app.confluence.client import ConfluenceClient
from app.confluence.jira_client import JiraClient
from app.confluence.models import (
    ConfluencePage,
    Datamart,
    DatamartFact,
    ParseResult,
    ReleaseChange,
    S2TResource,
    Stakeholder,
)
from app.confluence.urls import confluence_urljoin
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
FACT_ALIASES = {
    "business_stakeholders": [
        "заинтересованные со стороны бизнеса",
        "заинтересованное лица",
        "заинтересованные лица",
        "заинтересованные фио",
    ],
    "meta_links": ["мета", "ка фо", "карта данных", "смд"],
    "ke": ["кэ"],
    "db_name": ["имя витрины в бд", "витрина в бд", "название витрины в бд"],
    "periodicity": ["периодичность", "частота"],
    "depth": ["глубина"],
    "bank_process": [
        "процесс из реестра",
        "процесс",
        "реестр зарегистрированных процессов",
        "реестр зарегестрированных процессов",
    ],
    "release_changes": ["изменения в релизах"],
}
JIRA_KEY_RE = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")
PLACEHOLDER_TEXTS = {
    "получение подробных данных проблемы",
    "статус",
}


class ConfluenceParser:
    def __init__(
        self,
        client: ConfluenceClient,
        settings: Settings,
        jira_client: JiraClient | None = None,
    ) -> None:
        self.client = client
        self.settings = settings
        self.jira_client = jira_client

    def parse(self, dry_run: bool = False) -> ParseResult:
        result = ParseResult()
        pattern = normalize_text(self.settings.datamart_page_pattern)
        for page in self.client.iter_top_level_pages():
            if self.settings.confluence_request_delay > 0:
                time.sleep(self.settings.confluence_request_delay)
            if pattern not in normalize_text(page.title):
                continue
            logger.info("Found datamart page %s", page.title)
            datamart = self.parse_datamart_page(page)
            logger.info(
                "Parsed datamart=%s stakeholders=%s release_changes=%s s2t=%s",
                datamart.name,
                len(datamart.stakeholders),
                len(datamart.release_changes),
                datamart.s2t_resource.title if datamart.s2t_resource else "-",
            )
            result.datamarts.append(datamart)
        return result

    def parse_datamart_page(self, page: ConfluencePage) -> Datamart:
        html = page.body_html or ""
        stakeholders = self.extract_stakeholders(html)
        facts = self.extract_datamart_facts(html)
        release_changes = self.extract_release_changes(page, html)
        if self.jira_client:
            self.enrich_release_changes(release_changes)
        candidates = self.find_s2t_candidates(page)
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
            facts=facts,
            release_changes=release_changes,
            s2t_resource=selected,
        )

    def enrich_release_changes(self, changes: list[ReleaseChange]) -> None:
        if not self.jira_client:
            return
        field_mapping = self.jira_client.get_field_mapping()
        for change in changes:
            if not change.jira_key:
                continue
            issue = self.jira_client.get_issue(change.jira_key)
            if not issue:
                continue
            fields = issue.get("fields", {})
            created = fields.get("created")
            if created:
                try:
                    change.jira_created_at = datetime.fromisoformat(created.replace("Z", "+00:00"))
                except Exception:
                    logger.warning("Failed to parse Jira created date: %s", created)

            tag = (change.change_type or "").upper()
            if not tag:
                continue

            changelog = issue.get("changelog", {})
            histories = changelog.get("histories", [])
            histories.sort(key=lambda x: x.get("created", ""), reverse=True)

            found_value = None
            for history in histories:
                for item in history.get("items", []):
                    if (item.get("field") or "").upper() == tag:
                        found_value = item.get("toString")
                        break
                if found_value:
                    break

            if not found_value and tag in field_mapping:
                field_id = field_mapping[tag]
                found_value = fields.get(field_id)

            change.jira_last_activity_value = found_value

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

    def extract_datamart_facts(self, html: str) -> list[DatamartFact]:
        soup = BeautifulSoup(html, "html.parser")
        facts: list[DatamartFact] = []
        seen: set[tuple[str, str, str]] = set()
        for row in soup.find_all("tr"):
            cells = row.find_all(["th", "td"], recursive=False) or row.find_all(["th", "td"])
            if len(cells) < 2:
                continue
            label = self._clean_text(cells[0].get_text(" ", strip=True))
            value = self._clean_text(cells[1].get_text(" ", strip=True))
            if not label or not value:
                continue
            key = self._fact_key(label)
            if key == "unknown":
                continue
            links = self._links_from_node(cells[1])
            marker = (key, label.casefold(), value)
            if marker in seen:
                continue
            seen.add(marker)
            facts.append(DatamartFact(key=key, label=label, value=value, links=links))
        return facts

    def extract_release_changes(self, page: ConfluencePage, html: str) -> list[ReleaseChange]:
        release_page = self._release_page_from_link(page, html)
        if not release_page or not release_page.body_html:
            return []
        return self.parse_release_changes_page(release_page.body_html, release_page.url)

    def parse_release_changes_page(
        self, html: str, source_url: str | None = None
    ) -> list[ReleaseChange]:
        soup = BeautifulSoup(html, "html.parser")
        content = soup.find(id="main-content") or soup
        changes: list[ReleaseChange] = []
        current_version: str | None = None
        pending_jira_key: str | None = None
        pending_jira_title: str | None = None
        pending_status: str | None = None
        for node in content.find_all(["h1", "h2", "h3", "p", "ul", "ol"], recursive=False):
            if node.name in {"h1", "h2", "h3"}:
                text = self._clean_text(node.get_text(" ", strip=True))
                if self._jira_key_from_node(node) and "версия" not in normalize_text(text):
                    continue
                if text:
                    current_version = text
                    pending_jira_key = None
                    pending_jira_title = None
                    pending_status = None
                continue
            if not current_version:
                continue
            jira_key = self._jira_key_from_node(node)
            jira_title = self._jira_title_from_node(node)
            status = self._jira_status_from_node(node)
            if jira_key:
                pending_jira_key = jira_key
                pending_jira_title = jira_title
                pending_status = status
            items = node.find_all("li", recursive=False) if node.name in {"ul", "ol"} else []
            if not items:
                continue
            for item in items:
                item_jira_key = self._jira_key_from_node(item) or jira_key or pending_jira_key
                change_type = self._release_change_type(item)
                summary = self._release_summary(item, change_type)
                if not any([item_jira_key, change_type, summary]):
                    continue
                changes.append(
                    ReleaseChange(
                        version=current_version,
                        jira_key=item_jira_key,
                        jira_title=self._jira_title_from_node(item)
                        or jira_title
                        or pending_jira_title,
                        change_type=change_type,
                        summary=summary,
                        status=self._jira_status_from_node(item) or status or pending_status,
                        source_url=source_url,
                    )
                )
            pending_jira_key = None
            pending_jira_title = None
            pending_status = None
        return changes

    def find_s2t_candidates(self, page: ConfluencePage) -> list[S2TResource]:
        return self._find_s2t_recursive(page, depth=0, visited=set())

    def _find_s2t_recursive(
        self, page: ConfluencePage, depth: int, visited: set[str]
    ) -> list[S2TResource]:
        if page.id in visited or depth > 5:
            return []
        visited.add(page.id)

        logger.info("Recursively searching for S2T files on page '%s' (depth %d)", page.title, depth)

        html = page.body_html
        if html is None:
            try:
                full_page = self.client.get_page(page.id)
                html = full_page.body_html if full_page and full_page.body_html else ""
            except Exception:
                logger.warning("Failed to fetch page body for %s", page.id)
                html = ""

        candidates: list[S2TResource] = []
        # 1. Add direct attachments from current page
        attachments = self.client.get_attachments(page.id)
        self._append_new_resources(candidates, attachments)
        attachment_index = self._attachment_index(attachments)

        if html:
            soup = BeautifulSoup(html, "html.parser")
            # 2. Add files found in tables on current page
            self._append_new_resources(
                candidates,
                self._enrich_resources(
                    self._extract_s2t_table_resources(page, soup), attachment_index
                ),
            )

            # 3. Explore links on current page
            for link in soup.find_all("a"):
                title = link.get_text(" ", strip=True) or link.get("href", "")
                href = link.get("href")
                if not href:
                    continue

                parent_text = link.parent.get_text(" ", strip=True) if link.parent else ""

                if "/download/attachments/" in href and (
                    self._looks_like_s2t_file(href, title) or self._looks_like_s2t(parent_text)
                ):
                    file_name = self._file_name_from_url(href)
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
                    child_page_id = self._page_id_from_url(href)
                    if child_page_id and child_page_id not in visited:
                        try:
                            child_page = self.client.get_page(child_page_id)
                            if child_page:
                                recursive_files = self._find_s2t_recursive(
                                    child_page, depth + 1, visited
                                )
                                self._append_new_resources(candidates, recursive_files)
                        except Exception as exc:
                            logger.warning(
                                "Failed to fetch or process linked page %s: %s", child_page_id, exc
                            )

        # 4. Explore direct child pages
        for child in self.client.get_children(page.id):
            if self._looks_like_s2t(child.title):
                recursive_files = self._find_s2t_recursive(child, depth + 1, visited)
                self._append_new_resources(candidates, recursive_files)

        file_candidates = [
            c
            for c in candidates
            if c.file_name and c.file_name.lower().endswith(SUPPORTED_S2T_SUFFIXES)
        ]

        for candidate in file_candidates:
            candidate.file_date = candidate.file_date or parse_date_from_text(candidate.title)

        return file_candidates

    def _release_page_from_link(self, page: ConfluencePage, html: str) -> ConfluencePage | None:
        soup = BeautifulSoup(html, "html.parser")
        for link in soup.find_all("a"):
            title = link.get_text(" ", strip=True)
            href = link.get("href")
            if not href or "изменения в релизах" not in normalize_text(title):
                continue
            page_id = self._page_id_from_url(href)
            if not page_id:
                continue
            try:
                return self.client.get_page(page_id)
            except Exception:
                logger.warning("Cannot load release changes page %s for %s", href, page.title)
                return None
        return None

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

        def key(item: S2TResource) -> tuple[int, datetime, int]:
            priority = 1 if item.resource_type == "table_latest_row" else 0
            if item.file_date:
                dt = datetime.combine(item.file_date, datetime.min.time(), tzinfo=UTC)
            else:
                dt = self._comparable_datetime(item.updated_at)
            row_number = item.version or 0
            return priority, dt, row_number

        selected = max(candidates, key=key)
        if not selected.file_date and selected.resource_type != "table_latest_row":
            logger.warning(
                "S2T date is absent in title, fallback to updated_at/version for %s", selected.title
            )
        return selected

    @staticmethod
    def _comparable_datetime(value: datetime | None) -> datetime:
        if not value:
            return datetime.min.replace(tzinfo=UTC)
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def _looks_like_s2t(self, value: str) -> bool:
        return any(
            normalize_text(pattern) in normalize_text(value)
            for pattern in self.settings.s2t_patterns
        )

    def _looks_like_s2t_file(self, href: str, title: str) -> bool:
        lowered = f"{href} {title}".lower()
        return any(suffix in lowered for suffix in SUPPORTED_S2T_SUFFIXES)

    def _latest_non_empty_row_resource(self, page: ConfluencePage, rows) -> S2TResource | None:
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
                file_name = self._file_name_from_url(href)
                title = file_name or link.get_text(" ", strip=True) or href or ""
                if href and self._looks_like_s2t_file(href, title):
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

    def _append_new_resources(self, target: list[S2TResource], resources: list[S2TResource]) -> None:
        target_by_key = {resource.resource_key: i for i, resource in enumerate(target)}
        for resource in resources:
            if resource.resource_key in target_by_key:
                idx = target_by_key[resource.resource_key]
                if target[idx].resource_type == "attachment" and resource.resource_type != "attachment":
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

    @staticmethod
    def _clean_text(value: str) -> str:
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def _fact_key(label: str) -> str:
        normalized = normalize_text(label)
        for key, aliases in FACT_ALIASES.items():
            if any(alias in normalized for alias in aliases):
                return key
        return "unknown"

    @staticmethod
    def _links_from_node(node) -> list[dict[str, str]]:
        links = []
        for link in node.find_all("a"):
            href = link.get("href")
            if not href:
                continue
            links.append({"title": link.get_text(" ", strip=True) or href, "url": href})
        return links

    @staticmethod
    def _page_id_from_url(url: str) -> str | None:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        page_id = query.get("pageId", [None])[0]
        if page_id:
            return page_id
        path_parts = [part for part in parsed.path.split("/") if part]
        for part in path_parts:
            if part.isdigit():
                return part
        return None

    @staticmethod
    def _jira_key_from_node(node) -> str | None:
        jira_tag = node.find(attrs={"data-jira-key": True})
        if jira_tag and jira_tag.get("data-jira-key"):
            return str(jira_tag["data-jira-key"])
        match = JIRA_KEY_RE.search(node.get_text(" ", strip=True))
        return match.group(0) if match else None

    @staticmethod
    def _jira_title_from_node(node) -> str | None:
        summary = node.find(class_="summary")
        if not summary:
            return None
        text = ConfluenceParser._clean_text(summary.get_text(" ", strip=True))
        if normalize_text(text) in PLACEHOLDER_TEXTS:
            return None
        return text or None

    @staticmethod
    def _jira_status_from_node(node) -> str | None:
        for tag in node.find_all(class_=lambda value: value and "aui-lozenge" in value):
            if tag.find_parent(class_=lambda value: value and "status-macro" in value):
                continue
            text = ConfluenceParser._clean_text(tag.get_text(" ", strip=True))
            if text and normalize_text(text) not in PLACEHOLDER_TEXTS:
                return text
        return None

    @staticmethod
    def _release_change_type(node) -> str | None:
        for tag in node.find_all(class_=lambda value: value and "status-macro" in value):
            text = ConfluenceParser._clean_text(tag.get_text(" ", strip=True))
            if text:
                return text.lower()
        text = normalize_text(node.get_text(" ", strip=True))
        for change_type in ("изменение", "новое", "исправление"):
            if change_type in text:
                return change_type
        return None

    @staticmethod
    def _release_summary(node, change_type: str | None) -> str | None:
        text = ConfluenceParser._clean_text(node.get_text(" ", strip=True))
        if change_type:
            text = re.sub(change_type, "", text, count=1, flags=re.IGNORECASE).strip()
        text = re.sub(r"^[\s:–—-]+", "", text)
        return text or None

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
