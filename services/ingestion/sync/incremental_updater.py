import logging
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from services.ingestion.changes.diff_service import DiffService
from services.ingestion.changes.history_repository import HistoryRepository
from services.ingestion.confluence.client import ConfluenceClient
from services.ingestion.confluence.exceptions import ConfluenceAuthError, ConfluenceError
from services.ingestion.s2t.parser import S2TParser
from services.ingestion.sync.hash_service import HashService
from services.ingestion.sync.metadata_sync_service import MetadataSyncService, S2TMetadataSnapshot
from services.ingestion.sync.state_comparator import StateComparator
from services.rag.indexer import RAGIndexer
from shared.storage.metadata_repository import MetadataRepository
from shared.storage.s2t_state_repository import S2TStateRepository

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IncrementalUpdateItem:
    """
    Элемент результата инкрементального обновления для одной витрины/ресурса.
    """
    datamart_name: str
    resource_key: str
    file_name: str | None
    metadata_changed: bool
    reasons: list[str]
    will_download: bool
    will_parse: bool
    will_reindex: bool
    content_changed: bool | None = None
    content_hash: str | None = None
    changes_detected: int = 0


@dataclass(frozen=True)
class IncrementalUpdateResult:
    """
    Результат выполнения инкрементального обновления для всех витрин.
    """
    items: list[IncrementalUpdateItem] = field(default_factory=list)

    @property
    def downloaded_count(self) -> int:
        """Количество скачанных файлов."""
        return sum(1 for item in self.items if item.will_download)

    @property
    def parsed_count(self) -> int:
        """Количество распарсенных S2T файлов."""
        return sum(1 for item in self.items if item.will_parse)

    @property
    def reindexed_count(self) -> int:
        """Количество переиндексированных витрин."""
        return sum(1 for item in self.items if item.will_reindex)

    @property
    def changes_count(self) -> int:
        """Общее количество обнаруженных изменений в атрибутах."""
        return sum(item.changes_detected for item in self.items)


