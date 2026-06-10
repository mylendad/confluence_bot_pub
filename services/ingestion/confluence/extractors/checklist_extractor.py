import logging

from bs4 import BeautifulSoup

from services.ingestion.confluence.client import ConfluenceClient
from services.ingestion.confluence.extractors.utils import clean_text, fact_key, links_from_node
from services.ingestion.confluence.models import ConfluencePage, DatamartFact
from shared.utils.text_utils import normalize_text

logger = logging.getLogger(__name__)

class ChecklistExtractor:
    def __init__(self, client: ConfluenceClient):
        self.client = client

    def extract_checklist_facts(
        self, page: ConfluencePage, visited_versions: dict[str, int] | None = None
    ) -> list[DatamartFact]:
        checklist_page = self._find_checklist_page_recursive(
            page, depth=0, visited=set(), visited_versions=visited_versions
        )
        if not checklist_page or not checklist_page.body_html:
            return []

        logger.info("Parsing checklist page: %s", checklist_page.title)
        soup = BeautifulSoup(checklist_page.body_html, "html.parser")
        facts: list[DatamartFact] = []
        seen: set[tuple[str, str, str]] = set()

        for row in soup.find_all("tr"):
            cells = row.find_all(["th", "td"], recursive=False) or row.find_all(["th", "td"])
            if len(cells) < 2:
                continue
            label = clean_text(cells[0].get_text(" ", strip=True))
            value = clean_text(cells[1].get_text(" ", strip=True))
            if not label or not value:
                continue

            key = fact_key(label)
            if key == "unknown":
                key = normalize_text(label).replace(" ", "_")

            links = links_from_node(cells[1])
            marker = (key, label.casefold(), value)
            if marker in seen:
                continue
            seen.add(marker)
            facts.append(DatamartFact(key=key, label=label, value=value, links=links))

        return facts

    def _find_checklist_page_recursive(
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

        kw_checklist = normalize_text("чек-лист")
        kw_checklists = normalize_text("чек-листы")

        norm_title = normalize_text(page.title)
        if kw_checklist in norm_title and kw_checklists not in norm_title:
            return page

        try:
            children = self.client.get_children(page.id)
            children = sorted(children, key=lambda c: c.title, reverse=True)

            for child in children:
                c_norm_title = normalize_text(child.title)
                if kw_checklist in c_norm_title and kw_checklists not in c_norm_title:
                    logger.info("Found checklist page: %s", child.title)
                    full_page = self.client.get_page(child.id)
                    if visited_versions is not None and full_page.version:
                        visited_versions[full_page.id] = full_page.version
                    return full_page

            for child in children:
                c_norm_title = normalize_text(child.title)
                if kw_checklists in c_norm_title:
                    logger.info("Found checklists folder: %s", child.title)
                    res = self._find_checklist_page_recursive(
                        child, depth + 1, visited, visited_versions=visited_versions
                    )
                    if res:
                        return res

        except Exception as exc:
            logger.warning("Error searching checklists for page %s at stage checklist_discovery: %s", page.id, exc)

        return None
