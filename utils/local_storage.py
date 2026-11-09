"""เก็บไฟล์เอกสาร (PR/PO/ใบกำกับภาษี) ลงโฟลเดอร์ static/local_uploads/ ภายในโปรเจค (Streamlit เสิร์ฟให้เปิดจากตารางได้)

ใช้แทน SharePoint ชั่วคราวระหว่างรอสิทธิ์ (sharepoint_api.py ยังเก็บไว้ เตรียมต่อภายหลัง)
ไฟล์ไม่มี Streamlit: ถ้าผิดพลาดจะ raise LocalStorageError พร้อมข้อความภาษาไทย ให้หน้า UI เป็นคนแสดงผลเอง
"""

import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from config.settings import get_env_flag
from utils import file_removal
from utils.storage_backend import build_folder_name_from_files, build_storage_folder_parts

# เปิดเมื่อรันบนเครื่องของผู้ใช้เองเท่านั้น (LOCAL_DESKTOP_EXPORT=1 ใน .env): ตอน Upload สร้างโฟลเดอร์บน Desktop + คัดลอกไฟล์ให้อัตโนมัติ
# ส่วนไอคอน File แค่เปิดโฟลเดอร์นั้นใน Explorer; บน Server ต้องปิด เพราะโค้ดทำงานที่เครื่อง Server ผู้ใช้จะไม่เห็นไฟล์
# (ปิด = ไอคอนเปิดไฟล์ผ่านลิงก์ในเบราว์เซอร์แทน)
DESKTOP_EXPORT_ENABLED: bool = get_env_flag("LOCAL_DESKTOP_EXPORT", False)

# โฟลเดอร์เก็บไฟล์ static/local_uploads/ (ข้างไฟล์ app.py — ถ้าไม่มีจะถูกสร้างให้อัตโนมัติตอนบันทึกไฟล์แรก)
# ต้องอยู่ใต้ static/ และเปิด server.enableStaticServing ใน .streamlit/config.toml จึงเปิดไฟล์ผ่านเบราว์เซอร์ได้
UPLOAD_DIRECTORY: Path = Path(__file__).parent.parent / "static" / "local_uploads"
# ที่เก็บไฟล์รุ่นเก่า (ก่อนย้ายมา static/) แถวเก่าในฐานข้อมูลยังอ้างที่อยู่นี้
LEGACY_UPLOAD_DIRECTORY: Path = Path(__file__).parent.parent / "data" / "local_uploads"
STATIC_URL_PREFIX: str = "/app/static/local_uploads/"  # ลิงก์ที่ Streamlit เสิร์ฟ (ต้องตรงกับ UPLOAD_DIRECTORY)
FILE_PATH_SEPARATOR: str = file_removal.FILE_PATH_SEPARATOR  # ตัวคั่นเมื่อแนบหลายไฟล์ในคอลัมน์ file_path (ต้องตรงกับ submit_pipeline.py)


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
        same_name_file = target_directory / cleaned_name
        if same_name_file.is_file() and same_name_file.read_bytes() == file_bytes:
            stored_file_name = cleaned_name  # ไฟล์เดิมเนื้อเหมือนกันทุกไบต์ ใช้ไฟล์เดิม ไม่สร้าง _1
        else:
            stored_file_name = _pick_free_file_name(target_directory, cleaned_name)
            (target_directory / stored_file_name).write_bytes(file_bytes)
    except OSError as error:
        raise LocalStorageError(
            "บันทึกไฟล์ไม่สำเร็จ: ตรวจว่าดิสก์ไม่เต็ม และโฟลเดอร์ local_uploads/ ไม่ถูกล็อกหรือเป็นแบบอ่านอย่างเดียว"
            f"\n\nรายละเอียดทางเทคนิค: {error}"
        ) from error

    relative_parts = [UPLOAD_DIRECTORY.parent.name, UPLOAD_DIRECTORY.name, *(sub_folders or []), stored_file_name]
    return "/".join(relative_parts)


