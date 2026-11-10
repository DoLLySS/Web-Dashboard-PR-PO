"""ทดสอบไฟล์ Excel ที่ Export (utils/excel_export.py): เปิดไฟล์ที่ได้ด้วย openpyxl แล้วตรวจโครงสร้างและรูปแบบ

ครอบคลุม: หัวคอลัมน์, ตรึงหัวตาราง/ปุ่มกรอง, ความกว้าง/ตัดบรรทัด, วันที่/ราคา, ค่าว่าง, ข้อความที่ต้องไม่เป็นตัวเลข/สูตร,
สีสถานะ, คอลัมน์ File, ตารางว่าง, ภาษาไทย และชื่อไฟล์
"""

import io
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

import pages_ui.dashboard as dashboard
import utils.excel_export as excel_export
from data.database import STATUS_RECEIVED, _bump_data_version, add_transaction
from pages_ui import overview
from utils.excel_export import build_excel_bytes, excel_file_name
from utils.local_storage import save_document_locally

HEADERS = list(overview.TABLE_COLUMNS.values())
ONLINE_LINK = "https://example.sharepoint.test/sites/IT/Shared%20Documents/2026/Mar/19/x"


def make_table(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """ตารางหัวคอลัมน์ตามหน้าเว็บ ช่องที่ไม่ระบุเป็นค่าว่าง"""
    return pd.DataFrame(rows, columns=HEADERS)


def open_sheet(data: bytes):
    workbook = load_workbook(io.BytesIO(data))
    return workbook["MasterList"]


def column_of(sheet, header: str) -> int:
    return [cell.value for cell in sheet[1]].index(header) + 1


def sample_row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {
        "Date": date(2026, 3, 19),
        "Description": "Monitor Dell U2724DE",
        "Item": "Hardware",
        "Price": 14500.0,
        "Status": "⏳ Pending",
        "Company": "บริษัท เอ จำกัด",
        "Tel.": "0812345678",
        "Tax ID": "0105536123456",
        "PR No.": "PR-0012",
        "PR Date": date(2026, 3, 18),
        "QT No.": "QT0099",
        "Net Price": 13800.5,
        "File": ONLINE_LINK,
    }
    row.update(overrides)
    return row


# ---------------------------------------------------------------------------
# หัวตาราง
# ---------------------------------------------------------------------------


def test_headers_match_the_web_table_in_order() -> None:
    sheet = open_sheet(build_excel_bytes(make_table([sample_row()])))

    assert [cell.value for cell in sheet[1]] == HEADERS


def test_header_is_bold_filled_and_frozen_with_filter_buttons() -> None:
    sheet = open_sheet(build_excel_bytes(make_table([sample_row(), sample_row()])))

    for cell in sheet[1]:
        assert cell.font.bold is True
        assert cell.fill.fill_type == "solid" and cell.fill.fgColor.rgb.endswith(excel_export.HEADER_FILL.fgColor.rgb[-6:])
    assert sheet.freeze_panes == "A2"
    (table,) = sheet.tables.values()  # ตาราง Excel จริงมีปุ่มกรองในหัวตาราง
    assert table.ref == f"A1:{get_column_letter(len(HEADERS))}3"


def test_column_widths_fit_content_within_limits() -> None:
    long_company = "บริษัท " + "ยาวมาก" * 40
    sheet = open_sheet(build_excel_bytes(make_table([sample_row(Company=long_company, Tel="1")])))

    for index in range(1, len(HEADERS) + 1):
        width = sheet.column_dimensions[get_column_letter(index)].width
        assert excel_export.MIN_COLUMN_WIDTH <= width <= excel_export.MAX_COLUMN_WIDTH
    assert sheet.column_dimensions[get_column_letter(column_of(sheet, "Company"))].width == excel_export.MAX_COLUMN_WIDTH


def test_long_description_wraps_and_row_gets_taller() -> None:
    long_text = "รายละเอียดสินค้ายาวมาก " * 12
    sheet = open_sheet(build_excel_bytes(make_table([sample_row(Description=long_text), sample_row(Description="สั้น")])))
    description_column = column_of(sheet, "Description")

    assert sheet.cell(row=2, column=description_column).alignment.wrap_text is True
    assert sheet.row_dimensions[2].height > sheet.row_dimensions[3].height >= excel_export.BASE_ROW_HEIGHT


# ---------------------------------------------------------------------------
# วันที่ ราคา และค่าว่าง
# ---------------------------------------------------------------------------


def test_dates_are_real_dates_shown_as_day_month_gregorian_year() -> None:
    sheet = open_sheet(build_excel_bytes(make_table([sample_row()])))
    cell = sheet.cell(row=2, column=column_of(sheet, "Date"))

    assert isinstance(cell.value, datetime) and cell.value.date() == date(2026, 3, 19)
    # [$-409] บังคับปฏิทินสากล: Excel ภาษาไทยจะไม่แสดงปี พ.ศ. (2569) แทน 2026
    assert cell.number_format == "[$-409]DD/MM/YYYY"
    assert excel_export.DATE_FORMAT == "[$-409]DD/MM/YYYY"


def test_unparseable_date_is_kept_as_text_not_dropped() -> None:
    sheet = open_sheet(build_excel_bytes(make_table([sample_row(Date="ไม่ทราบวันที่")])))

    assert sheet.cell(row=2, column=column_of(sheet, "Date")).value == "ไม่ทราบวันที่"


@pytest.mark.parametrize("header", ["Price", "Net Price"])
def test_money_is_a_number_with_commas_two_decimals_right_aligned(header: str) -> None:
    sheet = open_sheet(build_excel_bytes(make_table([sample_row(**{header: 1234567.5})])))
    cell = sheet.cell(row=2, column=column_of(sheet, header))

    assert cell.value == 1234567.5 and isinstance(cell.value, float)
    assert cell.number_format == "#,##0.00" and cell.alignment.horizontal == "right"


@pytest.mark.parametrize("blank", [None, float("nan"), pd.NaT, "", "   "])
def test_blank_values_leave_cells_empty_not_none_or_nan(blank: Any) -> None:
    row = sample_row(**{header: blank for header in ("Tel.", "Tax ID", "Description", "Net Price", "PR Date", "QT No.", "Company")})
    sheet = open_sheet(build_excel_bytes(make_table([row])))

    for header in ("Tel.", "Tax ID", "Description", "Net Price", "PR Date", "QT No.", "Company"):
        assert sheet.cell(row=2, column=column_of(sheet, header)).value is None, header


def test_infinite_price_does_not_break_the_file() -> None:
    sheet = open_sheet(build_excel_bytes(make_table([sample_row(Price=float("inf"))])))

    assert sheet.cell(row=2, column=column_of(sheet, "Price")).value == "inf"  # เก็บเป็นข้อความ ไม่ทิ้งข้อมูล


# ---------------------------------------------------------------------------
# ข้อความที่ต้องไม่เป็นตัวเลขหรือสูตร
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("header", "value"),
    [("Tel.", "0812345678"), ("Tel.", "+66 81 234 5678"), ("Tax ID", "0105536123456"), ("PR No.", "00123"), ("QT No.", "0099")],
)
def test_ids_are_text_so_excel_keeps_leading_zeros(header: str, value: str) -> None:
    sheet = open_sheet(build_excel_bytes(make_table([sample_row(**{header: value})])))
    cell = sheet.cell(row=2, column=column_of(sheet, header))

    assert cell.value == value and cell.data_type == "s" and cell.number_format == "@"


