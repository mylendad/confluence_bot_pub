import logging
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from services.ingestion.s2t.models import S2TAttribute, S2TParseIssue, S2TParseResult
from shared.utils.text_utils import normalize_text

logger = logging.getLogger(__name__)

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


class ExcelS2TParser:
    """
    Парсер S2T-файлов в формате Excel (.xlsx, .xls).
    Поддерживает стандартные шаблоны и произвольные таблицы с маппингом колонок.
    """
    def parse(
        self,
        path: Path,
        datamart_name: str,
        s2t_file_date: date | None = None,
    ) -> S2TParseResult:
        """
        Парсит Excel-файл и извлекает атрибуты S2T.
        :param path: Путь к файлу.
        :param datamart_name: Название витрины данных.
        :param s2t_file_date: Дата файла (опционально).
        :return: Объект S2TParseResult.
        """
        result = S2TParseResult()
        workbook = pd.ExcelFile(path)
        sheet_names = set(workbook.sheet_names)

        # Template detection: must have metadata sheets and ONE sheet that looks like S2T
        base_template_sheets = {"Target columns", "Source columns", "Datamart info"}
        if base_template_sheets.issubset(sheet_names):
            s2t_sheet = next(
                (s for s in workbook.sheet_names if s == "S2T" or s.startswith("S2T-") or s.startswith("S2T -")), 
                None
            )
            if s2t_sheet:
                return self._parse_template(
                    workbook, path, datamart_name, s2t_file_date, s2t_sheet_name=s2t_sheet
                )

        for sheet_name in workbook.sheet_names:
            raw = pd.read_excel(workbook, sheet_name=sheet_name, header=None, dtype=str)
            header_row = self._find_header_row(raw)
            if header_row is None:
                result.issues.append(
                    S2TParseIssue(sheet=sheet_name, message="Header row was not found")
                )
                continue
            df = pd.read_excel(workbook, sheet_name=sheet_name, header=header_row, dtype=str)
            mapping = self._build_column_mapping(df.columns)
            if not {"target_field", "target_table"} & set(mapping.values()):
                result.issues.append(
                    S2TParseIssue(sheet=sheet_name, message="No target columns found")
                )
                continue
            result.processed_sheets.append(sheet_name)
            for idx, row in df.iterrows():
                try:
                    payload = self._row_payload(row, mapping)
                    if not any(
                        payload.get(key)
                        for key in ("target_field", "source_field", "transformation_logic")
                    ):
                        continue
                    result.attributes.append(
                        S2TAttribute(
                            datamart_name=datamart_name,
                            s2t_file_name=path.name,
                            s2t_file_date=s2t_file_date,
                            parsed_at=datetime.utcnow(),
                            **payload,
                        )
                    )
                except Exception as exc:
                    result.issues.append(
                        S2TParseIssue(sheet=sheet_name, row_number=int(idx) + 1, message=str(exc))
                    )
        logger.info("Parsed %s S2T attributes from %s", len(result.attributes), path)
        return result

    def _parse_template(
        self,
        workbook: pd.ExcelFile,
        path: Path,
        datamart_name: str,
        s2t_file_date: date | None,
        s2t_sheet_name: str = "S2T",
    ) -> S2TParseResult:
        """
        Парсит файл, соответствующий стандартному шаблону S2T.
        :param workbook: Загруженная книга Excel.
        :param path: Путь к файлу.
        :param datamart_name: Название витрины данных.
        :param s2t_file_date: Дата файла (опционально).
        :param s2t_sheet_name: Название листа с данными S2T.
        :return: Объект S2TParseResult.
        """
        result = S2TParseResult()
        target_notes = self._read_target_notes(workbook)
        datamart_info = self._read_datamart_info(workbook)
        s2t = pd.read_excel(workbook, sheet_name=s2t_sheet_name, header=0, dtype=str)
        mapping = self._build_column_mapping(s2t.columns)
        result.processed_sheets.extend(["Target columns", "Datamart info", s2t_sheet_name])
        for idx, row in s2t.iloc[1:].iterrows():
            try:
                payload = self._row_payload(row, mapping)
                if not any(
                    payload.get(key)
                    for key in ("target_field", "source_field", "transformation_logic")
                ):
                    break
                target_key = self._target_key(payload)
                payload.update(
                    {
                        key: value
                        for key, value in datamart_info.items()
                        if not payload.get(key) and value
                    }
                )
                if target_key in target_notes:
                    for key, value in target_notes[target_key].items():
                        if not payload.get(key) and value:
                            payload[key] = value
                result.attributes.append(
                    S2TAttribute(
                        datamart_name=datamart_name,
                        s2t_file_name=path.name,
                        s2t_file_date=s2t_file_date,
                        parsed_at=datetime.utcnow(),
                        **payload,
                    )
                )
            except Exception as exc:
                result.issues.append(
                    S2TParseIssue(sheet=s2t_sheet_name, row_number=int(idx) + 2, message=str(exc))
                )
        logger.info("Parsed %s template S2T attributes from %s", len(result.attributes), path)
        return result

    def _read_target_notes(
        self, workbook: pd.ExcelFile
    ) -> dict[tuple[str, str, str], dict[str, str | None]]:
        """
        Читает описания целевых полей из листа 'Target columns'.
        :param workbook: Загруженная книга Excel.
        :return: Словарь описаний, где ключ - (schema, table, field).
        """
        df = pd.read_excel(workbook, sheet_name="Target columns", header=0, dtype=str)
        mapping = self._build_column_mapping(df.columns)
        notes: dict[tuple[str, str, str], dict[str, str | None]] = {}
        for _, row in df.iloc[1:].iterrows():
            payload = self._row_payload(row, mapping)
            key = self._target_key(payload)
            if key == ("", "", ""):
                continue
            notes[key] = {
                "target_table_description": payload.get("target_table_description"),
                "target_field_description": payload.get("target_field_description"),
                "target_platform": payload.get("target_platform"),
                "target_instance": payload.get("target_instance"),
            }
        return notes

    def _read_datamart_info(self, workbook: pd.ExcelFile) -> dict[str, str | None]:
        """
        Читает общую информацию о витрине из листа 'Datamart info'.
        :param workbook: Загруженная книга Excel.
        :return: Словарь с общей информацией о витрине.
        """
        df = pd.read_excel(workbook, sheet_name="Datamart info", header=0, dtype=str)
        mapping = self._build_column_mapping(df.columns)
        for _, row in df.iloc[1:].iterrows():
            payload = self._row_payload(row, mapping)
            if any(payload.values()):
                return {
                    "datamart_code": payload.get("datamart_code"),
                    "owner": payload.get("owner"),
                    "business_description": payload.get("business_description"),
                }
        return {}

    @staticmethod
    def _target_key(payload: dict[str, str | None]) -> tuple[str, str, str]:
        """
        Генерирует составной ключ для целевого поля.
        :param payload: Словарь с данными строки S2T.
        :return: Кортеж (schema, table, field).
        """
        return (
            (payload.get("target_schema") or "").strip().lower(),
            (payload.get("target_table") or "").strip().lower(),
            (payload.get("target_field") or "").strip().lower(),
        )

    def _find_header_row(self, df: pd.DataFrame) -> int | None:
        """
        Ищет строку заголовка в таблице по совпадению названий колонок с алиасами.
        :param df: DataFrame для поиска заголовка.
        :return: Индекс строки заголовка или None.
        """
        aliases = {normalize_text(alias) for values in COLUMN_ALIASES.values() for alias in values}
        best_row: int | None = None
        best_score = 0
        for idx, row in df.head(30).iterrows():
            values = {normalize_text(str(value)) for value in row.dropna().tolist()}
            score = len(values & aliases)
            if score > best_score:
                best_score = score
                best_row = int(idx)
        return best_row if best_score >= 2 else None

    def _build_column_mapping(self, columns: Any) -> dict[str, str]:
        """
        Строит карту соответствия названий колонок в файле внутренним полям модели.
        :param columns: Список названий колонок из файла.
        :return: Словарь маппинга {название_в_файле: внутреннее_название}.
        """
        mapping: dict[str, str] = {}
        alias_lookup = {
            normalize_text(alias): field
            for field, aliases in COLUMN_ALIASES.items()
            for alias in aliases
        }
        for column in columns:
            field = alias_lookup.get(normalize_text(str(column)))
            if field:
                mapping[str(column)] = field
        return mapping

    @staticmethod
    def _row_payload(row: pd.Series, mapping: dict[str, str]) -> dict[str, str | None]:
        """
        Извлекает данные строки в виде словаря на основе маппинга колонок.
        :param row: Строка данных из pandas.
        :param mapping: Словарь маппинга колонок.
        :return: Словарь с данными строки.
        """
        payload: dict[str, str | None] = {}
        for column, field in mapping.items():
            value = row.get(column)
            if pd.isna(value):
                payload[field] = None
            else:
                text = str(value).strip()
                payload[field] = text or None
        return payload
