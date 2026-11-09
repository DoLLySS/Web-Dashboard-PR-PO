"""ตัวกลางส่งไฟล์ไปที่เก็บไฟล์ออนไลน์ (Google Drive / SharePoint) ตามโครงโฟลเดอร์ /ปี/เดือน/วัน/ชื่อไฟล์ PR/

เลือกปลายทางด้วย STORAGE_BACKEND ใน .env: "gdrive" (ค่าเริ่มต้น ใช้ทดสอบ), "powerautomate" หรือ "sharepoint" (แบบเดิม ใช้ไม่ได้แล้ว)
ไฟล์นี้ไม่เรียก Streamlit: ถ้าผิดพลาดจะ raise StorageError พร้อมข้อความภาษาไทย
"""

import re
from datetime import datetime
from typing import Optional

from config.settings import get_env_text
from utils.gdrive_api import GDriveError, is_gdrive_configured, upload_documents_to_gdrive
from utils.power_automate_api import PowerAutomateError, is_power_automate_configured, upload_file_to_flow
from utils.sharepoint_api import (
    SharePointError,
    get_folder_url_for,
    is_sharepoint_configured,
    upload_document_to_sharepoint,
)

BACKEND_GDRIVE: str = "gdrive"
BACKEND_SHAREPOINT: str = "sharepoint"  # แบบเดิม (Azure ACS) ใช้ไม่ได้แล้ว ดู NEXT_STEPS.md
BACKEND_POWER_AUTOMATE: str = "powerautomate"  # ส่งผ่าน Power Automate ไปที่ SharePoint
UNKNOWN_VENDOR_FOLDER: str = "Unknown"  # ใช้เมื่อไม่รู้ชื่อ Vendor
MAX_FOLDER_NAME_LENGTH: int = 80


class StorageError(Exception):
    """ข้อผิดพลาดการส่งไฟล์ไปที่เก็บไฟล์ออนไลน์ (ข้อความเป็นภาษาไทย แสดงให้ผู้ใช้ได้เลย)"""


def get_active_backend() -> str:
    """ปลายทางที่ใช้อยู่ตาม STORAGE_BACKEND (ไม่สนตัวพิมพ์ และ - _ ช่องว่าง เช่น "Power-Automate"; ค่าที่ไม่รู้จักใช้ gdrive)"""
    backend = re.sub(r"[-_\s]", "", get_env_text("STORAGE_BACKEND", BACKEND_GDRIVE).lower())
    if backend in (BACKEND_SHAREPOINT, BACKEND_POWER_AUTOMATE):
        return backend
    return BACKEND_GDRIVE


def is_storage_configured() -> bool:
    """ตั้งค่าปลายทางที่ใช้อยู่ครบหรือยัง (ยังไม่ครบ = ข้ามการส่งไฟล์ออนไลน์ ไม่ถือเป็น error)"""
    backend = get_active_backend()
    if backend == BACKEND_SHAREPOINT:
        return is_sharepoint_configured()
    if backend == BACKEND_POWER_AUTOMATE:
        return is_power_automate_configured()
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
# วันที่ 8 หลักที่ติดมานำหน้าชื่อโฟลเดอร์จากชื่อไฟล์ เช่น "20260319_Addin_ซื้อ_NB"
LEADING_DATE_PATTERN: re.Pattern[str] = re.compile(r"^\d{8}(?!\d)[-_ ]*")


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


def build_dated_folder_name(when: datetime, file_names: list[str]) -> str:
    """ชื่อโฟลเดอร์แบบมีวันที่นำหน้า เช่น "20260319_Addin_ซื้อ_NB" (วันที่จาก when ไม่ใช้วันที่ที่ติดมาจากชื่อไฟล์)

    Args:
        when: วันที่ของไฟล์ PR
        file_names: ชื่อไฟล์ที่ใช้ตั้งชื่อโฟลเดอร์ (ดู build_folder_name_from_files)
    """
    date_prefix = f"{when.year:04d}{when.month:02d}{when.day:02d}"
    name = LEADING_DATE_PATTERN.sub("", build_folder_name_from_files(file_names))
    return sanitize_folder_name(f"{date_prefix}_{name}" if name else date_prefix)


