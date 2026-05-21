from datetime import datetime, timedelta
from pathlib import Path

from app.changes.history_repository import HistoryRepository
from app.changes.models import ChangeLogEntry
from app.confluence.models import Datamart, DatamartFact, ReleaseChange
from app.rag.llm import AnswerGenerator
from app.rag.retriever import RAGRetriever
from app.rag.vector_store import JsonVectorStore
from app.s2t.models import S2TAttribute
from app.storage.metadata_repository import MetadataRepository
from app.storage.sqlite import SQLite


class FailingAnswerGenerator(AnswerGenerator):
    def generate(self, question: str, context: str) -> str:
        raise ConnectionError("LLM is unavailable")


def test_attribute_usage_structured_answer(tmp_path: Path) -> None:
    db = SQLite(tmp_path / "app.db")
    metadata_repo = MetadataRepository(db)
    metadata_repo.upsert_attributes(
        [
            S2TAttribute(
                datamart_name="Витрина клиентов",
                target_table="client_dm",
                target_field="epk_id",
                source_table="client_src",
                source_field="epk_id",
            )
        ]
    )
    retriever = RAGRetriever(metadata_repo, JsonVectorStore(tmp_path / "vs"), HistoryRepository(db))

    answer = retriever.answer("В каких витринах есть атрибут epk_id?")

    assert "Витрина клиентов" in answer.answer


def test_owner_lookup_uses_structured_s2t_owner(tmp_path: Path) -> None:
    db = SQLite(tmp_path / "app.db")
    metadata_repo = MetadataRepository(db)
    metadata_repo.upsert_attributes(
        [
            S2TAttribute(
                datamart_name="Витрина клиентских операций",
                target_schema="dds_dm",
                target_table="dm_client_operations",
                target_field="epk_id",
                owner="ivanov.ii@example.ru",
            )
        ]
    )
    retriever = RAGRetriever(metadata_repo, JsonVectorStore(tmp_path / "vs"), HistoryRepository(db))

    answer = retriever.answer("кто владелец Витрина клиентских операций")

    assert "ivanov.ii@example.ru" in answer.answer
    assert "Ответственные из S2T" in answer.answer


def test_owner_lookup_does_not_answer_for_unknown_datamart(tmp_path: Path) -> None:
    db = SQLite(tmp_path / "app.db")
    metadata_repo = MetadataRepository(db)
    metadata_repo.upsert_attributes(
        [
            S2TAttribute(
                datamart_name="Витрина клиентских операций",
                target_field="epk_id",
                owner="ivanov.ii@example.ru",
            )
        ]
    )
    retriever = RAGRetriever(metadata_repo, JsonVectorStore(tmp_path / "vs"), HistoryRepository(db))

    answer = retriever.answer("кто владелец Витрина счетов")

    assert "Данных по витрине `Витрина счетов` нет" in answer.answer
    assert "ivanov.ii@example.ru" not in answer.answer


def test_datamart_list_question_uses_metadata_store(tmp_path: Path) -> None:
    db = SQLite(tmp_path / "app.db")
    metadata_repo = MetadataRepository(db)
    metadata_repo.upsert_datamart(
        Datamart(
            name="Витрина Маркеры",
            confluence_page_id="42",
            confluence_url="https://confluence.example.ru/pages/42",
        )
    )
    retriever = RAGRetriever(metadata_repo, JsonVectorStore(tmp_path / "vs"), HistoryRepository(db))

    answer = retriever.answer("какие есть витрины")

    assert "Доступные витрины" in answer.answer
    assert "Витрина Маркеры" in answer.answer


def test_datamart_fact_question_uses_main_page_table(tmp_path: Path) -> None:
    db = SQLite(tmp_path / "app.db")
    metadata_repo = MetadataRepository(db)
    metadata_repo.upsert_datamart(
        Datamart(
            name="Витрина Маркеры",
            confluence_page_id="42",
            confluence_url="https://confluence.example.ru/pages/42",
            facts=[
                DatamartFact(key="ke", label="КЭ", value="КЭ-123"),
                DatamartFact(key="db_name", label="Имя витрины в БД", value="dm_markers"),
            ],
        )
    )
    retriever = RAGRetriever(metadata_repo, JsonVectorStore(tmp_path / "vs"), HistoryRepository(db))

    answer = retriever.answer("КЭ по витрине Витрина Маркеры")

    assert "КЭ-123" in answer.answer
    assert "dm_markers" not in answer.answer


