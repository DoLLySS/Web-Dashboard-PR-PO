"""จัดการฐานข้อมูล SQLite (masterlist.db) สำหรับระบบ IT PR/PO & Tax Invoice MasterList

ไฟล์นี้เป็นที่เดียวที่เขียน SQL ของตาราง transactions
ส่วนหน้าจอ (Streamlit) ให้เรียกใช้ฟังก์ชันจากไฟล์นี้เท่านั้น ห้ามเขียน SQL เอง

หมายเหตุ: ถ้าเกิด Error ทุกฟังก์ชันจะแสดงข้อความด้วย st.error แล้วคืนค่าเริ่มต้น
(None / [] / False) แทนการทำให้แอปล่ม
"""

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

import streamlit as st

from config.logging_setup import get_logger
from config.settings import DEFAULT_DB_JOURNAL_MODE, DEFAULT_DB_TIMEOUT_SECONDS, get_env_int, get_env_text

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# ค่าคงที่
# ---------------------------------------------------------------------------

# ที่อยู่ไฟล์ฐานข้อมูล: ค่าเริ่มต้นอยู่โฟลเดอร์ data/ เดียวกับไฟล์นี้
# บน Server ตั้ง DB_FILE_PATH ใน .env ให้ชี้ดิสก์ในเครื่อง (ไม่ใช่ OneDrive / network share ที่ทำให้ไฟล์ SQLite เสียได้)
DB_PATH: Path = Path(get_env_text("DB_FILE_PATH") or Path(__file__).parent / "masterlist.db")

# โหมดบันทึกของ SQLite ที่อนุญาต (กันค่าแปลกจาก .env ไปต่อใน PRAGMA)
ALLOWED_JOURNAL_MODES: frozenset[str] = frozenset({"DELETE", "WAL"})
_requested_journal_mode = get_env_text("DB_JOURNAL_MODE", DEFAULT_DB_JOURNAL_MODE).upper()
DB_JOURNAL_MODE: str = (
    _requested_journal_mode if _requested_journal_mode in ALLOWED_JOURNAL_MODES else DEFAULT_DB_JOURNAL_MODE
)

# รอสูงสุดกี่วินาทีถ้าฐานข้อมูลถูกคนอื่นล็อกอยู่ ก่อนจะถือว่า Error
# ปรับได้ผ่าน DB_TIMEOUT_SECONDS ใน .env (ไม่ใส่ = ค่าเริ่มต้นใน config/settings.py)
DB_TIMEOUT_SECONDS: int = get_env_int("DB_TIMEOUT_SECONDS", DEFAULT_DB_TIMEOUT_SECONDS)

# สถานะใบกำกับภาษี
STATUS_PENDING: str = "รอใบกำกับภาษี"
STATUS_RECEIVED: str = "ได้รับใบกำกับภาษีแล้ว"

# คอลัมน์ที่อนุญาตให้แก้ไขผ่าน update_transaction (กัน SQL Injection จากชื่อคอลัมน์)
UPDATABLE_COLUMNS: frozenset[str] = frozenset(
    {
        "date",
        "vendor",
        "tax_id",
        "po_no",
        "pr_run_no",
        "category",
        "total_price",
        "file_path",
        "invoice_status",
        "tel",
        "email",
        "contact_name",
        "sharepoint_url",
        "pr_request_date",
        "qt_no",
        "description",
        "unit_price",
    }
)

# คอลัมน์ที่เพิ่มภายหลัง: ชื่อคอลัมน์ -> ชนิดข้อมูล
# init_db จะเพิ่มให้อัตโนมัติถ้าไฟล์ฐานข้อมูลเดิมยังไม่มี (ข้อมูลเก่าไม่หาย)
# ถ้าจะเพิ่มคอลัมน์ใหม่ในอนาคต ให้เพิ่มที่นี่ + CREATE_TABLE_SQL + UPDATABLE_COLUMNS + add_transaction
ADDED_COLUMNS: dict[str, str] = {
    "tel": "TEXT",  # เบอร์โทร
    "email": "TEXT",  # อีเมล
    "contact_name": "TEXT",  # ชื่อ (ช่อง Name ในฟอร์ม)
    "sharepoint_url": "TEXT",  # ลิงก์ไฟล์บน SharePoint (กดที่ไอคอนโฟลเดอร์ในตารางเพื่อเปิด)
    # --- ข้อมูลที่สกัดจากเอกสาร PR / Quotation (Master-List) ---
    # หมายเหตุ: "บริษัทที่ติดต่อสั่งซื้อ" ใช้คอลัมน์ vendor และ "เบอร์โทร" ใช้คอลัมน์ tel (ไม่แยกคอลัมน์ซ้ำซ้อน)
    "pr_request_date": "TEXT",  # วันที่ PR รูปแบบ YYYY-MM-DD (ค.ศ.) เหมือนคอลัมน์ date
    "qt_no": "TEXT",  # เลขที่ Quotation
    "description": "TEXT",  # รายละเอียดอุปกรณ์
    "unit_price": "REAL",  # ราคาสุทธิที่รวม Discount แล้ว (บาท)
    # Soft Delete: 0 = ใช้งานปกติ, 1 = ถูกลบ (ซ่อนจากทุกหน้าแต่ข้อมูลยังอยู่ในไฟล์ฐานข้อมูล)
    # ไฟล์ masterlist.db เดิมจะได้คอลัมน์นี้ผ่าน _add_missing_columns โดยแถวเก่าทุกแถวมีค่าเป็น 0
    "is_deleted": "INTEGER NOT NULL DEFAULT 0",
}

