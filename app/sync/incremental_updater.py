import logging
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from app.changes.diff_service import DiffService
from app.changes.history_repository import HistoryRepository
from app.confluence.client import ConfluenceClient
from app.confluence.exceptions import ConfluenceAuthError, ConfluenceError
from app.rag.indexer import RAGIndexer
from app.s2t.parser import S2TParser
from app.storage.metadata_repository import MetadataRepository
from app.storage.s2t_state_repository import S2TStateRepository
from app.sync.hash_service import HashService
from app.sync.metadata_sync_service import MetadataSyncService, S2TMetadataSnapshot
from app.sync.state_comparator import StateComparator

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IncrementalUpdateItem:
    datamart_name: str
    resource_key: str
    file_name: str | None
    metadata_changed: bool
    reasons: list[str]
    will_download: bool
    will_parse: bool
    will_reindex: bool
    content_changed: bool | None = None
    content_hash: str | None = None
    changes_detected: int = 0


@dataclass(frozen=True)
class IncrementalUpdateResult:
    items: list[IncrementalUpdateItem] = field(default_factory=list)

    @property
    def downloaded_count(self) -> int:
        return sum(1 for item in self.items if item.will_download)

    @property
    def parsed_count(self) -> int:
        return sum(1 for item in self.items if item.will_parse)

    @property
    def reindexed_count(self) -> int:
        return sum(1 for item in self.items if item.will_reindex)

    @property
    def changes_count(self) -> int:
        return sum(item.changes_detected for item in self.items)


