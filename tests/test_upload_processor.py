"""ทดสอบการอัปโหลดอัตโนมัติจากไฟล์ PR (utils/upload_processor.py) บนฐานข้อมูลและโฟลเดอร์ชั่วคราว"""

from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pandas as pd
import pytest

import utils.upload_processor as processor
from config.constants import OVERDUE_RULE
from data.database import (
    STATUS_PENDING,
    STATUS_RECEIVED,
    _bump_data_version,
    _get_connection,
    count_transactions,
    get_transactions,
)
import pages_ui.overview as overview
from pages_ui.overview import (
    clean_pr_file_name,
    find_overdue_transactions,
    find_pr_date_in_file_names,
    find_rows_outside_range,
)
from pr_fixtures import make_pr_excel, make_pr_pdf, make_text_pdf
from utils.local_storage import list_folder_files
from utils.submit_pipeline import SubmitResult
from utils.upload_processor import (
    KIND_ATTACHED,
    KIND_BLOCKED,
    KIND_CREATED,
    INFERRED_INVOICE_STATUS_WARNING,
    TAX_INVOICE_STATUS_WARNING,
    UploadReport,
    attach_invoice_to_row,
    is_tax_invoice,
    process_upload,
)

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
    assert row["total_price"] == 47080.0  # ราคารวมหลังภาษี (Grand Total)
    assert row["unit_price"] == 44000.0
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


def test_image_named_after_second_item_goes_to_that_pr_folder(isolated_storage: Path) -> None:
    """ภาพชื่อรายการที่ 2 เข้าโฟลเดอร์ PR แม้ Description ในตารางย่อเหลือรายการแรก"""
    report = upload([(PDF_NAME, make_pr_pdf(TWO_ITEMS)), ("Monitor Dell U2724DE.jpg", b"image bytes")])

    assert [item.kind for item in report.items] == [KIND_CREATED, KIND_ATTACHED]
    assert folders_with_files(isolated_storage) == {
        "2026/Mar/19/20260319_Addin_NB Lenovo": {STORED_PDF, "Monitor_Dell_U2724DE.jpg"}
    }
    assert count_transactions() == 1


def test_tax_invoice_with_second_item_in_text_goes_to_that_pr_folder(isolated_storage: Path) -> None:
    """ใบกำกับภาษีอ้างอิงชื่อรายการในเนื้อหา แม้ไม่มี Tax ID ตรงและชื่อไฟล์ไม่บอกอะไร"""
    other_pr = make_pr_pdf([("Printer Canon G3010", "9,000.00")], vendor="Beta Co")
    upload([(PDF_NAME, make_pr_pdf(TWO_ITEMS)), ("20260320 PR_Beta_Printer.pdf", other_pr)])

    report = upload([("TAX-0001.pdf", make_text_pdf("Tax Invoice Monitor Dell U2724DE 14,500.00"))])

    assert [item.kind for item in report.items] == [KIND_ATTACHED]
    assert "TAX-0001.pdf" in folders_with_files(isolated_storage)["2026/Mar/19/20260319_Addin_NB Lenovo"]


def test_image_matching_items_of_two_prs_equally_is_blocked(isolated_storage: Path) -> None:
    """ชื่อรายการตรงสอง PR เท่ากัน = ไม่เดา"""
    upload(
        [
            ("20260319 PR_A.pdf", make_pr_pdf(TWO_ITEMS)),
            ("20260319 PR_B.pdf", make_pr_pdf([("Keyboard X", "100.00"), ("Monitor Dell U2724DE", "14,500.00")], vendor="Beta Co")),
        ]
    )
    report = upload([("Monitor Dell U2724DE.jpg", b"image bytes")])
    assert [item.kind for item in report.items] == [KIND_BLOCKED]


def test_image_with_only_one_word_of_item_is_blocked(isolated_storage: Path) -> None:
    """คำเดียวไม่พอยืนยัน กันจับผิดแถว"""
    upload([(PDF_NAME, make_pr_pdf(TWO_ITEMS))])
    report = upload([("Monitor.jpg", b"image bytes")])
    assert [item.kind for item in report.items] == [KIND_BLOCKED]