# ไฟล์ฐานข้อมูลที่เตรียมตาราง/คอลัมน์/index เสร็จแล้วในรอบการทำงานนี้ของโปรแกรม
# (Streamlit รันสคริปต์ใหม่ทุกครั้งที่ผู้ใช้กดอะไรสักอย่าง ถ้าไม่จำไว้ init_db จะเขียนฐานข้อมูลซ้ำทุกครั้ง
# ซึ่งแย่งล็อกกับผู้ใช้คนอื่นจนเกิด "database is locked")
_initialized_db_paths: set[Path] = set()

# ตัวนับ "เวอร์ชันข้อมูล": เพิ่มทุกครั้งที่มีการเขียนสำเร็จ ใช้เป็นส่วนหนึ่งของ key ของ cache ฝั่งอ่าน
# เขียนแล้ว key เปลี่ยน -> อ่านรอบต่อไปได้ข้อมูลใหม่ทันที (ไม่มีข้อมูลค้างเก่า) ใช้ร่วมกันทุก session ในโปรเซสเดียวกัน
_data_version: int = 0
_data_version_lock = threading.Lock()

# cache ฝั่งอ่านมีอายุสูงสุดเท่านี้ (วินาที) เผื่อมีโปรเซสอื่นเขียนฐานข้อมูลเดียวกัน (ตัวนับด้านบนไม่รู้)
READ_CACHE_TTL_SECONDS: int = 60

CREATE_TABLE_SQL: str = f"""
CREATE TABLE IF NOT EXISTS transactions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    date           TEXT NOT NULL,              -- วันที่เอกสาร รูปแบบ YYYY-MM-DD (ค.ศ.)
    vendor         TEXT NOT NULL,              -- ชื่อผู้ขาย / ร้านค้า
    tax_id         TEXT,                       -- เลขประจำตัวผู้เสียภาษี 13 หลัก
    po_no          TEXT,                       -- เลขที่ PO
    pr_run_no      TEXT,                       -- เลขรัน PR
    category       TEXT,                       -- หมวดหมู่ เช่น Hardware, Software
    total_price    REAL NOT NULL DEFAULT 0,    -- ยอดรวม (บาท)
    file_path      TEXT,                       -- ที่อยู่ไฟล์ที่อัปโหลด
    invoice_status TEXT NOT NULL DEFAULT '{STATUS_PENDING}',
    created_at     TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
    tel            TEXT,                       -- เบอร์โทร
    email          TEXT,                       -- อีเมล
    contact_name   TEXT,                       -- ชื่อ (ช่อง Name ในฟอร์ม)
    sharepoint_url TEXT,                       -- ลิงก์ไฟล์บน SharePoint
    pr_request_date TEXT,                      -- วันที่ PR รูปแบบ YYYY-MM-DD (ค.ศ.)
    qt_no          TEXT,                       -- เลขที่ Quotation
    description    TEXT,                       -- รายละเอียดอุปกรณ์
    unit_price     REAL                        -- ราคาสุทธิที่รวม Discount แล้ว (บาท)
);
"""

# Audit Trail: บันทึกทุกการเพิ่ม/แก้ไข/ลบ (เพิ่มแถวอย่างเดียว ไม่แก้ไขหรือลบ log เดิม)
# ถ้าจะเพิ่มข้อมูลที่เก็บใน log ให้เพิ่มคอลัมน์ที่นี่ + _write_audit_log (ไฟล์เก่าต้องเพิ่มคอลัมน์ด้วย ALTER TABLE)
AUDIT_ACTION_INSERT: str = "INSERT"
AUDIT_ACTION_UPDATE: str = "UPDATE"
AUDIT_ACTION_SOFT_DELETE: str = "SOFT_DELETE"

CREATE_AUDIT_LOGS_SQL: str = """
CREATE TABLE IF NOT EXISTS audit_logs (
    log_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    action_type TEXT NOT NULL,                 -- INSERT / UPDATE / SOFT_DELETE
    record_id   INTEGER NOT NULL,              -- id ของแถวใน transactions ที่ถูกเปลี่ยน
    details     TEXT,                          -- JSON: ค่าที่เพิ่ม / ค่าเดิม->ค่าใหม่ ที่แก้
    timestamp   TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
"""


# ---------------------------------------------------------------------------
# ฟังก์ชันช่วยภายในไฟล์
# ---------------------------------------------------------------------------


