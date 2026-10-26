"""เชื่อมต่อ SharePoint: อัปโหลดไฟล์เอกสาร (PR/PO/ใบกำกับภาษี) แล้วคืนลิงก์ของไฟล์

*** เตรียมไว้สำหรับเชื่อมต่อในอนาคต *** ตอนนี้ระบบยังไม่เรียกใช้ไฟล์นี้ (ปิดการเรียกใช้ใน pages_ui/overview.py)
ระหว่างนี้ไฟล์ถูกเก็บในโฟลเดอร์ data/local_uploads/ ผ่าน utils/local_storage.py แทน

ตั้งค่าผ่านไฟล์ .env (ห้ามใส่รหัสผ่านในโค้ด และ .env ถูกกันไม่ให้ขึ้น Git แล้ว):
    SHAREPOINT_URL            เช่น https://yourcompany.sharepoint.com/sites/IT
    SHAREPOINT_CLIENT_ID      Client ID ของ App ที่ลงทะเบียนไว้
    SHAREPOINT_CLIENT_SECRET  Client Secret ของ App
    SHAREPOINT_FOLDER_PATH    (ไม่บังคับ) โฟลเดอร์ปลายทาง ค่าเริ่มต้น "Shared Documents/PR-PO"
ดูตัวอย่างที่ .env.example

หมายเหตุ: ไลบรารีนี้ไม่เรียก Streamlit เลย (ไม่มี st.error ในไฟล์นี้) ถ้าผิดพลาดจะ raise SharePointError
พร้อมข้อความภาษาไทย ให้หน้า UI เป็นคนแสดงผลเอง
"""

import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlparse

from config.logging_setup import get_logger
from config.settings import DEFAULT_SHAREPOINT_FOLDER_PATH, get_env_text

# บันทึกลง logs/app.log (ห้ามเขียน Client Secret / รหัสผ่านลง Log)
logger = get_logger(__name__)

# ชื่อตัวแปรใน .env ที่ "ต้องมี" (ถ้าจะเพิ่มตัวแปรบังคับใหม่ ให้เพิ่มที่นี่และใน .env.example)
# การโหลดไฟล์ .env ทำใน config/settings.py แล้ว
REQUIRED_SETTING_NAMES: tuple[str, ...] = (
    "SHAREPOINT_URL",
    "SHAREPOINT_CLIENT_ID",
    "SHAREPOINT_CLIENT_SECRET",
)
# โฟลเดอร์ปลายทางเริ่มต้น (ใช้เมื่อไม่ใส่ SHAREPOINT_FOLDER_PATH ใน .env)
DEFAULT_FOLDER_PATH: str = DEFAULT_SHAREPOINT_FOLDER_PATH


class SharePointError(Exception):
    """ข้อผิดพลาดการเชื่อมต่อ/อัปโหลด SharePoint (ข้อความเป็นภาษาไทย พร้อมวิธีแก้ แสดงให้ผู้ใช้ได้เลย)"""


def load_sharepoint_settings() -> dict[str, str]:
    """อ่านค่าตั้งค่า SharePoint จากตัวแปรสภาพแวดล้อม (.env)

    Returns:
        dict ของค่าตั้งค่า: site_url, client_id, client_secret, folder_path

    Raises:
        SharePointError: ถ้าขาดค่าที่จำเป็น
    """
    missing_names = [name for name in REQUIRED_SETTING_NAMES if not get_env_text(name)]
    if missing_names:
        logger.warning("ตั้งค่า SharePoint ไม่ครบ ขาด: %s", ", ".join(missing_names))
        raise SharePointError(
            "ยังไม่ได้ตั้งค่า SharePoint: ไม่พบ " + ", ".join(missing_names)
            + " ในไฟล์ .env — คัดลอก .env.example เป็น .env แล้วกรอกค่าจริง จากนั้นรีสตาร์ทแอป"
        )

    # SHAREPOINT_FOLDER_PATH ไม่บังคับ: ไม่ใส่ (หรือใส่แต่ "/") จะใช้โฟลเดอร์เริ่มต้น
    folder_path = get_env_text("SHAREPOINT_FOLDER_PATH", DEFAULT_FOLDER_PATH).strip("/") or DEFAULT_FOLDER_PATH
    return {
        "site_url": get_env_text("SHAREPOINT_URL").rstrip("/"),
        "client_id": get_env_text("SHAREPOINT_CLIENT_ID"),
        "client_secret": get_env_text("SHAREPOINT_CLIENT_SECRET"),
        "folder_path": folder_path,
    }


def is_sharepoint_configured() -> bool:
    """เช็คว่าตั้งค่า SharePoint ใน .env ครบหรือยัง (ไม่โยน Error ใช้เช็คก่อนเปิดฟีเจอร์ได้)

    Returns:
        True ถ้ามีค่าที่จำเป็นครบทุกตัวใน REQUIRED_SETTING_NAMES
    """
    return all(get_env_text(name) for name in REQUIRED_SETTING_NAMES)


def build_safe_file_name(file_name: str) -> str:
    """สร้างชื่อไฟล์ที่ปลอดภัยสำหรับ SharePoint และไม่ซ้ำกัน (ใส่เวลานำหน้า)

    Args:
        file_name: ชื่อไฟล์เดิมจากผู้ใช้

    Returns:
        ชื่อไฟล์ใหม่ เช่น "20260101_093000_PO_1001.pdf"
    """
    # ตัดส่วน path ออก และแทนอักขระที่ SharePoint ไม่รองรับ/แปลกๆ ด้วย _ (ภาษาไทยยังใช้ได้)
    cleaned_name = re.sub(r"[^\w.\-]", "_", Path(file_name).name) or "document"
    return f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{cleaned_name}"


