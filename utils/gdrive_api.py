"""เชื่อมต่อ Google Drive (Service Account): อัปโหลดไฟล์เอกสารลงโฟลเดอร์ซ้อนชั้น แล้วคืนลิงก์ของไฟล์

ใช้ทดสอบแทน SharePoint ระหว่างรอสิทธิ์ ตั้งค่าผ่านไฟล์ .env (ห้ามใส่ key ในโค้ด และ .env ถูกกันไม่ให้ขึ้น Git แล้ว):
    GDRIVE_SERVICE_ACCOUNT_FILE  path ของไฟล์ JSON key ของ Service Account (ไฟล์ key ต้องอยู่นอก Git)
    GDRIVE_ROOT_FOLDER_ID        ID ของโฟลเดอร์ราก (แชร์ให้อีเมลของ Service Account แบบ Editor)

หมายเหตุ: Service Account ไม่มีพื้นที่เก็บของตัวเองใน My Drive ควรใช้โฟลเดอร์ใน Shared Drive
ไฟล์นี้ไม่เรียก Streamlit: ถ้าผิดพลาดจะ raise GDriveError พร้อมข้อความภาษาไทย (ห้ามเขียน key ลง Log)
"""

import io
import mimetypes
from pathlib import Path
from typing import Any

from config.logging_setup import get_logger
from config.settings import get_env_text

logger = get_logger(__name__)

REQUIRED_SETTING_NAMES: tuple[str, ...] = ("GDRIVE_SERVICE_ACCOUNT_FILE", "GDRIVE_ROOT_FOLDER_ID")
DRIVE_SCOPE: str = "https://www.googleapis.com/auth/drive"
FOLDER_MIME_TYPE: str = "application/vnd.google-apps.folder"


class GDriveError(Exception):
    """ข้อผิดพลาดการเชื่อมต่อ/อัปโหลด Google Drive (ข้อความเป็นภาษาไทย แสดงให้ผู้ใช้ได้เลย)"""


def is_gdrive_configured() -> bool:
    """เช็คว่าตั้งค่า Google Drive ใน .env ครบและไฟล์ key มีอยู่จริงหรือยัง (ไม่โยน Error)"""
    if not all(get_env_text(name) for name in REQUIRED_SETTING_NAMES):
        return False
    return Path(get_env_text("GDRIVE_SERVICE_ACCOUNT_FILE")).is_file()


def _escape_query_text(text: str) -> str:
    """escape ข้อความที่จะใส่ในเงื่อนไขค้นหา Drive (แทน \\ และ ' ) กัน query เพี้ยน"""
    return text.replace("\\", "\\\\").replace("'", "\\'")


def _build_drive_service() -> Any:
    """สร้าง client ของ Drive API จาก Service Account (import ในฟังก์ชัน เพื่อให้แอปเปิดได้แม้ยังไม่ติดตั้งไลบรารี)"""
    missing_names = [name for name in REQUIRED_SETTING_NAMES if not get_env_text(name)]
    if missing_names:
        raise GDriveError(
            "ยังไม่ได้ตั้งค่า Google Drive: ไม่พบ "
            + ", ".join(missing_names)
            + " ในไฟล์ .env — ดูขั้นตอนใน NEXT_STEPS.md แล้วรีสตาร์ทแอป"
        )
    key_file = Path(get_env_text("GDRIVE_SERVICE_ACCOUNT_FILE"))
    if not key_file.is_file():
        raise GDriveError("ไม่พบไฟล์ key ของ Service Account ตาม GDRIVE_SERVICE_ACCOUNT_FILE: ตรวจ path ใน .env")

    try:
        from google.oauth2.service_account import Credentials
        from googleapiclient.discovery import build
    except ImportError as error:
        raise GDriveError("ยังไม่ได้ติดตั้งไลบรารี Google Drive: รัน pip install -r requirements.txt แล้วรีสตาร์ทแอป") from error

    try:
        credentials = Credentials.from_service_account_file(str(key_file), scopes=[DRIVE_SCOPE])
        return build("drive", "v3", credentials=credentials, cache_discovery=False)
    except (ValueError, OSError) as error:
        logger.error("สร้าง client Google Drive ไม่สำเร็จ: %s", type(error).__name__)
        raise GDriveError(
            "อ่านไฟล์ key ของ Service Account ไม่ได้: ตรวจว่าเป็นไฟล์ JSON ของ Service Account ที่ถูกต้อง"
        ) from error


