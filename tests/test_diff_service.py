from app.changes.diff_service import DiffService
from app.s2t.models import S2TAttribute


def test_diff_detects_modified_attribute_logic() -> None:
    old = [
        S2TAttribute(
            datamart_name="dm",
            datamart_code="DM",
            target_schema="dds",
            target_table="t",
            target_field="f",
            transformation_logic="old",
        )
    ]
    new = [old[0].model_copy(update={"transformation_logic": "new"})]

    changes = DiffService().diff_attributes(old, new)

    assert len(changes) == 1
    assert changes[0].change_type == "modified"