def test_list_folder_files_shows_real_files_and_stays_inside_uploads(isolated_storage: Path) -> None:
    """เห็นไฟล์ที่อยู่ในโฟลเดอร์จริงแม้แถวไม่ได้อ้างถึง ไม่รวมโฟลเดอร์ย่อย และไม่หลุดออกนอกที่เก็บ"""
    folder = isolated_storage / "2026" / "Mar" / "19" / "A"
    (folder / "sub").mkdir(parents=True)
    (folder / "b.jpg").write_bytes(b"x")
    (folder / "a.pdf").write_bytes(b"x")

    assert [path.name for path in list_folder_files(["2026", "Mar", "19", "A"])] == ["a.pdf", "b.jpg"]
    assert list_folder_files(["..", ".."]) == []
    assert list_folder_files(["2026", "ไม่มีโฟลเดอร์นี้"]) == []
    assert list_folder_files(None) == []


# ---------------------------------------------------------------------------
# ใบกำกับภาษีเปลี่ยนสถานะแถวเป็น Completed
# ---------------------------------------------------------------------------


def only_row_status() -> str:
    rows = get_transactions()
    assert len(rows) == 1
    return rows[0]["invoice_status"]


@pytest.mark.parametrize(
    "name, text",
    [
        ("TAX-0001.pdf", "Tax Invoice Monitor Dell U2724DE"),
        ("Tax_Invoice_Monitor_Dell_U2724DE.pdf", "Monitor Dell U2724DE"),
    ],
)
def test_tax_invoice_text_or_name_marks_row_completed(isolated_storage: Path, name: str, text: str) -> None:
    upload([(PDF_NAME, make_pr_pdf(TWO_ITEMS))])
    assert only_row_status() == STATUS_PENDING

    report = upload([(name, make_text_pdf(text))])

    assert [item.kind for item in report.items] == [KIND_ATTACHED]
    assert only_row_status() == STATUS_RECEIVED
    assert TAX_INVOICE_STATUS_WARNING in report.items[0].warnings


def test_scanned_tax_invoice_named_in_thai_marks_row_completed(isolated_storage: Path) -> None:
    """ไฟล์ภาพไม่มีข้อความ: ใช้คำในชื่อไฟล์ (ต้องมีชื่อรุ่นเพื่อจับคู่แถว)"""
    upload([(PDF_NAME, make_pr_pdf(TWO_ITEMS))])
    upload([("ใบกำกับภาษี Monitor Dell U2724DE.jpg", b"image bytes")])
    assert only_row_status() == STATUS_RECEIVED


@pytest.mark.parametrize(
    "name, data",
    [
        ("INV_0001.pdf", make_text_pdf("Monitor Dell U2724DE")),
        ("Monitor Dell U2724DE.jpg", b"image bytes"),
        ("INV_0002.pdf", make_text_pdf("Monitor Dell U2724DE " + "x " * 300 + "Quotation")),
    ],
)
def test_file_matching_pr_without_invoice_word_marks_row_completed(isolated_storage: Path, name: str, data: bytes) -> None:
    """จับคู่กับ PR ได้และไม่ใช่เอกสารอื่น = ถือเป็นใบกำกับ (คำยกเว้นที่อยู่เลยหัวเอกสารไม่นับ) แม้ไม่มีคำว่าใบกำกับ"""
    upload([(PDF_NAME, make_pr_pdf(TWO_ITEMS))])

    report = upload([(name, data)])

    assert [item.kind for item in report.items] == [KIND_ATTACHED]
    assert only_row_status() == STATUS_RECEIVED
    # ต้องบอกชัดว่าเดาจากการจับคู่ ไม่ได้พบคำว่าใบกำกับ และบอกวิธีแก้กลับ
    assert INFERRED_INVOICE_STATUS_WARNING in report.items[0].warnings
    assert TAX_INVOICE_STATUS_WARNING not in report.items[0].warnings


def test_status_set_by_inferred_invoice_can_be_reverted_in_table() -> None:
    """ข้อความแจ้งผู้ใช้สัญญาว่าแก้กลับเป็น Pending ในตารางได้"""
    label = overview.TABLE_COLUMNS["invoice_status"]
    row = pd.Series({label: overview.STATUS_LABEL_COMPLETED})

    fields, ignored = overview.build_update_fields({label: overview.STATUS_LABEL_PENDING}, row)

    assert fields == {"invoice_status": STATUS_PENDING} and not ignored