class IncrementalUpdater:
    def __init__(
        self,
        *,
        metadata_sync: MetadataSyncService,
        confluence_client: ConfluenceClient,
        state_repo: S2TStateRepository,
        metadata_repo: MetadataRepository,
        history_repo: HistoryRepository,
        indexer: RAGIndexer,
        data_dir: Path,
        hash_service: HashService | None = None,
        comparator: StateComparator | None = None,
        s2t_parser: S2TParser | None = None,
        diff_service: DiffService | None = None,
    ) -> None:
        self.metadata_sync = metadata_sync
        self.confluence_client = confluence_client
        self.state_repo = state_repo
        self.metadata_repo = metadata_repo
        self.history_repo = history_repo
        self.indexer = indexer
        self.data_dir = data_dir
        self.hash_service = hash_service or HashService()
        self.comparator = comparator or StateComparator()
        self.s2t_parser = s2t_parser or S2TParser()
        self.diff_service = diff_service or DiffService()

    def run(self, dry_run: bool = False) -> IncrementalUpdateResult:
        items: list[IncrementalUpdateItem] = []
        for snapshot in self.metadata_sync.collect():
            try:
                item = self._process_snapshot(snapshot, dry_run=dry_run)
                items.append(item)
            except (ConfluenceError, ConfluenceAuthError) as exc:
                logger.error(
                    "Failed to process datamart %s: %s", snapshot.datamart.name, exc
                )
                items.append(
                    IncrementalUpdateItem(
                        datamart_name=snapshot.datamart.name,
                        resource_key=snapshot.resource.resource_key,
                        file_name=snapshot.resource.file_name,
                        metadata_changed=True,
                        reasons=[f"Processing failed: {exc}"],
                        will_download=False,
                        will_parse=False,
                        will_reindex=False,
                    )
                )
        return IncrementalUpdateResult(items=items)

    def _process_snapshot(
        self, snapshot: S2TMetadataSnapshot, dry_run: bool
    ) -> IncrementalUpdateItem:
        resource = snapshot.resource
        resource_key = resource.resource_key
        previous = self.state_repo.get(resource_key)
        decision = self.comparator.compare(previous, snapshot.metadata_hash, snapshot.metadata)
        file_name = resource.file_name or resource.title

        if not decision.changed:
            if not dry_run:
                self.state_repo.upsert(
                    resource_key=resource_key,
                    datamart_name=snapshot.datamart.name,
                    page_id=resource.page_id,
                    resource_type=resource.resource_type,
                    title=resource.title,
                    file_name=file_name,
                    url=resource.download_url or resource.url,
                    metadata=snapshot.metadata,
                    metadata_hash=snapshot.metadata_hash,
                    content_hash=previous.content_hash if previous else None,
                    synced=False,
                    updated_at=resource.updated_at,
                )
            return IncrementalUpdateItem(
                datamart_name=snapshot.datamart.name,
                resource_key=resource_key,
                file_name=file_name,
                metadata_changed=False,
                reasons=decision.reasons,
                will_download=False,
                will_parse=False,
                will_reindex=False,
            )

        if dry_run:
            return IncrementalUpdateItem(
                datamart_name=snapshot.datamart.name,
                resource_key=resource_key,
                file_name=file_name,
                metadata_changed=True,
                reasons=decision.reasons,
                will_download=True,
                will_parse=True,
                will_reindex=True,
            )

        url = resource.download_url or resource.url
        if not url:
            return IncrementalUpdateItem(
                datamart_name=snapshot.datamart.name,
                resource_key=resource_key,
                file_name=file_name,
                metadata_changed=True,
                reasons=[*decision.reasons, "download url is absent"],
                will_download=False,
                will_parse=False,
                will_reindex=False,
            )

        if hasattr(self.confluence_client, "download_resource"):
            content = self.confluence_client.download_resource(resource)
        else:
            content = self.confluence_client.download(url)
        content_hash = self.hash_service.sha256_bytes(content)
        previous_content_hash = previous.content_hash if previous else None
        content_changed = content_hash != previous_content_hash
        if not content_changed:
            self.state_repo.upsert(
                resource_key=resource_key,
                datamart_name=snapshot.datamart.name,
                page_id=resource.page_id,
                resource_type=resource.resource_type,
                title=resource.title,
                file_name=file_name,
                url=url,
                metadata=snapshot.metadata,
                metadata_hash=snapshot.metadata_hash,
                content_hash=content_hash,
                synced=True,
                updated_at=resource.updated_at,
            )
            return IncrementalUpdateItem(
                datamart_name=snapshot.datamart.name,
                resource_key=resource_key,
                file_name=file_name,
                metadata_changed=True,
                reasons=[*decision.reasons, "content hash unchanged"],
                will_download=True,
                will_parse=False,
                will_reindex=False,
                content_changed=False,
                content_hash=content_hash,
            )

        path = self._write_raw_file(resource_key, file_name, content)
        old_attrs = self.metadata_repo.list_attributes(datamart_name=snapshot.datamart.name)
        parsed = self.s2t_parser.parse(path, snapshot.datamart.name, resource.file_date)
        new_attrs = parsed.attributes
        changes = (
            []
            if previous is None and not old_attrs
            else self.diff_service.diff_attributes(old_attrs, new_attrs, source_url=url)
        )
        self.history_repo.add_many(changes)
        documents = self.indexer.update_datamart(snapshot.datamart, new_attrs)
        self.state_repo.upsert(
            resource_key=resource_key,
            datamart_name=snapshot.datamart.name,
            page_id=resource.page_id,
            resource_type=resource.resource_type,
            title=resource.title,
            file_name=file_name,
            url=url,
            metadata=snapshot.metadata,
            metadata_hash=snapshot.metadata_hash,
            content_hash=content_hash,
            synced=True,
            updated_at=resource.updated_at,
        )
        return IncrementalUpdateItem(
            datamart_name=snapshot.datamart.name,
            resource_key=resource_key,
            file_name=file_name,
            metadata_changed=True,
            reasons=decision.reasons,
            will_download=True,
            will_parse=True,
            will_reindex=bool(documents),
            content_changed=True,
            content_hash=content_hash,
            changes_detected=len(changes),
        )

    def _write_raw_file(self, resource_key: str, file_name: str | None, content: bytes) -> Path:
        raw_dir = self.data_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        safe_name = self._safe_file_name(file_name or resource_key)
        key_hash = self.hash_service.stable_metadata_hash({"key": resource_key})[:12]
        path = raw_dir / f"{key_hash}_{safe_name}"
        path.write_bytes(content)
        return path

    @staticmethod
    def _safe_file_name(value: str) -> str:
        parsed_name = Path(urlparse(value).path).name or "s2t.bin"
        return "".join(char if char.isalnum() or char in "._-" else "_" for char in parsed_name)
