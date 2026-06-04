import json
from dataclasses import dataclass
from datetime import datetime

from shared.storage.sqlite import SQLite


@dataclass(frozen=True)
class S2TState:
    """
    Представляет состояние ресурса S2T (файла или страницы) для инкрементальной синхронизации.
    """
    resource_key: str
    datamart_name: str
    page_id: str | None
    resource_type: str | None
    title: str | None
    file_name: str | None
    url: str | None
    metadata: dict
    metadata_hash: str
    content_hash: str | None
    last_checked_at: datetime
    last_synced_at: datetime | None
    updated_at: datetime | None


class S2TStateRepository:
    """
    Репозиторий для управления состоянием ресурсов S2T в SQLite.
    """
    def __init__(self, db: SQLite) -> None:
        """
        Инициализирует S2TStateRepository.
        :param db: Объект SQLite для взаимодействия с базой данных.
        """
        self.db = db

    def get(self, resource_key: str) -> S2TState | None:
        """
        Извлекает состояние ресурса по его ключу.
        :param resource_key: Уникальный ключ ресурса.
        :return: Объект S2TState или None, если ресурс не найден.
        """
        with self.db.connect() as conn:
            row = conn.execute(
                "select * from s2t_state where resource_key = ?", (resource_key,)
            ).fetchone()
        return self._row_to_state(row) if row else None

    def upsert(
        self,
        *,
        resource_key: str,
        datamart_name: str,
        page_id: str | None,
        resource_type: str | None,
        title: str | None,
        file_name: str | None,
        url: str | None,
        metadata: dict,
        metadata_hash: str,
        content_hash: str | None,
        synced: bool,
        updated_at: datetime | None,
    ) -> None:
        """
        Обновляет или добавляет состояние ресурса.
        :param resource_key: Уникальный ключ ресурса.
        :param datamart_name: Название витрины данных.
        :param page_id: ID страницы в Confluence.
        :param resource_type: Тип ресурса (например, attachment).
        :param title: Заголовок.
        :param file_name: Имя файла.
        :param url: URL ресурса.
        :param metadata: Метаданные в виде словаря.
        :param metadata_hash: Хеш метаданных.
        :param content_hash: Хеш содержимого.
        :param synced: Флаг, указывающий на успешную синхронизацию.
        :param updated_at: Дата последнего обновления.
        """
        now = datetime.utcnow()
        synced_at = now if synced else None
        with self.db.connect() as conn:
            previous = conn.execute(
                "select last_synced_at from s2t_state where resource_key = ?", (resource_key,)
            ).fetchone()
            if previous and not synced:
                synced_at_text = previous["last_synced_at"]
            else:
                synced_at_text = synced_at.isoformat() if synced_at else None
            conn.execute(
                """
                insert into s2t_state(
                    resource_key, datamart_name, page_id, resource_type, title, file_name,
                    url, metadata_json, metadata_hash, content_hash, last_checked_at,
                    last_synced_at, updated_at
                )
                values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(resource_key) do update set
                    datamart_name=excluded.datamart_name,
                    page_id=excluded.page_id,
                    resource_type=excluded.resource_type,
                    title=excluded.title,
                    file_name=excluded.file_name,
                    url=excluded.url,
                    metadata_json=excluded.metadata_json,
                    metadata_hash=excluded.metadata_hash,
                    content_hash=excluded.content_hash,
                    last_checked_at=excluded.last_checked_at,
                    last_synced_at=excluded.last_synced_at,
                    updated_at=excluded.updated_at
                """,
                (
                    resource_key,
                    datamart_name,
                    page_id,
                    resource_type,
                    title,
                    file_name,
                    url,
                    json.dumps(metadata, ensure_ascii=False, sort_keys=True, default=str),
                    metadata_hash,
                    content_hash,
                    now.isoformat(),
                    synced_at_text,
                    updated_at.isoformat() if updated_at else None,
                ),
            )

    def list_all(self) -> list[S2TState]:
        """
        Возвращает список всех состояний ресурсов.
        :return: Список объектов S2TState.
        """
        with self.db.connect() as conn:
            rows = conn.execute("select * from s2t_state").fetchall()
        return [self._row_to_state(row) for row in rows]

    @staticmethod
    def _row_to_state(row) -> S2TState:
        """
        Преобразует строку базы данных в объект S2TState.
        :param row: Строка результата запроса.
        :return: Объект S2TState.
        """
        return S2TState(
            resource_key=row["resource_key"],
            datamart_name=row["datamart_name"],
            page_id=row["page_id"],
            resource_type=row["resource_type"],
            title=row["title"],
            file_name=row["file_name"],
            url=row["url"],
            metadata=json.loads(row["metadata_json"]),
            metadata_hash=row["metadata_hash"],
            content_hash=row["content_hash"],
            last_checked_at=datetime.fromisoformat(row["last_checked_at"]),
            last_synced_at=datetime.fromisoformat(row["last_synced_at"])
            if row["last_synced_at"]
            else None,
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
        )
