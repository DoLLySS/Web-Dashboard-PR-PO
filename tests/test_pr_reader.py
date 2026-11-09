"""ทดสอบการอ่านค่าจากไฟล์ PR และกุญแจ PR เดียวกัน (utils/pr_reader.py)"""

import os
from pathlib import Path

import pytest

from pr_fixtures import build_pdf, make_pr_excel, make_pr_pdf, make_text_pdf, pr_form_items
from utils.pr_reader import (
    build_identity_key,
    read_pdf_sections,
    read_pr_excel,
    summarize_items,
)

ONE_ITEM = [("Notebook Lenovo ThinkPad E14 G7", "29,500.00")]
TWO_ITEMS = [("Notebook Lenovo ThinkPad E14 G7", "29,500.00"), ("Monitor Dell U2724DE", "14,500.00")]


def test_pdf_reads_the_five_values() -> None:
    """Date/Description/Price/Company/Tel ตรงกับตำแหน่งในฟอร์ม และไม่สับกับ Tel ของผู้ร้องขอ"""
    sections = read_pdf_sections(make_pr_pdf(ONE_ITEM))

    assert len(sections) == 1 and sections[0].page_numbers == [1]
    document = sections[0].document
    assert document is not None
    assert document.description == "Notebook Lenovo ThinkPad E14 G7"
    assert document.unit_price == 29500.0
    assert document.vendor == "Alpha Trading Co Ltd"
    assert document.tel == "092-849-6930"  # ไม่ใช่ 099-0547405 ของผู้ร้องขอ
    assert document.date == "2026-03-19"


def test_pdf_multiple_items_are_abbreviated_and_prices_summed() -> None:
    """หลายรายการ: Description = รายการแรก (+N รายการ) และ Price = ผลรวม Unit Price"""
    document = read_pdf_sections(make_pr_pdf(TWO_ITEMS))[0].document

    assert document is not None
    assert document.description == "Notebook Lenovo ThinkPad E14 G7 (+1 รายการ)"
    assert document.item_count == 2
    assert document.unit_price == 44000.0


def test_excel_and_pdf_of_same_pr_share_identity_key() -> None:
    """Excel กับ PDF ของ PR เดียวกันได้ค่าและกุญแจเดียวกัน (จึงเข้าโฟลเดอร์เดียวกันอัตโนมัติ)"""
    pdf_document = read_pdf_sections(make_pr_pdf(TWO_ITEMS))[0].document
    excel_document = read_pr_excel(make_pr_excel([("Notebook Lenovo ThinkPad E14 G7", 29500), ("Monitor Dell U2724DE", 14500)]))

    assert pdf_document is not None and excel_document is not None
    assert excel_document.description == pdf_document.description
    assert excel_document.unit_price == pdf_document.unit_price == 44000.0
    assert excel_document.date == pdf_document.date == "2026-03-19"
    assert excel_document.identity_key == pdf_document.identity_key is not None


def test_signature_date_falls_back_to_next_signer() -> None:
    """ช่องผู้ร้องขอว่าง ใช้ช่องผู้ตรวจสอบ"""
    document = read_pdf_sections(make_pr_pdf(ONE_ITEM, dates=("", "20-Mar-2026", "21-Mar-2026")))[0].document
    assert document is not None and document.date == "2026-03-20"


def test_missing_tel_gives_no_identity_key() -> None:
    """Tel ว่าง = ไม่มีกุญแจ (ไม่เดา ไม่รวมกับแถวเดิม) และบอกว่าช่องไหนหาย"""
    document = read_pdf_sections(make_pr_pdf(ONE_ITEM, tel=None))[0].document
    assert document is not None
    assert document.tel == ""
    assert document.identity_key is None
    assert document.missing_key_fields == ["เบอร์โทรศัพท์ (Tel.)"]


