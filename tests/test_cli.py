from pathlib import Path

import httpx
import pytest

from app.changes.history_repository import HistoryRepository
from app.cli import _raise_confluence_cli_error, parse_s2t
from app.config import get_settings
from app.storage.metadata_repository import MetadataRepository
from app.storage.sqlite import SQLite


def _write_s2t(path: Path, target_fields: list[str]) -> None:
    rows = [
        "codeDatamart,target_table,target_field,UserName",
        *[
            f"DM_CLIENT,client_dm,{field},owner@example.ru"
            for field in target_fields
        ],
    ]
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_parse_s2t_records_changes_on_reparse(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setenv("SQLITE_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("VECTOR_STORE_DIR", str(tmp_path / "vector_store"))
    get_settings.cache_clear()

    try:
        base_path = tmp_path / "base.csv"
        updated_path = tmp_path / "updated.csv"
        _write_s2t(base_path, ["epk_id"])
        _write_s2t(updated_path, ["epk_id", "new_client_status_cd"])

        parse_s2t(base_path, datamart="Витрина клиентов")
        assert "Detected changes: 0" in capsys.readouterr().out

        parse_s2t(updated_path, datamart="Витрина клиентов")
        assert "Detected changes: 1" in capsys.readouterr().out

        db = SQLite(tmp_path / "app.db")
        changes = HistoryRepository(db).list_changes(datamart_name="Витрина клиентов")
        attributes = MetadataRepository(db).list_attributes(datamart_name="Витрина клиентов")

        assert len(changes) == 1
        assert changes[0].change_type == "added"
        assert changes[0].entity_name == "new_client_status_cd"
        assert sorted(attr.target_field for attr in attributes) == [
            "epk_id",
            "new_client_status_cd",
        ]
    finally:
        get_settings.cache_clear()


def test_confluence_connect_error_is_reported_as_cli_hint() -> None:
    with pytest.raises(Exception) as exc_info:
        _raise_confluence_cli_error(
            "https://confluence.example.ru",
            httpx.ConnectError("[Errno -3] Temporary failure in name resolution"),
        )

    message = str(exc_info.value)
    assert "CONFLUENCE_BASE_URL" in message
    assert "DNS/VPN/прокси" in message
    assert "Temporary failure in name resolution" in message
