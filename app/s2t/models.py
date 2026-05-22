from datetime import date, datetime

from pydantic import BaseModel, Field

COLUMN_ALIASES = {
    "owner": [
        "UserName",
        "owner",
        "владелец",
        "ответственный",
        "заинтересованное лицо",
    ],
    "target_platform": ["T-trg-platform", "T-platform", "target platform", "целевая платформа"],
    "target_instance": ["T-trg-instance", "T-instance", "target instance", "целевой инстанс"],
    "target_schema": [
        "T-trg-schema",
        "T-schema",
        "target_schema",
        "target schema",
        "целевая схема",
        "схема приемника",
    ],
    "target_table": [
        "T-trg",
        "T-name",
        "target_table",
        "target table",
        "Наименование таблицы приемника",
    ],
    "target_field": [
        "T-trg-f",
        "T-col-name",
        "target_field",
        "target field",
        "Наименование поля приемника",
    ],
    "target_table_description": ["T-note", "описание целевой таблицы", "target table description"],
    "target_field_description": [
        "T-col-note",
        "описание целевого поля",
        "target field description",
        "Column Attribute Note",
    ],
    "source_name": ["T-src-main", "T-src-join", "источник данных", "source", "source name"],
    "source_platform": ["T-src-platform", "source platform", "исходная платформа"],
    "source_instance": ["T-src-instance", "source instance", "исходный инстанс"],
    "source_schema": [
        "T-src-schema",
        "source_schema",
        "source schema",
        "исходная схема",
        "схема источника",
    ],
    "source_table": ["T-src", "source_table", "source table", "Наименование таблицы источника"],
    "source_field": ["T-src-f-name", "source_field", "source field", "Наименование поля источника"],
    "join_condition": ["T-src-join-on", "join", "Условия соединения", "Условие соединения"],
    "where_condition": ["T-src-where", "where", "Условия фильтрации", "Условие фильтрации"],
    "group_by": ["T-src-group", "group", "Группировка"],
    "keys": ["ключи", "keys"],
    "history_type": ["T-hist-type", "target_data_hist", "тип историчности", "history type"],
    "history_role": ["T-hist-role", "роль историчности", "history role"],
    "datamart_code": ["codeDatamart", "codeApplication", "Код витрины", "ID Витрины"],
    "refresh_frequency": [
        "target_data_freq",
        "частота обновления",
        "Частота расчёта таблицы",
        "refresh frequency",
    ],
    "data_actuality": ["target_data_relevance", "актуальность данных", "data actuality"],
    "business_description": [
        "Datamart.description_source",
        "Table.description_source",
        "бизнес-описание",
        "business description",
    ],
    "transformation_logic": [
        "T-src-f",
        "техническая логика трансформации",
        "transformation",
        "logic",
    ],
}

TEMPLATE_SHEETS = {"Target columns", "Source columns", "Datamart info", "S2T"}


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
