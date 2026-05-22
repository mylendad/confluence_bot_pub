import logging
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from app.s2t.models import S2TAttribute, S2TParseIssue, S2TParseResult
from app.s2t.parser_base import BaseS2TParser

logger = logging.getLogger(__name__)


class HtmlS2TParser(BaseS2TParser):
    def parse(
        self,
        path: Path,
        datamart_name: str,
        s2t_file_date: date | None = None,
    ) -> S2TParseResult:
        result = S2TParseResult()
        try:
            tables = pd.read_html(path, header=0, dtype=str, encoding="utf-8")
        except Exception as exc:
            result.issues.append(S2TParseIssue(message=f"Cannot read HTML file: {exc}"))
            return result

        for i, df in enumerate(tables):
            sheet_name = f"table_{i}"
            mapping = self._build_column_mapping(df.columns)
            if not {"target_field", "target_table"} & set(mapping.values()):
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