# จำลิงก์ไฟล์ที่เจอแล้ว {file_path: (ลิงก์, เวลาหมดอายุ)} กันเช็คไฟล์บนดิสก์ซ้ำทุกแถวทุกครั้งที่หน้ารีรัน
FILE_URL_CACHE_SECONDS: float = 30.0
_file_url_cache: dict[str, tuple[str, float]] = {}


def build_local_file_url(file_path: Optional[str]) -> Optional[str]:
    """สร้างลิงก์เปิดไฟล์ในเครื่องจากค่า file_path ในฐานข้อมูล (ใช้ไฟล์แรกถ้าแนบหลายไฟล์)

    path ที่อยู่ใต้ local_uploads/ (รวมโฟลเดอร์ย่อย ปี/เดือน/วัน/ชื่อไฟล์ PR) ใช้ตามนั้น
    path แบบเก่า (ไฟล์แบนใน static/ หรือ data/) ใช้เฉพาะชื่อไฟล์ ถ้าไฟล์ยังอยู่ที่เก็บรุ่นเก่า
    จะคัดลอกมาไว้ใน static/local_uploads/ ให้ก่อน (ไม่แก้ไฟล์ต้นทางหรือฐานข้อมูล)

    Args:
        file_path: ค่าจากคอลัมน์ file_path (ว่าง/None ได้)

    Returns:
        ลิงก์แบบ "/app/static/local_uploads/<โฟลเดอร์ย่อย>/<ชื่อไฟล์>" หรือ None ถ้าไม่มีไฟล์/หาไฟล์ไม่เจอ
    """
    if not file_path:
        return None
    now = time.monotonic()
    cached = _file_url_cache.get(file_path)
    if cached is not None and cached[1] > now:
        return cached[0]
    relative_parts = _resolve_relative_parts(file_path.split(FILE_PATH_SEPARATOR)[0])
    url = STATIC_URL_PREFIX + "/".join(quote(part) for part in relative_parts) if relative_parts else None
    if url is not None:
        # จำเฉพาะกรณีเจอไฟล์ (ไม่เจอให้ลองใหม่ทุกรอบ เผื่อไฟล์เพิ่งมา): ตารางรีรันบ่อย ไม่ต้องเช็คดิสก์ (OneDrive ช้า) ซ้ำทุกแถวทุกรอบ
        _file_url_cache[file_path] = (url, now + FILE_URL_CACHE_SECONDS)
    return url


def parse_stored_path(stored_path: str) -> Optional[list[str]]:
    """แปลง path ที่เก็บในฐานข้อมูล (ไฟล์เดียว) เป็นส่วนของ path ใต้ local_uploads/ โดยไม่แตะดิสก์ (None = path ไม่ปลอดภัย/ว่าง)

    ตรรกะอยู่ที่ utils/file_removal.py (ใช้ร่วมกับเครื่องมือใน scripts/)
    """
    return file_removal.parse_stored_path(stored_path, UPLOAD_DIRECTORY.name)


def _resolve_relative_parts(stored_path: str) -> Optional[list[str]]:
    """แปลง path ที่เก็บในฐานข้อมูล (ไฟล์เดียว) เป็นส่วนของ path ใต้ static/local_uploads/ ที่ไฟล์มีอยู่จริง

    path แบบเก่าที่ยังอยู่ที่เก็บรุ่นเก่า จะคัดลอกมาไว้ใน static/local_uploads/ ให้ก่อน (ไม่แก้ไฟล์ต้นทาง)

    Returns:
        ส่วนของ path เช่น ["2026", "Oct", "28", "ABC", "PR_1.pdf"] หรือ None ถ้าไม่มีไฟล์/path ไม่ปลอดภัย
    """
    relative_parts = parse_stored_path(stored_path)
    if relative_parts is None:
        return None
    file_name = relative_parts[-1]

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


