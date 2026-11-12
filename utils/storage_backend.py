"""ตัวกลางส่งไฟล์ไปที่เก็บไฟล์ออนไลน์ (Power Automate -> SharePoint / Google Drive) ตามโครงโฟลเดอร์ /ปี/เดือน/วัน/ชื่อไฟล์ PR/

เลือกปลายทางด้วย STORAGE_BACKEND ใน .env: "powerautomate" (ส่งขึ้น SharePoint ผ่าน Flow) หรือ "gdrive" (ค่าเริ่มต้น)
ไฟล์นี้ไม่เรียก Streamlit: ถ้าผิดพลาดจะ raise StorageError พร้อมข้อความภาษาไทย
"""

import re
from datetime import datetime
from typing import Optional

from config.settings import get_env_text
from utils.gdrive_api import GDriveError, is_gdrive_configured, upload_documents_to_gdrive
from utils.power_automate_api import PowerAutomateError, is_power_automate_configured, upload_file_to_flow

BACKEND_GDRIVE: str = "gdrive"
BACKEND_POWER_AUTOMATE: str = "powerautomate"  # ส่งผ่าน Power Automate ไปที่ SharePoint
UNKNOWN_VENDOR_FOLDER: str = "Unknown"  # ใช้เมื่อไม่รู้ชื่อ Vendor
MAX_FOLDER_NAME_LENGTH: int = 80


class StorageError(Exception):
    """ข้อผิดพลาดการส่งไฟล์ไปที่เก็บไฟล์ออนไลน์ (ข้อความเป็นภาษาไทย แสดงให้ผู้ใช้ได้เลย)

    ถ้าล้มกลางชุด uploaded_links/folder_url คือของไฟล์ที่ส่งสำเร็จไปแล้ว (ไม่ให้หายไปกับ error)
    """

    def __init__(self, message: str, uploaded_links: Optional[list[str]] = None, folder_url: Optional[str] = None) -> None:
        super().__init__(message)
        self.uploaded_links: list[str] = list(uploaded_links or [])
        self.folder_url: Optional[str] = folder_url


def get_active_backend() -> str:
    """ปลายทางที่ใช้อยู่ตาม STORAGE_BACKEND (ไม่สนตัวพิมพ์ และ - _ ช่องว่าง เช่น "Power-Automate"; ค่าที่ไม่รู้จักใช้ gdrive)"""
    backend = re.sub(r"[-_\s]", "", get_env_text("STORAGE_BACKEND", BACKEND_GDRIVE).lower())
    if backend == BACKEND_POWER_AUTOMATE:
        return backend
    return BACKEND_GDRIVE


def is_storage_configured() -> bool:
    """ตั้งค่าปลายทางที่ใช้อยู่ครบหรือยัง (ยังไม่ครบ = ข้ามการส่งไฟล์ออนไลน์ ไม่ถือเป็น error)"""
    if get_active_backend() == BACKEND_POWER_AUTOMATE:
        return is_power_automate_configured()
    return is_gdrive_configured()


# อักขระต้องห้ามของ SharePoint/OneDrive ชุดเข้ม: \ / : * ? " < > | + # % ~ { } + อักขระควบคุม
# (# % ~ { } SharePoint Online ปัจจุบันยอมได้ แต่ตัดไว้ก่อนเพื่อความปลอดภัยกับ tenant ที่ยังไม่รองรับ)
UNSAFE_FOLDER_CHARS: re.Pattern[str] = re.compile(r'[\\/:*?"<>|#%~{}\x00-\x1f]')
# ชื่อสงวน (ไม่สนตัวพิมพ์): .lock CON PRN AUX NUL COM0-9 LPT0-9 desktop.ini และ _vti_ ที่ใดก็ได้ในชื่อ
# อ้างอิง: https://support.microsoft.com/en-us/office/invalid-file-names-and-file-types-in-onedrive-and-sharepoint-64883a5d-228e-48f5-b3d2-eb39e07630fa
RESERVED_FOLDER_NAME_PATTERN: re.Pattern[str] = re.compile(
    r"^(?:\.lock|con|prn|aux|nul|com\d|lpt\d|desktop\.ini|forms)$", re.IGNORECASE
)
VTI_PATTERN: re.Pattern[str] = re.compile(r"_vti_", re.IGNORECASE)


