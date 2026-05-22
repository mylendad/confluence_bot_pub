from datetime import date
from pathlib import Path

from app.s2t.csv_parser import CsvS2TParser
from app.s2t.excel_parser import ExcelS2TParser
from app.s2t.exceptions import S2TParseError
from app.s2t.html_parser import HtmlS2TParser
from app.s2t.models import S2TParseResult


class S2TParser:
    def __init__(self) -> None:
        self.excel = ExcelS2TParser()
        self.csv = CsvS2TParser()
        self.html = HtmlS2TParser()

    def parse(
        self, path: Path, datamart_name: str, s2t_file_date: date | None = None
    ) -> S2TParseResult:
        suffix = path.suffix.lower()
        if suffix in {".xlsx", ".xls"}:
            return self.excel.parse(path, datamart_name, s2t_file_date)
        if suffix == ".csv":
            return self.csv.parse(path, datamart_name, s2t_file_date)
        if suffix in {"", ".html", ".htm"}:
            return self.html.parse(path, datamart_name, s2t_file_date)
        raise S2TParseError(f"Unsupported S2T format: {suffix}")
