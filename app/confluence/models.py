from datetime import date, datetime

from pydantic import BaseModel, Field


class Stakeholder(BaseModel):
    name: str | None = None
    email: str | None = None
    role: str | None = None
    department: str | None = None
    profile_url: str | None = None


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

    @property
    def resource_key(self) -> str:
        return self.id or self.download_url or self.url or f"{self.page_id}:{self.file_name}"


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
    s2t_resource: S2TResource | None = None


class ParseResult(BaseModel):
    datamarts: list[Datamart] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