def _show_db_error(action: str, error: Exception) -> None:
    """แสดงข้อความ Error ภาษาไทยให้ทีม IT พร้อมวิธีแก้เบื้องต้น

    Args:
        action: คำอธิบายว่ากำลังทำอะไรอยู่ตอนเกิดปัญหา เช่น "บันทึกข้อมูล"
        error: Exception ที่เกิดขึ้น ใช้เลือกข้อความและวิธีแก้ให้ตรงกับสาเหตุ

    Returns:
        ไม่มีค่าคืน (แสดงผลบนหน้าจอด้วย st.error)
    """
    message = str(error).lower()

    # บันทึกลง logs/app.log พร้อมรายละเอียด Error เต็ม ๆ เพื่อให้ทีม IT ย้อนดูได้ภายหลัง
    logger.error("%sไม่สำเร็จ: %s", action, error, exc_info=error)

    if isinstance(error, sqlite3.IntegrityError):
        hint = "ข้อมูลซ้ำหรือไม่ครบตามเงื่อนไข ให้ตรวจช่องที่จำเป็น (วันที่, ผู้ขาย) แล้วลองใหม่"
    elif "locked" in message or "busy" in message:
        hint = (
            "ฐานข้อมูลถูกใช้งานอยู่ ให้รอสักครู่แล้วลองใหม่ "
            "หากยังไม่หาย ให้ตรวจว่าไม่มีโปรแกรมอื่น (เช่น DB Browser) เปิดไฟล์ masterlist.db ค้างไว้"
        )
    elif "readonly" in message or "permission" in message:
        hint = "ไม่มีสิทธิ์เขียนไฟล์ ให้ตรวจสิทธิ์ของโฟลเดอร์ data/ และว่าไฟล์ไม่ได้ถูกตั้งเป็น Read-only"
    elif "unable to open" in message:
        hint = "เปิดไฟล์ฐานข้อมูลไม่ได้ ให้ตรวจว่ามีโฟลเดอร์ data/ และ path ถูกต้อง"
    elif "disk" in message or "full" in message:
        hint = "พื้นที่ดิสก์อาจเต็ม ให้ตรวจพื้นที่ว่างในเครื่องแล้วลองใหม่"
    elif "malformed" in message or "not a database" in message:
        hint = "ไฟล์ฐานข้อมูลอาจเสียหาย ให้กู้คืนจากไฟล์สำรอง (backup) ล่าสุด"
    else:
        hint = "ลองรีเฟรชหน้าเว็บ หากยังเกิดซ้ำให้แจ้งทีม IT พร้อมข้อความด้านล่าง"

    st.error(f"❌ {action}ไม่สำเร็จ: {hint}\n\nรายละเอียดทางเทคนิค: {error}")


@contextmanager
def _get_connection() -> Iterator[sqlite3.Connection]:
    """เปิด connection ของ SQLite แล้วปิดให้อัตโนมัติเมื่อใช้เสร็จ

    ถ้าทำงานสำเร็จจะ commit ให้ ถ้าเกิด Error จะ rollback ให้ แล้วโยน Error ต่อ
    (ผู้เรียกต้องจับ Error เองและเรียก _show_db_error)

    Yields:
        sqlite3.Connection ที่ตั้ง row_factory เป็น sqlite3.Row
        ทำให้อ่านค่าตามชื่อคอลัมน์ได้ เช่น row["vendor"]
    """
    # สร้างโฟลเดอร์ data/ ถ้ายังไม่มี เพื่อไม่ให้เปิดไฟล์ไม่ได้ในการรันครั้งแรก
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(DB_PATH, timeout=DB_TIMEOUT_SECONDS)
    conn.row_factory = sqlite3.Row
    try:
        # WAL ให้ผู้อ่านไม่ขวางผู้เขียน (ค่าถูกจำในไฟล์ DB ตั้งซ้ำทุกครั้งได้ ไม่เสียหาย); ตั้งไม่ได้ก็ใช้โหมดเดิมต่อ
        if DB_JOURNAL_MODE != DEFAULT_DB_JOURNAL_MODE:
            try:
                conn.execute(f"PRAGMA journal_mode={DB_JOURNAL_MODE}")  # ค่ามาจากรายการอนุญาตด้านบนเท่านั้น
            except sqlite3.Error:
                logger.warning("ตั้ง journal_mode=%s ไม่สำเร็จ ใช้โหมดเดิมต่อ", DB_JOURNAL_MODE, exc_info=True)
        yield conn
        conn.commit()
    except BaseException:
        # BaseException = รวมกรณี Streamlit สั่ง rerun/stop กลางทางด้วย เพื่อให้ยกเลิกงานที่ค้างเสมอ
        # (แล้วโยนต่อ ไม่กลบ Error) และ finally ด้านล่างปิด connection ทุกกรณี
        conn.rollback()
        raise
    finally:
        conn.close()


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    """แปลงแถวจากฐานข้อมูลเป็น dict

    Args:
        row: แถวข้อมูล (sqlite3.Row)

    Returns:
        dict ที่ key คือชื่อคอลัมน์ ใช้ต่อกับ pandas.DataFrame ได้ทันที
    """
    return dict(row)


def get_data_version() -> int:
    """คืนเลขเวอร์ชันข้อมูลปัจจุบัน (เปลี่ยนทุกครั้งที่มีการเพิ่ม/แก้/ลบสำเร็จ) ใช้เป็น key ของ cache ฝั่งหน้าจอได้"""
    return _data_version