def build_storage_folder_parts(when: datetime, folder_name: str) -> list[str]:
    """โครงโฟลเดอร์ ปี/เดือน/วัน/ชื่อไฟล์ PR เช่น ["2026", "Oct", "28", "20260319_Addin_ซื้อ_NB"] (when = วันที่ของ PR ที่ผู้เรียกส่งมา ไม่ใช่วันอัปโหลด)"""
    return [
        f"{when.year:04d}",
        MONTH_ABBREVIATIONS[when.month - 1],
        f"{when.day:02d}",
        sanitize_folder_name(folder_name),
    ]


def get_storage_folder_url(folder_parts: list[str]) -> Optional[str]:
    """ลิงก์โฟลเดอร์ ปี/เดือน/วัน/ชื่อไฟล์ PR บน SharePoint แบบเดิม (ปลายทางอื่นหรือยังไม่ตั้งค่า = None)

    Power Automate ไม่ใช้ฟังก์ชันนี้ ลิงก์โฟลเดอร์มากับคำตอบของ Flow (ดู upload_files_and_folder_url)

    Raises:
        StorageError: ประกอบลิงก์ไม่ได้
    """
    if get_active_backend() != BACKEND_SHAREPOINT or not is_sharepoint_configured():
        return None
    try:
        return get_folder_url_for(folder_parts)
    except SharePointError as error:
        raise StorageError(str(error)) from error


def _upload_to_power_automate(files: list[tuple[str, bytes]], folder_parts: list[str]) -> tuple[list[str], Optional[str]]:
    """ส่งทีละไฟล์ตามลำดับ หยุดที่ไฟล์แรกที่ล้มเหลว (ข้อความบอกชื่อไฟล์) คืน (ลิงก์ไฟล์, ลิงก์โฟลเดอร์ที่ Flow ตอบ)"""
    links: list[str] = []
    folder_url: Optional[str] = None
    for name, data in files:
        try:
            uploaded = upload_file_to_flow(name, data, folder_parts)
        except PowerAutomateError as error:
            sent = f" (ส่งสำเร็จแล้ว {len(links)} ไฟล์ก่อนหน้า)" if links else ""
            raise StorageError(f"ส่งไฟล์ '{name}' ไม่สำเร็จ{sent}: {error}") from error
        links.append(uploaded.file_url)
        folder_url = folder_url or uploaded.folder_url
    return links, folder_url


def upload_files_and_folder_url(
    files: list[tuple[str, bytes]], folder_parts: list[str]
) -> tuple[list[str], Optional[str]]:
    """ส่งไฟล์ไปที่เก็บออนไลน์ แล้วคืน (ลิงก์ของแต่ละไฟล์, ลิงก์โฟลเดอร์ หรือ None ถ้าปลายทางไม่มี)

    Raises:
        StorageError: ส่งไม่สำเร็จ
    """
    if files and get_active_backend() == BACKEND_POWER_AUTOMATE:
        return _upload_to_power_automate(files, folder_parts)
    return upload_files_to_storage(files, folder_parts), get_storage_folder_url(folder_parts)


def upload_files_to_storage(files: list[tuple[str, bytes]], folder_parts: list[str]) -> list[str]:
    """ส่งไฟล์ไปที่ <root>/ปี/เดือน/วัน/ชื่อไฟล์ PR/ ของปลายทางที่เลือก แล้วคืนลิงก์ของแต่ละไฟล์

    Args:
        files: รายการ (ชื่อไฟล์, เนื้อไฟล์)
        folder_parts: โครงโฟลเดอร์ (ได้จาก build_storage_folder_parts หรือโฟลเดอร์ของรายการเดิม)

    Raises:
        StorageError: ส่งไม่สำเร็จ
    """
    if not files:
        return []
    if get_active_backend() == BACKEND_POWER_AUTOMATE:
        return _upload_to_power_automate(files, folder_parts)[0]
    try:
        if get_active_backend() == BACKEND_SHAREPOINT:
            return [upload_document_to_sharepoint(data, name, sub_folders=folder_parts) for name, data in files]
        return upload_documents_to_gdrive(files, folder_parts)
    except (GDriveError, SharePointError) as error:
        raise StorageError(str(error)) from error
