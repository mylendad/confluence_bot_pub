from datetime import date, datetime

from pydantic import BaseModel, Field


class S2TAttribute(BaseModel):
    datamart_name: str
    datamart_code: str | None = None
    owner: str | None = None
    target_platform: str | None = None
    target_instance: str | None = None
    target_schema: str | None = None
    target_table: str | None = None
    target_field: str | None = None
    target_table_description: str | None = None
    target_field_description: str | None = None
    source_name: str | None = None
    source_platform: str | None = None
    source_instance: str | None = None
    source_schema: str | None = None
    source_table: str | None = None
    source_field: str | None = None
    join_condition: str | None = None
    where_condition: str | None = None
    group_by: str | None = None
    keys: str | None = None
    history_type: str | None = None
    history_role: str | None = None
    refresh_frequency: str | None = None
    data_actuality: str | None = None
    business_description: str | None = None
    transformation_logic: str | None = None
    s2t_file_name: str | None = None
    s2t_file_date: date | None = None
    parsed_at: datetime = Field(default_factory=datetime.utcnow)

    @property
    def attribute_key(self) -> str:
        return "|".join(
            [
                self.datamart_code or self.datamart_name,
                self.target_schema or "",
                self.target_table or "",
                self.target_field or "",
            ]
        ).lower()


class S2TParseIssue(BaseModel):
    sheet: str | None = None
    row_number: int | None = None
    message: str


class S2TParseResult(BaseModel):
    attributes: list[S2TAttribute] = Field(default_factory=list)
    processed_sheets: list[str] = Field(default_factory=list)
    issues: list[S2TParseIssue] = Field(default_factory=list)