def _bump_data_version() -> None:
    """เพิ่มเลขเวอร์ชันข้อมูล เรียกหลังเขียนฐานข้อมูลสำเร็จ เพื่อให้ cache ฝั่งอ่านหมดอายุทันที"""
    global _data_version
    with _data_version_lock:
        _data_version += 1


# ---------------------------------------------------------------------------
# สร้างตาราง
# ---------------------------------------------------------------------------


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    """เพิ่มคอลัมน์ใน ADDED_COLUMNS ที่ตาราง transactions ยังไม่มี (ข้อมูลเดิมไม่หาย)

    Args:
        conn: connection ที่เปิดอยู่ (ฟังก์ชันนี้ไม่ commit เอง ให้ _get_connection จัดการ)
    """
    # PRAGMA table_info คืนรายการคอลัมน์ปัจจุบัน แถวที่ 2 (index 1) คือชื่อคอลัมน์
    existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(transactions)")}
    for column_name, column_type in ADDED_COLUMNS.items():
        if column_name not in existing_columns:
            # ชื่อและชนิดมาจากค่าคงที่ในไฟล์นี้เท่านั้น (ไม่ได้มาจากผู้ใช้) จึงใส่ใน SQL ตรง ๆ ได้
            conn.execute(f"ALTER TABLE transactions ADD COLUMN {column_name} {column_type}")


def _write_audit_log(
    conn: sqlite3.Connection,
    action_type: str,
    record_id: int,
    details: dict[str, Any],
) -> None:
    """บันทึก Audit Log 1 แถว โดยใช้ connection เดียวกับการแก้ข้อมูลหลัก

    เพราะใช้ transaction เดียวกัน ถ้าบันทึก log ไม่สำเร็จ การแก้ข้อมูลหลักจะถูก rollback ด้วย
    (และถ้าแก้ข้อมูลหลักไม่สำเร็จ ก็จะไม่มี log ค้าง) ข้อมูลจึงไม่ผิดเพี้ยน

    Args:
        conn: connection ที่กำลังแก้ข้อมูลหลักอยู่ (ฟังก์ชันนี้ไม่ commit เอง)
        action_type: ชนิดการกระทำ เช่น AUDIT_ACTION_INSERT
        record_id: id ของแถวใน transactions
        details: รายละเอียดที่เปลี่ยน จะเก็บเป็น JSON (รองรับภาษาไทย)
    """
    # default=str กันกรณีมีค่าที่ JSON ไม่รู้จัก เช่น วันที่
    details_json = json.dumps(details, ensure_ascii=False, default=str)
    conn.execute(
        "INSERT INTO audit_logs (action_type, record_id, details) VALUES (?, ?, ?)",
        (action_type, record_id, details_json),
    )


def init_db() -> bool:
    """สร้างตาราง transactions ถ้ายังไม่มี (เรียกซ้ำได้โดยไม่ลบข้อมูลเดิม)

    ควรเรียกตอนเริ่มแอป เช่นบนสุดของ app.py (เรียกทุกรอบได้ ฟังก์ชันจำไว้ว่าเตรียมแล้ว จะไม่เขียนฐานข้อมูลซ้ำ)
    ถ้าไฟล์ฐานข้อมูลถูกลบระหว่างแอปทำงาน จะเตรียมใหม่ให้อัตโนมัติ

    Returns:
        True ถ้าพร้อมใช้งาน, False ถ้าเกิด Error (จะแสดง st.error ให้แล้ว)
    """
    if DB_PATH in _initialized_db_paths and DB_PATH.exists():
        return True

    try:
        with _get_connection() as conn:
            conn.execute(CREATE_TABLE_SQL)
            # ตาราง Audit Trail (ไฟล์ฐานข้อมูลเดิมจะได้ตารางนี้เพิ่มโดยข้อมูลเก่าไม่หาย)
            conn.execute(CREATE_AUDIT_LOGS_SQL)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_logs_record ON audit_logs(record_id)")
            # ไฟล์ฐานข้อมูลเดิมที่สร้างก่อนมีคอลัมน์ tel/email/contact_name ต้องเพิ่มคอลัมน์ให้ก่อน
            _add_missing_columns(conn)
            logger.debug("ตรวจ/เพิ่มคอลัมน์ที่ขาดในตาราง transactions เรียบร้อย")
            # index ช่วยให้กรองตามวันที่/สถานะเร็วขึ้นเมื่อข้อมูลเยอะ
            conn.execute("CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(date)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_transactions_status ON transactions(invoice_status)")
            # ทุกคำสั่งอ่านกรอง is_deleted = 0 แล้วเรียง/กรองตามวันที่ -> index รวมช่วยให้ไม่ต้องสแกนทั้งตาราง
            conn.execute("CREATE INDEX IF NOT EXISTS idx_transactions_active_date ON transactions(is_deleted, date)")
        _initialized_db_paths.add(DB_PATH)
        logger.info("เตรียมฐานข้อมูลเรียบร้อย: %s", DB_PATH)
        return True
    except (sqlite3.Error, OSError) as error:
        _show_db_error("เตรียมฐานข้อมูล", error)
        return False


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------