@pytest.mark.parametrize("value", ["=1+1", "+66812345678x", "-5", "@SUM(A1:A9)", '=HYPERLINK("http://x","y")', "\t=cmd"])
def test_text_that_looks_like_a_formula_is_never_a_formula(value: str) -> None:
    text_headers = ["Description", "Item", "Company", "Tel.", "Tax ID", "PR No.", "QT No."]
    sheet = open_sheet(build_excel_bytes(make_table([sample_row(**{header: value for header in text_headers})])))

    for header in text_headers:
        cell = sheet.cell(row=2, column=column_of(sheet, header))
        assert cell.data_type == "s", header
        assert cell.value.strip() == value.strip()
    with zipfile.ZipFile(io.BytesIO(build_excel_bytes(make_table([sample_row(Description=value)])))) as archive:
        sheet_xml = archive.read("xl/worksheets/sheet1.xml")
    assert sheet_xml.count(b"<f>") == 2  # มีเฉพาะสูตร SUBTOTAL ของแถวสรุป 2 ช่อง ไม่มีสูตรจากข้อมูล
    assert sheet_xml.count(b"<f>SUBTOTAL(") == 2


def test_thai_text_and_control_characters_are_preserved_or_cleaned() -> None:
    row = sample_row(Description="จอภาพ ๒๗ นิ้ว ไม้เอก ก็ ผู้\x00ใช้\x0b", Company="บริษัท ไทยเทค (ประเทศไทย) จำกัด")
    sheet = open_sheet(build_excel_bytes(make_table([row])))

    assert sheet.cell(row=2, column=column_of(sheet, "Description")).value == "จอภาพ ๒๗ นิ้ว ไม้เอก ก็ ผู้ใช้"
    assert sheet.cell(row=2, column=column_of(sheet, "Company")).value == "บริษัท ไทยเทค (ประเทศไทย) จำกัด"


