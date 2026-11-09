"""สำรองฐานข้อมูลและไฟล์เอกสาร: ไม่แก้ข้อมูลต้นทาง และรันได้ขณะแอปทำงานอยู่

วิธีใช้:  venv/bin/python scripts/backup.py [--dest โฟลเดอร์ปลายทาง] [--keep จำนวนชุดที่เก็บ]
ตัวอย่าง cron ทุกวัน 01:30:  30 1 * * * cd /path/to/project && venv/bin/python scripts/backup.py >> logs/backup.log 2>&1

ผลลัพธ์ 1 ชุด: <ปลายทาง>/backup_ปปปปดดวว_ชชนนวว/ มี masterlist.db และ local_uploads.tar.gz
ลบเฉพาะชุดเก่าที่สคริปต์นี้สร้าง (ชื่อตรงรูปแบบ) หลังสำรองชุดใหม่สำเร็จแล้วเท่านั้น

วิธีกู้คืน (หยุดแอปก่อน และเก็บข้อมูลปัจจุบันไว้ก่อนเขียนทับ):
  1. คัดลอก masterlist.db ไปแทนไฟล์ที่ DB_FILE_PATH ชี้อยู่ และลบไฟล์ -wal / -shm เดิมของไฟล์นั้น
  2. แตก local_uploads.tar.gz เข้าโฟลเดอร์ static/
"""

import argparse
import re
import shutil
import sqlite3
import sys
import tarfile
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Optional

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))  # รันตรงจาก scripts/ ต้องหา config/ data/ utils/ เจอ

from data.database import DB_PATH  # noqa: E402
from utils.local_storage import UPLOAD_DIRECTORY  # noqa: E402

DEFAULT_DESTINATION: Path = PROJECT_ROOT / "backups"
DEFAULT_KEEP_COUNT: int = 14
BACKUP_NAME_PATTERN: re.Pattern[str] = re.compile(r"backup_\d{8}_\d{6}")
DATABASE_FILE_NAME: str = "masterlist.db"
UPLOADS_ARCHIVE_NAME: str = "local_uploads.tar.gz"
PRIVATE_FOLDER_MODE: int = 0o700  # ชุดสำรองมีเอกสารของบริษัท ให้เจ้าของเข้าถึงได้คนเดียว


class BackupError(Exception):
    """สำรองข้อมูลไม่สำเร็จ (ข้อความเป็นภาษาไทย)"""


def _backup_database(source: Path, target: Path) -> None:
    """คัดลอกฐานข้อมูลด้วย SQLite Backup API (รวมข้อมูลที่ยังอยู่ในไฟล์ -wal) แล้วตรวจความสมบูรณ์ของไฟล์ที่ได้"""
    with closing(sqlite3.connect(f"{source.resolve().as_uri()}?mode=ro", uri=True)) as source_conn:
        with closing(sqlite3.connect(target)) as target_conn:
            source_conn.backup(target_conn)
            result = target_conn.execute("PRAGMA integrity_check").fetchone()[0]
    if result != "ok":
        raise BackupError(f"ไฟล์สำรองของฐานข้อมูลไม่สมบูรณ์: {result}")


def _archive_uploads(upload_directory: Path, target: Path) -> None:
    """บีบอัดโฟลเดอร์เอกสาร ถ้ายังไม่มีโฟลเดอร์จะได้ไฟล์ว่าง (ยังไม่เคยอัปโหลด)"""
    with tarfile.open(target, "w:gz") as archive:
        if upload_directory.is_dir():
            archive.add(upload_directory, arcname=upload_directory.name)


def _prune_old_backups(destination: Path, keep: int) -> None:
    """เก็บชุดล่าสุดไว้ keep ชุด ไม่แตะโฟลเดอร์หรือไฟล์อื่นในปลายทาง"""
    backups = sorted(
        path
        for path in destination.iterdir()
        if path.is_dir() and not path.is_symlink() and BACKUP_NAME_PATTERN.fullmatch(path.name)
    )
    for path in backups[:-keep]:
        shutil.rmtree(path)


