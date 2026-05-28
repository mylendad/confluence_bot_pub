from pathlib import Path

from app.changes.history_repository import HistoryRepository
from app.confluence.models import Datamart, S2TResource
from app.rag.indexer import RAGIndexer
from app.rag.retriever import RAGRetriever
from app.rag.vector_store import JsonVectorStore
from app.storage.document_repository import DocumentRepository
from app.storage.metadata_repository import MetadataRepository
from app.storage.s2t_state_repository import S2TStateRepository
from app.storage.sqlite import SQLite
from app.sync.hash_service import HashService
from app.sync.incremental_updater import IncrementalUpdater
from app.sync.metadata_sync_service import S2TMetadataSnapshot


class FakeMetadataSync:
    def __init__(self, snapshots):
        self.snapshots = snapshots

    def collect(self):
        return self.snapshots


class FakeConfluenceClient:
    def __init__(self, content: bytes):
        self.content = content
        self.downloads = 0

    def download(self, url: str) -> bytes:
        self.downloads += 1
        return self.content


def _snapshot(version: int = 1) -> S2TMetadataSnapshot:
    datamart = Datamart(
        name="Витрина клиентов",
        confluence_page_id="42",
        confluence_url="https://conf/pages/42",
    )
    resource = S2TResource(
        id="100500",
        title="s2t.csv",
        file_name="s2t.csv",
        url="https://conf/download/s2t.csv",
        download_url="https://conf/download/s2t.csv",
        resource_type="attachment",
        version=version,
        page_id="42",
    )
    metadata = {
        "datamart_name": datamart.name,
        "attachment_id": resource.id,
        "attachment_title": resource.title,
        "attachment_version_number": resource.version,
        "download_url": resource.download_url,
        "resource_type": resource.resource_type,
    }
    return S2TMetadataSnapshot(
        datamart=datamart,
        resource=resource,
        metadata=metadata,
        metadata_hash=HashService.stable_metadata_hash(metadata),
    )


def _updater(tmp_path: Path, snapshots, client: FakeConfluenceClient) -> IncrementalUpdater:
    db = SQLite(tmp_path / "app.db")
    metadata_repo = MetadataRepository(db)
    vector_store = JsonVectorStore(tmp_path / "vector_store")
    indexer = RAGIndexer(metadata_repo, DocumentRepository(db), vector_store)
    return IncrementalUpdater(
        metadata_sync=FakeMetadataSync(snapshots),
        confluence_client=client,
        state_repo=S2TStateRepository(db),
        metadata_repo=metadata_repo,
        history_repo=HistoryRepository(db),
        indexer=indexer,
        data_dir=tmp_path / "data",
    )


def test_dry_run_reports_changes_without_download(tmp_path: Path) -> None:
    client = FakeConfluenceClient(b"")
    updater = _updater(tmp_path, [_snapshot()], client)

    result = updater.run(dry_run=True)

    assert result.items[0].will_download is True
    assert result.items[0].will_parse is True
    assert client.downloads == 0


def test_incremental_update_skips_unchanged_metadata(tmp_path: Path) -> None:
    content = (
        b"codeDatamart,target_table,target_field,UserName\n"
        b"DM_CLIENT,client_dm,epk_id,owner@example.ru\n"
    )
    snapshot = _snapshot()
    client = FakeConfluenceClient(content)
    updater = _updater(tmp_path, [snapshot], client)

    first = updater.run()
    second = updater.run()

    assert first.parsed_count == 1
    assert second.parsed_count == 0
    assert second.downloaded_count == 0
    assert client.downloads == 1


def test_changed_metadata_with_same_hash_skips_parse_and_reindex(tmp_path: Path) -> None:
    content = (
        b"codeDatamart,target_table,target_field,UserName\n"
        b"DM_CLIENT,client_dm,epk_id,owner@example.ru\n"
    )
    client = FakeConfluenceClient(content)
    updater = _updater(tmp_path, [_snapshot(version=1)], client)

    first = updater.run()
    updater.metadata_sync = FakeMetadataSync([_snapshot(version=2)])
    second = updater.run()

    assert first.parsed_count == 1
    assert second.downloaded_count == 1
    assert second.parsed_count == 0
    assert second.reindexed_count == 1
    assert second.items[0].content_changed is False
    assert client.downloads == 2


def test_incremental_update_added_s2t_field_is_reported_with_date(tmp_path: Path) -> None:
    base_content = (
        b"codeDatamart,target_table,target_field,UserName\n"
        b"DM_CLIENT,client_dm,epk_id,owner@example.ru\n"
    )
    updated_content = (
        b"codeDatamart,target_table,target_field,UserName\n"
        b"DM_CLIENT,client_dm,epk_id,owner@example.ru\n"
        b"DM_CLIENT,client_dm,new_client_status_cd,owner@example.ru\n"
    )
    client = FakeConfluenceClient(base_content)
    updater = _updater(tmp_path, [_snapshot(version=1)], client)

    first = updater.run()
    client.content = updated_content
    updater.metadata_sync = FakeMetadataSync([_snapshot(version=2)])
    second = updater.run()

    retriever = RAGRetriever(
        updater.metadata_repo,
        JsonVectorStore(tmp_path / "vector_store"),
        updater.history_repo,
    )
    # Используем вопрос, который не попадет в специфичные интенты и вызовет векторный поиск.
    # StubAnswerGenerator возвращает context, если он есть.
    answer = retriever.answer(
        "Расскажи про атрибут new_client_status_cd"
    )

    assert first.parsed_count == 1
    assert first.changes_count == 0
    assert second.parsed_count == 1
    assert second.changes_count == 1
    # StubAnswerGenerator возвращает контекст, в котором должен быть наш новый атрибут
    assert "new_client_status_cd" in answer.answer
