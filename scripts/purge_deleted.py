"""ล้างแถวเก่าที่ถูกซ่อนไว้ (is_deleted = 1) และล้าง details ใน Audit Log ของแถวที่ไม่มีอยู่แล้ว

ใช้เฉพาะไลบรารีมาตรฐานของ Python (และ utils/file_removal.py + scripts/backup.py) จึงคัดลอกไปรันที่โฟลเดอร์อื่นได้
โดยไม่ต้องอัปเดตโค้ดหรือ venv ของแอปจริง ให้ระบุ path จริงเองด้วย --db และ --uploads

ค่าเริ่มต้นไม่เปลี่ยนอะไร แค่พิมพ์สรุปจำนวนที่จะลบ:
    python3 scripts/purge_deleted.py --db <ไฟล์ฐานข้อมูล> --uploads <โฟลเดอร์ local_uploads>

หลังตรวจสรุปแล้ว ให้หยุดแอปก่อน จึงสั่งล้างจริง (ระบบสำรองข้อมูลให้ก่อนเสมอ):
    python3 scripts/purge_deleted.py --db ... --uploads ... --apply [--dest โฟลเดอร์ชุดสำรอง]

ถ้าไม่ระบุ --db / --uploads ใช้ค่าเดียวกับ scripts/backup.py (DB_FILE_PATH หรือ data/masterlist.db และ static/local_uploads)
Audit Log ที่ถูกล้างยังเหลือวันเวลา ประเภทการกระทำ และรหัสแถว
ไม่แตะแถวที่ใช้งานอยู่ log ของแถวเหล่านั้น ที่เก็บออนไลน์ Master-List และที่เก็บรุ่นเก่า data/local_uploads

ชุดสำรองมีข้อมูลเก่าครบ (ตั้งใจให้กู้คืนได้) จึงต้องลบเองเมื่อไม่ต้องการแล้ว
วิธีกู้คืนจะพิมพ์ออกมาหลังล้างเสร็จ และอยู่ใน DEPLOY.md
"""

import argparse
import sqlite3
import sys
import tarfile
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))  # รันตรงจาก scripts/ ต้องหา scripts.* และ utils.* เจอ

from scripts.backup import (  # noqa: E402
    DATABASE_FILE_NAME,
    UPLOADS_ARCHIVE_NAME,
    BackupError,
    create_backup,
    default_db_path,
    default_upload_directory,
)
from utils.file_removal import (  # noqa: E402
    FILE_PATH_SEPARATOR,
    FileRemovalPlan,
    count_existing_files,
    execute_removal_plan,
    plan_file_removal,
)

DEFAULT_DESTINATION: Path = PROJECT_ROOT / "backups" / "before_purge"  # แยกจากชุดรายวัน จึงไม่ถูกลบตามรอบของ backup.py
KEEP_ALL_BACKUPS: int = 1000  # สคริปต์นี้ไม่ลบชุดสำรองเก่า
LOCK_TIMEOUT_SECONDS: int = 30
CONFIRM_WORD: str = "PURGE"
REQUIRED_COLUMNS: frozenset[str] = frozenset({"id", "is_deleted", "file_path", "sharepoint_url"})
# ต้องตรงกับ AUDIT_ACTION_DELETE / AUDIT_REDACTED_DETAILS ใน data/database.py (เทสต์ตรวจให้ ไม่ import เพื่อให้รันเดี่ยวได้)
AUDIT_ACTION_DELETE: str = "DELETE"
AUDIT_REDACTED_DETAILS: str = '{"redacted": true}'
DELETE_LOG_DETAILS: str = '{"deleted": true}'
AUDIT_TO_REDACT_SQL: str = (
    "record_id NOT IN (SELECT id FROM transactions WHERE is_deleted = 0) AND action_type <> ? AND details IS NOT ?"
)
AUDIT_TO_REDACT_PARAMS: tuple[str, str] = (AUDIT_ACTION_DELETE, AUDIT_REDACTED_DETAILS)


class PurgeError(Exception):
    """ล้างข้อมูลไม่ได้ (ข้อความเป็นภาษาไทย)"""