class IncrementalUpdater:
    """
    Оркестратор инкрементального обновления данных.
    Координирует работу парсеров, клиентов и репозиториев для синхронизации состояния.
    """
    def __init__(
        self,
        *,
        metadata_sync: MetadataSyncService,
        confluence_client: ConfluenceClient,
        state_repo: S2TStateRepository,
        metadata_repo: MetadataRepository,
        history_repo: HistoryRepository,
        indexer: RAGIndexer,
        data_dir: Path,
        hash_service: HashService | None = None,
        comparator: StateComparator | None = None,
        s2t_parser: S2TParser | None = None,
        diff_service: DiffService | None = None,
    ) -> None:
        """
        Инициализирует IncrementalUpdater.
        :param metadata_sync: Сервис синхронизации метаданных.
        :param confluence_client: Клиент Confluence.
        :param state_repo: Репозиторий состояний S2T.
        :param metadata_repo: Репозиторий метаданных.
        :param history_repo: Репозиторий истории изменений.
        :param indexer: Индексатор RAG.
        :param data_dir: Директория для хранения данных.
        :param hash_service: Сервис для вычисления хэшей.
        :param comparator: Сервис сравнения состояний.
        :param s2t_parser: Парсер S2T.
        :param diff_service: Сервис вычисления разницы атрибутов.
        """
        self.metadata_sync = metadata_sync
        self.confluence_client = confluence_client
        self.state_repo = state_repo
        self.metadata_repo = metadata_repo
        self.history_repo = history_repo
        self.indexer = indexer
        self.data_dir = data_dir
        self.hash_service = hash_service or HashService()
        self.comparator = comparator or StateComparator()
        self.s2t_parser = s2t_parser or S2TParser()
        self.diff_service = diff_service or DiffService()

    def run(self, dry_run: bool = False) -> IncrementalUpdateResult:
        """
        Запускает процесс инкрементального обновления.
        :param dry_run: Если True, изменения не сохраняются.
        :return: Объект IncrementalUpdateResult.
        """
        items: list[IncrementalUpdateItem] = []
        active_names = []
        
        for snapshot in self.metadata_sync.collect():
            try:
                item = self._process_snapshot(snapshot, dry_run=dry_run)
                items.append(item)
                if not dry_run:
                    active_names.append(snapshot.datamart.name)
            except Exception as exc:
                logger.error(
                    "Failed to process datamart %s: %s", snapshot.datamart.name, exc, exc_info=True
                )
                items.append(
                    IncrementalUpdateItem(
                        datamart_name=snapshot.datamart.name,
                        resource_key=snapshot.unique_key,
                        file_name=snapshot.resource.file_name if snapshot.resource else None,
                        metadata_changed=True,
                        reasons=[f"Processing failed: {exc}"],
                        will_download=False,
                        will_parse=False,
                        will_reindex=False,
                    )
                )
        
        if not dry_run and active_names:
            deleted_count = self.metadata_repo.clear_stale_datamarts(active_names)
            if deleted_count > 0:
                logger.info("Sync: removed %d stale datamarts from database", deleted_count)
                
        return IncrementalUpdateResult(items=items)

    def _process_snapshot(
        self, snapshot: S2TMetadataSnapshot, dry_run: bool
    ) -> IncrementalUpdateItem:
        """
        Обрабатывает один снимок метаданных, принимая решение о необходимости обновления.
        :param snapshot: Снимок метаданных.
        :param dry_run: Режим пробного запуска.
        :return: Элемент результата обновления.
        """
        resource = snapshot.resource
        resource_key = snapshot.unique_key
        previous = self.state_repo.get(resource_key)
        decision = self.comparator.compare(previous, snapshot.metadata_hash, snapshot.metadata)
        
        file_name = resource.file_name or resource.title if resource else None
        page_id = resource.page_id if resource else None
        resource_type = resource.resource_type if resource else None
        title = resource.title if resource else None
        url = (resource.download_url or resource.url) if resource else None
        updated_at = resource.updated_at if resource else None

        if not decision.changed:
            if not dry_run:
                self.state_repo.upsert(
                    resource_key=resource_key,
                    datamart_name=snapshot.datamart.name,
                    page_id=page_id,
                    resource_type=resource_type,
                    title=title,
                    file_name=file_name,
                    url=url,
                    metadata=snapshot.metadata,
                    metadata_hash=snapshot.metadata_hash,
                    content_hash=previous.content_hash if previous else None,
                    synced=False,
                    updated_at=updated_at,
                )
            return IncrementalUpdateItem(
                datamart_name=snapshot.datamart.name,
                resource_key=resource_key,
                file_name=file_name,
                metadata_changed=False,
                reasons=decision.reasons,
                will_download=False,
                will_parse=False,
                will_reindex=False,
            )

        if dry_run:
            return IncrementalUpdateItem(
                datamart_name=snapshot.datamart.name,
                resource_key=resource_key,
                file_name=file_name,
                metadata_changed=True,
                reasons=decision.reasons,
                will_download=bool(resource),
                will_parse=bool(resource),
                will_reindex=True,
            )

        # Check if we can skip download based on version/id
        # If attachment ID and version are same as before, content must be same.
        can_skip_download = False
        if previous and previous.content_hash:
            old_id = previous.metadata.get("attachment_id")
            new_id = snapshot.metadata.get("attachment_id")
            old_ver = previous.metadata.get("attachment_version_number")
            new_ver = snapshot.metadata.get("attachment_version_number")
            
            if old_id and old_id == new_id and old_ver == new_ver:
                logger.info(
                    "Skipping download for %s: attachment version %s is unchanged",
                    resource_key, new_ver
                )
                can_skip_download = True

        if not resource or not url:
            # Обновляем метаданные витрины даже если нет s2t файла
            old_attrs = self.metadata_repo.list_attributes(datamart_name=snapshot.datamart.name)
            self.indexer.update_datamart(snapshot.datamart, old_attrs)
            
            self.state_repo.upsert(
                resource_key=resource_key,
                datamart_name=snapshot.datamart.name,
                page_id=page_id,
                resource_type=resource_type,
                title=title,
                file_name=file_name,
                url=url,
                metadata=snapshot.metadata,
                metadata_hash=snapshot.metadata_hash,
                content_hash=None,
                synced=True,
                updated_at=updated_at,
            )
            return IncrementalUpdateItem(
                datamart_name=snapshot.datamart.name,
                resource_key=resource_key,
                file_name=file_name,
                metadata_changed=True,
                reasons=[*decision.reasons, "no s2t resource" if not resource else "download url is absent"],
                will_download=False,
                will_parse=False,
                will_reindex=True,
                content_changed=False,
                content_hash=None,
            )

        if can_skip_download:
            content_hash = previous.content_hash
            content_changed = False
            actually_downloaded = False
            content = b"" # Not used if content_changed is False
        else:
            try:
                if hasattr(self.confluence_client, "download_resource"):
                    content = self.confluence_client.download_resource(resource, datamart_page_id=snapshot.datamart.confluence_page_id)
                else:
                    content = self.confluence_client.download(url)
                content_hash = self.hash_service.sha256_bytes(content)
                previous_content_hash = previous.content_hash if previous else None
                content_changed = content_hash != previous_content_hash
                actually_downloaded = True
            except (ConfluenceAuthError, ConfluenceError) as exc:
                logger.warning("Failed to download S2T for %s: %s. Updating metadata only.", snapshot.datamart.name, exc)
                # Если загрузка файла не удалась, мы все равно можем обновить метаданные самой витрины
                # (стейкхолдеры, факты, изменения в релизах), которые мы уже получили из Confluence.
                old_attrs = self.metadata_repo.list_attributes(datamart_name=snapshot.datamart.name)
                self.indexer.update_datamart(snapshot.datamart, old_attrs)
                
                # Мы НЕ обновляем state_repo, чтобы при следующем запуске бот снова попробовал скачать файл.
                return IncrementalUpdateItem(
                    datamart_name=snapshot.datamart.name,
                    resource_key=resource_key,
                    file_name=file_name,
                    metadata_changed=True,
                    reasons=[*decision.reasons, f"Download failed: {exc}. Metadata updated."],
                    will_download=True,
                    will_parse=False,
                    will_reindex=True,
                    content_changed=None,
                )

        if not content_changed:
            self.state_repo.upsert(
                resource_key=resource_key,
                datamart_name=snapshot.datamart.name,
                page_id=page_id,
                resource_type=resource_type,
                title=title,
                file_name=file_name,
                url=url,
                metadata=snapshot.metadata,
                metadata_hash=snapshot.metadata_hash,
                content_hash=content_hash,
                synced=True,
                updated_at=updated_at,
            )
            # Если поменялись только метаданные (например, стейкхолдеры), 
            # мы обновляем метаданные в БД и переиндексируем документы RAG, 
            # но не перепаршиваем сам файл.
            old_attrs = self.metadata_repo.list_attributes(datamart_name=snapshot.datamart.name)
            self.indexer.update_datamart(snapshot.datamart, old_attrs)

            return IncrementalUpdateItem(
                datamart_name=snapshot.datamart.name,
                resource_key=resource_key,
                file_name=file_name,
                metadata_changed=True,
                reasons=[*decision.reasons, "content hash unchanged but metadata updated"],
                will_download=actually_downloaded,
                will_parse=False,
                will_reindex=True,
                content_changed=False,
                content_hash=content_hash,
            )

        path = self._write_raw_file(resource_key, file_name, content)
        old_attrs = self.metadata_repo.list_attributes(datamart_name=snapshot.datamart.name)
        parsed = self.s2t_parser.parse(path, snapshot.datamart.name, resource.file_date)
        new_attrs = parsed.attributes
        changes = (
            []
            if previous is None and not old_attrs
            else self.diff_service.diff_attributes(old_attrs, new_attrs, source_url=url)
        )
        self.history_repo.add_many(changes)
        documents = self.indexer.update_datamart(snapshot.datamart, new_attrs)
        self.state_repo.upsert(
            resource_key=resource_key,
            datamart_name=snapshot.datamart.name,
            page_id=page_id,
            resource_type=resource_type,
            title=title,
            file_name=file_name,
            url=url,
            metadata=snapshot.metadata,
            metadata_hash=snapshot.metadata_hash,
            content_hash=content_hash,
            synced=True,
            updated_at=updated_at,
        )
        return IncrementalUpdateItem(
            datamart_name=snapshot.datamart.name,
            resource_key=resource_key,
            file_name=file_name,
            metadata_changed=True,
            reasons=decision.reasons,
            will_download=True,
            will_parse=True,
            will_reindex=bool(documents),
            content_changed=True,
            content_hash=content_hash,
            changes_detected=len(changes),
        )

    def _write_raw_file(self, datamart_name: str, file_name: str | None, content: bytes) -> Path:
        """
        Сохраняет бинарное содержимое файла на диск.
        :param datamart_name: Название витрины.
        :param file_name: Имя файла.
        :param content: Бинарные данные.
        :return: Путь к сохраненному файлу.
        """
        raw_dir = self.data_dir / "raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        safe_name = self._safe_file_name(file_name or "s2t.bin")
        # Use datamart_name and file_name to generate a stable, predictable hash for the filename
        # This prevents the RAG context from losing files because the generated key changed.
        key_hash = self.hash_service.stable_metadata_hash({"datamart": datamart_name, "file": safe_name})[:12]
        path = raw_dir / f"{key_hash}_{safe_name}"
        path.write_bytes(content)
        return path

    @staticmethod
    def _safe_file_name(value: str) -> str:
        """
        Создает безопасное имя файла, удаляя недопустимые символы.
        :param value: Исходная строка для имени файла.
        :return: Безопасное имя файла.
        """
        parsed_name = Path(urlparse(value).path).name or "s2t.bin"
        return "".join(char if char.isalnum() or char in "._-" else "_" for char in parsed_name)
