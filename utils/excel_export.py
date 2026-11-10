"""สร้างไฟล์ Excel (.xlsx) ของตาราง Master-List ให้อ่านง่าย: หัวตารางสี, วันที่/ราคาเป็นชนิดจริง, ปรับความกว้างอัตโนมัติ

ไฟล์นี้ไม่เรียก Streamlit (ผู้เรียกเป็นคนแสดง error เอง)
"""

import io
import math
import re
from datetime import date, datetime
from typing import Any

import pandas as pd
from openpyxl import Workbook
from openpyxl.cell.cell import Cell
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.worksheet.page import PageMargins
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

SHEET_NAME: str = "MasterList"
TABLE_NAME: str = "MasterListTable"
TABLE_STYLE: str = "TableStyleMedium2"  # ตารางจริงของ Excel: แถบสลับสี + ปุ่มกรองในหัวตาราง
LINK_DISPLAY_TEXT: str = "เปิดไฟล์"  # ข้อความที่แสดงแทน URL ยาว (คลิกแล้วเปิดลิงก์เต็ม)

# หัวคอลัมน์ -> ชนิดการจัดรูปแบบ (หัวคอลัมน์ตาม TABLE_COLUMNS ใน pages_ui/overview.py)
DATE_COLUMNS: frozenset[str] = frozenset({"Date", "PR Date"})
MONEY_COLUMNS: frozenset[str] = frozenset({"Price", "Net Price"})
TEXT_ID_COLUMNS: frozenset[str] = frozenset(
    {"Tel.", "Tax ID", "PR No.", "QT No."}
)  # เลขที่ต้องเก็บเป็นข้อความ (เลข 0 นำหน้าไม่หาย)
LINK_COLUMN: str = "File"
STATUS_COLUMN: str = "Status"
WRAP_COLUMNS: frozenset[str] = frozenset({"Description"})

# [$-409] = บังคับปฏิทินสากล (ค.ศ.) ไม่เช่นนั้น Excel ที่ตั้งภาษาไทยจะแสดงปี พ.ศ. เช่น 19/03/2569
DATE_FORMAT: str = "[$-409]DD/MM/YYYY"
DATE_DISPLAY_WIDTH: int = len("DD/MM/YYYY")
MONEY_FORMAT: str = "#,##0.00"

HEADER_FILL = PatternFill("solid", fgColor="1E3A8A")
HEADER_FONT = Font(name="Tahoma", size=11, bold=True, color="FFFFFF")
BODY_FONT = Font(name="Tahoma", size=10, color="1E293B")
LINK_FONT = Font(name="Tahoma", size=10, color="2563EB", underline="single")
THIN_SIDE = Side(style="thin", color="CBD5E1")
CELL_BORDER = Border(left=THIN_SIDE, right=THIN_SIDE, top=THIN_SIDE, bottom=THIN_SIDE)

# สีสถานะ: (สีพื้น, สีตัวอักษร)
STATUS_STYLES: dict[str, tuple[str, str]] = {
    "Completed": ("DCFCE7", "166534"),
    "Pending": ("FEF3C7", "92400E"),
    "Overdue": ("FEE2E2", "991B1B"),
}

MIN_COLUMN_WIDTH: int = 10
MAX_COLUMN_WIDTH: int = 40
WRAP_COLUMN_WIDTH: int = 40
FILTER_BUTTON_PADDING: int = 4  # เผื่อที่ปุ่มกรองในหัวตาราง ไม่ให้ทับข้อความ
BODY_PADDING: int = 3
HEADER_ROW_HEIGHT: int = 30
BASE_ROW_HEIGHT: int = 22
LINE_HEIGHT: int = 15  # ความสูงต่อ 1 บรรทัดของ Description ที่ตัดบรรทัด

# อักขระควบคุมที่ XML/Excel ไม่รับ (ทำให้ openpyxl แจ้ง IllegalCharacterError)
_ILLEGAL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
# ตัดอีโมจิ/สัญลักษณ์หน้าข้อความสถานะ เช่น "✅ Completed" -> "Completed" (Excel แสดงอีโมจิเพี้ยน/ถูกตัด)
_LEADING_SYMBOLS = re.compile(r"^[^\w]+", re.UNICODE)
# อีโมจิ/ไอคอนทุกช่วงหลัก + ตัวเชื่อม/ตัวเลือกรูปแบบ + ช่องว่างพิเศษ/zero-width ที่ Excel แสดงเป็นกล่อง
_ICON_CHARS = re.compile(
    r"[←-⇿⌀-⏿■-➿⤀-⥿⬀-⯿"
    r"🀀-🫿︎️​-‍⁠﻿]"
)
_ODD_SPACES = re.compile(r"[  -   　]")


