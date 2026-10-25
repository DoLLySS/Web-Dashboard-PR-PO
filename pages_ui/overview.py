"""หน้า Overview: แจ้งเตือนใบกำกับภาษีค้าง, ตาราง (ซ้าย), แผงฟอร์ม/อัปโหลด + สรุปอุปกรณ์ (ขวา)

โครงหน้า (ตามดีไซน์):
    หัวหน้า (ชื่อหน้า + Date Filter) อยู่ใน app.py
    แจ้งเตือนใบกำกับภาษีค้าง (เต็มความกว้าง)
    ┌──────────────────────────────┬─────────────────────────────┐
    │ การ์ดตาราง                   │ แท็บ [กรอก Form | Upload File]│
    │  Search bar                  │  การ์ดฟอร์ม / การ์ดอัปโหลด  │
    │  Item ▾   Vendor ▾           ├─────────────────────────────┤
    │  ตาราง (วันที่/ผู้ขาย/Item/ไฟล์) │ การ์ด Quantity of equipment │
    └──────────────────────────────┴─────────────────────────────┘

ส่วนที่ยังไม่ได้ทำ: เชื่อม SharePoint จริง (คอลัมน์ไฟล์ตอนนี้เป็นไอคอนเฉยๆ), OCR สำหรับรูปภาพ
"""

import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import streamlit as st

from config import CATEGORY_OPTIONS
from database import STATUS_PENDING, STATUS_RECEIVED, add_transaction, get_transactions
from text_extractor import extract_fields_from_pdf
from ui_common import build_css, render_equipment_table

# ---------------------------------------------------------------------------
# ค่าคงที่ (Configuration)
# ---------------------------------------------------------------------------

# จำนวนวันที่ใบกำกับภาษีค้าง (สถานะ "รอใบกำกับภาษี") ได้ก่อนจะขึ้นแจ้งเตือน
# (แก้ตัวเลขตรงนี้หากต้องการเปลี่ยนจำนวนวันแจ้งเตือน)
# นับจาก "วันที่เอกสาร" (คอลัมน์ date) จนถึงวันนี้ และแจ้งเตือนเมื่อ "เกิน" ค่านี้
OVERDUE_DAYS_LIMIT: int = 14

# คอลัมน์ในตาราง (ตามดีไซน์) ลำดับในนี้คือลำดับที่แสดง: {ชื่อคอลัมน์ใน DB: หัวคอลัมน์}
# ถ้าอยากเพิ่มคอลัมน์ เช่น po_no ให้เพิ่มที่นี่ และเพิ่มการดึงค่าใน build_table_for_display
TABLE_COLUMNS: dict[str, str] = {
    "date": "Date",
    "vendor": "Vendor",
    "category": "Item",
    "total_price": "Price",
    "invoice_status": "Status",
    "sharepoint_url": "File",
}

# คำอธิบายภาษาไทยของหัวคอลัมน์ (แสดงเมื่อเอาเมาส์ชี้ที่หัวคอลัมน์) ใช้หัวสั้นเพราะคอลัมน์แคบ
TABLE_COLUMN_HELP: dict[str, str] = {
    "date": "วันที่เอกสาร",
    "vendor": "ผู้จัดจำหน่าย",
    "category": "ประเภทสินค้า (Hardware / Software / Network / Service)",
    "total_price": "ราคา (บาท)",
    "invoice_status": "สถานะใบกำกับภาษี: Completed / Pending / Overdue (ค้างเกิน OVERDUE_DAYS_LIMIT วัน)",
    "sharepoint_url": "ไฟล์เชื่อม SharePoint: กดไอคอนเพื่อเปิดในแท็บใหม่",
}

# ความกว้างของแต่ละคอลัมน์ (พิกเซล หรือ "small" / "medium" / "large") ปรับให้ตารางไม่ล้นกรอบ
TABLE_COLUMN_WIDTHS: dict[str, "int | str"] = {
    "date": 90,
    "vendor": 140,
    "category": 85,
    "total_price": 100,
    "invoice_status": 110,
    "sharepoint_url": 50,
}

# ข้อความสถานะที่แสดงในตาราง (แก้ข้อความ/ไอคอนที่นี่)
STATUS_LABEL_COMPLETED: str = "✅ Completed"  # ได้รับใบกำกับภาษีแล้ว
STATUS_LABEL_PENDING: str = "⏳ Pending"  # รอใบกำกับภาษี และยังไม่เกินกำหนด
STATUS_LABEL_OVERDUE: str = "🔴 Overdue"  # รอใบกำกับภาษี และค้างเกิน OVERDUE_DAYS_LIMIT วัน

# ไอคอนที่แสดงในคอลัมน์ไฟล์ กดแล้วเปิดลิงก์ SharePoint ในแท็บใหม่ (รายการที่ไม่มีลิงก์จะเว้นว่าง)
FILE_LINK_ICON: str = "📁"

# สีแถวสลับในตาราง (zebra) ตามดีไซน์
TABLE_ZEBRA_COLOR: str = "#fff1cf"

# ตัวเลือก "ทั้งหมด" ของ dropdown กรอง Item / Vendor
# (เป็นตัวเลือกแรกของ dropdown จึงแสดงข้อความตามดีไซน์ว่า "Item (ประเภท)" / "Vendor" และหมายถึงไม่กรอง)
ALL_ITEMS_LABEL: str = "Item (ประเภท)"
ALL_VENDORS_LABEL: str = "Vendor"

# สัดส่วนความกว้างของหน้า: [ฝั่งซ้าย (ตาราง), ฝั่งขวา (ฟอร์ม + อัปโหลด)]
PAGE_COLUMN_RATIO: list[int] = [3, 2]

