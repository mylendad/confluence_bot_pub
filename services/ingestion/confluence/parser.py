import logging

from services.ingestion.confluence.client import ConfluenceClient
from services.ingestion.confluence.extractors.checklist_extractor import ChecklistExtractor
from services.ingestion.confluence.extractors.fact_extractor import FactExtractor
from services.ingestion.confluence.extractors.jira_enricher import JiraReleaseEnricher
from services.ingestion.confluence.extractors.release_changes_extractor import (
    ReleaseChangesExtractor,
)
from services.ingestion.confluence.extractors.s2t_discovery import S2TDiscovery
from services.ingestion.confluence.jira_client import JiraClient
from services.ingestion.confluence.models import ConfluencePage, Datamart, ParseResult
from shared.config.config import Settings
from shared.utils.text_utils import normalize_text

logger = logging.getLogger(__name__)

class ConfluenceParser:
    """
    Парсер страниц Confluence для извлечения информации о витринах данных.
    Работает как фасад над набором Extractors.
    """

    def __init__(
        self,
        client: ConfluenceClient,
        settings: Settings,
        jira_client: JiraClient | None = None,
    ) -> None:
        self.client = client
        self.settings = settings
        self.jira_client = jira_client

        self.fact_extractor = FactExtractor()
        self.checklist_extractor = ChecklistExtractor(client)
        self.release_extractor = ReleaseChangesExtractor(client)
        self.s2t_discovery = S2TDiscovery(client, settings)
        self.jira_enricher = JiraReleaseEnricher(jira_client)

    def parse(self, dry_run: bool = False, skip_jira: bool = False) -> ParseResult:
        result = ParseResult()
        pattern = normalize_text(self.settings.datamart_page_pattern)
        for page in self.client.iter_top_level_pages():
            if pattern not in normalize_text(page.title):
                continue
            logger.info("Found datamart page %s", page.title)
            datamart = self.parse_datamart_page(page, skip_jira=skip_jira)
            logger.info(
                "Parsed datamart=%s stakeholders=%s release_changes=%s s2t=%s",
                datamart.name,
                len(datamart.stakeholders),
                len(datamart.release_changes),
                datamart.s2t_resource.title if datamart.s2t_resource else "-",
            )
            result.datamarts.append(datamart)
        return result

    def parse_datamart_page(self, page: ConfluencePage, skip_jira: bool = False) -> Datamart:
        visited_versions: dict[str, int] = {}
        if page.version:
            visited_versions[page.id] = page.version

        html = page.body_html or ""
        stakeholders = self.fact_extractor.extract_stakeholders(html)
        facts = self.fact_extractor.extract_datamart_facts(html)

        checklist_facts = self.checklist_extractor.extract_checklist_facts(page, visited_versions=visited_versions)
        if checklist_facts:
            existing_keys = {f.key for f in facts}
            for cf in checklist_facts:
                if cf.key not in existing_keys:
                    facts.append(cf)
                    existing_keys.add(cf.key)

        unique_facts = []
        seen_keys = set()
        for f in facts:
            if f.key not in seen_keys:
                unique_facts.append(f)
                seen_keys.add(f.key)
        facts = unique_facts

        release_changes = self.release_extractor.extract_release_changes(
            page, html, visited_versions=visited_versions
        )
        
        if self.jira_client and not skip_jira:
            self.jira_enricher.enrich_release_changes(release_changes)

        candidates = self.s2t_discovery.find_s2t_candidates(page, visited_versions=visited_versions)
        selected = self.s2t_discovery.choose_latest_s2t(candidates)

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
            visited_pages=visited_versions,
        )
