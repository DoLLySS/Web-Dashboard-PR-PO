"""ตรรกะลบไฟล์เอกสารใต้โฟลเดอร์เก็บไฟล์ (ปี/เดือน/วัน/ชื่อ) ใช้ร่วมกันระหว่างแอปและเครื่องมือใน scripts/

ไฟล์นี้ใช้เฉพาะไลบรารีมาตรฐานของ Python (ห้าม import streamlit / config / data) เพื่อให้เครื่องมือใน scripts/
คัดลอกไปรันที่โฟลเดอร์อื่นได้ โดยไม่ต้องอัปเดตโค้ดหรือ venv ของแอปจริง (มีเทสต์กำกับ)

ทุกฟังก์ชันรับโฟลเดอร์เก็บไฟล์ (upload_dir) เป็นพารามิเตอร์ ไม่อ่านค่าตั้งค่าจากที่อื่น
"""

import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

FILE_PATH_SEPARATOR: str = "\n"  # ตัวคั่นเมื่อแนบหลายไฟล์ในคอลัมน์ file_path (ต้องตรงกับ submit_pipeline.py)
ROW_FOLDER_DEPTH: int = 4  # ปี/เดือน/วัน/ชื่อ: ตื้นกว่านี้เป็นโครงเก่า ลบเฉพาะไฟล์ ไม่ลบทั้งโฟลเดอร์


@dataclass
class FileRemovalPlan:
    """สิ่งที่จะลบเมื่อแถวหายไป (ยังไม่แตะดิสก์)"""

    own_files: list[tuple[str, ...]] = field(default_factory=list)  # ไฟล์ทั้งหมดที่แถวที่จะลบอ้างถึง
    whole_folders: list[tuple[str, ...]] = field(default_factory=list)  # โฟลเดอร์ที่ไม่มีแถวอื่นอ้างถึง
    files_by_folder: dict[tuple[str, ...], list[tuple[str, ...]]] = field(default_factory=dict)  # ไฟล์ที่ลบทีละไฟล์
    kept_files: list[str] = field(default_factory=list)  # ไฟล์ที่เก็บไว้เพราะแถวอื่นยังอ้างถึง


@dataclass
class RemovalResult:
    """ผลการลบตามแผน: รายการที่ลบไม่สำเร็จไม่ทำให้ขั้นอื่นล้ม"""

    removed_folders: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)


def parse_stored_path(stored_path: str, upload_dir_name: str) -> Optional[list[str]]:
    """แปลง path ที่เก็บในฐานข้อมูล (ไฟล์เดียว) เป็นส่วนของ path ใต้โฟลเดอร์เก็บไฟล์ โดยไม่แตะดิสก์

    Args:
        stored_path: ค่าที่เก็บไว้ เช่น "static/local_uploads/2026/Oct/28/ABC/PR_1.pdf" (มี "\\" ได้)
        upload_dir_name: ชื่อโฟลเดอร์เก็บไฟล์ เช่น "local_uploads"

    Returns:
        ส่วนของ path หลังชื่อโฟลเดอร์เก็บไฟล์ หรือ [ชื่อไฟล์] ถ้าเป็นโครงเก่าที่ไม่มีโฟลเดอร์ย่อย
        None = path ว่างหรือไม่ปลอดภัย (มี ".." หรือ "." หรือส่วนว่าง)
    """
    stored_path = stored_path.strip().replace("\\", "/")
    file_name = stored_path.rsplit("/", 1)[-1]
    if not file_name:
        return None
    marker = f"{upload_dir_name}/"
    relative_parts = stored_path.split(marker, 1)[1].split("/") if marker in stored_path else [file_name]
    if any(part in ("", ".", "..") for part in relative_parts):
        return None
    return relative_parts


def parse_stored_paths(file_paths: Optional[str], upload_dir_name: str) -> list[tuple[str, ...]]:
    """แปลงค่าคอลัมน์ file_path (หลายไฟล์คั่นด้วย FILE_PATH_SEPARATOR) เป็น path ที่ปลอดภัยทั้งหมด"""
    parsed = (parse_stored_path(path, upload_dir_name) for path in (file_paths or "").split(FILE_PATH_SEPARATOR) if path.strip())
    return [tuple(parts) for parts in parsed if parts]


def plan_file_removal(
    row_file_paths: list[Optional[str]], remaining_file_paths: list[str], upload_dir_name: str
) -> FileRemovalPlan:
    """ตัดสินว่าจะลบอะไรเมื่อแถวเหล่านี้หายไป โดยยังไม่แตะดิสก์

    โฟลเดอร์ที่ไม่มีแถวอื่นอ้างถึง: ลบทั้งโฟลเดอร์ รวมไฟล์ที่ไม่ได้อยู่ในรายการของแถว
    โฟลเดอร์ที่แถวอื่นยังใช้ หรือโครงเก่าที่ไม่มีโฟลเดอร์ของแถว: ลบเฉพาะไฟล์ของแถวนี้ที่แถวอื่นไม่อ้างถึง

    Args:
        row_file_paths: ค่า file_path ของแถวที่จะลบ
        remaining_file_paths: ค่า file_path ของแถวที่เหลือทั้งหมด (รวมแถวที่ถูกซ่อนไว้)
        upload_dir_name: ชื่อโฟลเดอร์เก็บไฟล์ เช่น "local_uploads"

    Returns:
        แผนการลบ
    """
    own_files = list(
        dict.fromkeys(parts for file_paths in row_file_paths for parts in parse_stored_paths(file_paths, upload_dir_name))
    )
    referenced = {
        parts for file_paths in remaining_file_paths for parts in parse_stored_paths(file_paths, upload_dir_name)
    }
    files_by_folder: dict[tuple[str, ...], list[tuple[str, ...]]] = {}
    for parts in own_files:
        files_by_folder.setdefault(parts[:-1], []).append(parts)

    plan = FileRemovalPlan(own_files=own_files)
    for folder, files in files_by_folder.items():
        folder_in_use = any(parts[: len(folder)] == folder for parts in referenced)
        if len(folder) >= ROW_FOLDER_DEPTH and not folder_in_use:
            plan.whole_folders.append(folder)
        else:
            plan.files_by_folder[folder] = [parts for parts in files if parts not in referenced]
            plan.kept_files.extend("/".join(parts) for parts in files if parts in referenced)
    return plan