# โฟลเดอร์เก็บไฟล์ (อยู่ข้างโฟลเดอร์ pages_ui)
UPLOAD_DIRECTORY: Path = Path(__file__).parent.parent / "data" / "uploads"
# คิวไฟล์ที่รอส่งขึ้น SharePoint (ยังไม่ได้เชื่อมจริง จึงเก็บไว้ในเครื่องก่อน)
SHAREPOINT_QUEUE_DIRECTORY: Path = Path(__file__).parent.parent / "data" / "sharepoint_pending"

# ประเภทไฟล์ที่อนุญาตให้อัปโหลด
ALLOWED_FILE_TYPES: list[str] = ["pdf", "png", "jpg", "jpeg"]

# เลขประจำตัวผู้เสียภาษีของไทยมี 13 หลัก
TAX_ID_LENGTH: int = 13

# ตรวจอีเมลแบบหลวม ๆ: มีตัวอักษร @ ตัวอักษร . ตัวอักษร
EMAIL_PATTERN: str = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
# เบอร์โทรอนุญาตตัวเลข ช่องว่าง - + ( ) และยาว 6-20 ตัวอักษร
TEL_PATTERN: str = r"^[0-9+\-() ]{6,20}$"
# ลิงก์ที่อนุญาต: ขึ้นต้น http:// หรือ https:// และไม่มีช่องว่าง
URL_PATTERN: str = r"^https?://\S+$"

# ชื่อ key ใน st.session_state
SESSION_KEY_SUCCESS_MESSAGE: str = "overview_success_message"  # ข้อความบันทึกสำเร็จ
SESSION_KEY_FORM_COUNTER: str = "overview_form_counter"  # ตัวนับ ใช้เคลียร์ฟอร์มหลังบันทึก
SESSION_KEY_PURCHASE_FILE_ID: str = "overview_purchase_file_id"  # ไฟล์ Purchase ที่ประมวลผลแล้ว
SESSION_KEY_PURCHASE_NOTICE: str = "overview_purchase_notice"  # ข้อความผลการดึงข้อมูลจากไฟล์
SESSION_KEY_SHAREPOINT_FILE_ID: str = "overview_sharepoint_file_id"  # ไฟล์ SharePoint ที่เก็บแล้ว
SESSION_KEY_SHAREPOINT_NOTICE: str = "overview_sharepoint_notice"  # ข้อความผลการเก็บไฟล์

# ---------------------------------------------------------------------------
# CSS เฉพาะหน้า Overview (กฎกลางของการ์ด/สี/ความมน อยู่ที่ ui_common.py)
# ---------------------------------------------------------------------------

PAGE_CSS_RULES: str = """
/* (สี ฟอนต์ ช่องกรอก ปุ่ม และมุม 8px ของทั้งระบบมาจากธีมกลาง styles.py แล้ว ที่นี่เหลือเฉพาะส่วนที่เป็นของหน้านี้) */

/* 1) แท็บ [กรอก Form | Upload File]: แถบสีอ่อน แท็บที่เลือกเป็นสีฟ้าหลัก */
.st-key-right_panel [role="tablist"] {
    background: var(--ui-inner-bg); border: 1px solid var(--ui-border);
    border-radius: INNER_RADIUS; padding: 4px; gap: 4px;
}
.st-key-right_panel [data-testid="stTab"] { border-radius: INNER_RADIUS; padding: 6px 20px; }
.st-key-right_panel [data-testid="stTab"][data-selected="true"] { background: var(--ui-accent); }
.st-key-right_panel [data-testid="stTab"][data-selected="true"] p { color: #ffffff !important; font-weight: 700; }
.st-key-right_panel .react-aria-SelectionIndicator { display: none; }  /* ซ่อนเส้นขีดใต้แท็บเดิม */

/* 2) กล่องขาวครอบตาราง: ตัดมุมตารางให้มน 8px + เส้นขอบบาง */
.st-key-table_inner [data-testid="stDataFrame"] {
    border-radius: INNER_RADIUS; overflow: hidden; border: 1px solid var(--ui-border);
}

/* 3) กล่องฟอร์มด้านใน (st.form): พื้นอ่อน เส้นขอบบาง */
.st-key-entry_form_card [data-testid="stForm"] {
    background: var(--ui-inner-bg); border: 1px solid var(--ui-border);
    border-radius: INNER_RADIUS; padding: var(--app-card-padding);
}
/* ป้ายชื่อฟิลด์ด้านซ้าย (TaxID :, P/O No. : ...) */
.field-label { font-size: 13px; color: var(--ui-text); font-weight: 600; }

/* 4) ปุ่ม Upload (บันทึกข้อมูล): เต็มความกว้าง (สีฟ้า/มุมมนมาจากธีมกลาง) */
.st-key-entry_form_card [data-testid="stFormSubmitButton"] { width: 100%; }
.st-key-entry_form_card [data-testid="stFormSubmitButton"] button { width: 100%; }

/* 5) กล่องลากไฟล์ (st.file_uploader): พื้นขาว เส้นขอบประ มุม 8px */
.st-key-upload_card [data-testid="stFileUploaderDropzone"],
.st-key-entry_form_card [data-testid="stFileUploaderDropzone"] {
    background: var(--ui-card-bg); border: 2px dashed var(--ui-dashed-border); border-radius: INNER_RADIUS;
}
.st-key-upload_card [data-testid="stFileUploaderDropzone"] {
    flex-direction: column; justify-content: center; align-items: center; text-align: center; padding: 24px 12px;
}
/* ข้อความในกล่องลากไฟล์: เติม "Drop your file here" เหนือข้อความขนาดไฟล์เดิม และจัดให้อยู่บนปุ่ม */
.st-key-upload_card [data-testid="stFileUploaderDropzoneInstructions"] {
    order: -1; flex-direction: column; align-items: center; text-align: center;
}
.st-key-upload_card [data-testid="stFileUploaderDropzoneInstructions"]::before {
    content: "Drop your file here";
    display: block; font-size: 15px; font-weight: 600; color: var(--ui-text); margin-bottom: 2px;
}

/* 6) ปุ่มเลือกไฟล์ (Browse files): สีฟ้าหลัก ซ่อนข้อความ/ไอคอนเดิม แล้วใส่คำว่า "Browser" แทน
      (เลือกเฉพาะ > span > button เพื่อไม่ให้ไปโดนปุ่ม x ลบไฟล์ที่อยู่ในกล่องเดียวกัน) */
.st-key-upload_card [data-testid="stFileUploaderDropzone"] > span > button {
    background: var(--ui-accent); border: none; border-radius: BUTTON_RADIUS; padding: 6px 36px;
}
.st-key-upload_card [data-testid="stFileUploaderDropzone"] > span > button > div { display: none; }
.st-key-upload_card [data-testid="stFileUploaderDropzone"] > span > button::after {
    content: "Browser"; font-size: 14px; font-weight: 700; color: #ffffff;
}
.st-key-upload_card [data-testid="stFileUploaderDropzone"] > span > button:hover { background: var(--ui-accent-hover); }
"""


