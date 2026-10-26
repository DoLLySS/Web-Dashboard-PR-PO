"""หน้า Overview: แจ้งเตือนใบกำกับภาษีค้าง + ตาราง Master-List เต็มความกว้าง + ปุ่มเปิดหน้าต่างเพิ่มข้อมูล

โครงหน้า (ตารางเป็นจุดสนใจหลัก ใช้พื้นที่กว้างที่สุด):
    หัวหน้า (ชื่อหน้า + Date Filter) อยู่ใน app.py (ตั้ง layout="wide" ที่ app.py แล้ว ครอบคลุมทุกหน้า)
    แจ้งเตือนใบกำกับภาษีค้าง (เต็มความกว้าง)
                                          [ ➕ เพิ่มข้อมูล / อัปโหลดเอกสาร ]  <- กดแล้วเด้งหน้าต่าง (st.dialog)
    ┌────────────────────────────────────────────────────────────┐
    │ การ์ดตาราง (เต็มความกว้าง)                                  │
    │  Search bar   |   Item ▾   |   Vendor ▾                     │
    │  ตาราง Master-List                                          │
    └────────────────────────────────────────────────────────────┘
    ▸ Quantity of equipment (กางออกดูได้)

    หน้าต่าง "เพิ่มข้อมูล / อัปโหลดเอกสาร" มีแท็บ [กรอก Form | Upload File] (ย้ายมาจากแผงด้านขวาเดิม ไม่เปลี่ยน Logic)

ไฟล์เอกสารถูกบันทึกลงโฟลเดอร์ data/local_uploads/ (utils/local_storage.py) แล้วเก็บที่อยู่ไฟล์ลงฐานข้อมูล
ส่วนเชื่อม SharePoint ปิดไว้ก่อน เตรียมไว้สำหรับเชื่อมต่อในอนาคต (utils/sharepoint_api.py, ค้นหา "SharePoint ปิดไว้")
ส่วนที่ยังไม่ได้ทำ: OCR สำหรับรูปภาพ
"""

import re
from datetime import date
from typing import Any, Optional

import pandas as pd
import streamlit as st
from streamlit.runtime.uploaded_file_manager import UploadedFile

from config.constants import CATEGORY_OPTIONS
from config.logging_setup import get_logger
from data.database import (
    STATUS_PENDING,
    STATUS_RECEIVED,
    add_transaction,
    delete_transaction,
    get_transactions,
    update_transaction,
)
from utils.local_storage import LocalStorageError, save_document_locally

# SharePoint ปิดไว้ — เตรียมไว้สำหรับเชื่อมต่อในอนาคต (เปิดใช้เมื่อได้สิทธิ์และตั้งค่า .env แล้ว)
# from utils.sharepoint_api import SharePointError, upload_document_to_sharepoint
from utils.text_extractor import extract_fields_from_file
from st_aggrid import JsCode
from ui_common import build_css, render_equipment_table
from ui_grid import build_grid_options, render_readonly_grid, show_grid

# บันทึกลง logs/app.log
logger = get_logger(__name__)

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
    # --- ข้อมูลจากเอกสาร PR / Quotation (Master-List) แสดงหลังคอลัมน์หลัก เลื่อนตารางไปทางขวาเพื่อดู ---
    "tel": "Tel.",
    "tax_id": "Tax ID",
    "pr_run_no": "PR No.",
    "pr_request_date": "PR Date",
    "qt_no": "QT No.",
    "description": "Description",
    "unit_price": "Net Price",
    "sharepoint_url": "File",
}

# คำอธิบายภาษาไทยของหัวคอลัมน์ (แสดงเมื่อเอาเมาส์ชี้ที่หัวคอลัมน์) ใช้หัวสั้นเพราะคอลัมน์แคบ
TABLE_COLUMN_HELP: dict[str, str] = {
    "date": "วันที่เอกสาร",
    "vendor": "ผู้จัดจำหน่าย",
    "category": "ประเภทสินค้า (Hardware / Software / Network / Service)",
    "total_price": "ราคา (บาท)",
    "invoice_status": "สถานะใบกำกับภาษี: Completed / Pending / Overdue (ค้างเกิน OVERDUE_DAYS_LIMIT วัน)",
    "tel": "เบอร์โทรศัพท์",
    "tax_id": "เลขประจำตัวผู้เสียภาษี 13 หลัก",
    "pr_run_no": "เลขที่ PR",
    "pr_request_date": "วันที่ PR",
    "qt_no": "เลขที่ Quotation",
    "description": "รายละเอียดอุปกรณ์",
    "unit_price": "ราคาสุทธิที่รวม Discount แล้ว (บาท)",
    "sharepoint_url": "ไฟล์เชื่อม SharePoint: กดไอคอนเพื่อเปิดในแท็บใหม่",
}

# ความกว้างที่ต้องการของแต่ละคอลัมน์ (พิกเซล) ตารางจะปรับคอลัมน์ให้พอดีหน้าจอเอง (fit to window) ไม่มีแถบเลื่อนแนวนอน
# - ค่าตัวเลข = ความกว้างที่ต้องการ (px) ตารางย่อ/ขยายตามสัดส่วนให้พอดีจอ (ดู ui_grid.GRID_MIN_WIDTH_RATIO_*)
# - None = คอลัมน์ข้อความยาว (ตอนนี้คือ Description) กว้างที่สุด ย่อได้มากสุดเมื่อจอแคบ
# - ถ้าเพิ่มคอลัมน์ใหม่ ให้เพิ่มความกว้างขั้นต่ำที่นี่ด้วย (ผลรวมมากเกินจอ ตารางจะมีแถบเลื่อนแนวนอน)
TABLE_COLUMN_WIDTHS: dict[str, "int | str | None"] = {
    "date": 118, "vendor": 86, "category": 86, "total_price": 104, "invoice_status": 138,
    "tel": 106, "tax_id": 142, "pr_run_no": 110, "pr_request_date": 118, "qt_no": 74,
    "description": None, "unit_price": 104, "sharepoint_url": 44,
}
# คอลัมน์ข้อความที่ย่อได้มากเมื่อจอแคบ (ข้อความยาวถูกตัดด้วย ... ชี้เมาส์ดูเต็มได้) ส่วนคอลัมน์อื่นพยายามไม่ย่อ
SHRINKABLE_TABLE_COLUMNS: tuple[str, ...] = ("vendor", "category", "tel", "pr_run_no")

# ข้อความสถานะที่แสดงในตาราง (แก้ข้อความ/ไอคอนที่นี่)
STATUS_LABEL_COMPLETED: str = "✅ Completed"  # ได้รับใบกำกับภาษีแล้ว
STATUS_LABEL_PENDING: str = "⏳ Pending"  # รอใบกำกับภาษี และยังไม่เกินกำหนด
STATUS_LABEL_OVERDUE: str = "🔴 Overdue"  # รอใบกำกับภาษี และค้างเกิน OVERDUE_DAYS_LIMIT วัน

# คอลัมน์ที่ผู้ใช้แก้ไขได้โดยตรงในตาราง (ดับเบิลคลิกที่ช่อง) คอลัมน์อื่นล็อกไว้ (ลบแถวทำได้เสมอ)
# ถ้าอยากเปิดให้แก้ date / vendor / category / total_price ด้วย แค่เพิ่มชื่อคอลัมน์ในรายการนี้
# (ระบบตรวจค่าและบันทึกให้ใน build_update_fields อยู่แล้ว)
# ถ้าเพิ่มคอลัมน์ใหม่ในตาราง: เพิ่มชื่อที่นี่ + เพิ่มวิธีตรวจค่าใน build_update_fields
EDITABLE_TABLE_COLUMNS: tuple[str, ...] = (
    "invoice_status",
    "tel",
    "tax_id",
    "pr_run_no",
    "pr_request_date",
    "qt_no",
    "description",
    "unit_price",
)

# ตัวเลือกว่าง ("-") ของคอลัมน์ Item หมายถึงยังไม่ระบุหมวด (เก็บเป็น NULL ในฐานข้อมูล)
NO_CATEGORY_LABEL: str = "-"

# ตัวเลือกใน dropdown ของคอลัมน์ Status (แก้ได้โดยตรงในตาราง)
# Overdue ใส่ไว้เพื่อให้แถวที่ค้างเกินกำหนดแสดงค่าปัจจุบันได้ แต่เป็นสถานะที่ระบบคำนวณเอง ผู้ใช้เลือกเองไม่ได้
STATUS_EDITOR_OPTIONS: list[str] = [STATUS_LABEL_PENDING, STATUS_LABEL_OVERDUE, STATUS_LABEL_COMPLETED]

# ข้อความสถานะในตาราง -> ค่าที่เก็บในฐานข้อมูล (Pending และ Overdue ในฐานข้อมูลคือ "รอใบกำกับภาษี" เหมือนกัน
# ต่างกันที่ Overdue คำนวณจากจำนวนวันที่ค้าง)
STATUS_LABEL_TO_DB: dict[str, str] = {
    STATUS_LABEL_COMPLETED: STATUS_RECEIVED,
    STATUS_LABEL_PENDING: STATUS_PENDING,
    STATUS_LABEL_OVERDUE: STATUS_PENDING,
}

# ไอคอนที่แสดงในคอลัมน์ไฟล์ กดแล้วเปิดลิงก์ SharePoint ในแท็บใหม่ (รายการที่ไม่มีลิงก์จะเว้นว่าง)
FILE_LINK_ICON: str = "📁"

# คอลัมน์ลำดับแถว (ซ่อนในตาราง) ใช้จับคู่แถวที่ผู้ใช้แก้ไข/เลือก กลับไปหารายการในฐานข้อมูล
ROW_POSITION_COLUMN: str = "_pos"