def test_overdue_row_leaves_alert_when_matching_file_has_no_invoice_word(isolated_storage: Path) -> None:
    upload([(PDF_NAME, make_pr_pdf(TWO_ITEMS))])
    row_id = get_transactions()[0]["id"]
    today = date.today()
    with _get_connection() as conn:
        conn.execute("UPDATE transactions SET created_at = ? WHERE id = ?", (f"{today - timedelta(days=30)} 09:00:00", row_id))
    _bump_data_version()
    assert row_id in {row["id"] for row in find_overdue_transactions(get_transactions(invoice_status=STATUS_PENDING), today)}

    upload([("INV_0001.pdf", make_text_pdf("Monitor Dell U2724DE"))])

    assert only_row_status() == STATUS_RECEIVED
    assert not find_overdue_transactions(get_transactions(invoice_status=STATUS_PENDING), today)


def test_invoice_word_wins_over_other_document_word(isolated_storage: Path) -> None:
    upload([(PDF_NAME, make_pr_pdf(TWO_ITEMS))])
    upload([("INV_0001.pdf", make_text_pdf("Tax Invoice Purchase Order 55 Monitor Dell U2724DE"))])
    assert only_row_status() == STATUS_RECEIVED


@pytest.mark.parametrize(
    "name, data",
    [
        ("Quotation.pdf", make_text_pdf("Quotation Monitor Dell U2724DE")),
        ("ใบเสนอราคา Monitor Dell U2724DE.jpg", b"image bytes"),
        ("คู่เทียบจอ Monitor Dell U2724DE.jpg", b"image bytes"),
        ("เปรียบเทียบราคา Monitor Dell U2724DE.jpg", b"image bytes"),
        ("PO_Monitor_Dell_U2724DE.jpg", b"image bytes"),
        ("quote-Monitor Dell U2724DE.jpg", b"image bytes"),
        ("ST-1.pdf", make_text_pdf("Purchase Order Monitor Dell U2724DE")),
    ],
)
def test_other_attached_files_keep_status(isolated_storage: Path, name: str, data: bytes) -> None:
    upload([(PDF_NAME, make_pr_pdf(TWO_ITEMS))])

    report = upload([(name, data)])

    assert [item.kind for item in report.items] == [KIND_ATTACHED]
    assert only_row_status() == STATUS_PENDING
    assert TAX_INVOICE_STATUS_WARNING not in report.items[0].warnings


def test_blocked_tax_invoice_changes_no_status(isolated_storage: Path) -> None:
    upload([(PDF_NAME, make_pr_pdf(TWO_ITEMS))])

    report = upload([("ใบกำกับภาษี.pdf", make_text_pdf("Tax Invoice nothing related"))])

    assert [item.kind for item in report.items] == [KIND_BLOCKED]
    assert only_row_status() == STATUS_PENDING


def test_unmatched_scanned_invoice_waits_for_row_choice_and_keeps_bytes(isolated_storage: Path) -> None:
    """ใบกำกับสแกนที่ชื่อไม่มีรุ่น: ยังไม่บันทึก ไม่เปลี่ยนสถานะ แต่เก็บเนื้อไฟล์ไว้ให้เลือกแถว"""
    upload([(PDF_NAME, make_pr_pdf(TWO_ITEMS))])

    item = upload([("ใบกำกับภาษี.pdf", b"scanned bytes")]).items[0]

    assert item.kind == KIND_BLOCKED and item.needs_row_choice
    assert item.data == b"scanned bytes"
    assert only_row_status() == STATUS_PENDING


def test_unmatched_other_file_does_not_ask_for_row(isolated_storage: Path) -> None:
    upload([(PDF_NAME, make_pr_pdf(TWO_ITEMS))])

    item = upload([("scan001.pdf", b"scanned bytes")]).items[0]

    assert item.kind == KIND_BLOCKED and not item.needs_row_choice
    assert item.data == b""


