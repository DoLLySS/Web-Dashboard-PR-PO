"""ส่งข้อมูลเข้า Master-List (ตอนนี้เป็น stub: ยังไม่มี API จึงไม่ยิง HTTP จริง)

เมื่อได้ API: ตั้ง MASTERLIST_API_URL ใน .env แล้วเติมการเรียกจริงใน send_to_masterlist
ส่งเฉพาะฟิลด์ที่ Master-List ต้องการ (เท่ากับคอลัมน์ในตาราง Overview) ไม่ส่งไฟล์
"""

from typing import Any, Mapping, Optional

from config.logging_setup import get_logger
from config.settings import get_env_text

logger = get_logger(__name__)

# ฟิลด์ที่ Master-List ต้องการ (ตรงกับ TABLE_COLUMNS ใน pages_ui/overview.py) แก้ที่นี่ที่เดียวเมื่อ API กำหนดฟิลด์แล้ว
MASTERLIST_FIELDS: tuple[str, ...] = (
    "date",
    "vendor",
    "category",
    "total_price",
    "invoice_status",
    "tel",
    "tax_id",
    "pr_run_no",
    "pr_request_date",
    "qt_no",
    "description",
    "unit_price",
    "sharepoint_url",
)


def build_masterlist_payload(record: Mapping[str, Any]) -> dict[str, Any]:
    """คัดเฉพาะฟิลด์ที่ Master-List ต้องการจากรายการทั้งหมด (ฟิลด์ที่ไม่มีใน record ได้ค่า None)"""
    return {field: record.get(field) for field in MASTERLIST_FIELDS}


def is_masterlist_configured() -> bool:
    """ตั้ง MASTERLIST_API_URL แล้วหรือยัง"""
    return bool(get_env_text("MASTERLIST_API_URL"))


def send_to_masterlist(payload: dict[str, Any]) -> tuple[bool, Optional[str]]:
    """ส่ง payload เข้า Master-List

    Returns:
        (ส่งแล้วหรือไม่, ข้อความอธิบายเมื่อยังไม่ได้ส่ง) — ตอนนี้ยังไม่มี API จึงคืน False พร้อมเหตุผลเสมอ
    """
    if not is_masterlist_configured():
        logger.info("ข้ามการส่ง Master-List: ยังไม่ได้ตั้ง MASTERLIST_API_URL (เตรียม payload %d ฟิลด์ไว้แล้ว)", len(payload))
        return False, "รอ API ของ Master-List (เตรียมข้อมูลไว้แล้ว ยังไม่ได้ส่ง)"
    # TODO: ยิง API จริงที่นี่เมื่อได้เอกสาร API (ห้ามใส่ token ในโค้ด อ่านจาก .env)
    return False, "ตั้ง MASTERLIST_API_URL แล้ว แต่ยังไม่ได้เขียนการเรียก API"
