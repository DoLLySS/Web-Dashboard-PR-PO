"""เก็บไฟล์เอกสาร (PR/PO/ใบกำกับภาษี) ลงโฟลเดอร์ static/local_uploads/ ภายในโปรเจค (Streamlit เสิร์ฟให้เปิดจากตารางได้)

ใช้แทน SharePoint ชั่วคราวระหว่างรอสิทธิ์ (sharepoint_api.py ยังเก็บไว้ เตรียมต่อภายหลัง)
ไฟล์ไม่มี Streamlit: ถ้าผิดพลาดจะ raise LocalStorageError พร้อมข้อความภาษาไทย ให้หน้า UI เป็นคนแสดงผลเอง
"""

import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from config.settings import get_env_flag
from utils.storage_backend import build_storage_folder_parts

# เปิดเมื่อรันบนเครื่องของผู้ใช้เองเท่านั้น (LOCAL_DESKTOP_EXPORT=1 ใน .env): กดไอคอน File แล้วคัดลอกไฟล์ไป Desktop + เปิด Explorer
# บน Server ต้องปิด เพราะโค้ดทำงานที่เครื่อง Server ผู้ใช้จะไม่เห็นไฟล์ (ปิด = ไอคอนเปิดไฟล์ผ่านลิงก์ในเบราว์เซอร์แทน)
DESKTOP_EXPORT_ENABLED: bool = get_env_flag("LOCAL_DESKTOP_EXPORT", False)

# โฟลเดอร์เก็บไฟล์ static/local_uploads/ (ข้างไฟล์ app.py — ถ้าไม่มีจะถูกสร้างให้อัตโนมัติตอนบันทึกไฟล์แรก)
# ต้องอยู่ใต้ static/ และเปิด server.enableStaticServing ใน .streamlit/config.toml จึงเปิดไฟล์ผ่านเบราว์เซอร์ได้
UPLOAD_DIRECTORY: Path = Path(__file__).parent.parent / "static" / "local_uploads"
# ที่เก็บไฟล์รุ่นเก่า (ก่อนย้ายมา static/) แถวเก่าในฐานข้อมูลยังอ้างที่อยู่นี้
LEGACY_UPLOAD_DIRECTORY: Path = Path(__file__).parent.parent / "data" / "local_uploads"
STATIC_URL_PREFIX: str = "/app/static/local_uploads/"  # ลิงก์ที่ Streamlit เสิร์ฟ (ต้องตรงกับ UPLOAD_DIRECTORY)
FILE_PATH_SEPARATOR: str = "\n"  # ตัวคั่นเมื่อแนบหลายไฟล์ในคอลัมน์ file_path (ต้องตรงกับ submit_pipeline.py)


class LocalStorageError(Exception):
    """ข้อผิดพลาดการบันทึกไฟล์ในเครื่อง (ข้อความเป็นภาษาไทย แสดงให้ผู้ใช้ได้เลย)"""


def _pick_free_file_name(target_directory: Path, file_name: str) -> str:
    """คืนชื่อไฟล์ที่ยังไม่มีในโฟลเดอร์ (ชื่อซ้ำต่อท้าย _1, _2, ... ก่อนนามสกุล) เพื่อไม่เขียนทับไฟล์เดิม"""
    candidate = Path(file_name)
    counter = 0
    while (target_directory / file_name).exists():
        counter += 1
        file_name = f"{candidate.stem}_{counter}{candidate.suffix}"
    return file_name