# ---------------------------------------------------------------------------
# ฟังก์ชันช่วย
# ---------------------------------------------------------------------------


def validate_form_input(
    vendor_name: str, tax_id: str, tel: str, email: str, sharepoint_url: str = ""
) -> list[str]:
    """ตรวจข้อมูลในฟอร์มก่อนบันทึก

    Args:
        vendor_name: ชื่อผู้ขายที่กรอก (บังคับ)
        tax_id: เลขผู้เสียภาษีที่กรอก (ว่างได้)
        tel: เบอร์โทรที่กรอก (ว่างได้)
        email: อีเมลที่กรอก (ว่างได้)
        sharepoint_url: ลิงก์ไฟล์บน SharePoint ที่กรอก (ว่างได้)

    Returns:
        list ของข้อความปัญหาภาษาไทย ถ้าว่างแปลว่าข้อมูลผ่านทั้งหมด
    """
    problem_messages: list[str] = []

    if not vendor_name.strip():
        problem_messages.append("กรุณากรอกชื่อผู้ขาย (Vendor)")

    # Tax ID ไม่บังคับ แต่ถ้ากรอกต้องเป็นตัวเลข 13 หลัก
    if tax_id and not (tax_id.isdigit() and len(tax_id) == TAX_ID_LENGTH):
        problem_messages.append(f"TaxID ต้องเป็นตัวเลข {TAX_ID_LENGTH} หลัก")

    if tel and not re.match(TEL_PATTERN, tel):
        problem_messages.append("เบอร์โทร (Tel.) ใช้ได้เฉพาะตัวเลข เว้นวรรค - + ( ) และยาว 6-20 ตัว")

    if email and not re.match(EMAIL_PATTERN, email):
        problem_messages.append("รูปแบบอีเมล (Email) ไม่ถูกต้อง เช่น name@company.com")

    # ลิงก์ต้องขึ้นต้นด้วย http:// หรือ https:// เท่านั้น (กันลิงก์อันตราย เช่น javascript:)
    if sharepoint_url and not re.match(URL_PATTERN, sharepoint_url):
        problem_messages.append("ลิงก์ SharePoint ต้องขึ้นต้นด้วย https://")

    return problem_messages


def save_uploaded_document(uploaded_document, target_directory: Path = UPLOAD_DIRECTORY) -> Optional[Path]:
    """บันทึกไฟล์ที่ผู้ใช้อัปโหลดลงโฟลเดอร์ที่กำหนด

    Args:
        uploaded_document: ไฟล์จาก st.file_uploader (UploadedFile)
        target_directory: โฟลเดอร์ปลายทาง (ค่าเริ่มต้นคือ data/uploads/)

    Returns:
        path ของไฟล์ที่บันทึก, หรือ None ถ้าบันทึกไม่สำเร็จ (แสดง st.error ให้แล้ว)
    """
    try:
        target_directory.mkdir(parents=True, exist_ok=True)

        # ตัดอักขระแปลกออกจากชื่อไฟล์ และใส่เวลานำหน้า กันชื่อซ้ำเขียนทับกัน
        safe_file_name = re.sub(r"[^\w.\-]", "_", Path(uploaded_document.name).name)
        timestamp_prefix = datetime.now().strftime("%Y%m%d_%H%M%S")
        saved_file_path = target_directory / f"{timestamp_prefix}_{safe_file_name}"

        saved_file_path.write_bytes(uploaded_document.getbuffer())
        return saved_file_path
    except OSError as error:
        st.error(
            "❌ บันทึกไฟล์ที่อัปโหลดไม่สำเร็จ: ตรวจว่าดิสก์ไม่เต็มและมีสิทธิ์เขียนโฟลเดอร์ "
            f"{target_directory.name}/ แล้วลองใหม่\n\nรายละเอียดทางเทคนิค: {error}"
        )
        return None


def remove_saved_document(saved_file_path: Path) -> None:
    """ลบไฟล์ที่เพิ่งบันทึก (ใช้ตอนบันทึกลง DB ไม่สำเร็จ เพื่อไม่ให้มีไฟล์ค้างโดยไม่มีรายการ)

    Args:
        saved_file_path: path ของไฟล์ที่ต้องการลบ
    """
    try:
        saved_file_path.unlink(missing_ok=True)
    except OSError:
        # ลบไม่ได้ก็ไม่เป็นไร แค่มีไฟล์ค้าง ไม่กระทบข้อมูลหลัก
        pass