# ---------------------------------------------------------------------------
# สถานะและคอลัมน์ File
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "text", "fill"),
    [("✅ Completed", "Completed", "DCFCE7"), ("⏳ Pending", "Pending", "FEF3C7"), ("🔴 Overdue", "Overdue", "FEE2E2")],
)
def test_status_has_light_background_by_value_and_no_emoji(raw: str, text: str, fill: str) -> None:
    sheet = open_sheet(build_excel_bytes(make_table([sample_row(Status=raw)])))
    cell = sheet.cell(row=2, column=column_of(sheet, "Status"))

    assert cell.value == text and cell.fill.fill_type == "solid" and cell.fill.fgColor.rgb.endswith(fill)


def test_file_column_keeps_only_online_links() -> None:
    rows = [sample_row(File=ONLINE_LINK), sample_row(File="/app/static/local_uploads/2026/Mar/19/x/PR.pdf"), sample_row(File="")]
    sheet = open_sheet(build_excel_bytes(make_table(rows)))
    file_column = column_of(sheet, "File")

    assert sheet.cell(row=2, column=file_column).hyperlink.target == ONLINE_LINK
    assert sheet.cell(row=3, column=file_column).value is None and sheet.cell(row=3, column=file_column).hyperlink is None
    assert sheet.cell(row=4, column=file_column).value is None


def test_file_column_is_dropped_when_no_row_has_an_online_link() -> None:
    rows = [sample_row(File="/app/static/local_uploads/2026/x/PR.pdf"), sample_row(File="")]
    sheet = open_sheet(build_excel_bytes(make_table(rows)))

    assert [cell.value for cell in sheet[1]] == [header for header in HEADERS if header != "File"]
    everything = {str(cell.value) for row in sheet.iter_rows() for cell in row if cell.value is not None}
    assert not any("/app/static" in text or "local_uploads" in text for text in everything)


# ---------------------------------------------------------------------------
# ตารางว่างและชื่อไฟล์
# ---------------------------------------------------------------------------


def test_empty_table_gives_a_valid_file_with_header_only() -> None:
    sheet = open_sheet(build_excel_bytes(make_table([])))

    assert [cell.value for cell in sheet[1]] == HEADERS  # ไม่มีแถวข้อมูลจึงไม่มีอะไรให้ตัดสินว่า File ว่างทั้งคอลัมน์
    assert sheet.max_row == 1 and not sheet.tables
    assert sheet.freeze_panes == "A2"


def test_file_name_has_the_export_date() -> None:
    assert excel_file_name(date(2026, 11, 10)) == "masterlist_2026-11-10.xlsx"
    assert excel_file_name(date(2026, 1, 5)) == "masterlist_2026-01-05.xlsx"


# ---------------------------------------------------------------------------
# Dashboard ใช้ตารางเดียวกับ Overview
# ---------------------------------------------------------------------------