def sanitize_folder_name(name: str) -> str:
    """ทำชื่อโฟลเดอร์ให้ปลอดภัยตามกฎ SharePoint: ตัดอักขระต้องห้าม / ช่องว่างซ้ำ / จุดท้ายชื่อ (ภาษาไทยใช้ได้)

    ชื่อสงวน (CON, .lock, desktop.ini, forms ฯลฯ) ต่อ "_" ท้ายชื่อ, "_vti_" และ "~" (รวม "~$") ถูกแทนด้วย "_" ชื่อว่าง -> Unknown
    """
    cleaned = UNSAFE_FOLDER_CHARS.sub("_", name or "")
    cleaned = VTI_PATTERN.sub("_", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    cleaned = cleaned[:MAX_FOLDER_NAME_LENGTH].strip(" .")
    if cleaned and RESERVED_FOLDER_NAME_PATTERN.match(cleaned):
        cleaned = f"{cleaned}_"
    return cleaned or UNKNOWN_VENDOR_FOLDER


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


LEADING_PR_PATTERN: re.Pattern[str] = re.compile(r"^PR(?![A-Za-z0-9])", re.IGNORECASE)
PR_FALLBACK_NAME: str = "PR"
MIN_FILE_DATE_YEAR: int = 2000
MAX_FILE_DATE_YEAR: int = 2100


def _parse_leading_date(stem: str) -> Optional[datetime]:
    """วันที่ 8 หลักนำหน้าชื่อ (YYYYMMDD) ที่เป็นวันที่จริงและปีอยู่ในช่วง 2000-2100 ไม่ใช่วันที่จริงคืน None"""
    match = re.match(r"\d{8}(?!\d)", stem)
    if not match:
        return None
    try:
        parsed = datetime.strptime(match.group(0), "%Y%m%d")
    except ValueError:
        return None
    return parsed if MIN_FILE_DATE_YEAR <= parsed.year <= MAX_FILE_DATE_YEAR else None


def parse_leading_date(file_name: str) -> Optional[datetime]:
    """วันที่จริงที่นำหน้าชื่อไฟล์ (ข้ามคำนำหน้าเวลาอัปโหลดของระบบ) ไม่มีหรือไม่ใช่วันที่จริงคืน None"""
    return _parse_leading_date(UPLOAD_STAMP_PATTERN.sub("", file_name.strip()))


def _split_pr_file_name(file_name: str) -> tuple[Optional[datetime], str]:
    """แยกชื่อไฟล์เป็น (วันที่นำหน้าที่เป็นวันที่จริง, ชื่อที่ตัดนามสกุล/เวลาอัปโหลด/วันที่/-signed_N/คำว่า PR ต้นชื่อ)

    PR ตัดเฉพาะที่อยู่ต้นชื่อ (ถัดจากวันที่) ไม่ตัด PR กลางชื่อ ชื่อว่างหลังตัด PR จริง ๆ ใช้ "PR"
    """
    stem = file_name.rsplit(".", 1)[0] if "." in file_name else file_name
    stem = SIGNED_SUFFIX_PATTERN.sub("", UPLOAD_STAMP_PATTERN.sub("", stem))
    found_date = _parse_leading_date(stem)
    if found_date:
        stem = stem[8:]
    stem = stem.lstrip(EDGE_SEPARATORS)
    stem, removed_pr = LEADING_PR_PATTERN.subn("", stem)
    stem = re.sub(r"[-_ ]*_[-_ ]*", "_", stem).strip(EDGE_SEPARATORS)
    return found_date, (stem or (PR_FALLBACK_NAME if removed_pr else ""))


def _choose_folder_source_file(file_names: list[str]) -> Optional[str]:
    """ไฟล์ที่ใช้ตั้งชื่อโฟลเดอร์: ไฟล์ -signed > ไฟล์ PR ที่ไม่มีเลขเวลาอัปโหลดนำหน้า > ไฟล์ PR > ไฟล์แรก"""
    names = [name.strip() for name in file_names if name and name.strip()]
    if not names:
        return None
    candidates = (
        [name for name in names if SIGNED_SUFFIX_PATTERN.search(name.rsplit(".", 1)[0])],
        [name for name in names if PR_TOKEN_PATTERN.search(name) and not UPLOAD_STAMP_PATTERN.match(name)],
        [name for name in names if PR_TOKEN_PATTERN.search(name)],
        names,
    )
    return next(group for group in candidates if group)[0]


def build_folder_name_from_files(file_names: list[str]) -> str:
    """ชื่อโฟลเดอร์ชั้นสุดท้ายจากชื่อไฟล์ PR เท่านั้น (ไม่อิงข้อมูลในตาราง): ตัดนามสกุล, "-signed_N" และ "PR" ต้นชื่อ

    ตัวอย่าง: "20260319_PR_Addin_ซื้อ_NB-signed_5.pdf" -> "20260319_Addin_ซื้อ_NB" (วันที่จริงที่นำหน้าคงไว้ครั้งเดียว)
    ลำดับเลือกไฟล์ดู _choose_folder_source_file ไม่มีไฟล์เลยได้ Unknown
    """
    chosen = _choose_folder_source_file(file_names)
    if chosen is None:
        return UNKNOWN_VENDOR_FOLDER
    found_date, name = _split_pr_file_name(chosen)
    prefix = f"{found_date:%Y%m%d}" if found_date else ""
    return sanitize_folder_name("_".join(part for part in (prefix, name) if part))


def resolve_folder_date_and_name(when: datetime, file_names: list[str]) -> tuple[datetime, str]:
    """(วันที่ที่ใช้, ชื่อโฟลเดอร์ชั้นสุดท้าย YYYYMMDD_<ชื่อ>) วันที่มาจากชื่อไฟล์ที่ใช้ตั้งชื่อถ้าเป็นวันที่จริง ไม่มีใช้ when"""
    chosen = _choose_folder_source_file(file_names)
    found_date, name = _split_pr_file_name(chosen) if chosen else (None, "")
    used = found_date or when
    prefix = f"{used.year:04d}{used.month:02d}{used.day:02d}"
    return used, sanitize_folder_name(f"{prefix}_{name}" if name else prefix)


def build_dated_folder_name(when: datetime, file_names: list[str]) -> str:
    """ชื่อโฟลเดอร์แบบมีวันที่นำหน้า เช่น "20260319_Addin_ซื้อ_NB" (วันที่จริงในชื่อไฟล์ก่อน ไม่มีใช้ when)

    Args:
        when: วันที่สำรองเมื่อชื่อไฟล์ไม่มีวันที่นำหน้า
        file_names: ชื่อไฟล์ที่ใช้ตั้งชื่อโฟลเดอร์
    """
    return resolve_folder_date_and_name(when, file_names)[1]


def build_storage_folder_parts(when: datetime, folder_name: str) -> list[str]:
    """โครงโฟลเดอร์ ปี/เดือน/วัน/ชื่อไฟล์ PR เช่น ["2026", "Oct", "28", "20260319_Addin_ซื้อ_NB"] (when = วันที่ของ PR ที่ผู้เรียกส่งมา ไม่ใช่วันอัปโหลด)"""
    return [
        f"{when.year:04d}",
        MONTH_ABBREVIATIONS[when.month - 1],
        f"{when.day:02d}",
        sanitize_folder_name(folder_name),
    ]


def build_storage_path(when: datetime, file_names: list[str], pr_no: Optional[str] = None) -> list[str]:
    """จุดเดียวที่คำนวณโครงโฟลเดอร์ ปี/เดือน/วัน/YYYYMMDD_ชื่อ ใช้ทั้งเก็บในเครื่อง, Desktop export และส่ง Power Automate

    ถ้าชุดไฟล์ไม่มีไฟล์ PR (ไม่มีคำว่า PR หรือ -signed) และมี pr_no ใช้ YYYYMMDD_<pr_no> แทน
    Args:
        when: วันที่ของ PR (ไม่ใช่วันอัปโหลด)
        file_names: ชื่อไฟล์ที่อัปโหลด
        pr_no: เลข PR ของแถว (สำรอง)
    """
    has_pr_file = any(
        PR_TOKEN_PATTERN.search(name) or SIGNED_SUFFIX_PATTERN.search(name.rsplit(".", 1)[0]) for name in file_names
    )
    if has_pr_file or pr_no is None:  # pr_no=None = ผู้เรียกไม่ใช้ fallback เลข PR
        when, folder_name = resolve_folder_date_and_name(when, file_names)
    else:
        number = pr_no.strip()
        folder_name = sanitize_folder_name(f"{when:%Y%m%d}_{number}" if number else f"{when:%Y%m%d}")
    return build_storage_folder_parts(when, folder_name)


def _upload_to_power_automate(files: list[tuple[str, bytes]], folder_parts: list[str]) -> tuple[list[str], Optional[str]]:
    """ส่งทีละไฟล์ตามลำดับ หยุดที่ไฟล์แรกที่ล้มเหลว (ข้อความบอกชื่อไฟล์) คืน (ลิงก์ไฟล์, ลิงก์โฟลเดอร์ที่ Flow ตอบ)"""
    links: list[str] = []
    folder_url: Optional[str] = None
    for index, (name, data) in enumerate(files):
        try:
            uploaded = upload_file_to_flow(name, data, folder_parts)
        except PowerAutomateError as error:
            sent = f" (ส่งสำเร็จแล้ว {len(links)} ไฟล์ก่อนหน้า)" if links else ""
            summary = (
                f" ส่งแล้ว: {', '.join(n for n, _ in files[:index])}." if index else ""
            ) + f" ยังไม่ได้ส่ง: {', '.join(n for n, _ in files[index:])}. ตรวจใน SharePoint ก่อนส่งซ้ำ เพื่อไม่ให้ไฟล์ซ้ำ"
            raise StorageError(
                f"ส่งไฟล์ '{name}' ไม่สำเร็จ{sent}: {error}{summary}", uploaded_links=links, folder_url=folder_url
            ) from error
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
    return upload_files_to_storage(files, folder_parts), None  # Google Drive ไม่มีลิงก์โฟลเดอร์แยก


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
        return upload_documents_to_gdrive(files, folder_parts)
    except GDriveError as error:
        raise StorageError(str(error)) from error