@dataclass
class PurgeSummary:
    """สิ่งที่จะเกิดขึ้นถ้าสั่งล้าง"""

    hidden_ids: list[int] = field(default_factory=list)
    active_row_count: int = 0
    audit_counts: dict[str, int] = field(default_factory=dict)  # {ประเภทการกระทำ: จำนวน log ที่จะล้าง details}
    plan: FileRemovalPlan = field(default_factory=FileRemovalPlan)
    referenced_files: int = 0  # ไฟล์ที่แถวที่จะลบอ้างถึง
    existing_referenced_files: int = 0  # ในนั้นมีอยู่จริงบนดิสก์ (ใช้ตรวจว่าชี้ --uploads ถูกที่)
    files_on_disk: int = 0  # ไฟล์ในเครื่องที่จะถูกลบจริง
    online_link_count: int = 0  # แถวที่มีลิงก์ที่เก็บออนไลน์ ซึ่งสคริปต์ไม่ลบ
    legacy_file_count: int = 0  # ไฟล์ในที่เก็บรุ่นเก่าที่สคริปต์ไม่ลบ

    @property
    def has_work(self) -> bool:
        return bool(self.hidden_ids or self.audit_counts)

    @property
    def uploads_path_looks_wrong(self) -> bool:
        """แถวอ้างถึงไฟล์ แต่ไม่พบไฟล์ใดเลยในโฟลเดอร์ที่ระบุ (น่าจะระบุ --uploads ผิด)"""
        return self.referenced_files > 0 and self.existing_referenced_files == 0


@dataclass
class PurgeReport:
    """ผลการล้าง"""

    deleted_count: int = 0
    removed_folders: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)  # ขั้นตอนหรือไฟล์ที่ไม่สำเร็จ


def _check_schema(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(transactions)")}
    has_audit_table = conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'audit_logs'").fetchone()
    if not REQUIRED_COLUMNS <= columns or not has_audit_table:
        raise PurgeError("โครงสร้างฐานข้อมูลเป็นรุ่นเก่า (ไม่มีคอลัมน์ is_deleted / ตาราง audit_logs) จึงไม่ล้างให้ ให้แจ้งทีมพัฒนา")


def _count_legacy_files(file_paths: list[Optional[str]], legacy_directory: Path) -> int:
    names = {
        path.strip().replace("\\", "/").rsplit("/", 1)[-1]
        for file_path in file_paths
        for path in (file_path or "").split(FILE_PATH_SEPARATOR)
        if path.strip()
    }
    return sum(1 for name in names if (legacy_directory / name).is_file())


def read_summary(db_path: Path, upload_directory: Path, legacy_directory: Optional[Path] = None) -> PurgeSummary:
    """อ่านสรุปจากฐานข้อมูลแบบอ่านอย่างเดียว

    Args:
        db_path: ไฟล์ฐานข้อมูล
        upload_directory: โฟลเดอร์ไฟล์เอกสาร (ชื่อโฟลเดอร์ใช้อ่านที่อยู่ไฟล์ที่เก็บในฐานข้อมูล)
        legacy_directory: ที่เก็บรุ่นเก่า (ใช้นับอย่างเดียว ไม่ลบ)

    Returns:
        สิ่งที่จะเกิดขึ้นถ้าสั่งล้าง

    Raises:
        PurgeError: ไม่พบไฟล์ หรือโครงสร้างฐานข้อมูลไม่ตรง
    """
    if not db_path.is_file():
        raise PurgeError(f"ไม่พบไฟล์ฐานข้อมูล: {db_path}")
    with closing(sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)) as conn:
        _check_schema(conn)
        hidden = conn.execute(
            "SELECT id, file_path, sharepoint_url FROM transactions WHERE is_deleted = 1 ORDER BY id"
        ).fetchall()
        active_paths = [row[0] for row in conn.execute("SELECT file_path FROM transactions WHERE is_deleted = 0")]
        audit_counts = dict(
            conn.execute(
                f"SELECT action_type, COUNT(*) FROM audit_logs WHERE {AUDIT_TO_REDACT_SQL} GROUP BY action_type",
                AUDIT_TO_REDACT_PARAMS,
            ).fetchall()
        )
    hidden_paths = [row[1] for row in hidden]
    plan = plan_file_removal(hidden_paths, [path for path in active_paths if path], upload_directory.name)
    existing_own, to_delete = count_existing_files(plan, upload_directory)
    return PurgeSummary(
        hidden_ids=[row[0] for row in hidden],
        active_row_count=len(active_paths),
        audit_counts=audit_counts,
        plan=plan,
        referenced_files=len(plan.own_files),
        existing_referenced_files=existing_own,
        files_on_disk=to_delete,
        online_link_count=sum(1 for row in hidden if row[2]),
        legacy_file_count=_count_legacy_files(hidden_paths, legacy_directory) if legacy_directory else 0,
    )


