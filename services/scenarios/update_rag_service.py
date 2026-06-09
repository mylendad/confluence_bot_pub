import logging

from services.ingestion.changes.history_repository import HistoryRepository
from services.ingestion.confluence.client import ConfluenceClient
from services.ingestion.confluence.jira_client import JiraClient
from services.ingestion.confluence.parser import ConfluenceParser
from services.ingestion.sync.incremental_updater import IncrementalUpdater, IncrementalUpdateResult
from services.ingestion.sync.metadata_sync_service import MetadataSyncService
from services.rag.indexer import RAGIndexer
from services.rag.vector_store import JsonVectorStore
from shared.config.config import get_settings
from shared.storage.document_repository import DocumentRepository
from shared.storage.metadata_repository import MetadataRepository
from shared.storage.page_snapshot_repository import PageSnapshotRepository
from shared.storage.s2t_state_repository import S2TStateRepository
from shared.storage.sqlite import SQLite

logger = logging.getLogger(__name__)

class UpdateRagService:
    """
    Сервис сценария для инкрементального обновления базы знаний RAG.
    """
    def __init__(self):
        self.settings = get_settings()

    def run(self, since: str | None = None, dry_run: bool = False) -> IncrementalUpdateResult:
        """
        Выполняет инкрементальное обновление.
        :param since: Опциональный фильтр даты (сейчас не используется напрямую в updater).
        :param dry_run: Режим 'вхолостую' (без изменения данных).
        """
        db = SQLite(self.settings.sqlite_db_path)
        metadata_repo = MetadataRepository(db)
        history_repo = HistoryRepository(db)
        document_repo = DocumentRepository(db)
        state_repo = S2TStateRepository(db)
        snapshot_repo = PageSnapshotRepository(db)
        vector_store = JsonVectorStore(self.settings.vector_store_dir)
        indexer = RAGIndexer(metadata_repo, document_repo, vector_store)
        
        jira_client = None
        if self.settings.jira_auth_token or (
            self.settings.jira_username and (self.settings.jira_token or self.settings.jira_api_token)
        ):
            logger.info("Initializing JiraClient...")
            jira_client = JiraClient(self.settings)
        else:
            logger.warning("Jira credentials not found in settings! jira_auth_token and (jira_username + jira_token) are missing.")

        try:
            confluence_client = ConfluenceClient(self.settings)
            parser = ConfluenceParser(confluence_client, self.settings, jira_client=jira_client)
            
            updater = IncrementalUpdater(
                metadata_sync=MetadataSyncService(parser, snapshot_repo=snapshot_repo),
                confluence_client=confluence_client,
                state_repo=state_repo,
                metadata_repo=metadata_repo,
                history_repo=history_repo,
                indexer=indexer,
                data_dir=self.settings.data_dir,
            )
            
            logger.info(f"Начало {'test' if dry_run else 'incremental'} обновления RAG...")
            result = updater.run(dry_run=dry_run)
            logger.info("Обновление успешно завершено.")
            return result
        finally:
            if jira_client:
                jira_client.close()