def save_document_locally(file_bytes: bytes, file_name: str, sub_folders: Optional[list[str]] = None) -> str:
    """บันทึกไฟล์ลง local_uploads/<sub_folders>/ แล้วคืนที่อยู่ไฟล์ (เทียบจากโฟลเดอร์โปรเจค) เพื่อเก็บลงฐานข้อมูล

    Args:
        file_bytes: เนื้อไฟล์ (bytes)
        file_name: ชื่อไฟล์เดิม (แทนอักขระแปลกๆ ด้วย _ ชื่อซ้ำในโฟลเดอร์เดียวกันต่อท้าย _1, _2, ...)
        sub_folders: โฟลเดอร์ย่อยเรียงตามลำดับ เช่น ["2026", "Oct", "28", "ABC"] (ผู้เรียกต้องทำชื่อให้ปลอดภัยแล้ว)
            ไม่ระบุ = เก็บตรง local_uploads/

    Returns:
        ที่อยู่ไฟล์แบบ relative เช่น "static/local_uploads/2026/Oct/28/ABC/PR_1001.pdf"

    Raises:
        LocalStorageError: ไฟล์ว่าง / สร้างโฟลเดอร์หรือเขียนไฟล์ไม่ได้
    """
    if not file_bytes:
        raise LocalStorageError("ไฟล์ที่เลือกว่างเปล่า (0 ไบต์): เลือกไฟล์ใหม่แล้วลองอีกครั้ง")

    # ตัดส่วน path ออก และแทนอักขระที่ไม่ปลอดภัยด้วย _ (ภาษาไทยยังใช้ได้)
    # (฀-๿ = ตัวอักษร/สระ/วรรณยุกต์ไทย)
    cleaned_name = re.sub(r"[^\w฀-๿.\-]", "_", Path(file_name).name) or "document"
    target_directory = UPLOAD_DIRECTORY.joinpath(*(sub_folders or []))

    try:
        target_directory.mkdir(parents=True, exist_ok=True)  # สร้างโฟลเดอร์ให้เองถ้ายังไม่มี
        stored_file_name = _pick_free_file_name(target_directory, cleaned_name)
        (target_directory / stored_file_name).write_bytes(file_bytes)
    except OSError as error:
        raise LocalStorageError(
            "บันทึกไฟล์ไม่สำเร็จ: ตรวจว่าดิสก์ไม่เต็ม และโฟลเดอร์ local_uploads/ ไม่ถูกล็อกหรือเป็นแบบอ่านอย่างเดียว"
            f"\n\nรายละเอียดทางเทคนิค: {error}"
        ) from error

    relative_parts = [UPLOAD_DIRECTORY.parent.name, UPLOAD_DIRECTORY.name, *(sub_folders or []), stored_file_name]
    return "/".join(relative_parts)


def build_local_file_url(file_path: Optional[str]) -> Optional[str]:
    """สร้างลิงก์เปิดไฟล์ในเครื่องจากค่า file_path ในฐานข้อมูล (ใช้ไฟล์แรกถ้าแนบหลายไฟล์)

    path ที่อยู่ใต้ local_uploads/ (รวมโฟลเดอร์ย่อย ปี/เดือน/วัน/Vendor) ใช้ตามนั้น
    path แบบเก่า (ไฟล์แบนใน static/ หรือ data/) ใช้เฉพาะชื่อไฟล์ ถ้าไฟล์ยังอยู่ที่เก็บรุ่นเก่า
    จะคัดลอกมาไว้ใน static/local_uploads/ ให้ก่อน (ไม่แก้ไฟล์ต้นทางหรือฐานข้อมูล)

    Args:
        file_path: ค่าจากคอลัมน์ file_path (ว่าง/None ได้)

    Returns:
        ลิงก์แบบ "/app/static/local_uploads/<โฟลเดอร์ย่อย>/<ชื่อไฟล์>" หรือ None ถ้าไม่มีไฟล์/หาไฟล์ไม่เจอ
    """
    if not file_path:
        return None
    relative_parts = _resolve_relative_parts(file_path.split(FILE_PATH_SEPARATOR)[0])
    return STATIC_URL_PREFIX + "/".join(quote(part) for part in relative_parts) if relative_parts else None


