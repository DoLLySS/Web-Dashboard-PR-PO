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

import io
import json
import re
from datetime import date
from typing import Any, Optional

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from streamlit.runtime.uploaded_file_manager import UploadedFile

from config.constants import CATEGORY_OPTIONS
from config.logging_setup import get_logger
from data.database import (
    STATUS_PENDING,
    STATUS_RECEIVED,
    add_transaction,
    delete_transaction,
    get_transactions,
    get_unique_vendors,
    update_transaction,
)
from utils.local_storage import LocalStorageError, save_document_locally

# SharePoint เตรียมโครงไว้พร้อมสลับเปิด: จะอัปโหลดจริงก็ต่อเมื่อตั้งค่า SHAREPOINT_* ใน .env ครบ (ไม่ตั้ง = ข้ามเงียบๆ)
from utils.sharepoint_api import SharePointError, is_sharepoint_configured, upload_document_to_sharepoint
from utils.text_extractor import extract_fields_from_file
from st_aggrid import JsCode
from ui_common import build_css, render_equipment_table
from ui_grid import build_grid_options, show_grid

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
    "sharepoint_url": "ลิงก์ SharePoint ที่เก็บไฟล์ทั้งหมดของบริษัทนั้น: กดไอคอนเพื่อเปิดในแท็บใหม่",
}

# ความกว้างที่ต้องการของแต่ละคอลัมน์ (พิกเซล) ตารางจะปรับคอลัมน์ให้พอดีหน้าจอเอง (fit to window) ไม่มีแถบเลื่อนแนวนอน
# - ค่าตัวเลข = ความกว้างที่ต้องการ (px) ตารางย่อ/ขยายตามสัดส่วนให้พอดีจอ (ดู ui_grid.GRID_MIN_WIDTH_RATIO_*)
# - None = คอลัมน์ข้อความยาว (ตอนนี้คือ Description) กว้างที่สุด ย่อได้มากสุดเมื่อจอแคบ
# - ถ้าเพิ่มคอลัมน์ใหม่ ให้เพิ่มความกว้างขั้นต่ำที่นี่ด้วย (ผลรวมมากเกินจอ ตารางจะมีแถบเลื่อนแนวนอน)
TABLE_COLUMN_WIDTHS: dict[str, "int | str | None"] = {
    "date": 140, "vendor": 160, "category": 125, "total_price": 120, "invoice_status": 140,
    "tel": 155, "tax_id": 130, "pr_run_no": 110, "pr_request_date": 105, "qt_no": 74,
    "description": None, "unit_price": 112, "sharepoint_url": 68,
}
# คอลัมน์ข้อความที่ย่อได้มากเมื่อจอแคบ (ข้อความยาวถูกตัดด้วย ... ชี้เมาส์ดูเต็มได้) ส่วนคอลัมน์อื่นพยายามไม่ย่อ
# (Vendor ชื่อยาวที่สุด จึงให้เป็นตัวย่อหลัก Item / Tel. ไม่ย่อ จะได้อ่านครบ)
SHRINKABLE_TABLE_COLUMNS: tuple[str, ...] = ("vendor", "pr_run_no")

# คอลัมน์ที่ "ซ่อนจากตาราง" แต่ยังอยู่ในข้อมูล (DB / ไฟล์ Export CSV-Excel ยังมีครบ)
# เตรียมไว้สำหรับส่งเข้า Master-List ภายหลัง: อยากแสดงกลับ แค่ลบชื่อคอลัมน์ออกจากรายการนี้
HIDDEN_TABLE_COLUMNS: tuple[str, ...] = (
    "tax_id", "pr_run_no", "pr_request_date", "qt_no", "description", "unit_price",
)

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
# เลือกได้เฉพาะ Pending / Completed (Overdue ระบบคำนวณจากจำนวนวันที่ค้างเอง แถวที่ค้างเกินกำหนดยังแสดง Overdue ตามปกติ)
STATUS_EDITOR_OPTIONS: list[str] = [STATUS_LABEL_PENDING, STATUS_LABEL_COMPLETED]

# สีป้าย (badge) ของสถานะในตาราง: (สีพื้น, สีตัวหนังสือ) แก้สีที่นี่
STATUS_BADGE_COLORS: dict[str, tuple[str, str]] = {
    "completed": ("#DCFCE7", "#166534"),  # เขียว
    "pending": ("#FEF3C7", "#92400E"),  # เหลือง
    "overdue": ("#FEE2E2", "#B91C1C"),  # แดง
}

# ข้อความสถานะในตาราง -> ค่าที่เก็บในฐานข้อมูล (Pending และ Overdue ในฐานข้อมูลคือ "รอใบกำกับภาษี" เหมือนกัน
# ต่างกันที่ Overdue คำนวณจากจำนวนวันที่ค้าง)
STATUS_LABEL_TO_DB: dict[str, str] = {
    STATUS_LABEL_COMPLETED: STATUS_RECEIVED,
    STATUS_LABEL_PENDING: STATUS_PENDING,
    STATUS_LABEL_OVERDUE: STATUS_PENDING,
}

# ชื่อปุ่มเพิ่มข้อมูล (ข้อความช่วยตอนชี้เมาส์) และชื่อหน้าต่างป๊อปอัป: หน้าต่างนี้มีแท็บ [กรอก Form | Upload File] อยู่แล้ว
ADD_DATA_BUTTON_NAME: str = "เพิ่มข้อมูล"

# ตัวเลือกในเมนูที่กางออกเมื่อชี้เมาส์ที่ปุ่ม "+": (ค่าโหมด, ป้ายชื่อ, ไอคอน Material)
# ถ้าจะเพิ่มตัวเลือกใหม่: เพิ่มค่าโหมด/ป้าย/ไอคอนที่นี่ แล้วเพิ่มปุ่มใน render_add_button และแท็บใน render_entry_dialog
ENTRY_MODE_FORM: str = "form"
ENTRY_MODE_UPLOAD: str = "upload"
ADD_OPTION_FORM_LABEL: str = "กรอก Form"
ADD_OPTION_UPLOAD_LABEL: str = "Upload ข้อมูล"
ADD_OPTION_FORM_ICON: str = ":material/edit_note:"
ADD_OPTION_UPLOAD_ICON: str = ":material/upload_file:"
SESSION_KEY_ENTRY_MODE: str = "entry_mode"  # โหมดที่ผู้ใช้เลือกจากเมนู: ใช้เลือกแท็บแรกในหน้าต่าง

