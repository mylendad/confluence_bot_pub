from pathlib import Path

from app.s2t.parser import S2TParser


def test_parse_csv_s2t(tmp_path: Path) -> None:
    path = tmp_path / "s2t.csv"
    path.write_text(
        "codeDatamart,target_table,target_field,source_table,source_field,transformation\n"
        "DM_CLIENT,client_dm,epk_id,client_src,epk_id,cast to string\n",
        encoding="utf-8",
    )

    result = S2TParser().parse(path, "Витрина клиентов")

    assert len(result.attributes) == 1
    attr = result.attributes[0]
    assert attr.datamart_code == "DM_CLIENT"
    assert attr.target_field == "epk_id"
    assert attr.transformation_logic == "cast to string"


def test_parse_real_5_sheet_template() -> None:
    path = Path("s2t_template_5_sheets_filled.xlsx")

    result = S2TParser().parse(path, "Витрина клиентских операций")

    assert len(result.attributes) == 3
    epk = result.attributes[0]
    assert epk.datamart_code == "DM_CLIENT_OPS"
    assert epk.target_schema == "dds_dm"
    assert epk.target_table == "dm_client_operations"
    assert epk.target_field == "epk_id"
    assert epk.source_field == "epk_id"
    assert epk.transformation_logic == "cast(client_profile.epk_id as varchar(32))"
    assert epk.target_field_description == "Единый профиль клиента"
    assert epk.owner == "ivanov.ii@example.ru"
