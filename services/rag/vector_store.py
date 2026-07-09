import json
import logging
from pathlib import Path
from typing import Protocol, runtime_checkable

from services.rag.models import RAGDocument, RetrievedDocument

logger = logging.getLogger(__name__)


@runtime_checkable
class VectorStore(Protocol):
    """Интерфейс для векторного хранилища документов."""

    def replace_all(self, documents: list[RAGDocument]) -> None:
        """Полностью заменяет все документы в хранилище."""
        ...

    def replace_for_datamart(self, datamart_name: str, documents: list[RAGDocument]) -> None:
        """Заменяет документы только для указанной витрины."""
        ...

    def search(self, query: str, k: int = 5) -> list[RetrievedDocument]:
        """Выполняет поиск наиболее похожих документов по запросу."""
        ...


class JsonVectorStore:
    """
    Локальное хранилище документов на базе JSONL-файла.
    Поиск выполняется через on-the-fly косинусное сходство (legacy fallback).
    Используйте ChromaVectorStore для production с реальными эмбеддингами.
    """

    def __init__(self, directory: Path, embedder=None) -> None:
        """
        Инициализирует JsonVectorStore.
        :param directory: Директория для хранения файла индекса.
        :param embedder: Объект для вычисления эмбеддингов текстов.
        """
        from services.rag.embeddings import LocalTextEmbedder

        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "documents.jsonl"
        self.embedder = embedder or LocalTextEmbedder()

    def replace_all(self, documents: list[RAGDocument]) -> None:
        """
        Полностью заменяет все документы в хранилище.
        :param documents: Список новых документов для сохранения.
        """
        with self.path.open("w", encoding="utf-8") as file:
            for document in documents:
                file.write(document.model_dump_json() + "\n")

    def replace_for_datamart(self, datamart_name: str, documents: list[RAGDocument]) -> None:
        """
        Заменяет документы только для указанной витрины.
        :param datamart_name: Название витрины.
        :param documents: Новые документы для данной витрины.
        """
        existing = self._read_documents()
        unchanged = [doc for doc in existing if doc.metadata.get("datamart_name") != datamart_name]
        self.replace_all([*unchanged, *documents])

    def search(self, query: str, k: int = 5) -> list[RetrievedDocument]:
        """
        Выполняет поиск наиболее похожих документов по запросу.
        :param query: Текст запроса.
        :param k: Количество возвращаемых результатов.
        """
        results: list[RetrievedDocument] = []
        for doc in self._read_documents():
            score = self.embedder.similarity(query, doc.text)
            if score > 0:
                results.append(RetrievedDocument(document=doc, score=score))
        return sorted(results, key=lambda item: item.score, reverse=True)[:k]

    def _read_documents(self) -> list[RAGDocument]:
        """Читает все документы из JSONL-файла."""
        if not self.path.exists():
            return []
        documents: list[RAGDocument] = []
        with self.path.open(encoding="utf-8") as file:
            for line in file:
                if line.strip():
                    documents.append(RAGDocument.model_validate(json.loads(line)))
        return documents