def build_file_url(site_url: str, folder_path: str, stored_file_name: str) -> str:
    """ประกอบลิงก์เปิดไฟล์บน SharePoint (ใช้เป็นค่าใน sharepoint_url ของฐานข้อมูล)

    Args:
        site_url: URL ของ Site เช่น https://x.sharepoint.com/sites/IT
        folder_path: โฟลเดอร์ปลายทาง เช่น "Shared Documents/PR-PO"
        stored_file_name: ชื่อไฟล์ที่เก็บบน SharePoint

    Returns:
        URL เต็มของไฟล์ (เข้ารหัสอักขระพิเศษแล้ว)
    """
    parsed_site = urlparse(site_url)
    site_path = parsed_site.path.rstrip("/")
    return f"{parsed_site.scheme}://{parsed_site.netloc}{quote(f'{site_path}/{folder_path}/{stored_file_name}')}"


def upload_document_to_sharepoint(file_bytes: bytes, file_name: str) -> str:
    """อัปโหลดไฟล์ขึ้น SharePoint แล้วคืนลิงก์ของไฟล์

    Args:
        file_bytes: เนื้อไฟล์ (bytes)
        file_name: ชื่อไฟล์ (ระบบจะใส่เวลานำหน้าให้เพื่อกันชื่อซ้ำ)

    Returns:
        URL ของไฟล์บน SharePoint

    Raises:
        SharePointError: ตั้งค่าไม่ครบ / ไฟล์ว่าง / เชื่อมต่อหรืออัปโหลดไม่สำเร็จ (ข้อความไทยพร้อมวิธีแก้)
    """
    if not file_bytes:
        logger.warning("อัปโหลดไม่สำเร็จ: ไฟล์ '%s' ว่างเปล่า", file_name)
        raise SharePointError("ไฟล์ที่เลือกว่างเปล่า (0 ไบต์): เลือกไฟล์ใหม่แล้วลองอีกครั้ง")

    settings = load_sharepoint_settings()
    stored_file_name = build_safe_file_name(file_name)

    try:
        # import ในฟังก์ชัน เพื่อให้แอปเปิดได้แม้ยังไม่ได้ติดตั้งไลบรารีนี้ (จะแจ้งเตือนตอนใช้งานจริงเท่านั้น)
        from office365.runtime.auth.client_credential import ClientCredential
        from office365.sharepoint.client_context import ClientContext
    except ImportError as error:
        logger.error("ยังไม่ได้ติดตั้งไลบรารี Office365: %s", error)
        raise SharePointError(
            "ยังไม่ได้ติดตั้งไลบรารี SharePoint: รัน pip install -r requirements.txt แล้วรีสตาร์ทแอป"
            f"\n\nรายละเอียดทางเทคนิค: {error}"
        ) from error

    try:
        # วิธีหลัก: ล็อกอินด้วย Client ID / Secret (App-only)
        client_context = ClientContext(settings["site_url"]).with_credentials(
            ClientCredential(settings["client_id"], settings["client_secret"])
        )

        # --- ตัวเลือกสำรอง (ปิดไว้): ล็อกอินด้วย Username / Password ---
        # ใช้เมื่อยังไม่มี App / Client Secret ให้ใช้ (เช่น ทีม IT ยังขอสิทธิ์ไม่ได้)
        # วิธีเปิดใช้: (1) ใส่ SHAREPOINT_USERNAME และ SHAREPOINT_PASSWORD ใน .env
        #             (2) เอา # หน้าโค้ดด้านล่างออก และใส่ # ปิดโค้ด "วิธีหลัก" ด้านบน
        #             (3) เพิ่ม UserCredential ในบรรทัด import ด้านบน:
        #                 from office365.runtime.auth.user_credential import UserCredential
        # ข้อควรระวัง: บัญชีที่เปิด MFA หรือองค์กรที่ปิด legacy auth จะล็อกอินวิธีนี้ไม่ได้
        # client_context = ClientContext(settings["site_url"]).with_credentials(
        #     UserCredential(get_env_text("SHAREPOINT_USERNAME"), get_env_text("SHAREPOINT_PASSWORD"))
        # )
        # โฟลเดอร์ปลายทางต้องมีอยู่แล้วบน SharePoint (ใช้ path แบบเทียบจาก root ของ Site)
        target_folder = client_context.web.get_folder_by_server_relative_path(settings["folder_path"])
        target_folder.upload_file(stored_file_name, file_bytes).execute_query()
    except Exception as error:  # noqa: BLE001 — ไลบรารีโยนหลายชนิด error จึงจับรวมแล้วแปลเป็นข้อความไทย
        logger.error("อัปโหลดขึ้น SharePoint ไม่สำเร็จ (โฟลเดอร์ %s): %s", settings["folder_path"], error, exc_info=True)
        raise SharePointError(
            "อัปโหลดขึ้น SharePoint ไม่สำเร็จ: ตรวจว่า (1) SHAREPOINT_URL ถูกต้อง "
            "(2) Client ID/Secret ถูกต้องและยังไม่หมดอายุ (3) App ได้สิทธิ์เขียนใน Site นี้ "
            f"(4) โฟลเดอร์ '{settings['folder_path']}' มีอยู่จริง (5) เน็ตใช้งานได้"
            f"\n\nรายละเอียดทางเทคนิค: {error}"
        ) from error

    logger.info("อัปโหลดไฟล์ '%s' ขึ้น SharePoint สำเร็จ", stored_file_name)
    return build_file_url(settings["site_url"], settings["folder_path"], stored_file_name)