def test_identity_key_ignores_thai_vowel_spelling_and_phone_format() -> None:
    """PDF กับ Excel สะกดสระไทยต่างกันได้ (เทียบเฉพาะพยัญชนะ) และเบอร์ใส่ขีดต่างกันได้"""
    excel_key = build_identity_key("Notebook X", "บริษัท แอด อิน บิซิเนส จำกัด", "092-849-6930")
    pdf_key = build_identity_key("notebook  x", "บรษิ ัท แอด อนิ บซิ เินส จ ำกดั", "0928496930")
    assert excel_key == pdf_key and excel_key is not None


def test_identity_key_differs_when_any_field_differs() -> None:
    base = build_identity_key("Notebook X", "Alpha Co", "0912345678")
    assert base != build_identity_key("Notebook Y", "Alpha Co", "0912345678")
    assert base != build_identity_key("Notebook X", "Beta Co", "0912345678")
    assert base != build_identity_key("Notebook X", "Alpha Co", "0912345679")


def test_identity_key_requires_all_three() -> None:
    assert build_identity_key("", "Alpha Co", "0912345678") is None
    assert build_identity_key("Notebook X", "  ", "0912345678") is None
    assert build_identity_key("Notebook X", "Alpha Co", "-") is None


def test_summarize_items() -> None:
    assert summarize_items([]) == ""
    assert summarize_items(["A  b", ""]) == "A b"
    assert summarize_items(["A", "B", "C"]) == "A (+2 รายการ)"


def test_pdf_pages_split_by_form_and_continuation_pages_follow_previous() -> None:
    """หน้าที่เป็นฟอร์ม PR เริ่ม PR ใหม่ หน้าอื่น (อ่านเลขไม่ได้) เป็นของ PR ก่อนหน้า ไม่ถามผู้ใช้"""
    pdf = build_pdf(
        [
            pr_form_items(ONE_ITEM, vendor="Alpha Co"),
            [(40, 100, "Terms and conditions")],
            pr_form_items([("Printer Beta Y200", "9,000.00")], vendor="Beta Co"),
        ]
    )
    sections = read_pdf_sections(pdf)

    assert [section.page_numbers for section in sections] == [[1, 2], [3]]
    assert [section.document.vendor for section in sections if section.document] == ["Alpha Co", "Beta Co"]


def test_pdf_pages_before_first_form_join_first_pr() -> None:
    pdf = build_pdf([[(40, 100, "Cover page")], pr_form_items(ONE_ITEM)])
    sections = read_pdf_sections(pdf)
    assert [section.page_numbers for section in sections] == [[1, 2]]


def test_non_form_pdf_and_broken_files_are_not_prs() -> None:
    """ไฟล์ที่ไม่ใช่ฟอร์ม PR / ไฟล์เสีย ไม่ทำให้ล้ม และได้ document = None"""
    assert read_pdf_sections(make_text_pdf("just a quotation"))[0].document is None
    assert read_pdf_sections(b"not a pdf")[0].document is None
    assert read_pr_excel(b"not an excel") is None


@pytest.mark.skipif(
    not os.environ.get("PR_SAMPLE_DIR"), reason="ตั้ง PR_SAMPLE_DIR เป็นโฟลเดอร์ไฟล์ PR จริงเพื่อทดสอบกับไฟล์จริง (อ่านอย่างเดียว)"
)
def test_real_sample_files_agree() -> None:
    """ไฟล์ PR จริง (PDF กับ Excel ของ PR เดียวกัน) ต้องได้ค่าและกุญแจตรงกัน"""
    folder = Path(os.environ["PR_SAMPLE_DIR"])
    pdf_path = next(folder.glob("*signed.pdf"))
    excel_path = next(folder.glob("*.xlsx"))
    pdf_document = read_pdf_sections(pdf_path.read_bytes())[0].document
    excel_document = read_pr_excel(excel_path.read_bytes())

    assert pdf_document is not None and excel_document is not None
    assert pdf_document.identity_key is not None
    assert pdf_document.identity_key == excel_document.identity_key
    assert pdf_document.date == excel_document.date
