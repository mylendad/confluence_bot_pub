from app.changes.history_repository import HistoryRepository
from app.config import Settings, get_settings
from app.confluence.client import ConfluenceClient
from app.rag.llm import AnswerGenerator, build_answer_generator
from app.rag.retriever import RAGRetriever
from app.rag.vector_store import JsonVectorStore
from app.storage.chat_history_repository import ChatHistoryRepository
from app.storage.metadata_repository import MetadataRepository
from app.storage.s2t_state_repository import S2TStateRepository
from app.storage.sqlite import SQLite


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
