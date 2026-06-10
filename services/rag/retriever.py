from services.ingestion.changes.history_repository import HistoryRepository
from services.rag.dispatcher import IntentDispatcher
from services.rag.intent_classifier import IntentClassifier
from services.rag.llm import AnswerGenerator, StubAnswerGenerator
from services.rag.models import RAGAnswer
from services.rag.vector_store import JsonVectorStore
from shared.storage.metadata_repository import MetadataRepository


class RAGRetriever:
    """
    Основной класс для поиска информации и формирования ответов (RAG).
    Использует метаданные из БД, векторное хранилище и LLM.
    """

    def __init__(
        self,
        metadata_repo: MetadataRepository,
        vector_store: JsonVectorStore,
        history_repo: HistoryRepository,
        answer_generator: AnswerGenerator | None = None,
    ) -> None:
        self.metadata_repo = metadata_repo
        self.vector_store = vector_store
        self.history_repo = history_repo
        self.answer_generator = answer_generator or StubAnswerGenerator()
        self.intent_classifier = IntentClassifier()
        self.dispatcher = IntentDispatcher(
            metadata_repo=metadata_repo,
            vector_store=vector_store,
            history_repo=history_repo,
            answer_generator=self.answer_generator,
            intent_classifier=self.intent_classifier,
        )

    def answer(self, question: str) -> RAGAnswer:
        res = self.dispatcher.dispatch(question)
        if res:
            res.sources = self._deduplicate_sources(res.sources)
        return res

    def _deduplicate_sources(self, sources: list[dict]) -> list[dict]:
        """Удаляет дубликаты из списка источников."""
        if not sources:
            return []
        unique_sources = []
        seen = set()
        for s in sources:
            dm = s.get("datamart") or s.get("datamart_name")
            s2t = s.get("s2t_file") or s.get("s2t_file_name")
            date = s.get("s2t_file_date")
            url = s.get("confluence_url") or s.get("source_url")

            key = (dm, s2t, date, url)
            if key not in seen:
                seen.add(key)
                unique_sources.append(s)
        return unique_sources