# ตัวแสดงไอคอนลิงก์ไฟล์ในเซลล์ (JavaScript ของ AgGrid) สร้างเป็น element ทีละชิ้น ไม่ต่อสตริง HTML เพื่อกัน XSS
# รับเฉพาะลิงก์ http/https เท่านั้น (ตรวจซ้ำอีกชั้นหลัง _valid_link_or_none ฝั่ง Python); FILE_ICON ถูกแทนด้วย FILE_LINK_ICON
FILE_LINK_RENDERER_JS: str = r"""
class FileLinkRenderer {
    init(params) {
        this.eGui = document.createElement('span');
        if (params.value && /^https?:\/\//i.test(params.value)) {
            const link = document.createElement('a');
            link.href = params.value;
            link.target = '_blank';
            link.rel = 'noopener noreferrer';
            link.title = 'เปิดไฟล์';
            link.textContent = 'FILE_ICON';
            this.eGui.appendChild(link);
        }
    }
    getGui() { return this.eGui; }
}
"""

# คอลัมน์วันที่ในตาราง (เก็บเป็นข้อความ "YYYY-MM-DD" แสดงเป็น DD/MM/YYYY) สีแถวสลับ/ฟอนต์ ตั้งที่ ui_grid.py
GRID_DATE_COLUMNS: tuple[str, ...] = ("date", "pr_request_date")

# ตัวเลือก "ทั้งหมด" ของ dropdown กรอง Item / Vendor
# (เป็นตัวเลือกแรกของ dropdown จึงแสดงข้อความตามดีไซน์ว่า "Item (ประเภท)" / "Vendor" และหมายถึงไม่กรอง)
ALL_ITEMS_LABEL: str = "Item (ประเภท)"
ALL_VENDORS_LABEL: str = "Vendor"

# ประเภทไฟล์ที่อนุญาตให้อัปโหลด
# (pdf และ xlsx/xls ดึงข้อมูลอัตโนมัติได้ รูปภาพยังไม่รองรับ OCR)
ALLOWED_FILE_TYPES: list[str] = ["pdf", "xlsx", "xls", "png", "jpg", "jpeg"]

# นามสกุลไฟล์ที่ระบบดึงข้อมูลอัตโนมัติได้ (ต้องเป็นตัวพิมพ์เล็ก)
AUTO_EXTRACT_EXTENSIONS: tuple[str, ...] = (".pdf", ".xlsx", ".xls")

# เลขประจำตัวผู้เสียภาษีของไทยมี 13 หลัก
TAX_ID_LENGTH: int = 13

# ตรวจอีเมลแบบหลวม ๆ: มีตัวอักษร @ ตัวอักษร . ตัวอักษร
EMAIL_PATTERN: str = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
# เบอร์โทรอนุญาตตัวเลข ช่องว่าง - + ( ) และยาว 6-20 ตัวอักษร
TEL_PATTERN: str = r"^[0-9+\-() ]{6,20}$"
# ลิงก์ที่อนุญาต: ขึ้นต้น http:// หรือ https:// และไม่มีช่องว่าง
URL_PATTERN: str = r"^https?://\S+$"

# ชื่อ key ใน st.session_state
# ช่อง Master-List ที่เป็นข้อความล้วน: คอลัมน์ใน DB -> ชื่อที่ใช้บอกผู้ใช้ตอนตรวจ/แจ้งผิดพลาด (ใช้ในตารางและ build_update_fields)
MASTERLIST_TEXT_COLUMNS: dict[str, str] = {
    "tel": "เบอร์โทรศัพท์",
    "pr_run_no": "เลขที่ PR",
    "qt_no": "เลขที่ Quotation",
    "description": "รายละเอียดอุปกรณ์",
}

SESSION_KEY_SUCCESS_MESSAGE: str = "overview_success_message"  # ข้อความบันทึกสำเร็จ
SESSION_KEY_STATUS_MESSAGES: str = "overview_status_messages"  # ผลการเปลี่ยนสถานะในตาราง [(ระดับ, ข้อความ)]
SESSION_KEY_EDITOR_VERSION: str = "overview_editor_version"  # เลขเวอร์ชันของตาราง ใช้ล้างสถานะการแก้ไขหลังบันทึก
SESSION_KEY_FORM_COUNTER: str = "overview_form_counter"  # ตัวนับ ใช้เคลียร์ฟอร์มหลังบันทึก
# --- หน้าต่างเพิ่มข้อมูลแบบ 2 ขั้นตอน ---
# ขั้นที่ 1 = ถามข้อมูลเบื้องต้น, ขั้นที่ 2 = ฟอร์มหลัก/อัปโหลด (รีเซ็ตเป็น 1 ทุกครั้งที่เปิดหน้าต่างและหลังบันทึกสำเร็จ)
FORM_STEP_QUESTIONS: int = 1
FORM_STEP_MAIN_FORM: int = 2
SESSION_KEY_FORM_STEP: str = "form_step"  # ขั้นตอนปัจจุบันของหน้าต่าง
SESSION_KEY_ENTRY_ITEM: str = "overview_entry_item"  # ประเภท (Item) ที่เลือกในขั้นที่ 1
SESSION_KEY_ENTRY_HAS_INVOICE: str = "overview_entry_has_invoice"  # สถานะใบกำกับภาษีที่เลือกในขั้นที่ 1
# key ของปุ่มเลือกในขั้นที่ 1 (ใช้อ่านค่าตอนกด "ถัดไป")
WIDGET_KEY_STEP1_ITEM: str = "overview_step1_item"
WIDGET_KEY_STEP1_INVOICE: str = "overview_step1_invoice"

# ตัวเลือกของขั้นที่ 1: ประเภทใช้ค่าเดียวกับ dropdown Item ในฟอร์ม (ตัด "อื่น ๆ" ออก เลือกในฟอร์มขั้นที่ 2 ได้)
STEP1_ITEM_OPTIONS: list[str] = [option for option in CATEGORY_OPTIONS if option != "อื่น ๆ"]
INVOICE_CHOICE_HAS: str = "มีใบกำกับภาษี"  # -> บันทึกเป็น STATUS_RECEIVED
INVOICE_CHOICE_NOT_YET: str = "ยังไม่มีใบกำกับภาษี"  # -> บันทึกเป็น STATUS_PENDING
INVOICE_CHOICE_OPTIONS: list[str] = [INVOICE_CHOICE_HAS, INVOICE_CHOICE_NOT_YET]
# ตัวเลือกสถานะใบกำกับภาษี -> ค่าที่เก็บในฐานข้อมูล
INVOICE_CHOICE_TO_DB: dict[str, str] = {
    INVOICE_CHOICE_HAS: STATUS_RECEIVED,
    INVOICE_CHOICE_NOT_YET: STATUS_PENDING,
}

SESSION_KEY_PURCHASE_FILE_ID: str ="overview_purchase_file_id"  # ไฟล์ Purchase ที่ประมวลผลแล้ว
SESSION_KEY_PURCHASE_NOTICE: str = "overview_purchase_notice"  # ข้อความผลการดึงข้อมูลจากไฟล์
SESSION_KEY_LOCAL_FILE_ID: str = "overview_local_file_id"  # ไฟล์ในกล่อง Upload ที่บันทึกลงเครื่องแล้ว
SESSION_KEY_LOCAL_NOTICE: str = "overview_local_notice"  # ผลการบันทึกไฟล์ (ระดับ, ข้อความ)
SESSION_KEY_LOCAL_PATH: str = "overview_local_path"  # ที่อยู่ไฟล์ที่บันทึกแล้ว รอผูกกับรายการตอนกด Upload

# ---------------------------------------------------------------------------
# CSS เฉพาะหน้า Overview (กฎกลางของการ์ด/สี/ความมน อยู่ที่ ui_common.py)
# ---------------------------------------------------------------------------

