from datetime import date, datetime

from pydantic import BaseModel, Field


class Stakeholder(BaseModel):
    """
    Модель данных стейкхолдера (заинтересованного лица).
    """
    name: str | None = None
    email: str | None = None
    role: str | None = None
    department: str | None = None
    profile_url: str | None = None


class DatamartFact(BaseModel):
    """
    Модель атрибута (факта) витрины данных.
    """
    key: str
    label: str
    value: str
    links: list[dict[str, str]] = Field(default_factory=list)


class ReleaseChange(BaseModel):
    """
    Модель изменения в релизе (задачи из журнала изменений).
    """
    version: str | None = None
    jira_key: str | None = None
    jira_title: str | None = None
    change_type: str | None = None
    summary: str | None = None
    status: str | None = None
    source_url: str | None = None
    jira_created_at: datetime | None = None
    jira_done_at: datetime | None = None
    jira_last_activity_value: str | None = None


class ConfluencePage(BaseModel):
    """
    Модель страницы Confluence с метаданными и содержимым.
    """
    id: str
    title: str
    url: str
    body_html: str | None = None
    updated_at: datetime | None = None
    version: int | None = None
    version_when: datetime | None = None
    last_modified: datetime | None = None
    history_last_updated: datetime | None = None


class S2TResource(BaseModel):
    """
    Модель ресурса S2T (вложение или ссылка на файл).
    """
    id: str | None = None
    title: str
    url: str | None = None
    resource_type: str = "unknown"
    file_name: str | None = None
    file_date: date | None = None
    updated_at: datetime | None = None
    version: int | None = None
    version_when: datetime | None = None
    file_size: int | None = None
    download_url: str | None = None
    media_type: str | None = None
    page_id: str | None = None

    @property
    def resource_key(self) -> str:
        """
        Генерирует уникальный ключ ресурса.
        :return: Строковый ключ.
        """
        base_key = self.id or self.download_url or self.url or self.file_name
        return f"{self.page_id}:{base_key}" if self.page_id else base_key


class Datamart(BaseModel):
    """
    Модель витрины данных со всей собранной информацией.
    """
    name: str
    confluence_page_id: str
    confluence_url: str
    code: str | None = None
    page_version: int | None = None
    page_version_when: datetime | None = None
    page_last_modified: datetime | None = None
    page_history_last_updated: datetime | None = None
    stakeholders: list[Stakeholder] = Field(default_factory=list)
    facts: list[DatamartFact] = Field(default_factory=list)
    release_changes: list[ReleaseChange] = Field(default_factory=list)
    s2t_resource: S2TResource | None = None
    visited_pages: dict[str, int] = Field(default_factory=dict)


class ParseResult(BaseModel):
    """
    Результат парсинга набора страниц Confluence.
    """
    datamarts: list[Datamart] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