def safe_upload_path(upload_dir: Path, parts: list[str]) -> Path:
    """path ใต้โฟลเดอร์เก็บไฟล์ที่ลบได้อย่างปลอดภัย

    Raises:
        OSError: path ว่าง / เป็นตัวโฟลเดอร์เก็บไฟล์เอง / เป็น symlink / หลุดออกนอกโฟลเดอร์เก็บไฟล์
    """
    path = upload_dir.joinpath(*parts)
    root = upload_dir.resolve()
    if not parts or ".." in parts or path.is_symlink() or root not in path.resolve().parents:
        raise OSError(f"ไม่ลบ path ที่อยู่นอกโฟลเดอร์เก็บไฟล์: {'/'.join(parts)}")
    return path


def prune_empty_parents(path: Path, stop_at: Path) -> None:
    """ลบโฟลเดอร์แม่ที่ว่างไล่ขึ้นไป (เช่น วัน/เดือน/ปี) จนถึง stop_at ซึ่งไม่ถูกลบ หยุดเมื่อเจอโฟลเดอร์ที่ไม่ว่าง"""
    for parent in path.parents:
        if parent == stop_at or stop_at not in parent.parents:
            return
        try:
            parent.rmdir()
        except FileNotFoundError:
            continue  # แถวอื่นในชุดลบเดียวกันอาจลบไปแล้ว ดูชั้นถัดไปต่อ
        except OSError:
            return


def remove_stored_file(upload_dir: Path, parts: list[str]) -> None:
    """ลบไฟล์เดียวใต้โฟลเดอร์เก็บไฟล์ พร้อมโฟลเดอร์แม่ที่ว่าง (ไม่มีไฟล์นี้แล้วไม่ถือเป็น error)

    Raises:
        OSError: path ไม่ปลอดภัย หรือลบไม่ได้
    """
    path = safe_upload_path(upload_dir, parts)
    path.unlink(missing_ok=True)
    prune_empty_parents(path, upload_dir)


def remove_upload_folder(upload_dir: Path, parts: list[str]) -> None:
    """ลบทั้งโฟลเดอร์ใต้โฟลเดอร์เก็บไฟล์ พร้อมโฟลเดอร์แม่ที่ว่าง (ไม่มีโฟลเดอร์นี้แล้วไม่ถือเป็น error)

    Raises:
        OSError: path ไม่ปลอดภัย หรือลบไม่ได้
    """
    path = safe_upload_path(upload_dir, parts)
    if path.exists():
        shutil.rmtree(path)
    prune_empty_parents(path, upload_dir)


def count_existing_files(plan: FileRemovalPlan, upload_dir: Path) -> tuple[int, int]:
    """นับไฟล์ตามแผนโดยไม่แตะดิสก์เพิ่ม

    Returns:
        (จำนวนไฟล์ที่แถวอ้างถึงและมีอยู่จริงบนดิสก์, จำนวนไฟล์ทั้งหมดที่จะถูกลบจริง รวมไฟล์กำพร้าในโฟลเดอร์ที่ลบทั้งโฟลเดอร์)
    """
    existing_own = sum(1 for parts in plan.own_files if upload_dir.joinpath(*parts).is_file())
    to_delete = 0
    for folder in plan.whole_folders:
        to_delete += sum(1 for path in upload_dir.joinpath(*folder).rglob("*") if path.is_file())
    for files in plan.files_by_folder.values():
        to_delete += sum(1 for parts in files if upload_dir.joinpath(*parts).is_file())
    return existing_own, to_delete


def execute_removal_plan(plan: FileRemovalPlan, upload_dir: Path) -> RemovalResult:
    """ลบไฟล์ตามแผน (ไม่รวมสำเนา Desktop) รายการที่ลบไม่สำเร็จเก็บใน failed แล้วทำรายการถัดไปต่อ"""
    result = RemovalResult()
    for folder in plan.whole_folders:
        label = "/".join(folder)
        try:
            remove_upload_folder(upload_dir, list(folder))
            result.removed_folders.append(label)
        except OSError:
            result.failed.append(label)
    for files in plan.files_by_folder.values():
        for parts in files:
            try:
                remove_stored_file(upload_dir, list(parts))
            except OSError:
                result.failed.append("/".join(parts))
    return result
