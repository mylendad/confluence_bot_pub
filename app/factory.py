from app.changes.history_repository import HistoryRepository
from app.config import Settings, get_settings
from app.rag.llm import build_answer_generator
from app.rag.retriever import RAGRetriever
from app.rag.vector_store import JsonVectorStore
from app.storage.metadata_repository import MetadataRepository
from app.storage.sqlite import SQLite


def build_retriever(settings: Settings | None = None) -> RAGRetriever:
    settings = settings or get_settings()
    db = SQLite(settings.sqlite_db_path)
    metadata_repo = MetadataRepository(db)
    history_repo = HistoryRepository(db)
    vector_store = JsonVectorStore(settings.vector_store_dir)
    answer_generator = build_answer_generator(settings)
    return RAGRetriever(metadata_repo, vector_store, history_repo, answer_generator)
