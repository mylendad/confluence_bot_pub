import logging
from dataclasses import dataclass
from datetime import UTC

from app.confluence.models import Datamart, S2TResource
from app.confluence.parser import ConfluenceParser
from app.sync.hash_service import HashService
from app.utils.hashing import stable_hash
from app.utils.text_utils import normalize_text
from app.storage.page_snapshot_repository import PageSnapshotRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class S2TMetadataSnapshot:
    datamart: Datamart
    resource: S2TResource
    metadata: dict
    metadata_hash: str
    
    @property
    def unique_key(self) -> str:
        # A datamart can link to an attachment on another page.
        # To avoid state collisions between datamarts sharing the same file,
        # we prefix the resource key with the datamart's own page ID.
        base_key = self.resource.id or self.resource.download_url or self.resource.url or self.resource.file_name
        return f"{self.datamart.confluence_page_id}:{base_key}"


class MetadataSyncService:
    def __init__(
        self, 
        parser: ConfluenceParser, 
        hash_service: HashService | None = None,
        snapshot_repo: PageSnapshotRepository | None = None
    ) -> None:
        self.parser = parser
        self.hash_service = hash_service or HashService()
        self.snapshot_repo = snapshot_repo
        self._prefetched_versions: dict[str, int] = {}

    def collect(self) -> list[S2TMetadataSnapshot]:
        snapshots: list[S2TMetadataSnapshot] = []
        pattern = normalize_text(self.parser.settings.datamart_page_pattern)
        
        # Pre-fetch top-level pages
        logger.info("Discovery: fetching top-level pages...")
        top_level_pages = list(self.parser.client.iter_top_level_pages())
        
        # Gather all required page IDs for bulk version check
        all_required_page_ids = set()
        if self.snapshot_repo:
            for page in top_level_pages:
                if pattern not in normalize_text(page.title):
                    continue
                snapshot = self.snapshot_repo.get(page.id)
                if snapshot:
                    version_map, _ = snapshot
                    all_required_page_ids.update(version_map.keys())

        # Bulk fetch metadata for all cached pages
        if all_required_page_ids:
            logger.info("Discovery: bulk fetching metadata for %d cached pages...", len(all_required_page_ids))
            bulk_meta = self.parser.client.get_pages_metadata_bulk(list(all_required_page_ids))
            for pid, meta_page in bulk_meta.items():
                if meta_page.version is not None:
                    self._prefetched_versions[pid] = meta_page.version

        for page in top_level_pages:
            if pattern not in normalize_text(page.title):
                continue
                
            logger.info("Discovery: processing datamart page '%s' (ID: %s)", page.title, page.id)
            
            datamart = self._get_datamart_with_cache(page)
            if not datamart or not datamart.s2t_resource:
                continue
                
            resource = datamart.s2t_resource
            metadata = self._metadata(datamart, resource)
            
            # Для хэша используем только те поля, которые влияют на контент в RAG.
            hash_metadata = {
                "datamart_name": metadata["datamart_name"],
                "datamart_page_id": metadata["datamart_page_id"],
                "attachment_id": metadata["attachment_id"],
                "attachment_version_number": metadata["attachment_version_number"],
                "release_changes_hash": metadata["release_changes_hash"],
                "stakeholders_hash": metadata["stakeholders_hash"],
                "facts_hash": metadata["facts_hash"],
            }
            
            snapshots.append(
                S2TMetadataSnapshot(
                    datamart=datamart,
                    resource=resource,
                    metadata=metadata,
                    metadata_hash=self.hash_service.stable_metadata_hash(hash_metadata),
                )
            )
        return snapshots

    def _get_datamart_with_cache(self, page) -> Datamart | None:
        if not self.snapshot_repo:
            return self.parser.parse_datamart_page(page, skip_jira=True)
            
        snapshot = self.snapshot_repo.get(page.id)
        if snapshot:
            version_map, cached_datamart = snapshot
            if self._verify_versions(version_map):
                logger.info("Using cached parsing result for datamart '%s'", page.title)
                return cached_datamart
            else:
                logger.info("Cache invalidated for datamart '%s' due to version changes", page.title)
        
        # Parse from scratch
        datamart = self.parser.parse_datamart_page(page, skip_jira=True)
        if datamart:
            self.snapshot_repo.upsert(page.id, datamart.visited_pages, datamart)
        return datamart

    def _verify_versions(self, version_map: dict[str, int]) -> bool:
        for page_id, expected_version in version_map.items():
            # First try prefetched bulk map
            if page_id in self._prefetched_versions:
                if self._prefetched_versions[page_id] != expected_version:
                    return False
                continue
                
            # Fallback to single fast request if not in prefetched map
            try:
                current_page = self.parser.client.get_page(page_id, expand="version,history.lastUpdated")
                if not current_page or current_page.version != expected_version:
                    return False
            except Exception:
                return False
        return True

    @staticmethod
    def _metadata(datamart: Datamart, resource: S2TResource) -> dict:
        def fmt_dt(dt) -> str | None:
            if not dt:
                return None
            # Normalize to UTC and remove microseconds for stable hashing
            if dt.tzinfo:
                dt = dt.astimezone(UTC)
            return dt.replace(microsecond=0).isoformat()

        # Для хэша изменений в релизах используем только стабильные данные из Confluence,
        # чтобы изменения в Jira (статус, даты) не триггерили полную переиндексацию RAG.
        stable_release_changes = [
            {
                "version": c.version,
                "jira_key": c.jira_key,
                "change_type": c.change_type,
                "summary": c.summary,
            }
            for c in datamart.release_changes
        ]

        return {
            "datamart_name": datamart.name,
            "datamart_page_id": datamart.confluence_page_id,
            "datamart_page_version": datamart.page_version,
            "datamart_page_version_when": fmt_dt(datamart.page_version_when),
            "datamart_page_last_modified": fmt_dt(datamart.page_last_modified),
            "datamart_page_history_last_updated": fmt_dt(datamart.page_history_last_updated),
            "attachment_id": resource.id,
            "attachment_title": resource.title,
            "attachment_version_number": resource.version,
            "attachment_version_when": fmt_dt(resource.version_when),
            "attachment_file_size": resource.file_size,
            "download_url": resource.download_url or resource.url,
            "media_type": resource.media_type,
            "resource_type": resource.resource_type,
            "resource_page_id": resource.page_id,
            "resource_updated_at": fmt_dt(resource.updated_at),
            "file_name": resource.file_name,
            "release_changes_hash": stable_hash(stable_release_changes),
            "stakeholders_hash": stable_hash([s.model_dump() for s in datamart.stakeholders]),
            "facts_hash": stable_hash([f.model_dump() for f in datamart.facts]),
        }
