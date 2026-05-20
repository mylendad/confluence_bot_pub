from datetime import date
from pathlib import Path

import pandas as pd

from app.s2t.excel_parser import ExcelS2TParser
from app.s2t.models import S2TAttribute, S2TParseIssue, S2TParseResult


class CsvS2TParser:
    def parse(
        self, path: Path, datamart_name: str, s2t_file_date: date | None = None
    ) -> S2TParseResult:
        df = pd.read_csv(path, dtype=str)
        helper = ExcelS2TParser()
        mapping = helper._build_column_mapping(df.columns)
        result = S2TParseResult(processed_sheets=[path.name])
        for idx, row in df.iterrows():
            try:
                payload = helper._row_payload(row, mapping)
                if payload:
                    result.attributes.append(
                        S2TAttribute(
                            datamart_name=datamart_name,
                            s2t_file_name=path.name,
                            s2t_file_date=s2t_file_date,
                            **payload,
                        )
                    )
            except Exception as exc:
                result.issues.append(
                    S2TParseIssue(sheet=path.name, row_number=int(idx) + 1, message=str(exc))
                )
        return result
