from datetime import datetime, timedelta
from pathlib import Path

import httpx
import pandas.errors
import typer

from app.bot.cli_adapter import CLIAdapter
from app.bot.service import BotService
from app.changes.diff_service import DiffService
from app.changes.history_repository import HistoryRepository
from app.config import get_settings
from app.confluence.client import ConfluenceClient
from app.confluence.exceptions import ConfluenceAuthError, ConfluenceError
from app.confluence.jira_client import JiraClient
from app.confluence.models import Datamart
from app.confluence.parser import ConfluenceParser
from app.factory import build_retriever
from app.logging_config import configure_logging
from app.rag.indexer import RAGIndexer
from app.rag.vector_store import JsonVectorStore
from app.s2t.exceptions import S2TParseError
from app.s2t.parser import S2TParser
from app.storage.document_repository import DocumentRepository
from app.storage.metadata_repository import MetadataRepository
from app.storage.s2t_state_repository import S2TStateRepository
from app.storage.sqlite import SQLite
from app.sync.incremental_updater import IncrementalUpdater, IncrementalUpdateResult
from app.sync.metadata_sync_service import MetadataSyncService

app = typer.Typer(no_args_is_help=True)


def _repos():
    settings = get_settings()
    configure_logging(settings.log_level)
    db = SQLite(settings.sqlite_db_path)
    metadata_repo = MetadataRepository(db)
    document_repo = DocumentRepository(db)
    history_repo = HistoryRepository(db)
    vector_store = JsonVectorStore(settings.vector_store_dir)
    indexer = RAGIndexer(metadata_repo, document_repo, vector_store)
    return settings, metadata_repo, history_repo, indexer


@app.command("parse-confluence")
def parse_confluence(dry_run: bool = typer.Option(False, "--dry-run")) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    jira_client = None
    # Fix: Also check for jira_auth_token
    if settings.jira_auth_token or (settings.jira_username and (settings.jira_token or settings.jira_api_token)):
        import logging
        logging.getLogger(__name__).info("Initializing JiraClient...")
        jira_client = JiraClient(settings)
    else:
        import logging
        logging.getLogger(__name__).warning("Jira credentials not found in settings! jira_auth_token and (jira_username + jira_token) are missing.")
    try:
        parser = ConfluenceParser(ConfluenceClient(settings), settings, jira_client=jira_client)
        result = parser.parse(dry_run=dry_run)
    except (httpx.ConnectError, httpx.TimeoutException, ConfluenceError) as exc:
        _raise_confluence_cli_error(settings.confluence_base_url, exc)
    finally:
        if jira_client:
            jira_client.close()
    db = SQLite(settings.sqlite_db_path)
    metadata_repo = MetadataRepository(db)
    for datamart in result.datamarts:
        if not dry_run:
            metadata_repo.upsert_datamart(datamart)
        typer.echo(f"Витрина: {datamart.name}")
        typer.echo(f"  stakeholders: {len(datamart.stakeholders)}")
        typer.echo(f"  release_changes: {len(datamart.release_changes)}")
        typer.echo(f"  s2t: {datamart.s2t_resource.title if datamart.s2t_resource else '-'}")


@app.command("parse-s2t")
def parse_s2t(
    path: Path,
    datamart: str = typer.Option(..., "--datamart"),
) -> None:
    if not path.exists():
        raise typer.BadParameter(f"S2T file not found: {path}", param_hint="path")
    if not path.is_file():
        raise typer.BadParameter(f"S2T path is not a file: {path}", param_hint="path")

    _, metadata_repo, history_repo, _ = _repos()
    try:
        result = S2TParser().parse(path, datamart)
    except (S2TParseError, pandas.errors.ParserError, ValueError) as exc:
        raise typer.BadParameter(f"Cannot parse S2T file {path}: {exc}", param_hint="path") from exc
    old_attributes = metadata_repo.list_attributes(datamart_name=datamart)
    changes = (
        []
        if not old_attributes
        else DiffService().diff_attributes(old_attributes, result.attributes, source_url=str(path))
    )
    metadata_repo.upsert_datamart(
        Datamart(name=datamart, confluence_page_id="local", confluence_url=str(path))
    )
    metadata_repo.replace_attributes_for_datamart(datamart, result.attributes)
    history_repo.add_many(changes)
    typer.echo(f"Parsed attributes: {len(result.attributes)}")
    typer.echo(f"Detected changes: {len(changes)}")
    typer.echo(f"Processed sheets: {', '.join(result.processed_sheets) or '-'}")
    for issue in result.issues:
        typer.echo(f"WARNING {issue.sheet}:{issue.row_number}: {issue.message}")


@app.command("build-rag")
def build_rag(full: bool = typer.Option(False, "--full")) -> None:
    _, _, _, indexer = _repos()
    docs = indexer.rebuild_from_storage()
    typer.echo(f"Indexed documents: {len(docs)}")
    if full:
        typer.echo("Full rebuild completed")