def add_transaction(
    date: str,
    vendor: str,
    total_price: float,
    tax_id: Optional[str] = None,
    po_no: Optional[str] = None,
    pr_run_no: Optional[str] = None,
    category: Optional[str] = None,
    file_path: Optional[str] = None,
    invoice_status: str = STATUS_PENDING,
    tel: Optional[str] = None,
    email: Optional[str] = None,
    contact_name: Optional[str] = None,
    sharepoint_url: Optional[str] = None,
    pr_request_date: Optional[str] = None,
    qt_no: Optional[str] = None,
    description: Optional[str] = None,
    unit_price: Optional[float] = None,
    created_at: Optional[str] = None,
) -> Optional[int]:
    """เพิ่มรายการใหม่ 1 แถวลงตาราง transactions

    Args:
        date: วันที่เอกสาร รูปแบบ "YYYY-MM-DD" (ค.ศ.)
        vendor: ชื่อผู้ขาย (ห้ามว่าง)
        total_price: ยอดรวมเป็นบาท
        tax_id: เลขประจำตัวผู้เสียภาษี (ไม่บังคับ)
        po_no: เลขที่ PO (ไม่บังคับ)
        pr_run_no: เลขรัน PR (ไม่บังคับ)
        category: หมวดหมู่ (ไม่บังคับ)
        file_path: ที่อยู่ไฟล์ที่อัปโหลด (ไม่บังคับ)
        invoice_status: สถานะใบกำกับภาษี ค่าเริ่มต้นคือ "รอใบกำกับภาษี"
        tel: เบอร์โทร (ไม่บังคับ)
        email: อีเมล (ไม่บังคับ)
        contact_name: ชื่อ (ช่อง Name ในฟอร์ม ไม่บังคับ)
        sharepoint_url: ลิงก์ไฟล์บน SharePoint ขึ้นต้นด้วย http(s):// (ไม่บังคับ)
        pr_request_date: วันที่ PR รูปแบบ "YYYY-MM-DD" (ค.ศ. ไม่บังคับ)
        qt_no: เลขที่ Quotation (ไม่บังคับ)
        description: รายละเอียดอุปกรณ์ (ไม่บังคับ)
        unit_price: ราคาสุทธิที่รวม Discount แล้ว เป็นบาท (ไม่บังคับ)
        created_at: วันเวลาที่ Upload รูปแบบ "YYYY-MM-DD HH:MM:SS" ใช้นับวันที่ค้าง (ไม่ระบุ = เวลาปัจจุบันของเครื่อง)

    Returns:
        id ของแถวที่เพิ่ม, หรือ None ถ้าบันทึกไม่สำเร็จ
    """
    try:
        # ตรวจค่าที่จำเป็นก่อน เพื่อให้ข้อความแจ้งผู้ใช้ชัดกว่า error ของ SQLite
        if not date or not vendor.strip():
            st.error("❌ บันทึกข้อมูลไม่สำเร็จ: กรุณากรอก 'วันที่' และ 'ผู้ขาย' ให้ครบ")
            return None

        with _get_connection() as conn:
            cursor = conn.execute(
                """
                INSERT INTO transactions
                    (date, vendor, tax_id, po_no, pr_run_no, category,
                     total_price, file_path, invoice_status, tel, email, contact_name,
                     sharepoint_url, pr_request_date, qt_no, description, unit_price, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        COALESCE(?, datetime('now', 'localtime')))
                """,
                (
                    date,
                    vendor.strip(),
                    tax_id,
                    po_no,
                    pr_run_no,
                    category,
                    total_price,
                    file_path,
                    invoice_status,
                    tel,
                    email,
                    contact_name,
                    sharepoint_url,
                    pr_request_date,
                    qt_no,
                    description,
                    unit_price,
                    created_at,
                ),
            )
            new_transaction_id = cursor.lastrowid
            # บันทึก log ใน transaction เดียวกับการ INSERT (ถ้า log พลาด แถวใหม่จะถูก rollback)
            inserted_values = {
                "date": date,
                "vendor": vendor.strip(),
                "tax_id": tax_id,
                "po_no": po_no,
                "pr_run_no": pr_run_no,
                "category": category,
                "total_price": total_price,
                "file_path": file_path,
                "invoice_status": invoice_status,
                "tel": tel,
                "email": email,
                "contact_name": contact_name,
                "sharepoint_url": sharepoint_url,
                "pr_request_date": pr_request_date,
                "qt_no": qt_no,
                "description": description,
                "unit_price": unit_price,
            }
            _write_audit_log(conn, AUDIT_ACTION_INSERT, new_transaction_id, inserted_values)
        _bump_data_version()
        logger.info("เพิ่มรายการใหม่ id=%s (ผู้ขาย: %s)", new_transaction_id, vendor.strip())
        return new_transaction_id
    except (sqlite3.Error, OSError, AttributeError) as error:
        _show_db_error("บันทึกข้อมูล", error)
        return None


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------