def create_backup(
    db_path: Path, upload_directory: Path, destination: Path, keep: int = DEFAULT_KEEP_COUNT, now: Optional[datetime] = None
) -> Path:
    """สร้างชุดสำรองใหม่ แล้วลบชุดเก่าที่เกินจำนวน

    Args:
        db_path: ไฟล์ฐานข้อมูลต้นทาง
        upload_directory: โฟลเดอร์เอกสารต้นทาง
        destination: โฟลเดอร์ที่เก็บชุดสำรอง
        keep: จำนวนชุดล่าสุดที่เก็บไว้ (อย่างน้อย 1)
        now: เวลาที่ใช้ตั้งชื่อชุด (ไม่ระบุใช้เวลาปัจจุบัน)

    Returns:
        โฟลเดอร์ของชุดสำรองที่สร้าง

    Raises:
        BackupError: ค่าที่ส่งมาใช้ไม่ได้ หรือไฟล์สำรองไม่สมบูรณ์
        OSError, sqlite3.Error, tarfile.TarError: อ่านหรือเขียนไฟล์ไม่สำเร็จ
    """
    if keep < 1:
        raise BackupError("จำนวนชุดที่เก็บต้องอย่างน้อย 1")
    if not db_path.is_file():
        raise BackupError(f"ไม่พบไฟล์ฐานข้อมูล: {db_path}")
    # โฟลเดอร์ static/ ถูกเสิร์ฟทางเว็บโดยไม่ล็อกอิน ถ้าเก็บไว้ในนั้นใครก็ดาวน์โหลดชุดสำรองได้
    if destination.resolve().is_relative_to(upload_directory.resolve().parent):
        raise BackupError(f"ห้ามเก็บชุดสำรองในโฟลเดอร์ที่เปิดทางเว็บ: {destination}")

    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    final_folder = destination / f"backup_{stamp}"
    if final_folder.exists():
        raise BackupError(f"มีชุดสำรองชื่อนี้อยู่แล้ว: {final_folder}")
    partial_folder = destination / f".partial_{stamp}"  # ชื่อไม่ตรงรูปแบบ ชุดที่ทำไม่เสร็จจึงไม่ถูกนับเป็นชุดสำรอง

    destination.mkdir(parents=True, exist_ok=True)
    partial_folder.mkdir(mode=PRIVATE_FOLDER_MODE)
    try:
        _backup_database(db_path, partial_folder / DATABASE_FILE_NAME)
        _archive_uploads(upload_directory, partial_folder / UPLOADS_ARCHIVE_NAME)
        partial_folder.rename(final_folder)
    except BaseException:
        shutil.rmtree(partial_folder, ignore_errors=True)
        raise
    _prune_old_backups(destination, keep)
    return final_folder


def main(argv: Optional[list[str]] = None) -> int:
    """จุดเริ่มต้นของคำสั่ง คืนค่า 0 เมื่อสำเร็จ และ 1 เมื่อไม่สำเร็จ"""
    parser = argparse.ArgumentParser(description="สำรองฐานข้อมูลและไฟล์เอกสาร")
    parser.add_argument("--dest", type=Path, default=DEFAULT_DESTINATION, help="โฟลเดอร์ปลายทาง ควรอยู่คนละดิสก์กับข้อมูลจริง")
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP_COUNT, help="จำนวนชุดล่าสุดที่เก็บไว้")
    args = parser.parse_args(argv)
    try:
        folder = create_backup(DB_PATH, UPLOAD_DIRECTORY, args.dest, args.keep)
    except (BackupError, OSError, sqlite3.Error, tarfile.TarError) as error:
        print(f"สำรองข้อมูลไม่สำเร็จ: {error}", file=sys.stderr)
        return 1
    print(f"สำรองข้อมูลแล้ว: {folder}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