def get_folder_parts_from_file_paths(file_paths: Optional[str]) -> Optional[list[str]]:
    """อ่านโครงโฟลเดอร์จริงจากค่าคอลัมน์ file_path เช่น ["2026", "Oct", "28", "ABC"]

    Args:
        file_paths: ค่าคอลัมน์ file_path (หลายไฟล์คั่นด้วย FILE_PATH_SEPARATOR)

    Returns:
        ส่วนของโฟลเดอร์ใต้ local_uploads/ หรือ None ถ้าไม่พบไฟล์ หรือเป็นไฟล์เก่าที่ไม่มีโฟลเดอร์ย่อย
    """
    for stored_path in (file_paths or "").split(FILE_PATH_SEPARATOR):
        relative_parts = _resolve_relative_parts(stored_path) if stored_path.strip() else None
        if relative_parts and len(relative_parts) > 1:
            return relative_parts[:-1]
    return None


def list_stored_files(file_paths: Optional[str]) -> list[Path]:
    """ไฟล์ในเครื่องที่มีอยู่จริงจากค่าคอลัมน์ file_path (ไม่พบเลย = รายการว่าง ไม่โยน Error)"""
    try:
        return _resolve_source_files(file_paths or "")
    except LocalStorageError:
        return []


def list_folder_files(folder_parts: Optional[list[str]]) -> list[Path]:
    """ไฟล์จริงทั้งหมดในโฟลเดอร์ใต้ local_uploads/ (ไม่รวมโฟลเดอร์ย่อย) เรียงตามชื่อ ไม่พบ/path ไม่ปลอดภัย = []"""
    if not folder_parts or ".." in folder_parts or not all(folder_parts):
        return []
    folder = UPLOAD_DIRECTORY.joinpath(*folder_parts)
    try:
        return sorted((path for path in folder.iterdir() if path.is_file()), key=lambda path: path.name)
    except OSError:
        return []


def remove_stored_file(parts: list[str]) -> None:
    """ลบไฟล์เดียวใต้ local_uploads/ พร้อมโฟลเดอร์แม่ที่ว่าง (ไม่มีไฟล์นี้แล้วไม่ถือเป็น error)

    Raises:
        OSError: path ไม่ปลอดภัย หรือลบไม่ได้
    """
    file_removal.remove_stored_file(UPLOAD_DIRECTORY, parts)


def remove_upload_folder(parts: list[str]) -> None:
    """ลบทั้งโฟลเดอร์ใต้ local_uploads/ พร้อมโฟลเดอร์แม่ที่ว่าง (ไม่มีโฟลเดอร์นี้แล้วไม่ถือเป็น error)

    Raises:
        OSError: path ไม่ปลอดภัย หรือลบไม่ได้
    """
    file_removal.remove_upload_folder(UPLOAD_DIRECTORY, parts)


def remove_desktop_copy(folder_parts: list[str], file_names: Optional[list[str]] = None) -> None:
    """ลบสำเนาบน Desktop ที่สร้างตอน Upload (ทำงานเฉพาะเมื่อเปิด LOCAL_DESKTOP_EXPORT)

    Args:
        folder_parts: โครงโฟลเดอร์ ปี/เดือน/วัน/ชื่อ (ตรงกับโฟลเดอร์ใต้ local_uploads/)
        file_names: ลบเฉพาะไฟล์เหล่านี้ (ไม่ส่ง = ลบทั้งโฟลเดอร์)

    Raises:
        OSError: path ไม่ปลอดภัย หรือลบไม่ได้
    """
    if not DESKTOP_EXPORT_ENABLED:
        return
    desktop = get_desktop_directory()
    folder = desktop.joinpath(*folder_parts)
    if not folder_parts or ".." in folder_parts or folder.is_symlink():
        raise OSError(f"ไม่ลบ path บน Desktop: {'/'.join(folder_parts)}")
    if file_names is None:
        if folder.exists():
            shutil.rmtree(folder)
    else:
        for file_name in file_names:
            (folder / file_name).unlink(missing_ok=True)
    file_removal.prune_empty_parents(folder / "_", desktop)


def forget_file_url(file_path: Optional[str]) -> None:
    """ลืมลิงก์ไฟล์ที่จำไว้ของค่าคอลัมน์ file_path นี้ (ใช้เมื่อไฟล์ถูกลบ)"""
    _file_url_cache.pop(file_path or "", None)


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


