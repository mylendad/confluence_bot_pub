from datetime import date, datetime

from pydantic import BaseModel, Field


class Stakeholder(BaseModel):
    name: str | None = None
    email: str | None = None
    role: str | None = None
    department: str | None = None
    profile_url: str | None = None


class DatamartFact(BaseModel):
    key: str
    label: str
    value: str
    links: list[dict[str, str]] = Field(default_factory=list)


class ReleaseChange(BaseModel):
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
    # We will compute a unique key dynamically in the sync service or during processing
    # but as a fallback property we can use the ID and page ID of the resource itself.
    @property
    def resource_key(self) -> str:
        base_key = self.id or self.download_url or self.url or self.file_name
        return f"{self.page_id}:{base_key}" if self.page_id else base_key


class Datamart(BaseModel):
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
    # Map of page_id -> version_number for all pages visited during parsing
    visited_pages: dict[str, int] = Field(default_factory=dict)


class ParseResult(BaseModel):
    datamarts: list[Datamart] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