def get_transaction(transaction_id: int) -> Optional[dict[str, Any]]:
    """ดึงรายการ 1 แถวตาม id

    Args:
        transaction_id: id ของรายการที่ต้องการ

    Returns:
        dict ของรายการ, หรือ None ถ้าไม่พบหรือเกิด Error
    """
    try:
        with _get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM transactions WHERE id = ? AND is_deleted = 0", (transaction_id,)
            ).fetchone()
        return _row_to_dict(row) if row else None
    except (sqlite3.Error, OSError) as error:
        _show_db_error("ดึงข้อมูลรายการ", error)
        return None


def _fetch_transactions(
    start_date: Optional[str],
    end_date: Optional[str],
    invoice_status: Optional[str],
    keyword: Optional[str],
) -> list[dict[str, Any]]:
    """อ่านรายการจากฐานข้อมูลตามตัวกรอง (ไม่จับ Error ให้ผู้เรียกจัดการ เพื่อไม่ให้ cache เก็บผลที่พลาด)"""
    # สร้างเงื่อนไขทีละข้อ ค่าทั้งหมดส่งผ่าน ? เพื่อกัน SQL Injection
    # Soft Delete: ไม่แสดงรายการที่ถูกลบ (is_deleted = 1) ในทุกกรณี
    conditions: list[str] = ["is_deleted = 0"]
    params: list[Any] = []

    if start_date:
        conditions.append("date >= ?")
        params.append(start_date)
    if end_date:
        conditions.append("date <= ?")
        params.append(end_date)
    if invoice_status:
        conditions.append("invoice_status = ?")
        params.append(invoice_status)
    if keyword:
        # ค้นเฉพาะชื่อผู้ขายและเบอร์โทร; เบอร์โทรเทียบแบบไม่สนขีด/ช่องว่าง (081-234 ตรงกับ 081234)
        phone_keyword = keyword.replace("-", "").replace(" ", "")
        phone_condition = "REPLACE(REPLACE(COALESCE(tel, ''), '-', ''), ' ', '') LIKE ?"
        if phone_keyword:
            conditions.append(f"(vendor LIKE ? OR tel LIKE ? OR {phone_condition})")
            params.extend([f"%{keyword}%", f"%{keyword}%", f"%{phone_keyword}%"])
        else:
            conditions.append("vendor LIKE ?")
            params.append(f"%{keyword}%")

    where_clause = f"WHERE {' AND '.join(conditions)}"
    sql = f"SELECT * FROM transactions {where_clause} ORDER BY date DESC, id DESC"

    with _get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_dict(row) for row in rows]


@st.cache_data(ttl=READ_CACHE_TTL_SECONDS, show_spinner=False)
def _fetch_transactions_cached(
    data_version: int,
    start_date: Optional[str],
    end_date: Optional[str],
    invoice_status: Optional[str],
    keyword: Optional[str],
) -> list[dict[str, Any]]:
    """อ่านรายการแบบจำ (cache) ตาม data_version + ตัวกรอง; เขียนข้อมูลเมื่อไรเลขเวอร์ชันเปลี่ยนและอ่านใหม่ทันที

    Streamlit คืนสำเนาให้ทุกครั้ง ผู้เรียกแก้ list/dict ที่ได้รับได้โดยไม่กระทบ cache
    """
    return _fetch_transactions(start_date, end_date, invoice_status, keyword)


def get_transactions(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    invoice_status: Optional[str] = None,
    keyword: Optional[str] = None,
) -> list[dict[str, Any]]:
    """ดึงรายการทั้งหมด พร้อมตัวกรองที่เลือกใช้ได้ (เรียงใหม่สุดก่อน)

    ผลถูกจำไว้ตามเวอร์ชันข้อมูล (get_data_version) จึงเรียกซ้ำใน rerun ถัดไปได้โดยไม่ query ใหม่
    จนกว่าจะมีการเพิ่ม/แก้/ลบ

    Args:
        start_date: วันที่เริ่ม "YYYY-MM-DD" (รวมวันนี้) ถ้า None คือไม่จำกัด
        end_date: วันที่สิ้นสุด "YYYY-MM-DD" (รวมวันนี้) ถ้า None คือไม่จำกัด
        invoice_status: กรองตามสถานะใบกำกับภาษี ถ้า None คือทุกสถานะ
        keyword: ค้นหาเฉพาะชื่อผู้ขาย (Vendor) และเบอร์โทร (Tel.)

    Returns:
        list ของ dict (ว่างถ้าไม่พบหรือเกิด Error) ใช้ pd.DataFrame(result) ได้ทันที
    """
    try:
        return _fetch_transactions_cached(get_data_version(), start_date, end_date, invoice_status, keyword)
    except (sqlite3.Error, OSError) as error:
        _show_db_error("ดึงรายการข้อมูล", error)
        return []


def count_transactions() -> int:
    """นับจำนวนรายการที่ยังใช้งานอยู่ในตาราง transactions (ไม่นับรายการที่ถูกลบแบบ Soft Delete)

    Returns:
        จำนวนแถวที่ยังไม่ถูกลบ (0 ถ้าตารางว่าง หรือเกิด Error ซึ่งจะแสดง st.error ให้แล้ว)
    """
    try:
        with _get_connection() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM transactions WHERE is_deleted = 0").fetchone()[0])
    except (sqlite3.Error, OSError) as error:
        _show_db_error("นับจำนวนรายการ", error)
        return 0


