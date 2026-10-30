"""หน้า Overview: แจ้งเตือนใบกำกับภาษีค้าง + ตาราง Master-List เต็มความกว้าง + ปุ่มเปิดหน้าต่างเพิ่มข้อมูล

โครงหน้า (ตารางเป็นจุดสนใจหลัก ใช้พื้นที่กว้างที่สุด):
    หัวหน้า (ชื่อหน้า + Date Filter) อยู่ใน app.py (ตั้ง layout="wide" ที่ app.py แล้ว ครอบคลุมทุกหน้า)
    แจ้งเตือนใบกำกับภาษีค้าง + ดูรายการที่ค้าง (เต็มความกว้าง แสดงเสมอ นับจากวันที่ Upload ไม่ใช่คอลัมน์ Date)
                                          [ ➕ เพิ่มข้อมูล / อัปโหลดเอกสาร ]  <- กดแล้วเด้งหน้าต่าง (st.dialog)
    ┌────────────────────────────────────────────────────────────┐
    │ การ์ดตาราง (เต็มความกว้าง)                                  │
    │  Search bar   |   Item ▾   |   Vendor ▾                     │
    │  ตาราง Master-List                                          │
    └────────────────────────────────────────────────────────────┘
    ▸ Quantity of equipment (กางออกดูได้)

    หน้าต่าง "เพิ่มข้อมูล / อัปโหลดเอกสาร" มีแท็บ [กรอก Form | Upload File] (ย้ายมาจากแผงด้านขวาเดิม ไม่เปลี่ยน Logic)

ไฟล์เอกสารถูกบันทึกลงโฟลเดอร์ static/local_uploads/ (utils/local_storage.py) แล้วเก็บที่อยู่ไฟล์ลงฐานข้อมูล
ส่วนเชื่อม SharePoint ปิดไว้ก่อน เตรียมไว้สำหรับเชื่อมต่อในอนาคต (utils/sharepoint_api.py, ค้นหา "SharePoint ปิดไว้")
ส่วนที่ยังไม่ได้ทำ: OCR สำหรับรูปภาพ
"""

import html
import json
import os
import re
import sys
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from st_aggrid import JsCode
from streamlit.runtime.uploaded_file_manager import UploadedFile

from config.constants import CATEGORY_OPTIONS
from config.logging_setup import get_logger
from data.database import (
    STATUS_PENDING,
    STATUS_RECEIVED,
    add_transaction,
    delete_transactions,
    get_transactions,
    get_unique_vendors,
    update_transaction,
)
from ui_common import build_css, build_equipment_cards_html, get_equipment_quantities
from ui_grid import (
    ROW_FX_COLUMN,
    ROW_FX_DELETE_MS,
    ROW_FX_DELETING,
    ROW_FX_HIGHLIGHT_MS,
    ROW_FX_NEW,
    ROW_FX_UPDATED,
    build_grid_options,
    show_grid,
)
from utils.excel_export import build_excel_bytes
from utils.local_storage import (
    DESKTOP_EXPORT_ENABLED,
    STATIC_URL_PREFIX,
    LocalStorageError,
    build_local_file_url,
    find_file_location,
)
from utils.storage_backend import UNKNOWN_VENDOR_FOLDER
from utils.submit_pipeline import RecordFields, SubmitResult, submit_record
from utils.text_extractor import ExtractedFields, extract_fields_from_file

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
    "description": "Description",  # อยู่หน้า Item
    "category": "Item",
    "total_price": "Price",
    "invoice_status": "Status",
    # --- ข้อมูลจากเอกสาร PR / Quotation (Master-List) แสดงหลังคอลัมน์หลัก เลื่อนตารางไปทางขวาเพื่อดู ---
    "vendor": "Vendor",  # อยู่ติดกับ Tel.
    "tel": "Tel.",
    "tax_id": "Tax ID",
    "pr_run_no": "PR No.",
    "pr_request_date": "PR Date",
    "qt_no": "QT No.",
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
    "description": "ชื่อไฟล์ PR ที่อัปโหลด (ตัดวันที่ / PR_Addin_ซื้อ / -signed ออกแล้ว) แก้ไขได้",
    "unit_price": "ราคาสุทธิที่รวม Discount แล้ว (บาท)",
    "sharepoint_url": "ไฟล์ที่อัปโหลด: กดไอคอนเพื่อเปิดโฟลเดอร์ปี/เดือน/วัน/ชื่อไฟล์ PR บน SharePoint (ถ้ายังไม่มีลิงก์ออนไลน์ = เปิดไฟล์ที่เก็บไว้ในระบบ)",
}

# ความกว้างที่ต้องการของแต่ละคอลัมน์ (พิกเซล) ตารางจะปรับคอลัมน์ให้พอดีหน้าจอเอง (fit to window) ไม่มีแถบเลื่อนแนวนอน
# - ค่าตัวเลข = ความกว้างที่ต้องการ (px) ตารางย่อ/ขยายตามสัดส่วนให้พอดีจอ (ดู ui_grid.GRID_MIN_WIDTH_RATIO_*)
# - None = คอลัมน์ข้อความยาว (ตอนนี้คือ Description) กว้างที่สุด ย่อได้มากสุดเมื่อจอแคบ
# - ถ้าเพิ่มคอลัมน์ใหม่ ให้เพิ่มความกว้างขั้นต่ำที่นี่ด้วย (ผลรวมมากเกินจอ ตารางจะมีแถบเลื่อนแนวนอน)
TABLE_COLUMN_WIDTHS: dict[str, "int | str | None"] = {
    "date": 140,
    "vendor": 160,
    "category": 125,
    "total_price": 150,
    "invoice_status": 140,
    "tel": 155,
    "tax_id": 130,
    "pr_run_no": 110,
    "pr_request_date": 105,
    "qt_no": 74,
    "description": None,
    "unit_price": 112,
    "sharepoint_url": 68,
}
# คอลัมน์ข้อความที่ย่อได้มากเมื่อจอแคบ (ข้อความยาวถูกตัดด้วย ... ชี้เมาส์ดูเต็มได้) ส่วนคอลัมน์อื่นพยายามไม่ย่อ
# (Vendor ชื่อยาวที่สุด จึงให้เป็นตัวย่อหลัก Item / Tel. ไม่ย่อ จะได้อ่านครบ)
SHRINKABLE_TABLE_COLUMNS: tuple[str, ...] = ("vendor", "pr_run_no")

