"""ทดสอบการตรวจ Tax ID ในฟอร์มและตารางแก้ไข: รับเฉพาะเลขอารบิก 13 หลัก (str.isdigit รับเลขไทยและตัวยกด้วย)"""

import pandas as pd
import pytest

from pages_ui import overview

VALID_TAX_ID = "0105536123456"
BAD_TAX_IDS = ["๐๑๐๕๕๓๖๑๒๓๔๕๖", "010553612345²", "010553612345", "01055361234567", "0105536 23456", "0105536123456\n", "ABCDEFGHIJKLM"]


def form_problems(tax_id: str) -> list[str]:
    return overview.validate_form_input(
        vendor_name="บริษัท ก",
        tax_id=tax_id,
        tel="0812345678",
        email="a@b.co",
        sharepoint_url="",
        purchase_order_number="PO-1",
        pr_run_number="1",
        contact_name="สมชาย",
    )


def test_ascii_tax_id_passes() -> None:
    assert form_problems(VALID_TAX_ID) == []


@pytest.mark.parametrize("tax_id", BAD_TAX_IDS)
def test_form_rejects_non_ascii_or_wrong_length_tax_id(tax_id: str) -> None:
    assert any("TaxID" in problem for problem in form_problems(tax_id))


def update_with_tax_id(value: str) -> dict:
    row = pd.Series({"Status": overview.STATUS_LABEL_PENDING})
    fields, _ignored = overview.build_update_fields({"Tax ID": value}, row)
    return fields


def test_table_edit_accepts_ascii_tax_id_and_empty_clears_it() -> None:
    assert update_with_tax_id(VALID_TAX_ID) == {"tax_id": VALID_TAX_ID}
    assert update_with_tax_id("") == {"tax_id": None}


@pytest.mark.parametrize("tax_id", [value for value in BAD_TAX_IDS if value != "0105536123456\n"])  # ตารางตัดช่องว่างท้ายค่าก่อนตรวจ
def test_table_edit_rejects_non_ascii_or_wrong_length_tax_id(tax_id: str) -> None:
    with pytest.raises(ValueError, match="Tax ID"):
        update_with_tax_id(tax_id)
