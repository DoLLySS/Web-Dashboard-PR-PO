"""ทดสอบการอัปโหลดอัตโนมัติจากไฟล์ PR (utils/upload_processor.py) บนฐานข้อมูลและโฟลเดอร์ชั่วคราว"""

from datetime import date
from pathlib import Path
from typing import Optional

import pytest

import utils.upload_processor as processor
from data.database import STATUS_PENDING, count_transactions, get_transactions
from pages_ui.overview import clean_pr_file_name, find_pr_date_in_file_names, find_rows_outside_range
from pr_fixtures import make_pr_excel, make_pr_pdf, make_text_pdf
from utils.submit_pipeline import SubmitResult
from utils.upload_processor import KIND_ATTACHED, KIND_BLOCKED, KIND_CREATED, UploadReport, process_upload

TWO_ITEMS = [("Notebook Lenovo ThinkPad E14 G7", "29,500.00"), ("Monitor Dell U2724DE", "14,500.00")]
EXCEL_TWO_ITEMS = [("Notebook Lenovo ThinkPad E14 G7", 29500), ("Monitor Dell U2724DE", 14500)]
PDF_NAME = "20260319 PR_Addin_NB Lenovo-signed.pdf"
EXCEL_NAME = "PR_Addin_NB Lenovo.xlsx"
# ระบบเก็บไฟล์โดยเปลี่ยนช่องว่างในชื่อเป็น _
STORED_PDF = PDF_NAME.replace(" ", "_")
STORED_EXCEL = EXCEL_NAME.replace(" ", "_")


def upload(files: list[tuple[str, bytes]]) -> UploadReport:
    """อัปโหลดแบบที่หน้าจอเรียก (Item = Notebook, ยังไม่มีใบกำกับภาษี)"""
    return process_upload(
        files, "Notebook", STATUS_PENDING, clean_pr_file_name, lambda name: find_pr_date_in_file_names([name])
    )


def folders_with_files(directory: Path) -> dict[str, set[str]]:
    """{โฟลเดอร์ ปี/เดือน/วัน/ชื่อ: ชื่อไฟล์ในนั้น}"""
    found: dict[str, set[str]] = {}
    for path in directory.rglob("*"):
        if path.is_file():
            found.setdefault(path.parent.relative_to(directory).as_posix(), set()).add(path.name)
    return found


def test_pr_pdf_creates_row_immediately_with_values_from_file(isolated_storage: Path) -> None:
    """อัปโหลดไฟล์ PR แล้วได้แถวใหม่ทันที ค่าตรงไฟล์ และโฟลเดอร์ตามวันที่ในไฟล์ + ชื่อไฟล์ PR ตัดคำ PR"""
    report = upload([(PDF_NAME, make_pr_pdf(TWO_ITEMS))])

    assert [item.kind for item in report.items] == [KIND_CREATED]
    rows = get_transactions()
    assert len(rows) == 1
    row = rows[0]
    assert row["date"] == "2026-03-19"
    assert row["description"] == "Notebook Lenovo ThinkPad E14 G7 (+1 รายการ)"
    assert row["total_price"] == 44000.0
    assert row["vendor"] == "Alpha Trading Co Ltd"
    assert row["tel"] == "092-849-6930"
    assert row["category"] == "Notebook"
    assert set(folders_with_files(isolated_storage)) == {"2026/Mar/19/20260319_Addin_NB Lenovo"}


def test_excel_and_pdf_of_same_pr_go_to_one_row_and_one_folder(isolated_storage: Path) -> None:
    """Excel กับ PDF ของ PR เดียวกันในชุดเดียวกัน = แถวเดียว โฟลเดอร์เดียว โดยไม่ต้องเลือก"""
    report = upload([(EXCEL_NAME, make_pr_excel(EXCEL_TWO_ITEMS)), (PDF_NAME, make_pr_pdf(TWO_ITEMS))])

    assert [item.kind for item in report.items] == [KIND_CREATED, KIND_ATTACHED]
    assert count_transactions() == 1
    folders = folders_with_files(isolated_storage)
    assert len(folders) == 1
    assert set(next(iter(folders.values()))) == {STORED_EXCEL, STORED_PDF}