PAGE_CSS_RULES: str = """
/* (สี ฟอนต์ ช่องกรอก ปุ่ม และมุม 8px ของทั้งระบบมาจากธีมกลาง config/styles.py แล้ว ที่นี่เหลือเฉพาะส่วนที่เป็นของหน้านี้) */

/* 1) แท็บ [กรอก Form | Upload File]: แถบสีอ่อน แท็บที่เลือกเป็นสีฟ้าหลัก */
.st-key-right_panel [role="tablist"] {
    background: var(--ui-inner-bg); border: 1px solid var(--ui-border);
    border-radius: INNER_RADIUS; padding: 4px; gap: 4px;
}
.st-key-right_panel [data-testid="stTab"] { border-radius: INNER_RADIUS; padding: 6px 20px; }
.st-key-right_panel [data-testid="stTab"][data-selected="true"] { background: var(--ui-accent); }
.st-key-right_panel [data-testid="stTab"][data-selected="true"] p { color: #ffffff !important; font-weight: 700; }
.st-key-right_panel .react-aria-SelectionIndicator { display: none; }  /* ซ่อนเส้นขีดใต้แท็บเดิม */

/* 1.1) ลดระยะขอบรอบตาราง เพื่อให้ตารางกว้างขึ้น (ตารางวาดด้วย canvas ปรับขนาดตัวอักษรด้วย CSS ไม่ได้ จึงเอาพื้นที่จากขอบแทน)
      ขอบของหน้าหลัก 48px -> 16px, การ์ดตาราง 32px -> 12px, กล่องขาวด้านใน 20px -> 8px (รวมได้ตารางกว้างขึ้น ~128px) */
[data-testid="stMainBlockContainer"] { padding-left: 16px !important; padding-right: 16px !important; }
.st-key-table_card { padding-left: 12px !important; padding-right: 12px !important; }
.st-key-table_inner { padding-left: 8px !important; padding-right: 8px !important; }

/* 1.2) แถวหัวข้อตาราง + ปุ่มเพิ่มข้อมูล: ปุ่มเต็มความกว้างคอลัมน์ขวา (ชิดขอบขวาเท่ากับกล่องตาราง)
        หัวข้อไม่มีระยะบน/ล่างเกิน เพื่อให้อยู่ตรงกลางแนวเดียวกับปุ่ม และดึงแถวนี้ให้ชิดกล่องค้นหาด้านล่าง */
.st-key-table_header_row [data-testid="stButton"],
.st-key-table_header_row [data-testid="stButton"] button { width: 100% !important; }
.st-key-table_header_row h3 { padding: 0 !important; margin: 0 !important; }
.st-key-table_header_row { margin-bottom: -8px; }

/* 1.3) หน้าต่าง Popup แบบแคบ (width="small"): ปุ่มถัดไปเต็มความกว้าง และลดขอบ/ขนาดหัวข้อของฟอร์มให้ช่องกรอกกว้างขึ้น */
.st-key-step1_next_button,
.st-key-step1_next_button button { width: 100% !important; }
.st-key-entry_form_card { padding: 4px !important; }
.st-key-entry_form_card .card-title { font-size: 18px !important; margin: 0 0 4px 0 !important; }
.st-key-entry_form_card [data-testid="stForm"] { padding: 12px !important; }

/* 1.4) Typography ของ Popup (ทั้งขั้นที่ 1 และ 2): ใหญ่ขึ้นอย่างเห็นได้ชัด อ่านง่าย
        ถ้าอยากปรับขนาดอีก แก้ตัวเลข font-size ในกฎนี้ที่เดียว (ไม่แตะ span เพื่อไม่ให้ไอคอนของ Streamlit เพี้ยน) */
/* ข้อความทั่วไปใน Popup: 16px */
div[data-testid="stDialog"] [data-testid="stMarkdownContainer"] p { font-size: 16px; line-height: 1.5; }
/* ป้ายชื่อช่องกรอก: 16px ตัวหนา สีเข้ม */
div[data-testid="stDialog"] label,
div[data-testid="stDialog"] label p,
div[data-testid="stDialog"] .field-label { font-size: 16px !important; font-weight: 600 !important; color: #1f2937 !important; }
/* ข้อความที่พิมพ์ในช่องกรอก / กล่องเลือก: 16px */
div[data-testid="stDialog"] input,
div[data-testid="stDialog"] textarea,
div[data-testid="stDialog"] [data-baseweb="select"] { font-size: 16px !important; }
/* ปุ่มตัวเลือกขั้นที่ 1 (segmented control / pills): ฟอนต์ 15px และ padding อวบขึ้น */
div[data-testid="stDialog"] [data-testid="stButtonGroup"] button { font-size: 15px !important; padding: 10px 16px !important; min-height: 44px; }
div[data-testid="stDialog"] [data-testid="stButtonGroup"] button p { font-size: 15px !important; }
/* ปุ่ม "ถัดไป" / "บันทึก" / "ย้อนกลับ": 16px ตัวหนา */
div[data-testid="stDialog"] [data-testid="stButton"] button,
div[data-testid="stDialog"] [data-testid="stFormSubmitButton"] button { font-size: 16px !important; font-weight: 700 !important; min-height: 46px; }
div[data-testid="stDialog"] [data-testid="stButton"] button p,
div[data-testid="stDialog"] [data-testid="stFormSubmitButton"] button p { font-size: 16px !important; font-weight: 700 !important; }
/* หัวข้อคำถามขั้นที่ 1 (####): 18px ให้เด่นกว่าปุ่มตัวเลือก */
div[data-testid="stDialog"] h4 { font-size: 18px !important; font-weight: 700 !important; padding: 0 0 6px 0 !important; }
/* เว้นช่องไฟระหว่างฟิลด์ให้โปร่ง ไม่เบียดเมื่อตัวอักษรใหญ่ขึ้น */
.st-key-entry_form_card [data-testid="stForm"] [data-testid="stVerticalBlock"] { gap: 1.1rem !important; }
div[data-testid="stDialog"] [data-testid="stVerticalBlock"] { gap: 0.9rem; }
.step-subtitle { font-size: 15px !important; color: #666; margin: 0 0 8px 0; }  /* ข้อความ "ขั้นตอนที่ X / 2" */

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
    vendor_name: str,
    tax_id: str,
    tel: str,
    email: str,
    sharepoint_url: str = "",
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


def save_document_and_get_path(uploaded_document: Optional[UploadedFile]) -> Optional[str]:
    """บันทึกไฟล์ที่ผู้ใช้เลือกลง local_uploads/ แล้วคืนที่อยู่ไฟล์

    Args:
        uploaded_document: ไฟล์จาก st.file_uploader (UploadedFile)

    Returns:
        ที่อยู่ไฟล์ (relative), หรือ None ถ้าบันทึกไม่สำเร็จ (แสดง st.error ให้แล้ว)
    """
    try:
        return save_document_locally(uploaded_document.getvalue(), uploaded_document.name)
    except LocalStorageError as error:
        st.error(f"❌ {error}")
        return None

    # --- SharePoint ปิดไว้: เตรียมไว้สำหรับเชื่อมต่อในอนาคต ---
    # เปิดใช้โดยแทนที่การเรียก save_document_locally ด้านบนด้วยโค้ดนี้ (และเปิด import ด้านบนไฟล์)
    # try:
    #     return upload_document_to_sharepoint(uploaded_document.getvalue(), uploaded_document.name)
    # except SharePointError as error:
    #     st.error(f"❌ {error}")
    #     return None


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

    # ไม่มีรายการค้าง (X = 0) -> ซ่อนแถบแจ้งเตือนทั้งหมด ไม่แสดงอะไรเลย
    if not overdue_transactions:
        return

    st.warning(
        f"⚠️ มีใบกำกับภาษีค้างเกิน {OVERDUE_DAYS_LIMIT} วัน จำนวน "
        f"{len(overdue_transactions)} รายการ กรุณาติดตามจากผู้ขาย"
    )
    # on_change="rerun" + เช็ค .open: วาดตารางเมื่อกางออกแล้วเท่านั้น (ตาราง AgGrid ที่ถูกสร้างตอนพับอยู่จะกว้าง 0 แล้วแสดงไม่ได้)
    overdue_expander = st.expander("ดูรายการที่ค้าง", on_change="rerun")
    if overdue_expander.open:
        with overdue_expander:
            overdue_table = pd.DataFrame(overdue_transactions)[
                ["id", "date", "vendor", "po_no", "total_price", "days_pending"]
            ]
            overdue_table.columns = ["รหัส", "วันที่", "ผู้ขาย", "เลขที่ PO", "ราคารวม (บาท)", "ค้างมาแล้ว (วัน)"]
            render_readonly_grid(
                overdue_table,
                key="overdue_grid",
                money_columns=("ราคารวม (บาท)",),
                right_aligned_columns=("รหัส", "ค้างมาแล้ว (วัน)"),
            )


# ---------------------------------------------------------------------------
# การ์ดตาราง (ฝั่งซ้าย): Search bar + Item/Vendor + ตาราง
# ---------------------------------------------------------------------------


def _valid_link_or_none(url: Optional[str]) -> Optional[str]:
    """คืน url ถ้าเป็นลิงก์ http(s) ที่ถูกต้อง ไม่เช่นนั้นคืน None (ใช้ก่อนแสดงเป็นลิงก์ในตาราง)"""
    return url if url and re.match(URL_PATTERN, url) else None


def _parse_iso_date_or_none(date_text: Optional[str]) -> Optional[date]:
    """แปลงข้อความ "YYYY-MM-DD" เป็น date, คืน None ถ้าว่างหรือรูปแบบผิด (ไม่ให้ทั้งตารางพัง)"""
    try:
        return date.fromisoformat(date_text) if date_text else None
    except (ValueError, TypeError):
        return None


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
        except (ValueError, TypeError):
            document_date = None  # วันที่ในฐานข้อมูลผิดรูปแบบ แสดงเป็นช่องว่าง (ไม่ให้ทั้งตารางพัง)

        display_rows.append(
            {
                "date": document_date,  # ชนิด date จริง รูปแบบ DD/MM/YYYY กำหนดที่ column_config
                "vendor": transaction["vendor"],
                "category": transaction.get("category") or "-",
                "total_price": float(transaction.get("total_price") or 0),  # ยังเป็นตัวเลข จัดรูปแบบตอนแสดง
                "invoice_status": get_status_label(transaction["invoice_status"], document_date, today),
                # --- ข้อมูล Master-List: ข้อความที่ไม่มีค่าแสดงเป็น "" (ถ้าเป็น None ตารางจะแสดงคำว่า None) ---
                "tel": transaction.get("tel") or "",
                "tax_id": transaction.get("tax_id") or "",
                "pr_run_no": transaction.get("pr_run_no") or "",
                "pr_request_date": _parse_iso_date_or_none(transaction.get("pr_request_date")),
                "qt_no": transaction.get("qt_no") or "",
                "description": transaction.get("description") or "",
                "unit_price": transaction.get("unit_price"),  # None = ยังไม่มีราคา แสดงเป็นช่องว่าง
                # ลิงก์ไฟล์บน SharePoint: ใส่เฉพาะที่ขึ้นต้น http(s):// (ที่เหลือเว้นว่าง ไม่แสดงไอคอน)
                # ไม่มีลิงก์ให้ใส่ "" (ถ้าใส่ None ตารางจะแสดงคำว่า None)
                "sharepoint_url": _valid_link_or_none(transaction.get("sharepoint_url")) or "",
            }
        )
    # หมายเหตุ: ตารางนี้ใช้ index ลำดับ 0,1,2,... (ไม่ใช่ id)
    # ถ้า index ไม่ใช่ลำดับ ส่วนการรู้ว่าแถวที่ n คือรายการ id อะไร ให้ดูจากลิสต์ id ที่เรียงเหมือนกัน
    # (ดู transaction_ids ใน render_table_card / apply_table_edits)
    return pd.DataFrame(display_rows, columns=list(TABLE_COLUMNS.keys())).rename(columns=TABLE_COLUMNS)


def build_update_fields(
    changes: dict[str, Any], original_row: pd.Series
) -> tuple[dict[str, Any], bool]:
    """แปลงค่าที่ผู้ใช้แก้ในตาราง (หนึ่งแถว) เป็นฟิลด์ที่จะอัปเดตลงฐานข้อมูล พร้อมตรวจความถูกต้อง

    Args:
        changes: ค่าที่แก้ {หัวคอลัมน์: ค่าใหม่} (จาก collect_grid_changes)
        original_row: แถวเดิมก่อนแก้ (ใช้ดูสถานะเดิม)

    Returns:
        (ฟิลด์ที่จะอัปเดต {ชื่อคอลัมน์ DB: ค่า}, มีการพยายามเปลี่ยนสถานะ Pending<->Overdue ที่ไม่ได้รับอนุญาตหรือไม่)

    Raises:
        ValueError: ถ้าค่าที่กรอกไม่ถูกต้อง (ข้อความอธิบายเป็นภาษาไทย)
    """
    label_to_column = {label: column for column, label in TABLE_COLUMNS.items()}
    fields: dict[str, Any] = {}
    status_change_ignored = False

    for column_label, new_value in changes.items():
        column = label_to_column.get(column_label)
        if column not in EDITABLE_TABLE_COLUMNS:
            continue  # คอลัมน์ที่ล็อกไว้ ไม่รับค่า

        if column == "date":
            # ค่าวันที่จากตารางอาจมาเป็นข้อความ ISO ("2026-10-24") หรืออ็อบเจกต์ date
            if not new_value:
                raise ValueError("วันที่ห้ามว่าง")
            fields["date"] = str(new_value)[:10] if not isinstance(new_value, date) else new_value.isoformat()
        elif column == "vendor":
            vendor_name = str(new_value or "").strip()
            if not vendor_name:
                raise ValueError("ชื่อผู้ขาย (Vendor) ห้ามว่าง")
            fields["vendor"] = vendor_name
        elif column == "category":
            fields["category"] = None if new_value in (None, "", NO_CATEGORY_LABEL) else str(new_value)
        elif column == "total_price":
            try:
                price = float(new_value)
            except (TypeError, ValueError):
                raise ValueError("ราคาต้องเป็นตัวเลข") from None
            if price < 0:
                raise ValueError("ราคาต้องไม่ติดลบ")
            fields["total_price"] = price
        elif column in MASTERLIST_TEXT_COLUMNS:
            # ข้อความล้วน: ว่างเก็บเป็น NULL
            text_value = str(new_value or "").strip()
            if column == "tel" and text_value and not re.match(TEL_PATTERN, text_value):
                raise ValueError("เบอร์โทรใช้ได้เฉพาะตัวเลข เว้นวรรค - + ( ) และยาว 6-20 ตัว")
            fields[column] = text_value or None
        elif column == "tax_id":
            tax_id_value = str(new_value or "").strip()
            if tax_id_value and not (tax_id_value.isdigit() and len(tax_id_value) == TAX_ID_LENGTH):
                raise ValueError(f"Tax ID ต้องเป็นตัวเลข {TAX_ID_LENGTH} หลัก")
            fields["tax_id"] = tax_id_value or None
        elif column == "pr_request_date":
            if not new_value:
                fields["pr_request_date"] = None
            elif isinstance(new_value, date):
                fields["pr_request_date"] = new_value.isoformat()
            else:
                try:
                    fields["pr_request_date"] = date.fromisoformat(str(new_value)[:10]).isoformat()
                except ValueError:
                    raise ValueError("วันที่ PR ต้องเป็นรูปแบบ ปปปป-ดด-วว เช่น 2026-10-24") from None
        elif column == "unit_price":
            if new_value in (None, ""):
                fields["unit_price"] = None
            else:
                try:
                    unit_price_value = float(new_value)
                except (TypeError, ValueError):
                    raise ValueError("ราคาสุทธิต้องเป็นตัวเลข") from None
                if unit_price_value < 0:
                    raise ValueError("ราคาสุทธิต้องไม่ติดลบ")
                fields["unit_price"] = unit_price_value
        elif column == "invoice_status":
            # Completed <-> ไม่ใช่ Completed บันทึกได้ ส่วน Pending <-> Overdue ระบบคำนวณเอง ไม่บันทึก
            was_completed = original_row[TABLE_COLUMNS["invoice_status"]] == STATUS_LABEL_COMPLETED
            will_be_completed = new_value == STATUS_LABEL_COMPLETED
            if was_completed == will_be_completed:
                status_change_ignored = True
            else:
                fields["invoice_status"] = STATUS_LABEL_TO_DB[new_value]

    return fields, status_change_ignored


def apply_table_edits(
    display_table: pd.DataFrame, transaction_ids: list[int], editor_state: dict[str, Any]
) -> list[tuple[str, str]]:
    """ซิงก์การแก้ไข/ลบในตาราง (AgGrid) กลับไปที่ตาราง transactions ในฐานข้อมูลทันที

    ใช้ editor_state ซึ่งมี 3 ส่วน (สร้างจากตาราง AgGrid ใน render_table_card):
      - edited_rows  : {ตำแหน่งแถว: {หัวคอลัมน์: ค่าใหม่}}  -> อัปเดตด้วย update_transaction
      - deleted_rows : [ตำแหน่งแถว, ...]                    -> ลบด้วย delete_transaction
      - added_rows   : แถวที่ผู้ใช้กดเพิ่มในตาราง           -> ไม่รับ (ให้ใช้ฟอร์ม "กรอก Form" แทน)
    "ตำแหน่งแถว" นับตามตารางเดิมที่แสดง จึงแปลงเป็น id รายการจาก transaction_ids

    Args:
        display_table: ตารางที่แสดงอยู่
        transaction_ids: id ของรายการในฐานข้อมูล เรียงเหมือนแถวของ display_table (แถวที่ n = transaction_ids[n])
        editor_state: ค่าสถานะการแก้ไขของตาราง (dict ที่มีคีย์ edited_rows / deleted_rows / added_rows)

    Returns:
        list ของ (ระดับข้อความ "success" / "error" / "info", ข้อความภาษาไทย) สำหรับแจ้งผู้ใช้
    """
    deleted_positions = {int(position) for position in editor_state.get("deleted_rows", [])}
    edited_rows = editor_state.get("edited_rows", {})
    added_rows = editor_state.get("added_rows", [])

    updated_count = deleted_count = delete_failed_count = update_failed_count = 0
    ignored_status_count = 0
    error_reasons: list[str] = []

    # --- ลบ (Delete) ---
    for position in sorted(deleted_positions):
        try:
            transaction_id = int(transaction_ids[position])
            if delete_transaction(transaction_id):
                deleted_count += 1
            else:
                delete_failed_count += 1  # delete_transaction แสดง error/warning ให้แล้ว
        except (IndexError, ValueError, TypeError) as error:
            delete_failed_count += 1
            error_reasons.append(f"ลบแถวที่ {position + 1}: {error}")

    # --- แก้ไข (Update) --- ข้ามแถวที่ถูกลบในรอบเดียวกัน
    for raw_position, changes in edited_rows.items():
        position = int(raw_position)
        if position in deleted_positions:
            continue
        try:
            transaction_id = int(transaction_ids[position])
            fields, status_ignored = build_update_fields(changes, display_table.iloc[position])
            ignored_status_count += int(status_ignored)
            if not fields:
                continue
            if update_transaction(transaction_id, **fields):  # update_transaction แสดง error ให้เองเมื่อล้มเหลว
                updated_count += 1
            else:
                update_failed_count += 1
        except ValueError as error:
            update_failed_count += 1
            error_reasons.append(f"แถวที่ {position + 1}: {error}")
        except (IndexError, TypeError, KeyError) as error:
            update_failed_count += 1
            error_reasons.append(f"แถวที่ {position + 1}: ข้อมูลไม่ถูกต้อง ({error})")

    messages: list[tuple[str, str]] = []
    if updated_count:
        messages.append(("success", f"✅ อัปเดตข้อมูลสำเร็จ {updated_count} รายการ"))
    if deleted_count:
        messages.append(("success", f"✅ ลบข้อมูลสำเร็จ {deleted_count} รายการ"))
    if delete_failed_count:
        messages.append(("error", f"❌ ไม่สามารถลบข้อมูลได้ {delete_failed_count} รายการ"))
    if update_failed_count:
        reason_text = f" ({'; '.join(error_reasons)})" if error_reasons else ""
        messages.append(("error", f"❌ ไม่สามารถอัปเดตข้อมูลได้ {update_failed_count} รายการ{reason_text}"))
    if added_rows:
        messages.append(
            ("info", 'ℹ️ เพิ่มรายการใหม่ไม่ได้จากตาราง กรุณาใช้ฟอร์ม "กรอก Form" ด้านขวา (แถวที่เพิ่มถูกยกเลิก)')
        )
    if ignored_status_count:
        messages.append(
            (
                "info",
                f"ℹ️ สถานะ Pending / Overdue ระบบกำหนดให้อัตโนมัติ (ค้างเกิน {OVERDUE_DAYS_LIMIT} วัน = Overdue) "
                "เปลี่ยนเองไม่ได้ เลือกได้เฉพาะ Completed เมื่อได้รับใบกำกับภาษีแล้ว",
            )
        )
    return messages


def build_grid_table(display_table: pd.DataFrame) -> pd.DataFrame:
    """แปลงตารางแสดงผล (หัวคอลัมน์เป็นป้ายไทย/อังกฤษ) เป็นตารางสำหรับ AgGrid (ชื่อคอลัมน์ = ชื่อใน DB)

    ต่างจาก display_table 3 อย่าง: ชื่อคอลัมน์เป็นชื่อใน DB, วันที่เป็นข้อความ "YYYY-MM-DD" (ไม่มี = ""),
    และมีคอลัมน์ลำดับแถว ROW_POSITION_COLUMN (ใช้จับคู่แถวตอนแก้ไข/ลบ แม้ผู้ใช้เรียงลำดับหรือกรองตาราง)

    Args:
        display_table: ตารางจาก build_table_for_display

    Returns:
        DataFrame พร้อมส่งให้ AgGrid
    """
    label_to_column = {label: column for column, label in TABLE_COLUMNS.items()}
    grid_table = display_table.rename(columns=label_to_column).reset_index(drop=True)
    for date_column in GRID_DATE_COLUMNS:
        grid_table[date_column] = grid_table[date_column].map(
            lambda value: value.isoformat() if isinstance(value, date) else ""
        )
    grid_table["unit_price"] = pd.to_numeric(grid_table["unit_price"], errors="coerce")  # ไม่มีราคา = ช่องว่าง
    grid_table.insert(0, ROW_POSITION_COLUMN, range(len(grid_table)))
    return grid_table


def build_transaction_grid_options(grid_table: pd.DataFrame) -> dict[str, Any]:
    """ตั้งค่าตาราง Master-List: คอลัมน์ไหนแก้ได้ / ชนิดข้อมูล / dropdown สถานะ / ไอคอนลิงก์ไฟล์

    ถ้าเพิ่มคอลัมน์ใหม่ในตาราง: เพิ่มชื่อใน TABLE_COLUMNS แล้วกำหนดชนิดตรงนี้ (เงิน -> money_columns, วันที่ -> GRID_DATE_COLUMNS)

    Args:
        grid_table: ตารางจาก build_grid_table

    Returns:
        gridOptions สำหรับ show_grid
    """
    extra_column_options: dict[str, dict[str, Any]] = {
        # คอลัมน์สถานะ: ดับเบิลคลิกแล้วเลือกจาก dropdown
        "invoice_status": {"cellEditor": "agSelectCellEditor", "cellEditorParams": {"values": STATUS_EDITOR_OPTIONS}},
        "unit_price": {"cellEditor": "agNumberCellEditor", "cellEditorParams": {"min": 0}},
        # คอลัมน์ไฟล์: แสดงเป็นไอคอน กดแล้วเปิดลิงก์ SharePoint ในแท็บใหม่ (ดู FILE_LINK_RENDERER_JS)
        "sharepoint_url": {
            "cellRenderer": JsCode(FILE_LINK_RENDERER_JS.replace("FILE_ICON", FILE_LINK_ICON)),
            "sortable": False,
            "filter": False,
        },
    }
    return build_grid_options(
        grid_table,
        header_names=TABLE_COLUMNS,
        column_widths=TABLE_COLUMN_WIDTHS,
        shrinkable_columns=SHRINKABLE_TABLE_COLUMNS,
        editable_columns=EDITABLE_TABLE_COLUMNS,
        money_columns=("total_price", "unit_price"),
        date_columns=GRID_DATE_COLUMNS,
        hidden_columns=(ROW_POSITION_COLUMN,),
        selectable=True,
        paginated=True,
        filterable=True,
        extra_column_options=extra_column_options,
    )


def _normalize_cell_value(value: Any) -> Any:
    """ทำให้ค่าในเซลล์เทียบกันได้: ว่าง / NaN / None ถือเป็น None, ข้อความตัดช่องว่างหัวท้าย"""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, str):
        return value.strip() or None
    return value


def collect_grid_changes(original_table: pd.DataFrame, grid_response: Any) -> dict[int, dict[str, Any]]:
    """เทียบตารางที่ AgGrid ส่งกลับมากับตารางเดิม เพื่อหาเซลล์ที่ผู้ใช้แก้ไข

    Args:
        original_table: ตารางเดิมที่ส่งให้ AgGrid (จาก build_grid_table)
        grid_response: ผลจาก show_grid (None ถ้าตารางวาดไม่สำเร็จ หรือยังไม่ส่งค่ากลับ)

    Returns:
        {ตำแหน่งแถว: {หัวคอลัมน์: ค่าใหม่}} รูปแบบ edited_rows (ส่งต่อให้ apply_table_edits ได้เลย)
    """
    returned_table = getattr(grid_response, "data", None)
    if returned_table is None or len(returned_table) == 0 or ROW_POSITION_COLUMN not in returned_table.columns:
        return {}

    returned_by_position = returned_table.drop_duplicates(ROW_POSITION_COLUMN).set_index(
        returned_table.drop_duplicates(ROW_POSITION_COLUMN)[ROW_POSITION_COLUMN].astype(int)
    )
    changes_by_position: dict[int, dict[str, Any]] = {}
    for _, original_row in original_table.iterrows():
        position = int(original_row[ROW_POSITION_COLUMN])
        if position not in returned_by_position.index:
            continue
        row_changes: dict[str, Any] = {}
        for column in EDITABLE_TABLE_COLUMNS:
            original_value = _normalize_cell_value(original_row[column])
            new_value = _normalize_cell_value(returned_by_position.at[position, column])
            if original_value != new_value:
                row_changes[TABLE_COLUMNS[column]] = new_value
        if row_changes:
            changes_by_position[position] = row_changes
    return changes_by_position


def get_selected_positions(grid_response: Any) -> list[int]:
    """อ่านตำแหน่งแถวที่ผู้ใช้ติ๊กเลือกในตาราง (ใช้กับปุ่มลบ)

    Args:
        grid_response: ผลจาก show_grid (None = ไม่มีแถวที่เลือก)

    Returns:
        ตำแหน่งแถวตาม ROW_POSITION_COLUMN (ว่างถ้าไม่ได้เลือก)
    """
    selected_rows = getattr(grid_response, "selected_rows", None)
    if selected_rows is None or len(selected_rows) == 0:
        return []
    # selected_rows อาจเป็น DataFrame หรือ list ของ dict ตามเวอร์ชันของไลบรารี รองรับทั้งสองแบบ
    records = selected_rows.to_dict("records") if isinstance(selected_rows, pd.DataFrame) else list(selected_rows)
    return sorted({int(record[ROW_POSITION_COLUMN]) for record in records if record.get(ROW_POSITION_COLUMN) is not None})


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
        # แถบตัวกรองแถวเดียว: ช่องค้นหา (กว้างสุด) + dropdown Item + dropdown Vendor
        # ถ้าจะเพิ่มตัวกรองใหม่ ให้เพิ่มสัดส่วนใน st.columns ด้านล่าง แล้วเพิ่มเงื่อนไขกรองต่อจาก selected_vendor
        search_column, item_column, vendor_column = st.columns([3, 1.3, 1.7])

        # ช่องค้นหา: ค้นในชื่อผู้ขาย, เลข PO, เลขรัน PR, Tax ID (ดู database.get_transactions)
        search_keyword = search_column.text_input(
            "Search bar",
            placeholder="🔍 ค้นหา (ผู้ขาย, เลข PO, เลขรัน PR, Tax ID)",
            label_visibility="collapsed",
        ).strip()

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

        # เส้นคั่นระหว่างตัวกรองกับตาราง ให้สายตาแยกส่วนได้ชัด
        st.divider()

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

            # ตาราง AgGrid แบบแก้ไข/ลบได้ (CRUD): ดับเบิลคลิกช่องเพื่อแก้ไขค่า / ติ๊กเลือกแถวแล้วกดปุ่ม "ลบ" เพื่อลบ
            # ทุกการแก้ไขหรือลบจะถูกซิงก์ลงฐานข้อมูลทันที (ดู apply_table_edits)
            editor_version = st.session_state.setdefault(SESSION_KEY_EDITOR_VERSION, 0)
            transaction_ids = [t["id"] for t in visible_transactions]  # แถวที่ n ในตาราง = transaction_ids[n]

            # ปุ่มลบอยู่เหนือตาราง แต่ต้องรู้แถวที่เลือกจากตารางก่อน จึงจองที่ไว้แล้วเติมหลังวาดตาราง
            action_bar = st.container()

            grid_table = build_grid_table(display_table)
            # key = เลขเวอร์ชัน (เปลี่ยนเมื่อบันทึกแล้ว) + ค่าแฮชของข้อมูล: ข้อมูลที่แสดงเปลี่ยน (ค้นหา / กรอง / Date Filter)
            # ตารางจะถูกสร้างใหม่ ไม่เอาค่าที่ส่งกลับของข้อมูลชุดเก่ามาเทียบ (กันเขียนค่าผิดแถวลงฐานข้อมูล)
            data_hash = int(pd.util.hash_pandas_object(grid_table, index=False).sum() % 10**9)
            grid_key = f"transaction_grid_{editor_version}_{data_hash}"
            grid_response = show_grid(
                grid_table,
                build_transaction_grid_options(grid_table),
                grid_key,
                update_on=["cellValueChanged", "selectionChanged"],  # ส่งค่ากลับเมื่อแก้ไขเซลล์ / เปลี่ยนแถวที่เลือก
            )

            editor_state: dict[str, Any] = {
                "edited_rows": collect_grid_changes(grid_table, grid_response),
                "deleted_rows": [],
            }
            selected_positions = get_selected_positions(grid_response)
            with action_bar:
                is_delete_clicked = st.button(
                    f"🗑️ ลบรายการที่เลือก ({len(selected_positions)})",
                    key="delete_selected_rows",
                    disabled=not selected_positions,
                    help="ติ๊กช่องหน้าแถวที่ต้องการลบ แล้วกดปุ่มนี้",
                )
            if is_delete_clicked:
                editor_state["deleted_rows"] = selected_positions

            has_changes = bool(editor_state["edited_rows"] or editor_state["deleted_rows"])
            if has_changes:
                try:
                    st.session_state[SESSION_KEY_STATUS_MESSAGES] = apply_table_edits(
                        display_table, transaction_ids, editor_state
                    )
                except (ValueError, TypeError, KeyError, IndexError, AttributeError) as error:
                    # error ของแถวเดี่ยว ๆ apply_table_edits จัดการเองแล้ว ที่หลุดมาถึงนี่คือข้อมูลตารางผิดรูปแบบทั้งก้อน
                    logger.error("บันทึกการแก้ไขตารางไม่สำเร็จ: %s", error, exc_info=True)
                    st.session_state[SESSION_KEY_STATUS_MESSAGES] = [
                        ("error", f"❌ บันทึกการเปลี่ยนแปลงไม่สำเร็จ: ลองรีเฟรชหน้าเว็บ รายละเอียด: {error}")
                    ]
                st.session_state[SESSION_KEY_EDITOR_VERSION] = editor_version + 1
                # บันทึกลง SQLite เสร็จแล้ว -> รีรันทั้งหน้าทันที เพื่อให้แถบแจ้งเตือน Overdue (render_overdue_alert)
                # และตัวเลขสรุปต่าง ๆ query ค่าล่าสุดจากฐานข้อมูลใหม่
                st.rerun()


# ---------------------------------------------------------------------------
# ส่วนที่ 2: การ์ด Upload File (กล่องลากไฟล์ 2 ช่อง)
# ---------------------------------------------------------------------------


def _prefill_form_from_purchase_document(purchase_document: UploadedFile, form_counter: int) -> str:
    """ดึง TaxID / Vendor จากไฟล์ PO แล้วเติมลงช่องของฟอร์ม

    ต้องเรียกก่อนที่ฟอร์มจะถูกวาดในรอบเดียวกัน (ดูลำดับใน render()) เพราะ Streamlit
    ให้ตั้งค่าช่องผ่าน session_state ได้เฉพาะก่อนช่องนั้นถูกสร้าง

    Args:
        purchase_document: ไฟล์ที่ผู้ใช้อัปโหลด (UploadedFile)
        form_counter: ตัวนับของฟอร์มปัจจุบัน (ใช้สร้าง key ของช่อง)

    Returns:
        ข้อความสรุปผลให้แสดงผู้ใช้ (ว่างไม่ได้ เพราะต้องบอกผู้ใช้เสมอว่าต้องตรวจเอง)
    """
    if not purchase_document.name.lower().endswith(AUTO_EXTRACT_EXTENSIONS):
        return "⚠️ ไฟล์รูปภาพยังดึงข้อความอัตโนมัติไม่ได้ กรุณากรอกข้อมูลเอง"

    # เลือกวิธีอ่านตามนามสกุล (PDF / Excel) ถ้าอ่านไม่ได้ฟิลด์จะว่างและระบบแจ้งให้กรอกเอง
    extracted_fields = extract_fields_from_file(purchase_document, purchase_document.name)

    # เติมเฉพาะฟิลด์ที่หาเจอ (ค่าว่างไม่เขียนทับสิ่งที่ผู้ใช้พิมพ์ไว้)
    if extracted_fields.tax_id:
        st.session_state[_field_key("tax_id", form_counter)] = extracted_fields.tax_id
    if extracted_fields.vendor:
        st.session_state[_field_key("vendor", form_counter)] = extracted_fields.vendor
    if extracted_fields.total_amount:
        st.session_state[_field_key("total_price", form_counter)] = float(extracted_fields.total_amount)

    # ฟิลด์ Master-List (โครงร่างการสกัดยังเป็น Logic จำลอง) ชื่อฟิลด์ตรงกับ key ของช่องในฟอร์ม
    # ถ้าเพิ่มฟิลด์ข้อความใหม่ ให้เพิ่มชื่อในรายการนี้
    for text_field_name in ("tel", "pr_run_no", "qt_no", "description"):
        extracted_value = getattr(extracted_fields, text_field_name)
        if extracted_value:
            st.session_state[_field_key(text_field_name, form_counter)] = extracted_value
    pr_request_date = _parse_iso_date_or_none(extracted_fields.pr_request_date)
    if pr_request_date:
        st.session_state[_field_key("pr_request_date", form_counter)] = pr_request_date
    if extracted_fields.unit_price:
        st.session_state[_field_key("unit_price", form_counter)] = float(extracted_fields.unit_price)

    if extracted_fields.warning_message:
        return f"⚠️ {extracted_fields.warning_message}"
    return "✅ เติมข้อมูลจากไฟล์ให้แล้ว กรุณาตรวจความถูกต้องก่อนกด Upload"


def render_upload_section(form_counter: int) -> None:
    """วาดการ์ด "Upload File": กล่องลากไฟล์ Purchase และ SharePoint

    - Purchase: อ่านไฟล์ PDF แล้วเติม TaxID/Vendor ลงฟอร์มให้ และแนบไฟล์นี้กับรายการเมื่อกด Upload
    - กล่องที่ 2: บันทึกไฟล์ลง local_uploads/ ทันที แล้วเก็บที่อยู่ไฟล์ไว้ผูกกับรายการเมื่อกด Upload
      (SharePoint ปิดไว้ เตรียมไว้สำหรับเชื่อมต่อในอนาคต)

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

    # --- กล่องที่ 2: Upload P/O (เก็บในเครื่อง local_uploads/) ---
    # เลือกไฟล์แล้วบันทึกทันที เก็บที่อยู่ไฟล์ไว้ใน session แล้วผูกกับรายการเมื่อกดปุ่ม Upload ในแท็บฟอร์ม
    # (SharePoint ปิดไว้ เตรียมไว้สำหรับเชื่อมต่อในอนาคต — ดู save_document_and_get_path)
    st.markdown('<div class="card-section-label">Upload P/O (เก็บในเครื่อง)</div>', unsafe_allow_html=True)
    local_document = st.file_uploader(
        "Upload P/O (เก็บในเครื่อง)",
        type=ALLOWED_FILE_TYPES,
        key=_field_key("local_uploader", form_counter),
        label_visibility="collapsed",
    )
    if local_document is None:
        st.session_state.pop(SESSION_KEY_LOCAL_FILE_ID, None)
        st.session_state.pop(SESSION_KEY_LOCAL_NOTICE, None)
        st.session_state.pop(SESSION_KEY_LOCAL_PATH, None)
    else:
        # บันทึกแค่ครั้งเดียวต่อไฟล์ (Streamlit รันสคริปต์ซ้ำทุกครั้งที่มีการกดอะไรสักอย่าง)
        local_file_id = f"{local_document.name}:{local_document.size}:{form_counter}"
        if st.session_state.get(SESSION_KEY_LOCAL_FILE_ID) != local_file_id:
            st.session_state[SESSION_KEY_LOCAL_FILE_ID] = local_file_id
            try:
                saved_path = save_document_locally(local_document.getvalue(), local_document.name)
                st.session_state[SESSION_KEY_LOCAL_PATH] = saved_path
                st.session_state[SESSION_KEY_LOCAL_NOTICE] = (
                    "success",
                    f"✅ บันทึกไฟล์แล้ว กด Upload ในแท็บ \"กรอก Form\" เพื่อผูกไฟล์กับรายการ: {saved_path}",
                )
            except LocalStorageError as error:
                st.session_state.pop(SESSION_KEY_LOCAL_PATH, None)
                st.session_state[SESSION_KEY_LOCAL_NOTICE] = ("error", f"❌ {error}")

        notice_level, notice_message = st.session_state.get(SESSION_KEY_LOCAL_NOTICE, ("", ""))
        if notice_level == "error":
            st.error(notice_message)
        elif notice_message:
            st.caption(notice_message)


