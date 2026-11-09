"""สำรองฐานข้อมูล ไฟล์เอกสาร และ (ถ้าสั่ง) โค้ดของโปรเจกต์: ไม่แก้ข้อมูลต้นทาง และรันได้ขณะแอปทำงานอยู่

ใช้เฉพาะไลบรารีมาตรฐานของ Python จึงคัดลอกไปรันที่โฟลเดอร์อื่นได้ โดยไม่ต้องอัปเดตโค้ดหรือ venv ของแอปจริง

วิธีใช้:
    python3 scripts/backup.py --db <ไฟล์ฐานข้อมูล> --uploads <โฟลเดอร์ local_uploads> [--code <โฟลเดอร์โปรเจกต์>]
                              [--dest <โฟลเดอร์ปลายทาง>] [--keep <จำนวนชุดที่เก็บ>]
ถ้าไม่ระบุ --db ใช้ตัวแปรระบบ DB_FILE_PATH (ไม่อ่านไฟล์ .env) ไม่มีก็ใช้ <โปรเจกต์>/data/masterlist.db
ถ้าไม่ระบุ --uploads ใช้ <โปรเจกต์>/static/local_uploads
ตัวอย่าง cron ทุกวัน 01:30:  30 1 * * * cd /path/to/project && venv/bin/python scripts/backup.py >> logs/backup.log 2>&1

ผลลัพธ์ 1 ชุด: <ปลายทาง>/backup_ปปปปดดวว_ชชนนวว/
    masterlist.db         สำเนาฐานข้อมูล (ตรวจ integrity_check แล้ว)
    local_uploads.tar.gz  ไฟล์เอกสาร
    code.tar.gz           โค้ดโปรเจกต์ (เมื่อใช้ --code) ไม่รวม venv, ฐานข้อมูล, ไฟล์เอกสาร, logs และ backups
                          ***รวมไฟล์ .env ซึ่งมีรหัสลับ*** ชุดสำรองจึงตั้งสิทธิ์ให้เจ้าของอ่านได้คนเดียว
    MANIFEST.sha256       ค่า sha256 ของทุกไฟล์ในชุด ตรวจด้วย: cd <ชุด> && sha256sum -c MANIFEST.sha256
ลบเฉพาะชุดเก่าที่สคริปต์นี้สร้าง (ชื่อตรงรูปแบบ) หลังสำรองชุดใหม่สำเร็จแล้วเท่านั้น

วิธีกู้คืน (หยุดแอปก่อน และเก็บข้อมูลปัจจุบันไว้ก่อนเขียนทับ):
  1. คัดลอก masterlist.db ไปแทนไฟล์ฐานข้อมูล และลบไฟล์ -wal / -shm เดิมของไฟล์นั้น
  2. แตก local_uploads.tar.gz เข้าโฟลเดอร์ที่อยู่เหนือ local_uploads (เช่น <โปรเจกต์>/static)
  3. (ถ้าต้องย้อนโค้ด) แตก code.tar.gz เข้าโฟลเดอร์ที่อยู่เหนือโปรเจกต์
"""

import argparse
import hashlib
import os
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
    sys.path.insert(0, str(PROJECT_ROOT))  # รันตรงจาก scripts/ ต้องหา scripts.* และ utils.* เจอ

DEFAULT_DESTINATION: Path = PROJECT_ROOT / "backups"
DEFAULT_KEEP_COUNT: int = 14
BACKUP_NAME_PATTERN: re.Pattern[str] = re.compile(r"backup_\d{8}_\d{6}")
DATABASE_FILE_NAME: str = "masterlist.db"
UPLOADS_ARCHIVE_NAME: str = "local_uploads.tar.gz"
CODE_ARCHIVE_NAME: str = "code.tar.gz"
MANIFEST_FILE_NAME: str = "MANIFEST.sha256"
PRIVATE_FOLDER_MODE: int = 0o700  # ชุดสำรองมีเอกสารและรหัสลับของบริษัท ให้เจ้าของเข้าถึงได้คนเดียว
PRIVATE_FILE_MODE: int = 0o600
CODE_EXCLUDED_TOP_LEVEL: frozenset[str] = frozenset({"venv", ".venv", "backups", "logs"})
CODE_EXCLUDED_NAMES: frozenset[str] = frozenset({"__pycache__"})
CODE_EXCLUDED_SUFFIXES: tuple[str, ...] = (".db", ".db-wal", ".db-shm", ".pyc")
CODE_EXCLUDED_UPLOAD_PATHS: tuple[tuple[str, str], ...] = (("static", "local_uploads"), ("data", "local_uploads"))
HASH_CHUNK_BYTES: int = 1024 * 1024


class BackupError(Exception):
    """สำรองข้อมูลไม่สำเร็จ (ข้อความเป็นภาษาไทย)"""


def default_db_path() -> Path:
    """ไฟล์ฐานข้อมูลเริ่มต้น: ตัวแปรระบบ DB_FILE_PATH (ไม่อ่านไฟล์ .env) ไม่มีใช้ data/masterlist.db ในโปรเจกต์"""
    configured = os.environ.get("DB_FILE_PATH", "").strip()
    return Path(configured) if configured else PROJECT_ROOT / "data" / DATABASE_FILE_NAME


def default_upload_directory() -> Path:
    """โฟลเดอร์เก็บไฟล์เอกสารเริ่มต้นในโปรเจกต์"""
    return PROJECT_ROOT / "static" / "local_uploads"


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