@app.command("update-rag")
def update_rag(
    since: str | None = typer.Option(None, "--since"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    db = SQLite(settings.sqlite_db_path)
    metadata_repo = MetadataRepository(db)
    history_repo = HistoryRepository(db)
    document_repo = DocumentRepository(db)
    vector_store = JsonVectorStore(settings.vector_store_dir)
    indexer = RAGIndexer(metadata_repo, document_repo, vector_store)
    jira_client = None
    # Fix: Also check for jira_auth_token
    if settings.jira_auth_token or (settings.jira_username and (settings.jira_token or settings.jira_api_token)):
        import logging
        logging.getLogger(__name__).info("Initializing JiraClient...")
        jira_client = JiraClient(settings)
    else:
        import logging
        logging.getLogger(__name__).warning("Jira credentials not found in settings! jira_auth_token and (jira_username + jira_token) are missing.")
    try:
        confluence_client = ConfluenceClient(settings)
        parser = ConfluenceParser(confluence_client, settings, jira_client=jira_client)
        from app.storage.page_snapshot_repository import PageSnapshotRepository
        updater = IncrementalUpdater(
            metadata_sync=MetadataSyncService(parser, snapshot_repo=PageSnapshotRepository(db)),
            confluence_client=confluence_client,
            state_repo=S2TStateRepository(db),
            metadata_repo=metadata_repo,
            history_repo=history_repo,
            indexer=indexer,
            data_dir=settings.data_dir,
        )
        result = updater.run(dry_run=dry_run)
    except (httpx.ConnectError, httpx.TimeoutException, ConfluenceError) as exc:
        _raise_confluence_cli_error(settings.confluence_base_url, exc)
    finally:
        if jira_client:
            jira_client.close()
    _print_incremental_update_result(result, dry_run=dry_run)
    if since:
        typer.echo(f"Since filter accepted for orchestration: {since}")


def _print_incremental_update_result(
    result: IncrementalUpdateResult, dry_run: bool = False
) -> None:
    prefix = "Dry run" if dry_run else "Incremental update"
    typer.echo(f"{prefix} S2T resources: {len(result.items)}")
    for item in result.items:
        typer.echo(f"- {item.datamart_name}: {item.file_name or item.resource_key}")
        typer.echo(f"  metadata_changed: {item.metadata_changed}")
        typer.echo(f"  reasons: {', '.join(item.reasons) or '-'}")
        typer.echo(f"  will_download: {item.will_download}")
        typer.echo(f"  will_parse: {item.will_parse}")
        typer.echo(f"  will_reindex: {item.will_reindex}")
        if item.content_changed is not None:
            typer.echo(f"  content_changed: {item.content_changed}")
        if item.changes_detected:
            typer.echo(f"  changes_detected: {item.changes_detected}")
    if dry_run:
        typer.echo(f"Files to download: {result.downloaded_count}")
        typer.echo(f"S2T files to parse: {result.parsed_count}")
        typer.echo(f"Datamarts to reindex: {result.reindexed_count}")
    else:
        typer.echo(f"Downloaded files: {result.downloaded_count}")
        typer.echo(f"Parsed S2T files: {result.parsed_count}")
        typer.echo(f"Reindexed datamarts: {result.reindexed_count}")
    typer.echo(f"Detected changes: {result.changes_count}")


def _raise_confluence_cli_error(base_url: str, exc: Exception) -> None:
    if isinstance(exc, ConfluenceAuthError):
        message = (
            f"Confluence authentication failed for {base_url}. Проверьте "
            "CONFLUENCE_AUTH_TYPE, CONFLUENCE_USERNAME, CONFLUENCE_API_TOKEN "
            "и права на space/page/attachment. "
            f"Детали: {exc}"
        )
    elif isinstance(exc, httpx.TimeoutException):
        message = (
            f"Confluence не ответил вовремя: {base_url}. Проверьте VPN/сеть "
            "и доступность Confluence."
        )
    elif isinstance(exc, httpx.ConnectError):
        message = (
            f"Не удалось подключиться к Confluence: {base_url}. "
            "Чаще всего это DNS/VPN/прокси или ошибка в CONFLUENCE_BASE_URL. "
            f"Детали: {exc}"
        )
    else:
        message = f"Confluence request failed for {base_url}: {exc}"
    raise typer.BadParameter(message, param_hint="CONFLUENCE") from exc


@app.command("ask")
def ask(question: str) -> None:
    service = BotService(build_retriever())
    typer.echo(service.format_answer(service.ask(question)))


@app.command("chat")
def chat() -> None:
    service = BotService(build_retriever())
    adapter = CLIAdapter()
    adapter.send_message("Введите вопрос. Для выхода: exit")
    while True:
        question = adapter.receive_message().strip()
        if not question:
            continue
        if question.lower() in {"exit", "quit", "q"}:
            break
        adapter.send_message(service.format_answer(service.ask(question)))


@app.command("changes")
def changes(
    datamart: str | None = typer.Option(None, "--datamart"),
    last_year: bool = typer.Option(False, "--last-year"),
) -> None:
    _, _, history_repo, _ = _repos()
    since = datetime.utcnow() - timedelta(days=365) if last_year else None
    entries = history_repo.list_changes(since=since, datamart_name=datamart)
    for entry in entries:
        date = entry.change_date.date()
        typer.echo(f"{date} {entry.datamart_name} {entry.entity_name} {entry.change_type}")


@app.command("find-attribute")
def find_attribute(attribute: str) -> None:
    _, metadata_repo, _, _ = _repos()
    attrs = metadata_repo.find_attribute_usage(attribute)
    for attr in attrs:
        target = f"{attr.target_table}.{attr.target_field}"
        source = f"{attr.source_table}.{attr.source_field}"
        typer.echo(f"{attr.datamart_name}: {target} <- {source}")


if __name__ == "__main__":
    app()