class ChromaVectorStore:
    """
    Векторное хранилище на базе ChromaDB с реальными sentence-transformer эмбеддингами.
    Хранит векторы персистентно на диске, поддерживает инкрементальное обновление через upsert.
    """

    COLLECTION_NAME = "rag_documents"

    def __init__(self, directory: Path, embedder=None) -> None:
        """
        Инициализирует ChromaVectorStore.
        :param directory: Директория для персистентного хранения ChromaDB.
        :param embedder: Экземпляр SentenceTransformerEmbedder.
        """
        try:
            import chromadb
        except ImportError as exc:
            raise ImportError(
                "chromadb не установлен. Установите: pip install -e '.[rag]'"
            ) from exc

        from services.rag.embeddings import SentenceTransformerEmbedder

        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.embedder: SentenceTransformerEmbedder = embedder or SentenceTransformerEmbedder()

        self._client = chromadb.PersistentClient(path=str(directory))
        self._collection = self._client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            "ChromaVectorStore инициализирован: %s (документов: %d)",
            directory,
            self._collection.count(),
        )

    def replace_all(self, documents: list[RAGDocument]) -> None:
        """
        Полностью заменяет все документы: удаляет коллекцию и создаёт заново.
        :param documents: Список новых документов.
        """
        try:
            import chromadb

            self._client.delete_collection(self.COLLECTION_NAME)
        except Exception:
            pass
        self._collection = self._client.get_or_create_collection(
            name=self.COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )
        if not documents:
            return
        self._upsert_batch(documents)
        logger.info("ChromaVectorStore: загружено %d документов.", len(documents))

    def replace_for_datamart(self, datamart_name: str, documents: list[RAGDocument]) -> None:
        """
        Удаляет старые документы витрины и добавляет новые через upsert.
        :param datamart_name: Название витрины.
        :param documents: Новые документы для данной витрины.
        """
        # Удаляем старые документы этой витрины
        try:
            self._collection.delete(where={"datamart_name": datamart_name})
        except Exception as exc:
            logger.debug("Не удалось удалить старые документы для %s: %s", datamart_name, exc)

        if documents:
            self._upsert_batch(documents)
        logger.info(
            "ChromaVectorStore: обновлено %d документов для витрины '%s'.",
            len(documents),
            datamart_name,
        )

    def search(self, query: str, k: int = 5) -> list[RetrievedDocument]:
        """
        Выполняет семантический поиск по вектору запроса.
        :param query: Текст запроса.
        :param k: Количество возвращаемых результатов.
        """
        if self._collection.count() == 0:
            return []

        query_embedding = self.embedder.embed(query)
        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=min(k, self._collection.count()),
            include=["documents", "metadatas", "distances"],
        )

        retrieved: list[RetrievedDocument] = []
        ids = results.get("ids", [[]])[0]
        texts = results.get("documents", [[]])[0]
        metadatas = results.get("metadatas", [[]])[0]
        distances = results.get("distances", [[]])[0]

        for doc_id, text, metadata, distance in zip(ids, texts, metadatas, distances):
            # ChromaDB cosine distance: 0 = identical, 2 = opposite
            # Конвертируем в similarity: 1 - distance/2 → [0, 1]
            score = 1.0 - distance / 2.0
            doc = RAGDocument(id=doc_id, text=text, metadata=metadata or {})
            retrieved.append(RetrievedDocument(document=doc, score=score))

        return retrieved

    def _upsert_batch(self, documents: list[RAGDocument], batch_size: int = 100) -> None:
        """
        Добавляет/обновляет документы в коллекции пакетами.
        :param documents: Список документов.
        :param batch_size: Размер пакета для батч-вставки.
        """
        for i in range(0, len(documents), batch_size):
            batch = documents[i : i + batch_size]
            texts = [doc.text for doc in batch]
            embeddings = self.embedder.embed_batch(texts)
            # ChromaDB требует строковые значения в метаданных
            sanitized_metadatas = [_sanitize_metadata(doc.metadata) for doc in batch]
            self._collection.upsert(
                ids=[doc.id for doc in batch],
                embeddings=embeddings,
                documents=texts,
                metadatas=sanitized_metadatas,
            )
            logger.debug("Загружен пакет %d/%d документов.", min(i + batch_size, len(documents)), len(documents))


def _sanitize_metadata(metadata: dict) -> dict:
    """
    Приводит метаданные к формату, совместимому с ChromaDB.
    ChromaDB принимает только str, int, float, bool — None и списки не поддерживаются.
    :param metadata: Исходные метаданные.
    :return: Очищенные метаданные.
    """
    result: dict = {}
    for key, value in metadata.items():
        if value is None:
            result[key] = ""
        elif isinstance(value, (str, int, float, bool)):
            result[key] = value
        elif isinstance(value, list):
            # Список сериализуем в JSON-строку
            result[key] = json.dumps(value, ensure_ascii=False)
        else:
            result[key] = str(value)
    return result