# คอลัมน์ที่ "ซ่อนจากตาราง" แต่ยังอยู่ในข้อมูล (DB / ไฟล์ Export CSV-Excel ยังมีครบ)
# เตรียมไว้สำหรับส่งเข้า Master-List ภายหลัง: อยากแสดงกลับ แค่ลบชื่อคอลัมน์ออกจากรายการนี้
HIDDEN_TABLE_COLUMNS: tuple[str, ...] = (
    "tax_id",
    "pr_run_no",
    "pr_request_date",
    "qt_no",
    "unit_price",
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
# คอลัมน์ id รายการในฐานข้อมูล (ซ่อนในตาราง) ใช้เป็น id แถวของ AgGrid: ข้อมูลเปลี่ยนแล้วตารางเพิ่ม/ลบ/แก้เฉพาะแถวนั้น ไม่วาดใหม่ทั้งตาราง
# และใช้จับคู่แถวที่ผู้ใช้แก้/เลือก/กด กลับหารายการในฐานข้อมูล (ลำดับแถวเปลี่ยนได้ตามการเรียง/กรอง แต่ id ไม่เปลี่ยน)
ROW_ID_COLUMN: str = "_id"

# ตัวแสดงไอคอนลิงก์ไฟล์ในเซลล์ (JavaScript ของ AgGrid) สร้างเป็น element ทีละชิ้น ไม่ต่อสตริง HTML เพื่อกัน XSS
# รับเฉพาะลิงก์ http/https เท่านั้น (ตรวจซ้ำอีกชั้นหลัง _valid_link_or_none ฝั่ง Python); FILE_ICON ถูกแทนด้วย FILE_LINK_ICON
FILE_LINK_RENDERER_JS: str = r"""
class FileLinkRenderer {
    init(params) {
        this.eGui = document.createElement('span');
        if (params.value && /^(https?:\/\/|FILE_STATIC_PREFIX)/i.test(params.value)) {
            // ไฟล์ในเครื่อง (ค่าขึ้นต้น FILE_STATIC_PREFIX) = ปุ่มที่ไม่เปิดลิงก์ ตารางส่ง cellClicked ให้ฝั่ง Python
            // โหมด Desktop (เปิดเฉพาะตอนรันบนเครื่องตัวเอง) เปิดโฟลเดอร์ที่เก็บไฟล์ใน Explorer (โฟลเดอร์สร้างไว้ตอน Upload แล้ว)
            // นอกนั้น (เช่นบน Server) ไฟล์ในเครื่องเปิดเป็นลิงก์ในแท็บใหม่เหมือนลิงก์ออนไลน์ (http/https)
            const isLocalFile = FILE_DESKTOP_MODE && !/^https?:/i.test(params.value);
            const link = document.createElement(isLocalFile ? 'span' : 'a');
            if (isLocalFile) {
                link.setAttribute('role', 'button');
                link.title = 'เปิดโฟลเดอร์ที่เก็บไฟล์';
            } else {
                link.href = params.value;
                link.target = '_blank';
                link.rel = 'noopener noreferrer';
            }
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
        this.eGui = document.createElement('span');
        this.badge = null;
        this.key = '';
        this.apply(params, true);
    }
    // วาดหรืออัปเดตป้าย: ถ้ามีป้ายเดิมอยู่แล้ว (refresh) หรือรู้สีเดิมของแถวนี้ (ตัวแก้ไขปิดแล้ว AgGrid สร้างป้ายใหม่)
    // สีจะไล่จากสีเดิมไปสีใหม่แทนการสลับทันที ค่าเท่าเดิมไม่แตะ DOM เลย (กันกะพริบตอนเซิร์ฟเวอร์ส่งค่าเดิมกลับมา)
    apply(params, isInit) {
        const colors = STATUS_COLORS;
        const raw = String(params.value || '');
        const key = raw.indexOf('Completed') >= 0 ? 'completed' : raw.indexOf('Overdue') >= 0 ? 'overdue' : raw.indexOf('Pending') >= 0 ? 'pending' : '';
        const store = (window.__statusBadgePrev = window.__statusBadgePrev || {});
        const rowId = params.node && params.node.id != null ? String(params.node.id) : null;
        const previous = isInit ? (rowId !== null ? store[rowId] : undefined) : this.key;
        if (rowId !== null) store[rowId] = key;
        if (!isInit && key === this.key) return;
        this.key = key;
        if (!key) { this.eGui.textContent = raw; this.badge = null; return; }
        if (!this.badge) {
            this.badge = document.createElement('span');
            this.badge.style.cssText = 'cursor:pointer;display:inline-block;padding:2px 12px;border-radius:999px;font-weight:600;font-size:15px;line-height:26px;';
            this.eGui.textContent = '';
            this.eGui.appendChild(this.badge);
        }
        const badge = this.badge;
        badge.textContent = '● ' + key.charAt(0).toUpperCase() + key.slice(1) + '  ▾';  // ▾ บอกว่ากดเลือกสถานะได้
        badge.style.background = colors[key][0];
        badge.style.color = colors[key][1];
        const reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
        if (previous && previous !== key && colors[previous] && badge.animate && !reduce) {
            badge.animate(
                [{backgroundColor: colors[previous][0], color: colors[previous][1]}, {backgroundColor: colors[key][0], color: colors[key][1]}],
                {duration: 280, easing: 'ease-out'}
            );
        }
    }
    refresh(params) { this.apply(params, false); return true; }
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
        // เลือกแล้วปิดทันที ห้ามหน่วง/จางหาย: ระหว่างนั้นเซลล์ใต้ popup ยังแสดงสถานะเดิม ผู้ใช้จะเห็นเหมือนเด้งกลับค่าเก่าก่อนขึ้นค่าใหม่
        const choose = (label) => {
            this.value = label;
            params.stopEditing();
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

# ระบบอ่านข้อมูลอัตโนมัติเฉพาะไฟล์ PR: ชื่อไฟล์ขึ้นต้นด้วย PR (ไม่สนตัวพิมพ์เล็ก/ใหญ่) และนามสกุลต้องเป็นตัวพิมพ์เล็กตามนี้
# ไฟล์อื่น (PO, ใบกำกับภาษี ฯลฯ) ยังแนบและเก็บตามปกติ แต่ไม่ถูกอ่านข้อมูล
PR_FILE_NAME_PREFIX: str = "pr"
AUTO_EXTRACT_EXTENSIONS: tuple[str, ...] = (".pdf", ".xlsx")

# ตัดส่วนที่ไม่ต้องการออกจากชื่อไฟล์ก่อนแสดงในคอลัมน์ Description (ไม่สนตัวพิมพ์เล็ก/ใหญ่)
# ตัวอย่าง "20260319 PR_Addin_ซื้อ NB Lenovo-signed.pdf" -> "NB Lenovo"  (แก้รูปแบบที่ตัดได้ที่นี่)
FILE_NAME_DATE_PREFIX_PATTERN: str = r"^\s*(?:\d{8}|\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4})[\s_\-]*"  # วันที่นำหน้า เช่น 20260319
FILE_NAME_PR_PREFIX_PATTERN: str = r"^\s*PR(?:[\s_\-]*Addin)?[\s_\-]*(?:ซื้อ)?[\s_\-]*"  # PR_Addin_ซื้อ / PR_ซื้อ / PR
FILE_NAME_SUFFIX_PATTERN: str = r"[\s_\-]*signed\s*$"  # -signed ท้ายชื่อ
UPLOAD_STAMP_FILE_NAME_PATTERN: str = (
    r"^\d{8}_\d{6}_\d+_"  # เลขเวลาอัปโหลดที่ระบบเติม เช่น 20261028_134912_664797_ (ไม่ใช่วันที่ PR)
)

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
SESSION_KEY_EDITOR_VERSION: str = (
    "overview_editor_version"  # เลขเวอร์ชันของตาราง เพิ่มเฉพาะเมื่อต้องวาดตารางใหม่จริง ๆ (ล้างสถานะค้างในตาราง)
)
SESSION_KEY_ROW_EFFECTS: str = "overview_row_effects"  # animation แถวที่ยังไม่หมดเวลา {id รายการ: (ชนิด, เวลาหมดอายุ)}
SESSION_KEY_MAX_SEEN_ID: str = "overview_max_seen_id"  # id รายการสูงสุดที่ตารางเคยเห็น: id ที่สูงกว่านี้ = เพิ่งเพิ่ม
SESSION_KEY_DELETING_IDS: str = "overview_deleting_ids"  # id ที่กดลบแล้ว รอเล่น animation ก่อนลบจริง (รอบถัดไป)
SESSION_KEY_LAST_SELECTED_IDS: str = "overview_last_selected_ids"  # id ที่ติ๊กเลือกไว้ในรอบล่าสุด (ปุ่มลบอ่านจากตรงนี้)
SESSION_KEY_LAST_EDIT_SIGNATURE: str = (
    "overview_last_edit_signature"  # ลายนิ้วมือของการแก้ไขที่บันทึกไปแล้ว กันบันทึกซ้ำจากค่าเก่าที่ตารางส่งค้าง
)
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
/* แถบสถานะปกติ (ไม่มีรายการค้าง) โทนเขียวอ่อน ไม่มี animation ชีพจร */
.overdue-alert.overdue-alert-ok {
    border-left-color: #16A34A; background: linear-gradient(100deg, #F0FDF4 0%, #ECFDF5 100%);
    box-shadow: 0 1px 2px rgba(22, 163, 74, 0.10), 0 12px 28px -10px rgba(22, 163, 74, 0.25);
}
.overdue-alert-ok .overdue-alert-icon { animation: none; }
.overdue-alert-ok .overdue-alert-title { color: #166534; }
.overdue-alert-ok .overdue-alert-sub { color: #15803D; }
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
.st-key-overdue_alert [data-testid="stExpander"] {
    border: 1px solid #FECACA; border-radius: 16px; background: #FFFFFF; overflow: hidden;
    box-shadow: 0 10px 28px -14px rgba(220, 38, 38, 0.35);
}
.st-key-overdue_alert [data-testid="stExpander"] details { border: none; }
.st-key-overdue_alert [data-testid="stExpander"] summary {
    padding: 16px 20px; border-left: 5px solid #DC2626;
    background: linear-gradient(90deg, #FFF1F2 0%, #FFFFFF 70%); transition: background-color 0.2s ease;
}
.st-key-overdue_alert [data-testid="stExpander"] summary:hover { background: linear-gradient(90deg, #FFE4E6 0%, #FFF1F2 80%); }
.st-key-overdue_alert [data-testid="stExpander"] summary p { font-size: 1.3rem !important; font-weight: 800 !important; color: #991B1B; letter-spacing: 0.01em; }
.st-key-overdue_alert [data-testid="stExpander"] summary svg,
.st-key-overdue_alert [data-testid="stExpander"] summary [data-testid="stIconMaterial"] {
    font-size: 1.6rem !important; width: 1.6rem; height: 1.6rem; color: #B91C1C; transition: transform 0.3s cubic-bezier(.2,.8,.2,1);
}
.st-key-overdue_alert [data-testid="stExpander"] details::details-content {
    height: 0; overflow: clip; opacity: 0;
    transition: height 0.38s cubic-bezier(.2,.8,.2,1), opacity 0.3s ease, content-visibility 0.38s allow-discrete;
}
.st-key-overdue_alert [data-testid="stExpander"] details[open]::details-content { height: auto; opacity: 1; }
.st-key-overdue_alert [data-testid="stExpander"] details[open] > summary ~ * { animation: overdue-expand-in 0.3s cubic-bezier(.2,.8,.2,1) both; }
@keyframes overdue-expand-in { from { opacity: 0; transform: translateY(-8px); } to { opacity: 1; transform: none; } }
/* ตารางรายการที่ค้าง (modern): หัวคอลัมน์ติดบน, แถวใหญ่อ่านง่าย, ป้ายวันสีตามความวิกฤต, แถวไหลเข้าทีละแถว (--i สูงสุด 12)
   แถวเยอะเลื่อนในกล่อง (od-scroll) ปรับความสูงที่ max-height */
.st-key-overdue_alert .od-table { padding: 4px 12px 14px; }
.st-key-overdue_alert .od-scroll { max-height: 60vh; overflow: auto; }
.st-key-overdue_alert .od-head, .st-key-overdue_alert .od-row {
    display: grid; grid-template-columns: 70px 130px minmax(140px, 1.4fr) minmax(130px, 1fr) minmax(130px, 0.8fr) 150px;
    align-items: center; column-gap: 20px; min-width: 760px;
}
.st-key-overdue_alert .od-head {
    position: sticky; top: 0; z-index: 1; background: #FFFFFF; padding: 10px 12px;
    font-size: 0.95rem; font-weight: 700; letter-spacing: 0.04em; color: #64748B; border-bottom: 2px solid #E2E8F0;
}
.st-key-overdue_alert .od-head span:nth-child(5), .st-key-overdue_alert .od-price { text-align: right; }
.st-key-overdue_alert .od-head span:nth-child(6), .st-key-overdue_alert .od-days { text-align: right; }
.st-key-overdue_alert .od-row {
    min-height: 64px; padding: 0 12px; border-bottom: 1px solid #EEF2F6; border-left: 4px solid transparent; border-radius: 10px;
    font-size: 1.2rem; color: #1E293B; font-variant-numeric: tabular-nums;
    transition: background-color 0.18s ease; animation: od-row-in 0.4s cubic-bezier(.2,.8,.2,1) both; animation-delay: calc(var(--i, 0) * 60ms);
}
.st-key-overdue_alert .od-row:hover { background: #FFF7ED; }
.st-key-overdue_alert .od-row-critical { border-left-color: #DC2626; }
.st-key-overdue_alert .od-id { color: #64748B; font-weight: 600; }
.st-key-overdue_alert .od-vendor { font-weight: 700; color: #0F172A; }
.st-key-overdue_alert .od-vendor, .st-key-overdue_alert .od-po { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.st-key-overdue_alert .od-price { font-size: 1.3rem; font-weight: 700; color: #0F172A; }
.st-key-overdue_alert .od-badge {
    display: inline-block; padding: 4px 14px; border-radius: 999px; font-size: 1.1rem; font-weight: 800; white-space: nowrap;
    animation: od-badge-pop 0.45s cubic-bezier(.2,.8,.2,1) both; animation-delay: calc(var(--i, 0) * 60ms + 120ms);
}
.st-key-overdue_alert .od-badge-critical { background: linear-gradient(135deg, #FEE2E2, #FECACA); color: #B91C1C; }
.st-key-overdue_alert .od-badge-warn { background: linear-gradient(135deg, #FFEDD5, #FED7AA); color: #C2410C; }
@keyframes od-row-in { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }
@keyframes od-badge-pop { from { opacity: 0; transform: scale(0.7); } to { opacity: 1; transform: none; } }
@media (max-width: 640px) {
    /* จอแคบ: ซ่อนหัวตาราง แต่ละแถวเป็นการ์ด 2 บรรทัด (ผู้ขาย | ราคา / วันที่ | ป้ายวัน) ไม่ต้องเลื่อนแนวนอน */
    .st-key-overdue_alert .od-head, .st-key-overdue_alert .od-id, .st-key-overdue_alert .od-po { display: none; }
    .st-key-overdue_alert .od-scroll { overflow-x: hidden; }
    .st-key-overdue_alert .od-row {
        grid-template-columns: 1fr auto; grid-template-areas: "vendor price" "date days"; min-width: 0; min-height: 0;
        column-gap: 12px; row-gap: 4px; padding: 12px; font-size: 1.05rem;
    }
    .st-key-overdue_alert .od-vendor { grid-area: vendor; }
    .st-key-overdue_alert .od-price { grid-area: price; font-size: 1.15rem; }
    .st-key-overdue_alert .od-date { grid-area: date; color: #64748B; }
    .st-key-overdue_alert .od-days { grid-area: days; }
    .st-key-overdue_alert .od-badge { font-size: 0.95rem; padding: 3px 10px; }
}
@media (prefers-reduced-motion: reduce) {
    .overdue-alert, .overdue-alert-icon, .st-key-overdue_alert .od-row, .st-key-overdue_alert .od-badge,
    .st-key-overdue_alert [data-testid="stExpander"] details[open] > summary ~ * { animation: none; }
    .st-key-overdue_alert [data-testid="stExpander"] details::details-content,
    .st-key-overdue_alert [data-testid="stExpander"] summary,
    .st-key-overdue_alert [data-testid="stExpander"] summary svg { transition: none; }
}

/* ตาราง Quantity of equipment (modern): หัวแถบไล่เฉด+ขอบซ้ายสีเน้น, แถวใหญ่อ่านง่าย, แถบสัดส่วนขยายจาก 0, แถวไหลเข้าทีละแถว
   เปิด/ปิดใช้ ::details-content แบบเดียวกับแถบ overdue (ใช้ transform/opacity เป็นหลัก) */
.st-key-equipment_summary [data-testid="stExpander"] {
    border: 1px solid #E2E8F0; border-radius: 16px; background: #FFFFFF; overflow: hidden;
    box-shadow: 0 10px 28px -14px rgba(15, 23, 42, 0.25);
}
.st-key-equipment_summary [data-testid="stExpander"] details { interpolate-size: allow-keywords; border: none; }
.st-key-equipment_summary [data-testid="stExpander"] summary {
    padding: 16px 20px; border-left: 5px solid #F59E0B;
    background: linear-gradient(90deg, #FFF7ED 0%, #FFFFFF 70%); transition: background-color 0.2s ease, padding 0.2s ease;
}
.st-key-equipment_summary [data-testid="stExpander"] summary:hover { background: linear-gradient(90deg, #FFEDD5 0%, #FFF7ED 80%); }
.st-key-equipment_summary [data-testid="stExpander"] summary p { font-size: 1.3rem !important; font-weight: 800 !important; color: #0F172A; letter-spacing: 0.01em; }
.st-key-equipment_summary [data-testid="stExpander"] summary svg,
.st-key-equipment_summary [data-testid="stExpander"] summary [data-testid="stIconMaterial"] {
    font-size: 1.6rem !important; width: 1.6rem; height: 1.6rem; color: #B45309; transition: transform 0.3s cubic-bezier(.2,.8,.2,1);
}
.st-key-equipment_summary [data-testid="stExpander"] details::details-content {
    height: 0; overflow: clip; opacity: 0;
    transition: height 0.38s cubic-bezier(.2,.8,.2,1), opacity 0.3s ease, content-visibility 0.38s allow-discrete;
}
.st-key-equipment_summary [data-testid="stExpander"] details[open]::details-content { height: auto; opacity: 1; }
.st-key-equipment_summary .eq-table { padding: 8px 20px 16px; }
.st-key-equipment_summary .eq-head, .st-key-equipment_summary .eq-row {
    display: grid; grid-template-columns: minmax(150px, 1.1fr) 2fr minmax(70px, 0.5fr); align-items: center; column-gap: 24px;
}
.st-key-equipment_summary .eq-head {
    padding: 8px 12px; font-size: 0.95rem; font-weight: 700; letter-spacing: 0.08em; text-transform: uppercase; color: #64748B;
    border-bottom: 2px solid #E2E8F0;
}
.st-key-equipment_summary .eq-head span:last-child, .st-key-equipment_summary .eq-qty { text-align: right; }
.st-key-equipment_summary .eq-row {
    min-height: 68px; padding: 0 12px; border-bottom: 1px solid #EEF2F6; border-radius: 10px;
    transition: background-color 0.18s ease, transform 0.18s ease; animation: eq-row-in 0.45s cubic-bezier(.2,.8,.2,1) both;
    animation-delay: calc(var(--i, 0) * 70ms);
}
.st-key-equipment_summary .eq-row:hover { background: #F8FAFC; transform: translateX(3px); }
.st-key-equipment_summary .eq-name { display: flex; align-items: center; gap: 14px; font-size: 1.3rem; font-weight: 600; color: #1E293B; }
.st-key-equipment_summary .eq-qty { font-size: 1.85rem; font-weight: 800; color: #0F172A; font-variant-numeric: tabular-nums; }
.st-key-equipment_summary .eq-dot { width: 14px; height: 14px; border-radius: 50%; flex: 0 0 auto; }
.st-key-equipment_summary .eq-dot-0 { background: linear-gradient(135deg, #3B82F6, #1D4ED8); }
.st-key-equipment_summary .eq-dot-1 { background: linear-gradient(135deg, #8B5CF6, #6D28D9); }
.st-key-equipment_summary .eq-dot-2 { background: linear-gradient(135deg, #10B981, #047857); }
.st-key-equipment_summary .eq-dot-3 { background: linear-gradient(135deg, #F59E0B, #D97706); }
.st-key-equipment_summary .eq-bar { display: block; height: 12px; border-radius: 999px; background: #F1F5F9; overflow: hidden; }
.st-key-equipment_summary .eq-fill {
    display: block; height: 100%; border-radius: 999px; transform-origin: left center;
    animation: eq-bar-grow 0.7s cubic-bezier(.2,.8,.2,1) both; animation-delay: calc(var(--i, 0) * 70ms + 150ms);
}
.st-key-equipment_summary .eq-total { border-bottom: none; background: #F8FAFC; margin-top: 6px; }
.st-key-equipment_summary .eq-total .eq-name { font-weight: 800; color: #0F172A; }
.st-key-equipment_summary .eq-total .eq-qty { color: #B45309; }
@keyframes eq-row-in { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }
@keyframes eq-bar-grow { from { transform: scaleX(0); } to { transform: scaleX(1); } }
@media (max-width: 640px) {
    .st-key-equipment_summary .eq-head, .st-key-equipment_summary .eq-row { grid-template-columns: 1fr auto; }
    .st-key-equipment_summary .eq-head span:nth-child(2), .st-key-equipment_summary .eq-bar, .st-key-equipment_summary .eq-total > span:nth-child(2) { display: none; }
}
@media (prefers-reduced-motion: reduce) {
    .st-key-equipment_summary .eq-row, .st-key-equipment_summary .eq-fill { animation: none; }
    .st-key-equipment_summary [data-testid="stExpander"] details::details-content,
    .st-key-equipment_summary [data-testid="stExpander"] summary,
    .st-key-equipment_summary [data-testid="stExpander"] summary svg { transition: none; }
}

/* 1.1) ลดระยะขอบรอบตาราง เพื่อให้ตารางกว้างขึ้น (ตารางวาดด้วย canvas ปรับขนาดตัวอักษรด้วย CSS ไม่ได้ จึงเอาพื้นที่จากขอบแทน)
      ขอบของหน้าหลัก 48px -> 16px, การ์ดตาราง 32px -> 12px, กล่องขาวด้านใน 20px -> 8px (รวมได้ตารางกว้างขึ้น ~128px) */
/* ใช้ min() กับตัวแปร responsive: จอใหญ่ขอบไม่เกิน 2rem (ตารางกว้างเต็มที่) จอเล็กใช้ค่าที่ config/styles.py กำหนด (0.75rem) */
:root { --app-page-padding-x: min(var(--app-main-padding-x), 2rem); }  /* ให้กฎชดเชยแถบเมนูพับใน config/styles.py ข้อ 13.1 ใช้ค่าเดียวกับหน้านี้ */
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
/* 1.2.1) ปุ่ม "+" ลอย (ไม่มีพื้นหลัง/กรอบ) + เมนูตัวเลือกที่กางลงด้านล่างเมื่อชี้เมาส์หรือโฟกัส (แตะบนจอสัมผัส)
          ไอคอนหมุน 135° (กลายเป็น x) ตัวเลือกเลื่อน+เฟดเข้า ตัวที่ 2 หน่วงเล็กน้อย
          ปรับขนาดไอคอนที่ font-size 40px, องศาหมุนที่ rotate(), ความเร็วที่ 0.35s / 0.25s */
.st-key-add_menu { position: relative; width: 60px; height: 60px; gap: 0 !important; }
.st-key-add_menu [data-testid="stButton"] button {
    width: 60px !important; min-width: 60px !important; height: 60px !important; padding: 0 !important;
    background: transparent !important; border: none !important; box-shadow: none !important; border-radius: 50% !important;
}
.st-key-add_menu_trigger button [data-testid="stIconMaterial"] {
    font-size: 52px !important; color: var(--ui-accent) !important; transition: transform 0.35s ease;
}
.st-key-add_menu:hover .st-key-add_menu_trigger button [data-testid="stIconMaterial"],
.st-key-add_menu:focus-within .st-key-add_menu_trigger button [data-testid="stIconMaterial"] { transform: rotate(135deg); }
/* กล่องเมนู: กางลงใต้ปุ่ม "+" ชิดขวา เป็นการ์ดขาวจาง ๆ; padding บน 8px เป็นสะพานให้เมาส์เลื่อนจากไอคอนลงมาได้โดยเมนูไม่หาย */
.st-key-add_menu_options {
    position: absolute; right: 0; top: 100%; z-index: 50; height: auto; display: flex !important; flex-direction: column !important;
    align-items: stretch; gap: 2px !important; padding: 8px 6px 6px; width: max-content;
    background: rgba(255, 255, 255, 0.96); border-radius: 12px; box-shadow: 0 6px 18px rgba(15, 23, 42, 0.08);
    visibility: hidden; opacity: 0; pointer-events: none;
    transition: opacity 0.25s ease, visibility 0s linear 0.25s;
}
.st-key-add_menu:hover .st-key-add_menu_options,
.st-key-add_menu:focus-within .st-key-add_menu_options {
    visibility: visible; opacity: 1; pointer-events: auto; transition: opacity 0.25s ease, visibility 0s;
}
.st-key-add_menu_options { width: max-content !important; min-width: max-content !important; max-width: none !important; }
.st-key-add_menu_options > [data-testid="stElementContainer"] {
    flex: 0 0 auto !important; width: 100% !important; min-width: max-content !important; transform: translateY(-8px); transition: transform 0.3s ease;
}
.st-key-add_menu_options [data-testid="stButton"] { width: 100% !important; min-width: max-content !important; }
.st-key-add_menu_options [data-testid="stElementContainer"]:nth-child(2) { transition-delay: 0.06s; }
.st-key-add_menu:hover .st-key-add_menu_options [data-testid="stElementContainer"],
.st-key-add_menu:focus-within .st-key-add_menu_options [data-testid="stElementContainer"] { transform: translateY(0); }
.st-key-add_menu_options [data-testid="stButton"] button {
    width: 100% !important; min-width: 0 !important; height: 48px !important; padding: 0 18px !important;
    border-radius: 10px !important; white-space: nowrap; justify-content: flex-start !important; text-align: left;
}
.st-key-add_menu_options [data-testid="stButton"] button > div { justify-content: flex-start !important; width: 100%; }
.st-key-add_menu_options [data-testid="stButton"] button p { font-size: 19px !important; font-weight: 600; color: #1E293B !important; }
.st-key-add_menu_options [data-testid="stButton"] button [data-testid="stIconMaterial"] { font-size: 28px !important; color: var(--ui-accent) !important; }
.st-key-add_menu_options [data-testid="stButton"] button { background: transparent !important; }
.st-key-add_menu_options [data-testid="stButton"] button:hover,
.st-key-add_menu_options [data-testid="stButton"] button:focus,
.st-key-add_menu_options [data-testid="stButton"] button:active { background: rgba(37, 99, 235, 0.04) !important; box-shadow: none !important; }
/* จอ >= 768px: ตัวเลือกออกทางซ้ายของปุ่ม "+" (บนเสมอกับปุ่ม) แทนการกางลงล่าง; padding ขวา 8px เป็นสะพานให้เมาส์ไม่หลุด
   ตัวเลือกเลื่อนเข้าจากขวา (translateX) แทนจากบน; จอแคบกว่านี้คงแบบกางลงล่าง */
@media (min-width: 768px) {
    .st-key-add_menu_options { top: 0; right: 100%; padding: 6px 8px 6px 6px; }
    .st-key-add_menu_options > [data-testid="stElementContainer"] { transform: translateX(8px); }
    .st-key-add_menu:hover .st-key-add_menu_options [data-testid="stElementContainer"],
    .st-key-add_menu:focus-within .st-key-add_menu_options [data-testid="stElementContainer"] { transform: translateX(0); }
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

/* 1.6) การ์ดตารางหลัก: แถบกรอง / KPI / ปุ่ม ตัวใหญ่ สไตล์ modern + animation เฉพาะ 8 จุด
        (ช่องค้นหา, Item, Vendor, Total Price, จำนวนรายการ, ปุ่มลบ, Export CSV, Export Excel)
        ใช้ transform / opacity / box-shadow เท่านั้น; จอที่ตั้งค่าลดการเคลื่อนไหวจะปิดทั้งหมดท้ายหัวข้อนี้ */
/* แถบกรอง: ช่องสูงเท่ากัน 52px มุม 12px ตัวอักษร 18px */
.st-key-table_filters [data-testid="stTextInputRootElement"],
.st-key-table_filters [data-testid="stSelectbox"] [role="group"] {
    min-height: 52px; border-radius: 12px; border-color: #E2E8F0; background: #FFFFFF;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
    transition: transform 0.2s ease, box-shadow 0.2s ease, border-color 0.2s ease;
}
.st-key-table_filters input, .st-key-table_filters [data-baseweb="select"] { font-size: 18px !important; }
.st-key-table_filters input::placeholder { color: #94A3B8; }
.st-key-table_filters [data-testid="stTextInputRootElement"]:hover,
.st-key-table_filters [data-testid="stSelectbox"] [role="group"]:hover {
    transform: translateY(-1px); border-color: #93C5FD; box-shadow: 0 6px 14px -6px rgba(37, 99, 235, 0.35);
}
.st-key-table_filters [data-testid="stTextInputRootElement"]:focus-within,
.st-key-table_filters [data-testid="stSelectbox"] [role="group"]:focus-within {
    transform: translateY(-1px); border-color: #2563EB; box-shadow: 0 0 0 4px rgba(37, 99, 235, 0.16);
}
.st-key-table_filters [data-testid="stColumn"] { animation: tbl-rise 0.45s cubic-bezier(.2,.8,.2,1) backwards; }
.st-key-table_filters [data-testid="stColumn"]:nth-child(2) { animation-delay: 0.06s; }
.st-key-table_filters [data-testid="stColumn"]:nth-child(3) { animation-delay: 0.12s; }

/* KPI: การ์ดมุม 16px มีแท่งสีซ้าย ป้ายเล็ก ตัวเลขใหญ่หนา */
.st-key-table_kpis [data-testid="stMetric"] {
    position: relative; overflow: hidden; padding: 18px 24px 18px 28px; border: 1px solid #E2E8F0; border-radius: 16px;
    background: linear-gradient(180deg, #FFFFFF 0%, #F8FAFC 100%);
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.05), 0 8px 20px -10px rgba(15, 23, 42, 0.18);
    animation: tbl-rise 0.5s 0.1s cubic-bezier(.2,.8,.2,1) backwards;
    transition: transform 0.22s ease, box-shadow 0.22s ease;
}
.st-key-table_kpis [data-testid="stColumn"]:nth-child(2) [data-testid="stMetric"] { animation-delay: 0.18s; }
.st-key-table_kpis [data-testid="stMetric"]::before {
    content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: 6px;
    background: linear-gradient(180deg, #2563EB, #38BDF8); transform-origin: top;
    animation: tbl-bar-grow 0.6s 0.25s cubic-bezier(.2,.8,.2,1) backwards;
}
.st-key-table_kpis [data-testid="stColumn"]:nth-child(2) [data-testid="stMetric"]::before { background: linear-gradient(180deg, #0D9488, #2DD4BF); }
.st-key-table_kpis [data-testid="stMetric"]:hover {
    transform: translateY(-3px); box-shadow: 0 2px 4px rgba(15, 23, 42, 0.06), 0 16px 28px -12px rgba(37, 99, 235, 0.35);
}
.st-key-table_kpis [data-testid="stMetricLabel"] p { font-size: 1.05rem !important; font-weight: 700 !important; color: #475569; letter-spacing: 0.01em; }
.st-key-table_kpis [data-testid="stMetricValue"] { font-size: calc(var(--app-metric-value) * 1.15) !important; font-weight: 800 !important; line-height: 1.15; }
.st-key-table_kpis [data-testid="stColumn"]:first-child [data-testid="stMetricValue"] {
    background: linear-gradient(100deg, #0F172A 0%, #1D4ED8 100%); -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
}

/* ปุ่มลบ / Export: สูง 46px มุม 12px ตัวอักษร 17px */
.st-key-table_action_bar button { min-height: 46px; border-radius: 12px; }
[data-testid="stMainBlockContainer"] .st-key-table_action_bar [data-testid^="stBaseButton-"] p { font-size: 17px !important; font-weight: 700 !important; }
.st-key-delete_selected_rows button, .st-key-export_csv_button button, .st-key-export_excel_button button {
    transition: transform 0.18s ease, box-shadow 0.18s ease, border-color 0.18s ease, background-color 0.18s ease, color 0.18s ease;
}
.st-key-delete_selected_rows button { border-color: #FECACA; color: #B91C1C; }
.st-key-delete_selected_rows button:not(:disabled) { background: #FEF2F2; animation: tbl-pulse-red 0.9s ease-out 1; }
.st-key-delete_selected_rows button:not(:disabled):hover {
    transform: translateY(-2px); border-color: #DC2626; color: #991B1B; box-shadow: 0 10px 18px -8px rgba(220, 38, 38, 0.55);
}
.st-key-export_csv_button button:hover, .st-key-export_excel_button button:hover {
    transform: translateY(-2px); border-color: #2563EB; color: #1D4ED8; box-shadow: 0 10px 18px -8px rgba(37, 99, 235, 0.5);
}
.st-key-export_csv_button button:hover [data-testid="stMarkdownContainer"],
.st-key-export_excel_button button:hover [data-testid="stMarkdownContainer"] { animation: tbl-nudge-down 0.5s ease 1; }
.st-key-delete_selected_rows button:not(:disabled):active,
.st-key-export_csv_button button:active, .st-key-export_excel_button button:active { transform: scale(0.97); box-shadow: none; }
.st-key-table_action_bar [data-testid="stElementContainer"] { animation: tbl-rise 0.45s 0.2s cubic-bezier(.2,.8,.2,1) backwards; }

/* เมนู dropdown ของ selectbox (Item / Vendor): Streamlit 1.66 (react-aria) วาดใน portal นอกการ์ด จึงใช้ selector กลาง
   กรอบมน เงานุ่ม เด้งเปิดนุ่ม ๆ ตัวเลือกอ่านง่าย hover ฟ้าจาง ตัวที่เลือกอยู่ฟ้าเข้ม
   (ไม่แตะความสูงแถว เพราะรายการเป็น virtual list คำนวณตำแหน่งจากความสูงเดิม)
   ห้ามใช้ transform กับตัวเมนูและตัวเลือก: react-aria วางตำแหน่งด้วย inline transform ถ้าทับ เมนูจะวาบไปมุมซ้ายบนก่อนเลื่อนมาที่ช่อง
   จึง animate ด้วย clip-path (ม้วนลงจากขอบบนของช่อง) + opacity เท่านั้น */
[data-testid="stSelectboxVirtualDropdown"] {
    border: 1px solid #E2E8F0; border-radius: 14px; background: #FFFFFF; overflow: hidden;
    box-shadow: 0 4px 6px rgba(15, 23, 42, 0.05), 0 18px 36px -12px rgba(15, 23, 42, 0.28);
    animation: dd-pop 0.26s cubic-bezier(.2,.8,.2,1) backwards;
    scrollbar-width: thin; scrollbar-color: #CBD5E1 transparent;
}
[data-testid="stSelectboxVirtualDropdown"] [role="option"] {
    font-size: 17px; color: #0F172A; border-radius: 10px; padding: 0 14px; width: calc(100% - 12px); margin-left: 6px;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; cursor: pointer;
    transition: background-color 0.12s ease, color 0.12s ease;
}
[data-testid="stSelectboxVirtualDropdown"] [role="option"] { animation: dd-opt-in 0.22s ease 0.06s backwards; }
[data-testid="stSelectboxVirtualDropdown"] [role="option"]:hover,
[data-testid="stSelectboxVirtualDropdown"] [role="option"][data-focused="true"] { background: #EFF6FF; color: #1D4ED8; }
[data-testid="stSelectboxVirtualDropdown"] [role="option"][aria-selected="true"] { background: #DBEAFE; color: #1E3A8A; font-weight: 600; }
.st-key-table_filters [data-testid="stSelectbox"] [role="group"] svg { transition: transform 0.2s ease; }
.st-key-table_filters [data-testid="stSelectbox"] [role="group"]:focus-within svg:last-of-type { transform: rotate(180deg); }
@keyframes dd-pop { from { opacity: 0; clip-path: inset(0 0 100% 0 round 14px); } to { opacity: 1; clip-path: inset(0 0 0 0 round 14px); } }
@keyframes dd-opt-in { from { opacity: 0; } to { opacity: 1; } }
@keyframes tbl-rise { from { opacity: 0; transform: translateY(10px); } to { opacity: 1; transform: none; } }
@keyframes tbl-bar-grow { from { transform: scaleY(0); } to { transform: scaleY(1); } }
@keyframes tbl-pulse-red { 0% { box-shadow: 0 0 0 0 rgba(220, 38, 38, 0.45); } 100% { box-shadow: 0 0 0 12px rgba(220, 38, 38, 0); } }
@keyframes tbl-nudge-down { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(3px); } }
@media (prefers-reduced-motion: reduce) {
    .st-key-table_filters [data-testid="stColumn"], .st-key-table_kpis [data-testid="stMetric"],
    .st-key-table_kpis [data-testid="stMetric"]::before, .st-key-table_action_bar [data-testid="stElementContainer"],
    [data-testid="stSelectboxVirtualDropdown"], .st-key-table_filters [data-testid="stSelectbox"] [role="group"] svg,
    [data-testid="stSelectboxVirtualDropdown"] [role="option"],
    .st-key-delete_selected_rows button, .st-key-export_csv_button [data-testid="stMarkdownContainer"],
    .st-key-export_excel_button [data-testid="stMarkdownContainer"] { animation: none !important; }
    .st-key-table_filters [data-testid="stTextInputRootElement"], .st-key-table_filters [data-testid="stSelectbox"] [role="group"],
    .st-key-table_kpis [data-testid="stMetric"], .st-key-table_action_bar button { transition: none !important; transform: none !important; }
}

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
    padding: 12px 18px 22px 18px; max-height: 92vh; overflow: hidden;
    display: flex; flex-direction: column;
    animation: dialog-pop-in .3s cubic-bezier(.2, .8, .2, 1);
}
/* เลื่อนเฉพาะส่วนเนื้อหา: หัวข้อกับปุ่มปิด (x) อยู่กับที่ ไม่เลื่อนหายตอนเลื่อนฟอร์มลง */
div[data-testid="stDialog"] [role="dialog"] > h2 { flex: 0 0 auto; }
div[data-testid="stDialog"] [role="dialog"] > div:has(> [data-testid="stVerticalBlock"]) { flex: 1 1 auto; min-height: 0; overflow-y: auto; overflow-x: hidden; }
@keyframes dialog-pop-in { from { opacity: 0; transform: translateY(14px) scale(.98); } to { opacity: 1; transform: none; } }
/* ชื่อหน้าต่าง "เพิ่มข้อมูล": ฟอนต์ Prompt ตัวหนา ใหญ่ */
div[data-testid="stDialog"] [role="dialog"] h2,
div[data-testid="stDialog"] [role="dialog"] h2 * { font-family: 'Prompt', 'Sarabun', sans-serif !important; font-size: 26px !important; font-weight: 700 !important; color: #0F172A; }
/* ปุ่มปิด (x): กลม มีพื้นจางตอนชี้ */
div[data-testid="stDialog"] [role="dialog"] > button { border-radius: 50%; transition: background .2s; z-index: 2; }
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

/* จอแคบ (มือถือ <= 640px): ลดขอบหน้าต่าง และให้ตัวอักษรย่อตามความกว้างจอด้วย clamp(ต่ำสุด, ตามจอ, สูงสุดเท่าเดิม)
   แก้ขนาดตัวอักษรของ dialog บนมือถือที่ตัวเลขในกฎนี้ที่เดียว */
@media (max-width: 640px) {
    div[data-testid="stDialog"] [role="dialog"] { padding: 8px 10px 18px 10px; }
    div[data-testid="stDialog"] [role="dialog"] h2,
    div[data-testid="stDialog"] [role="dialog"] h2 * { font-size: clamp(20px, 5.5vw, 26px) !important; }
    div[data-testid="stDialog"] h4 { font-size: clamp(17px, 4.6vw, 22px) !important; }
    div[data-testid="stDialog"] [data-testid="stMarkdownContainer"] p { font-size: clamp(14px, 3.6vw, 17px); }
    div[data-testid="stDialog"] label,
    div[data-testid="stDialog"] label p,
    div[data-testid="stDialog"] .field-label,
    div[data-testid="stDialog"] input,
    div[data-testid="stDialog"] textarea,
    div[data-testid="stDialog"] [data-baseweb="select"] { font-size: clamp(14px, 3.6vw, 17px) !important; }
    .step-subtitle { font-size: clamp(13px, 3.4vw, 16px) !important; }
    div[data-testid="stDialog"] [data-testid="stButton"] button,
    div[data-testid="stDialog"] [data-testid="stFormSubmitButton"] button,
    div[data-testid="stDialog"] [data-testid="stButton"] button p,
    div[data-testid="stDialog"] [data-testid="stFormSubmitButton"] button p { font-size: clamp(15px, 4vw, 18px) !important; }
    div[data-testid="stDialog"] [data-testid="stButtonGroup"] button { padding: 8px 2px !important; }
    div[data-testid="stDialog"] [data-testid="stButtonGroup"] button p { font-size: clamp(13px, 3.6vw, 17px) !important; overflow: visible !important; text-overflow: clip !important; }
}

/* จอ <= 425px: ตัวเลือก 4–5 ตัวจัดเป็นกริด 2 คอลัมน์, 2–3 ตัว (เช่น ใบกำกับภาษี) เรียงลงทีละแถวและตัดบรรทัดได้ → ข้อความไม่ถูกตัด
   แท่งขาวเลื่อน (::before) ใช้กับหลายแถวไม่ได้ จึงปิด แล้วให้ปุ่มที่เลือกมีพื้นขาว+ขอบน้ำเงินเอง */
@media (max-width: 425px) {
    div[data-testid="stDialog"] [data-testid="stButtonGroup"] [role="radiogroup"] {
        grid-auto-flow: row; grid-auto-columns: auto; grid-template-columns: 1fr 1fr; gap: 4px;
    }
    div[data-testid="stDialog"] [data-testid="stButtonGroup"] [role="radiogroup"]:has(> button:nth-child(2):last-child),
    div[data-testid="stDialog"] [data-testid="stButtonGroup"] [role="radiogroup"]:has(> button:nth-child(3):last-child) { grid-template-columns: 1fr; }
    div[data-testid="stDialog"] [data-testid="stButtonGroup"] [role="radiogroup"]::before { display: none; }
    div[data-testid="stDialog"] [data-testid="stButtonGroup"] button { min-height: 46px; padding: 8px 6px !important; }
    div[data-testid="stDialog"] [data-testid="stButtonGroup"] button p { white-space: normal; line-height: 1.25; }
    div[data-testid="stDialog"] [data-testid="stButtonGroup"] button[data-selected="true"] {
        background: #FFFFFF !important; box-shadow: 0 2px 8px rgba(37, 99, 235, 0.22), 0 0 0 1.5px rgba(37, 99, 235, 0.35) !important;
    }
    /* ขั้นที่ 2: ลด padding ที่ซ้อนกันหลายชั้น (เนื้อหา dialog 24px + การ์ด + ฟอร์ม) ให้ช่องกรอกกว้างขึ้น */
    div[data-testid="stDialog"] [role="dialog"] > div:has(> [data-testid="stVerticalBlock"]) { padding-left: 4px !important; padding-right: 4px !important; }
    .st-key-entry_form_card { padding-left: 0 !important; padding-right: 0 !important; }
    .st-key-entry_form_card [data-testid="stForm"] { padding: 10px 8px !important; }
    .st-key-entry_form_card [data-testid="stForm"] [data-testid="stVerticalBlock"] { gap: 0.8rem !important; }
    /* ข้อความตัวอย่างในช่อง: ย่อให้เห็นครบขึ้น ถ้ายาวเกินให้ตัดด้วย ... */
    div[data-testid="stDialog"] input::placeholder,
    div[data-testid="stDialog"] textarea::placeholder { font-size: clamp(12px, 3.3vw, 14px); text-overflow: ellipsis; }
    div[data-testid="stDialog"] .step-subtitle { text-wrap: balance; }
    div[data-testid="stDialog"] [data-testid="stFormSubmitButton"] button p,
    div[data-testid="stDialog"] [data-testid="stButton"] button p { white-space: normal; }
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
/* 8) โหมด Upload: ชิปปลายทาง + แถวปุ่ม (ย้อนกลับ = ปุ่มรอง แคบ / Upload = ปุ่มหลัก กว้าง สูงเท่ากัน) */
.upload-dest-chips { display: flex; flex-wrap: wrap; justify-content: center; gap: 6px 8px; margin: 2px 0 0 0; }
.upload-dest-chips span {
    font-size: 13px; font-weight: 600; color: #0F766E; background: #F0FDFA;
    border: 1px solid #99F6E4; border-radius: 999px; padding: 3px 12px; white-space: nowrap;
}
.upload-dest-chips { margin-bottom: 14px; }
.st-key-upload_card [data-testid="stHorizontalBlock"] { display: grid !important; grid-template-columns: 1fr 2fr; gap: 10px; align-items: stretch; }
.st-key-upload_card [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] { width: 100% !important; min-width: 0 !important; flex: none !important; }
.st-key-upload_back_button, .st-key-upload_submit_button,
.st-key-upload_back_button [data-testid="stButton"], .st-key-upload_submit_button [data-testid="stButton"] { width: 100% !important; }
.st-key-upload_back_button button, .st-key-upload_submit_button button { width: 100%; min-height: 50px; border-radius: 14px; font-weight: 700; }
.st-key-upload_back_button button { background: #ffffff !important; border: 1.5px solid #CBD5E1 !important; color: #475569 !important; }
.st-key-upload_back_button button:hover { border-color: #0D9488 !important; color: #0D9488 !important; }
.st-key-upload_submit_button button {
    box-shadow: 0 8px 18px -6px rgba(37, 99, 235, 0.5);  /* สีปุ่มหลักมาจากธีมกลาง (ฟ้า) */
}
.st-key-upload_submit_button button:hover:not(:disabled) { transform: translateY(-1px); }
.st-key-upload_submit_button button:disabled { opacity: 0.45; cursor: not-allowed; box-shadow: none; }
.st-key-upload_submit_button button p, .st-key-upload_submit_button button:disabled p { color: #ffffff !important; }
/* จอ <= 425px: การ์ดกะทัดรัดขึ้น หัวข้อ/ป้ายตัดบรรทัดได้ ปุ่มสองปุ่มยังอยู่แถวเดียวกัน */
@media (max-width: 425px) {
    .st-key-upload_card [data-testid="stFileUploaderDropzone"] { min-height: 150px; padding: 16px 8px; gap: 10px; }
    .upload-card-hint { white-space: normal; }
    .st-key-upload_box_extract { padding: 16px 12px 12px 12px; }
    .st-key-upload_back_button button p, .st-key-upload_submit_button button p { white-space: nowrap; }
    .st-key-upload_card [data-testid="stHorizontalBlock"] { gap: 8px; grid-template-columns: 1fr 1.5fr; }
    .st-key-upload_back_button button, .st-key-upload_submit_button button { padding-left: 6px; padding-right: 6px; }
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


def _field_key(field_name: str, form_counter: int) -> str:
    """สร้าง key ของช่องกรอก (ต่อท้ายด้วยตัวนับ เพื่อให้ฟอร์มว่างใหม่หลังบันทึกสำเร็จ)"""
    return f"overview_field_{field_name}_{form_counter}"


# ---------------------------------------------------------------------------
# แจ้งเตือนใบกำกับภาษีค้าง
# ---------------------------------------------------------------------------


def get_upload_date(transaction: dict[str, Any]) -> Optional[date]:
    """วันที่ Upload ของรายการ (ใช้นับวันที่ค้าง ไม่ใช่วันที่ในไฟล์ PR)

    อ่านจาก created_at ("YYYY-MM-DD HH:MM:SS") ถ้าไม่มี/ผิดรูปแบบ ถอยไปใช้คอลัมน์ date

    Args:
        transaction: dict รายการจาก database.py

    Returns:
        วันที่ Upload หรือ None ถ้าอ่านวันที่ไม่ได้ทั้งสองคอลัมน์
    """
    for column in ("created_at", "date"):
        try:
            return date.fromisoformat(str(transaction[column])[:10])
        except (KeyError, ValueError, TypeError):
            continue
    return None


def find_overdue_transactions(pending_transactions: list[dict[str, Any]], today: date) -> list[dict[str, Any]]:
    """คัดรายการที่ค้างใบกำกับภาษีเกิน OVERDUE_DAYS_LIMIT วัน นับจากวันที่ Upload

    Args:
        pending_transactions: รายการที่สถานะ "รอใบกำกับภาษี" (dict จาก database.py)
        today: วันนี้ (ส่งเข้ามาเพื่อให้ทดสอบง่าย)

    Returns:
        รายการที่ค้างเกินกำหนด แต่ละ dict จะมีคอลัมน์ "days_pending" (จำนวนวันที่ค้าง)
        และ "upload_date" (วันที่ Upload) เพิ่มมา เรียงจากค้างนานที่สุดก่อน
    """
    overdue_transactions: list[dict[str, Any]] = []

    for transaction in pending_transactions:
        upload_date = get_upload_date(transaction)
        if upload_date is None:
            # วันที่ในฐานข้อมูลผิดรูปแบบ ข้ามรายการนี้ไป ไม่ให้ทั้งหน้าพัง
            continue

        days_pending = (today - upload_date).days
        if days_pending > OVERDUE_DAYS_LIMIT:
            overdue_transactions.append(
                {**transaction, "days_pending": days_pending, "upload_date": upload_date.isoformat()}
            )

    overdue_transactions.sort(key=lambda item: item["days_pending"], reverse=True)
    return overdue_transactions


# ตารางรายการที่ค้าง: ชื่อคอลัมน์ที่แสดง และความกว้างที่ต้องการ (None = คอลัมน์ข้อความยาว ยืดตามหน้าจอ)
# ถ้าเพิ่มคอลัมน์ในตารางนี้: เพิ่มชื่อใน OVERDUE_TABLE_COLUMNS แล้วกำหนดความกว้างใน OVERDUE_TABLE_COLUMN_WIDTHS
OVERDUE_TABLE_COLUMNS: dict[str, str] = {
    "id": "รหัส",
    "upload_date": "วันที่อัปโหลด",
    "vendor": "ผู้ขาย",
    "po_no": "เลขที่ PO",
    "total_price": "ราคารวม (บาท)",
    "days_pending": "ค้างมาแล้ว (วัน)",
}
# ค้างตั้งแต่กี่วันขึ้นไปถือว่า "วิกฤต" (ป้ายวันที่ค้างเป็นสีแดงเข้ม) ที่เหลือเป็นสีส้ม แก้ตัวเลขตรงนี้ได้
OVERDUE_CRITICAL_DAYS: int = 30


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
        "</div>"
        f'<div class="overdue-alert-badges">'
        f'<span class="overdue-pill overdue-pill-count"><b>{overdue_count}</b> รายการ</span>'
        f'<span class="overdue-pill overdue-pill-days">นานสุด <b>{longest_days}</b> วัน</span>'
        "</div>"
        "</div>"
    )


def build_no_overdue_html() -> str:
    """สร้าง HTML ของแถบสถานะปกติ เมื่อไม่มีใบกำกับภาษีค้างเกินกำหนด (ไม่มีข้อความจากผู้ใช้)

    Returns:
        สตริง HTML (สไตล์อยู่ใน PAGE_CSS_RULES คลาส overdue-alert-ok)
    """
    return (
        '<div class="overdue-alert overdue-alert-ok" role="status">'
        '<div class="overdue-alert-icon">✅</div>'
        '<div class="overdue-alert-text">'
        f'<div class="overdue-alert-title">ไม่มีรายการค้างเกิน {OVERDUE_DAYS_LIMIT} วัน</div>'
        '<div class="overdue-alert-sub">นับจากวันที่ Upload / บันทึกข้อมูล</div>'
        "</div>"
        "</div>"
    )


def format_overdue_date(date_text: Any) -> str:
    """แปลงวันที่ "YYYY-MM-DD" เป็น DD/MM/YYYY (แปลงไม่ได้ให้คืนข้อความเดิม ไม่แครช)

    Args:
        date_text: วันที่จาก DB

    Returns:
        ข้อความวันที่สำหรับแสดงผล
    """
    try:
        return date.fromisoformat(str(date_text)).strftime("%d/%m/%Y")
    except ValueError:
        return str(date_text or "")


def format_overdue_price(price: Any) -> str:
    """จัดรูปเงินแบบมีคอมม่าทศนิยม 2 ตำแหน่ง (ค่าว่าง/แปลงไม่ได้ให้ขีด "-")

    Args:
        price: ราคารวมจาก DB

    Returns:
        ข้อความราคาสำหรับแสดงผล
    """
    try:
        return f"{float(price):,.2f}"
    except (TypeError, ValueError):
        return "-"


def build_overdue_table_html(overdue_transactions: list[dict[str, Any]]) -> str:
    """สร้าง HTML ตารางรายการที่ค้างแบบ modern (สไตล์อยู่ใน PAGE_CSS_RULES หัวข้อ "ตารางรายการที่ค้าง")

    Args:
        overdue_transactions: รายการที่ค้างเกินกำหนด (จาก find_overdue_transactions มีคอลัมน์ days_pending)

    Returns:
        สตริง HTML (ข้อความจากผู้ใช้ผ่าน html.escape แล้วทุกจุด)

    Raises:
        KeyError: ถ้าข้อมูลขาดคอลัมน์ที่ตารางต้องใช้
    """
    headers = "".join(f"<span>{html.escape(title)}</span>" for title in OVERDUE_TABLE_COLUMNS.values())
    parts: list[str] = ['<div class="od-table"><div class="od-scroll">', f'<div class="od-head">{headers}</div>']
    for index, transaction in enumerate(overdue_transactions):
        days = int(transaction["days_pending"])
        is_critical = days >= OVERDUE_CRITICAL_DAYS
        vendor = html.escape(str(transaction["vendor"] or "-"))
        po_no = html.escape(str(transaction["po_no"] or "-"))
        badge_class = "od-badge-critical" if is_critical else "od-badge-warn"
        parts.append(
            f'<div class="od-row{" od-row-critical" if is_critical else ""}" style="--i:{min(index, 12)}">'
            f'<span class="od-id">{html.escape(str(transaction["id"]))}</span>'
            f'<span class="od-date">{format_overdue_date(transaction["upload_date"])}</span>'
            f'<span class="od-vendor" title="{vendor}">{vendor}</span>'
            f'<span class="od-po" title="{po_no}">{po_no}</span>'
            f'<span class="od-price">{format_overdue_price(transaction["total_price"])}</span>'
            f'<span class="od-days"><b class="od-badge {badge_class}">{"🔥" if is_critical else "⏰"} {days} วัน</b></span>'
            "</div>"
        )
    parts.append("</div></div>")
    return "".join(parts)


def render_overdue_table(overdue_transactions: list[dict[str, Any]]) -> None:
    """วาดตารางรายการที่ค้างเป็น HTML modern (วันที่เป็น DD/MM/YYYY, เงินมีคอมม่า, ป้ายวันที่ค้าง)

    Args:
        overdue_transactions: รายการที่ค้างเกินกำหนด (จาก find_overdue_transactions มีคอลัมน์ days_pending)
    """
    try:
        st.markdown(build_overdue_table_html(overdue_transactions), unsafe_allow_html=True)
    except (KeyError, ValueError, TypeError) as error:
        logger.warning("วาดตารางรายการที่ค้างไม่สำเร็จ: %s", error)
        st.error("แสดงตารางรายการที่ค้างไม่สำเร็จ กรุณารีเฟรชหน้าอีกครั้ง")


def render_overdue_alert() -> None:
    """แสดงแถบแจ้งเตือนใบกำกับภาษีค้างเกินกำหนด พร้อมแถบกางดูรายการที่ค้าง (แสดงเสมอ อยู่เหนือตาราง Master-List)

    หมายเหตุ: นับจากวันที่ Upload / บันทึก (created_at) ไม่ขึ้นกับคอลัมน์ Date (วันที่ไฟล์ PR) และไม่ขึ้นกับ Date Filter
    เพราะรายการเก่าที่ค้างอยู่ต้องไม่หลุดจากการแจ้งเตือนเมื่อผู้ใช้เลือกช่วงวันที่ใหม่
    ไม่มีรายการค้าง = แสดงแถบสีเขียว "ไม่มีรายการค้าง" แทนการซ่อนแถบ
    """
    pending_transactions = get_transactions(invoice_status=STATUS_PENDING)
    overdue_transactions = find_overdue_transactions(pending_transactions, date.today())

    with st.container(key="overdue_alert"):
        if overdue_transactions:
            # find_overdue_transactions เรียงจากค้างนานสุดก่อน รายการแรกจึงเป็นรายการที่นานที่สุด
            longest_days = int(overdue_transactions[0]["days_pending"])
            st.markdown(build_overdue_alert_html(len(overdue_transactions), longest_days), unsafe_allow_html=True)
        else:
            st.markdown(build_no_overdue_html(), unsafe_allow_html=True)
        # on_change="rerun" + เช็ค .open: วาดตารางเมื่อกางออกแล้วเท่านั้น (ตาราง AgGrid ที่ถูกสร้างตอนพับอยู่จะกว้าง 0 แล้วแสดงไม่ได้)
        overdue_expander = st.expander("ดูรายการที่ค้าง", on_change="rerun")
        if overdue_expander.open:
            with overdue_expander:
                if overdue_transactions:
                    render_overdue_table(overdue_transactions)
                else:
                    st.info("ไม่มีรายการค้าง")


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


def get_status_label(invoice_status: str, upload_date: Optional[date], today: date) -> str:
    """แปลงสถานะใบกำกับภาษีในฐานข้อมูลเป็นข้อความที่แสดงในตาราง

    กติกา:
      - ได้รับใบกำกับภาษีแล้ว                          -> "✅ Completed"
      - รอใบกำกับภาษี และค้างไม่เกิน OVERDUE_DAYS_LIMIT วัน -> "⏳ Pending"
      - รอใบกำกับภาษี และค้างเกิน OVERDUE_DAYS_LIMIT วัน   -> "🔴 Overdue"
    (นับวันค้างจากวันที่ Upload ไม่ใช่วันที่ในไฟล์ PR)

    Args:
        invoice_status: ค่าในคอลัมน์ invoice_status (STATUS_PENDING / STATUS_RECEIVED)
        upload_date: วันที่ Upload (None ถ้าอ่านวันที่ไม่ได้ จะถือว่ายังไม่เกินกำหนด)
        today: วันนี้ (ส่งเข้ามาเพื่อให้ทดสอบง่าย)

    Returns:
        ข้อความสถานะ ถ้าเป็นสถานะที่ไม่รู้จักจะแสดงค่าเดิมตามที่เก็บไว้
    """
    if invoice_status == STATUS_RECEIVED:
        return STATUS_LABEL_COMPLETED
    if invoice_status == STATUS_PENDING:
        is_overdue = upload_date is not None and (today - upload_date).days > OVERDUE_DAYS_LIMIT
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
                "invoice_status": get_status_label(transaction["invoice_status"], get_upload_date(transaction), today),
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
                # มีลิงก์ออนไลน์ (โฟลเดอร์ SharePoint) -> ไอคอนเปิดลิงก์นั้นในแท็บใหม่
                # ไม่มี (ยังไม่ได้สิทธิ์) -> ไอคอนเปิดไฟล์ในระบบ (ถ้าเปิด LOCAL_DESKTOP_EXPORT = เปิดโฟลเดอร์ที่เก็บไฟล์ ดู handle_file_icon_click)
                "sharepoint_url": _valid_link_or_none(transaction.get("sharepoint_url"))
                or build_local_file_url(transaction.get("file_path"))
                or "",
            }
        )
    # หมายเหตุ: ตารางนี้ใช้ index ลำดับ 0,1,2,... (ไม่ใช่ id)
    # ถ้า index ไม่ใช่ลำดับ ส่วนการรู้ว่าแถวที่ n คือรายการ id อะไร ให้ดูจากลิสต์ id ที่เรียงเหมือนกัน
    # (ดู transaction_ids ใน render_table_card / apply_table_edits)
    return pd.DataFrame(display_rows, columns=list(TABLE_COLUMNS.keys())).rename(columns=TABLE_COLUMNS)


def build_update_fields(changes: dict[str, Any], original_row: pd.Series) -> tuple[dict[str, Any], bool]:
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


def register_row_effects(transaction_ids: list[int], effect: str) -> None:
    """จดว่าแถวเหล่านี้ต้องเล่น animation (ROW_FX_NEW / ROW_FX_UPDATED) ตามเวลาที่กำหนด

    ใช้เวลาหมดอายุแทนการใช้ครั้งเดียวแล้วทิ้ง เพราะตารางอาจรีรันซ้ำทันทีหลังอัปเดต (เช่น ส่งผลเลือกแถวกลับมา)
    ถ้าลบ class ทันที animation ที่เพิ่งเริ่มจะถูกตัดจบกลางคัน

    Args:
        transaction_ids: id รายการที่ต้องเล่น animation
        effect: ชนิด animation (ROW_FX_NEW หรือ ROW_FX_UPDATED)
    """
    if not transaction_ids:
        return
    effects: dict[int, tuple[str, float]] = st.session_state.setdefault(SESSION_KEY_ROW_EFFECTS, {})
    expires_at = time.monotonic() + ROW_FX_HIGHLIGHT_MS / 1000
    for transaction_id in transaction_ids:
        effects[int(transaction_id)] = (effect, expires_at)


def collect_row_effects(all_transactions: list[dict[str, Any]]) -> dict[int, str]:
    """รวบรวม animation ของแถวที่ต้องเล่นในรอบนี้: แถวใหม่ (id สูงกว่าที่เคยเห็น) + แถวที่เพิ่งแก้ไขและยังไม่หมดเวลา

    Args:
        all_transactions: รายการทั้งหมดในช่วงวันที่ (ใช้หา id สูงสุดเพื่อรู้ว่ามีแถวใหม่ไหม)

    Returns:
        {id รายการ: ชนิด animation} (ว่างถ้าไม่มี)
    """
    current_max_id = max((int(t["id"]) for t in all_transactions), default=0)
    max_seen_id: Optional[int] = st.session_state.get(SESSION_KEY_MAX_SEEN_ID)
    if max_seen_id is not None and current_max_id > max_seen_id:
        # id เพิ่มขึ้นเรื่อย ๆ (AUTOINCREMENT) แถวที่ id สูงกว่าที่เคยเห็น = เพิ่งถูกเพิ่ม (ครั้งแรกที่เปิดหน้าไม่ถือว่าใหม่)
        register_row_effects([int(t["id"]) for t in all_transactions if int(t["id"]) > max_seen_id], ROW_FX_NEW)
    st.session_state[SESSION_KEY_MAX_SEEN_ID] = max(current_max_id, max_seen_id or 0)

    now = time.monotonic()
    stored: dict[int, tuple[str, float]] = st.session_state.get(SESSION_KEY_ROW_EFFECTS, {})
    active = {
        transaction_id: (effect, expires_at)
        for transaction_id, (effect, expires_at) in stored.items()
        if expires_at > now
    }
    st.session_state[SESSION_KEY_ROW_EFFECTS] = active  # ทิ้งอันที่หมดเวลาแล้ว
    return {transaction_id: effect for transaction_id, (effect, _expires_at) in active.items()}


def request_delete_selected() -> None:
    """callback ปุ่ม "ลบรายการที่เลือก": จำ id ที่ติ๊กไว้ รอบถัดไปจะเล่น animation ลบก่อนแล้วค่อยลบจริง"""
    st.session_state[SESSION_KEY_DELETING_IDS] = list(st.session_state.get(SESSION_KEY_LAST_SELECTED_IDS, []))


def apply_table_edits(
    display_table: pd.DataFrame, transaction_ids: list[int], editor_state: dict[str, Any]
) -> list[tuple[str, str]]:
    """ซิงก์การแก้ไข/ลบในตาราง (AgGrid) กลับไปที่ตาราง transactions ในฐานข้อมูลทันที

    ใช้ editor_state ซึ่งมี 3 ส่วน (สร้างจากตาราง AgGrid ใน render_table_card):
      - edited_rows  : {ตำแหน่งแถว: {หัวคอลัมน์: ค่าใหม่}}  -> อัปเดตด้วย update_transaction
      - deleted_rows : [ตำแหน่งแถว, ...]                    -> ลบด้วย delete_transactions (ครั้งเดียวทั้งชุด)
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

    updated_count = delete_failed_count = update_failed_count = 0
    ignored_status_count = 0
    error_reasons: list[str] = []
    updated_ids: list[int] = []  # id ที่แก้สำเร็จ ใช้เล่น animation ไฮไลต์แถว

    # --- ลบ (Delete) --- ลบทุกแถวใน connection เดียว (เร็วกว่าลบทีละแถว)
    delete_ids: list[int] = []
    for position in sorted(deleted_positions):
        try:
            delete_ids.append(int(transaction_ids[position]))
        except (IndexError, ValueError, TypeError) as error:
            delete_failed_count += 1
            error_reasons.append(f"ลบแถวที่ {position + 1}: {error}")
    deleted_count = delete_transactions(delete_ids)  # แสดง error ให้เองเมื่อล้มเหลว
    delete_failed_count += len(delete_ids) - deleted_count

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
                updated_ids.append(transaction_id)
            else:
                update_failed_count += 1
        except ValueError as error:
            update_failed_count += 1
            error_reasons.append(f"แถวที่ {position + 1}: {error}")
        except (IndexError, TypeError, KeyError) as error:
            update_failed_count += 1
            error_reasons.append(f"แถวที่ {position + 1}: ข้อมูลไม่ถูกต้อง ({error})")

    register_row_effects(updated_ids, ROW_FX_UPDATED)

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
        messages.append(("info", 'ℹ️ เพิ่มรายการใหม่ไม่ได้จากตาราง กรุณาใช้ฟอร์ม "กรอก Form" ด้านขวา (แถวที่เพิ่มถูกยกเลิก)'))
    if ignored_status_count:
        messages.append(
            (
                "info",
                f"ℹ️ สถานะ Pending / Overdue ระบบกำหนดให้อัตโนมัติ (ค้างเกิน {OVERDUE_DAYS_LIMIT} วัน = Overdue) "
                "เปลี่ยนเองไม่ได้ เลือกได้เฉพาะ Completed เมื่อได้รับใบกำกับภาษีแล้ว",
            )
        )
    return messages


def build_grid_table(
    display_table: pd.DataFrame,
    transaction_ids: list[int],
    row_effects: Optional[dict[int, str]] = None,
) -> pd.DataFrame:
    """แปลงตารางแสดงผล (หัวคอลัมน์เป็นป้ายไทย/อังกฤษ) เป็นตารางสำหรับ AgGrid (ชื่อคอลัมน์ = ชื่อใน DB)

    ต่างจาก display_table 3 อย่าง: ชื่อคอลัมน์เป็นชื่อใน DB, วันที่เป็นข้อความ "YYYY-MM-DD" (ไม่มี = ""),
    และมีคอลัมน์ลำดับแถว ROW_POSITION_COLUMN (ใช้จับคู่แถวตอนแก้ไข/ลบ แม้ผู้ใช้เรียงลำดับหรือกรองตาราง)

    Args:
        display_table: ตารางจาก build_table_for_display
        transaction_ids: id รายการในฐานข้อมูล เรียงเหมือนแถวของ display_table (ใส่คอลัมน์ ROW_ID_COLUMN)
        row_effects: {id รายการ: ชนิด animation} ของแถวที่ต้องเล่น animation (ใส่คอลัมน์ ROW_FX_COLUMN)

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
    grid_table.insert(1, ROW_ID_COLUMN, [int(transaction_id) for transaction_id in transaction_ids])
    effects = row_effects or {}
    grid_table[ROW_FX_COLUMN] = [effects.get(int(transaction_id), "") for transaction_id in transaction_ids]
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
            "enableCellChangeFlash": False,  # สีป้ายไล่เปลี่ยนเอง + ไฮไลต์แถวทันที ไม่ต้องแฟลชเซลล์ซ้อนอีกชั้น
            "cellRenderer": JsCode(STATUS_BADGE_RENDERER_JS.replace("STATUS_COLORS", json.dumps(STATUS_BADGE_COLORS))),
            "cellEditor": JsCode(
                STATUS_DROPDOWN_EDITOR_JS.replace("STATUS_OPTIONS", json.dumps(STATUS_EDITOR_OPTIONS)).replace(
                    "STATUS_COLORS", json.dumps(STATUS_BADGE_COLORS)
                )
            ),
        },
        "unit_price": {"cellEditor": "agNumberCellEditor", "cellEditorParams": {"min": 0}},
        # คอลัมน์ไฟล์: แสดงเป็นไอคอน กดแล้วเปิดลิงก์ SharePoint ในแท็บใหม่ (ดู FILE_LINK_RENDERER_JS)
        "sharepoint_url": {
            "cellRenderer": JsCode(
                FILE_LINK_RENDERER_JS.replace("FILE_STATIC_PREFIX", re.escape(STATIC_URL_PREFIX).replace("/", "\\/"))
                .replace("FILE_DESKTOP_MODE", "true" if DESKTOP_EXPORT_ENABLED else "false")
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
        hidden_columns=(
            ROW_POSITION_COLUMN,
            ROW_ID_COLUMN,
            ROW_FX_COLUMN,
            *HIDDEN_TABLE_COLUMNS,
        ),  # ซ่อนในตาราง แต่ข้อมูล/Export ยังครบ
        selectable=True,
        paginated=True,
        filterable=True,
        extra_column_options=extra_column_options,
        row_id_column=ROW_ID_COLUMN,  # id จริงในฐานข้อมูล: ข้อมูลเปลี่ยนแล้วตารางอัปเดตเฉพาะแถว + animation ทำงาน
        row_fx_column=ROW_FX_COLUMN,
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

    จับคู่แถวด้วย id รายการ (ROW_ID_COLUMN) ไม่ใช่ลำดับแถว เพราะตารางไม่ถูกวาดใหม่เมื่อข้อมูลเปลี่ยน
    ค่าที่ตารางส่งกลับจึงอาจเป็นของข้อมูลชุดก่อนหน้า: แถวที่ไม่อยู่ในตารางปัจจุบันถูกข้าม

    Args:
        original_table: ตารางเดิมที่ส่งให้ AgGrid (จาก build_grid_table)
        grid_response: ผลจาก show_grid (None ถ้าตารางวาดไม่สำเร็จ หรือยังไม่ส่งค่ากลับ)

    Returns:
        {ตำแหน่งแถวในตารางปัจจุบัน: {หัวคอลัมน์: ค่าใหม่}} รูปแบบ edited_rows (ส่งต่อให้ apply_table_edits ได้เลย)
    """
    returned_table = getattr(grid_response, "data", None)
    if returned_table is None or len(returned_table) == 0 or ROW_ID_COLUMN not in returned_table.columns:
        return {}

    returned_unique = returned_table.drop_duplicates(ROW_ID_COLUMN)
    returned_by_id = returned_unique.set_index(returned_unique[ROW_ID_COLUMN].astype(int))
    changes_by_position: dict[int, dict[str, Any]] = {}
    for _, original_row in original_table.iterrows():
        transaction_id = int(original_row[ROW_ID_COLUMN])
        if transaction_id not in returned_by_id.index:
            continue
        row_changes: dict[str, Any] = {}
        for column in EDITABLE_TABLE_COLUMNS:
            original_value = _normalize_cell_value(original_row[column])
            new_value = _normalize_cell_value(returned_by_id.at[transaction_id, column])
            if original_value != new_value:
                row_changes[TABLE_COLUMNS[column]] = new_value
        if row_changes:
            changes_by_position[int(original_row[ROW_POSITION_COLUMN])] = row_changes
    return changes_by_position


def get_selected_positions(grid_response: Any, grid_table: pd.DataFrame) -> list[int]:
    """อ่านตำแหน่งแถวที่ผู้ใช้ติ๊กเลือกในตาราง (ใช้กับปุ่มลบ)

    Args:
        grid_response: ผลจาก show_grid (None = ไม่มีแถวที่เลือก)
        grid_table: ตารางปัจจุบันที่ส่งให้ AgGrid: ใช้แปลง id ที่เลือกเป็นตำแหน่งแถว และตัดแถวที่ไม่อยู่ในตารางแล้ว
            (เช่น เพิ่งลบไป แต่ตารางยังส่งผลเลือกชุดเก่ากลับมา)

    Returns:
        ตำแหน่งแถวตาม ROW_POSITION_COLUMN (ว่างถ้าไม่ได้เลือก)
    """
    selected_rows = getattr(grid_response, "selected_rows", None)
    if selected_rows is None or len(selected_rows) == 0:
        return []
    # selected_rows อาจเป็น DataFrame หรือ list ของ dict ตามเวอร์ชันของไลบรารี รองรับทั้งสองแบบ
    records = selected_rows.to_dict("records") if isinstance(selected_rows, pd.DataFrame) else list(selected_rows)
    position_by_id = {
        int(transaction_id): int(position)
        for transaction_id, position in zip(grid_table[ROW_ID_COLUMN], grid_table[ROW_POSITION_COLUMN])
    }
    return sorted(
        {
            position_by_id[int(record[ROW_ID_COLUMN])]
            for record in records
            if record.get(ROW_ID_COLUMN) is not None and int(record[ROW_ID_COLUMN]) in position_by_id
        }
    )


def find_clicked_file_position(grid_response: Any, position_by_id: dict[int, int]) -> Optional[int]:
    """อ่านว่าผู้ใช้เพิ่งกดไอคอนในคอลัมน์ File ของแถวไหน (จาก event cellClicked)

    Args:
        grid_response: ผลจาก show_grid (None = ไม่มีเหตุการณ์)
        position_by_id: {id รายการ: ตำแหน่งแถวในตารางปัจจุบัน} (event ค้างอาจเป็นของแถวที่ไม่อยู่ในตารางแล้ว)

    Returns:
        ตำแหน่งแถวในตารางปัจจุบัน หรือ None ถ้าไม่ใช่การกดคอลัมน์ File / แถวนั้นไม่อยู่ในตารางแล้ว
    """
    event_data = getattr(grid_response, "event_data", None)
    if not isinstance(event_data, dict) or event_data.get("type") != "cellClicked":
        return None
    column_id = event_data.get("colId") or (event_data.get("column") or {}).get("colId") or ""
    row_data = event_data.get("data") or (event_data.get("node") or {}).get("data") or {}
    # colId ในตารางจริงคือชื่อฟิลด์ (sharepoint_url) ส่วนหัวคอลัมน์ "File" เป็นแค่ข้อความแสดง
    if column_id not in ("sharepoint_url", TABLE_COLUMNS["sharepoint_url"]) or row_data.get(ROW_ID_COLUMN) is None:
        return None
    return position_by_id.get(int(row_data[ROW_ID_COLUMN]))


def handle_file_icon_click(grid_response: Any, visible_transactions: list[dict[str, Any]]) -> None:
    """กดไอคอน File: เปิดหน้าต่างโฟลเดอร์ที่เก็บไฟล์ของแถวนั้นขึ้นหน้าจอ (ไม่สร้างโฟลเดอร์ ไม่คัดลอกไฟล์ — สร้างไว้แล้วตอน Upload)

    ใช้วันที่ created_at ของแถว (วันที่บันทึกรายการ = วันที่อัปโหลด) หาโฟลเดอร์ ปี/เดือน/วัน บน Desktop
    event ค้างอยู่ทุกครั้งที่หน้ารีรัน (และไม่มีเวลากำกับ) จึงจัดการเสร็จแล้วเปลี่ยน key ของตารางแล้วรีรัน
    ตารางใหม่ไม่มี event ค้าง -> ไม่ทำซ้ำ และกดไอคอนเดิมซ้ำได้

    Args:
        grid_response: ผลจาก show_grid
        visible_transactions: รายการที่แสดงในตาราง (แถวที่ n ในตาราง = ตัวที่ n)
    """
    if not DESKTOP_EXPORT_ENABLED:
        return  # โหมดปกติ (Server): ไอคอนเป็นลิงก์เปิดไฟล์ในเบราว์เซอร์ ไม่ต้องคัดลอกอะไร
    position = find_clicked_file_position(grid_response, {int(t["id"]): n for n, t in enumerate(visible_transactions)})
    if position is None or not 0 <= position < len(visible_transactions):
        return

    transaction = visible_transactions[position]
    try:
        pr_date = datetime.fromisoformat(f"{transaction['date']}T00:00:00")  # โฟลเดอร์ ปี/เดือน/วัน ตามวันที่ PR
    except ValueError:
        pr_date = datetime.now()
    message: tuple[str, str]
    try:
        folder = find_file_location(transaction.get("file_path") or "", pr_date)
    except LocalStorageError as error:
        message = ("error", f"❌ {error}")
    else:
        message = ("success", f"📁 เปิดโฟลเดอร์ที่เก็บไฟล์: {folder}")
        _open_folder_in_explorer(folder)
    st.session_state[SESSION_KEY_STATUS_MESSAGES] = [message]  # แสดงหลังรีรัน (ดู render ด้านบนของหน้า)
    st.session_state[SESSION_KEY_EDITOR_VERSION] = st.session_state.get(SESSION_KEY_EDITOR_VERSION, 0) + 1
    st.rerun()


def _bring_explorer_window_to_front(folder_name: str, timeout_seconds: float = 2.0) -> None:
    """ดึงหน้าต่าง Explorer ที่ชื่อตรงกับโฟลเดอร์ขึ้นหน้าสุด (Windows เท่านั้น)

    Streamlit ไม่ใช่หน้าต่าง foreground (เบราว์เซอร์เป็น) Windows จึงมักเปิด Explorer ไว้ข้างหลัง
    จึงรอให้หน้าต่างโผล่ แล้วส่ง Alt key เพื่อผ่านข้อจำกัด foreground-lock ก่อนสั่ง SetForegroundWindow

    Args:
        folder_name: ชื่อโฟลเดอร์ชั้นสุดท้าย (ชื่อหน้าต่าง Explorer = ชื่อโฟลเดอร์นี้)
        timeout_seconds: เวลารอสูงสุดให้หน้าต่างโผล่
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def collect_window(hwnd: int, _lparam: int) -> bool:
        class_name = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, class_name, 64)
        if class_name.value == "CabinetWClass" and user32.IsWindowVisible(hwnd):
            title = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(hwnd, title, 512)
            if title.value == folder_name or title.value.startswith(
                f"{folder_name} - "
            ):  # Win11 ต่อท้าย " - File Explorer"
                found.append(hwnd)
        return True

    deadline = time.monotonic() + timeout_seconds
    while not found and time.monotonic() < deadline:
        user32.EnumWindows(collect_window, 0)
        if not found:
            time.sleep(0.1)
    if not found:
        return

    vk_menu, keyeventf_keyup, sw_restore = 0x12, 0x0002, 9
    user32.keybd_event(vk_menu, 0, 0, 0)  # กด/ปล่อย Alt เพื่อให้ Windows อนุญาตให้ดึงหน้าต่างขึ้นหน้า
    user32.keybd_event(vk_menu, 0, keyeventf_keyup, 0)
    user32.ShowWindow(found[0], sw_restore)
    user32.SetForegroundWindow(found[0])


def _open_folder_in_explorer(folder: Path) -> None:
    """เปิดโฟลเดอร์ใน Explorer แล้วดึงหน้าต่างขึ้นหน้าจอ (Windows เท่านั้น) ถ้าเปิดไม่ได้แค่บันทึก log ไม่ให้หน้าเว็บล้ม"""
    if sys.platform != "win32":
        return
    try:
        os.startfile(folder)  # noqa: S606 - เปิดโฟลเดอร์ที่มีอยู่แล้ว ไม่สร้างอะไรเพิ่ม
    except OSError:
        logger.warning("เปิดโฟลเดอร์ใน Explorer ไม่สำเร็จ", exc_info=True)
        return
    try:
        _bring_explorer_window_to_front(folder.name)
    except (OSError, AttributeError, ImportError):
        logger.warning("ดึงหน้าต่าง Explorer ขึ้นหน้าจอไม่สำเร็จ", exc_info=True)


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
    """แปลงตารางเป็นไฟล์ .xlsx ในหน่วยความจำ (ต้องใช้ openpyxl) จัดรูปแบบตาม utils/excel_export.py

    Args:
        export_table: ตารางที่กรองแล้ว (หัวคอลัมน์ตาม TABLE_COLUMNS)

    Returns:
        ไบต์ของไฟล์ Excel หรือ None ถ้าแปลงไม่สำเร็จ
    """
    try:
        return build_excel_bytes(export_table)
    except (ValueError, TypeError, OSError, ImportError) as error:
        logger.error("แปลงตารางเป็น Excel ไม่สำเร็จ: %s", error, exc_info=True)
        st.error(f"❌ สร้างไฟล์ Excel ไม่สำเร็จ: {error}")
        return None


def render_table_card(range_transactions: list[dict[str, Any]], start_date: date, end_date: date) -> None:
    """วาดการ์ดตาราง: ช่อง Search bar, dropdown Item / Vendor และตารางรายการ

    Args:
        range_transactions: รายการทั้งหมดในช่วงวันที่ของ Date Filter (ใช้สร้างตัวเลือก Vendor)
        start_date: วันที่เริ่มต้นจาก Date Filter
        end_date: วันที่สิ้นสุดจาก Date Filter
    """
    with st.container(key="table_card"):
        # แถบตัวกรองแถวเดียว: ช่องค้นหา (กว้างสุด) + dropdown Item + dropdown Vendor
        # ถ้าจะเพิ่มตัวกรองใหม่ ให้เพิ่มสัดส่วนใน st.columns ด้านล่าง แล้วเพิ่มเงื่อนไขกรองต่อจาก selected_vendor
        # key="table_filters" ให้ CSS (PAGE_CSS_RULES ข้อ 1.6) จับเฉพาะแถบกรองนี้
        with st.container(key="table_filters"):
            search_column, item_column, vendor_column = st.columns([3, 1.3, 1.7])

            # ช่องค้นหา: ค้นเฉพาะชื่อ Vendor และ Tel. (ดู database.get_transactions)
            search_keyword = search_column.text_input(
                "Search bar",
                placeholder="🔍 ค้นหา ชื่อ Vendor, Tel.",
                label_visibility="collapsed",
            ).strip()

            selected_item = item_column.selectbox(
                "Item", [ALL_ITEMS_LABEL, *CATEGORY_OPTIONS], label_visibility="collapsed"
            )
            vendor_options = [ALL_VENDORS_LABEL, *sorted({t["vendor"] for t in range_transactions})]
            selected_vendor = vendor_column.selectbox("Vendor", vendor_options, label_visibility="collapsed")

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
            with st.container(key="table_kpis"):  # key ให้ CSS จับการ์ด KPI (ข้อ 1.6)
                summary_column, count_column = st.columns(2)
                summary_column.metric("Total Price (บาท)", f"{total_price:,.2f}")
                count_column.metric("จำนวนรายการ", f"{len(display_table):,}")

            # ตาราง AgGrid แบบแก้ไข/ลบได้ (CRUD): ดับเบิลคลิกช่องเพื่อแก้ไขค่า / ติ๊กเลือกแถวแล้วกดปุ่ม "ลบ" เพื่อลบ
            # ทุกการแก้ไขหรือลบจะถูกซิงก์ลงฐานข้อมูลทันที (ดู apply_table_edits)
            editor_version = st.session_state.setdefault(SESSION_KEY_EDITOR_VERSION, 0)
            transaction_ids = [t["id"] for t in visible_transactions]  # แถวที่ n ในตาราง = transaction_ids[n]

            # animation ของแถว: แถวใหม่ / แถวที่เพิ่งแก้ (ยังไม่หมดเวลา) / แถวที่กดลบไว้ (รอเล่น animation ก่อนลบจริง)
            row_effects = collect_row_effects(range_transactions)
            visible_id_set = {int(transaction_id) for transaction_id in transaction_ids}
            deleting_ids = [
                int(transaction_id)
                for transaction_id in st.session_state.pop(SESSION_KEY_DELETING_IDS, [])
                if int(transaction_id) in visible_id_set
            ]
            for transaction_id in deleting_ids:
                row_effects[transaction_id] = ROW_FX_DELETING

            # ปุ่มลบอยู่เหนือตาราง แต่ต้องรู้แถวที่เลือกจากตารางก่อน จึงจองที่ไว้แล้วเติมหลังวาดตาราง
            action_bar = st.container(key="table_action_bar")  # key ใช้ให้ CSS responsive (config/styles.py) จับแถบปุ่ม

            grid_table = build_grid_table(display_table, transaction_ids, row_effects)
            # key คงที่ (เปลี่ยนเฉพาะเมื่อต้องวาดตารางใหม่จริง ๆ ดู editor_version): ข้อมูลเปลี่ยน (ค้นหา / กรอง / Date Filter / แก้ / ลบ / เพิ่ม)
            # ตารางเดิมรับข้อมูลใหม่แล้วอัปเดตเฉพาะแถวที่ต่าง ไม่กระพริบ และเล่น animation ได้ แถวจับคู่ด้วย id รายการ (ROW_ID_COLUMN)
            grid_response = show_grid(
                grid_table,
                build_transaction_grid_options(grid_table),
                f"transaction_grid_{editor_version}",
                # ส่งค่ากลับเมื่อแก้ไขเซลล์ / เปลี่ยนแถวที่เลือก / กดเซลล์ File (ใช้จับการกดไอคอน File; กดคอลัมน์อื่นไม่รีรัน)
                update_on=["cellValueChanged", "selectionChanged", "cellClicked"],
                server_wins=True,  # ข้อมูลจากเซิร์ฟเวอร์ทับตารางเสมอ (ไม่งั้นหลังแก้ครั้งแรกตารางจะเมินข้อมูลใหม่)
                click_only_column="sharepoint_url",
            )
            handle_file_icon_click(grid_response, visible_transactions)

            editor_state: dict[str, Any] = {
                "edited_rows": collect_grid_changes(grid_table, grid_response),
                "deleted_rows": [],
            }
            selected_positions = get_selected_positions(grid_response, grid_table)
            st.session_state[SESSION_KEY_LAST_SELECTED_IDS] = [int(transaction_ids[n]) for n in selected_positions]
            with action_bar:
                # Toolbar แบบ space-between: ซ้าย = ปุ่มลบ | กลาง = ช่องว่างดัน | ขวา = กล่องรวมปุ่ม Export
                # ถ้าจะเพิ่มปุ่มจัดการข้อมูลให้ใส่ใน col_left ถ้าเพิ่มปุ่มส่งออกให้เพิ่มจำนวนใน st.columns ของ col_right
                # สัดส่วน [2.5, 6, 3.5]: ช่องกลางกว้างสุดทำหน้าที่เป็นสปริงดันปุ่มไปชิดขอบ (ปรับได้เช่น [2, 7, 3])
                col_left, _col_spacer, col_right = st.columns([2.5, 6, 3.5], vertical_alignment="center")
                with col_right:
                    # กล่องห่อฝั่งขวา: แบ่งเป็น 2 กล่องย่อยเท่ากัน ระยะห่างแคบ (gap="small") สำหรับ CSV และ Excel
                    csv_column, excel_column = st.columns(2, gap="small", vertical_alignment="center")
                col_left.button(
                    f"🗑️ ลบรายการที่เลือก ({len(selected_positions)})",
                    key="delete_selected_rows",
                    disabled=not selected_positions,
                    help="ติ๊กช่องหน้าแถวที่ต้องการลบ แล้วกดปุ่มนี้",
                    use_container_width=True,
                    on_click=request_delete_selected,  # จำแถวที่เลือก -> รอบถัดไปเล่น animation ลบ แล้วค่อยลบจริง
                )
                # ส่งออกข้อมูลชุดเดียวกับที่แสดงในตาราง (ผ่าน Date Filter / Search / Item / Vendor แล้ว)
                # สร้างไฟล์เมื่อกดเตรียมไฟล์เท่านั้น (เดิมสร้าง CSV + Excel ทุกครั้งที่หน้ารีรัน ซึ่งช้าที่สุดของหน้านี้)
                export_file_stem = f"masterlist_{start_date.isoformat()}_{end_date.isoformat()}"
                render_export_buttons(display_table, export_file_stem, csv_column, excel_column)

            if deleting_ids:
                # แถวที่กดลบถูกส่งไปตารางพร้อม class animation แล้ว: รอให้ animation เล่นจบ ค่อยลบจริงแล้วรีรันให้แถวหายไป
                time.sleep(ROW_FX_DELETE_MS / 1000)
                editor_state["deleted_rows"] = [
                    transaction_ids.index(transaction_id) for transaction_id in deleting_ids
                ]

            edited_rows = editor_state["edited_rows"]
            edit_signature = repr(sorted(edited_rows.items())) if edited_rows else ""
            # การแก้ไขชุดเดิมซ้ำอีกรอบ = ค่าเก่าที่ตารางส่งค้าง (เช่น สถานะที่ระบบไม่ยอมให้เปลี่ยน หรือมีคนอื่นแก้ฐานข้อมูลทับไปแล้ว)
            # ไม่บันทึกซ้ำ (กันรีรันวนและกันเขียนทับข้อมูลใหม่) แต่ให้วาดตารางใหม่เพื่อล้างค่าค้าง
            is_stale_edit = bool(edit_signature) and edit_signature == st.session_state.get(
                SESSION_KEY_LAST_EDIT_SIGNATURE
            )
            if is_stale_edit:
                st.session_state[SESSION_KEY_LAST_EDIT_SIGNATURE] = ""
                st.session_state[SESSION_KEY_EDITOR_VERSION] = editor_version + 1
                st.rerun()

            if edited_rows or editor_state["deleted_rows"]:
                if edit_signature:
                    st.session_state[SESSION_KEY_LAST_EDIT_SIGNATURE] = edit_signature
                try:
                    status_messages = apply_table_edits(display_table, transaction_ids, editor_state)
                except (ValueError, TypeError, KeyError, IndexError, AttributeError) as error:
                    # error ของแถวเดี่ยว ๆ apply_table_edits จัดการเองแล้ว ที่หลุดมาถึงนี่คือข้อมูลตารางผิดรูปแบบทั้งก้อน
                    logger.error("บันทึกการแก้ไขตารางไม่สำเร็จ: %s", error, exc_info=True)
                    status_messages = [("error", f"❌ บันทึกการเปลี่ยนแปลงไม่สำเร็จ: ลองรีเฟรชหน้าเว็บ รายละเอียด: {error}")]
                st.session_state[SESSION_KEY_STATUS_MESSAGES] = status_messages
                if any(level != "success" for level, _text in status_messages):
                    # มีการแก้ที่ไม่ผ่าน/ถูกปฏิเสธ: ค่าที่ผู้ใช้เห็นในตารางไม่ตรงฐานข้อมูล ต้องวาดตารางใหม่เพื่อให้กลับมาตรงกัน
                    st.session_state[SESSION_KEY_EDITOR_VERSION] = editor_version + 1
                # บันทึกลง SQLite เสร็จแล้ว -> รีรันทั้งหน้า เพื่อให้แถบแจ้งเตือน Overdue (render_overdue_alert)
                # และตัวเลขสรุปต่าง ๆ query ค่าล่าสุดจากฐานข้อมูลใหม่ (ตาราง key เดิม จึงอัปเดตแถวที่เปลี่ยนโดยไม่กระพริบ)
                st.rerun()


def render_export_buttons(
    display_table: pd.DataFrame, export_file_stem: str, csv_column: Any, excel_column: Any
) -> None:
    """วาดปุ่ม Export CSV / Excel: สร้างไฟล์ตอนผู้ใช้กดปุ่มเท่านั้น (ไม่สร้างทุกครั้งที่หน้ารีรัน)

    ส่งฟังก์ชันให้ download_button แทนไบต์ของไฟล์ Streamlit จะเรียกฟังก์ชันเมื่อกดดาวน์โหลด (บน thread แยก ไม่บล็อกหน้า)
    เดิมสร้าง CSV + Excel (openpyxl) ทุกรอบที่รีรัน ซึ่งเป็นงานที่ช้าที่สุดของหน้านี้

    Args:
        display_table: ตารางที่แสดง (ผ่านตัวกรองแล้ว) ที่จะส่งออก
        export_file_stem: ชื่อไฟล์ (ไม่รวมนามสกุล)
        csv_column: คอลัมน์ที่วางปุ่ม CSV
        excel_column: คอลัมน์ที่วางปุ่ม Excel
    """
    csv_column.download_button(
        "⬇️ Export CSV",
        data=lambda: convert_table_to_csv_bytes(display_table) or b"",
        file_name=f"{export_file_stem}.csv",
        mime="text/csv",
        key="export_csv_button",
        use_container_width=True,
    )
    excel_column.download_button(
        "⬇️ Export Excel",
        data=lambda: convert_table_to_excel_bytes(display_table) or b"",
        file_name=f"{export_file_stem}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="export_excel_button",
        use_container_width=True,
    )


# ---------------------------------------------------------------------------
# ส่วนที่ 2: การ์ด Upload File (กล่องลากไฟล์ 2 ช่อง)
# ---------------------------------------------------------------------------


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


def _merge_extracted_fields(extracted_list: list[ExtractedFields]) -> ExtractedFields:
    """รวมผลดึงข้อมูลจากหลายไฟล์: แต่ละฟิลด์ใช้ค่าแรกที่ไม่ว่างจากไฟล์ที่เรียงมา (ไฟล์ก่อนหน้าสำคัญกว่า)"""
    merged = ExtractedFields()
    for extracted in extracted_list:
        for field_name in merged.__dataclass_fields__:
            if not getattr(merged, field_name):
                setattr(merged, field_name, getattr(extracted, field_name))
    return merged


def is_pr_document(file_name: str) -> bool:
    """ไฟล์นี้เป็นไฟล์ PR ที่ระบบอ่านข้อมูลได้หรือไม่: ชื่อขึ้นต้นด้วย PR และนามสกุลเป็น .pdf / .xlsx"""
    lowered_name = (file_name or "").strip().lower()
    return lowered_name.startswith(PR_FILE_NAME_PREFIX) and lowered_name.endswith(AUTO_EXTRACT_EXTENSIONS)


def clean_pr_file_name(file_name: str) -> str:
    """ตัดนามสกุล วันที่นำหน้า คำนำหน้า PR_Addin_ซื้อ และ -signed ท้ายชื่อ ออกจากชื่อไฟล์ เพื่อใช้เป็น Description

    ตัวอย่าง: "20260319 PR_Addin_ซื้อ NB Lenovo ThinkPad E14 G7-signed.pdf" -> "NB Lenovo ThinkPad E14 G7"

    Args:
        file_name: ชื่อไฟล์ที่อัปโหลด

    Returns:
        ชื่อที่ตัดแล้ว (ถ้าตัดแล้วว่างจะคืนชื่อเดิมที่ตัดแค่นามสกุล)
    """
    stem = Path((file_name or "").strip()).stem.strip()
    cleaned = re.sub(FILE_NAME_DATE_PREFIX_PATTERN, "", stem, flags=re.IGNORECASE)
    cleaned = re.sub(FILE_NAME_PR_PREFIX_PATTERN, "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(FILE_NAME_SUFFIX_PATTERN, "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip(" _-") or stem


def parse_date_from_file_name(file_name: str) -> Optional[date]:
    """อ่านวันที่ 8 หลักนำหน้าชื่อไฟล์ (YYYYMMDD เช่น "20260319_PR_...") คืน None ถ้าไม่มี/ไม่ใช่วันที่จริง

    ปี พ.ศ. (มากกว่า 2400) แปลงเป็น ค.ศ. ให้อัตโนมัติ
    """
    match = re.match(r"^\s*(\d{4})(\d{2})(\d{2})(?!\d)", file_name or "")
    if not match:
        return None
    year, month, day = (int(part) for part in match.groups())
    if year > 2400:
        year -= 543
    try:
        return date(year, month, day)
    except ValueError:
        return None


def find_pr_date_in_file_names(file_names: list[str]) -> Optional[date]:
    """หาวันที่ของไฟล์ PR จากวันที่ 8 หลักนำหน้าชื่อไฟล์ (เช่น "20260319_PR_...") คืน None ถ้าไม่มีไฟล์ไหนมี

    ดูทุกไฟล์ที่วาง (ชื่อไม่จำเป็นต้องขึ้นต้นด้วย PR) โดยให้ไฟล์ที่มีคำว่า PR มาก่อน
    ข้ามชื่อที่ขึ้นต้นด้วยเลขเวลาอัปโหลดที่ระบบเติม (เช่น "20261028_134912_664797_") เพราะไม่ใช่วันที่ของ PR
    """
    candidates = [name for name in file_names if not re.match(UPLOAD_STAMP_FILE_NAME_PATTERN, name or "")]
    candidates.sort(key=lambda name: "pr" not in name.lower())  # sort เสถียร: ไฟล์ PR ก่อน ลำดับเดิมคงไว้
    return next((parsed for parsed in map(parse_date_from_file_name, candidates) if parsed), None)


def build_record_from_documents(
    documents: list[UploadedFile], category: str, invoice_choice: str
) -> tuple[RecordFields, str]:
    """Extract ข้อมูลจากไฟล์ PR ที่วาง (ชื่อขึ้นต้น PR นามสกุล .pdf/.xlsx) แล้วประกอบเป็นรายการพร้อมบันทึก

    ไฟล์อื่นที่วางมาด้วยไม่ถูกอ่านข้อมูล แต่ยังถูกแนบและเก็บไว้ในโฟลเดอร์เดียวกัน (ดู submit_record)

    Args:
        documents: ไฟล์ที่วาง (ไฟล์ที่ไม่ใช่ PR ถูกแนบอย่างเดียว)
        category: หมวดหมู่จากขั้นที่ 1
        invoice_choice: สถานะใบกำกับภาษีจากขั้นที่ 1

    Returns:
        (รายการ, ข้อความเตือนถ้ามีฟิลด์ที่ดึงไม่ได้ — ว่างถ้าได้ครบ)
    """
    readable = [document for document in documents if is_pr_document(document.name)]
    extracted = _merge_extracted_fields([extract_fields_from_file(document, document.name) for document in readable])
    warning = (
        extracted.warning_message
        if readable
        else "ไม่พบไฟล์ PR (ชื่อขึ้นต้นด้วย PR นามสกุล .pdf หรือ .xlsx) จึงไม่ได้อ่านข้อมูล เก็บไฟล์ไว้ในโฟลเดอร์ Unknown"
    )

    # พบใบกำกับภาษีในไฟล์ -> ตั้งสถานะเป็น Completed ให้เอง
    if extracted.has_tax_invoice:
        invoice_choice = INVOICE_CHOICE_HAS
    pr_request_date = _parse_iso_date_or_none(extracted.pr_request_date)
    # คอลัมน์ Date = วันที่ของไฟล์ PR: วันที่นำหน้าชื่อไฟล์ (ทุกไฟล์ที่วาง) -> วันที่ในเนื้อไฟล์ -> (ไม่พบเลย) วันที่อัปโหลด
    # วันที่ Upload จริงเก็บแยกใน created_at อัตโนมัติ (ใช้นับวันค้างของแถบแจ้งเตือน)
    pr_file_date = (
        find_pr_date_in_file_names([document.name for document in documents]) or pr_request_date or date.today()
    )
    record = RecordFields(
        date=pr_file_date.isoformat(),
        vendor=extracted.vendor or UNKNOWN_VENDOR_FOLDER,
        total_price=float(extracted.total_amount) if extracted.total_amount else 0.0,
        tax_id=extracted.tax_id or None,
        pr_run_no=extracted.pr_run_no or None,
        category=category,
        invoice_status=INVOICE_CHOICE_TO_DB[invoice_choice],
        tel=extracted.tel or None,
        pr_request_date=pr_request_date.isoformat() if pr_request_date else None,
        qt_no=extracted.qt_no or None,
        # Description = ชื่อไฟล์ PR ที่ตัดส่วนเกินแล้ว (ไม่มีไฟล์ PR ใช้ไฟล์แรกที่แนบ / ไม่มีไฟล์เลยใช้ค่าที่อ่านจากเอกสาร)
        description=clean_pr_file_name((readable or documents)[0].name)
        if documents
        else (extracted.description or None),
        unit_price=float(extracted.unit_price) if extracted.unit_price else None,
    )
    return record, warning


def build_submit_summary(result: SubmitResult, extra_warning: str = "") -> str:
    """สรุปผลการส่งเป็นข้อความ (markdown) ต่อปลายทาง: เว็บ / ไฟล์ออนไลน์ / Master-List"""
    lines = [f"✅ บันทึกรายการเรียบร้อย (รหัสรายการ {result.transaction_id}) · แสดงบนเว็บแล้ว"]
    if result.desktop_folder:
        lines.append(f"📁 สร้างโฟลเดอร์บน Desktop แล้ว: {result.desktop_folder}")
    elif result.desktop_message:
        lines.append(f"⚠️ {result.desktop_message}")
    if result.storage_status == "ok":
        lines.append(f"☁️ ส่งไฟล์ไปที่เก็บไฟล์ออนไลน์แล้ว {len(result.storage_links)} ไฟล์")
    elif result.storage_status in ("skipped", "error"):
        lines.append(f"⚠️ {result.storage_message}")
    lines.append(
        "📤 ส่งเข้า Master-List แล้ว" if result.masterlist_sent else f"⏳ Master-List: {result.masterlist_message}"
    )
    if extra_warning:
        lines.append(f"⚠️ {extra_warning}")
    return "\n\n".join(lines)


def finish_submission(summary_message: str, form_counter: int) -> None:
    """ส่งสำเร็จ: เก็บข้อความสรุป ล้างฟอร์ม รีเซ็ตกลับขั้นที่ 1 แล้วโหลดหน้าใหม่ (หน้าต่างปิดเอง ตารางอัปเดต)"""
    st.session_state[SESSION_KEY_SUCCESS_MESSAGE] = summary_message
    st.session_state[SESSION_KEY_FORM_COUNTER] = form_counter + 1
    st.session_state[SESSION_KEY_FORM_STEP] = FORM_STEP_QUESTIONS
    st.rerun()


def render_upload_mode(form_counter: int) -> None:
    """โหมด "Upload ข้อมูล": วางไฟล์แล้วกด Upload ได้เลย ไม่มีช่องให้กรอกเพิ่ม

    ตอนกด Upload: Extract ข้อมูลจากไฟล์ -> ส่งออกไป เว็บไซต์ (ฐานข้อมูล) / ที่เก็บไฟล์ออนไลน์ / Master-List ผ่าน submit_record
    ฟิลด์ที่ดึงไม่ได้ไม่บล็อกการบันทึก (แสดงเป็นข้อความเตือนหลังส่ง)

    Args:
        form_counter: ตัวนับของฟอร์มปัจจุบัน (ทำให้กล่องวางไฟล์ว่างใหม่หลังส่งสำเร็จ)
    """
    _inject_drag_feedback_script()
    with st.container(key="upload_box_extract"):
        _render_upload_card_heading(
            "📄", "Upload P/O", "วางได้หลายไฟล์ ระบบอ่านข้อมูลเฉพาะไฟล์ PR (.pdf / .xlsx)", "เว็บไซต์ + Drive + Master-List"
        )
        documents: list[UploadedFile] = st.file_uploader(
            "Upload P/O",
            type=ALLOWED_FILE_TYPES,
            accept_multiple_files=True,
            key=_field_key("upload_files", form_counter),
            label_visibility="collapsed",
        )
    # ชิปบอกปลายทางหลังกด Upload (แสดงเสมอ)
    st.markdown(
        '<div class="upload-dest-chips"><span>🌐 เว็บไซต์</span><span>☁️ Drive</span><span>📋 Master-List</span></div>',
        unsafe_allow_html=True,
    )

    back_column, upload_column = st.columns([1, 2])
    back_column.button("⬅️ ย้อนกลับ", on_click=go_back_to_questions_step, width="stretch", key="upload_back_button")
    is_clicked = upload_column.button(
        "⬆️ Upload", type="primary", width="stretch", disabled=not documents, key="upload_submit_button"
    )
    if not is_clicked or not documents:
        return

    with st.spinner("กำลังอ่านข้อมูลและส่งออก..."):
        record, extract_warning = build_record_from_documents(
            documents,
            st.session_state.get(SESSION_KEY_ENTRY_ITEM, STEP1_ITEM_OPTIONS[0]),
            st.session_state.get(SESSION_KEY_ENTRY_HAS_INVOICE, INVOICE_CHOICE_NOT_YET),
        )
        result = submit_record(record, [(document.name, document.getvalue()) for document in documents])
    if result.transaction_id is None:
        st.error(f"❌ {result.error}")  # ไฟล์ที่วางยังอยู่ กด Upload ซ้ำได้
        return
    finish_submission(build_submit_summary(result, extract_warning), form_counter)


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


def render_entry_form(form_counter: int, show_po_uploader: bool = True, title: str = "กรอกข้อมูล") -> None:
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
        is_submitted = save_column.form_submit_button("💾 บันทึกข้อมูล", type="primary", use_container_width=True)

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

    # ไฟล์แนบจากช่อง Upload ใต้ฟอร์ม ส่งออกแบบเดียวกับหน้า Upload (เก็บในเครื่อง + ที่เก็บไฟล์ออนไลน์ + DB + Master-List)
    # ถ้าส่งไม่สำเร็จจะไม่ล้างฟอร์ม ผู้ใช้กดบันทึกซ้ำได้โดยไม่ต้องกรอกใหม่
    result = submit_record(
        RecordFields(
            # เก็บเป็น ค.ศ. รูปแบบ YYYY-MM-DD: มีไฟล์แนบที่ชื่อขึ้นต้นด้วยวันที่ PR ใช้วันที่นั้น ไม่งั้นใช้ค่าในช่อง Date
            date=(
                find_pr_date_in_file_names([document.name for document in (uploaded_po_documents or [])])
                or document_date
            ).isoformat(),
            vendor=vendor_name,
            total_price=total_price,
            tax_id=tax_id or None,
            po_no=purchase_order_number or None,
            pr_run_no=pr_run_number or None,
            category=category_name,
            invoice_status=INVOICE_CHOICE_TO_DB[invoice_choice],
            tel=tel or None,
            email=email or None,
            contact_name=contact_name or None,
            sharepoint_url=sharepoint_url or None,  # ลิงก์ที่กรอกเอง (ไม่บังคับ) มาก่อนลิงก์ที่ส่งขึ้นให้
            pr_request_date=pr_request_date.isoformat() if pr_request_date else None,
            qt_no=qt_no or None,
            description=description or None,
            unit_price=unit_price or None,  # 0 = ไม่ได้กรอก เก็บเป็น NULL
        ),
        [(document.name, document.getvalue()) for document in (uploaded_po_documents or [])],
    )
    if result.transaction_id is None:
        st.error(f"❌ {result.error}")
        return
    finish_submission(build_submit_summary(result), form_counter)


# ---------------------------------------------------------------------------
# จุดเข้าของหน้า
# ---------------------------------------------------------------------------


# width="medium" เพื่อให้ฟอร์มขั้นที่ 2 จัดเป็น 2 คอลัมน์ได้ (ถ้าแคบเกินไปเปลี่ยนเป็น "large")
@st.dialog(ADD_DATA_BUTTON_NAME, width="medium")
def render_entry_dialog(form_counter: int) -> None:
    """หน้าต่างป๊อปอัป "เพิ่มข้อมูล": ขั้นที่ 1 ถามข้อมูลเบื้องต้น ขั้นที่ 2 แท็บ [กรอก Form | Upload ข้อมูล]

    ภายในใช้ฟังก์ชันเดิมทั้งหมด (render_upload_mode / render_entry_form) ไม่เปลี่ยน Logic
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
    segments: str = "".join(f'<span class="{"on" if index <= step_number else ""}"></span>' for index in (1, 2))
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
        with st.container(key="entry_form_card"):
            render_entry_form(form_counter)
        return

    # โหมด "Upload ข้อมูล": วางไฟล์แล้วกด Upload ได้เลย ไม่มีฟอร์มให้กรอกเพิ่ม
    with st.container(key="upload_card"):
        render_upload_mode(form_counter)


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
    with st.container(key="equipment_summary"):
        equipment_expander = st.expander("Quantity of equipment", expanded=False, on_change="rerun")
        if equipment_expander.open:
            with equipment_expander:
                # ตารางเป็น HTML ที่ประกอบเอง (สไตล์/แอนิเมชันอยู่ใน PAGE_CSS_RULES ข้อ eq-*)
                st.markdown(
                    build_equipment_cards_html(get_equipment_quantities(start_date, end_date)),
                    unsafe_allow_html=True,
                )


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
