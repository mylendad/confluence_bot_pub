from typing import Any

import pandas as pd

from app.s2t.models import COLUMN_ALIASES
from app.utils.text_utils import normalize_text


class BaseS2TParser:
    def _find_header_row(self, df: pd.DataFrame) -> int | None:
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
        payload: dict[str, str | None] = {}
        for column, field in mapping.items():
            value = row.get(column)
            if pd.isna(value):
                payload[field] = None
            else:
                text = str(value).strip()
                payload[field] = text or None
        return payload
