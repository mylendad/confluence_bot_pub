import logging
import re

from bs4 import BeautifulSoup

from services.ingestion.confluence.client import ConfluenceClient
from services.ingestion.confluence.extractors.utils import (
    JIRA_KEY_RE,
    PLACEHOLDER_TEXTS,
    clean_text,
    page_id_from_url,
)
from services.ingestion.confluence.models import ConfluencePage, ReleaseChange
from shared.utils.text_utils import normalize_text

logger = logging.getLogger(__name__)

class ReleaseChangesExtractor:
    def __init__(self, client: ConfluenceClient):
        self.client = client

    def extract_release_changes(
        self, page: ConfluencePage, html: str, visited_versions: dict[str, int] | None = None
    ) -> list[ReleaseChange]:
        release_page = self._find_release_page_recursive(
            page, depth=0, visited=set(), visited_versions=visited_versions
        )
        if not release_page or not release_page.body_html:
            return []
        changes = self.parse_release_changes_page(release_page.body_html, release_page.url)
        changes.sort(key=lambda x: (x.version or "", x.jira_key or ""))
        return changes

    def parse_release_changes_page(
        self, html: str, source_url: str | None = None
    ) -> list[ReleaseChange]:
        soup = BeautifulSoup(html, "html.parser")
        changes: list[ReleaseChange] = []

        current_version = "Неизвестная версия"
        current_jira_keys = []
        current_jira_titles = {}
        current_status = None

        for node in soup.find_all(["h1", "h2", "h3", "h4", "p", "ul", "ol"]):
            text = clean_text(node.get_text(" ", strip=True))
            norm_text = normalize_text(text)

            if node.name in ["h1", "h2", "h3", "h4"] or ("версия" in norm_text and len(text) < 50):
                if (
                    "версия" in norm_text
                    or "релиз" in norm_text
                    or re.search(r"202[0-9]", norm_text)
                ):
                    current_version = text
                    current_jira_keys = []
                    current_jira_titles = {}
                    current_status = None
                    continue

            node_keys = self._jira_keys_from_node(node)
            if node_keys:
                current_jira_keys = node_keys
                for key in node_keys:
                    issue_node = node.find(attrs={"data-jira-key": key})
                    if issue_node:
                        title = self._jira_title_from_node(issue_node)
                        if title:
                            current_jira_titles[key] = title

                node_status = self._jira_status_from_node(node)
                if node_status:
                    current_status = node_status

            if node.name in ["ul", "ol"]:
                for item in node.find_all("li", recursive=False):
                    item_keys = self._jira_keys_from_node(item) or current_jira_keys

                    if not item_keys:
                        continue

                    for key in self._jira_keys_from_node(item):
                        issue_node = item.find(attrs={"data-jira-key": key})
                        if issue_node:
                            title = self._jira_title_from_node(issue_node)
                            if title:
                                current_jira_titles[key] = title

                    change_type = self._release_change_type(item)
                    summary = self._release_summary(item, change_type)

                    item_status = self._jira_status_from_node(item) or current_status

                    if summary and ("[" in summary and "]" in summary):
                        continue

                    for key in item_keys:
                        changes.append(
                            ReleaseChange(
                                version=current_version,
                                jira_key=key,
                                jira_title=current_jira_titles.get(key),
                                change_type=change_type,
                                summary=summary,
                                status=item_status,
                                source_url=source_url,
                            )
                        )

        return changes

    def _find_release_page_recursive(
        self,
        page: ConfluencePage,
        depth: int,
        visited: set[str],
        visited_versions: dict[str, int] | None = None,
    ) -> ConfluencePage | None:
        if page.id in visited or depth > 3:
            return None
        visited.add(page.id)
        if visited_versions is not None and page.version:
            visited_versions[page.id] = page.version

        html = page.body_html
        if html is None:
            try:
                full_page = self.client.get_page(page.id)
                html = full_page.body_html or ""
                if visited_versions is not None and full_page.version:
                    visited_versions[full_page.id] = full_page.version
            except Exception as exc:
                logger.warning("Error fetching full page %s during release changes discovery: %s", page.id, exc)
                html = ""

        found = self._release_page_from_link(page, html, visited_versions=visited_versions)
        if found:
            return found

        try:
            children = self.client.get_children(page.id)
            for child in children:
                norm_title = normalize_text(child.title)
                if any(
                    kw in norm_title
                    for kw in ["изменения в релизах", "журнал изменений", "список изменений"]
                ):
                    logger.info(f"Found release changes by child page title: '{child.title}'")
                    full_child = self.client.get_page(child.id)
                    if visited_versions is not None and full_child.version:
                        visited_versions[full_child.id] = full_child.version
                    return full_child

                res = self._find_release_page_recursive(
                    child, depth + 1, visited, visited_versions=visited_versions
                )
                if res:
                    return res
        except Exception as exc:
            logger.warning("Error iterating children of page %s during release changes discovery: %s", page.id, exc)

        return None

    def _release_page_from_link(
        self, page: ConfluencePage, html: str, visited_versions: dict[str, int] | None = None
    ) -> ConfluencePage | None:
        if "шаблон" in normalize_text(page.title):
            return None

        try:
            children = self.client.get_children(page.id)
            for child in children:
                norm_child_title = normalize_text(child.title)
                if any(
                    kw in norm_child_title
                    for kw in ["изменения в релизах", "журнал изменений", "список изменений"]
                ):
                    if "шаблон" in norm_child_title:
                        continue
                    logger.info(f"Found release changes child page: '{child.title}'")
                    full_child = self.client.get_page(child.id)
                    if visited_versions is not None and full_child.version:
                        visited_versions[full_child.id] = full_child.version
                    return full_child
        except Exception as exc:
            logger.warning("Failed to fetch children of %s for link search: %s", page.id, exc)

        soup = BeautifulSoup(html, "html.parser")

        for link_tag in soup.find_all(["a", "ac:link"]):
            link_text = ""
            page_id = None

            if link_tag.name == "a":
                link_text = link_tag.get_text(" ", strip=True)
                page_id = page_id_from_url(link_tag.get("href", ""))
            else:
                ri_page = link_tag.find("ri:page")
                if ri_page:
                    link_text = ri_page.get("ri:content-title") or ""
                    if not link_text:
                        link_text = link_tag.get_text(" ", strip=True)

            if not link_text:
                continue

            norm_text = normalize_text(link_text)
            if any(
                kw in norm_text
                for kw in [
                    "изменения в релизах",
                    "журнал изменений",
                    "список изменений",
                    "история изменений",
                ]
            ):
                if not page_id and link_tag.name == "ac:link":
                    ri_page = link_tag.find("ri:page")
                    if ri_page:
                        title = ri_page.get("ri:content-title")
                        if title:
                            for child in self.client.get_children(page.id):
                                if child.title == title:
                                    page_id = child.id
                                    break

                if page_id:
                    logger.info(f"Found release changes link '{link_text}' (ID: {page_id})")
                    try:
                        full_page = self.client.get_page(page_id)
                        if visited_versions is not None and full_page.version:
                            visited_versions[full_page.id] = full_page.version
                        return full_page
                    except Exception as exc:
                        logger.warning("Failed to fetch release page %s: %s", page_id, exc)

        return None

    def _jira_keys_from_node(self, node) -> list[str]:
        keys = []
        for tag in node.find_all(attrs={"data-jira-key": True}):
            if tag.get("data-jira-key"):
                keys.append(str(tag["data-jira-key"]))

        text = node.get_text(" ", strip=True)
        found_in_text = JIRA_KEY_RE.findall(text)
        for k in found_in_text:
            if k not in keys:
                keys.append(k)
        return keys

    def _jira_title_from_node(self, node) -> str | None:
        summary = node.find(class_="summary")
        if not summary:
            return None
        text = clean_text(summary.get_text(" ", strip=True))
        if normalize_text(text) in PLACEHOLDER_TEXTS:
            return None
        return text or None

    def _jira_status_from_node(self, node) -> str | None:
        for tag in node.find_all(class_=lambda value: value and "aui-lozenge" in value):
            if tag.find_parent(class_=lambda value: value and "status-macro" in value):
                continue
            text = clean_text(tag.get_text(" ", strip=True))
            if text and normalize_text(text) not in PLACEHOLDER_TEXTS:
                return text
        return None

    def _release_change_type(self, node) -> str | None:
        for tag in node.find_all(class_=lambda value: value and "status-macro" in value):
            text = clean_text(tag.get_text(" ", strip=True))
            if text:
                return text.lower()
        text = normalize_text(node.get_text(" ", strip=True))
        for change_type in ("изменение", "новое", "исправление"):
            if change_type in text:
                return change_type
        return None

    def _release_summary(self, node, change_type: str | None) -> str | None:
        text = clean_text(node.get_text(" ", strip=True))
        if change_type:
            text = re.sub(change_type, "", text, count=1, flags=re.IGNORECASE).strip()
        text = re.sub(r"^[\s:–—-]+", "", text)
        return text or None