def format_summary(summary: PurgeSummary, db_path: Path, upload_directory: Path) -> str:
    """ข้อความสรุปสิ่งที่จะลบ (พิมพ์ path ที่ใช้จริงไว้ด้านบนเสมอ)"""
    audit_total = sum(summary.audit_counts.values())
    audit_detail = ", ".join(f"{action} {count}" for action, count in sorted(summary.audit_counts.items()))
    lines = [
        f"ฐานข้อมูล: {db_path} ({db_path.stat().st_size:,} ไบต์)",
        f"โฟลเดอร์ไฟล์เอกสาร: {upload_directory}",
        f"แถวที่ถูกซ่อน ที่จะลบ: {len(summary.hidden_ids)} แถว",
        f"แถวที่ใช้งานอยู่ (ไม่แตะ): {summary.active_row_count} แถว",
        f"Audit Log ที่จะล้างรายละเอียด: {audit_total} รายการ" + (f" ({audit_detail})" if audit_detail else ""),
        f"ไฟล์ที่แถวเหล่านี้อ้างถึง: {summary.referenced_files} ไฟล์ พบบนดิสก์จริง {summary.existing_referenced_files} ไฟล์",
        f"ไฟล์ในเครื่องที่จะลบ: {summary.files_on_disk} ไฟล์ (ลบทั้งโฟลเดอร์ {len(summary.plan.whole_folders)} โฟลเดอร์)",
        f"ไฟล์ที่เก็บไว้เพราะแถวที่ใช้งานยังอ้างถึง: {len(summary.plan.kept_files)} ไฟล์",
        f"แถวที่มีลิงก์ที่เก็บออนไลน์ (ไม่ลบ ต้องลบเองที่ปลายทาง): {summary.online_link_count} แถว",
        f"ไฟล์ในที่เก็บรุ่นเก่า data/local_uploads (ไม่ลบ): {summary.legacy_file_count} ไฟล์",
    ]
    if summary.uploads_path_looks_wrong:
        lines.append(
            "\nคำเตือน: แถวอ้างถึงไฟล์ แต่ไม่พบไฟล์ใดเลยในโฟลเดอร์ไฟล์เอกสารข้างต้น น่าจะระบุ --uploads ผิด "
            "จึงจะไม่ล้างจริงจนกว่าจะแก้ (หรือระบุ --allow-missing-files ถ้าแน่ใจว่าไฟล์ไม่อยู่แล้ว)"
        )
    return "\n".join(lines)