def _archive_code(code_directory: Path, target: Path, skip: tuple[Path, ...]) -> None:
    """บีบอัดโค้ดโปรเจกต์ โดยตัด venv, ฐานข้อมูล, ไฟล์เอกสาร, logs, backups และโฟลเดอร์ในรายการ skip (ไม่ตาม symlink)"""
    root = code_directory.resolve()
    skipped = tuple(path.resolve() for path in skip)

    def keep(info: tarfile.TarInfo) -> Optional[tarfile.TarInfo]:
        relative = Path(info.name).parts[1:]  # ส่วนแรกคือชื่อโฟลเดอร์โปรเจกต์
        if not relative:
            return info
        if relative[0] in CODE_EXCLUDED_TOP_LEVEL or relative[:2] in CODE_EXCLUDED_UPLOAD_PATHS:
            return None
        if any(part in CODE_EXCLUDED_NAMES for part in relative) or relative[-1].endswith(CODE_EXCLUDED_SUFFIXES):
            return None
        if any(root.joinpath(*relative).is_relative_to(path) for path in skipped):
            return None
        return info

    with tarfile.open(target, "w:gz") as archive:
        archive.add(root, arcname=root.name, filter=keep)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(HASH_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_manifest(folder: Path) -> None:
    """เขียนค่า sha256 ของทุกไฟล์ในชุด (รูปแบบเดียวกับ sha256sum -c)"""
    files = sorted(path for path in folder.iterdir() if path.is_file() and path.name != MANIFEST_FILE_NAME)
    manifest = folder / MANIFEST_FILE_NAME
    manifest.write_text("".join(f"{_sha256(path)}  {path.name}\n" for path in files), encoding="utf-8")


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
    db_path: Path,
    upload_directory: Path,
    destination: Path,
    keep: int = DEFAULT_KEEP_COUNT,
    now: Optional[datetime] = None,
    code_directory: Optional[Path] = None,
) -> Path:
    """สร้างชุดสำรองใหม่ แล้วลบชุดเก่าที่เกินจำนวน

    Args:
        db_path: ไฟล์ฐานข้อมูลต้นทาง
        upload_directory: โฟลเดอร์เอกสารต้นทาง
        destination: โฟลเดอร์ที่เก็บชุดสำรอง
        keep: จำนวนชุดล่าสุดที่เก็บไว้ (อย่างน้อย 1)
        now: เวลาที่ใช้ตั้งชื่อชุด (ไม่ระบุใช้เวลาปัจจุบัน)
        code_directory: โฟลเดอร์โปรเจกต์ที่ต้องการสำรองโค้ดด้วย (ไม่ระบุ = ไม่สำรองโค้ด)

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
    if code_directory is not None and not code_directory.is_dir():
        raise BackupError(f"ไม่พบโฟลเดอร์โปรเจกต์ที่จะสำรองโค้ด: {code_directory}")
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
        if code_directory is not None:
            _archive_code(code_directory, partial_folder / CODE_ARCHIVE_NAME, (destination, partial_folder))
        for path in partial_folder.iterdir():
            path.chmod(PRIVATE_FILE_MODE)
        _write_manifest(partial_folder)
        (partial_folder / MANIFEST_FILE_NAME).chmod(PRIVATE_FILE_MODE)
        partial_folder.rename(final_folder)
    except BaseException:
        shutil.rmtree(partial_folder, ignore_errors=True)
        raise
    _prune_old_backups(destination, keep)
    return final_folder


def main(argv: Optional[list[str]] = None) -> int:
    """จุดเริ่มต้นของคำสั่ง คืนค่า 0 เมื่อสำเร็จ และ 1 เมื่อไม่สำเร็จ"""
    parser = argparse.ArgumentParser(description="สำรองฐานข้อมูล ไฟล์เอกสาร และโค้ด")
    parser.add_argument("--db", type=Path, default=None, help="ไฟล์ฐานข้อมูล (ไม่ระบุ = DB_FILE_PATH หรือ data/masterlist.db)")
    parser.add_argument("--uploads", type=Path, default=None, help="โฟลเดอร์ไฟล์เอกสาร (ไม่ระบุ = static/local_uploads ในโปรเจกต์)")
    parser.add_argument("--code", type=Path, default=None, help="โฟลเดอร์โปรเจกต์ที่ต้องการสำรองโค้ดด้วย (ไม่รวม venv และข้อมูล)")
    parser.add_argument("--dest", type=Path, default=DEFAULT_DESTINATION, help="โฟลเดอร์ปลายทาง ควรอยู่คนละดิสก์กับข้อมูลจริง")
    parser.add_argument("--keep", type=int, default=DEFAULT_KEEP_COUNT, help="จำนวนชุดล่าสุดที่เก็บไว้")
    args = parser.parse_args(argv)
    db_path = args.db or default_db_path()
    upload_directory = args.uploads or default_upload_directory()
    print(f"ฐานข้อมูล: {db_path}\nโฟลเดอร์ไฟล์เอกสาร: {upload_directory}")
    if args.code:
        print(f"โฟลเดอร์โปรเจกต์ (สำรองโค้ด): {args.code}")
    try:
        folder = create_backup(db_path, upload_directory, args.dest, args.keep, code_directory=args.code)
    except (BackupError, OSError, sqlite3.Error, tarfile.TarError) as error:
        print(f"สำรองข้อมูลไม่สำเร็จ: {error}", file=sys.stderr)
        return 1
    print(f"สำรองข้อมูลแล้ว: {folder}")
    if args.code and (args.code / ".env").exists():
        print("คำเตือน: ชุดสำรองโค้ดมีไฟล์ .env (รหัสลับ) เก็บไว้ในที่ปลอดภัย อย่าส่งต่อ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