def _is_blank(value: Any) -> bool:
    """ค่าว่าง: None / NaN / NaT / ข้อความว่าง"""
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _clean_text(value: Any) -> str:
    """แปลงเป็นข้อความที่ Excel รับได้ (ตัดอักขระควบคุม/ไอคอน, ช่องว่างพิเศษเป็นช่องว่างปกติ)"""
    text = _ODD_SPACES.sub(" ", _ILLEGAL_CHARS.sub("", str(value)))
    return _ICON_CHARS.sub("", text).strip()


def _to_date(value: Any) -> date | None:
    """แปลงเป็นวันที่ ถ้าแปลงไม่ได้คืน None"""
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _to_number(value: Any) -> float | None:
    """แปลงเป็นตัวเลข ถ้าแปลงไม่ได้คืน None"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _set_text(cell: Cell, text: str) -> None:
    """ใส่ข้อความแบบ 'ข้อความล้วน' (ค่าที่ขึ้นต้นด้วย = + - @ จะไม่ถูกตีเป็นสูตร)"""
    cell.value = text
    cell.data_type = "s"
    cell.number_format = "@"


def _write_cell(cell: Cell, header: str, value: Any) -> None:
    """เขียนค่า 1 ช่องตามชนิดของคอลัมน์ พร้อมจัดรูปแบบและการจัดวาง"""
    cell.font = BODY_FONT
    cell.border = CELL_BORDER
    cell.alignment = Alignment(vertical="center", horizontal="left")
    if _is_blank(value):
        return

    if header in DATE_COLUMNS:
        parsed_date = _to_date(value)
        if parsed_date is None:
            _set_text(cell, _clean_text(value))  # วันที่ผิดรูปแบบ: คงข้อความเดิมไว้ ไม่ทิ้งข้อมูล
        else:
            cell.value = parsed_date
            cell.number_format = DATE_FORMAT
        cell.alignment = Alignment(vertical="center", horizontal="center")
    elif header in MONEY_COLUMNS:
        number = _to_number(value)
        if number is not None and not math.isfinite(number):
            number = None  # inf/nan ทำให้ไฟล์เสีย: เก็บเป็นข้อความแทน
        if number is None:
            _set_text(cell, _clean_text(value))
        else:
            cell.value = number
            cell.number_format = MONEY_FORMAT
        cell.alignment = Alignment(vertical="center", horizontal="right")
    elif header == STATUS_COLUMN:
        status_text = _LEADING_SYMBOLS.sub("", _clean_text(value)) or _clean_text(value)
        _set_text(cell, status_text)
        fill_color, font_color = STATUS_STYLES.get(status_text, ("", ""))
        if fill_color:
            cell.fill = PatternFill("solid", fgColor=fill_color)
            cell.font = Font(name="Tahoma", size=10, bold=True, color=font_color)
        cell.alignment = Alignment(vertical="center", horizontal="center")
    elif header == LINK_COLUMN:
        link_text = _clean_text(value)
        if link_text.lower().startswith(("http://", "https://")):
            _set_text(cell, LINK_DISPLAY_TEXT)
            cell.hyperlink = link_text
            cell.font = LINK_FONT
            cell.alignment = Alignment(vertical="center", horizontal="center")
        else:
            _set_text(cell, link_text)
    elif header in TEXT_ID_COLUMNS:
        _set_text(cell, _clean_text(value))
        cell.alignment = Alignment(vertical="center", horizontal="center")
    elif header in WRAP_COLUMNS:
        _set_text(cell, _clean_text(value))
        cell.alignment = Alignment(vertical="center", horizontal="left", wrap_text=True)
    else:
        _set_text(cell, _clean_text(value))


def excel_file_name(day: date) -> str:
    """ชื่อไฟล์ Excel ที่ Export: masterlist_ปปปป-ดด-วว.xlsx (วันที่ส่งออก)"""
    return f"masterlist_{day.isoformat()}.xlsx"


def _online_link_or_blank(value: Any) -> str:
    """เหลือเฉพาะลิงก์ออนไลน์ (http/https) ส่วนที่อยู่ไฟล์ในเครื่อง เช่น /app/static/... ใช้นอกเว็บแอปไม่ได้และเป็นข้อมูลภายใน จึงไม่ลงไฟล์"""
    text = "" if _is_blank(value) else _clean_text(value)
    return text if text.lower().startswith(("http://", "https://")) else ""


def _prepare_table(table: pd.DataFrame) -> pd.DataFrame:
    """เตรียมตารางก่อนเขียน: คอลัมน์ File เหลือเฉพาะลิงก์ออนไลน์ และตัดคอลัมน์ทิ้งเมื่อไม่มีแถวไหนมีลิงก์เลย (ตารางไม่มีแถว = คงไว้)"""
    if LINK_COLUMN not in table.columns:
        return table
    prepared = table.copy()
    prepared[LINK_COLUMN] = prepared[LINK_COLUMN].map(_online_link_or_blank)
    if len(prepared) and not (prepared[LINK_COLUMN] != "").any():
        prepared = prepared.drop(columns=[LINK_COLUMN])
    return prepared


def _display_width(text: str) -> float:
    """ความกว้างโดยประมาณของข้อความ (อักขระไทยที่เป็นสระ/วรรณยุกต์ลอยไม่กินที่)"""
    return sum(0 if "ั" <= ch <= "ฺ" or "็" <= ch <= "๎" else 1 for ch in text)


def _fit_column_widths(sheet: Any, headers: list[str]) -> None:
    """ปรับความกว้างแต่ละคอลัมน์ให้พอดีเนื้อหา (หัวตารางเผื่อที่ปุ่มกรอง, ไม่เกินค่าสูงสุด)"""
    for column_index, header in enumerate(headers, start=1):
        if header in WRAP_COLUMNS:
            width = WRAP_COLUMN_WIDTH
        else:
            body_longest = 0.0
            for row_index in range(2, sheet.max_row + 1):
                cell_value = sheet.cell(row=row_index, column=column_index).value
                if cell_value is None:
                    continue
                if isinstance(cell_value, (date, datetime)):
                    body_longest = max(body_longest, DATE_DISPLAY_WIDTH)
                elif isinstance(cell_value, float):
                    body_longest = max(body_longest, len(f"{cell_value:,.2f}"))
                else:
                    body_longest = max(body_longest, _display_width(str(cell_value)))
            header_width = _display_width(header) + FILTER_BUTTON_PADDING
            width = min(max(body_longest + BODY_PADDING, header_width, MIN_COLUMN_WIDTH), MAX_COLUMN_WIDTH)
        sheet.column_dimensions[get_column_letter(column_index)].width = width


def _row_height(sheet: Any, row_number: int, headers: list[str]) -> float:
    """ความสูงแถว: เพิ่มตามจำนวนบรรทัดของคอลัมน์ที่ตัดบรรทัด (Description)"""
    lines = 1
    for column_index, header in enumerate(headers, start=1):
        if header not in WRAP_COLUMNS:
            continue
        text = str(sheet.cell(row=row_number, column=column_index).value or "")
        usable_width = max(WRAP_COLUMN_WIDTH - 2, 1)
        lines = max(lines, sum(max(1, math.ceil(_display_width(part) / usable_width)) for part in text.split("\n")))
    return max(BASE_ROW_HEIGHT, LINE_HEIGHT * lines + 7)


SUMMARY_COUNT_FORMAT: str = '"จำนวน "#,##0" รายการ"'
SUMMARY_LABEL: str = "รวม (ตามตัวกรอง)"
SUMMARY_COUNT_COLUMN: str = "Date"  # คอลัมน์ที่ทุกแถวมีค่า ใช้นับจำนวนรายการ
SUMMARY_MONEY_COLUMN: str = "Price"
PAGE_MARGIN_INCH: float = 0.4
PAPER_SIZE_A4: int = 9


def _write_summary_row(sheet: Any, headers: list[str], data_row_count: int) -> None:
    """แถวสรุปใต้ตาราง (เว้น 1 แถวจากตาราง Excel): จำนวนรายการและยอดรวม Price

    ใช้ SUBTOTAL เพื่อให้ตัวเลขเปลี่ยนตามตัวกรองในไฟล์ (สูตรนี้สร้างโดยระบบเท่านั้น ข้อมูลของผู้ใช้ยังเป็นข้อความล้วน)
    """
    if data_row_count == 0 or not headers:
        return
    summary_row = data_row_count + 3
    last_data_row = data_row_count + 1
    summary_font = Font(name="Tahoma", size=11, bold=True)

    count_header = SUMMARY_COUNT_COLUMN if SUMMARY_COUNT_COLUMN in headers else headers[0]
    count_letter = get_column_letter(headers.index(count_header) + 1)
    # ป้ายอยู่คอลัมน์แรก, จำนวนอยู่คอลัมน์ที่ 2 (ถ้ามี; กว้างพอแสดงข้อความ) ไม่เช่นนั้นอยู่คอลัมน์แรก
    count_column = 2 if len(headers) > 1 else 1
    if count_column == 2:
        label_cell = sheet.cell(row=summary_row, column=1, value=SUMMARY_LABEL)
        label_cell.font = summary_font
        label_cell.alignment = Alignment(horizontal="left", vertical="center")
    count_cell = sheet.cell(row=summary_row, column=count_column, value=f"=SUBTOTAL(103,{count_letter}2:{count_letter}{last_data_row})")
    count_cell.number_format = SUMMARY_COUNT_FORMAT
    count_cell.font = summary_font
    count_cell.alignment = Alignment(horizontal="left", vertical="center")

    if SUMMARY_MONEY_COLUMN in headers:
        money_column = headers.index(SUMMARY_MONEY_COLUMN) + 1
        money_letter = get_column_letter(money_column)
        money_cell = sheet.cell(row=summary_row, column=money_column, value=f"=SUBTOTAL(109,{money_letter}2:{money_letter}{last_data_row})")
        money_cell.number_format = MONEY_FORMAT
        money_cell.font = summary_font
        money_cell.alignment = Alignment(horizontal="right", vertical="center")


def _setup_print(sheet: Any, date_range: tuple[date, date] | None) -> None:
    """หน้าพิมพ์: A4 แนวนอน กว้างพอดี 1 หน้า ขอบแคบ ซ้ำแถวหัวตาราง ท้ายกระดาษมีช่วงวันที่ของข้อมูลและเลขหน้า"""
    sheet.page_setup.paperSize = PAPER_SIZE_A4
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_margins = PageMargins(left=PAGE_MARGIN_INCH, right=PAGE_MARGIN_INCH, top=0.5, bottom=0.6, header=0.3, footer=0.3)
    sheet.print_title_rows = "1:1"
    if date_range is not None:
        start, end = date_range
        sheet.oddFooter.left.text = f"ข้อมูลวันที่ {start:%d/%m/%Y} – {end:%d/%m/%Y}"
    sheet.oddFooter.right.text = "หน้า &P / &N"


def build_excel_bytes(table: pd.DataFrame, date_range: tuple[date, date] | None = None) -> bytes:
    """สร้างไฟล์ .xlsx ในหน่วยความจำจากตาราง

    Args:
        table: ตารางที่กรองแล้ว หัวคอลัมน์ตาม TABLE_COLUMNS (Date, Description, Item, Price, Status, ...)
        date_range: ช่วงวันที่ของข้อมูล (เริ่ม, สิ้นสุด) แสดงที่ท้ายกระดาษตอนพิมพ์ ไม่ระบุก็ได้

    Returns:
        ไบต์ของไฟล์ .xlsx

    Raises:
        ValueError, TypeError, OSError: ถ้าสร้างไฟล์ไม่สำเร็จ (ผู้เรียกเป็นคนแจ้งผู้ใช้)
    """
    table = _prepare_table(table)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = SHEET_NAME
    headers = [str(column) for column in table.columns]

    for column_index, header in enumerate(headers, start=1):
        header_cell = sheet.cell(row=1, column=column_index, value=header)
        header_cell.font = HEADER_FONT
        header_cell.fill = HEADER_FILL
        header_cell.border = CELL_BORDER
        header_cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    sheet.row_dimensions[1].height = HEADER_ROW_HEIGHT

    for row_number, row_values in enumerate(table.itertuples(index=False, name=None), start=2):
        for column_index, (header, value) in enumerate(zip(headers, row_values), start=1):
            cell = sheet.cell(row=row_number, column=column_index)
            _write_cell(cell, header, value)
        sheet.row_dimensions[row_number].height = _row_height(sheet, row_number, headers)

    _fit_column_widths(sheet, headers)
    sheet.freeze_panes = "A2"  # หัวตารางค้างไว้เวลาเลื่อน
    if table.shape[0] > 0 and headers:
        # ตาราง Excel จริง: มีปุ่มกรอง/เรียง และแถบสลับสีจากสไตล์ (ไม่ต้องใช้ auto_filter แยก)
        excel_table = Table(displayName=TABLE_NAME, ref=f"A1:{get_column_letter(len(headers))}{table.shape[0] + 1}")
        excel_table.tableStyleInfo = TableStyleInfo(name=TABLE_STYLE, showRowStripes=True)
        sheet.add_table(excel_table)
    sheet.sheet_view.showGridLines = False
    sheet.sheet_view.zoomScale = 100
    _write_summary_row(sheet, headers, table.shape[0])
    _setup_print(sheet, date_range)

    excel_buffer = io.BytesIO()
    workbook.save(excel_buffer)
    return excel_buffer.getvalue()