def _purge_database(db_path: Path, expected_hidden_ids: list[int]) -> tuple[list[Optional[str]], list[str]]:
    """ลบแถวที่ซ่อนและล้าง details ใน transaction เดียว ถ้าล้มเหลวฐานข้อมูลไม่เปลี่ยน

    Returns:
        (file_path ของแถวที่ลบ, file_path ของแถวที่เหลือ) อ่านใน transaction เดียวกับการลบ
    """
    with closing(sqlite3.connect(db_path, timeout=LOCK_TIMEOUT_SECONDS, isolation_level=None)) as conn:
        conn.execute("PRAGMA secure_delete = ON")  # เขียนทับพื้นที่ที่ลบ ไม่ให้ข้อความเก่าค้างในไฟล์
        conn.execute("BEGIN IMMEDIATE")
        try:
            hidden = conn.execute("SELECT id, file_path FROM transactions WHERE is_deleted = 1 ORDER BY id").fetchall()
            if [row[0] for row in hidden] != expected_hidden_ids:
                raise PurgeError("ข้อมูลเปลี่ยนระหว่างทำงาน ยังไม่ได้ลบอะไร กรุณาหยุดแอปแล้วรันใหม่")
            conn.execute("DELETE FROM transactions WHERE is_deleted = 1")
            conn.executemany(
                "INSERT INTO audit_logs (action_type, record_id, details) VALUES (?, ?, ?)",
                [(AUDIT_ACTION_DELETE, row[0], DELETE_LOG_DETAILS) for row in hidden],
            )
            conn.execute(
                f"UPDATE audit_logs SET details = ? WHERE {AUDIT_TO_REDACT_SQL}",
                (AUDIT_REDACTED_DETAILS, *AUDIT_TO_REDACT_PARAMS),
            )
            remaining = [row[0] for row in conn.execute("SELECT file_path FROM transactions") if row[0]]
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise
    return [row[1] for row in hidden], remaining


def _compact_database(db_path: Path) -> None:
    """เขียนไฟล์ฐานข้อมูลใหม่ ไม่ให้ข้อความเก่าค้างในพื้นที่ว่างหรือไฟล์ -wal"""
    with closing(sqlite3.connect(db_path, timeout=LOCK_TIMEOUT_SECONDS, isolation_level=None)) as conn:
        conn.execute("VACUUM")
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")


def format_restore_help(backup_folder: Path, db_path: Path, upload_directory: Path) -> str:
    """วิธีกู้คืนจากชุดสำรองนี้ (path จริงของเครื่องนี้)"""
    return "\n".join(
        [
            f"ชุดสำรองอยู่ที่: {backup_folder}",
            "วิธีกู้คืน (หยุดแอปก่อน):",
            f'  cp "{backup_folder / DATABASE_FILE_NAME}" "{db_path}"',
            f'  rm -f "{db_path}-wal" "{db_path}-shm"',
            f'  tar -xzf "{backup_folder / UPLOADS_ARCHIVE_NAME}" -C "{upload_directory.parent}"',
            "ชุดสำรองมีข้อมูลเก่าครบ เก็บไว้ในที่ปลอดภัย และลบเองเมื่อไม่ต้องการแล้ว",
        ]
    )


def apply_purge(
    db_path: Path, upload_directory: Path, summary: PurgeSummary, destination: Path
) -> tuple[Optional[Path], PurgeReport]:
    """สำรองข้อมูล ล้างฐานข้อมูล ลบไฟล์ แล้วเขียนไฟล์ฐานข้อมูลใหม่ สำรองไม่สำเร็จจะไม่แก้อะไรเลย

    Args:
        db_path: ไฟล์ฐานข้อมูล
        upload_directory: โฟลเดอร์ไฟล์เอกสาร
        summary: สรุปที่ผู้ใช้ยืนยันแล้ว
        destination: โฟลเดอร์เก็บชุดสำรอง

    Returns:
        (โฟลเดอร์ชุดสำรอง หรือ None เมื่อไม่มีข้อมูลต้องล้าง, ผลการล้าง)
    """
    report = PurgeReport()
    backup_folder: Optional[Path] = None
    if summary.has_work:
        backup_folder = create_backup(db_path, upload_directory, destination, KEEP_ALL_BACKUPS)
        deleted_paths, remaining_paths = _purge_database(db_path, summary.hidden_ids)
        report.deleted_count = len(deleted_paths)
        plan = plan_file_removal(deleted_paths, remaining_paths, upload_directory.name)
        removal = execute_removal_plan(plan, upload_directory)
        report.removed_folders = removal.removed_folders
        report.failed.extend(removal.failed)
    try:
        _compact_database(db_path)
    except sqlite3.Error as error:
        # ล้างข้อมูลไปแล้ว ต้องแจ้งผลและที่เก็บชุดสำรองต่อ จึงไม่โยน Error ออกไป
        report.failed.append(f"เขียนไฟล์ฐานข้อมูลใหม่ ({error}) ข้อความเก่าอาจค้างในไฟล์ ให้หยุดแอปแล้วรัน --apply ซ้ำ")
    return backup_folder, report