def _field_key(field_name: str, form_counter: int) -> str:
    """สร้าง key ของช่องกรอก (ต่อท้ายด้วยตัวนับ เพื่อให้ฟอร์มว่างใหม่หลังบันทึกสำเร็จ)"""
    return f"overview_field_{field_name}_{form_counter}"


# ---------------------------------------------------------------------------
# แจ้งเตือนใบกำกับภาษีค้าง
# ---------------------------------------------------------------------------


def find_overdue_transactions(
    pending_transactions: list[dict[str, Any]], today: date
) -> list[dict[str, Any]]:
    """คัดรายการที่ค้างใบกำกับภาษีเกิน OVERDUE_DAYS_LIMIT วัน

    Args:
        pending_transactions: รายการที่สถานะ "รอใบกำกับภาษี" (dict จาก database.py)
        today: วันนี้ (ส่งเข้ามาเพื่อให้ทดสอบง่าย)

    Returns:
        รายการที่ค้างเกินกำหนด แต่ละ dict จะมีคอลัมน์ "days_pending" (จำนวนวันที่ค้าง) เพิ่มมา
        เรียงจากค้างนานที่สุดก่อน
    """
    overdue_transactions: list[dict[str, Any]] = []

    for transaction in pending_transactions:
        try:
            document_date = date.fromisoformat(transaction["date"])
        except (ValueError, TypeError):
            # วันที่ในฐานข้อมูลผิดรูปแบบ ข้ามรายการนี้ไป ไม่ให้ทั้งหน้าพัง
            continue

        days_pending = (today - document_date).days
        if days_pending > OVERDUE_DAYS_LIMIT:
            overdue_transactions.append({**transaction, "days_pending": days_pending})

    overdue_transactions.sort(key=lambda item: item["days_pending"], reverse=True)
    return overdue_transactions


def render_overdue_alert() -> None:
    """แสดงกล่องแจ้งเตือนถ้ามีใบกำกับภาษีค้างเกินกำหนด

    หมายเหตุ: ตรวจจากรายการค้างทุกวันที่ ไม่ขึ้นกับ Date Filter
    เพราะรายการเก่าที่ค้างอยู่ต้องไม่หลุดจากการแจ้งเตือนเมื่อผู้ใช้เลือกช่วงวันที่ใหม่
    """
    pending_transactions = get_transactions(invoice_status=STATUS_PENDING)
    overdue_transactions = find_overdue_transactions(pending_transactions, date.today())

    if not overdue_transactions:
        return

    st.warning(
        f"⚠️ มีใบกำกับภาษีค้างเกิน {OVERDUE_DAYS_LIMIT} วัน จำนวน "
        f"{len(overdue_transactions)} รายการ กรุณาติดตามจากผู้ขาย"
    )
    with st.expander("ดูรายการที่ค้าง"):
        overdue_table = pd.DataFrame(overdue_transactions)[
            ["id", "date", "vendor", "po_no", "total_price", "days_pending"]
        ]
        overdue_table.columns = ["รหัส", "วันที่", "ผู้ขาย", "เลขที่ PO", "ราคารวม (บาท)", "ค้างมาแล้ว (วัน)"]
        st.dataframe(overdue_table, hide_index=True, width="stretch")


# ---------------------------------------------------------------------------
# การ์ดตาราง (ฝั่งซ้าย): Search bar + Item/Vendor + ตาราง
# ---------------------------------------------------------------------------


def _valid_link_or_none(url: Optional[str]) -> Optional[str]:
    """คืน url ถ้าเป็นลิงก์ http(s) ที่ถูกต้อง ไม่เช่นนั้นคืน None (ใช้ก่อนแสดงเป็นลิงก์ในตาราง)"""
    return url if url and re.match(URL_PATTERN, url) else None


def get_status_label(invoice_status: str, document_date: Optional[date], today: date) -> str:
    """แปลงสถานะใบกำกับภาษีในฐานข้อมูลเป็นข้อความที่แสดงในตาราง

    กติกา:
      - ได้รับใบกำกับภาษีแล้ว                          -> "✅ Completed"
      - รอใบกำกับภาษี และค้างไม่เกิน OVERDUE_DAYS_LIMIT วัน -> "⏳ Pending"
      - รอใบกำกับภาษี และค้างเกิน OVERDUE_DAYS_LIMIT วัน   -> "🔴 Overdue"

    Args:
        invoice_status: ค่าในคอลัมน์ invoice_status (STATUS_PENDING / STATUS_RECEIVED)
        document_date: วันที่เอกสาร (None ถ้าอ่านวันที่ไม่ได้ จะถือว่ายังไม่เกินกำหนด)
        today: วันนี้ (ส่งเข้ามาเพื่อให้ทดสอบง่าย)

    Returns:
        ข้อความสถานะ ถ้าเป็นสถานะที่ไม่รู้จักจะแสดงค่าเดิมตามที่เก็บไว้
    """
    if invoice_status == STATUS_RECEIVED:
        return STATUS_LABEL_COMPLETED
    if invoice_status == STATUS_PENDING:
        is_overdue = document_date is not None and (today - document_date).days > OVERDUE_DAYS_LIMIT
        return STATUS_LABEL_OVERDUE if is_overdue else STATUS_LABEL_PENDING
    return invoice_status