def test_later_upload_of_same_pr_goes_to_existing_folder(isolated_storage: Path) -> None:
    """PR เดียวกันที่อัปโหลดทีหลัง (คนละครั้ง) เข้าโฟลเดอร์เดิม ไม่สร้างแถวซ้ำ อัปไฟล์เดิมซ้ำไม่ทำสำเนา"""
    upload([(PDF_NAME, make_pr_pdf(TWO_ITEMS))])
    second = upload([(EXCEL_NAME, make_pr_excel(EXCEL_TWO_ITEMS))])
    third = upload([(PDF_NAME, make_pr_pdf(TWO_ITEMS))])

    assert second.items[0].kind == KIND_ATTACHED and third.items[0].kind == KIND_ATTACHED
    assert third.items[0].result is not None and third.items[0].result.attached_file_names == []
    assert count_transactions() == 1
    folders = folders_with_files(isolated_storage)
    assert len(folders) == 1 and set(next(iter(folders.values()))) == {STORED_PDF, STORED_EXCEL}


@pytest.mark.parametrize(
    "variant",
    [
        {"tel": "081-111-2222"},
        {"vendor": "Beta Trading Co Ltd"},
        {"items": [("Printer Epson L3250", "5,000.00")]},
    ],
)
def test_any_one_of_three_fields_different_makes_new_row(isolated_storage: Path, variant: dict) -> None:
    """Description / Company / Tel ต่างกันแม้ช่องเดียว = ไม่ใช่ PR เดียวกัน ได้แถวใหม่และโฟลเดอร์ใหม่"""
    upload([(PDF_NAME, make_pr_pdf(TWO_ITEMS))])
    items = variant.pop("items", TWO_ITEMS)
    report = upload([("20260320 PR_Other-signed.pdf", make_pr_pdf(items, **variant))])

    assert report.items[0].kind == KIND_CREATED
    assert count_transactions() == 2
    assert len(folders_with_files(isolated_storage)) == 2


def test_unreadable_key_field_creates_new_row_with_warning_never_merges(isolated_storage: Path) -> None:
    """Tel อ่านไม่ได้ = สร้างแถวใหม่ + เตือน แม้อัปซ้ำก็ไม่รวม (ไม่เดา)"""
    pdf = make_pr_pdf(TWO_ITEMS, tel=None)
    first = upload([(PDF_NAME, pdf)])
    second = upload([(PDF_NAME, pdf)])

    assert first.items[0].kind == second.items[0].kind == KIND_CREATED
    assert count_transactions() == 2
    assert any("Tel" in warning for warning in first.items[0].warnings)


def test_pdf_with_two_prs_makes_two_rows(isolated_storage: Path) -> None:
    """PDF หลาย PR แยกตามฟอร์มอัตโนมัติ ได้แถวละ PR (หน้าที่ไม่ใช่ฟอร์มเป็นของ PR ก่อนหน้า)"""
    from pr_fixtures import build_pdf, pr_form_items

    pdf = build_pdf(
        [
            pr_form_items([("Notebook Alpha X100", "10,000.00")], vendor="Alpha Co"),
            [(40, 100, "Terms and conditions")],
            pr_form_items([("Printer Beta Y200", "9,000.00")], vendor="Beta Co"),
        ]
    )
    report = upload([("20260319 PR_bundle.pdf", pdf)])

    assert [item.kind for item in report.items] == [KIND_CREATED, KIND_CREATED]
    assert {row["vendor"] for row in get_transactions()} == {"Alpha Co", "Beta Co"}


def test_unreadable_pr_file_creates_row_from_file_name_with_warning(isolated_storage: Path) -> None:
    """ไฟล์ชื่อ PR ที่อ่านค่าไม่ได้ (เช่น สแกน) ยังสร้างแถวจากชื่อไฟล์ พร้อมเตือน ไม่ล้ม"""
    report = upload([("20260318 PR_Scan_Toner.pdf", make_text_pdf(""))])

    assert report.items[0].kind == KIND_CREATED
    assert report.items[0].warnings
    row = get_transactions()[0]
    assert row["date"] == "2026-03-18" and row["description"] == "Scan_Toner"