def main(argv: Optional[list[str]] = None, ask: Callable[[str], str] = input) -> int:
    """จุดเริ่มต้นของคำสั่ง คืนค่า 0 เมื่อสำเร็จ และ 1 เมื่อไม่สำเร็จหรือไม่ยืนยัน"""
    parser = argparse.ArgumentParser(description="ล้างแถวที่ถูกซ่อนและรายละเอียดใน Audit Log ของแถวที่ลบแล้ว")
    parser.add_argument("--db", type=Path, default=None, help="ไฟล์ฐานข้อมูล (ไม่ระบุ = DB_FILE_PATH หรือ data/masterlist.db)")
    parser.add_argument("--uploads", type=Path, default=None, help="โฟลเดอร์ไฟล์เอกสาร local_uploads (ไม่ระบุ = static/local_uploads)")
    parser.add_argument("--legacy-uploads", type=Path, default=None, help="ที่เก็บรุ่นเก่า (ใช้นับอย่างเดียว ไม่ลบ)")
    parser.add_argument("--apply", action="store_true", help="ล้างจริง (สำรองข้อมูลก่อนเสมอ) ถ้าไม่ใส่จะพิมพ์สรุปอย่างเดียว")
    parser.add_argument("--yes", action="store_true", help="ไม่ถามยืนยันซ้ำ")
    parser.add_argument("--allow-missing-files", action="store_true", help="ล้างต่อแม้ไม่พบไฟล์ที่แถวอ้างถึงเลย (ปกติถือว่าระบุ --uploads ผิด)")
    parser.add_argument("--dest", type=Path, default=DEFAULT_DESTINATION, help="โฟลเดอร์เก็บชุดสำรอง ควรอยู่คนละดิสก์กับข้อมูลจริง")
    args = parser.parse_args(argv)
    db_path = args.db or default_db_path()
    upload_directory = args.uploads or default_upload_directory()
    legacy_directory = args.legacy_uploads or PROJECT_ROOT / "data" / "local_uploads"
    try:
        summary = read_summary(db_path, upload_directory, legacy_directory)
        print(format_summary(summary, db_path, upload_directory))
        if not args.apply:
            print("\nยังไม่ได้เปลี่ยนอะไร ถ้าสรุปถูกต้อง ให้หยุดแอปแล้วรันอีกครั้งพร้อม --apply")
            return 0
        if summary.uploads_path_looks_wrong and not args.allow_missing_files:
            print("ไม่ได้ล้างอะไร: ตรวจ --uploads แล้วรันใหม่", file=sys.stderr)
            return 1
        if summary.has_work and not args.yes:
            try:
                answer = ask(f"\nพิมพ์ {CONFIRM_WORD} เพื่อยืนยัน (จะสำรองข้อมูลไว้ที่ {args.dest} ก่อน): ")
            except EOFError:
                answer = ""
            if answer.strip() != CONFIRM_WORD:
                print("ยกเลิก ยังไม่ได้เปลี่ยนอะไร")
                return 1
        backup_folder, report = apply_purge(db_path, upload_directory, summary, args.dest)
    except (PurgeError, BackupError, OSError, sqlite3.Error, tarfile.TarError) as error:
        print(f"ล้างข้อมูลไม่สำเร็จ: {error}", file=sys.stderr)
        return 1

    print(f"\nลบแถวที่ถูกซ่อนแล้ว {report.deleted_count} แถว และลบโฟลเดอร์ของแถวแล้ว {len(report.removed_folders)} โฟลเดอร์")
    if backup_folder:
        print(format_restore_help(backup_folder, db_path, upload_directory))
    else:
        print("ไม่มีข้อมูลต้องล้าง จึงไม่ได้สร้างชุดสำรอง")
    if report.failed:
        print(f"มีขั้นตอนที่ไม่สำเร็จ กรุณาตรวจ: {', '.join(report.failed)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
