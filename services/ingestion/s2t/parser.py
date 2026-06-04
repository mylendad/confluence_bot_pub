from datetime import date
from pathlib import Path

from services.ingestion.s2t.csv_parser import CsvS2TParser
from services.ingestion.s2t.excel_parser import ExcelS2TParser
from services.ingestion.s2t.exceptions import S2TParseError
from services.ingestion.s2t.models import S2TParseResult


class S2TParser:
    """
    Универсальный парсер S2T-файлов.
    Автоматически выбирает нужный парсер (Excel или CSV) на основе расширения файла.
    """
    def __init__(self) -> None:
        """Инициализирует S2TParser, создавая экземпляры специализированных парсеров."""
        self.excel = ExcelS2TParser()
        self.csv = CsvS2TParser()

    def parse(
        self, path: Path, datamart_name: str, s2t_file_date: date | None = None
    ) -> S2TParseResult:
        """
        Парсит S2T-файл по указанному пути.
        :param path: Путь к файлу.
        :param datamart_name: Название витрины данных.
        :param s2t_file_date: Дата файла (опционально).
        :return: Объект S2TParseResult с результатами парсинга.
        """
        suffix = path.suffix.lower()
        if suffix in {".xlsx", ".xls"}:
            return self.excel.parse(path, datamart_name, s2t_file_date)
        if suffix == ".csv":
            return self.csv.parse(path, datamart_name, s2t_file_date)
        raise S2TParseError(f"Unsupported S2T format: {suffix}")
