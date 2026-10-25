"""จัดการฐานข้อมูล SQLite (masterlist.db) สำหรับระบบ IT PR/PO & Tax Invoice MasterList

ไฟล์นี้เป็นที่เดียวที่เขียน SQL ของตาราง transactions
ส่วนหน้าจอ (Streamlit) ให้เรียกใช้ฟังก์ชันจากไฟล์นี้เท่านั้น ห้ามเขียน SQL เอง

หมายเหตุ: ถ้าเกิด Error ทุกฟังก์ชันจะแสดงข้อความด้วย st.error แล้วคืนค่าเริ่มต้น
(None / [] / False) แทนการทำให้แอปล่ม
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

import streamlit as st

# ---------------------------------------------------------------------------
# ค่าคงที่
# ---------------------------------------------------------------------------

# ที่อยู่ไฟล์ฐานข้อมูล (โฟลเดอร์ data/ อยู่ข้างไฟล์นี้)
DB_PATH: Path = Path(__file__).parent / "data" / "masterlist.db"

# รอสูงสุดกี่วินาทีถ้าฐานข้อมูลถูกคนอื่นล็อกอยู่ ก่อนจะถือว่า Error
DB_TIMEOUT_SECONDS: int = 10

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
}

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
    sharepoint_url TEXT                        -- ลิงก์ไฟล์บน SharePoint
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
        yield conn
        conn.commit()
    except Exception:
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


def init_db() -> bool:
    """สร้างตาราง transactions ถ้ายังไม่มี (เรียกซ้ำได้โดยไม่ลบข้อมูลเดิม)

    ควรเรียกครั้งเดียวตอนเริ่มแอป เช่นบนสุดของ app.py

    Returns:
        True ถ้าพร้อมใช้งาน, False ถ้าเกิด Error (จะแสดง st.error ให้แล้ว)
    """
    try:
        with _get_connection() as conn:
            conn.execute(CREATE_TABLE_SQL)
            # ไฟล์ฐานข้อมูลเดิมที่สร้างก่อนมีคอลัมน์ tel/email/contact_name ต้องเพิ่มคอลัมน์ให้ก่อน
            _add_missing_columns(conn)
            # index ช่วยให้กรองตามวันที่/สถานะเร็วขึ้นเมื่อข้อมูลเยอะ
            conn.execute("CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(date)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_transactions_status ON transactions(invoice_status)"
            )
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
                     sharepoint_url)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                ),
            )
            return cursor.lastrowid
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
                "SELECT * FROM transactions WHERE id = ?", (transaction_id,)
            ).fetchone()
        return _row_to_dict(row) if row else None
    except (sqlite3.Error, OSError) as error:
        _show_db_error("ดึงข้อมูลรายการ", error)
        return None


def get_transactions(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    invoice_status: Optional[str] = None,
    keyword: Optional[str] = None,
) -> list[dict[str, Any]]:
    """ดึงรายการทั้งหมด พร้อมตัวกรองที่เลือกใช้ได้ (เรียงใหม่สุดก่อน)

    Args:
        start_date: วันที่เริ่ม "YYYY-MM-DD" (รวมวันนี้) ถ้า None คือไม่จำกัด
        end_date: วันที่สิ้นสุด "YYYY-MM-DD" (รวมวันนี้) ถ้า None คือไม่จำกัด
        invoice_status: กรองตามสถานะใบกำกับภาษี ถ้า None คือทุกสถานะ
        keyword: ค้นหาในชื่อผู้ขาย, เลข PO, เลขรัน PR, เลขผู้เสียภาษี

    Returns:
        list ของ dict (ว่างถ้าไม่พบหรือเกิด Error) ใช้ pd.DataFrame(result) ได้ทันที
    """
    try:
        # สร้างเงื่อนไขทีละข้อ ค่าทั้งหมดส่งผ่าน ? เพื่อกัน SQL Injection
        conditions: list[str] = []
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
            conditions.append(
                "(vendor LIKE ? OR po_no LIKE ? OR pr_run_no LIKE ? OR tax_id LIKE ?)"
            )
            params.extend([f"%{keyword}%"] * 4)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT * FROM transactions {where_clause} ORDER BY date DESC, id DESC"

        with _get_connection() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [_row_to_dict(row) for row in rows]
    except (sqlite3.Error, OSError) as error:
        _show_db_error("ดึงรายการข้อมูล", error)
        return []


def count_transactions() -> int:
    """นับจำนวนรายการทั้งหมดในตาราง transactions

    Returns:
        จำนวนแถวทั้งหมด (0 ถ้าตารางว่าง หรือเกิด Error ซึ่งจะแสดง st.error ให้แล้ว)
    """
    try:
        with _get_connection() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0])
    except (sqlite3.Error, OSError) as error:
        _show_db_error("นับจำนวนรายการ", error)
        return 0


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
        with _get_connection() as conn:
            rows = conn.execute(
                """
                SELECT COALESCE(category, 'ไม่ระบุ') AS category,
                       COUNT(*) AS quantity,
                       COALESCE(SUM(total_price), 0) AS total_price
                FROM transactions
                WHERE date >= ? AND date <= ?
                GROUP BY COALESCE(category, 'ไม่ระบุ')
                """,
                (start_date, end_date),
            ).fetchall()
        return [_row_to_dict(row) for row in rows]
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
            st.error(
                f"❌ แก้ไขข้อมูลไม่สำเร็จ: ไม่รู้จักคอลัมน์ {', '.join(sorted(invalid))} "
                "(แจ้งทีมพัฒนาให้ตรวจชื่อคอลัมน์ที่ส่งเข้ามา)"
            )
            return False

        set_clause = ", ".join(f"{column} = ?" for column in fields)
        params = [*fields.values(), transaction_id]

        with _get_connection() as conn:
            cursor = conn.execute(f"UPDATE transactions SET {set_clause} WHERE id = ?", params)
            updated = cursor.rowcount > 0

        if not updated:
            st.warning(f"⚠️ ไม่พบรายการ id = {transaction_id}")
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
    """ลบรายการ 1 แถวตาม id (ลบแล้วกู้คืนไม่ได้ ควรให้ผู้ใช้กดยืนยันก่อนเรียก)

    Args:
        transaction_id: id ของรายการที่ต้องการลบ

    Returns:
        True ถ้าลบสำเร็จ, False ถ้าไม่พบรายการหรือเกิด Error
    """
    try:
        with _get_connection() as conn:
            cursor = conn.execute("DELETE FROM transactions WHERE id = ?", (transaction_id,))
            deleted = cursor.rowcount > 0

        if not deleted:
            st.warning(f"⚠️ ไม่พบรายการ id = {transaction_id}")
        return deleted
    except (sqlite3.Error, OSError) as error:
        _show_db_error("ลบข้อมูล", error)
        return False