def build_table_for_display(transactions: list[dict[str, Any]]) -> pd.DataFrame:
    """แปลงรายการจากฐานข้อมูลเป็นตารางที่จะแสดง (คอลัมน์ตาม TABLE_COLUMNS)

    Args:
        transactions: รายการจาก database.get_transactions()

    Returns:
        DataFrame ที่หัวคอลัมน์เป็นภาษาไทยตาม TABLE_COLUMNS
    """
    today = date.today()
    display_rows: list[dict[str, Any]] = []
    for transaction in transactions:
        try:
            document_date: Optional[date] = date.fromisoformat(transaction["date"])
            display_date = document_date.strftime("%d/%m/%Y")
        except (ValueError, TypeError):
            document_date = None
            display_date = str(transaction.get("date", ""))  # วันที่ผิดรูปแบบ แสดงตามที่เก็บไว้

        display_rows.append(
            {
                "date": display_date,
                "vendor": transaction["vendor"],
                "category": transaction.get("category") or "-",
                "total_price": float(transaction.get("total_price") or 0),  # ยังเป็นตัวเลข จัดรูปแบบตอนแสดง
                "invoice_status": get_status_label(transaction["invoice_status"], document_date, today),
                # ลิงก์ไฟล์บน SharePoint: ใส่เฉพาะที่ขึ้นต้น http(s):// (ที่เหลือเว้นว่าง ไม่แสดงไอคอน)
                # ไม่มีลิงก์ให้ใส่ "" (ถ้าใส่ None ตารางจะแสดงคำว่า None)
                "sharepoint_url": _valid_link_or_none(transaction.get("sharepoint_url")) or "",
            }
        )
    return pd.DataFrame(display_rows, columns=list(TABLE_COLUMNS.keys())).rename(columns=TABLE_COLUMNS)


def _zebra_styles(table: pd.DataFrame) -> pd.DataFrame:
    """สร้างสไตล์แถวสลับสี (แถวที่ 1, 3, 5 ... ใส่สีพื้น) สำหรับ DataFrame.style.apply"""
    styles = pd.DataFrame("", index=table.index, columns=table.columns)
    styles.iloc[::2] = f"background-color: {TABLE_ZEBRA_COLOR}"
    return styles


def render_table_card(
    range_transactions: list[dict[str, Any]], start_date: date, end_date: date
) -> None:
    """วาดการ์ดตาราง: ช่อง Search bar, dropdown Item / Vendor และตารางรายการ

    Args:
        range_transactions: รายการทั้งหมดในช่วงวันที่ของ Date Filter (ใช้สร้างตัวเลือก Vendor)
        start_date: วันที่เริ่มต้นจาก Date Filter
        end_date: วันที่สิ้นสุดจาก Date Filter
    """
    with st.container(key="table_card"):
        # ช่องค้นหา: ค้นในชื่อผู้ขาย, เลข PO, เลขรัน PR, Tax ID (ดู database.get_transactions)
        search_keyword = st.text_input(
            "Search bar",
            placeholder="Search bar (ผู้ขาย, เลข PO, เลขรัน PR, Tax ID)",
            label_visibility="collapsed",
        ).strip()

        # dropdown กรอง Item (หมวดหมู่) และ Vendor แถวเดียวกัน
        item_column, vendor_column = st.columns(2)
        selected_item = item_column.selectbox(
            "Item", [ALL_ITEMS_LABEL, *CATEGORY_OPTIONS], label_visibility="collapsed"
        )
        vendor_options = [ALL_VENDORS_LABEL, *sorted({t["vendor"] for t in range_transactions})]
        selected_vendor = vendor_column.selectbox(
            "Vendor", vendor_options, label_visibility="collapsed"
        )

        # ถ้ามีคำค้นหาให้ query ใหม่ตามคำค้น ไม่งั้นใช้รายการทั้งช่วงวันที่ที่มีอยู่แล้ว (ไม่ query ซ้ำ)
        visible_transactions = (
            get_transactions(start_date.isoformat(), end_date.isoformat(), keyword=search_keyword)
            if search_keyword
            else range_transactions
        )
        if selected_item != ALL_ITEMS_LABEL:
            visible_transactions = [t for t in visible_transactions if t.get("category") == selected_item]
        if selected_vendor != ALL_VENDORS_LABEL:
            visible_transactions = [t for t in visible_transactions if t["vendor"] == selected_vendor]

        if not visible_transactions:
            st.info("ไม่พบรายการในช่วงวันที่ที่เลือก")
            return

        display_table = build_table_for_display(visible_transactions)
        # กล่องขาวมุมมนครอบตาราง (สไตล์อยู่ใน PAGE_CSS_RULES ข้อ 7)
        with st.container(key="table_inner"):
            # สรุปราคา: ยอดรวมของรายการที่แสดงอยู่ในตารางขณะนี้ (เปลี่ยนตาม Date Filter / Search / Item / Vendor)
            total_price = sum(float(t.get("total_price") or 0) for t in visible_transactions)
            summary_column, count_column = st.columns(2)
            summary_column.metric("Total Price (บาท)", f"{total_price:,.2f}")
            count_column.metric("จำนวนรายการ", f"{len(display_table):,}")

            st.dataframe(
                display_table.style.apply(_zebra_styles, axis=None)  # แถวสลับสี
                .format({TABLE_COLUMNS["total_price"]: "{:,.2f}"}),  # ราคา: มีคอมม่า ทศนิยม 2 ตำแหน่ง
                hide_index=True,
                width="stretch",
                column_config={
                    # ความกว้างแต่ละคอลัมน์ (small / medium / large)
                    TABLE_COLUMNS["date"]: st.column_config.TextColumn(
                        width=TABLE_COLUMN_WIDTHS["date"], help=TABLE_COLUMN_HELP["date"]
                    ),
                    TABLE_COLUMNS["vendor"]: st.column_config.TextColumn(
                        width=TABLE_COLUMN_WIDTHS["vendor"], help=TABLE_COLUMN_HELP["vendor"]
                    ),
                    TABLE_COLUMNS["category"]: st.column_config.TextColumn(
                        width=TABLE_COLUMN_WIDTHS["category"], help=TABLE_COLUMN_HELP["category"]
                    ),
                    TABLE_COLUMNS["total_price"]: st.column_config.NumberColumn(
                        width=TABLE_COLUMN_WIDTHS["total_price"], help=TABLE_COLUMN_HELP["total_price"]
                    ),
                    TABLE_COLUMNS["invoice_status"]: st.column_config.TextColumn(
                        width=TABLE_COLUMN_WIDTHS["invoice_status"], help=TABLE_COLUMN_HELP["invoice_status"]
                    ),
                    # คอลัมน์ไฟล์: แสดงเป็นไอคอน 📁 กดแล้วเปิดลิงก์ SharePoint ในแท็บใหม่
                    TABLE_COLUMNS["sharepoint_url"]: st.column_config.LinkColumn(
                        width=TABLE_COLUMN_WIDTHS["sharepoint_url"],
                        display_text=FILE_LINK_ICON,
                        help=TABLE_COLUMN_HELP["sharepoint_url"],
                    ),
                },
            )


