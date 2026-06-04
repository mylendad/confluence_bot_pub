from datetime import datetime

from pydantic import BaseModel, Field


class ChangeLogEntry(BaseModel):
    id: str
    datamart_name: str
    datamart_code: str | None = None
    entity_type: str
    entity_name: str
    change_type: str
    old_value: str | None = None
    new_value: str | None = None
    change_date: datetime = Field(default_factory=datetime.utcnow)
    detected_at: datetime = Field(default_factory=datetime.utcnow)
    source_url: str | None = None
    s2t_file_name: str | None = None