# ไอคอนที่แสดงในคอลัมน์ไฟล์ กดแล้วเปิดลิงก์ SharePoint ที่เก็บไฟล์ทั้งหมดของบริษัทนั้นในแท็บใหม่
# (รายการที่ไม่มีลิงก์จะเว้นว่าง)
FILE_LINK_ICON: str = "📁"
# วงกลมหลังไอคอนตอนเมาส์ชี้ (ไม่มีขีดเส้นใต้แบบลิงก์ปกติ): ขนาด / สีพื้น / เงา แก้ได้ที่นี่
FILE_LINK_CIRCLE_PX: int = 38
FILE_LINK_HOVER_BACKGROUND: str = "#E2E8F0"
FILE_LINK_HOVER_SHADOW: str = "0 2px 8px rgba(15, 23, 42, 0.22)"

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
            link.textContent = 'FILE_ICON';
            const restStyle = 'display:inline-flex;align-items:center;justify-content:center;width:FILE_CIRCLE_PXpx;height:FILE_CIRCLE_PXpx;'
                + 'border-radius:50%;text-decoration:none;cursor:pointer;outline:none;background:transparent;box-shadow:none;'
                + 'transition:background-color 0.15s ease, box-shadow 0.15s ease;';
            const hoverStyle = restStyle.replace('background:transparent;box-shadow:none;', 'background:FILE_HOVER_BG;box-shadow:FILE_HOVER_SHADOW;');
            link.style.cssText = restStyle;
            const showCircle = () => { link.style.cssText = hoverStyle; };
            const hideCircle = () => { link.style.cssText = restStyle; };
            link.addEventListener('mouseenter', showCircle);
            link.addEventListener('mouseleave', hideCircle);
            link.addEventListener('focus', showCircle);
            link.addEventListener('blur', hideCircle);
            this.eGui.appendChild(link);
        }
    }
    getGui() { return this.eGui; }
}
"""

# ตัวแสดงสถานะเป็นป้ายสี (badge) ในเซลล์ สร้างเป็น element ทีละชิ้น ไม่ต่อสตริง HTML เพื่อกัน XSS
# STATUS_COLORS ถูกแทนด้วยค่าจาก STATUS_BADGE_COLORS (JSON) ข้อความป้ายตัดอีโมจิหน้าข้อความออก ใช้จุดสีแทน
STATUS_BADGE_RENDERER_JS: str = r"""
class StatusBadgeRenderer {
    init(params) {
        const colors = STATUS_COLORS;
        const raw = String(params.value || '');
        const key = raw.indexOf('Completed') >= 0 ? 'completed' : raw.indexOf('Overdue') >= 0 ? 'overdue' : raw.indexOf('Pending') >= 0 ? 'pending' : '';
        this.eGui = document.createElement('span');
        if (!key) { this.eGui.textContent = raw; return; }
        const badge = document.createElement('span');
        badge.textContent = '● ' + key.charAt(0).toUpperCase() + key.slice(1) + '  ▾';  // ▾ บอกว่ากดเลือกสถานะได้
        badge.style.cssText = 'cursor:pointer;display:inline-block;padding:2px 12px;border-radius:999px;font-weight:600;font-size:15px;line-height:26px;'
            + 'background:' + colors[key][0] + ';color:' + colors[key][1] + ';';
        this.eGui.appendChild(badge);
    }
    getGui() { return this.eGui; }
}
"""

# ตัวแก้ไขสถานะแบบ dropdown ที่ "เปิดรายการทันที" เมื่อคลิกครั้งเดียว (agSelectCellEditor ต้องคลิกซ้ำเพื่อเปิดรายการ
# ส่วน agRichSelectCellEditor เป็นฟีเจอร์ Enterprise จึงเขียน editor เองแบบ popup) สร้างด้วย element ไม่ต่อ HTML เพื่อกัน XSS
# STATUS_OPTIONS / STATUS_COLORS ถูกแทนด้วยค่า JSON จาก STATUS_EDITOR_OPTIONS / STATUS_BADGE_COLORS
STATUS_DROPDOWN_EDITOR_JS: str = r"""
class StatusDropdownEditor {
    init(params) {
        const options = STATUS_OPTIONS;
        const colors = STATUS_COLORS;
        const current = String(params.value || '');
        this.value = params.value;
        // เล่น animation เฉพาะเมื่อผู้ใช้ไม่ได้ตั้งค่าลดการเคลื่อนไหว และเบราว์เซอร์รองรับ Web Animations API
        const animate = !(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
        this.eGui = document.createElement('div');
        this.eGui.setAttribute('role', 'listbox');
        this.eGui.style.cssText = 'background:#fff;border:1px solid #E2E8F0;border-radius:12px;padding:8px;'
            + 'box-shadow:0 10px 28px rgba(15,23,42,0.12);min-width:170px;display:flex;flex-direction:column;gap:6px;'
            + 'transform-origin:top left;';
        if (animate && this.eGui.animate) {
            this.eGui.animate(
                [{opacity: 0, transform: 'translateY(-6px) scale(0.96)'}, {opacity: 1, transform: 'translateY(0) scale(1)'}],
                {duration: 160, easing: 'cubic-bezier(.2,.8,.2,1)'}
            );
        }
        // เลือกแล้วค่อย ๆ จางหายก่อนปิด (ถ้าไม่มี animation ปิดทันที)
        const choose = (label) => {
            this.value = label;
            if (animate && this.eGui.animate) {
                this.eGui.animate([{opacity: 1}, {opacity: 0}], {duration: 100, fill: 'forwards'});
                setTimeout(() => params.stopEditing(), 100);
            } else {
                params.stopEditing();
            }
        };
        options.forEach((label, index) => {
            const key = label.indexOf('Completed') >= 0 ? 'completed' : 'pending';
            const name = key.charAt(0).toUpperCase() + key.slice(1);
            const item = document.createElement('div');
            item.setAttribute('role', 'option');
            // ป้ายชิดซ้าย เครื่องหมาย ✓ ชิดขวา (ช่องติ๊กกว้างคงที่ ทุกแถวเรียงตรงกัน) พื้นตอนชี้เมาส์บางมาก
            item.style.cssText = 'cursor:pointer;padding:5px 8px;border-radius:8px;display:flex;align-items:center;justify-content:space-between;gap:14px;'
                + 'background:transparent;transition:background-color 0.12s ease;';
            const badge = document.createElement('span');
            badge.textContent = '● ' + name;
            badge.style.cssText = 'display:inline-block;padding:2px 12px;border-radius:999px;font-weight:600;font-size:15px;line-height:26px;'
                + 'background:' + colors[key][0] + ';color:' + colors[key][1] + ';';
            item.appendChild(badge);
            const tick = document.createElement('span');
            tick.textContent = current.indexOf(name) >= 0 ? '✓' : '';
            tick.style.cssText = 'display:inline-block;width:18px;text-align:center;font-weight:700;color:#0F766E;';
            item.appendChild(tick);
            item.addEventListener('mouseenter', () => { item.style.background = 'rgba(15,23,42,0.04)'; });
            item.addEventListener('mouseleave', () => { item.style.background = 'transparent'; });
            item.addEventListener('click', () => choose(label));
            this.eGui.appendChild(item);
            if (animate && item.animate) {  // รายการไล่เข้าทีละตัว
                item.animate(
                    [{opacity: 0, transform: 'translateY(-4px)'}, {opacity: 1, transform: 'translateY(0)'}],
                    {duration: 180, delay: 40 * index, easing: 'ease-out', fill: 'backwards'}
                );
            }
        });
    }
    getGui() { return this.eGui; }
    getValue() { return this.value; }
    isPopup() { return true; }
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

# ข้อความตัวอย่างจางๆ ในช่องกรอก (ชื่อภายในของช่อง -> ข้อความ) ถ้าเพิ่มช่องใหม่ ให้เพิ่มบรรทัดที่นี่
FORM_FIELD_PLACEHOLDERS: dict[str, str] = {
    "tax_id": "เช่น 0105536000000 (13 หลัก)",
    "po_no": "เช่น PO-2026-0001",
    "pr_run_no": "เช่น PR-2026-0001",
    "tel": "เช่น 081-234-5678",
    "email": "เช่น name@company.com",
    "contact_name": "ชื่อผู้ติดต่อ เช่น สมชาย ใจดี",
}
# ดาวแดงต่อท้ายป้ายชื่อของช่องบังคับ (รูปแบบสีของ Streamlit markdown)
REQUIRED_FIELD_MARK: str = " :red[*]"
# ตัวคั่นที่อยู่ไฟล์เมื่อแนบหลายไฟล์ (เก็บรวมในคอลัมน์ file_path เดิม จึงไม่ต้องแก้โครงสร้างฐานข้อมูล)
FILE_PATH_SEPARATOR: str = "\n"

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

SESSION_KEY_EXTRACT_FILE_ID: str = "overview_extract_file_id"  # ไฟล์ในกล่อง Extract ที่อ่านข้อมูลแล้ว
SESSION_KEY_EXTRACT_NOTICE: str = "overview_extract_notice"  # ข้อความผลการดึงข้อมูลจากไฟล์
SESSION_KEY_LOCAL_FILE_ID: str = "overview_local_file_id"  # ไฟล์ในกล่อง Upload ที่บันทึกลงเครื่องแล้ว
SESSION_KEY_LOCAL_NOTICE: str = "overview_local_notice"  # ผลการบันทึกไฟล์ (ระดับ, ข้อความ)
SESSION_KEY_LOCAL_PATH: str = "overview_local_path"  # ที่อยู่ไฟล์ที่บันทึกแล้ว รอผูกกับรายการตอนกด Upload

# ---------------------------------------------------------------------------
# CSS เฉพาะหน้า Overview (กฎกลางของการ์ด/สี/ความมน อยู่ที่ ui_common.py)
# ---------------------------------------------------------------------------

PAGE_CSS_RULES: str = """
/* (สี ฟอนต์ ช่องกรอก ปุ่ม และมุม 8px ของทั้งระบบมาจากธีมกลาง config/styles.py แล้ว ที่นี่เหลือเฉพาะส่วนที่เป็นของหน้านี้) */

/* 0) แจ้งเตือนค้าง (แถบ + ป้ายตัวเลข) และแถบ "ดูรายการที่ค้าง" ที่กาง/พับแบบมี animation
      ปรับสีที่ linear-gradient / ความเร็วชีพจรที่ overdue-pulse (2s) ปิด animation อัตโนมัติถ้าเครื่องตั้งค่าลดการเคลื่อนไหว */
.overdue-alert {
    display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
    padding: 16px 20px; border-radius: 14px; border-left: 6px solid #DC2626;
    background: linear-gradient(100deg, #FFF1F2 0%, #FFEDD5 100%);
    box-shadow: 0 1px 2px rgba(220, 38, 38, 0.10), 0 12px 28px -10px rgba(220, 38, 38, 0.35);
    animation: overdue-alert-in 0.45s cubic-bezier(.2,.8,.2,1) both;
    margin-bottom: 14px;
}
.overdue-alert-icon {
    flex: 0 0 auto; width: 48px; height: 48px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center; font-size: 24px;
    background: #FFFFFF; box-shadow: 0 0 0 0 rgba(220, 38, 38, 0.45);
    animation: overdue-pulse 2s ease-out infinite;
}
.overdue-alert-text { flex: 1 1 260px; min-width: 0; }
.overdue-alert-title { font-size: 1.25rem; font-weight: 800; color: #991B1B; line-height: 1.3; }
.overdue-alert-sub { margin-top: 2px; font-size: 1rem; color: #9A3412; }
.overdue-alert-badges { display: flex; gap: 8px; flex-wrap: wrap; }
.overdue-pill { padding: 6px 14px; border-radius: 999px; font-size: 1rem; font-weight: 600; white-space: nowrap; }
.overdue-pill b { font-size: 1.25rem; font-weight: 800; }
.overdue-pill-count { background: #DC2626; color: #FFFFFF; box-shadow: 0 6px 14px -6px rgba(220, 38, 38, 0.7); }
.overdue-pill-days { background: #FFFFFF; color: #B91C1C; border: 1px solid #FECACA; }
@keyframes overdue-alert-in { from { opacity: 0; transform: translateY(-8px); } to { opacity: 1; transform: none; } }
@keyframes overdue-pulse {
    0% { box-shadow: 0 0 0 0 rgba(220, 38, 38, 0.45); }
    70% { box-shadow: 0 0 0 14px rgba(220, 38, 38, 0); }
    100% { box-shadow: 0 0 0 0 rgba(220, 38, 38, 0); }
}
.st-key-overdue_alert > [data-testid="stVerticalBlock"] { gap: 0.75rem; }
/* แถบ "ดูรายการที่ค้าง": หัวมี hover, ลูกศรหมุนนุ่ม, เนื้อหาเลื่อน+เฟดลงตอนกาง (ใช้ opacity/translate เท่านั้น ตารางจึงไม่กว้าง 0)
   ตอนพับค่อยๆ หุบด้วย ::details-content (Chromium 131+) เบราว์เซอร์เก่าจะหุบทันทีโดยไม่พัง */
.st-key-overdue_alert [data-testid="stExpander"] details { interpolate-size: allow-keywords; }
.st-key-overdue_alert [data-testid="stExpander"] summary { transition: background-color 0.18s ease; border-radius: 8px; }
.st-key-overdue_alert [data-testid="stExpander"] summary:hover { background: #F1F5F9; }
.st-key-overdue_alert [data-testid="stExpander"] summary svg,
.st-key-overdue_alert [data-testid="stExpander"] summary [data-testid="stIconMaterial"] { transition: transform 0.25s ease; }
.st-key-overdue_alert [data-testid="stExpander"] details::details-content {
    height: 0; overflow: clip; opacity: 0;
    transition: height 0.3s ease, opacity 0.25s ease, content-visibility 0.3s allow-discrete;
}
.st-key-overdue_alert [data-testid="stExpander"] details[open]::details-content { height: auto; opacity: 1; }
.st-key-overdue_alert [data-testid="stExpander"] details[open] > summary ~ * { animation: overdue-expand-in 0.3s cubic-bezier(.2,.8,.2,1) both; }
@keyframes overdue-expand-in { from { opacity: 0; transform: translateY(-8px); } to { opacity: 1; transform: none; } }
@media (prefers-reduced-motion: reduce) {
    .overdue-alert, .overdue-alert-icon,
    .st-key-overdue_alert [data-testid="stExpander"] details[open] > summary ~ * { animation: none; }
    .st-key-overdue_alert [data-testid="stExpander"] details::details-content,
    .st-key-overdue_alert [data-testid="stExpander"] summary,
    .st-key-overdue_alert [data-testid="stExpander"] summary svg { transition: none; }
}

/* 1.1) ลดระยะขอบรอบตาราง เพื่อให้ตารางกว้างขึ้น (ตารางวาดด้วย canvas ปรับขนาดตัวอักษรด้วย CSS ไม่ได้ จึงเอาพื้นที่จากขอบแทน)
      ขอบของหน้าหลัก 48px -> 16px, การ์ดตาราง 32px -> 12px, กล่องขาวด้านใน 20px -> 8px (รวมได้ตารางกว้างขึ้น ~128px) */
/* ใช้ min() กับตัวแปร responsive: จอใหญ่ขอบไม่เกิน 2rem (ตารางกว้างเต็มที่) จอเล็กใช้ค่าที่ config/styles.py กำหนด (0.75rem) */
[data-testid="stMainBlockContainer"] {
    padding-left: min(var(--app-main-padding-x), 2rem) !important;
    padding-right: min(var(--app-main-padding-x), 2rem) !important;
}
.st-key-table_card { padding-left: min(12px, var(--app-card-padding)) !important; padding-right: min(12px, var(--app-card-padding)) !important; }
.st-key-table_inner { padding-left: min(8px, var(--app-inner-padding)) !important; padding-right: min(8px, var(--app-inner-padding)) !important; }

/* 1.2) แถวหัวข้อตาราง + ปุ่มเพิ่มข้อมูล (ไอคอนอย่างเดียว): ปุ่มสี่เหลี่ยมมุมมน 52px ชิดขอบขวาเท่ากับกล่องตาราง
        แถวไม่ขึ้นบรรทัดใหม่แม้จอแคบ (หัวข้อได้พื้นที่ที่เหลือ) ปรับขนาดปุ่ม/ไอคอนที่ค่า 52px / 30px
        หัวข้อไม่มีระยะบน/ล่างเกิน เพื่อให้อยู่ตรงกลางแนวเดียวกับปุ่ม และดึงแถวนี้ให้ชิดกล่องค้นหาด้านล่าง */
.st-key-table_header_row > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] {
    flex-wrap: nowrap !important; align-items: center; gap: 12px;
}
.st-key-table_header_row [data-testid="stColumn"]:first-child { flex: 1 1 0 !important; min-width: 0 !important; }
.st-key-table_header_row [data-testid="stColumn"]:last-child { flex: 0 0 auto !important; width: auto !important; min-width: 0 !important; }
.st-key-table_header_row [data-testid="stColumn"]:last-child [data-testid="stElementContainer"] { display: flex; justify-content: flex-end; }
/* 1.2.1) ปุ่ม "+" ลอย (ไม่มีพื้นหลัง/กรอบ) + เมนูตัวเลือกที่กางไปทางซ้ายเมื่อชี้เมาส์หรือโฟกัส (แตะบนจอสัมผัส)
          ไอคอนหมุน 135° (กลายเป็น x) ตัวเลือกเลื่อน+เฟดเข้า ตัวที่ 2 หน่วงเล็กน้อย
          ปรับขนาดไอคอนที่ font-size 40px, องศาหมุนที่ rotate(), ความเร็วที่ 0.35s / 0.25s */
.st-key-add_menu { position: relative; width: 52px; height: 52px; gap: 0 !important; }
.st-key-add_menu [data-testid="stButton"] button {
    width: 52px !important; min-width: 52px !important; height: 52px !important; padding: 0 !important;
    background: transparent !important; border: none !important; box-shadow: none !important; border-radius: 50% !important;
}
.st-key-add_menu_trigger button [data-testid="stIconMaterial"] {
    font-size: 40px !important; color: var(--ui-accent) !important; transition: transform 0.35s ease;
}
.st-key-add_menu:hover .st-key-add_menu_trigger button [data-testid="stIconMaterial"],
.st-key-add_menu:focus-within .st-key-add_menu_trigger button [data-testid="stIconMaterial"] { transform: rotate(135deg); }
/* กล่องเมนู: padding ขวา 8px เป็นสะพานให้เมาส์เลื่อนจากไอคอนมาตัวเลือกได้โดยเมนูไม่หาย */
.st-key-add_menu_options {
    position: absolute; right: 52px; top: 0; height: 52px; display: flex !important; flex-direction: row !important;
    align-items: center; gap: 4px !important; padding-right: 8px; width: max-content;
    visibility: hidden; opacity: 0; pointer-events: none;
    transition: opacity 0.25s ease, visibility 0s linear 0.25s;
}
.st-key-add_menu:hover .st-key-add_menu_options,
.st-key-add_menu:focus-within .st-key-add_menu_options {
    visibility: visible; opacity: 1; pointer-events: auto; transition: opacity 0.25s ease, visibility 0s;
}
.st-key-add_menu_options { width: max-content !important; min-width: max-content !important; max-width: none !important; }
.st-key-add_menu_options > [data-testid="stElementContainer"] {
    flex: 0 0 auto !important; width: max-content !important; min-width: max-content !important; transform: translateX(16px); transition: transform 0.3s ease;
}
.st-key-add_menu_options [data-testid="stButton"] { width: max-content !important; min-width: max-content !important; }
.st-key-add_menu_options [data-testid="stElementContainer"]:nth-child(2) { transition-delay: 0.06s; }
.st-key-add_menu:hover .st-key-add_menu_options [data-testid="stElementContainer"],
.st-key-add_menu:focus-within .st-key-add_menu_options [data-testid="stElementContainer"] { transform: translateX(0); }
.st-key-add_menu_options [data-testid="stButton"] button {
    width: auto !important; min-width: 0 !important; height: 40px !important; padding: 0 14px !important;
    border-radius: 10px !important; white-space: nowrap;
}
.st-key-add_menu_options [data-testid="stButton"] button p { font-size: 16px; font-weight: 600; color: #1E293B !important; }
.st-key-add_menu_options [data-testid="stButton"] button [data-testid="stIconMaterial"] { font-size: 24px !important; color: var(--ui-accent) !important; }
.st-key-add_menu_options [data-testid="stButton"] button:hover { background: rgba(37, 99, 235, 0.08) !important; }
@media (max-width: 640px) {
    /* จอแคบ: เมนูทับหัวข้อ จึงใส่พื้นขาวโปร่งให้ข้อความอ่านออก */
    .st-key-add_menu_options { background: rgba(255, 255, 255, 0.97); border-radius: 12px; }
}
@media (prefers-reduced-motion: reduce) {
    .st-key-add_menu_trigger button [data-testid="stIconMaterial"], .st-key-add_menu_options,
    .st-key-add_menu_options [data-testid="stElementContainer"] { transition: none !important; }
}
.st-key-table_header_row h3 { padding: 0 !important; margin: 0 !important; line-height: 1.3 !important; }
.st-key-table_header_row [data-testid="stColumn"]:first-child [data-testid="stElementContainer"] { height: 52px !important; min-height: 52px !important; display: flex; align-items: center; }
.st-key-table_header_row [data-testid="stColumn"]:first-child [data-testid="stVerticalBlock"] { height: auto !important; }
.st-key-table_header_row [data-testid="stHeading"] { height: 36px !important; display: flex; align-items: center; padding: 0 !important; margin: 0 !important; }
.st-key-table_header_row [data-testid="stHeading"] [data-testid="stMarkdownContainer"] { padding: 0 !important; margin: 0 !important; }
.st-key-table_header_row { margin-bottom: -8px; }

/* 1.5) แถบปุ่มใต้ตัวกรอง: ปุ่มลบ ชิดซ้าย | ช่องว่างกลาง | Export CSV + Excel ชิดขวาติดกัน (เว้นขอบซ้าย-ขวา 8px)
        ถ้าจะเว้นขอบมาก/น้อยลง แก้ค่า padding; ถ้าจะปรับช่องไฟระหว่าง CSV กับ Excel แก้ค่า gap ของกลุ่มขวา */
.st-key-table_action_bar > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] {
    justify-content: space-between; align-items: center; padding: 0 8px; gap: 12px;
}
.st-key-table_action_bar > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {
    flex: 0 0 auto; width: auto;
}
/* คอลัมน์กลาง = ช่องว่างดันให้ปุ่มซ้ายกับกลุ่มขวาแยกจากกัน */
.st-key-table_action_bar > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:not(:has([data-testid="stButton"], [data-testid="stDownloadButton"])) {
    flex: 1 1 auto; min-width: 24px;
}
/* กลุ่มขวา (CSV | Excel): ชิดขวา ติดกัน เว้นช่องไฟเล็กน้อย */
.st-key-table_action_bar [data-testid="stColumn"] [data-testid="stHorizontalBlock"] { justify-content: flex-end; gap: 12px; flex-wrap: wrap; }  /* wrap: จอแคบให้ปุ่มตกบรรทัดแทนล้นขอบ */
.st-key-table_action_bar [data-testid="stColumn"] [data-testid="stColumn"] { flex: 0 0 auto; width: auto; min-width: 0; }
.st-key-table_action_bar [data-testid="stButton"] button,
.st-key-table_action_bar [data-testid="stDownloadButton"] button { width: auto; padding-left: 20px; padding-right: 20px; white-space: nowrap; }
.st-key-table_action_bar [data-testid="stButton"],
.st-key-table_action_bar [data-testid="stDownloadButton"] { width: auto; }

/* 1.3) หน้าต่าง Popup แบบแคบ (width="small"): ปุ่มถัดไปเต็มความกว้าง และลดขอบ/ขนาดหัวข้อของฟอร์มให้ช่องกรอกกว้างขึ้น */
.st-key-step1_next_button,
.st-key-step1_next_button button { width: 100% !important; }
.st-key-entry_form_card { padding: 4px !important; }
.st-key-entry_form_card .card-title { font-size: 18px !important; margin: 0 0 4px 0 !important; }
.st-key-entry_form_card [data-testid="stForm"] { padding: 12px !important; }

/* 1.4) หน้าต่าง Popup (ขั้นที่ 1 และ 2): ตัวอักษรใหญ่ขึ้น ตกแต่งใหม่ ตัวเลือกมีแท่งสีเลื่อนไปหาตัวที่กด
        แก้ขนาด/สีได้ที่ตัวเลขในกฎนี้ที่เดียว (ไม่แตะ span เพื่อไม่ให้ไอคอนของ Streamlit เพี้ยน) */
/* กลางจอ: ฉากหลังหรี่ + เบลอเล็กน้อย, ตัวหน้าต่างอยู่กึ่งกลางแนวตั้ง, เนื้อหายาวให้เลื่อนภายในหน้าต่าง */
div[data-testid="stDialog"] { align-items: center !important; background: rgba(15, 23, 42, 0.45) !important; backdrop-filter: blur(3px); }
div[data-testid="stDialog"] [role="dialog"] {
    border-radius: 22px; box-shadow: 0 24px 60px rgba(15, 23, 42, 0.28);
    padding: 12px 18px 22px 18px; max-height: 92vh; overflow-y: auto;
    animation: dialog-pop-in .3s cubic-bezier(.2, .8, .2, 1);
}
@keyframes dialog-pop-in { from { opacity: 0; transform: translateY(14px) scale(.98); } to { opacity: 1; transform: none; } }
/* ชื่อหน้าต่าง "เพิ่มข้อมูล": ฟอนต์ Prompt ตัวหนา ใหญ่ */
div[data-testid="stDialog"] [role="dialog"] h2,
div[data-testid="stDialog"] [role="dialog"] h2 * { font-family: 'Prompt', 'Sarabun', sans-serif !important; font-size: 26px !important; font-weight: 700 !important; color: #0F172A; }
/* ปุ่มปิด (x): กลม มีพื้นจางตอนชี้ */
div[data-testid="stDialog"] [role="dialog"] > button { border-radius: 50%; transition: background .2s; }
div[data-testid="stDialog"] [role="dialog"] > button:hover { background: #F1F5F9; }
/* ข้อความทั่วไป 17px */
div[data-testid="stDialog"] [data-testid="stMarkdownContainer"] p { font-size: 17px; line-height: 1.55; }
/* ป้ายชื่อช่องกรอก 17px ตัวหนา */
div[data-testid="stDialog"] label,
div[data-testid="stDialog"] label p,
div[data-testid="stDialog"] .field-label { font-size: 17px !important; font-weight: 600 !important; color: #1E293B !important; }
/* ช่องกรอก / กล่องเลือก 17px มุมมน โฟกัสแล้วมีวงสีฟ้า */
div[data-testid="stDialog"] input,
div[data-testid="stDialog"] textarea,
div[data-testid="stDialog"] [data-baseweb="select"] { font-size: 17px !important; }
div[data-testid="stDialog"] [data-baseweb="input"],
div[data-testid="stDialog"] [data-baseweb="select"] > div,
div[data-testid="stDialog"] [data-baseweb="textarea"] { border-radius: 12px !important; transition: box-shadow .2s, border-color .2s; }
div[data-testid="stDialog"] [data-baseweb="input"]:focus-within,
div[data-testid="stDialog"] [data-baseweb="select"] > div:focus-within,
div[data-testid="stDialog"] [data-baseweb="textarea"]:focus-within { box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.18); }
/* คลิกช่องกรอก: ขอบเป็นน้ำเงิน + ยกขึ้นเล็กน้อย + เงานุ่ม, ป้ายชื่อของช่องเปลี่ยนเป็นสีน้ำเงิน (ค่าอยู่ที่นี่ที่เดียว)
   ตัวกรอบจริงใน Streamlit 1.66: ช่องข้อความ = stTextInputRootElement, Vendor = [role=group] ใน stSelectbox, วันที่ = stDateInputField */
div[data-testid="stDialog"] [data-testid="stTextInputRootElement"],
div[data-testid="stDialog"] [data-testid="stSelectbox"] [role="group"],
div[data-testid="stDialog"] [data-testid="stDateInputField"] { transition: box-shadow .22s ease, border-color .22s ease, transform .22s ease; }
div[data-testid="stDialog"] [data-testid="stTextInputRootElement"]:focus-within,
div[data-testid="stDialog"] [data-testid="stSelectbox"] [role="group"]:focus-within,
div[data-testid="stDialog"] [data-testid="stDateInputField"]:focus-within {
    border-color: #2563EB !important; transform: translateY(-1px);
    box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.18), 0 6px 14px rgba(37, 99, 235, 0.14) !important;
}
div[data-testid="stDialog"] [data-testid="stWidgetLabel"] { transition: color .22s ease; }
div[data-testid="stDialog"] [data-testid="stElementContainer"]:has(:focus-within) [data-testid="stWidgetLabel"] p { color: #1D4ED8 !important; }
/* ซ่อนข้อความ "Press Enter to submit form" ที่ทับ placeholder ตอนโฟกัส */
div[data-testid="stDialog"] [data-testid="InputInstructions"] { display: none; }
/* ข้อความตัวอย่างในช่อง (placeholder): จางและบาง */
div[data-testid="stDialog"] input::placeholder,
div[data-testid="stDialog"] textarea::placeholder { color: #94A3B8 !important; font-weight: 400; opacity: 1; }
/* ปุ่มในไดอะล็อกไม่ตัดคำ (เช่น "ย้อนกลับ" ต้องแสดงเต็ม) */
div[data-testid="stDialog"] [data-testid="stFormSubmitButton"] button p { white-space: nowrap; }

/* แถบ progress ของขั้นตอน (2 ช่อง) + ข้อความ "ขั้นตอนที่ X / 2" */
.step-progress { display: flex; gap: 8px; margin: 2px 0 10px 0; }
.step-progress span { flex: 1; height: 6px; border-radius: 999px; background: #E2E8F0; transition: background .3s; }
.step-progress span.on { background: linear-gradient(90deg, #3B82F6, #2563EB); }
.step-subtitle { font-size: 16px !important; color: #64748B; margin: 0 0 6px 0; text-align: center; }

/* หัวข้อคำถามขั้นที่ 1 (####): ฟอนต์ Prompt 22px กึ่งกลาง */
div[data-testid="stDialog"] h4 { font-family: 'Prompt', 'Sarabun', sans-serif !important; font-size: 22px !important; font-weight: 600 !important; padding: 0 0 6px 0 !important; text-align: center; color: #0F172A; }

/* ตัวเลือก (segmented control): แคปซูลพื้นเทาอ่อน ปุ่มกว้างเท่ากัน + แท่งสีขาว (::before) เลื่อนไปหาตัวที่เลือก
   จำนวนตัวเลือกที่รองรับ 2–5 ตัว (กฎ n/k ด้านล่าง) ถ้าเพิ่มเกิน 5 ให้เพิ่มกฎ nth-child ต่อท้าย */
div[data-testid="stDialog"] [data-testid="stElementContainer"]:has([data-testid="stButtonGroup"]) { width: 100% !important; }
div[data-testid="stDialog"] [data-testid="stButtonGroup"] { display: flex; flex-direction: column; align-items: center; width: 100%; }
div[data-testid="stDialog"] [data-testid="stButtonGroup"] [role="radiogroup"] {
    position: relative; display: grid; grid-auto-flow: column; grid-auto-columns: 1fr; gap: 0;
    width: 100%; max-width: 640px; padding: 5px; border-radius: 16px; background: #EEF2F7;
}
div[data-testid="stDialog"] [data-testid="stButtonGroup"] [role="radiogroup"]::before {
    content: ""; position: absolute; top: 5px; bottom: 5px; left: 5px; width: calc((100% - 10px) / 4);
    border-radius: 12px; background: #FFFFFF; box-shadow: 0 2px 8px rgba(37, 99, 235, 0.22), 0 0 0 1.5px rgba(37, 99, 235, 0.35);
    opacity: 0; transition: transform .38s cubic-bezier(.4, 0, .2, 1), opacity .25s;
}
div[data-testid="stDialog"] [data-testid="stButtonGroup"] [role="radiogroup"]:has(> button:nth-child(2):last-child)::before { width: calc((100% - 10px) / 2); }
div[data-testid="stDialog"] [data-testid="stButtonGroup"] [role="radiogroup"]:has(> button:nth-child(3):last-child)::before { width: calc((100% - 10px) / 3); }
div[data-testid="stDialog"] [data-testid="stButtonGroup"] [role="radiogroup"]:has(> button:nth-child(5):last-child)::before { width: calc((100% - 10px) / 5); }
div[data-testid="stDialog"] [data-testid="stButtonGroup"] [role="radiogroup"]:has(> button[data-selected="true"])::before { opacity: 1; }
div[data-testid="stDialog"] [data-testid="stButtonGroup"] [role="radiogroup"]:has(> button:nth-child(2)[data-selected="true"])::before { transform: translateX(100%); }
div[data-testid="stDialog"] [data-testid="stButtonGroup"] [role="radiogroup"]:has(> button:nth-child(3)[data-selected="true"])::before { transform: translateX(200%); }
div[data-testid="stDialog"] [data-testid="stButtonGroup"] [role="radiogroup"]:has(> button:nth-child(4)[data-selected="true"])::before { transform: translateX(300%); }
div[data-testid="stDialog"] [data-testid="stButtonGroup"] [role="radiogroup"]:has(> button:nth-child(5)[data-selected="true"])::before { transform: translateX(400%); }
div[data-testid="stDialog"] [data-testid="stButtonGroup"] button {
    position: relative; z-index: 1; min-height: 52px; padding: 10px 14px !important; border: none !important; border-radius: 12px !important;
    background: transparent !important; box-shadow: none !important; color: #475569; transition: color .25s, transform .15s;
}
div[data-testid="stDialog"] [data-testid="stButtonGroup"] button p { font-size: 17px !important; font-weight: 500; white-space: nowrap; }
div[data-testid="stDialog"] [data-testid="stButtonGroup"] button:hover { color: #1D4ED8; }
div[data-testid="stDialog"] [data-testid="stButtonGroup"] button:active { transform: scale(.97); }
div[data-testid="stDialog"] [data-testid="stButtonGroup"] button[data-selected="true"] { color: #1D4ED8; }
div[data-testid="stDialog"] [data-testid="stButtonGroup"] button[data-selected="true"] p { font-weight: 700; }

/* ปุ่ม "ถัดไป" / "บันทึก" / "ย้อนกลับ": ฟอนต์ Prompt 18px, มุม 14px, ปุ่มหลักไล่เฉดน้ำเงิน เงาจาง ชี้แล้วยกขึ้นเล็กน้อย */
div[data-testid="stDialog"] [data-testid="stButton"] button,
div[data-testid="stDialog"] [data-testid="stFormSubmitButton"] button {
    font-family: 'Prompt', 'Sarabun', sans-serif !important; font-size: 18px !important; font-weight: 600 !important;
    min-height: 52px; border-radius: 14px !important;
    transition: transform .18s ease, box-shadow .25s ease, filter .25s ease, opacity .25s ease;
}
div[data-testid="stDialog"] [data-testid="stButton"] button p,
div[data-testid="stDialog"] [data-testid="stFormSubmitButton"] button p { font-family: inherit !important; font-size: 18px !important; font-weight: 600 !important; }
div[data-testid="stDialog"] button[kind="primary"],
div[data-testid="stDialog"] button[kind="primaryFormSubmit"] {
    background: linear-gradient(135deg, #3B82F6 0%, #2563EB 55%, #1D4ED8 100%) !important; border: none !important;
    box-shadow: 0 6px 16px rgba(37, 99, 235, 0.32);
}
div[data-testid="stDialog"] button[kind="primary"]:hover:not(:disabled),
div[data-testid="stDialog"] button[kind="primaryFormSubmit"]:hover:not(:disabled) { transform: translateY(-2px); box-shadow: 0 10px 22px rgba(37, 99, 235, 0.4); filter: brightness(1.05); }
div[data-testid="stDialog"] button[kind="primary"]:active:not(:disabled),
div[data-testid="stDialog"] button[kind="primaryFormSubmit"]:active:not(:disabled) { transform: translateY(0) scale(.98); box-shadow: 0 3px 8px rgba(37, 99, 235, 0.3); }
div[data-testid="stDialog"] button:disabled { opacity: .5; box-shadow: none !important; }

/* เปลี่ยนขั้น: เนื้อหาของแต่ละขั้นเฟดเข้า + เลื่อนขึ้นเล็กน้อย (แต่ละขั้นเป็น key คนละอัน จึงเล่นใหม่ทุกครั้งที่เปลี่ยนขั้น) */
.st-key-dialog_step_1, .st-key-dialog_step_2 { animation: dialog-step-in .38s cubic-bezier(.2, .8, .2, 1); }
@keyframes dialog-step-in { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: none; } }
@media (prefers-reduced-motion: reduce) {
    div[data-testid="stDialog"] *, div[data-testid="stDialog"] *::before, .st-key-dialog_step_1, .st-key-dialog_step_2,
    div[data-testid="stDialog"] [role="dialog"] { animation: none !important; transition: none !important; }
}

/* จอแคบ (มือถือ): ลดขอบหน้าต่าง/ขนาดตัวเลือก 4 ตัวให้พอดีบรรทัดเดียว ไม่ถูกตัดเป็น "H..." */
@media (max-width: 640px) {
    div[data-testid="stDialog"] [role="dialog"] { padding: 8px 10px 18px 10px; }
    div[data-testid="stDialog"] [data-testid="stButtonGroup"] button { padding: 8px 2px !important; }
    div[data-testid="stDialog"] [data-testid="stButtonGroup"] button p { font-size: 14px !important; overflow: visible !important; text-overflow: clip !important; }
    div[data-testid="stDialog"] h4 { font-size: 19px !important; }
}

/* ขั้นที่ 1: ปุ่มถัดไปห่างจากตัวเลือกพอดี */
.st-key-step1_next_button { margin-top: 10px; }
/* เส้นคั่นในฟอร์ม: เว้นระยะบน/ล่างพอดี ไม่ชิดช่องกรอก */
div[data-testid="stDialog"] hr { margin: 0.4rem 0 !important; }
/* เว้นช่องไฟระหว่างฟิลด์ให้โปร่ง ไม่เบียดเมื่อตัวอักษรใหญ่ขึ้น */
.st-key-entry_form_card [data-testid="stForm"] [data-testid="stVerticalBlock"] { gap: 1.1rem !important; }
div[data-testid="stDialog"] [data-testid="stVerticalBlock"] { gap: 1rem; }

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
    content: "Drop your files here";
    display: block; font-size: 17px; font-weight: 600; color: var(--ui-text); margin-bottom: 2px;
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

/* 7) หน้า Upload ข้อมูล: หัวข้อกล่องใหญ่ขึ้น (Prompt) + 2 กล่องกว้าง/สูงเท่ากัน สมมาตร
      แก้ขนาดตัวอักษรหัวข้อที่ .upload-card-title / .upload-card-hint ที่เดียว */
.upload-card-heading { display: flex; align-items: center; gap: 10px; margin: 0 0 8px 0; min-height: 48px; }
.upload-card-icon {
    display: inline-flex; align-items: center; justify-content: center; flex: none;
    width: 40px; height: 40px; border-radius: 12px; font-size: 20px; background: #EFF6FF;
}
.upload-card-title { font-family: 'Prompt', 'Sarabun', sans-serif; font-size: 19px; font-weight: 600; color: #0F172A; line-height: 1.25; }
.upload-card-hint { white-space: nowrap; font-size: 14px; color: #64748B; line-height: 1.3; margin-top: 2px; }
.st-key-upload_card [data-testid="stFileUploaderDropzone"] { min-height: 190px; border-radius: 16px; }
.st-key-upload_card [data-testid="stFileUploaderDropzoneInstructions"] small,
.st-key-upload_card [data-testid="stFileUploaderDropzoneInstructions"] span { font-size: 14px; white-space: normal; text-overflow: clip; overflow: visible; }
.st-key-upload_card [data-testid="stFileUploaderDropzone"] { gap: 14px; }
.st-key-upload_card [data-testid="stFileUploaderFile"] { font-size: 14px; }
.st-key-upload_card [data-testid="stFileUploader"] section + div { max-height: 130px; overflow-y: auto; }
/* 7.1) แยก 2 กล่องเป็นการ์ดคนละใบชัดเจน: กรอบ + แถบสีบนคนละโทน (ฟ้า = ขึ้นเว็บไซต์/SharePoint, เขียวอมฟ้า = Extract)
        + ป้ายปลายทาง (pill) แก้สีที่ .upload-card-badge ของแต่ละกล่อง */
.st-key-upload_box_purchase, .st-key-upload_box_extract {
    position: relative; background: #ffffff; border: 1.5px solid #CBD5E1; border-radius: 18px;
    padding: 20px 16px 16px 16px; overflow: hidden; box-shadow: 0 2px 8px rgba(15, 23, 42, 0.06);
}
.st-key-upload_box_purchase::before, .st-key-upload_box_extract::before {
    content: ""; position: absolute; top: 0; left: 0; right: 0; height: 5px;
}
.st-key-upload_box_purchase::before { background: linear-gradient(90deg, #2563EB, #60A5FA); }
.st-key-upload_box_extract::before { background: linear-gradient(90deg, #0D9488, #5EEAD4); }
/* ให้ 2 การ์ดสูงเท่ากันเสมอ แม้ฝั่งหนึ่งมีไฟล์/ข้อความผลลัพธ์ยาวกว่า */
[data-testid="stLayoutWrapper"]:has(> .st-key-upload_box_purchase),
[data-testid="stLayoutWrapper"]:has(> .st-key-upload_box_extract) { flex: 1 1 auto !important; }
.st-key-upload_box_purchase, .st-key-upload_box_extract { flex: 1 1 auto !important; }
.upload-card-badge {
    display: inline-block; font-size: 12.5px; font-weight: 600; padding: 3px 12px; border-radius: 999px; margin: 0 0 10px 0;
}
.st-key-upload_box_purchase .upload-card-badge { background: #DBEAFE; color: #1D4ED8; }
.st-key-upload_box_extract .upload-card-badge { background: #CCFBF1; color: #0F766E; }
.st-key-upload_box_extract .upload-card-icon { background: #F0FDFA; }
/* 7.2) ตกแต่งการ์ด Upload: เงานุ่ม 2 ชั้น + พื้นไล่สีบางๆ + วงกลมสีตัดมุม + ยกตัวตอนชี้เมาส์
        แก้สีของแต่ละการ์ดที่ตัวแปร --box-* ตรงนี้ที่เดียว (accent = สีหลัก, soft = สีพื้นอ่อน, glow = สีเงา/แสง เป็น rgb ไม่มี alpha) */
.st-key-upload_box_purchase { --box-accent: #2563EB; --box-accent-2: #60A5FA; --box-soft: #F3F8FF; --box-glow: 37, 99, 235; }
.st-key-upload_box_extract  { --box-accent: #0D9488; --box-accent-2: #2DD4BF; --box-soft: #F0FDFA; --box-glow: 13, 148, 136; }
.st-key-upload_box_purchase, .st-key-upload_box_extract {
    background:
        radial-gradient(circle at 100% 0%, rgba(var(--box-glow), 0.14) 0, rgba(var(--box-glow), 0) 42%),
        linear-gradient(180deg, var(--box-soft) 0%, #ffffff 55%);
    border-color: rgba(var(--box-glow), 0.28);
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06), 0 14px 30px -10px rgba(var(--box-glow), 0.28);
    transition: transform 0.22s ease, box-shadow 0.22s ease;
}
.st-key-upload_box_purchase:hover, .st-key-upload_box_extract:hover {
    transform: translateY(-2px);
    box-shadow: 0 2px 4px rgba(15, 23, 42, 0.08), 0 20px 38px -10px rgba(var(--box-glow), 0.38);
}
.st-key-upload_box_purchase .upload-card-icon, .st-key-upload_box_extract .upload-card-icon {
    background: #ffffff; box-shadow: 0 0 0 3px rgba(var(--box-glow), 0.12), 0 4px 10px rgba(var(--box-glow), 0.18);
}
.st-key-upload_box_purchase [data-testid="stFileUploaderDropzone"], .st-key-upload_box_extract [data-testid="stFileUploaderDropzone"] {
    position: relative; background: rgba(255, 255, 255, 0.78); border-color: rgba(var(--box-glow), 0.45);
    transition: transform 0.2s ease, background-color 0.2s ease, border-color 0.2s ease, box-shadow 0.2s ease;
}

/* 7.3) ปุ่ม Browser: ไล่สีตามโทนการ์ด + เงา, วงแหวนเรืองแสงเต้นช้าๆ ตอนว่าง, ชี้เมาส์ = ยกขึ้น + แสงเงาไหลผ่าน, กด = ยุบ */
.st-key-upload_box_purchase [data-testid="stFileUploaderDropzone"] > span > button,
.st-key-upload_box_extract [data-testid="stFileUploaderDropzone"] > span > button {
    position: relative; overflow: hidden; border: none;
    background: linear-gradient(135deg, var(--box-accent), var(--box-accent-2));
    box-shadow: 0 6px 14px -4px rgba(var(--box-glow), 0.55);
    animation: upload-browse-pulse 2.4s ease-out infinite;
    transition: transform 0.18s ease, box-shadow 0.18s ease;
}
.st-key-upload_box_purchase [data-testid="stFileUploaderDropzone"] > span > button::before,
.st-key-upload_box_extract [data-testid="stFileUploaderDropzone"] > span > button::before {
    content: ""; position: absolute; top: 0; left: -80%; width: 50%; height: 100%;
    background: linear-gradient(100deg, rgba(255, 255, 255, 0) 0%, rgba(255, 255, 255, 0.55) 50%, rgba(255, 255, 255, 0) 100%);
    transform: skewX(-20deg); pointer-events: none;
}
.st-key-upload_box_purchase [data-testid="stFileUploaderDropzone"] > span > button:hover,
.st-key-upload_box_extract [data-testid="stFileUploaderDropzone"] > span > button:hover {
    background: linear-gradient(135deg, var(--box-accent), var(--box-accent-2));
    transform: translateY(-2px); animation: none; box-shadow: 0 12px 22px -6px rgba(var(--box-glow), 0.65);
}
.st-key-upload_box_purchase [data-testid="stFileUploaderDropzone"] > span > button:hover::before,
.st-key-upload_box_extract [data-testid="stFileUploaderDropzone"] > span > button:hover::before {
    animation: upload-browse-shine 0.75s ease;
}
.st-key-upload_box_purchase [data-testid="stFileUploaderDropzone"] > span > button:active,
.st-key-upload_box_extract [data-testid="stFileUploaderDropzone"] > span > button:active { transform: scale(0.96); }
@keyframes upload-browse-pulse {
    0%   { box-shadow: 0 6px 14px -4px rgba(var(--box-glow), 0.55), 0 0 0 0 rgba(var(--box-glow), 0.45); }
    70%  { box-shadow: 0 6px 14px -4px rgba(var(--box-glow), 0.55), 0 0 0 12px rgba(var(--box-glow), 0); }
    100% { box-shadow: 0 6px 14px -4px rgba(var(--box-glow), 0.55), 0 0 0 0 rgba(var(--box-glow), 0); }
}
@keyframes upload-browse-shine { from { left: -80%; } to { left: 140%; } }

/* 7.4) ตอบรับตอนลากไฟล์: .file-drag-active (ลากไฟล์อยู่ที่ไหนก็ได้ในหน้า) = กล่องเรืองแสงเบาๆ ชวนให้วาง
        data-drag="over" (ลากอยู่เหนือกล่องนั้น) = เส้นทึบ + ขยายนิด + ข้อความเปลี่ยน
        data-drop="done" (เพิ่งวางไฟล์) = วงแหวนกระเพื่อม
        คลาสเหล่านี้ใส่โดย DRAG_FEEDBACK_SCRIPT (ฝังด้วย _inject_drag_feedback_script) */
.file-drag-active .st-key-upload_box_purchase [data-testid="stFileUploaderDropzone"],
.file-drag-active .st-key-upload_box_extract [data-testid="stFileUploaderDropzone"] {
    background: rgba(var(--box-glow), 0.06); border-style: dashed; animation: upload-drop-breathe 1.4s ease-in-out infinite;
}
.st-key-upload_box_purchase [data-testid="stFileUploaderDropzone"][data-drag="over"],
.st-key-upload_box_extract [data-testid="stFileUploaderDropzone"][data-drag="over"] {
    background: rgba(var(--box-glow), 0.12); border-style: solid; border-color: var(--box-accent);
    transform: scale(1.025); animation: none;
    box-shadow: 0 0 0 5px rgba(var(--box-glow), 0.16), 0 16px 30px -10px rgba(var(--box-glow), 0.45);
}
.st-key-upload_box_purchase [data-testid="stFileUploaderDropzone"][data-drag="over"] [data-testid="stFileUploaderDropzoneInstructions"]::before,
.st-key-upload_box_extract [data-testid="stFileUploaderDropzone"][data-drag="over"] [data-testid="stFileUploaderDropzoneInstructions"]::before {
    content: "ปล่อยไฟล์ได้เลย ✨"; color: var(--box-accent);
}
.st-key-upload_box_purchase [data-testid="stFileUploaderDropzone"][data-drop="done"],
.st-key-upload_box_extract [data-testid="stFileUploaderDropzone"][data-drop="done"] { animation: upload-drop-ripple 0.8s ease-out; }
@keyframes upload-drop-breathe {
    0%, 100% { box-shadow: 0 0 0 0 rgba(var(--box-glow), 0); }
    50%      { box-shadow: 0 0 0 6px rgba(var(--box-glow), 0.14); }
}
@keyframes upload-drop-ripple {
    0%   { box-shadow: 0 0 0 0 rgba(22, 163, 74, 0.55); border-color: #16A34A; transform: scale(1.025); }
    100% { box-shadow: 0 0 0 26px rgba(22, 163, 74, 0); transform: scale(1); }
}
/* ผู้ใช้ตั้งค่าลดการเคลื่อนไหว: ปิด animation ทั้งหมดของการ์ด Upload (คงสี/เงาไว้) */
@media (prefers-reduced-motion: reduce) {
    .st-key-upload_box_purchase, .st-key-upload_box_extract,
    .st-key-upload_box_purchase *, .st-key-upload_box_extract *,
    .st-key-upload_box_purchase *::before, .st-key-upload_box_extract *::before {
        animation: none !important; transition: none !important;
    }
}
/* การ์ดตรวจสอบข้อมูลด้านล่าง: ใช้หน้าตาเดียวกับการ์ดฟอร์ม */
.upload-review-hint {
    text-align: center; color: #64748B; font-size: 16px; margin: 0; padding: 16px 12px;
    background: var(--ui-inner-bg); border: 1px dashed var(--ui-dashed-border); border-radius: 16px;
}
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
    purchase_order_number: str = "",
    pr_run_number: str = "",
    contact_name: str = "",
) -> list[str]:
    """ตรวจข้อมูลในฟอร์มก่อนบันทึก

    ช่องบังคับ (ห้ามว่าง): Vendor, Tax ID, P/O No., PR Run No., Tel., Email, Name
    ถ้าจะเพิ่ม/เอาช่องบังคับออก: แก้รายการ required_fields ด้านล่าง (และใส่/ถอด REQUIRED_FIELD_MARK ที่ป้ายช่องใน render_entry_form)

    Args:
        vendor_name: ชื่อผู้ขายที่กรอก
        tax_id: เลขผู้เสียภาษีที่กรอก (ต้องเป็นตัวเลข 13 หลัก)
        tel: เบอร์โทรที่กรอก
        email: อีเมลที่กรอก
        sharepoint_url: ลิงก์ไฟล์บน SharePoint ที่กรอก (ว่างได้)
        purchase_order_number: เลข P/O ที่กรอก
        pr_run_number: เลขรัน PR ที่กรอก
        contact_name: ชื่อผู้ติดต่อที่กรอก

    Returns:
        list ของข้อความปัญหาภาษาไทย ถ้าว่างแปลว่าข้อมูลผ่านทั้งหมด
    """
    problem_messages: list[str] = []

    required_fields: list[tuple[str, str]] = [
        ("Vendor", vendor_name),
        ("Tax ID", tax_id),
        ("P/O No.", purchase_order_number),
        ("PR Run No.", pr_run_number),
        ("Tel.", tel),
        ("Email", email),
        ("Name", contact_name),
    ]
    for field_label, field_value in required_fields:
        if not field_value.strip():
            problem_messages.append(f"กรุณากรอก {field_label}")

    # ถ้ากรอกแล้วต้องมีรูปแบบถูกต้อง (ช่องที่ว่างถูกแจ้งไปแล้วด้านบน)
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


# ตารางรายการที่ค้าง: ชื่อคอลัมน์ที่แสดง และความกว้างที่ต้องการ (None = คอลัมน์ข้อความยาว ยืดตามหน้าจอ)
# ถ้าเพิ่มคอลัมน์ในตารางนี้: เพิ่มชื่อใน OVERDUE_TABLE_COLUMNS แล้วกำหนดความกว้างใน OVERDUE_TABLE_COLUMN_WIDTHS
OVERDUE_TABLE_COLUMNS: dict[str, str] = {
    "id": "รหัส",
    "date": "วันที่",
    "vendor": "ผู้ขาย",
    "po_no": "เลขที่ PO",
    "total_price": "ราคารวม (บาท)",
    "days_pending": "ค้างมาแล้ว (วัน)",
}
OVERDUE_TABLE_COLUMN_WIDTHS: dict[str, Optional[int]] = {
    "รหัส": 90,
    "วันที่": 140,
    "ผู้ขาย": None,
    "เลขที่ PO": None,
    "ราคารวม (บาท)": 170,
    "ค้างมาแล้ว (วัน)": 190,
}
# ค้างตั้งแต่กี่วันขึ้นไปถือว่า "วิกฤต" (ป้ายวันที่ค้างเป็นสีแดงเข้ม) ที่เหลือเป็นสีส้ม แก้ตัวเลขตรงนี้ได้
OVERDUE_CRITICAL_DAYS: int = 30

# ป้ายจำนวนวันที่ค้างในตาราง: สร้างด้วย element ไม่ต่อสตริง HTML เพื่อกัน XSS
# OVERDUE_CRITICAL_DAYS ถูกแทนด้วยค่าคงที่ข้างบน
OVERDUE_DAYS_BADGE_RENDERER_JS: str = r"""
class OverdueDaysBadgeRenderer {
    init(params) {
        const days = Number(params.value);
        this.eGui = document.createElement('span');
        if (!isFinite(days)) { this.eGui.textContent = String(params.value || ''); return; }
        const critical = days >= OVERDUE_CRITICAL_DAYS;
        const badge = document.createElement('span');
        badge.textContent = (critical ? '🔥 ' : '⏰ ') + days + ' วัน';
        badge.style.cssText = 'display:inline-block;padding:2px 12px;border-radius:999px;font-weight:700;font-size:15px;line-height:26px;'
            + (critical ? 'background:#FEE2E2;color:#B91C1C;' : 'background:#FFEDD5;color:#C2410C;');
        this.eGui.appendChild(badge);
    }
    getGui() { return this.eGui; }
}
"""


def build_overdue_alert_html(overdue_count: int, longest_days: int) -> str:
    """สร้าง HTML ของแถบแจ้งเตือนใบกำกับภาษีค้าง (ประกอบจากตัวเลขภายในระบบเท่านั้น ไม่มีข้อความจากผู้ใช้)

    Args:
        overdue_count: จำนวนรายการที่ค้างเกินกำหนด
        longest_days: จำนวนวันที่ค้างนานที่สุด

    Returns:
        สตริง HTML (สไตล์อยู่ใน PAGE_CSS_RULES หัวข้อ "แจ้งเตือนค้าง")
    """
    # อนาคต: ถ้าจะเพิ่มปุ่ม "แจ้งเตือนผ่าน Line OA" ให้เพิ่มปุ่มต่อท้าย div.overdue-alert-text ในนี้
    return (
        '<div class="overdue-alert" role="alert">'
        '<div class="overdue-alert-icon">⚠️</div>'
        '<div class="overdue-alert-text">'
        f'<div class="overdue-alert-title">ใบกำกับภาษีค้างเกิน {OVERDUE_DAYS_LIMIT} วัน</div>'
        '<div class="overdue-alert-sub">กรุณาติดตามจากผู้ขายโดยเร็ว ก่อนจะค้างนานกว่านี้</div>'
        '</div>'
        f'<div class="overdue-alert-badges">'
        f'<span class="overdue-pill overdue-pill-count"><b>{overdue_count}</b> รายการ</span>'
        f'<span class="overdue-pill overdue-pill-days">นานสุด <b>{longest_days}</b> วัน</span>'
        '</div>'
        '</div>'
    )


def render_overdue_table(overdue_transactions: list[dict[str, Any]]) -> None:
    """วาดตารางรายการที่ค้างให้เต็มความกว้าง หน้าตาเดียวกับตารางหลัก (วันที่เป็น DD/MM/YYYY, เงินมีคอมม่า)

    Args:
        overdue_transactions: รายการที่ค้างเกินกำหนด (จาก find_overdue_transactions มีคอลัมน์ days_pending)
    """
    try:
        overdue_table = pd.DataFrame(overdue_transactions)[list(OVERDUE_TABLE_COLUMNS)]
        overdue_table.columns = list(OVERDUE_TABLE_COLUMNS.values())
        grid_options = build_grid_options(
            overdue_table,
            column_widths=OVERDUE_TABLE_COLUMN_WIDTHS,
            money_columns=("ราคารวม (บาท)",),
            date_columns=("วันที่",),
            extra_column_options={
                "ค้างมาแล้ว (วัน)": {
                    "cellRenderer": JsCode(
                        OVERDUE_DAYS_BADGE_RENDERER_JS.replace("OVERDUE_CRITICAL_DAYS", str(OVERDUE_CRITICAL_DAYS))
                    ),
                },
            },
        )
        # ต่อท้าย key ด้วยค่าแฮชของข้อมูล: ข้อมูลเปลี่ยนแล้วตารางวาดใหม่ ไม่ค้างข้อมูลเก่า
        content_hash = int(pd.util.hash_pandas_object(overdue_table.reset_index(drop=True), index=False).sum() % 10**9)
        show_grid(overdue_table, grid_options, f"overdue_table_{content_hash}")
    except (KeyError, ValueError) as error:
        logger.warning("วาดตารางรายการที่ค้างไม่สำเร็จ: %s", error)
        st.error("แสดงตารางรายการที่ค้างไม่สำเร็จ กรุณารีเฟรชหน้าอีกครั้ง")


def render_overdue_alert() -> None:
    """แสดงแถบแจ้งเตือนถ้ามีใบกำกับภาษีค้างเกินกำหนด พร้อมแถบกางดูรายการที่ค้าง

    หมายเหตุ: ตรวจจากรายการค้างทุกวันที่ ไม่ขึ้นกับ Date Filter
    เพราะรายการเก่าที่ค้างอยู่ต้องไม่หลุดจากการแจ้งเตือนเมื่อผู้ใช้เลือกช่วงวันที่ใหม่
    """
    pending_transactions = get_transactions(invoice_status=STATUS_PENDING)
    overdue_transactions = find_overdue_transactions(pending_transactions, date.today())

    # ไม่มีรายการค้าง (X = 0) -> ซ่อนแถบแจ้งเตือนทั้งหมด ไม่แสดงอะไรเลย
    if not overdue_transactions:
        return

    # find_overdue_transactions เรียงจากค้างนานสุดก่อน รายการแรกจึงเป็นรายการที่นานที่สุด
    longest_days = int(overdue_transactions[0]["days_pending"])
    with st.container(key="overdue_alert"):
        st.markdown(build_overdue_alert_html(len(overdue_transactions), longest_days), unsafe_allow_html=True)
        # on_change="rerun" + เช็ค .open: วาดตารางเมื่อกางออกแล้วเท่านั้น (ตาราง AgGrid ที่ถูกสร้างตอนพับอยู่จะกว้าง 0 แล้วแสดงไม่ได้)
        overdue_expander = st.expander("ดูรายการที่ค้าง", on_change="rerun")
        if overdue_expander.open:
            with overdue_expander:
                render_overdue_table(overdue_transactions)


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
        # คอลัมน์สถานะ: แสดงเป็นป้ายสี คลิกครั้งเดียวก็เปิด dropdown เลือก Pending / Completed
        # (singleClickEdit ตั้งเฉพาะคอลัมน์นี้ คอลัมน์อื่นยังต้องดับเบิลคลิกเพื่อกันแก้ผิด)
        "invoice_status": {
            "singleClickEdit": True,
            "cellEditorPopup": True,
            "cellRenderer": JsCode(STATUS_BADGE_RENDERER_JS.replace("STATUS_COLORS", json.dumps(STATUS_BADGE_COLORS))),
            "cellEditor": JsCode(
                STATUS_DROPDOWN_EDITOR_JS
                .replace("STATUS_OPTIONS", json.dumps(STATUS_EDITOR_OPTIONS))
                .replace("STATUS_COLORS", json.dumps(STATUS_BADGE_COLORS))
            ),
        },
        "unit_price": {"cellEditor": "agNumberCellEditor", "cellEditorParams": {"min": 0}},
        # คอลัมน์ไฟล์: แสดงเป็นไอคอน กดแล้วเปิดลิงก์ SharePoint ในแท็บใหม่ (ดู FILE_LINK_RENDERER_JS)
        "sharepoint_url": {
            "cellRenderer": JsCode(
                FILE_LINK_RENDERER_JS
                .replace("FILE_ICON", FILE_LINK_ICON)
                .replace("FILE_CIRCLE_PX", str(FILE_LINK_CIRCLE_PX))
                .replace("FILE_HOVER_BG", FILE_LINK_HOVER_BACKGROUND)
                .replace("FILE_HOVER_SHADOW", FILE_LINK_HOVER_SHADOW)
            ),
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
        hidden_columns=(ROW_POSITION_COLUMN, *HIDDEN_TABLE_COLUMNS),  # ซ่อนในตาราง แต่ข้อมูล/Export ยังครบ
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


def convert_table_to_csv_bytes(export_table: pd.DataFrame) -> Optional[bytes]:
    """แปลงตารางเป็นไฟล์ CSV (UTF-8 แบบมี BOM เพื่อให้ Excel เปิดภาษาไทยไม่เพี้ยน)

    Args:
        export_table: ตารางที่กรองแล้ว (หัวคอลัมน์ตาม TABLE_COLUMNS)

    Returns:
        ไบต์ของไฟล์ CSV หรือ None ถ้าแปลงไม่สำเร็จ
    """
    try:
        return export_table.to_csv(index=False).encode("utf-8-sig")
    except (ValueError, TypeError, UnicodeError) as error:
        logger.error("แปลงตารางเป็น CSV ไม่สำเร็จ: %s", error, exc_info=True)
        st.error(f"❌ สร้างไฟล์ CSV ไม่สำเร็จ: {error}")
        return None


def convert_table_to_excel_bytes(export_table: pd.DataFrame) -> Optional[bytes]:
    """แปลงตารางเป็นไฟล์ .xlsx ในหน่วยความจำ (io.BytesIO + pd.ExcelWriter ต้องใช้ openpyxl)

    Args:
        export_table: ตารางที่กรองแล้ว (หัวคอลัมน์ตาม TABLE_COLUMNS)

    Returns:
        ไบต์ของไฟล์ Excel หรือ None ถ้าแปลงไม่สำเร็จ
    """
    try:
        excel_buffer = io.BytesIO()
        with pd.ExcelWriter(excel_buffer, engine="openpyxl") as excel_writer:
            export_table.to_excel(excel_writer, index=False, sheet_name="MasterList")
        return excel_buffer.getvalue()
    except (ValueError, TypeError, OSError, ImportError) as error:
        logger.error("แปลงตารางเป็น Excel ไม่สำเร็จ: %s", error, exc_info=True)
        st.error(f"❌ สร้างไฟล์ Excel ไม่สำเร็จ: {error}")
        return None


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
            action_bar = st.container(key="table_action_bar")  # key ใช้ให้ CSS responsive (config/styles.py) จับแถบปุ่ม

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
                # Toolbar แบบ space-between: ซ้าย = ปุ่มลบ | กลาง = ช่องว่างดัน | ขวา = กล่องรวมปุ่ม Export
                # ถ้าจะเพิ่มปุ่มจัดการข้อมูลให้ใส่ใน col_left ถ้าเพิ่มปุ่มส่งออกให้เพิ่มจำนวนใน st.columns ของ col_right
                # สัดส่วน [2.5, 6, 3.5]: ช่องกลางกว้างสุดทำหน้าที่เป็นสปริงดันปุ่มไปชิดขอบ (ปรับได้เช่น [2, 7, 3])
                col_left, _col_spacer, col_right = st.columns([2.5, 6, 3.5], vertical_alignment="center")
                with col_right:
                    # กล่องห่อฝั่งขวา: แบ่งเป็น 2 กล่องย่อยเท่ากัน ระยะห่างแคบ (gap="small") สำหรับ CSV และ Excel
                    csv_column, excel_column = st.columns(2, gap="small", vertical_alignment="center")
                is_delete_clicked = col_left.button(
                    f"🗑️ ลบรายการที่เลือก ({len(selected_positions)})",
                    key="delete_selected_rows",
                    disabled=not selected_positions,
                    help="ติ๊กช่องหน้าแถวที่ต้องการลบ แล้วกดปุ่มนี้",
                    use_container_width=True,
                )
                # ส่งออกข้อมูลชุดเดียวกับที่แสดงในตาราง (ผ่าน Date Filter / Search / Item / Vendor แล้ว)
                export_file_stem = f"masterlist_{start_date.isoformat()}_{end_date.isoformat()}"
                csv_bytes = convert_table_to_csv_bytes(display_table)
                if csv_bytes is not None:
                    csv_column.download_button(
                        "⬇️ Export CSV",
                        data=csv_bytes,
                        file_name=f"{export_file_stem}.csv",
                        mime="text/csv",
                        key="export_csv_button",
                        use_container_width=True,
                    )
                excel_bytes = convert_table_to_excel_bytes(display_table)
                if excel_bytes is not None:
                    excel_column.download_button(
                        "⬇️ Export Excel",
                        data=excel_bytes,
                        file_name=f"{export_file_stem}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        key="export_excel_button",
                        use_container_width=True,
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

    # พบใบกำกับภาษีในไฟล์ -> ตั้งสถานะเป็น "มีใบกำกับภาษี" (Completed) ให้เอง ผู้ใช้แก้ในฟอร์มได้
    tax_invoice_notice = ""
    if extracted_fields.has_tax_invoice:
        st.session_state[SESSION_KEY_ENTRY_HAS_INVOICE] = INVOICE_CHOICE_HAS
        tax_invoice_notice = " 🧾 พบใบกำกับภาษีในไฟล์ ตั้งสถานะเป็น Completed ให้อัตโนมัติ"

    if extracted_fields.warning_message:
        return f"⚠️ {extracted_fields.warning_message}{tax_invoice_notice}"
    return f"✅ เติมข้อมูลจากไฟล์ให้แล้ว กรุณาตรวจความถูกต้องก่อนกด Upload{tax_invoice_notice}"


# สคริปต์ตอบรับตอนลากไฟล์ (ค่าคงที่ ไม่รับข้อมูลจากผู้ใช้) ผูก event ที่ document ของหน้าหลักเพียงครั้งเดียว
# - ลากไฟล์เข้ามาในหน้า: ใส่ .file-drag-active ที่ <html> / ลากอยู่เหนือกล่องไหน: ตั้ง data-drag ที่กล่องนั้น
# - วางไฟล์: ตั้ง data-drop ชั่วครู่ (CSS ข้อ 7.4 เป็นตัวทำ animation)
DRAG_FEEDBACK_SCRIPT: str = r"""
(function () {
    if (window.__uploadDragFeedbackBound) { return; }
    window.__uploadDragFeedbackBound = true;
    var ZONE = '[data-testid="stFileUploaderDropzone"]';
    var root = document.documentElement;
    var hasFiles = function (event) {
        var types = event.dataTransfer && event.dataTransfer.types;
        return !!types && Array.prototype.indexOf.call(types, 'Files') >= 0;
    };
    var zoneOf = function (event) { return event.target && event.target.closest ? event.target.closest(ZONE) : null; };
    var clearDragging = function () {
        root.classList.remove('file-drag-active');
        document.querySelectorAll(ZONE + '[data-drag="over"]').forEach(function (zone) { zone.removeAttribute('data-drag'); });
    };
    ['dragenter', 'dragover'].forEach(function (name) {
        document.addEventListener(name, function (event) {
            if (!hasFiles(event)) { return; }
            root.classList.add('file-drag-active');
            var zone = zoneOf(event);
            document.querySelectorAll(ZONE + '[data-drag="over"]').forEach(function (other) { if (other !== zone) { other.removeAttribute('data-drag'); } });
            if (zone) { zone.setAttribute('data-drag', 'over'); }
        }, true);
    });
    document.addEventListener('dragleave', function (event) {
        if (!event.relatedTarget) { clearDragging(); return; }  // ลากออกนอกหน้าต่าง
        var zone = zoneOf(event);
        if (zone && !zone.contains(event.relatedTarget)) { zone.removeAttribute('data-drag'); }
    }, true);
    document.addEventListener('drop', function (event) {
        var zone = zoneOf(event);
        clearDragging();
        if (!zone) { return; }
        zone.setAttribute('data-drop', 'done');
        setTimeout(function () { zone.removeAttribute('data-drop'); }, 900);
    }, true);
    document.addEventListener('dragend', clearDragging, true);
})();
"""


def _inject_drag_feedback_script() -> None:
    """ฝังสคริปต์ตอบรับตอนลากไฟล์ (animation ที่กล่อง Upload) ถ้าฝังไม่ได้ หน้ายังใช้งานปกติ แค่ไม่มี animation ตอนลาก

    ใช้ iframe สูง 0 รันสคริปต์ แล้วสั่งให้ทำงานใน window ของหน้าหลักด้วย eval (หน้าหลักกับ iframe เป็น origin เดียวกัน)
    """
    try:
        components.html(
            f"<script>try {{ window.parent.eval({json.dumps(DRAG_FEEDBACK_SCRIPT)}); }} catch (e) {{}}</script>",
            height=0,
        )
    except Exception as error:  # ไม่ให้ animation เล็กน้อยทำให้หน้าล้ม
        logger.warning("ฝังสคริปต์ animation การลากไฟล์ไม่สำเร็จ: %s", error)


def _render_upload_card_heading(icon: str, title: str, hint: str, badge: str) -> None:
    """วาดหัวข้อของกล่องอัปโหลด: ไอคอน + ชื่อ (ฟอนต์ Prompt ขนาดใหญ่) + คำอธิบายสั้น + ป้ายบอกปลายทางของไฟล์/ข้อมูล

    ลักษณะ/ขนาดตัวอักษรแก้ได้ใน CSS ข้อ 7 (PAGE_CSS_RULES) ที่ .upload-card-title / .upload-card-hint / .upload-card-badge

    Args:
        icon: อีโมจิหน้าชื่อ
        title: ชื่อกล่อง
        hint: คำอธิบายสั้นๆ ว่ากล่องนี้ใช้ทำอะไร
        badge: ป้ายสั้นๆ บอกว่าข้อมูล/ไฟล์ไปที่ไหน
    """
    st.markdown(
        f'<div class="upload-card-heading"><span class="upload-card-icon">{icon}</span>'
        f'<div><div class="upload-card-title">{title}</div>'
        f'<div class="upload-card-hint">{hint}</div></div></div>'
        f'<span class="upload-card-badge">{badge}</span>',
        unsafe_allow_html=True,
    )


def _prefill_form_from_extract_documents(extract_documents: list[UploadedFile], form_counter: int) -> str:
    """ดึงข้อมูลจากไฟล์หลายไฟล์ในกล่อง Extract: ใช้ไฟล์แรกที่อ่านข้อความได้ (PDF/Excel) เติมลงฟอร์ม

    Args:
        extract_documents: ไฟล์ที่ผู้ใช้อัปโหลด (ต้องมีอย่างน้อย 1 ไฟล์)
        form_counter: ตัวนับของฟอร์มปัจจุบัน

    Returns:
        ข้อความสรุปผลให้แสดงผู้ใช้
    """
    readable_documents = [
        document for document in extract_documents if document.name.lower().endswith(AUTO_EXTRACT_EXTENSIONS)
    ]
    source_document = readable_documents[0] if readable_documents else extract_documents[0]
    summary_message = _prefill_form_from_purchase_document(source_document, form_counter)
    if len(extract_documents) > 1:
        summary_message += f" (อ่านจากไฟล์ {source_document.name} จากทั้งหมด {len(extract_documents)} ไฟล์)"
    return summary_message


def upload_attachments_to_sharepoint_if_ready(attached_documents: list[UploadedFile]) -> tuple[Optional[str], str]:
    """ส่งไฟล์ที่แนบขึ้น SharePoint (เฉพาะเมื่อตั้งค่า SHAREPOINT_* ใน .env ครบ) คืนลิงก์ไฟล์แรกกับข้อความเตือน

    ถ้าส่งไม่สำเร็จจะไม่ทำให้การบันทึกรายการล้ม (ไฟล์ยังเก็บในเครื่องแล้ว) แต่คืนข้อความเตือนให้แสดงผู้ใช้

    Args:
        attached_documents: ไฟล์จากกล่อง Purchase

    Returns:
        (ลิงก์ SharePoint ของไฟล์แรก หรือ None, ข้อความเตือน ว่างถ้าไม่มีปัญหา)
    """
    if not attached_documents or not is_sharepoint_configured():
        return None, ""

    first_link: Optional[str] = None
    try:
        for document in attached_documents:
            uploaded_link = upload_document_to_sharepoint(document.getvalue(), document.name)
            if first_link is None:
                first_link = uploaded_link
    except SharePointError as error:
        logger.error("ส่งไฟล์ขึ้น SharePoint ไม่สำเร็จ: %s", error)
        return first_link, f"⚠️ บันทึกรายการแล้ว แต่ส่งไฟล์ขึ้น SharePoint ไม่สำเร็จ: {error}"
    return first_link, ""


def render_upload_section(form_counter: int) -> bool:
    """วาดการ์ด "Upload File": 2 กล่องแยกเป็นการ์ดคนละใบ วางคู่กัน กล่องละหลายไฟล์ได้

    - Upload P/O to Purchase: ไฟล์ขึ้นแสดงที่หน้าเว็บไซต์ (แนบกับรายการ) และส่งขึ้น SharePoint ตอนกดบันทึก
      (SharePoint ส่งจริงเมื่อตั้งค่า SHAREPOINT_* ใน .env แล้วเท่านั้น)
    - Upload P/O (เก็บในเครื่อง): Extract Text จากไฟล์ เติมข้อมูลที่ต้องการลงฟอร์มเพื่อส่งเข้า Master-List
      และเก็บไฟล์ไว้ใน local_uploads/ ผูกกับรายการเมื่อกดบันทึก

    Args:
        form_counter: ตัวนับของฟอร์มปัจจุบัน (ทำให้กล่องว่างใหม่หลังบันทึกสำเร็จ)

    Returns:
        True ถ้ามีไฟล์ถูกอัปโหลดแล้วอย่างน้อย 1 กล่อง (ผู้เรียกใช้ตัดสินใจแสดงฟอร์มตรวจสอบ)
    """
    _inject_drag_feedback_script()
    purchase_column, extract_column = st.columns(2, gap="large")

    # --- กล่องที่ 1: Upload P/O to Purchase (ขึ้นเว็บไซต์ + SharePoint) ---
    with purchase_column, st.container(key="upload_box_purchase"):
        _render_upload_card_heading(
            "📄", "Upload P/O to Purchase", "แนบไฟล์กับรายการ · หลายไฟล์ได้", "ขึ้นเว็บไซต์ + SharePoint"
        )
        purchase_documents: list[UploadedFile] = st.file_uploader(
            "Upload P/O to Purchase",
            type=ALLOWED_FILE_TYPES,
            accept_multiple_files=True,
            key=_field_key("purchase_uploader", form_counter),
            label_visibility="collapsed",
        )
        if purchase_documents and not is_sharepoint_configured():
            st.caption("ℹ️ ยังไม่ได้เชื่อม SharePoint ไฟล์จะแสดงบนเว็บไซต์ก่อน (ตั้งค่า SHAREPOINT_* ใน .env เพื่อเปิดส่งขึ้น SharePoint)")

    # --- กล่องที่ 2: Upload P/O (เก็บในเครื่อง) Extract Text -> Master-List + เก็บไฟล์ใน local_uploads/ ---
    # เลือกไฟล์แล้วบันทึกทันที เก็บที่อยู่ไฟล์ไว้ใน session แล้วผูกกับรายการเมื่อกดปุ่มบันทึกในการ์ดตรวจสอบ
    with extract_column, st.container(key="upload_box_extract"):
        _render_upload_card_heading(
            "🔎", "Upload P/O (เก็บในเครื่อง)", "อ่านข้อมูลอัตโนมัติ · หลายไฟล์ได้", "Extract → Master-List"
        )
        extract_documents: list[UploadedFile] = st.file_uploader(
            "Upload P/O (เก็บในเครื่อง)",
            type=ALLOWED_FILE_TYPES,
            accept_multiple_files=True,
            key=_field_key("local_uploader", form_counter),
            label_visibility="collapsed",
        )
        if not extract_documents:
            # ผู้ใช้กดลบไฟล์ออก ล้างสถานะ เพื่อให้อัปโหลดไฟล์เดิมซ้ำแล้วดึงข้อมูลใหม่ได้
            st.session_state.pop(SESSION_KEY_EXTRACT_FILE_ID, None)
            st.session_state.pop(SESSION_KEY_EXTRACT_NOTICE, None)
            st.session_state.pop(SESSION_KEY_LOCAL_FILE_ID, None)
            st.session_state.pop(SESSION_KEY_LOCAL_NOTICE, None)
            st.session_state.pop(SESSION_KEY_LOCAL_PATH, None)
        else:
            # ประมวลผลแค่ครั้งเดียวต่อชุดไฟล์ (Streamlit รันสคริปต์ซ้ำทุกครั้งที่มีการกดอะไรสักอย่าง)
            extract_file_id = "|".join(f"{document.name}:{document.size}" for document in extract_documents)
            extract_file_id += f":{form_counter}"
            if st.session_state.get(SESSION_KEY_EXTRACT_FILE_ID) != extract_file_id:
                st.session_state[SESSION_KEY_EXTRACT_FILE_ID] = extract_file_id
                st.session_state[SESSION_KEY_EXTRACT_NOTICE] = _prefill_form_from_extract_documents(
                    extract_documents, form_counter
                )
                try:
                    saved_paths = [
                        save_document_locally(document.getvalue(), document.name) for document in extract_documents
                    ]
                    st.session_state[SESSION_KEY_LOCAL_PATH] = FILE_PATH_SEPARATOR.join(saved_paths)
                    st.session_state[SESSION_KEY_LOCAL_NOTICE] = (
                        "success",
                        f"💾 เก็บไฟล์ในเครื่องแล้ว {len(saved_paths)} ไฟล์ จะผูกกับรายการเมื่อกดบันทึก",
                    )
                except LocalStorageError as error:
                    st.session_state.pop(SESSION_KEY_LOCAL_PATH, None)
                    st.session_state[SESSION_KEY_LOCAL_NOTICE] = ("error", f"❌ {error}")

            st.caption(st.session_state.get(SESSION_KEY_EXTRACT_NOTICE, ""))
            notice_level, notice_message = st.session_state.get(SESSION_KEY_LOCAL_NOTICE, ("", ""))
            if notice_level == "error":
                st.error(notice_message)
            elif notice_message:
                st.caption(notice_message)

    return bool(purchase_documents) or bool(extract_documents)


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
    # (หมวดหมู่และสถานะใบกำกับภาษีใช้ค่าจาก SESSION_KEY_ENTRY_* ด้านบนตอนบันทึก ไม่มีช่องซ้ำในฟอร์มแล้ว)
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
    st.markdown(_build_step_header_html(1, "ข้อมูลเบื้องต้น"), unsafe_allow_html=True)

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


def _labeled_text_input(label_text: str, field_name: str, form_counter: int, container: Any = st) -> str:
    """วาดช่องกรอกข้อความ (ป้ายชื่ออยู่เหนือช่อง) ในคอลัมน์ที่ระบุ แล้วคืนค่าที่กรอก

    Args:
        label_text: ข้อความป้ายชื่อ เช่น "Tax ID"
        field_name: ชื่อภายในของช่อง (ใช้สร้าง key)
        form_counter: ตัวนับของฟอร์มปัจจุบัน
        container: คอลัมน์/คอนเทนเนอร์ที่จะวางช่อง (ค่าเริ่มต้น = วางตรงๆ ในหน้า)

    Returns:
        ข้อความที่ผู้ใช้กรอก (ตัดช่องว่างหัวท้ายแล้ว)
    """
    return container.text_input(
        f"{label_text}{REQUIRED_FIELD_MARK}",  # ช่องกรอกทั้งหมดในฟังก์ชันนี้เป็นช่องบังคับ (ดู validate_form_input)
        key=_field_key(field_name, form_counter),
        placeholder=FORM_FIELD_PLACEHOLDERS.get(field_name, ""),
    ).strip()


def _vendor_autocomplete_input(form_counter: int) -> str:
    """วาดแถว Vendor แบบ Auto-complete: พิมพ์ค้นหาชื่อเดิมได้ หรือพิมพ์ชื่อเจ้าใหม่แล้วกด Enter ได้

    ใช้ st.selectbox(accept_new_options=True) ซึ่งทำงานได้ในฟอร์มโดยไม่ต้องรีรันหน้า
    ถ้าฐานข้อมูลยังว่าง รายการตัวเลือกจะว่าง ผู้ใช้พิมพ์ชื่อใหม่ได้ตามปกติ

    Args:
        form_counter: ตัวนับของฟอร์มปัจจุบัน

    Returns:
        ชื่อผู้ขายที่เลือก/พิมพ์ (ตัดช่องว่างหัวท้ายแล้ว; ว่างถ้ายังไม่กรอก)
    """
    vendor_key = _field_key("vendor", form_counter)
    existing_vendors = get_unique_vendors()
    # ชื่อที่ดึงมาจากไฟล์ (prefill) อาจยังไม่อยู่ในฐานข้อมูล ต้องใส่ในตัวเลือกด้วยเพื่อให้แสดงค่าได้
    prefilled_vendor = str(st.session_state.get(vendor_key) or "").strip()
    if prefilled_vendor and prefilled_vendor not in existing_vendors:
        existing_vendors = [prefilled_vendor, *existing_vendors]

    selected_vendor = st.selectbox(
        f"Vendor{REQUIRED_FIELD_MARK}",
        options=existing_vendors,
        index=None,
        accept_new_options=True,
        placeholder="พิมพ์ค้นหา หรือพิมพ์ชื่อผู้ขายใหม่",
        key=vendor_key,
    )
    return str(selected_vendor or "").strip()


def render_entry_form(
    form_counter: int, show_po_uploader: bool = True, title: str = "กรอกข้อมูล"
) -> None:
    """วาดการ์ด "กรอกข้อมูล" และจัดการเมื่อกดปุ่ม Upload (บันทึก)

    ถ้าจะเพิ่มฟิลด์ใหม่ ต้องแก้ 3 จุด:
    (1) เพิ่มช่องกรอกใน "ส่วนที่ 1"  (2) ส่งค่าเข้า add_transaction ใน "ส่วนที่ 4"
    (3) ถ้าเป็นคอลัมน์ใหม่ ต้องเพิ่มใน database.py และ TABLE_COLUMNS ด้านบนไฟล์นี้ด้วย

    Args:
        form_counter: ตัวนับของฟอร์ม เมื่อบันทึกสำเร็จจะถูกบวกเพื่อให้ฟอร์มว่างใหม่
                      (ถ้าบันทึกไม่สำเร็จ ไม่บวก ผู้ใช้จะได้ไม่ต้องกรอกใหม่)
        show_po_uploader: แสดงช่อง Upload PO ใต้ฟอร์มหรือไม่ (โหมด Upload ข้อมูลซ่อนไว้ เพราะไฟล์มาจากกล่องด้านบน)
        title: หัวข้อการ์ด
    """
    st.markdown(f'<div class="card-title">{title}</div>', unsafe_allow_html=True)

    with st.form(key=f"transaction_form_{form_counter}", border=False):
        # ส่วนที่ 1: ข้อมูลพื้นฐาน จัดเป็น Grid 2 คอลัมน์ (ป้ายชื่ออยู่เหนือช่องกรอก)
        # ถ้าจะเพิ่มฟิลด์ใหม่: เพิ่มแถว `left_column, right_column = st.columns(2)` ต่อท้ายหรือใส่ในช่องว่างของแถวที่มีอยู่
        left_column, right_column = st.columns(2)  # แถว 1: Tax ID | Vendor
        tax_id = _labeled_text_input("Tax ID", "tax_id", form_counter, left_column)
        with right_column:
            vendor_name = _vendor_autocomplete_input(form_counter)

        left_column, right_column = st.columns(2)  # แถว 2: P/O No. | PR Run No.
        purchase_order_number = _labeled_text_input("P/O No.", "po_no", form_counter, left_column)
        pr_run_number = _labeled_text_input("PR Run No.", "pr_run_no", form_counter, right_column)

        left_column, right_column = st.columns(2)  # แถว 3: Tel. | Email
        tel = _labeled_text_input("Tel.", "tel", form_counter, left_column)
        email = _labeled_text_input("Email", "email", form_counter, right_column)

        left_column, right_column = st.columns(2)  # แถว 4: Name | Date
        contact_name = _labeled_text_input("Name", "contact_name", form_counter, left_column)
        document_date = right_column.date_input(
            "Date",
            value=date.today(),
            format="DD/MM/YYYY",
            key=_field_key("date", form_counter),
        )

        # สถานะใบกำกับภาษีและหมวดหมู่ ถูกเลือกไว้แล้วในขั้นที่ 1 จึงไม่แสดงซ้ำในฟอร์ม (อ่านค่าจาก session ตอนบันทึก)
        invoice_choice: str = st.session_state.get(SESSION_KEY_ENTRY_HAS_INVOICE, INVOICE_CHOICE_NOT_YET)
        category_name: str = st.session_state.get(SESSION_KEY_ENTRY_ITEM, STEP1_ITEM_OPTIONS[0])

        # ข้อมูลจากเอกสาร PR / Quotation (Master-List, ไม่บังคับ): ระบบเติมให้จากไฟล์ PDF ผู้ใช้ตรวจ/แก้ได้
        # ถ้าจะเพิ่มฟิลด์ใหม่: เพิ่มช่องตรงนี้ + ส่งค่าเข้า add_transaction ด้านล่าง
        with st.expander("ข้อมูลจากเอกสาร PR / Quotation (ไม่บังคับ)"):
            left_column, right_column = st.columns(2)  # PR No./Quotation | PR Date
            qt_no = left_column.text_input("เลขที่ Quotation", key=_field_key("qt_no", form_counter)).strip()
            pr_request_date = right_column.date_input(
                "วันที่ PR",
                value=None,  # None = ยังไม่ระบุ (ไม่บังคับ) ผู้ใช้เลือกเองหรือรอระบบเติมจากไฟล์
                format="DD/MM/YYYY",
                key=_field_key("pr_request_date", form_counter),
            )
            description = st.text_area("รายละเอียดอุปกรณ์", key=_field_key("description", form_counter)).strip()
            left_column, right_column = st.columns(2)  # Price | Net Price
            total_price = left_column.number_input(
                "ราคารวม (บาท)",
                min_value=0.0,
                step=100.0,
                format="%.2f",
                key=_field_key("total_price", form_counter),
            )
            unit_price = right_column.number_input(
                "ราคาสุทธิที่รวม Discount แล้ว (บาท)",
                min_value=0.0,
                step=100.0,
                format="%.2f",
                key=_field_key("unit_price", form_counter),
            )

        # ข้อมูลเพิ่มเติม (ไม่บังคับ): ซ่อนไว้ไม่รก
        with st.expander("รายละเอียดเพิ่มเติม (ไม่บังคับ)"):
            # ลิงก์ไฟล์บน SharePoint (ใช้เปิดจากไอคอนโฟลเดอร์ในตาราง) จนกว่าระบบจะอัปโหลดขึ้น SharePoint ให้เอง
            sharepoint_url = st.text_input(
                "ลิงก์ไฟล์บน SharePoint (https://...)", key=_field_key("sharepoint_url", form_counter)
            ).strip()

        # ส่วนที่ 2: ไฟล์เอกสารที่แนบมากับรายการนี้ (คั่นด้วยเส้นแบ่งจากข้อมูลพื้นฐาน)
        st.divider()
        uploaded_po_documents: list[UploadedFile] = []
        if show_po_uploader:
            uploaded_po_documents = st.file_uploader(
                "Upload PO (แนบได้หลายไฟล์)",
                type=ALLOWED_FILE_TYPES,
                accept_multiple_files=True,
                key=_field_key("form_files", form_counter),
            )

        # ส่วนที่ 3: ปุ่ม ย้อนกลับ (ซ้าย, รอง) + บันทึกข้อมูล (ขวา, หลัก) อยู่บรรทัดเดียวกัน คั่นด้วยช่องว่างตรงกลาง
        # (ปุ่มย้อนกลับต้องเป็น form_submit_button เพราะอยู่ในฟอร์ม
        # และใช้ on_click ทำงานก่อนหน้าถูกวาดใหม่ จึงไม่เกิด Error ตอนเปลี่ยนหน้า)
        # สัดส่วนคอลัมน์ [4, 2, 4] กว้างพอให้คำว่า "ย้อนกลับ" แสดงเต็ม
        st.divider()
        back_column, _spacer_column, save_column = st.columns([4, 2, 4])
        back_column.form_submit_button(
            "⬅️ ย้อนกลับ", on_click=go_back_to_questions_step, type="secondary", use_container_width=True
        )
        is_submitted = save_column.form_submit_button(
            "💾 บันทึกข้อมูล", type="primary", use_container_width=True
        )

    if not is_submitted:
        return

    # ส่วนที่ 4: ตรวจข้อมูล -> บันทึกไฟล์ -> บันทึกลงฐานข้อมูล
    problem_messages = validate_form_input(
        vendor_name,
        tax_id,
        tel,
        email,
        sharepoint_url,
        purchase_order_number=purchase_order_number,
        pr_run_number=pr_run_number,
        contact_name=contact_name,
    )
    if problem_messages:
        for problem_message in problem_messages:
            st.error(f"❌ {problem_message}")
        return

    # ไฟล์ที่แนบกับรายการ: (1) ไฟล์ใต้ฟอร์ม (2) ไฟล์จากกล่อง Purchase (โหมด Upload ข้อมูล) บันทึกตอนนี้เลย
    # (3) ไฟล์ที่บันทึกไว้แล้วจากกล่อง "เก็บในเครื่อง" รวมทุกที่อยู่คั่นด้วย FILE_PATH_SEPARATOR
    # ถ้าไฟล์ใดบันทึกไม่สำเร็จจะไม่บันทึกรายการ เพื่อไม่ให้ไฟล์หายไปเงียบๆ
    purchase_documents: list[UploadedFile] = list(
        st.session_state.get(_field_key("purchase_uploader", form_counter)) or []
    )
    documents_to_attach: list[UploadedFile] = list(uploaded_po_documents or []) + purchase_documents
    attached_file_paths: list[str] = []
    for document_to_attach in documents_to_attach:
        saved_path = save_document_and_get_path(document_to_attach)
        if saved_path is None:
            return  # save_document_and_get_path แสดง error ให้แล้ว
        attached_file_paths.append(saved_path)
    already_saved_paths: Optional[str] = st.session_state.get(SESSION_KEY_LOCAL_PATH)
    if already_saved_paths:
        attached_file_paths.append(already_saved_paths)
    final_file_path: Optional[str] = FILE_PATH_SEPARATOR.join(attached_file_paths) or None

    # ไฟล์จากกล่อง Purchase ส่งขึ้น SharePoint ด้วย (ข้ามเมื่อยังไม่ตั้งค่า .env) ลิงก์ไฟล์แรกเก็บใน sharepoint_url
    sharepoint_link, sharepoint_warning = upload_attachments_to_sharepoint_if_ready(purchase_documents)
    final_sharepoint_url: str = sharepoint_url or sharepoint_link or ""

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
        sharepoint_url=final_sharepoint_url or None,  # ลิงก์ที่กรอกเอง (ไม่บังคับ) มาก่อน ไม่มีก็ใช้ลิงก์ที่ส่งขึ้นให้
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
        + (f"\n\n{sharepoint_warning}" if sharepoint_warning else "")
    )
    st.session_state[SESSION_KEY_FORM_COUNTER] = form_counter + 1
    st.session_state[SESSION_KEY_FORM_STEP] = FORM_STEP_QUESTIONS  # เปิดครั้งหน้าเริ่มที่ขั้นที่ 1 เสมอ
    st.rerun()


# ---------------------------------------------------------------------------
# จุดเข้าของหน้า
# ---------------------------------------------------------------------------


# width="medium" เพื่อให้ฟอร์มขั้นที่ 2 จัดเป็น 2 คอลัมน์ได้ (ถ้าแคบเกินไปเปลี่ยนเป็น "large")
@st.dialog(ADD_DATA_BUTTON_NAME, width="medium")
def render_entry_dialog(form_counter: int) -> None:
    """หน้าต่างป๊อปอัป "เพิ่มข้อมูล": ขั้นที่ 1 ถามข้อมูลเบื้องต้น ขั้นที่ 2 แท็บ [กรอก Form | Upload ข้อมูล]

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

    # แต่ละขั้นอยู่ในคอนเทนเนอร์คนละ key -> เปลี่ยนขั้นแล้วเนื้อหาถูกสร้างใหม่ และ CSS เล่นแอนิเมชันเฟดเข้า
    if current_step == FORM_STEP_QUESTIONS:
        with st.container(key="dialog_step_1"):
            render_questions_step(form_counter)
        return

    with st.container(key="dialog_step_2"):
        _render_dialog_step_body(form_counter)


def _build_step_header_html(step_number: int, description: str) -> str:
    """สร้าง HTML หัวขั้นตอน: แถบ progress 2 ช่อง + ข้อความ "ขั้นตอนที่ X / 2 — ..."

    Args:
        step_number: ขั้นปัจจุบัน (1 หรือ 2) ถ้าเพิ่มขั้นใหม่ ให้เพิ่มช่อง <span> และแก้ตัวเลข "/ 2"
        description: คำอธิบายสั้นๆ ต่อท้าย

    Returns:
        สตริง HTML สำหรับ st.markdown(unsafe_allow_html=True)
    """
    segments: str = "".join(
        f'<span class="{"on" if index <= step_number else ""}"></span>' for index in (1, 2)
    )
    return (
        f'<div class="step-progress">{segments}</div>'
        f'<p class="step-subtitle">ขั้นตอนที่ {step_number} / 2 — {description}</p>'
    )


def _render_dialog_step_body(form_counter: int) -> None:
    """วาดเนื้อหาขั้นที่ 2 ของหน้าต่าง: หัวขั้นตอน + หน้าตามโหมดที่เลือก (กรอก Form หรือ Upload ข้อมูล แยกกัน ไม่ปนแท็บ)

    Args:
        form_counter: ตัวนับของฟอร์มปัจจุบัน
    """
    st.markdown(
        _build_step_header_html(
            2,
            f"{st.session_state[SESSION_KEY_ENTRY_ITEM]} · {st.session_state[SESSION_KEY_ENTRY_HAS_INVOICE]}",
        ),
        unsafe_allow_html=True,
    )
    # โหมด "กรอก Form": แสดงเฉพาะฟอร์ม ไม่มีแท็บ Upload ข้อมูลปนอยู่
    if st.session_state.get(SESSION_KEY_ENTRY_MODE) != ENTRY_MODE_UPLOAD:
        st.session_state.pop(SESSION_KEY_LOCAL_PATH, None)  # ไม่ให้ไฟล์จากแท็บที่ไม่แสดงค้างมาผูกกับรายการ
        with st.container(key="entry_form_card"):
            render_entry_form(form_counter)
        return

    # โหมด "Upload ข้อมูล": กล่องอัปโหลด 2 กล่อง แล้วเมื่อมีไฟล์ แสดงการ์ดตรวจสอบ/แก้ข้อมูลก่อนบันทึก (ไม่มีแท็บ)
    # ต้องวาดกล่องอัปโหลดก่อนฟอร์ม เพราะมันเติมค่าลงช่องของฟอร์ม
    # (Streamlit ตั้งค่าช่องผ่าน session_state ได้เฉพาะก่อนช่องนั้นถูกสร้างในรอบนั้น)
    with st.container(key="upload_card"):
        has_uploaded_files: bool = render_upload_section(form_counter)
    if has_uploaded_files:
        with st.container(key="entry_form_card"):
            render_entry_form(form_counter, show_po_uploader=False, title="ตรวจสอบข้อมูลก่อนบันทึก")
    else:
        st.markdown(
            '<p class="upload-review-hint">อัปโหลดไฟล์ด้านบน แล้วระบบจะอ่านข้อมูลมาให้ตรวจสอบก่อนบันทึก</p>',
            unsafe_allow_html=True,
        )


def render_add_button(form_counter: int) -> None:
    """วาดแถบหัวเรื่องของตาราง: ชื่อส่วน (ซ้าย) + ไอคอน "+" ลอย (ขวา)

    ชี้เมาส์ที่ "+" แล้วไอคอนหมุนและเมนูกางออก 2 ตัวเลือก (กรอก Form / Upload ข้อมูล) ซึ่งเป็นแค่ CSS
    กดตัวเลือกแล้วเปิดหน้าต่างเพิ่มข้อมูล (ชื่อหน้าหลักและ Date Filter วาดโดย app.py แล้ว)

    Args:
        form_counter: ตัวนับของฟอร์มปัจจุบัน (ส่งต่อให้หน้าต่าง)
    """
    # key="table_header_row" ใช้ให้ CSS (PAGE_CSS_RULES ข้อ 1.2) จับแถวนี้ เพื่อชิดปุ่มขวาและลดช่องว่างใต้หัวข้อ
    # vertical_alignment="center" ทำให้ปุ่มอยู่กึ่งกลางแนวตั้งเสมอกับชื่อส่วน ไม่ต้องใช้เว้นบรรทัดช่วย
    # ความกว้างคอลัมน์ถูก CSS กำหนดใหม่ (หัวข้อกินที่ที่เหลือ ปุ่มกว้างตามขนาดปุ่ม) สัดส่วน [1, 1] จึงเป็นแค่ค่าเริ่มต้น
    with st.container(key="table_header_row"):
        title_column, button_column = st.columns([1, 1], vertical_alignment="center")
        title_column.subheader("ตารางข้อมูล Master-List")
        # ปุ่ม "+" ไม่ทำอะไรเมื่อกด (เป็นปุ่มจริงเพื่อให้แตะบนจอสัมผัสแล้วเมนูค้างเปิดผ่าน :focus-within)
        # ตัวเลือกอยู่ใน add_menu_options ซ่อนไว้จนกว่าจะชี้เมาส์ ลักษณะ/แอนิเมชันแก้ใน CSS ข้อ 1.2
        chosen_mode: Optional[str] = None
        with button_column.container(key="add_menu"):
            st.button("", icon=":material/add:", key="add_menu_trigger", help=None)
            with st.container(key="add_menu_options"):
                if st.button(ADD_OPTION_FORM_LABEL, icon=ADD_OPTION_FORM_ICON, key="add_option_form", type="tertiary"):
                    chosen_mode = ENTRY_MODE_FORM
                if st.button(
                    ADD_OPTION_UPLOAD_LABEL, icon=ADD_OPTION_UPLOAD_ICON, key="add_option_upload", type="tertiary"
                ):
                    chosen_mode = ENTRY_MODE_UPLOAD
        if chosen_mode is not None:
            # เปิดหน้าต่างทุกครั้งเริ่มที่ขั้นที่ 1 (รวมกรณีปิดด้วยปุ่ม x ระหว่างขั้นที่ 2)
            st.session_state[SESSION_KEY_ENTRY_MODE] = chosen_mode
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