def _find_or_create_folder(service: Any, parent_id: str, folder_name: str) -> str:
    """หาโฟลเดอร์ชื่อนี้ใต้ parent ถ้าไม่มีให้สร้าง แล้วคืน ID ของโฟลเดอร์"""
    query = (
        f"name = '{_escape_query_text(folder_name)}' and mimeType = '{FOLDER_MIME_TYPE}' "
        f"and '{parent_id}' in parents and trashed = false"
    )
    found = (
        service.files()
        .list(q=query, fields="files(id)", pageSize=1, supportsAllDrives=True, includeItemsFromAllDrives=True)
        .execute()
    )
    existing = found.get("files", [])
    if existing:
        return existing[0]["id"]
    created = (
        service.files()
        .create(
            body={"name": folder_name, "mimeType": FOLDER_MIME_TYPE, "parents": [parent_id]},
            fields="id",
            supportsAllDrives=True,
        )
        .execute()
    )
    return created["id"]


def upload_documents_to_gdrive(files: list[tuple[str, bytes]], folder_parts: list[str]) -> list[str]:
    """อัปโหลดหลายไฟล์ลงโฟลเดอร์ <root>/<folder_parts...> (สร้างโฟลเดอร์ที่ยังไม่มีให้เอง) แล้วคืนลิงก์ของแต่ละไฟล์

    Args:
        files: รายการ (ชื่อไฟล์, เนื้อไฟล์)
        folder_parts: ชื่อโฟลเดอร์ทีละชั้น เช่น ["2026", "Oct", "28", "ABC"]

    Returns:
        ลิงก์เปิดไฟล์ (เรียงตามไฟล์ที่ส่งเข้ามา)

    Raises:
        GDriveError: ตั้งค่าไม่ครบ / ไฟล์ว่าง / เชื่อมต่อหรืออัปโหลดไม่สำเร็จ
    """
    if any(not file_bytes for _, file_bytes in files):
        raise GDriveError("มีไฟล์ว่างเปล่า (0 ไบต์): เลือกไฟล์ใหม่แล้วลองอีกครั้ง")

    service = _build_drive_service()
    try:
        from googleapiclient.errors import HttpError
        from googleapiclient.http import MediaIoBaseUpload

        folder_id = get_env_text("GDRIVE_ROOT_FOLDER_ID")
        for part in folder_parts:
            folder_id = _find_or_create_folder(service, folder_id, part)

        links: list[str] = []
        for file_name, file_bytes in files:
            mime_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
            media = MediaIoBaseUpload(io.BytesIO(file_bytes), mimetype=mime_type, resumable=False)
            created = (
                service.files()
                .create(
                    body={"name": file_name, "parents": [folder_id]},
                    media_body=media,
                    fields="id,webViewLink",
                    supportsAllDrives=True,
                )
                .execute()
            )
            links.append(created.get("webViewLink") or f"https://drive.google.com/file/d/{created['id']}/view")
    except (HttpError, OSError, KeyError) as error:
        logger.error("อัปโหลดขึ้น Google Drive ไม่สำเร็จ: %s", type(error).__name__, exc_info=True)
        raise GDriveError(
            "อัปโหลดขึ้น Google Drive ไม่สำเร็จ: ตรวจว่า (1) GDRIVE_ROOT_FOLDER_ID ถูกต้อง "
            "(2) แชร์โฟลเดอร์ให้อีเมลของ Service Account แบบ Editor แล้ว (3) ใช้โฟลเดอร์ใน Shared Drive "
            "(Service Account ไม่มีพื้นที่เก็บของตัวเอง) (4) เน็ตใช้งานได้"
            f"\n\nรายละเอียดทางเทคนิค: {error}"
        ) from error

    logger.info("อัปโหลดขึ้น Google Drive สำเร็จ %d ไฟล์ (โฟลเดอร์ %s)", len(links), "/".join(folder_parts))
    return links
