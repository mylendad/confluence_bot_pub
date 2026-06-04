import json
import logging
from datetime import UTC, datetime

from services.ingestion.confluence.models import Datamart
from shared.storage.sqlite import SQLite

logger = logging.getLogger(__name__)


class PageSnapshotRepository:
    """
    Репозиторий для хранения снимков (снапшотов) страниц Confluence.
    """
    def __init__(self, db: SQLite) -> None:
        """
        Инициализирует PageSnapshotRepository.
        :param db: Объект SQLite для взаимодействия с базой данных.
        """
        self.db = db

    def get(self, datamart_page_id: str) -> tuple[dict[str, int], Datamart] | None:
        """
        Извлекает сохраненный снимок страницы по её ID.
        :param datamart_page_id: Идентификатор страницы витрины в Confluence.
        :return: Кортеж (карта версий, объект Datamart) или None, если снимок не найден.
        """
        with self.db.connect() as conn:
            row = conn.execute(
                "select version_map_json, extracted_data_json from page_snapshots where datamart_page_id = ?",
                (datamart_page_id,),
            ).fetchone()
            if not row:
                return None
            try:
                version_map = json.loads(row["version_map_json"])
                data_dict = json.loads(row["extracted_data_json"])
                return version_map, Datamart.model_validate(data_dict)
            except Exception as exc:
                logger.error("Failed to load page snapshot for %s: %s", datamart_page_id, exc)
                return None

    def upsert(self, datamart_page_id: str, version_map: dict[str, int], datamart: Datamart) -> None:
        """
        Сохраняет или обновляет снимок страницы.
        :param datamart_page_id: Идентификатор страницы витрины в Confluence.
        :param version_map: Словарь соответствия путей к файлам и их версий.
        :param datamart: Извлеченный объект Datamart.
        """
        with self.db.connect() as conn:
            conn.execute(
                """
                insert into page_snapshots (datamart_page_id, version_map_json, extracted_data_json, updated_at)
                values (?, ?, ?, ?)
                on conflict(datamart_page_id) do update set
                    version_map_json = excluded.version_map_json,
                    extracted_data_json = excluded.extracted_data_json,
                    updated_at = excluded.updated_at
                """,
                (
                    datamart_page_id,
                    json.dumps(version_map),
                    datamart.model_dump_json(),
                    datetime.now(UTC).isoformat(),
                ),
            )

    def delete(self, datamart_page_id: str) -> None:
        """
        Удаляет снимок страницы из базы данных.
        :param datamart_page_id: Идентификатор страницы для удаления.
        """
        with self.db.connect() as conn:
            conn.execute("delete from page_snapshots where datamart_page_id = ?", (datamart_page_id,))
