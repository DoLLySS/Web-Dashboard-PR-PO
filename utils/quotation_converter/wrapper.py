"""ชั้นห่อ (wrapper) สำหรับแปลงใบเสนอราคา PDF เป็น Excel ฟอร์ม PR

ห้ามแก้ extractor.py และ excel_generator.py ในโฟลเดอร์นี้ (คัดลอกมาจาก Covert-PDF-to-Excel) ให้เพิ่มความสามารถที่ไฟล์นี้เท่านั้น
ทำงานในหน่วยความจำล้วน: ไม่เขียนไฟล์ลงดิสก์ และไม่ส่งข้อมูลไป SharePoint / Power Automate / Master-List
"""

import re
from dataclasses import dataclass
from typing import Any

import streamlit as st

from utils.quotation_converter.excel_generator import generate_pr_excel
from utils.quotation_converter.extractor import extract_pdf_data

# แคชผลอ่าน PDF ในหน่วยความจำ (หมดอายุเองและจำกัดจำนวน เพราะเนื้อหาเป็นเอกสารจริง)
CACHE_TTL_SECONDS: int = 3600
CACHE_MAX_ENTRIES: int = 8
# ขนาดไฟล์ PDF สูงสุดที่รับ
MAX_PDF_BYTES: int = 10 * 1024 * 1024


@dataclass(frozen=True)
class ConversionResult:
    """ผลการแปลง: bytes ของ .xlsx, ชื่อไฟล์ และข้อมูลที่สกัดได้"""

    excel_bytes: bytes
    file_name: str
    data: dict[str, Any]


@st.cache_data(ttl=CACHE_TTL_SECONDS, max_entries=CACHE_MAX_ENTRIES, show_spinner=False)
def load_pdf_data(pdf_bytes: bytes) -> dict[str, Any]:
    """สกัดข้อมูลจาก PDF (แคชตาม bytes ของไฟล์ เก็บในหน่วยความจำเท่านั้น)"""
    return extract_pdf_data(pdf_bytes)


def format_grand_total(data: dict[str, Any]) -> str:
    """คืนยอดรวมสุทธิเป็นข้อความ ถ้าอ่านไม่ได้คืน "-" """
    try:
        value = ((data.get("summary") or {}).get("grand_total") or {}).get("value")
        return f"{float(value):,.2f}" if value is not None else "-"
    except (TypeError, ValueError):
        return "-"


def build_file_name(data: dict[str, Any]) -> str:
    """ตั้งชื่อไฟล์ตามเลขที่ใบเสนอราคา และตัดอักขระที่ใช้เป็นชื่อไฟล์ไม่ได้ออก"""
    qt_no = str((data.get("doc_info") or {}).get("qt_no") or "").strip()
    safe_qt = re.sub(r'[\\/:*?"<>|\s]+', "_", qt_no).strip("_")
    return f"ใบเสนอราคา_{safe_qt}.xlsx" if safe_qt else "ใบเสนอราคา.xlsx"


def validate_pdf_bytes(pdf_bytes: bytes) -> None:
    """ตรวจไฟล์ก่อนอ่าน

    Raises:
        ValueError: ไฟล์ว่าง ใหญ่เกิน หรือไม่ใช่ PDF
    """
    if not pdf_bytes:
        raise ValueError("ไฟล์ว่างเปล่า")
    if len(pdf_bytes) > MAX_PDF_BYTES:
        raise ValueError(f"ไฟล์ใหญ่เกิน {MAX_PDF_BYTES // (1024 * 1024)} MB")
    if not pdf_bytes.lstrip()[:5] == b"%PDF-":
        raise ValueError("ไฟล์นี้ไม่ใช่ PDF")


def convert_pdf_to_excel(pdf_bytes: bytes) -> ConversionResult:
    """แปลง PDF ใบเสนอราคาเป็น Excel ฟอร์ม PR

    Args:
        pdf_bytes: เนื้อไฟล์ PDF

    Returns:
        ConversionResult

    Raises:
        ValueError: ไฟล์ไม่ผ่านการตรวจ อ่านข้อมูลไม่ครบ หรือสร้าง Excel ไม่สำเร็จ
    """
    validate_pdf_bytes(pdf_bytes)
    try:
        data = load_pdf_data(pdf_bytes)
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"อ่านไฟล์ PDF ไม่สำเร็จ: {exc}") from exc
    if data.get("errors"):
        raise ValueError(f"อ่านข้อมูลจาก PDF ไม่ครบ: {data['errors']}")
    excel_bytes = generate_pr_excel(data).getvalue()
    return ConversionResult(excel_bytes=excel_bytes, file_name=build_file_name(data), data=data)