def test_release_changes_question_uses_confluence_release_page(tmp_path: Path) -> None:
    db = SQLite(tmp_path / "app.db")
    metadata_repo = MetadataRepository(db)
    metadata_repo.upsert_datamart(
        Datamart(
            name="Витрина Маркеры",
            confluence_page_id="42",
            confluence_url="https://confluence.example.ru/pages/42",
            release_changes=[
                ReleaseChange(
                    version="Версия 20260327",
                    jira_key="SSDWH-3208",
                    jira_title="Снятие тега SCH",
                    change_type="изменение",
                    summary="Снятия тэга SCH для конкретного ЕПК",
                    status="ЗАКРЫТ",
                    source_url="https://confluence.example.ru/pages/99",
                )
            ],
        )
    )
    retriever = RAGRetriever(metadata_repo, JsonVectorStore(tmp_path / "vs"), HistoryRepository(db))

    answer = retriever.answer("Изменения в релизах по витрине Витрина Маркеры")

    assert "Версия 20260327" in answer.answer
    assert "SSDWH-3208" in answer.answer
    assert "Снятия тэга SCH" in answer.answer
    assert "ЗАКРЫТ" in answer.answer


def test_last_year_changes_answer_includes_dates_and_added_fields(tmp_path: Path) -> None:
    db = SQLite(tmp_path / "app.db")
    metadata_repo = MetadataRepository(db)
    history_repo = HistoryRepository(db)
    change_date = datetime.utcnow() - timedelta(days=3)
    history_repo.add_many(
        [
            ChangeLogEntry(
                id="change-1",
                datamart_name="Витрина клиентских операций",
                datamart_code="DM_CLIENT_OPS",
                entity_type="attribute",
                entity_name="new_client_status_cd",
                change_type="added",
                change_date=change_date,
                detected_at=change_date,
                s2t_file_name="s2t.xlsx",
            )
        ]
    )
    retriever = RAGRetriever(metadata_repo, JsonVectorStore(tmp_path / "vs"), history_repo)

    answer = retriever.answer(
        "Какие изменения за последний год по витрине Витрина клиентских операций с датами?"
    )

    assert "Изменения за период" in answer.answer
    assert str(change_date.date()) in answer.answer
    assert "Добавлены атрибуты" in answer.answer
    assert "new_client_status_cd" in answer.answer


def test_current_year_changes_uses_january_first_period(tmp_path: Path) -> None:
    db = SQLite(tmp_path / "app.db")
    metadata_repo = MetadataRepository(db)
    history_repo = HistoryRepository(db)
    now = datetime.utcnow()
    change_date = datetime(now.year, 2, 10)
    history_repo.add_many(
        [
            ChangeLogEntry(
                id="change-current-year",
                datamart_name="Витрина клиентских операций",
                datamart_code="DM_CLIENT_OPS",
                entity_type="attribute",
                entity_name="new_client_status_cd",
                change_type="added",
                change_date=change_date,
                detected_at=change_date,
                s2t_file_name="s2t.xlsx",
            )
        ]
    )
    retriever = RAGRetriever(metadata_repo, JsonVectorStore(tmp_path / "vs"), history_repo)

    answer = retriever.answer(
        "какие изменения за текущий год для витрины Витрина клиентских операций"
    )

    assert f"Изменения за период {now.year}-01-01" in answer.answer
    assert "Добавлены атрибуты" in answer.answer
    assert "new_client_status_cd" in answer.answer


def test_source_lineage_skips_missing_schema(tmp_path: Path) -> None:
    db = SQLite(tmp_path / "app.db")
    metadata_repo = MetadataRepository(db)
    metadata_repo.upsert_attributes(
        [
            S2TAttribute(
                datamart_name="Витрина счетов",
                target_table="dm_account_balance",
                target_field="account_balance_amt",
                source_table="account_balance",
                source_field="balance_amt",
            )
        ]
    )
    retriever = RAGRetriever(metadata_repo, JsonVectorStore(tmp_path / "vs"), HistoryRepository(db))

    answer = retriever.answer("Из какого источника берется account_balance_amt?")

    assert "dm_account_balance.account_balance_amt <- account_balance.balance_amt" in answer.answer
    assert "None" not in answer.answer


def test_vector_answer_returns_friendly_llm_error(tmp_path: Path) -> None:
    db = SQLite(tmp_path / "app.db")
    metadata_repo = MetadataRepository(db)
    metadata_repo.upsert_attributes(
        [
            S2TAttribute(
                datamart_name="Витрина счетов",
                target_table="dm_account_balance",
                target_field="account_balance_amt",
                source_table="account_balance",
                source_field="balance_amt",
                transformation_logic="round(account_balance.balance_amt, 2)",
            )
        ]
    )
    vector_store = JsonVectorStore(tmp_path / "vs")
    from app.rag.indexer import RAGIndexer
    from app.storage.document_repository import DocumentRepository

    RAGIndexer(metadata_repo, DocumentRepository(db), vector_store).rebuild_from_storage()
    retriever = RAGRetriever(
        metadata_repo,
        vector_store,
        HistoryRepository(db),
        FailingAnswerGenerator(),
    )

    answer = retriever.answer("Объясни витрину счетов")

    assert "Не удалось вызвать LLM" in answer.answer
    assert answer.sources
