"""ลบแถวแบบถาวร: แถวในฐานข้อมูล + ไฟล์/โฟลเดอร์ของแถวบนเครื่อง (รวมสำเนาบน Desktop ถ้าเปิดโหมดนั้น)

ไม่แตะที่เก็บออนไลน์ Master-List ที่เก็บรุ่นเก่า data/local_uploads และไฟล์ที่แถวอื่นยังอ้างถึง
(นับแถวที่ถูกซ่อนไว้จากรุ่นก่อนด้วย เพื่อไม่ให้ไฟล์ของแถวเหล่านั้นหาย)

ไฟล์นี้ไม่เรียก Streamlit โดยตรง
"""

import logging
from dataclasses import dataclass, field
from typing import Optional

from data.database import delete_transactions, get_all_file_paths, get_transaction
from utils.local_storage import (
    FILE_PATH_SEPARATOR,
    forget_file_url,
    parse_stored_path,
    remove_desktop_copy,
    remove_stored_file,
    remove_upload_folder,
)

logger = logging.getLogger(__name__)

ROW_FOLDER_DEPTH: int = 4  # ปี/เดือน/วัน/ชื่อ: ตื้นกว่านี้เป็นโครงเก่า ลบเฉพาะไฟล์ ไม่ลบทั้งโฟลเดอร์


@dataclass
class CleanupReport:
    """ผลการลบ: แถวที่ลบแล้วกู้คืนไม่ได้ แม้ลบไฟล์บางส่วนไม่สำเร็จ (ดู failed)"""

    deleted_count: int = 0
    removed_folders: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)  # โฟลเดอร์/ไฟล์ที่ลบไม่สำเร็จ
    kept_files: list[str] = field(default_factory=list)  # ไฟล์ของแถวที่ลบ แต่เก็บไว้เพราะแถวอื่น (รวมแถวที่ถูกซ่อน) ยังอ้างถึง


@dataclass
class FileRemovalPlan:
    """สิ่งที่จะลบเมื่อแถวหายไป (ยังไม่แตะดิสก์)"""

    whole_folders: list[tuple[str, ...]] = field(default_factory=list)  # โฟลเดอร์ที่ไม่มีแถวอื่นอ้างถึง
    files_by_folder: dict[tuple[str, ...], list[tuple[str, ...]]] = field(default_factory=dict)  # ไฟล์ที่ลบทีละไฟล์
    kept_files: list[str] = field(default_factory=list)  # ไฟล์ที่เก็บไว้เพราะแถวอื่นยังอ้างถึง


def _parse_paths(file_paths: Optional[str]) -> list[tuple[str, ...]]:
    parsed = (parse_stored_path(path) for path in (file_paths or "").split(FILE_PATH_SEPARATOR) if path.strip())
    return [tuple(parts) for parts in parsed if parts]


def _remove_files(files: list[tuple[str, ...]], folder: tuple[str, ...], report: CleanupReport) -> None:
    for parts in files:
        try:
            remove_stored_file(list(parts))
        except OSError as error:
            logger.error("ลบไฟล์ไม่สำเร็จ %s: %s", "/".join(parts), type(error).__name__)
            report.failed.append("/".join(parts))
    if len(folder) >= ROW_FOLDER_DEPTH:
        try:
            remove_desktop_copy(list(folder), [parts[-1] for parts in files])
        except OSError as error:
            logger.error("ลบสำเนาบน Desktop ไม่สำเร็จ %s: %s", "/".join(folder), type(error).__name__)
            report.failed.append(f"Desktop/{'/'.join(folder)}")


def _remove_folder(folder: tuple[str, ...], report: CleanupReport) -> None:
    label = "/".join(folder)
    try:
        remove_upload_folder(list(folder))
        report.removed_folders.append(label)
    except OSError as error:
        logger.error("ลบโฟลเดอร์ไม่สำเร็จ %s: %s", label, type(error).__name__)
        report.failed.append(label)
    try:
        remove_desktop_copy(list(folder))
    except OSError as error:
        logger.error("ลบสำเนาบน Desktop ไม่สำเร็จ %s: %s", label, type(error).__name__)
        report.failed.append(f"Desktop/{label}")