# ---------------------------------------------------------------------------
# ส่วนที่ 2: การ์ด Upload File (กล่องลากไฟล์ 2 ช่อง)
# ---------------------------------------------------------------------------


def _prefill_form_from_purchase_document(purchase_document, form_counter: int) -> str:
    """ดึง TaxID / Vendor จากไฟล์ PO แล้วเติมลงช่องของฟอร์ม

    ต้องเรียกก่อนที่ฟอร์มจะถูกวาดในรอบเดียวกัน (ดูลำดับใน render()) เพราะ Streamlit
    ให้ตั้งค่าช่องผ่าน session_state ได้เฉพาะก่อนช่องนั้นถูกสร้าง

    Args:
        purchase_document: ไฟล์ที่ผู้ใช้อัปโหลด (UploadedFile)
        form_counter: ตัวนับของฟอร์มปัจจุบัน (ใช้สร้าง key ของช่อง)

    Returns:
        ข้อความสรุปผลให้แสดงผู้ใช้ (ว่างไม่ได้ เพราะต้องบอกผู้ใช้เสมอว่าต้องตรวจเอง)
    """
    if not purchase_document.name.lower().endswith(".pdf"):
        return "⚠️ ไฟล์รูปภาพยังดึงข้อความอัตโนมัติไม่ได้ กรุณากรอกข้อมูลเอง"

    extracted_fields = extract_fields_from_pdf(purchase_document)

    # เติมเฉพาะฟิลด์ที่หาเจอ (ค่าว่างไม่เขียนทับสิ่งที่ผู้ใช้พิมพ์ไว้)
    if extracted_fields.tax_id:
        st.session_state[_field_key("tax_id", form_counter)] = extracted_fields.tax_id
    if extracted_fields.vendor:
        st.session_state[_field_key("vendor", form_counter)] = extracted_fields.vendor
    if extracted_fields.total_amount:
        st.session_state[_field_key("total_price", form_counter)] = float(extracted_fields.total_amount)

    if extracted_fields.warning_message:
        return f"⚠️ {extracted_fields.warning_message}"
    return "✅ เติมข้อมูลจากไฟล์ให้แล้ว กรุณาตรวจความถูกต้องก่อนกด Upload"


def render_upload_section(form_counter: int) -> None:
    """วาดการ์ด "Upload File": กล่องลากไฟล์ Purchase และ SharePoint

    - Purchase: อ่านไฟล์ PDF แล้วเติม TaxID/Vendor ลงฟอร์มให้ และแนบไฟล์นี้กับรายการเมื่อกด Upload
    - SharePoint: ยังไม่ได้เชื่อมจริง เก็บไฟล์ไว้ในคิว data/sharepoint_pending/ ก่อน

    Args:
        form_counter: ตัวนับของฟอร์มปัจจุบัน (ทำให้กล่อง Purchase ว่างใหม่หลังบันทึกสำเร็จ)
    """
    # --- กล่องที่ 1: Upload P/O to Purchase ---
    st.markdown('<div class="card-section-label">Upload P/O to Purchase</div>', unsafe_allow_html=True)
    purchase_document = st.file_uploader(
        "Upload P/O to Purchase",
        type=ALLOWED_FILE_TYPES,
        key=_field_key("purchase_uploader", form_counter),
        label_visibility="collapsed",
    )
    if purchase_document is None:
        # ผู้ใช้กดลบไฟล์ออก ล้างสถานะ เพื่อให้อัปโหลดไฟล์เดิมซ้ำแล้วดึงข้อมูลใหม่ได้
        st.session_state.pop(SESSION_KEY_PURCHASE_FILE_ID, None)
        st.session_state.pop(SESSION_KEY_PURCHASE_NOTICE, None)
    else:
        # ประมวลผลแค่ครั้งเดียวต่อไฟล์ (Streamlit รันสคริปต์ซ้ำทุกครั้งที่มีการกดอะไรสักอย่าง)
        purchase_file_id = f"{purchase_document.name}:{purchase_document.size}:{form_counter}"
        if st.session_state.get(SESSION_KEY_PURCHASE_FILE_ID) != purchase_file_id:
            st.session_state[SESSION_KEY_PURCHASE_FILE_ID] = purchase_file_id
            st.session_state[SESSION_KEY_PURCHASE_NOTICE] = _prefill_form_from_purchase_document(
                purchase_document, form_counter
            )
        st.caption(st.session_state.get(SESSION_KEY_PURCHASE_NOTICE, ""))

    # --- กล่องที่ 2: Upload P/O to SharePoint ---
    st.markdown('<div class="card-section-label">Upload P/O to SharePoint</div>', unsafe_allow_html=True)
    sharepoint_document = st.file_uploader(
        "Upload P/O to SharePoint",
        type=ALLOWED_FILE_TYPES,
        key="overview_sharepoint_uploader",
        label_visibility="collapsed",
    )
    if sharepoint_document is None:
        st.session_state.pop(SESSION_KEY_SHAREPOINT_FILE_ID, None)
        st.session_state.pop(SESSION_KEY_SHAREPOINT_NOTICE, None)
    else:
        sharepoint_file_id = f"{sharepoint_document.name}:{sharepoint_document.size}"
        if st.session_state.get(SESSION_KEY_SHAREPOINT_FILE_ID) != sharepoint_file_id:
            st.session_state[SESSION_KEY_SHAREPOINT_FILE_ID] = sharepoint_file_id
            queued_file_path = save_uploaded_document(sharepoint_document, SHAREPOINT_QUEUE_DIRECTORY)
            st.session_state[SESSION_KEY_SHAREPOINT_NOTICE] = (
                "📥 เก็บไฟล์ในคิวแล้ว (ระบบยังไม่ได้เชื่อม SharePoint จึงยังไม่ถูกส่งขึ้นไป)"
                if queued_file_path
                else ""
            )
        st.caption(st.session_state.get(SESSION_KEY_SHAREPOINT_NOTICE, ""))