def _fetch_unique_vendors() -> list[str]:
    """อ่านรายชื่อผู้ขายไม่ซ้ำจากฐานข้อมูล (ไม่จับ Error ให้ผู้เรียกจัดการ)"""
    with _get_connection() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT TRIM(vendor) AS vendor
            FROM transactions
            WHERE vendor IS NOT NULL AND TRIM(vendor) <> '' AND is_deleted = 0
            ORDER BY vendor COLLATE NOCASE
            """
        ).fetchall()
    return [row["vendor"] for row in rows]


@st.cache_data(ttl=READ_CACHE_TTL_SECONDS, show_spinner=False)
def _fetch_unique_vendors_cached(data_version: int) -> list[str]:
    """รายชื่อผู้ขายแบบจำ (cache) ตาม data_version"""
    return _fetch_unique_vendors()


def get_unique_vendors() -> list[str]:
    """ดึงรายชื่อผู้ขายที่มีอยู่ในระบบ (ไม่ซ้ำ เรียง ก-ฮ / A-Z) ไว้ใช้เป็นตัวเลือก Auto-complete

    Returns:
        list ของชื่อผู้ขาย (ว่างถ้ายังไม่มีข้อมูลเลย หรือเกิด Error ซึ่งจะแสดง st.error ให้แล้ว)
    """
    try:
        return _fetch_unique_vendors_cached(get_data_version())
    except (sqlite3.Error, OSError) as error:
        _show_db_error("ดึงรายชื่อผู้ขาย", error)
        return []


def _fetch_category_counts(start_date: str, end_date: str) -> list[dict[str, Any]]:
    """อ่านสรุปตามหมวดหมู่จากฐานข้อมูล (ไม่จับ Error ให้ผู้เรียกจัดการ)"""
    with _get_connection() as conn:
        rows = conn.execute(
            """
            SELECT COALESCE(category, 'ไม่ระบุ') AS category,
                   COUNT(*) AS quantity,
                   COALESCE(SUM(total_price), 0) AS total_price
            FROM transactions
            WHERE date >= ? AND date <= ? AND is_deleted = 0
            GROUP BY COALESCE(category, 'ไม่ระบุ')
            """,
            (start_date, end_date),
        ).fetchall()
    return [_row_to_dict(row) for row in rows]


@st.cache_data(ttl=READ_CACHE_TTL_SECONDS, show_spinner=False)
def _fetch_category_counts_cached(data_version: int, start_date: str, end_date: str) -> list[dict[str, Any]]:
    """สรุปตามหมวดหมู่แบบจำ (cache) ตาม data_version + ช่วงวันที่"""
    return _fetch_category_counts(start_date, end_date)


def get_category_counts(start_date: str, end_date: str) -> list[dict[str, Any]]:
    """สรุปจำนวนรายการและยอดรวมแยกตามหมวดหมู่ ในช่วงวันที่ที่กำหนด

    Args:
        start_date: วันที่เริ่ม "YYYY-MM-DD" (รวมวันนี้)
        end_date: วันที่สิ้นสุด "YYYY-MM-DD" (รวมวันนี้)

    Returns:
        list ของ dict คีย์ category (ว่างเป็น "ไม่ระบุ"), quantity (จำนวนรายการ), total_price
        (ว่างถ้าไม่พบหรือเกิด Error)
    """
    try:
        return _fetch_category_counts_cached(get_data_version(), start_date, end_date)
    except (sqlite3.Error, OSError) as error:
        _show_db_error("สรุปจำนวนตามหมวดหมู่", error)
        return []


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------


def update_transaction(transaction_id: int, **fields: Any) -> bool:
    """แก้ไขเฉพาะคอลัมน์ที่ส่งมา เช่น update_transaction(5, vendor="ABC", total_price=1500)

    Args:
        transaction_id: id ของรายการที่ต้องการแก้
        **fields: คอลัมน์และค่าใหม่ ต้องอยู่ใน UPDATABLE_COLUMNS

    Returns:
        True ถ้าแก้สำเร็จ, False ถ้าไม่พบรายการ / ชื่อคอลัมน์ไม่ถูกต้อง / เกิด Error
    """
    try:
        if not fields:
            st.warning("⚠️ ไม่มีข้อมูลที่ต้องแก้ไข")
            return False

        # อนุญาตเฉพาะคอลัมน์ในรายการที่กำหนด เพราะชื่อคอลัมน์ใส่ ? ไม่ได้
        invalid = set(fields) - UPDATABLE_COLUMNS
        if invalid:
            logger.error("แก้ไขรายการ id=%s ถูกปฏิเสธ: ไม่รู้จักคอลัมน์ %s", transaction_id, sorted(invalid))
            st.error(f"❌ แก้ไขข้อมูลไม่สำเร็จ: ไม่รู้จักคอลัมน์ {', '.join(sorted(invalid))} (แจ้งทีมพัฒนาให้ตรวจชื่อคอลัมน์ที่ส่งเข้ามา)")
            return False

        set_clause = ", ".join(f"{column} = ?" for column in fields)
        params = [*fields.values(), transaction_id]

        with _get_connection() as conn:
            # อ่านค่าเดิมก่อนแก้ (ใน connection เดียวกัน) เพื่อบันทึกใน log ว่าเปลี่ยนจากอะไรเป็นอะไร
            old_row = conn.execute(
                "SELECT * FROM transactions WHERE id = ? AND is_deleted = 0", (transaction_id,)
            ).fetchone()
            # แก้ไขได้เฉพาะรายการที่ยังไม่ถูกลบ
            cursor = conn.execute(f"UPDATE transactions SET {set_clause} WHERE id = ? AND is_deleted = 0", params)
            updated = cursor.rowcount > 0

            if updated and old_row is not None:
                # เก็บเฉพาะคอลัมน์ที่ค่าเปลี่ยนจริง; ถ้าไม่มีอะไรเปลี่ยนก็ไม่ต้องมี log
                changes = {
                    column: {"old": old_row[column], "new": new_value}
                    for column, new_value in fields.items()
                    if old_row[column] != new_value
                }
                if changes:
                    _write_audit_log(conn, AUDIT_ACTION_UPDATE, transaction_id, changes)

        if not updated:
            logger.warning("แก้ไขไม่สำเร็จ: ไม่พบรายการ id=%s", transaction_id)
            st.warning(f"⚠️ ไม่พบรายการ id = {transaction_id}")
        else:
            _bump_data_version()
            logger.info("แก้ไขรายการ id=%s คอลัมน์: %s", transaction_id, ", ".join(sorted(fields)))
        return updated
    except (sqlite3.Error, OSError) as error:
        _show_db_error("แก้ไขข้อมูล", error)
        return False


def mark_invoice_received(transaction_id: int) -> bool:
    """เปลี่ยนสถานะรายการเป็น "ได้รับใบกำกับภาษีแล้ว" (ทางลัดของ update_transaction)

    Args:
        transaction_id: id ของรายการ

    Returns:
        True ถ้าสำเร็จ, False ถ้าไม่สำเร็จ
    """
    return update_transaction(transaction_id, invoice_status=STATUS_RECEIVED)


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------


def delete_transaction(transaction_id: int) -> bool:
    """ลบรายการ 1 แถวตาม id แบบ Soft Delete (ตั้ง is_deleted = 1 ข้อมูลยังอยู่ในฐานข้อมูล แต่ไม่แสดงผล)

    Args:
        transaction_id: id ของรายการที่ต้องการลบ

    Returns:
        True ถ้าลบสำเร็จ, False ถ้าไม่พบรายการ (หรือถูกลบไปแล้ว) หรือเกิด Error
    """
    try:
        with _get_connection() as conn:
            cursor = conn.execute(
                "UPDATE transactions SET is_deleted = 1 WHERE id = ? AND is_deleted = 0",
                (transaction_id,),
            )
            deleted = cursor.rowcount > 0
            if deleted:
                # บันทึก log ใน transaction เดียวกับการ UPDATE is_deleted
                _write_audit_log(conn, AUDIT_ACTION_SOFT_DELETE, transaction_id, {"is_deleted": 1})

        if not deleted:
            logger.warning("ลบไม่สำเร็จ: ไม่พบรายการ id=%s", transaction_id)
            st.warning(f"⚠️ ไม่พบรายการ id = {transaction_id}")
        else:
            _bump_data_version()
            logger.info("ลบรายการ id=%s", transaction_id)
        return deleted
    except (sqlite3.Error, OSError) as error:
        _show_db_error("ลบข้อมูล", error)
        return False


def delete_transactions(transaction_ids: list[int]) -> int:
    """ลบหลายรายการแบบ Soft Delete ใน connection/transaction เดียว (เร็วกว่าเรียก delete_transaction ทีละแถว)

    Args:
        transaction_ids: id ของรายการที่ต้องการลบ

    Returns:
        จำนวนรายการที่ลบสำเร็จ (ไม่พบ/ถูกลบไปแล้วไม่นับ; 0 ถ้าเกิด Error ซึ่งจะแสดง st.error ให้แล้ว)
    """
    if not transaction_ids:
        return 0
    try:
        deleted_count = 0
        with _get_connection() as conn:
            for transaction_id in transaction_ids:
                cursor = conn.execute(
                    "UPDATE transactions SET is_deleted = 1 WHERE id = ? AND is_deleted = 0",
                    (transaction_id,),
                )
                if cursor.rowcount > 0:
                    deleted_count += 1
                    _write_audit_log(conn, AUDIT_ACTION_SOFT_DELETE, transaction_id, {"is_deleted": 1})
        if deleted_count:
            _bump_data_version()
            logger.info("ลบรายการ %s รายการ (batch)", deleted_count)
        return deleted_count
    except (sqlite3.Error, OSError) as error:
        _show_db_error("ลบข้อมูล", error)
        return 0
