
from pathlib import Path
from app.storage.sqlite import SQLite
from app.storage.metadata_repository import MetadataRepository
from app.confluence.models import Datamart, DatamartFact
from app.rag.retriever import RAGRetriever
from app.rag.vector_store import JsonVectorStore
from app.changes.history_repository import HistoryRepository

def test_datamart_fact_with_mismatched_datamart(tmp_path: Path) -> None:
    db = SQLite(tmp_path / "app.db")
    metadata_repo = MetadataRepository(db)
    metadata_repo.upsert_datamart(
        Datamart(
            name="Витрина Маркеры",
            confluence_page_id="42",
            confluence_url="http://example.com/42",
            facts=[
                DatamartFact(key="business_stakeholders", label="Заинтересованные со стороны бизнеса", value="Иванов")
            ]
        )
    )
    metadata_repo.upsert_datamart(
        Datamart(
            name="Витрина Депозиты",
            confluence_page_id="43",
            confluence_url="http://example.com/43",
            facts=[
                DatamartFact(key="business_stakeholders", label="Заинтересованные со стороны бизнеса", value="Петров")
            ]
        )
    )
    retriever = RAGRetriever(metadata_repo, JsonVectorStore(tmp_path / "vs"), HistoryRepository(db))

    # "Витрина Несуществующая" will likely not match any existing datamart name.
    # But it contains "Заинтересованные со стороны бизнеса", which triggers datamart_fact.
    answer = retriever.answer("Витрина Несуществующая Заинтересованные со стороны бизнеса")

    print(f"Answer: {answer.answer}")
    
    # Check if it leaked other datamarts
    assert "Витрина Маркеры" not in answer.answer
    assert "Витрина Депозиты" not in answer.answer
    assert "Данных по этому вопросу на главной странице витрины не найдено" in answer.answer

if __name__ == "__main__":
    import pytest
    pytest.main([__file__])