def test_non_pr_file_matches_pr_by_content_and_goes_to_its_folder(isolated_storage: Path) -> None:
    """ใบเสนอราคาที่เนื้อหาตรงกับ PR (อัปพร้อมกันหรือทีหลัง) เข้าโฟลเดอร์ของ PR นั้นอัตโนมัติ"""
    quote = make_text_pdf("Quotation Notebook Lenovo ThinkPad E14 G7 Monitor Dell U2724DE")
    report = upload([("ใบเสนอราคา.pdf", quote), (PDF_NAME, make_pr_pdf(TWO_ITEMS))])  # ไฟล์อื่นอยู่ก่อนก็ยังจับคู่ได้

    assert {item.file_name: item.kind for item in report.items} == {PDF_NAME: KIND_CREATED, "ใบเสนอราคา.pdf": KIND_ATTACHED}
    folders = folders_with_files(isolated_storage)
    assert len(folders) == 1 and "ใบเสนอราคา.pdf" in next(iter(folders.values()))

    later = upload([("ใบเสนอราคา2.pdf", quote)])
    assert later.items[0].kind == KIND_ATTACHED and count_transactions() == 1


def test_non_pr_file_without_match_is_blocked_but_others_still_save(isolated_storage: Path) -> None:
    """ไฟล์ที่ไม่ใช่ PR และจับคู่ไม่ได้ = ไม่บันทึกพร้อมเหตุผล ส่วนไฟล์อื่นในชุดยังบันทึก"""
    report = upload([("random.pdf", make_text_pdf("unrelated document")), (PDF_NAME, make_pr_pdf(TWO_ITEMS))])

    by_name = {item.file_name: item for item in report.items}
    assert by_name["random.pdf"].kind == KIND_BLOCKED and by_name["random.pdf"].reason
    assert by_name[PDF_NAME].kind == KIND_CREATED
    assert "random.pdf" not in {name for names in folders_with_files(isolated_storage).values() for name in names}


def test_failure_of_one_item_does_not_roll_back_others(isolated_storage: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """สร้างแถวของไฟล์หนึ่งล้มเหลว ไฟล์อื่นยังบันทึกอยู่"""
    real_submit = processor.submit_record

    def flaky_submit(fields, files, *args, **kwargs) -> SubmitResult:
        if files[0][0].startswith("bad"):
            return SubmitResult(error="จำลองว่าบันทึกไม่ได้")
        return real_submit(fields, files, *args, **kwargs)

    monkeypatch.setattr(processor, "submit_record", flaky_submit)
    report = upload(
        [("bad PR.pdf", make_pr_pdf(TWO_ITEMS, vendor="Bad Co")), (PDF_NAME, make_pr_pdf(TWO_ITEMS, vendor="Good Co"))]
    )

    assert [item.kind for item in report.items] == [KIND_BLOCKED, KIND_CREATED]
    assert [row["vendor"] for row in get_transactions()] == ["Good Co"]


def test_new_row_outside_date_filter_is_reported(isolated_storage: Path) -> None:
    """แถวใหม่ใช้วันที่ในไฟล์ จึงเตือนได้เมื่ออยู่นอกช่วงตัวกรอง (กลไกเดิมของปุ่ม "แสดงแถวนี้")"""
    report = upload([(PDF_NAME, make_pr_pdf(TWO_ITEMS))])
    saved = [(result.transaction_id, result.record_date) for result in report.saved_results]

    assert find_rows_outside_range(saved, date(2026, 4, 1), date(2026, 4, 30)) == [(saved[0][0], date(2026, 3, 19))]
    assert find_rows_outside_range(saved, date(2026, 3, 1), date(2026, 3, 31)) == []


def test_scanned_non_pr_file_gets_distinct_reason_and_rows_reported_once(isolated_storage: Path) -> None:
    """ไฟล์สแกน (ไม่มีข้อความ) ถูกบล็อกด้วยเหตุผลเรื่องอ่านไม่ได้ ไม่ใช่ "ไม่พบ PR" และแถวเดียวกันแจ้งเตือนครั้งเดียว"""
    quote = make_text_pdf("Quotation Notebook Lenovo ThinkPad E14 G7 Monitor Dell U2724DE")
    report = upload([(PDF_NAME, make_pr_pdf(TWO_ITEMS)), ("scan.pdf", make_text_pdf("")), ("quote.pdf", quote)])

    by_name = {item.file_name: item for item in report.items}
    assert by_name["scan.pdf"].kind == KIND_BLOCKED and "OCR" in by_name["scan.pdf"].reason
    assert by_name["quote.pdf"].kind == KIND_ATTACHED
    assert len(report.results) == 2 and len(report.saved_results) == 1