def test_dashboard_excel_uses_web_headers_and_hides_internal_columns(isolated_storage: Path) -> None:
    _bump_data_version()  # get_transactions จำผลไว้ข้ามเทสต์ ล้างก่อนเพื่อไม่ให้เห็นข้อมูลของเทสต์อื่น
    stored_path = save_document_locally(b"pdf", "PR_1.pdf", ["2026", "Mar", "19", "งานทดสอบ"])
    add_transaction(
        date="2026-03-19",
        vendor="บริษัท เอ จำกัด",
        total_price=14500.0,
        tax_id="0105536123456",
        category="Hardware",
        file_path=stored_path,
        tel="0812345678",
        email="secret@example.com",
        contact_name="สมชาย ใจดี",
        description="Monitor Dell",
    )
    add_transaction(date="2026-03-20", vendor="บริษัท บี", total_price=100.0, invoice_status=STATUS_RECEIVED)

    sheet = open_sheet(dashboard.build_export_excel(date(2026, 3, 1), date(2026, 3, 31)))

    headers = [cell.value for cell in sheet[1]]
    assert headers == [header for header in HEADERS if header != "File"]  # ไม่มีลิงก์ออนไลน์เลย จึงไม่มีคอลัมน์ File
    for forbidden in ("id", "is_deleted", "file_path", "email", "total_price", "invoice_status"):
        assert forbidden not in headers
    values = [str(cell.value) for row in sheet.iter_rows(min_row=2) for cell in row if cell.value is not None]
    assert not any("secret@example.com" in text or "สมชาย" in text or "local_uploads" in text or "/app/static" in text for text in values)
    status_column = column_of(sheet, "Status")
    assert {sheet.cell(row=row, column=status_column).value for row in (2, 3)} == {"Completed", "Pending"}


def test_dashboard_excel_is_empty_bytes_without_data(isolated_storage: Path) -> None:
    _bump_data_version()
    assert dashboard.build_export_excel(date(2026, 3, 1), date(2026, 3, 31)) == b""


# ---------------------------------------------------------------------------
# แถวสรุปท้ายตาราง + ตั้งค่าหน้าพิมพ์ (ข้อ 7)
# ---------------------------------------------------------------------------


def summary_rows(sheet) -> list[int]:
    """แถวใต้ตารางที่มีสูตร"""
    return [row[0].row for row in sheet.iter_rows(min_row=2) if any(c.data_type == "f" for c in row)]


def test_summary_row_sits_below_the_table_with_subtotal_formulas() -> None:
    sheet = open_sheet(build_excel_bytes(make_table([sample_row(), sample_row(Price=100.0), sample_row()])))

    rows = summary_rows(sheet)
    assert len(rows) == 1
    row = rows[0]
    assert row == 3 + 1 + 2  # ข้อมูล 3 แถว (ถึงแถว 4) เว้น 1 แถว แล้วจึงสรุปที่แถว 6
    table_ref = list(sheet.tables.values())[0].ref
    assert row > int(table_ref.split(":")[1].lstrip("ABCDEFGHIJKLMNOPQRSTUVWXYZ"))  # นอกตาราง
    date_letter = get_column_letter(column_of(sheet, "Date"))
    price_letter = get_column_letter(column_of(sheet, "Price"))
    count_cell = next(c for c in sheet[row] if c.data_type == "f" and "103" in str(c.value))
    assert count_cell.value == f"=SUBTOTAL(103,{date_letter}2:{date_letter}4)"
    assert count_cell.number_format == '"จำนวน "#,##0" รายการ"'
    price_cell = sheet.cell(row=row, column=column_of(sheet, "Price"))
    assert price_cell.value == f"=SUBTOTAL(109,{price_letter}2:{price_letter}4)"
    assert price_cell.number_format == "#,##0.00"
    assert price_cell.alignment.horizontal == "right" and price_cell.font.bold
    assert sheet.cell(row=row, column=1).value  # มีป้ายอยู่คอลัมน์แรก


def test_only_the_two_summary_formulas_exist_user_data_stays_text() -> None:
    hostile = sample_row(Description="=1+1", Company="@SUM(A1) Trading")
    data = build_excel_bytes(make_table([hostile, sample_row(**{"Tel.": "+66812345678"})]))

    sheet = open_sheet(data)
    formulas = [c.value for row in sheet.iter_rows() for c in row if c.data_type == "f"]
    assert len(formulas) == 2 and all(str(f).startswith("=SUBTOTAL(") for f in formulas)
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        sheet_xml = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert sheet_xml.count("<f>") == 2


def test_empty_table_has_no_summary_row() -> None:
    sheet = open_sheet(build_excel_bytes(make_table([])))
    assert sheet.max_row == 1


