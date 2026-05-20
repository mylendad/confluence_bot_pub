import json
from pathlib import Path

from app.rag.embeddings import LocalTextEmbedder
from app.rag.models import RAGDocument, RetrievedDocument


class JsonVectorStore:
    def __init__(self, directory: Path, embedder: LocalTextEmbedder | None = None) -> None:
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "documents.jsonl"
        self.embedder = embedder or LocalTextEmbedder()

    def replace_all(self, documents: list[RAGDocument]) -> None:
        with self.path.open("w", encoding="utf-8") as file:
            for document in documents:
                file.write(document.model_dump_json() + "\n")

    def replace_for_datamart(self, datamart_name: str, documents: list[RAGDocument]) -> None:
        existing = self._read_documents()
        unchanged = [
            doc for doc in existing if doc.metadata.get("datamart_name") != datamart_name
        ]
        self.replace_all([*unchanged, *documents])

    def search(self, query: str, k: int = 5) -> list[RetrievedDocument]:
        results: list[RetrievedDocument] = []
        for doc in self._read_documents():
            score = self.embedder.similarity(query, doc.text)
            if score > 0:
                results.append(RetrievedDocument(document=doc, score=score))
        return sorted(results, key=lambda item: item.score, reverse=True)[:k]

    def _read_documents(self) -> list[RAGDocument]:
        if not self.path.exists():
            return []
        documents: list[RAGDocument] = []
        with self.path.open(encoding="utf-8") as file:
            for line in file:
                if line.strip():
                    documents.append(RAGDocument.model_validate(json.loads(line)))
        return documents
