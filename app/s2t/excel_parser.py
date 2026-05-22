import logging
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from app.s2t.models import S2TAttribute, S2TParseIssue, S2TParseResult, TEMPLATE_SHEETS
from app.s2t.parser_base import BaseS2TParser

logger = logging.getLogger(__name__)


class ExcelS2TParser(BaseS2TParser):
    def parse(
        self,
        path: Path,
        datamart_name: str,
        s2t_file_date: date | None = None,
    ) -> S2TParseResult:
        result = S2TParseResult()
        try:
            workbook = pd.ExcelFile(path)
        except Exception as exc:
            result.issues.append(S2TParseIssue(message=f"Cannot open Excel file: {exc}"))
            return result

        if TEMPLATE_SHEETS.issubset(set(workbook.sheet_names)):
            return self._parse_template(workbook, path, datamart_name, s2t_file_date)

        for sheet_name in workbook.sheet_names:
            try:
                raw = pd.read_excel(workbook, sheet_name=sheet_name, header=None, dtype=str)
            except Exception as exc:
                result.issues.append(
                    S2TParseIssue(sheet=sheet_name, message=f"Cannot read sheet: {exc}")
                )
                continue

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
    ) -> S2TParseResult:
        result = S2TParseResult()
        target_notes = self._read_target_notes(workbook)
        datamart_info = self._read_datamart_info(workbook)
        s2t = pd.read_excel(workbook, sheet_name="S2T", header=0, dtype=str)
        mapping = self._build_column_mapping(s2t.columns)
        result.processed_sheets.extend(["Target columns", "Datamart info", "S2T"])
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
                    S2TParseIssue(sheet="S2T", row_number=int(idx) + 2, message=str(exc))
                )
        logger.info("Parsed %s template S2T attributes from %s", len(result.attributes), path)
        return result

    def _read_target_notes(
        self, workbook: pd.ExcelFile
    ) -> dict[tuple[str, str, str], dict[str, str | None]]:
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
        return (
            (payload.get("target_schema") or "").strip().lower(),
            (payload.get("target_table") or "").strip().lower(),
            (payload.get("target_field") or "").strip().lower(),
        )