def _resolve_source_files(file_paths: str) -> list[Path]:
    """แปลงค่าคอลัมน์ file_path (หลายไฟล์คั่นด้วย FILE_PATH_SEPARATOR) เป็นไฟล์ในเครื่องที่มีอยู่จริง

    Raises:
        LocalStorageError: ไม่พบไฟล์เลย
    """
    sources: list[Path] = []
    for stored_path in file_paths.split(FILE_PATH_SEPARATOR):
        relative_parts = _resolve_relative_parts(stored_path) if stored_path.strip() else None
        if relative_parts:
            sources.append(UPLOAD_DIRECTORY.joinpath(*relative_parts))
    if not sources:
        raise LocalStorageError("ไม่พบไฟล์ของรายการนี้ในเครื่อง (ไฟล์อาจถูกย้ายหรือลบไป)")
    return sources


def _build_desktop_target_directory(sources: list[Path], when: datetime) -> Path:
    """โฟลเดอร์ปลายทางบน Desktop: ปี/เดือน/วัน/ชื่อไฟล์ PR (ยังไม่สร้างโฟลเดอร์)"""
    # ใช้โครงโฟลเดอร์ที่ไฟล์อยู่จริง (ตรงกับตอนอัปโหลด แม้เป็นไฟล์ที่เพิ่มเข้าโฟลเดอร์เดิมทีหลัง) ไฟล์เก่าที่ไม่มีโฟลเดอร์ย่อยตั้งจากชื่อไฟล์และ when
    first_parent = sources[0].parent
    if first_parent in (UPLOAD_DIRECTORY, LEGACY_UPLOAD_DIRECTORY):
        folder_name = build_folder_name_from_files([source.name for source in sources])
        return get_desktop_directory().joinpath(*build_storage_folder_parts(when, folder_name))
    return get_desktop_directory().joinpath(*first_parent.relative_to(UPLOAD_DIRECTORY).parts)


def find_file_location(file_paths: str, when: datetime) -> Path:
    """หาโฟลเดอร์ที่เก็บไฟล์ของรายการหนึ่ง เพื่อเปิดใน Explorer (ไม่สร้างโฟลเดอร์ ไม่คัดลอกไฟล์)

    ใช้โฟลเดอร์บน Desktop ที่สร้างตอนอัปโหลด ถ้าไม่มี (รายการเก่าก่อนมีฟีเจอร์นี้) ใช้โฟลเดอร์เก็บไฟล์ในเครื่องแทน

    Args:
        file_paths: ค่าคอลัมน์ file_path (หลายไฟล์คั่นด้วย FILE_PATH_SEPARATOR)
        when: วันที่อัปโหลด (ใช้หาโฟลเดอร์ ปี/เดือน/วัน บน Desktop)

    Raises:
        LocalStorageError: ไม่พบไฟล์ของรายการนี้ในเครื่อง
    """
    sources = _resolve_source_files(file_paths)
    desktop_directory = _build_desktop_target_directory(sources, when)
    return desktop_directory if desktop_directory.is_dir() else sources[0].parent


def export_files_to_desktop(file_paths: str, when: datetime) -> Path:
    """คัดลอกไฟล์ของรายการหนึ่งไปไว้ Desktop/ปี/เดือน/วัน/ชื่อไฟล์ PR/ (ใช้โฟลเดอร์ที่มีอยู่แล้วซ้ำ ไม่สร้างซ้ำ)

    Args:
        file_paths: ค่าคอลัมน์ file_path (หลายไฟล์คั่นด้วย FILE_PATH_SEPARATOR)
        when: วันที่อัปโหลด (ใช้ตั้งชื่อโฟลเดอร์ ปี/เดือน/วัน)

    Returns:
        โฟลเดอร์ปลายทางบน Desktop ที่ไฟล์ถูกเก็บไว้ (ชื่อโฟลเดอร์ตั้งจากชื่อไฟล์ PR เหมือนตอนอัปโหลด)

    Raises:
        LocalStorageError: ไม่พบไฟล์ต้นทางเลย / สร้างโฟลเดอร์หรือคัดลอกไฟล์ไม่ได้
    """
    sources = _resolve_source_files(file_paths)
    target_directory = _build_desktop_target_directory(sources, when)
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