# ---------------------------------------------------------------------------
# ส่วนที่ 1: การ์ดกรอกข้อมูล (ฟอร์ม)
# ---------------------------------------------------------------------------


def go_to_main_form_step(form_counter: int) -> None:
    """Callback ปุ่ม "ถัดไป": จำคำตอบขั้นที่ 1 แล้วตั้งเป็นค่าเริ่มต้นของฟอร์มขั้นที่ 2

    ใช้เป็น on_click เพื่อให้ทำงานก่อนหน้าต่างถูกวาดใหม่ (ตั้งค่าช่องฟอร์มได้ก่อนช่องถูกสร้าง จึงไม่เกิด Error)
    ถ้าจะให้คำตอบขั้นที่ 1 เติมช่องอื่นเพิ่ม: เพิ่มบรรทัด st.session_state[_field_key("ชื่อช่อง", form_counter)] = ... ตรงนี้

    Args:
        form_counter: ตัวนับของฟอร์มปัจจุบัน (ใช้สร้าง key ของช่อง)
    """
    selected_item: Optional[str] = st.session_state.get(WIDGET_KEY_STEP1_ITEM)
    selected_invoice_choice: Optional[str] = st.session_state.get(WIDGET_KEY_STEP1_INVOICE)
    if selected_item is None or selected_invoice_choice is None:
        return  # ยังเลือกไม่ครบ (ปุ่มถัดไปถูกปิดไว้แล้ว กันซ้ำอีกชั้น)

    # เก็บคำตอบไว้ใน key ธรรมดา (ค่าของปุ่มเลือกจะหายเมื่อไม่ได้วาดในรอบถัดไป)
    st.session_state[SESSION_KEY_ENTRY_ITEM] = selected_item
    st.session_state[SESSION_KEY_ENTRY_HAS_INVOICE] = selected_invoice_choice
    # ตั้งค่าเริ่มต้นให้ช่องในฟอร์ม ผู้ใช้ไม่ต้องเลือกซ้ำ
    st.session_state[_field_key("category", form_counter)] = selected_item
    st.session_state[_field_key("invoice_choice", form_counter)] = selected_invoice_choice
    st.session_state[SESSION_KEY_FORM_STEP] = FORM_STEP_MAIN_FORM


