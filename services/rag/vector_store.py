import json
from pathlib import Path

from services.rag.embeddings import LocalTextEmbedder
from services.rag.models import RAGDocument, RetrievedDocument


class JsonVectorStore:
    """
    Локальное векторное хранилище на базе JSONL-файла.
    Обеспечивает сохранение документов и поиск по сходству через эмбеддинги.
    """

    def __init__(self, directory: Path, embedder: LocalTextEmbedder | None = None) -> None:
        """
        Инициализирует JsonVectorStore.
        :param directory: Директория для хранения файла индекса.
        :param embedder: Объект для вычисления эмбеддингов текстов.
        """
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "documents.jsonl"
        self.embedder = embedder or LocalTextEmbedder()

    def replace_all(self, documents: list[RAGDocument]) -> None:
        """
        Полностью заменяет все документы в хранилище атомарно.
        :param documents: Список новых документов для сохранения.
        """
        temp_path = self.path.with_suffix(".jsonl.tmp")
        try:
            with temp_path.open("w", encoding="utf-8") as file:
                for document in documents:
                    file.write(document.model_dump_json() + "\n")
            temp_path.replace(self.path)
        except Exception:
            if temp_path.exists():
                temp_path.unlink()
            raise

    def replace_for_datamart(self, datamart_name: str, documents: list[RAGDocument]) -> None:
        """
        Заменяет документы только для указанной витрины атомарно.
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
