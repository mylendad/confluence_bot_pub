from services.ingestion.changes.history_repository import HistoryRepository
from shared.config.config import Settings, get_settings
from services.ingestion.confluence.client import ConfluenceClient
from services.rag.llm import AnswerGenerator, build_answer_generator
from services.rag.retriever import RAGRetriever
from services.rag.vector_store import JsonVectorStore
from shared.storage.chat_history_repository import ChatHistoryRepository
from shared.storage.metadata_repository import MetadataRepository
from shared.storage.s2t_state_repository import S2TStateRepository
from shared.storage.sqlite import SQLite


def build_retriever(settings: Settings | None = None) -> RAGRetriever:
    settings = settings or get_settings()
    db = SQLite(settings.sqlite_db_path)
    metadata_repo = MetadataRepository(db)
    history_repo = HistoryRepository(db)
    vector_store = JsonVectorStore(settings.vector_store_dir)
    answer_generator = build_answer_generator(settings)
    return RAGRetriever(metadata_repo, vector_store, history_repo, answer_generator)


def build_state_repository(settings: Settings | None = None) -> S2TStateRepository:
    settings = settings or get_settings()
    db = SQLite(settings.sqlite_db_path)
    return S2TStateRepository(db)


def build_metadata_repository(settings: Settings | None = None) -> MetadataRepository:
    settings = settings or get_settings()
    db = SQLite(settings.sqlite_db_path)
    return MetadataRepository(db)


def build_chat_history_repository(settings: Settings | None = None) -> ChatHistoryRepository:
    settings = settings or get_settings()
    db = SQLite(settings.sqlite_db_path)
    return ChatHistoryRepository(db)


def build_confluence_client(settings: Settings | None = None) -> ConfluenceClient:
    settings = settings or get_settings()
    return ConfluenceClient(settings)


def build_llm_generator(settings: Settings | None = None) -> AnswerGenerator:
    settings = settings or get_settings()
    return build_answer_generator(settings)


def build_jira_client(settings: Settings | None = None):
    from services.ingestion.confluence.jira_client import JiraClient
    settings = settings or get_settings()
    return JiraClient(settings)