def go_back_to_questions_step() -> None:
    """Callback ปุ่ม "ย้อนกลับ": กลับไปขั้นที่ 1 (ค่าที่กรอกในฟอร์มขั้นที่ 2 จะถูกล้าง)"""
    st.session_state[SESSION_KEY_FORM_STEP] = FORM_STEP_QUESTIONS


def render_questions_step(form_counter: int) -> None:
    """วาดขั้นที่ 1: ถามประเภท (Item) และสถานะใบกำกับภาษี แล้วปุ่ม "ถัดไป"

    ถ้าจะเพิ่มคำถามใหม่: เพิ่ม st.segmented_control ตรงนี้ แล้วอ่านค่าใน go_to_main_form_step

    Args:
        form_counter: ตัวนับของฟอร์มปัจจุบัน (ส่งต่อให้ callback)
    """
    st.markdown('<p class="step-subtitle">ขั้นตอนที่ 1 / 2 — ข้อมูลเบื้องต้น</p>', unsafe_allow_html=True)

    st.markdown("#### ประเภทของ PR/PO (Item):")
    selected_item = st.segmented_control(
        "ประเภทของ PR/PO (Item)",
        STEP1_ITEM_OPTIONS,
        selection_mode="single",
        default=st.session_state.get(SESSION_KEY_ENTRY_ITEM, STEP1_ITEM_OPTIONS[0]),
        key=WIDGET_KEY_STEP1_ITEM,
        label_visibility="collapsed",
    )

    st.write("")  # เว้นระยะระหว่างสองคำถาม
    st.markdown("#### สถานะใบกำกับภาษี:")
    selected_invoice_choice = st.segmented_control(
        "สถานะใบกำกับภาษี",
        INVOICE_CHOICE_OPTIONS,
        selection_mode="single",
        default=st.session_state.get(SESSION_KEY_ENTRY_HAS_INVOICE, INVOICE_CHOICE_NOT_YET),
        key=WIDGET_KEY_STEP1_INVOICE,
        label_visibility="collapsed",
    )

    # segmented_control กดซ้ำเพื่อยกเลิกการเลือกได้ (ค่าเป็น None) จึงปิดปุ่มถัดไปไว้จนกว่าจะเลือกครบ
    is_answered = selected_item is not None and selected_invoice_choice is not None
    if not is_answered:
        st.caption("⚠️ กรุณาเลือกให้ครบทั้ง 2 ข้อ")
    st.write("")  # เว้นระยะก่อนปุ่มถัดไป
    st.button(
        "ถัดไป ➡️",
        type="primary",
        width="stretch",
        disabled=not is_answered,
        on_click=go_to_main_form_step,
        args=(form_counter,),
        key="step1_next_button",
    )