def plan_file_removal(row_file_paths: list[Optional[str]], remaining_file_paths: list[str]) -> FileRemovalPlan:
    """ตัดสินว่าจะลบอะไรเมื่อแถวเหล่านี้หายไป โดยยังไม่แตะดิสก์

    โฟลเดอร์ที่ไม่มีแถวอื่นอ้างถึง: ลบทั้งโฟลเดอร์ รวมไฟล์ที่ไม่ได้อยู่ในรายการของแถว
    โฟลเดอร์ที่แถวอื่นยังใช้ หรือโครงเก่าที่ไม่มีโฟลเดอร์ของแถว: ลบเฉพาะไฟล์ของแถวนี้ที่แถวอื่นไม่อ้างถึง

    Args:
        row_file_paths: ค่า file_path ของแถวที่จะลบ
        remaining_file_paths: ค่า file_path ของแถวที่เหลือทั้งหมด

    Returns:
        แผนการลบ
    """
    own_files = {parts: None for file_paths in row_file_paths for parts in _parse_paths(file_paths)}
    referenced = {parts for file_paths in remaining_file_paths for parts in _parse_paths(file_paths)}
    files_by_folder: dict[tuple[str, ...], list[tuple[str, ...]]] = {}
    for parts in own_files:
        files_by_folder.setdefault(parts[:-1], []).append(parts)

    plan = FileRemovalPlan()
    for folder, files in files_by_folder.items():
        folder_in_use = any(parts[: len(folder)] == folder for parts in referenced)
        if len(folder) >= ROW_FOLDER_DEPTH and not folder_in_use:
            plan.whole_folders.append(folder)
        else:
            plan.files_by_folder[folder] = [parts for parts in files if parts not in referenced]
            plan.kept_files.extend("/".join(parts) for parts in files if parts in referenced)
    return plan


def carry_out_file_removal(plan: FileRemovalPlan, report: CleanupReport) -> None:
    """ลบไฟล์ตามแผน เรียกหลังลบแถวจากฐานข้อมูลสำเร็จแล้วเท่านั้น รายการที่ลบไม่สำเร็จเก็บใน report.failed

    Args:
        plan: แผนจาก plan_file_removal
        report: รายงานที่จะเติมผลการลบ
    """
    for folder in plan.whole_folders:
        _remove_folder(folder, report)
    for folder, files in plan.files_by_folder.items():
        _remove_files(files, folder, report)
    report.kept_files.extend(plan.kept_files)


def delete_rows_and_files(transaction_ids: list[int]) -> CleanupReport:
    """ลบแถวถาวรแล้วลบไฟล์ของแถวเหล่านั้น ลบแถวก่อน ถ้าลบแถวไม่สำเร็จจะไม่แตะไฟล์

    Args:
        transaction_ids: id ของแถวที่ต้องการลบ

    Returns:
        จำนวนแถวที่ลบ โฟลเดอร์ที่ลบ และรายการที่ลบไม่สำเร็จ
    """
    rows = [row for row in (get_transaction(row_id) for row_id in transaction_ids) if row]
    report = CleanupReport(deleted_count=delete_transactions(transaction_ids))
    if not report.deleted_count:
        return report

    row_file_paths = [row.get("file_path") for row in rows]
    remaining = get_all_file_paths()  # อ่านหลังลบ จึงเหลือเฉพาะแถวอื่น
    if remaining is None:
        # ไม่รู้ว่าแถวอื่นใช้ไฟล์ไหนอยู่ จึงไม่ลบไฟล์เลย
        own_files = {parts: None for file_paths in row_file_paths for parts in _parse_paths(file_paths)}
        report.failed.extend("/".join(parts) for parts in own_files)
        return report

    carry_out_file_removal(plan_file_removal(row_file_paths, remaining), report)
    for row in rows:
        forget_file_url(row.get("file_path"))
    return report
