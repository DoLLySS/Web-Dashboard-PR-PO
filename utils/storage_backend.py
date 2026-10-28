"""ตัวกลางส่งไฟล์ไปที่เก็บไฟล์ออนไลน์ (Google Drive / SharePoint) ตามโครงโฟลเดอร์ /ปี/เดือน/วัน/Vendor/

เลือกปลายทางด้วย STORAGE_BACKEND ใน .env: "gdrive" (ค่าเริ่มต้น ใช้ทดสอบ) หรือ "sharepoint"
ไฟล์นี้ไม่เรียก Streamlit: ถ้าผิดพลาดจะ raise StorageError พร้อมข้อความภาษาไทย
"""

import re
from datetime import datetime
from typing import Optional

from config.settings import get_env_text
from utils.gdrive_api import GDriveError, is_gdrive_configured, upload_documents_to_gdrive
from utils.sharepoint_api import (
    SharePointError,
    get_folder_url_for,
    is_sharepoint_configured,
    upload_document_to_sharepoint,
)

BACKEND_GDRIVE: str = "gdrive"
BACKEND_SHAREPOINT: str = "sharepoint"
UNKNOWN_VENDOR_FOLDER: str = "Unknown"  # ใช้เมื่อไม่รู้ชื่อ Vendor
MAX_FOLDER_NAME_LENGTH: int = 80


class StorageError(Exception):
    """ข้อผิดพลาดการส่งไฟล์ไปที่เก็บไฟล์ออนไลน์ (ข้อความเป็นภาษาไทย แสดงให้ผู้ใช้ได้เลย)"""


def get_active_backend() -> str:
    """ปลายทางที่ใช้อยู่ตาม STORAGE_BACKEND (ค่าที่ไม่รู้จักใช้ gdrive)"""
    backend = get_env_text("STORAGE_BACKEND", BACKEND_GDRIVE).lower()
    return BACKEND_SHAREPOINT if backend == BACKEND_SHAREPOINT else BACKEND_GDRIVE


def is_storage_configured() -> bool:
    """ตั้งค่าปลายทางที่ใช้อยู่ครบหรือยัง (ยังไม่ครบ = ข้ามการส่งไฟล์ออนไลน์ ไม่ถือเป็น error)"""
    if get_active_backend() == BACKEND_SHAREPOINT:
        return is_sharepoint_configured()
    return is_gdrive_configured()


def sanitize_folder_name(name: str) -> str:
    """ทำชื่อโฟลเดอร์ให้ปลอดภัย: ตัดอักขระต้องห้าม / ช่องว่างซ้ำ / จุดท้ายชื่อ (ภาษาไทยใช้ได้) ว่าง -> Unknown"""
    cleaned = re.sub(r'[\\/:*?"<>|#%\x00-\x1f]', "_", name or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned[:MAX_FOLDER_NAME_LENGTH].strip(" .") or UNKNOWN_VENDOR_FOLDER


# ชื่อเดือนย่อภาษาอังกฤษ (ไม่ใช้ strftime("%b") เพราะขึ้นกับ locale ของเครื่อง อาจได้ชื่อไทย)
MONTH_ABBREVIATIONS: tuple[str, ...] = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


def build_storage_folder_parts(when: datetime, vendor: str) -> list[str]:
    """โครงโฟลเดอร์ ปี/เดือน/วัน/Vendor เช่น ["2026", "Oct", "28", "ABC"] (ใช้วันที่อัปโหลดจริง)"""
    return [
        f"{when.year:04d}",
        MONTH_ABBREVIATIONS[when.month - 1],
        f"{when.day:02d}",
        sanitize_folder_name(vendor),
    ]


def get_storage_folder_url(vendor: str, when: datetime) -> Optional[str]:
    """ลิงก์โฟลเดอร์ ปี/เดือน/วัน/Vendor บน SharePoint (ปลายทางอื่นหรือยังไม่ตั้งค่า = None)

    Raises:
        StorageError: ประกอบลิงก์ไม่ได้
    """
    if get_active_backend() != BACKEND_SHAREPOINT or not is_sharepoint_configured():
        return None
    try:
        return get_folder_url_for(build_storage_folder_parts(when, vendor))
    except SharePointError as error:
        raise StorageError(str(error)) from error


def upload_files_to_storage(files: list[tuple[str, bytes]], vendor: str, when: datetime) -> list[str]:
    """ส่งไฟล์ไปที่ <root>/ปี/เดือน/วัน/Vendor/ ของปลายทางที่เลือก แล้วคืนลิงก์ของแต่ละไฟล์

    Args:
        files: รายการ (ชื่อไฟล์, เนื้อไฟล์)
        vendor: ชื่อ Vendor (ใช้ตั้งชื่อโฟลเดอร์ชั้นสุดท้าย)
        when: เวลาอัปโหลด

    Raises:
        StorageError: ส่งไม่สำเร็จ
    """
    if not files:
        return []
    parts = build_storage_folder_parts(when, vendor)
    try:
        if get_active_backend() == BACKEND_SHAREPOINT:
            return [upload_document_to_sharepoint(data, name, sub_folders=parts) for name, data in files]
        return upload_documents_to_gdrive(files, parts)
    except (GDriveError, SharePointError) as error:
        raise StorageError(str(error)) from error
