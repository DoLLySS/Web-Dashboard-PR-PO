"""ตัวกลางส่งไฟล์ไปที่เก็บไฟล์ออนไลน์ (Google Drive / SharePoint) ตามโครงโฟลเดอร์ /ปี/เดือน/วัน/ชื่อไฟล์ PR/

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
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


# ท้ายชื่อไฟล์ที่ได้จากการเซ็นเอกสาร เช่น "-signed_5", "_signed" (ไม่สนตัวพิมพ์)
SIGNED_SUFFIX_PATTERN: re.Pattern[str] = re.compile(r"[-_ ]*signed(?:[-_ ]*\d+)?$", re.IGNORECASE)
# คำว่า "PR" ที่เป็นคำเดี่ยว (คั่นด้วย _ - ช่องว่าง หรือต้น/ท้ายชื่อ) ไม่ตัด PR ที่อยู่ในคำอื่น เช่น PRINT
PR_TOKEN_PATTERN: re.Pattern[str] = re.compile(r"(?<![A-Za-z0-9])PR(?![A-Za-z0-9])", re.IGNORECASE)
EDGE_SEPARATORS: str = "-_ ."
# คำนำหน้าเวลาอัปโหลดที่ระบบเติมให้บางไฟล์ เช่น "20261028_134912_664797_" (ไม่ใช่ส่วนหนึ่งของชื่อไฟล์ PR)
UPLOAD_STAMP_PATTERN: re.Pattern[str] = re.compile(r"^\d{8}_\d{6}_\d+_")


def _strip_pr_file_name(file_name: str) -> str:
    """ตัดนามสกุล, คำนำหน้าเวลาอัปโหลด, ท้าย -signed_N และคำว่า PR ออกจากชื่อไฟล์ แล้วยุบตัวคั่นที่ซ้ำกัน"""
    stem = file_name.rsplit(".", 1)[0] if "." in file_name else file_name
    stem = UPLOAD_STAMP_PATTERN.sub("", stem)
    stem = SIGNED_SUFFIX_PATTERN.sub("", stem)
    stem = PR_TOKEN_PATTERN.sub("", stem)
    stem = re.sub(r"[-_ ]*_[-_ ]*", "_", stem)  # "__" / "_-" / "- _" ที่เกิดหลังตัดคำ -> "_" เดียว
    return stem.strip(EDGE_SEPARATORS)


def build_folder_name_from_files(file_names: list[str]) -> str:
    """ชื่อโฟลเดอร์ชั้นสุดท้ายจากชื่อไฟล์ PR เท่านั้น (ไม่อิงข้อมูลในตาราง): ใช้ชื่อไฟล์เต็ม แล้วตัดนามสกุล, "PR", "-signed_N"

    ตัวอย่าง: "20260319_PR_Addin_ซื้อ_NB-signed_5.pdf" -> "20260319_Addin_ซื้อ_NB"
    ลำดับเลือกไฟล์: ไฟล์ -signed (ไฟล์ PR ที่เซ็นแล้ว) > ไฟล์ที่มีคำว่า PR และไม่มีเลขเวลาอัปโหลดนำหน้า
    > ไฟล์ที่มีคำว่า PR > ไฟล์แรก ไม่มีไฟล์เลยได้ Unknown (ตัดแล้วว่างจะใช้ชื่อเต็มแทน)
    """
    names = [name.strip() for name in file_names if name and name.strip()]
    if not names:
        return UNKNOWN_VENDOR_FOLDER
    candidates = (
        [name for name in names if SIGNED_SUFFIX_PATTERN.search(name.rsplit(".", 1)[0])],
        [name for name in names if PR_TOKEN_PATTERN.search(name) and not UPLOAD_STAMP_PATTERN.match(name)],
        [name for name in names if PR_TOKEN_PATTERN.search(name)],
        names,
    )
    chosen = next(group for group in candidates if group)[0]
    stripped = _strip_pr_file_name(chosen)
    if not stripped:
        stripped = chosen.rsplit(".", 1)[0] if "." in chosen else chosen
    return sanitize_folder_name(stripped)


def build_storage_folder_parts(when: datetime, folder_name: str) -> list[str]:
    """โครงโฟลเดอร์ ปี/เดือน/วัน/ชื่อไฟล์ PR เช่น ["2026", "Oct", "28", "20260319_Addin_ซื้อ_NB"] (ใช้วันที่อัปโหลดจริง)"""
    return [
        f"{when.year:04d}",
        MONTH_ABBREVIATIONS[when.month - 1],
        f"{when.day:02d}",
        sanitize_folder_name(folder_name),
    ]


def get_storage_folder_url(folder_name: str, when: datetime) -> Optional[str]:
    """ลิงก์โฟลเดอร์ ปี/เดือน/วัน/ชื่อไฟล์ PR บน SharePoint (ปลายทางอื่นหรือยังไม่ตั้งค่า = None)

    Raises:
        StorageError: ประกอบลิงก์ไม่ได้
    """
    if get_active_backend() != BACKEND_SHAREPOINT or not is_sharepoint_configured():
        return None
    try:
        return get_folder_url_for(build_storage_folder_parts(when, folder_name))
    except SharePointError as error:
        raise StorageError(str(error)) from error


def upload_files_to_storage(files: list[tuple[str, bytes]], folder_name: str, when: datetime) -> list[str]:
    """ส่งไฟล์ไปที่ <root>/ปี/เดือน/วัน/ชื่อไฟล์ PR/ ของปลายทางที่เลือก แล้วคืนลิงก์ของแต่ละไฟล์

    Args:
        files: รายการ (ชื่อไฟล์, เนื้อไฟล์)
        folder_name: ชื่อโฟลเดอร์ชั้นสุดท้าย (ได้จาก build_folder_name_from_files)
        when: เวลาอัปโหลด

    Raises:
        StorageError: ส่งไม่สำเร็จ
    """
    if not files:
        return []
    parts = build_storage_folder_parts(when, folder_name)
    try:
        if get_active_backend() == BACKEND_SHAREPOINT:
            return [upload_document_to_sharepoint(data, name, sub_folders=parts) for name, data in files]
        return upload_documents_to_gdrive(files, parts)
    except (GDriveError, SharePointError) as error:
        raise StorageError(str(error)) from error