# ---------------------------------------------------------------------------
# ส่วนที่ 1: การ์ดกรอกข้อมูล (ฟอร์ม)
# ---------------------------------------------------------------------------


def _labeled_text_input(label_text: str, field_name: str, form_counter: int) -> str:
    """วาดแถวฟิลด์: ป้ายชื่อด้านซ้าย ช่องกรอกด้านขวา (ตามดีไซน์) แล้วคืนค่าที่กรอก

    Args:
        label_text: ข้อความป้ายชื่อ เช่น "TaxID"
        field_name: ชื่อภายในของช่อง (ใช้สร้าง key)
        form_counter: ตัวนับของฟอร์มปัจจุบัน

    Returns:
        ข้อความที่ผู้ใช้กรอก (ตัดช่องว่างหัวท้ายแล้ว)
    """
    label_column, input_column = st.columns([1.35, 2], vertical_alignment="center")
    label_column.markdown(f'<div class="field-label">{label_text} :</div>', unsafe_allow_html=True)
    return input_column.text_input(
        label_text, key=_field_key(field_name, form_counter), label_visibility="collapsed"
    ).strip()


def render_entry_form(form_counter: int) -> None:
    """วาดการ์ด "กรอกข้อมูล" และจัดการเมื่อกดปุ่ม Upload (บันทึก)

    ถ้าจะเพิ่มฟิลด์ใหม่ ต้องแก้ 3 จุด:
    (1) เพิ่มช่องกรอกใน "ส่วนที่ 1"  (2) ส่งค่าเข้า add_transaction ใน "ส่วนที่ 4"
    (3) ถ้าเป็นคอลัมน์ใหม่ ต้องเพิ่มใน database.py และ TABLE_COLUMNS ด้านบนไฟล์นี้ด้วย

    Args:
        form_counter: ตัวนับของฟอร์ม เมื่อบันทึกสำเร็จจะถูกบวกเพื่อให้ฟอร์มว่างใหม่
                      (ถ้าบันทึกไม่สำเร็จ ไม่บวก ผู้ใช้จะได้ไม่ต้องกรอกใหม่)
    """
    st.markdown('<div class="card-title">กรอกข้อมูล</div>', unsafe_allow_html=True)

    with st.form(key=f"transaction_form_{form_counter}", border=False):
        # ส่วนที่ 1: ช่องกรอกข้อมูล ลำดับตามดีไซน์ (เพิ่มช่องใหม่ตรงนี้)
        tax_id = _labeled_text_input("TaxID", "tax_id", form_counter)
        purchase_order_number = _labeled_text_input("P/O No.", "po_no", form_counter)
        pr_run_number = _labeled_text_input("PR Run No.", "pr_run_no", form_counter)
        vendor_name = _labeled_text_input("Vendor", "vendor", form_counter)
        tel = _labeled_text_input("Tel.", "tel", form_counter)
        email = _labeled_text_input("Email", "email", form_counter)
        contact_name = _labeled_text_input("Name", "contact_name", form_counter)

        date_label_column, date_input_column = st.columns([1.35, 2], vertical_alignment="center")
        date_label_column.markdown('<div class="field-label">Date :</div>', unsafe_allow_html=True)
        document_date = date_input_column.date_input(
            "Date",
            value=date.today(),
            format="DD/MM/YYYY",
            key=_field_key("date", form_counter),
            label_visibility="collapsed",
        )

        # ข้อมูลเพิ่มเติม (ไม่บังคับ): ไม่อยู่ในดีไซน์ แต่ Dashboard ใช้ยอดเงิน/หมวดหมู่ ซ่อนไว้ไม่รก
        with st.expander("รายละเอียดเพิ่มเติม (ไม่บังคับ)"):
            category_name = st.selectbox("หมวดหมู่", CATEGORY_OPTIONS, key=_field_key("category", form_counter))
            total_price = st.number_input(
                "ราคารวม (บาท)",
                min_value=0.0,
                step=100.0,
                format="%.2f",
                key=_field_key("total_price", form_counter),
            )
            # ลิงก์ไฟล์บน SharePoint (ใช้เปิดจากไอคอนโฟลเดอร์ในตาราง) จนกว่าระบบจะอัปโหลดขึ้น SharePoint ให้เอง
            sharepoint_url = st.text_input(
                "ลิงก์ไฟล์บน SharePoint (https://...)", key=_field_key("sharepoint_url", form_counter)
            ).strip()

        # ส่วนที่ 2: ไฟล์เอกสารที่แนบมากับรายการนี้ (ปุ่มเลือกไฟล์ใต้ฟอร์ม)
        uploaded_po_document = st.file_uploader(
            "Upload PO", type=ALLOWED_FILE_TYPES, key=_field_key("form_file", form_counter)
        )

        # ส่วนที่ 3: ปุ่ม Upload (บันทึกข้อมูล)
        is_submitted = st.form_submit_button("Upload", type="primary", width="stretch")

    if not is_submitted:
        return

    # ส่วนที่ 4: ตรวจข้อมูล -> บันทึกไฟล์ -> บันทึกลงฐานข้อมูล
    problem_messages = validate_form_input(vendor_name, tax_id, tel, email, sharepoint_url)
    if problem_messages:
        for problem_message in problem_messages:
            st.error(f"❌ {problem_message}")
        return

    # ไฟล์ที่แนบกับรายการ: ใช้ไฟล์ใต้ฟอร์มก่อน ถ้าไม่มีใช้ไฟล์จากกล่อง Upload P/O to Purchase
    purchase_document = st.session_state.get(_field_key("purchase_uploader", form_counter))
    document_to_attach = uploaded_po_document or purchase_document

    saved_file_path: Optional[Path] = None
    if document_to_attach is not None:
        saved_file_path = save_uploaded_document(document_to_attach)
        if saved_file_path is None:
            return  # save_uploaded_document แสดง error ให้แล้ว

    new_transaction_id = add_transaction(
        date=document_date.isoformat(),  # เก็บเป็น ค.ศ. รูปแบบ YYYY-MM-DD
        vendor=vendor_name,
        total_price=total_price,
        tax_id=tax_id or None,
        po_no=purchase_order_number or None,
        pr_run_no=pr_run_number or None,
        category=category_name,
        file_path=str(saved_file_path) if saved_file_path else None,
        tel=tel or None,
        email=email or None,
        contact_name=contact_name or None,
        sharepoint_url=sharepoint_url or None,
    )

    if new_transaction_id is None:
        # add_transaction แสดง error ให้แล้ว แค่เก็บกวาดไฟล์ที่เพิ่งบันทึก
        if saved_file_path is not None:
            remove_saved_document(saved_file_path)
        return

    # ส่วนที่ 5: บันทึกสำเร็จ -> เคลียร์ฟอร์มแล้วโหลดหน้าใหม่
    st.session_state[SESSION_KEY_SUCCESS_MESSAGE] = (
        f"✅ บันทึกรายการเรียบร้อย (รหัสรายการ {new_transaction_id})"
    )
    st.session_state[SESSION_KEY_FORM_COUNTER] = form_counter + 1
    st.rerun()