def _resolve_relative_parts(stored_path: str) -> Optional[list[str]]:
    """แปลง path ที่เก็บในฐานข้อมูล (ไฟล์เดียว) เป็นส่วนของ path ใต้ static/local_uploads/ ที่ไฟล์มีอยู่จริง

    path แบบเก่าที่ยังอยู่ที่เก็บรุ่นเก่า จะคัดลอกมาไว้ใน static/local_uploads/ ให้ก่อน (ไม่แก้ไฟล์ต้นทาง)

    Returns:
        ส่วนของ path เช่น ["2026", "Oct", "28", "ABC", "PR_1.pdf"] หรือ None ถ้าไม่มีไฟล์/path ไม่ปลอดภัย
    """
    # แปลง "\" เป็น "/" ด้วย เพราะเครื่อง Windows อาจเก็บ path แบบมี backslash
    stored_path = stored_path.strip().replace("\\", "/")
    file_name = stored_path.rsplit("/", 1)[-1]
    if not file_name:
        return None

    # ส่วนของ path หลัง "local_uploads/" (ไม่มี = path เก่าแบบไม่มีโฟลเดอร์ย่อย)
    marker = f"{UPLOAD_DIRECTORY.name}/"
    relative_parts = stored_path.split(marker, 1)[1].split("/") if marker in stored_path else [file_name]
    if ".." in relative_parts or not all(relative_parts):
        return None  # กัน path ที่หลุดออกนอกโฟลเดอร์เก็บไฟล์

    if not UPLOAD_DIRECTORY.joinpath(*relative_parts).is_file():
        legacy_path = LEGACY_UPLOAD_DIRECTORY / file_name
        if not legacy_path.is_file():
            return None
        try:
            UPLOAD_DIRECTORY.mkdir(parents=True, exist_ok=True)
            shutil.copy2(legacy_path, UPLOAD_DIRECTORY / file_name)
        except OSError:
            return None
        relative_parts = [file_name]
    return relative_parts


def get_desktop_directory() -> Path:
    """หาโฟลเดอร์ Desktop จริงของผู้ใช้ (รองรับ Desktop ที่ OneDrive ย้ายไปไว้) สำรองด้วย ~/Desktop"""
    if sys.platform == "win32":
        try:
            import ctypes

            # FOLDERID_Desktop = {B4BFCC3A-DB2C-424C-B029-7FE99A87C641}
            guid = (ctypes.c_ubyte * 16)(
                0x3A, 0xCC, 0xBF, 0xB4, 0x2C, 0xDB, 0x4C, 0x42, 0xB0, 0x29, 0x7F, 0xE9, 0x9A, 0x87, 0xC6, 0x41
            )
            path_pointer = ctypes.c_wchar_p()
            result = ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(guid), 0, None, ctypes.byref(path_pointer))
            if result == 0 and path_pointer.value:
                desktop = Path(path_pointer.value)
                ctypes.windll.ole32.CoTaskMemFree(path_pointer)
                return desktop
        except (OSError, AttributeError, ImportError):
            pass
    return Path.home() / "Desktop"


def export_files_to_desktop(file_paths: str, vendor: str, when: datetime) -> Path:
    """คัดลอกไฟล์ของรายการหนึ่งไปไว้ Desktop/ปี/เดือน/วัน/Vendor/ (ใช้โฟลเดอร์ที่มีอยู่แล้วซ้ำ ไม่สร้างซ้ำ)

    Args:
        file_paths: ค่าคอลัมน์ file_path (หลายไฟล์คั่นด้วย FILE_PATH_SEPARATOR)
        vendor: ชื่อ Vendor ของรายการ
        when: วันที่อัปโหลด (ใช้ตั้งชื่อโฟลเดอร์ ปี/เดือน/วัน)

    Returns:
        โฟลเดอร์ Vendor บน Desktop ที่ไฟล์ถูกเก็บไว้

    Raises:
        LocalStorageError: ไม่พบไฟล์ต้นทางเลย / สร้างโฟลเดอร์หรือคัดลอกไฟล์ไม่ได้
    """
    sources: list[Path] = []
    for stored_path in file_paths.split(FILE_PATH_SEPARATOR):
        relative_parts = _resolve_relative_parts(stored_path) if stored_path.strip() else None
        if relative_parts:
            sources.append(UPLOAD_DIRECTORY.joinpath(*relative_parts))
    if not sources:
        raise LocalStorageError("ไม่พบไฟล์ของรายการนี้ในเครื่อง (ไฟล์อาจถูกย้ายหรือลบไป)")

    target_directory = get_desktop_directory().joinpath(*build_storage_folder_parts(when, vendor))
    try:
        target_directory.mkdir(parents=True, exist_ok=True)
        for source in sources:
            target = target_directory / source.name
            if target.is_file() and target.read_bytes() == source.read_bytes():
                continue  # เคยคัดลอกแล้ว ไม่ต้องทำซ้ำ
            shutil.copy2(source, target_directory / _pick_free_file_name(target_directory, source.name))
    except OSError as error:
        raise LocalStorageError(f"สร้างโฟลเดอร์/คัดลอกไฟล์ไปที่ Desktop ไม่สำเร็จ\n\nรายละเอียดทางเทคนิค: {error}") from error
    return target_directory