@pytest.mark.parametrize("days_ago", [5, 30])
def test_invoice_attached_to_chosen_row_marks_only_that_row(isolated_storage: Path, days_ago: int) -> None:
    """เลือกแถวเอง (Pending หรือ Overdue): ไฟล์เข้าโฟลเดอร์แถวนั้น เป็น Completed หายจากรายการค้าง แถวอื่นไม่เปลี่ยน"""
    upload([(PDF_NAME, make_pr_pdf(TWO_ITEMS))])
    upload([("PR_Other.pdf", make_pr_pdf([("Printer Beta Y200", "9,000.00")], vendor="Beta Co"))])
    chosen = next(row for row in get_transactions() if row["vendor"] == "Beta Co")
    other = next(row for row in get_transactions() if row["vendor"] != "Beta Co")
    today = date.today()
    with _get_connection() as conn:
        conn.execute(
            "UPDATE transactions SET created_at = ? WHERE id = ?",
            (f"{today - timedelta(days=days_ago)} 09:00:00", chosen["id"]),
        )
    _bump_data_version()

    outcome = attach_invoice_to_row(chosen["id"], "ใบกำกับภาษี.pdf", b"scanned bytes")

    assert outcome.kind == KIND_ATTACHED and TAX_INVOICE_STATUS_WARNING in outcome.warnings
    assert outcome.result.attached_file_names == ["ใบกำกับภาษี.pdf"]
    rows = {row["id"]: row for row in get_transactions()}
    assert rows[chosen["id"]]["invoice_status"] == STATUS_RECEIVED
    assert rows[other["id"]]["invoice_status"] == STATUS_PENDING
    pending = get_transactions(invoice_status=STATUS_PENDING)
    assert chosen["id"] not in {row["id"] for row in find_overdue_transactions(pending, today)}


def test_invoice_attached_to_completed_row_reports_no_status_change(isolated_storage: Path) -> None:
    upload([(PDF_NAME, make_pr_pdf(TWO_ITEMS))])
    row_id = get_transactions()[0]["id"]
    assert attach_invoice_to_row(row_id, "ใบกำกับภาษี.pdf", b"first").kind == KIND_ATTACHED

    outcome = attach_invoice_to_row(row_id, "ใบกำกับภาษี_2.pdf", b"second")

    assert outcome.kind == KIND_ATTACHED and TAX_INVOICE_STATUS_WARNING not in outcome.warnings
    assert only_row_status() == STATUS_RECEIVED


def test_invoice_attached_to_missing_row_is_blocked(isolated_storage: Path) -> None:
    outcome = attach_invoice_to_row(99999, "ใบกำกับภาษี.pdf", b"scanned bytes")
    assert outcome.kind == KIND_BLOCKED and outcome.reason


def test_is_tax_invoice_ignores_scrambled_thai_vowels_and_spacing() -> None:
    assert is_tax_invoice("a.pdf", "ใบก ำกบั ภาษี เลขที่ 1")
    assert is_tax_invoice("a.pdf", "TAX  INVOICE")
    assert is_tax_invoice("tax-invoice.pdf", "")
    assert not is_tax_invoice("ใบเสนอราคา.pdf", "Quotation invoice address")


@pytest.mark.parametrize("days_ago", [5, 30])
def test_tax_invoice_removes_pending_or_overdue_row_from_alert_without_deleting(
    isolated_storage: Path, days_ago: int
) -> None:
    """แถวอายุ 5 วัน (Pending) และ 30 วัน (Overdue) เป็น Completed และไม่อยู่ในรายการค้าง แต่แถวยังอยู่ในตาราง"""
    upload([(PDF_NAME, make_pr_pdf(TWO_ITEMS))])
    today = date.today()
    row_id = get_transactions()[0]["id"]
    with _get_connection() as conn:
        conn.execute(
            "UPDATE transactions SET created_at = ? WHERE id = ?",
            (f"{today - timedelta(days=days_ago)} 09:00:00", row_id),
        )
    _bump_data_version()
    pending = get_transactions(invoice_status=STATUS_PENDING)
    assert len(find_overdue_transactions(pending, today)) == (1 if days_ago > OVERDUE_RULE.days_limit else 0)

    upload([("TAX-0001.pdf", make_text_pdf("Tax Invoice Monitor Dell U2724DE"))])

    assert get_transactions(invoice_status=STATUS_PENDING) == []
    assert find_overdue_transactions(get_transactions(invoice_status=STATUS_PENDING), today) == []
    assert count_transactions() == 1 and only_row_status() == STATUS_RECEIVED