def test_without_price_column_only_the_count_is_summarised() -> None:
    table = make_table([sample_row()]).drop(columns=["Price"])
    sheet = open_sheet(build_excel_bytes(table))
    formulas = [c.value for row in sheet.iter_rows() for c in row if c.data_type == "f"]
    assert len(formulas) == 1 and "103" in formulas[0]


def test_summary_row_does_not_widen_columns() -> None:
    plain = open_sheet(build_excel_bytes(make_table([sample_row()])))
    # แถวสรุปเขียนทีหลังการคำนวณความกว้าง: ความกว้างต้องอยู่ในช่วงปกติและเท่าเดิมเมื่อข้อมูลเหมือนกัน
    again = open_sheet(build_excel_bytes(make_table([sample_row()])))
    for letter, dimension in plain.column_dimensions.items():
        assert dimension.width == again.column_dimensions[letter].width
        assert 10 <= dimension.width <= 40


def test_print_setup_a4_landscape_fit_width_repeat_header_and_footer() -> None:
    data = build_excel_bytes(make_table([sample_row()]), date_range=(date(2026, 3, 1), date(2026, 3, 31)))

    sheet = open_sheet(data)
    assert sheet.page_setup.paperSize == 9  # A4
    assert sheet.page_setup.orientation == "landscape"
    assert sheet.page_setup.fitToWidth == 1 and sheet.page_setup.fitToHeight == 0
    assert sheet.sheet_properties.pageSetUpPr.fitToPage is True
    assert sheet.print_title_rows == "$1:$1"
    assert sheet.page_margins.left <= 0.5 and sheet.page_margins.right <= 0.5
    footer = sheet.oddFooter
    assert "01/03/2026" in footer.left.text and "31/03/2026" in footer.left.text
    assert "&P" in footer.right.text and "&N" in footer.right.text


def test_footer_without_date_range_still_has_page_numbers() -> None:
    sheet = open_sheet(build_excel_bytes(make_table([sample_row()])))
    assert not sheet.oddFooter.left.text
    assert "&P" in sheet.oddFooter.right.text


def test_dashboard_excel_footer_carries_the_selected_range(isolated_storage: Path) -> None:
    _bump_data_version()
    add_transaction(date="2026-03-19", vendor="บริษัท เอ จำกัด", total_price=14500.0)
    sheet = open_sheet(dashboard.build_export_excel(date(2026, 3, 1), date(2026, 3, 31)))
    assert "01/03/2026" in sheet.oddFooter.left.text and "31/03/2026" in sheet.oddFooter.left.text


# ---------------------------------------------------------------------------
# ปุ่ม Export ของ Dashboard: กลุ่มเดียว Excel = ปุ่มหลัก CSV = ปุ่มรอง
# ---------------------------------------------------------------------------


def _render_header_script() -> None:
    from datetime import date as _date

    import pages_ui.dashboard as _dashboard

    _dashboard.render_header_row(_date(2026, 3, 1), _date(2026, 3, 31))


def test_dashboard_header_has_primary_excel_and_secondary_csv_buttons(isolated_storage: Path) -> None:
    from streamlit.testing.v1 import AppTest

    _bump_data_version()
    add_transaction(date="2026-03-19", vendor="บริษัท เอ จำกัด", total_price=14500.0)

    app = AppTest.from_function(_render_header_script).run()

    assert not app.exception
    buttons = {element.proto.label: element.proto for element in app.get("download_button")}
    assert set(buttons) == {"Export Excel", "Export CSV"}
    assert buttons["Export Excel"].type == "primary"
    assert buttons["Export CSV"].type == "secondary"
    assert not buttons["Export Excel"].disabled and not buttons["Export CSV"].disabled


def test_dashboard_export_buttons_are_disabled_without_data(isolated_storage: Path) -> None:
    from streamlit.testing.v1 import AppTest

    _bump_data_version()
    app = AppTest.from_function(_render_header_script).run()

    assert not app.exception
    assert all(element.proto.disabled for element in app.get("download_button"))


def test_dashboard_css_styles_excel_solid_and_csv_outlined() -> None:
    css = dashboard.PAGE_CSS_RULES
    assert ".st-key-dashboard_actions" in css
    assert ".st-key-dashboard_export_csv button {" in css and "background: #ffffff" in css
    assert ".st-key-dashboard_export_excel button {" in css and "background: var(--ui-accent)" in css