def _labeled_text_input(label_text: str, field_name: str, form_counter: int) -> str:
    """วาดแถวฟิลด์: ป้ายชื่อด้านซ้าย ช่องกรอกด้านขวา (ตามดีไซน์) แล้วคืนค่าที่กรอก

    Args:
        label_text: ข้อความป้ายชื่อ เช่น "TaxID"
        field_name: ชื่อภายในของช่อง (ใช้สร้าง key)
        form_counter: ตัวนับของฟอร์มปัจจุบัน

    Returns:
        ข้อความที่ผู้ใช้กรอก (ตัดช่องว่างหัวท้ายแล้ว)
    """
    label_column, input_column = st.columns([1, 2], vertical_alignment="center")
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
        # ส่วนที่ 1: ช่องกรอกข้อมูล เรียงแนวตั้ง 1 คอลัมน์ เพราะหน้าต่างแคบ (เพิ่มช่องใหม่ต่อท้ายกลุ่มที่ต้องการตรงนี้)
        # ถ้าขยายหน้าต่างเป็น width="large" ให้เปลี่ยน 2 บรรทัดนี้กลับเป็น st.columns(2, gap="large") ได้
        left_fields = st.container()
        right_fields = st.container()
        with left_fields:
            tax_id = _labeled_text_input("TaxID", "tax_id", form_counter)
            purchase_order_number = _labeled_text_input("P/O No.", "po_no", form_counter)
            pr_run_number = _labeled_text_input("PR Run No.", "pr_run_no", form_counter)
            vendor_name = _labeled_text_input("Vendor", "vendor", form_counter)
        with right_fields:
            tel = _labeled_text_input("Tel.", "tel", form_counter)
            email = _labeled_text_input("Email", "email", form_counter)
            contact_name = _labeled_text_input("Name", "contact_name", form_counter)
            date_label_column, date_input_column = st.columns([1, 2], vertical_alignment="center")
            date_label_column.markdown('<div class="field-label">Date :</div>', unsafe_allow_html=True)
            document_date = date_input_column.date_input(
                "Date",
                value=date.today(),
                format="DD/MM/YYYY",
                key=_field_key("date", form_counter),
                label_visibility="collapsed",
            )
            # สถานะใบกำกับภาษี: ค่าเริ่มต้นมาจากขั้นที่ 1 (ตั้งไว้ใน go_to_main_form_step) แก้ได้ที่นี่
            invoice_label_column, invoice_input_column = st.columns([1, 2], vertical_alignment="center")
            invoice_label_column.markdown('<div class="field-label">ใบกำกับภาษี :</div>', unsafe_allow_html=True)
            invoice_choice = invoice_input_column.selectbox(
                "สถานะใบกำกับภาษี",
                INVOICE_CHOICE_OPTIONS,
                index=1,  # ถ้าไม่มีค่าจากขั้นที่ 1 ให้เป็น "ยังไม่มีใบกำกับภาษี"
                key=_field_key("invoice_choice", form_counter),
                label_visibility="collapsed",
            )

        # ข้อมูลจากเอกสาร PR / Quotation (Master-List, ไม่บังคับ): ระบบเติมให้จากไฟล์ PDF ผู้ใช้ตรวจ/แก้ได้
        # ถ้าจะเพิ่มฟิลด์ใหม่: เพิ่มช่องตรงนี้ + ส่งค่าเข้า add_transaction ด้านล่าง
        with st.expander("ข้อมูลจากเอกสาร PR / Quotation (ไม่บังคับ)"):
            qt_no = st.text_input("เลขที่ Quotation", key=_field_key("qt_no", form_counter)).strip()
            pr_request_date = st.date_input(
                "วันที่ PR",
                value=None,  # None = ยังไม่ระบุ (ไม่บังคับ) ผู้ใช้เลือกเองหรือรอระบบเติมจากไฟล์
                format="DD/MM/YYYY",
                key=_field_key("pr_request_date", form_counter),
            )
            description = st.text_area("รายละเอียดอุปกรณ์", key=_field_key("description", form_counter)).strip()
            unit_price = st.number_input(
                "ราคาสุทธิที่รวม Discount แล้ว (บาท)",
                min_value=0.0,
                step=100.0,
                format="%.2f",
                key=_field_key("unit_price", form_counter),
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

        # ส่วนที่ 3: ปุ่ม ย้อนกลับ + บันทึกข้อมูล (ปุ่มย้อนกลับต้องเป็น form_submit_button เพราะอยู่ในฟอร์ม
        # และใช้ on_click ทำงานก่อนหน้าถูกวาดใหม่ จึงไม่เกิด Error ตอนเปลี่ยนหน้า)
        back_column, save_column = st.columns([1, 2])
        back_column.form_submit_button("⬅️ ย้อนกลับ", on_click=go_back_to_questions_step, width="stretch")
        is_submitted = save_column.form_submit_button("บันทึกข้อมูล", type="primary", width="stretch")

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

    # ที่อยู่ไฟล์ในเครื่อง เลือกตามลำดับ: (1) ไฟล์ที่แนบใต้ฟอร์ม/กล่อง Purchase บันทึกตอนนี้เลย
    # (2) ไฟล์ที่บันทึกไว้แล้วจากแท็บ Upload File — ถ้า (1) ไม่สำเร็จจะไม่บันทึกรายการ เพื่อไม่ให้ไฟล์หายไปเงียบๆ
    final_file_path: Optional[str] = st.session_state.get(SESSION_KEY_LOCAL_PATH)
    if document_to_attach is not None:
        final_file_path = save_document_and_get_path(document_to_attach)
        if final_file_path is None:
            return  # save_document_and_get_path แสดง error ให้แล้ว

    new_transaction_id = add_transaction(
        date=document_date.isoformat(),  # เก็บเป็น ค.ศ. รูปแบบ YYYY-MM-DD
        vendor=vendor_name,
        total_price=total_price,
        tax_id=tax_id or None,
        po_no=purchase_order_number or None,
        pr_run_no=pr_run_number or None,
        category=category_name,
        tel=tel or None,
        email=email or None,
        contact_name=contact_name or None,
        file_path=final_file_path,
        invoice_status=INVOICE_CHOICE_TO_DB[invoice_choice],
        sharepoint_url=sharepoint_url or None,  # ลิงก์ที่กรอกเอง (ไม่บังคับ) ยังใช้ได้ตามเดิม
        pr_request_date=pr_request_date.isoformat() if pr_request_date else None,
        qt_no=qt_no or None,
        description=description or None,
        unit_price=unit_price or None,  # 0 = ไม่ได้กรอก เก็บเป็น NULL
    )

    if new_transaction_id is None:
        return  # add_transaction แสดง error ให้แล้ว (ไฟล์ที่บันทึกไปแล้วยังอยู่ ผู้ใช้กดบันทึกซ้ำได้)

    # ส่วนที่ 5: บันทึกสำเร็จ -> เคลียร์ฟอร์มแล้วโหลดหน้าใหม่
    st.session_state[SESSION_KEY_SUCCESS_MESSAGE] = (
        f"✅ บันทึกรายการเรียบร้อย (รหัสรายการ {new_transaction_id})"
    )
    st.session_state[SESSION_KEY_FORM_COUNTER] = form_counter + 1
    st.session_state[SESSION_KEY_FORM_STEP] = FORM_STEP_QUESTIONS  # เปิดครั้งหน้าเริ่มที่ขั้นที่ 1 เสมอ
    st.rerun()


# ---------------------------------------------------------------------------
# จุดเข้าของหน้า
# ---------------------------------------------------------------------------


# width="small" ให้หน้าต่างกระชับ (ฟอร์มขั้นที่ 2 จึงเรียงช่องแนวตั้ง 1 คอลัมน์) ถ้าอยากกว้างขึ้นเปลี่ยนเป็น "medium"
@st.dialog("เพิ่มข้อมูล / อัปโหลดเอกสาร", width="small")
def render_entry_dialog(form_counter: int) -> None:
    """หน้าต่างป๊อปอัป "เพิ่มข้อมูล / อัปโหลดเอกสาร": แท็บ [กรอก Form | Upload File]

    ภายในใช้ฟังก์ชันเดิมทั้งหมด (render_upload_section / render_entry_form) ไม่เปลี่ยน Logic
    - ปุ่ม Upload สำเร็จ -> render_entry_form สั่ง st.rerun() ทั้งหน้า หน้าต่างจะปิดเองและตารางอัปเดต
    - กรอกไม่ครบ/บันทึกไม่สำเร็จ -> หน้าต่างค้างไว้พร้อมข้อความ error ข้อมูลที่กรอกไม่หาย
    - ปิดหน้าต่างด้วยปุ่ม x ได้เสมอ (ค่าที่กรอกค้างจะถูกล้างเมื่อเปิดใหม่)

    Args:
        form_counter: ตัวนับของฟอร์มปัจจุบัน
    """
    # ขั้นตอนปัจจุบัน (ค่าเริ่มต้น = ขั้นที่ 1) ถ้ายังไม่มีคำตอบจากขั้นที่ 1 ห้ามข้ามไปขั้นที่ 2
    current_step: int = st.session_state.get(SESSION_KEY_FORM_STEP, FORM_STEP_QUESTIONS)
    if current_step == FORM_STEP_MAIN_FORM and SESSION_KEY_ENTRY_ITEM not in st.session_state:
        current_step = FORM_STEP_QUESTIONS

    if current_step == FORM_STEP_QUESTIONS:
        render_questions_step(form_counter)
        return

    st.markdown(
        f'<p class="step-subtitle">ขั้นตอนที่ 2 / 2 — {st.session_state[SESSION_KEY_ENTRY_ITEM]} · '
        f'{st.session_state[SESSION_KEY_ENTRY_HAS_INVOICE]}</p>',
        unsafe_allow_html=True,
    )
    with st.container(key="right_panel"):  # key นี้ใช้ให้ CSS ข้อ 1 จับแท็บ
        form_tab, upload_tab = st.tabs(["กรอก Form", "Upload File"])

        # ข้อควรระวัง: ต้อง "เขียนโค้ด" วาดแท็บอัปโหลดก่อนแท็บฟอร์ม เพราะมันเติมค่าลงช่องของฟอร์ม
        # (Streamlit ตั้งค่าช่องผ่าน session_state ได้เฉพาะก่อนช่องนั้นถูกสร้างในรอบนั้น)
        # ส่วนลำดับบนหน้าจอถูกกำหนดโดย st.tabs ด้านบนแล้ว จึงไม่กระทบ
        with upload_tab, st.container(key="upload_card"):
            render_upload_section(form_counter)
        with form_tab, st.container(key="entry_form_card"):
            render_entry_form(form_counter)


def render_add_button(form_counter: int) -> None:
    """วาดแถบหัวเรื่องของตาราง: ชื่อส่วน (ซ้าย) + ปุ่ม "เพิ่มข้อมูล / อัปโหลดเอกสาร" (ขวา)

    กดปุ่มแล้วเปิดหน้าต่างฟอร์ม/อัปโหลด (ชื่อหน้าหลักและ Date Filter วาดโดย app.py แล้ว)

    Args:
        form_counter: ตัวนับของฟอร์มปัจจุบัน (ส่งต่อให้หน้าต่าง)
    """
    # key="table_header_row" ใช้ให้ CSS (PAGE_CSS_RULES ข้อ 1.2) จับแถวนี้ เพื่อชิดปุ่มขวาและลดช่องว่างใต้หัวข้อ
    # vertical_alignment="center" ทำให้ปุ่มอยู่กึ่งกลางแนวตั้งเสมอกับชื่อส่วน ไม่ต้องใช้เว้นบรรทัดช่วย
    # สัดส่วน [8, 2]: ปรับตัวเลขเพื่อเปลี่ยนความกว้างปุ่ม (ปุ่มจะเต็มความกว้างของคอลัมน์ขวาเสมอ)
    with st.container(key="table_header_row"):
        title_column, button_column = st.columns([8, 2], vertical_alignment="center")
        title_column.subheader("ตารางข้อมูล Master-List")
        if button_column.button(
            "➕ เพิ่มข้อมูล / อัปโหลดเอกสาร", type="primary", width="stretch", key="open_entry_dialog"
        ):
            # เปิดหน้าต่างทุกครั้งเริ่มที่ขั้นที่ 1 (รวมกรณีปิดด้วยปุ่ม x ระหว่างขั้นที่ 2)
            st.session_state[SESSION_KEY_FORM_STEP] = FORM_STEP_QUESTIONS
            render_entry_dialog(form_counter)


def render_equipment_summary(start_date: date, end_date: date) -> None:
    """วาดสรุป Quantity of equipment (HW / SW / NW / Service) ใต้ตาราง แบบกางออก/พับเก็บได้

    Args:
        start_date: วันที่เริ่มต้นจาก Date Filter
        end_date: วันที่สิ้นสุดจาก Date Filter
    """
    # วาดตารางเมื่อกางออกแล้วเท่านั้น (เหตุผลเดียวกับแถบ "ดูรายการที่ค้าง" ใน render_overdue_alert)
    equipment_expander = st.expander("Quantity of equipment", expanded=False, on_change="rerun")
    if equipment_expander.open:
        with equipment_expander:
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

    # แสดงผลการเปลี่ยนสถานะจากตารางครั้งก่อน (เก็บไว้ข้ามการ rerun) แล้วลบทิ้งไม่ให้แสดงซ้ำ
    for message_level, message_text in st.session_state.pop(SESSION_KEY_STATUS_MESSAGES, []):
        if message_level == "success":
            st.toast(message_text)  # สำเร็จ: แจ้งแบบ Toast มุมจอ ไม่กินพื้นที่
        else:
            getattr(st, message_level)(message_text)  # ล้มเหลว/ข้อมูล: กล่อง st.error / st.info ค้างไว้ให้อ่าน

    # ส่วนที่ 1: แจ้งเตือนใบกำกับภาษีค้าง (เต็มความกว้าง อยู่บนสุดเพื่อให้เห็นก่อน)
    # ลำดับการทำงาน: แถบนี้นับจาก DB ทุกครั้งที่หน้ารันใหม่ ส่วนการบันทึกการแก้ไขตารางอยู่ถัดลงไป (render_table_card)
    # ซึ่งจะสั่ง st.rerun() ทันทีหลังบันทึกเสร็จ -> รอบใหม่จึงนับจาก DB ที่อัปเดตแล้วเสมอ (ตัวเลขไม่ค้างค่าเก่า)
    render_overdue_alert()

    form_counter: int = st.session_state.setdefault(SESSION_KEY_FORM_COUNTER, 0)
    range_transactions = get_transactions(start_date.isoformat(), end_date.isoformat())

    # ส่วนที่ 2: ปุ่มเปิดหน้าต่าง "เพิ่มข้อมูล / อัปโหลดเอกสาร" (ฟอร์ม + อัปโหลดไฟล์ อยู่ใน render_entry_dialog)
    render_add_button(form_counter)

    # ส่วนที่ 3: การ์ดตาราง เต็มความกว้าง (Search bar + Item/Vendor + ตาราง)
    render_table_card(range_transactions, start_date, end_date)

    # ส่วนที่ 4: สรุปอุปกรณ์ (พับเก็บได้) อยู่ใต้ตาราง
    render_equipment_summary(start_date, end_date)