# ---------------------------------------------------------------------------
# จุดเข้าของหน้า
# ---------------------------------------------------------------------------


def render_right_panel(form_counter: int, start_date: date, end_date: date) -> None:
    """วาดฝั่งขวา: แท็บ [กรอก Form | Upload File] และการ์ด Quantity of equipment

    Args:
        form_counter: ตัวนับของฟอร์มปัจจุบัน
        start_date: วันที่เริ่มต้นจาก Date Filter
        end_date: วันที่สิ้นสุดจาก Date Filter
    """
    with st.container(key="right_panel"):
        form_tab, upload_tab = st.tabs(["กรอก Form", "Upload File"])

        # ข้อควรระวัง: ต้อง "เขียนโค้ด" วาดแท็บอัปโหลดก่อนแท็บฟอร์ม เพราะมันเติมค่าลงช่องของฟอร์ม
        # (Streamlit ตั้งค่าช่องผ่าน session_state ได้เฉพาะก่อนช่องนั้นถูกสร้างในรอบนั้น)
        # ส่วนลำดับบนหน้าจอถูกกำหนดโดย st.tabs ด้านบนแล้ว จึงไม่กระทบ
        with upload_tab, st.container(key="upload_card"):
            render_upload_section(form_counter)
        with form_tab, st.container(key="entry_form_card"):
            render_entry_form(form_counter)

        # การ์ด HW / SW / NW / Service (Quantity of equipment)
        with st.container(key="equipment_card"):
            st.markdown('<span class="card-pill">Quantity of equipment</span>', unsafe_allow_html=True)
            with st.container(key="equipment_inner"):
                render_equipment_table(start_date, end_date)


def render(start_date: date, end_date: date) -> None:
    """แสดงเนื้อหาหน้า Overview (app.py เรียกฟังก์ชันนี้ หลังวาดหัวหน้าและ Date Filter แล้ว)

    Args:
        start_date: วันที่เริ่มต้นจาก Date Filter
        end_date: วันที่สิ้นสุดจาก Date Filter

    Returns:
        ไม่มีค่าคืน (วาดหน้าจอด้วย Streamlit)
    """
    st.markdown(build_css(PAGE_CSS_RULES), unsafe_allow_html=True)

    # แสดงข้อความบันทึกสำเร็จครั้งก่อน (เก็บไว้ข้ามการ rerun) แล้วลบทิ้งเพื่อไม่ให้แสดงซ้ำ
    success_message = st.session_state.pop(SESSION_KEY_SUCCESS_MESSAGE, None)
    if success_message:
        st.success(success_message)

    # ส่วนที่ 1: แจ้งเตือนใบกำกับภาษีค้าง (เต็มความกว้าง อยู่บนสุดเพื่อให้เห็นก่อน)
    render_overdue_alert()

    form_counter: int = st.session_state.setdefault(SESSION_KEY_FORM_COUNTER, 0)
    range_transactions = get_transactions(start_date.isoformat(), end_date.isoformat())
    left_column, right_column = st.columns(PAGE_COLUMN_RATIO, gap="medium")

    # ส่วนที่ 2: ฝั่งซ้าย = การ์ดตาราง (Search bar + Item/Vendor + ตาราง)
    with left_column:
        render_table_card(range_transactions, start_date, end_date)

    # ส่วนที่ 3: ฝั่งขวา = แท็บฟอร์ม/อัปโหลด + การ์ดสรุปอุปกรณ์
    with right_column:
        render_right_panel(form_counter, start_date, end_date)
