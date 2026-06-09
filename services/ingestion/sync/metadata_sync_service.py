import logging
import re
from dataclasses import dataclass
from datetime import UTC

from services.ingestion.confluence.models import Datamart, S2TResource
from services.ingestion.confluence.parser import ConfluenceParser
from services.ingestion.sync.hash_service import HashService
from shared.storage.page_snapshot_repository import PageSnapshotRepository
from shared.utils.hashing import stable_hash
from shared.utils.text_utils import normalize_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class S2TMetadataSnapshot:
    """
    Снимок метаданных ресурса S2T, используемый для отслеживания изменений.
    """

    datamart: Datamart
    resource: S2TResource | None
    metadata: dict
    metadata_hash: str

    @property
    def unique_key(self) -> str:
        """
        Генерирует уникальный ключ для ресурса S2T.
        :return: Строковый уникальный ключ.
        """
        if not self.resource:
            return f"{self.datamart.confluence_page_id}:no_s2t"
        base_key = (
            self.resource.id
            or self.resource.download_url
            or self.resource.url
            or self.resource.file_name
        )
        return f"{self.datamart.confluence_page_id}:{base_key}"


class MetadataSyncService:
    """
    Сервис для синхронизации метаданных витрин данных из Confluence.
    Обеспечивает поиск страниц, извлечение фактов и формирование снимков состояния.
    """

    def __init__(
        self,
        parser: ConfluenceParser,
        hash_service: HashService | None = None,
        snapshot_repo: PageSnapshotRepository | None = None,
    ) -> None:
        """
        Инициализирует MetadataSyncService.
        :param parser: Парсер Confluence.
        :param hash_service: Сервис для вычисления хэшей.
        :param snapshot_repo: Репозиторий для кэширования снимков страниц.
        """
        self.parser = parser
        self.hash_service = hash_service or HashService()
        self.snapshot_repo = snapshot_repo
        self._prefetched_versions: dict[str, int] = {}

    def collect(self) -> list[S2TMetadataSnapshot]:
        """
        Собирает снимки метаданных для всех найденных витрин данных.
        :return: Список объектов S2TMetadataSnapshot.
        """
        snapshots: list[S2TMetadataSnapshot] = []
        pattern = normalize_text(self.parser.settings.datamart_page_pattern)
        exclude_pattern = self.parser.settings.datamart_exclude_pattern

        logger.info("Discovery: fetching all accessible pages recursively...")
        top_level_pages = list(self.parser.client.iter_top_level_pages())
        logger.info("Discovery: found %d pages total in Confluence tree", len(top_level_pages))

        # Keywords for identifying helper pages (only if they are at the START of the title)
        helper_prefixes = [
            "чек-лист",
            "тз",
            "препятствия",
            "функциональное решение",
            "s2t",
            "изменения в релизах",
            "страница для 2лс",
            "копия",
        ]
        norm_prefixes = [normalize_text(kw) for kw in helper_prefixes]

        for page in top_level_pages:
            title_clean = page.title.replace("\u00a0", " ").strip()
            norm_title = normalize_text(title_clean)

            # 1. Skip helper pages only if they START with helper keywords
            is_helper = False
            for prefix in norm_prefixes:
                if norm_title.startswith(prefix):
                    is_helper = True
                    break

            if is_helper:
                logger.debug("Discovery: skipping helper page '%s'", page.title)
                continue

            # 2. Check pattern (if configured)
            if pattern and pattern not in norm_title:
                # Special check for Inner Source even if pattern doesn't match
                if "inner" not in norm_title:
                    logger.debug(
                        "Discovery: skipping page '%s' - title doesn't match pattern '%s'",
                        page.title,
                        pattern,
                    )
                    continue
                else:
                    logger.info(
                        "Discovery: page '%s' matches 'inner' keyword, bypassing pattern filter",
                        page.title,
                    )

            # 3. Check exclusions
            if exclude_pattern and re.search(exclude_pattern, page.title, re.IGNORECASE):
                logger.info("Discovery: skipping page '%s' - excluded by pattern", page.title)
                continue

            logger.info("Discovery: processing datamart page '%s' (ID: %s)", page.title, page.id)

            datamart = self._get_datamart_with_cache(page)
            if not datamart:
                continue

            snapshots.append(self._to_snapshot(datamart))

        # 4. Final attempt for Inner Source if still missing
        discovered_names = {s.datamart.name.lower() for s in snapshots}
        if not any("inner source" in name for name in discovered_names):
            logger.info(
                "Discovery: 'Inner Source' still missing, attempting GLOBAL direct search..."
            )
            try:
                for name in ["Витрина Inner Source", "Inner Source", "Витрина InnerSource"]:
                    found_page = self.parser.client.find_page_by_title(name)
                    if found_page:
                        logger.info(
                            "Discovery: FOUND '%s' via direct API lookup! (ID: %s)",
                            name,
                            found_page.id,
                        )
                        dm = self._get_datamart_with_cache(found_page)
                        if dm:
                            snapshots.append(self._to_snapshot(dm))
                        break
            except Exception as e:
                logger.warning("Discovery: direct search failed: %s", e)

        return snapshots

    def _to_snapshot(self, datamart: Datamart) -> S2TMetadataSnapshot:
        """
        Преобразует объект Datamart в снимок метаданных S2TMetadataSnapshot.
        :param datamart: Объект витрины данных.
        :return: Снимок метаданных.
        """
        resource = datamart.s2t_resource
        metadata = self._metadata(datamart, resource)

        hash_metadata = {
            "datamart_name": metadata["datamart_name"],
            "datamart_page_id": metadata["datamart_page_id"],
            "attachment_id": metadata.get("attachment_id"),
            "attachment_version_number": metadata.get("attachment_version_number"),
            "release_changes_hash": metadata["release_changes_hash"],
            "stakeholders_hash": metadata["stakeholders_hash"],
            "facts_hash": metadata["facts_hash"],
        }

        return S2TMetadataSnapshot(
            datamart=datamart,
            resource=resource,
            metadata=metadata,
            metadata_hash=self.hash_service.stable_metadata_hash(hash_metadata),
        )

    def _get_datamart_with_cache(self, page) -> Datamart | None:
        """
        Получает данные витрины, используя кэш снимков страниц, если он доступен.
        :param page: Страница Confluence.
        :return: Объект Datamart или None.
        """
        if not self.snapshot_repo:
            return self.parser.parse_datamart_page(page, skip_jira=False)

        snapshot = self.snapshot_repo.get(page.id)
        if snapshot:
            version_map, cached_datamart = snapshot
            if self._verify_versions(version_map):
                return cached_datamart

        datamart = self.parser.parse_datamart_page(page, skip_jira=False)
        if datamart:
            self.snapshot_repo.upsert(page.id, datamart.visited_pages, datamart)
        return datamart

    def _verify_versions(self, version_map: dict[str, int]) -> bool:
        """
        Проверяет, что версии страниц в Confluence совпадают с ожидаемыми.
        :param version_map: Словарь {page_id: version}.
        :return: True, если все версии совпадают.
        """
        for page_id, expected_version in version_map.items():
            if hasattr(self, "_prefetched_versions") and page_id in self._prefetched_versions:
                if self._prefetched_versions[page_id] != expected_version:
                    return False
                continue
            try:
                current_page = self.parser.client.get_page(page_id)
                if not current_page or current_page.version != expected_version:
                    return False
            except Exception:
                return False
        return True

    @staticmethod
    def _metadata(datamart: Datamart, resource: S2TResource | None) -> dict:
        """
        Формирует словарь метаданных для витрины и ее ресурса S2T.
        :param datamart: Объект витрины данных.
        :param resource: Ресурс S2T (может быть None).
        :return: Словарь метаданных.
        """

        def fmt_dt(dt) -> str | None:
            if not dt:
                return None
            if dt.tzinfo:
                dt = dt.astimezone(UTC)
            return dt.replace(microsecond=0).isoformat()

        stable_release_changes = sorted(
            [{"v": c.version, "k": c.jira_key, "s": c.summary} for c in datamart.release_changes],
            key=lambda x: (x["v"] or "", x["k"] or ""),
        )

        stable_facts = sorted(
            [f.model_dump(mode="json") for f in datamart.facts], key=lambda x: x["key"]
        )

        meta = {
            "datamart_name": datamart.name,
            "datamart_page_id": datamart.confluence_page_id,
            "release_changes_hash": stable_hash(stable_release_changes),
            "stakeholders_hash": stable_hash(
                sorted(
                    [s.model_dump(mode="json") for s in datamart.stakeholders],
                    key=lambda x: x.get("email") or "",
                )
            ),
            "facts_hash": stable_hash(stable_facts),
        }

        if resource:
            meta.update({
                "attachment_id": resource.id,
                "attachment_version_number": resource.version,
                "file_name": resource.file_name,
            })
        return meta
