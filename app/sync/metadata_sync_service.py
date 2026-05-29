from dataclasses import dataclass
from datetime import UTC

from app.confluence.models import Datamart, S2TResource
from app.confluence.parser import ConfluenceParser
from app.sync.hash_service import HashService
from app.utils.hashing import stable_hash


@dataclass(frozen=True)
class S2TMetadataSnapshot:
    datamart: Datamart
    resource: S2TResource
    metadata: dict
    metadata_hash: str


class MetadataSyncService:
    def __init__(self, parser: ConfluenceParser, hash_service: HashService | None = None) -> None:
        self.parser = parser
        self.hash_service = hash_service or HashService()

    def collect(self) -> list[S2TMetadataSnapshot]:
        result = self.parser.parse(dry_run=True)
        snapshots: list[S2TMetadataSnapshot] = []
        for datamart in result.datamarts:
            if not datamart.s2t_resource:
                continue
            resource = datamart.s2t_resource
            metadata = self._metadata(datamart, resource)
            snapshots.append(
                S2TMetadataSnapshot(
                    datamart=datamart,
                    resource=resource,
                    metadata=metadata,
                    metadata_hash=self.hash_service.stable_metadata_hash(metadata),
                )
            )
        return snapshots

    @staticmethod
    def _metadata(datamart: Datamart, resource: S2TResource) -> dict:
        def fmt_dt(dt) -> str | None:
            if not dt:
                return None
            # Normalize to UTC and remove microseconds for stable hashing
            if dt.tzinfo:
                dt = dt.astimezone(UTC)
            return dt.replace(microsecond=0).isoformat()

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
            "release_changes_hash": stable_hash([c.model_dump(mode='json') for c in datamart.release_changes]),
        }
