"""ส่งแถวที่บันทึกในเครื่องไว้แล้วเข้า Master-List อีกครั้ง โดยไม่อัปโหลดไฟล์และไม่สร้างแถวใหม่ในแอป

วิธีใช้ (รันในโฟลเดอร์โปรเจกต์ ด้วย venv ของแอป เพราะอ่านค่า MASTERLIST_* และ DB_FILE_PATH จากไฟล์ .env):
    venv/bin/python scripts/resend_masterlist.py --id 6           # ตรวจก่อน (dry-run) ไม่ส่งอะไรออกเครือข่าย
    venv/bin/python scripts/resend_masterlist.py --id 6 --send    # ส่งจริง 1 แถว

ข้อควรระวัง:
- เปิดฐานข้อมูลแบบอ่านอย่างเดียว ไม่แก้แถว ไม่เรียกขั้นตอนอัปโหลดไฟล์
- requestId คงที่ต่อแถว (uuid5 จากชื่อไฟล์ DB + id แถว) เว็บกันซ้ำด้วย requestId: รัน --send ซ้ำ id เดิมได้ ตอบ ok โดยไม่สร้างแถวซ้ำ
- ถ้าข้อมูลของแถวเปลี่ยนหลังส่งแล้ว เว็บจะไม่อัปเดตแถวเดิม ต้องใช้ requestId ใหม่ และให้แอดมิน Master-List ปฏิเสธแถวเก่า (สคริปต์นี้ยังไม่มีตัวเลือกสร้าง requestId ใหม่)
- แถวต่าง id เป็นรายการต่างกันในสายตาเว็บ: อย่าส่งแถวของ PR เดียวกันมากกว่า 1 แถว
- ส่งทีละแถวและตรวจใน Master-List ทุกครั้ง; ก่อนใช้จริงต้องมีปลายทางทดสอบหรือวิธีลบรายการ
- พิมพ์เฉพาะชื่อฟิลด์ ความยาว requestId และสถานะ "ตั้งค่าแล้ว/ยังไม่ตั้งค่า" ไม่พิมพ์ค่าข้อมูล PR, ชื่อเซิร์ฟเวอร์, URL หรือคีย์
"""

import argparse
import sqlite3
import sys
import uuid
from pathlib import Path
from typing import Any, Optional

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import data.database as database  # noqa: E402
from utils.masterlist_client import (  # noqa: E402
    build_masterlist_payload,
    is_masterlist_configured,
    send_to_masterlist,
    validate_masterlist_payload,
)


# namespace คงที่ของโปรเจกต์นี้ ห้ามเปลี่ยน: เปลี่ยนแล้ว requestId ของทุกแถวเปลี่ยน และเว็บจะมองเป็นรายการใหม่
REQUEST_ID_NAMESPACE: uuid.UUID = uuid.UUID("039de9bb-9750-4007-8de0-5dec080e0329")


def make_request_id(db_path: Path, row_id: int) -> str:
    """requestId คงที่ต่อ (ชื่อไฟล์ DB, id แถว): ส่งซ้ำแล้วเว็บไม่สร้างแถวซ้ำ"""
    return str(uuid.uuid5(REQUEST_ID_NAMESPACE, f"{Path(db_path).name}:{row_id}"))


def load_active_row(transaction_id: int) -> Optional[dict[str, Any]]:
    """อ่านแถวที่ยังไม่ถูกลบแบบอ่านอย่างเดียว (ไม่มีแถว / ถูกลบ / ไม่มีไฟล์ DB = None)"""
    db_path = Path(database.DB_PATH)
    if not db_path.is_file():
        return None
    connection = sqlite3.connect(f"{db_path.resolve().as_uri()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute("SELECT * FROM transactions WHERE id = ? AND is_deleted = 0", (transaction_id,)).fetchone()
    finally:
        connection.close()
    return dict(row) if row else None


def describe_field(value: Any) -> str:
    """บอกความยาว/ชนิดของค่าโดยไม่แสดงค่า"""
    if value is None:
        return "ไม่มีค่า"
    if isinstance(value, str):
        return f"ข้อความยาว {len(value)} ตัวอักษร"
    return type(value).__name__


def main(argv: Optional[list[str]] = None) -> int:
    """คืน 0 เมื่อตรวจผ่าน (dry-run) หรือส่งสำเร็จ และ 1 เมื่อไม่สำเร็จ"""
    parser = argparse.ArgumentParser(description="ส่งแถวที่บันทึกแล้วเข้า Master-List (ค่าเริ่มต้นคือ dry-run)")
    parser.add_argument("--id", type=int, required=True, help="id ของแถวในตาราง transactions (ส่งทีละแถว)")
    parser.add_argument("--send", action="store_true", help="ส่งจริง (ไม่ใส่ = ตรวจอย่างเดียว ไม่ส่ง)")
    args = parser.parse_args(argv)

    row = load_active_row(args.id)
    if row is None:
        print(f"ไม่พบแถว id={args.id} (หรือถูกลบแล้ว) ในฐานข้อมูล จึงไม่ส่ง", file=sys.stderr)
        return 1
    payload = build_masterlist_payload(row)
    problem = validate_masterlist_payload(payload)
    if problem:
        print(problem, file=sys.stderr)
        return 1

    configured = is_masterlist_configured()
    request_id = make_request_id(Path(database.DB_PATH), args.id)
    status = "ตั้งค่าแล้ว" if configured else "ยังไม่ตั้งค่า"
    print(f"แถว id={args.id}: จะส่ง {len(payload)} ฟิลด์ (ปลายทาง Master-List: {status}; ไม่ส่งไฟล์ ไม่สร้างแถวใหม่ในแอป)")
    print(f"  requestId: {request_id} (คงที่ต่อแถว ส่งซ้ำได้โดยเว็บไม่สร้างแถวซ้ำ)")
    for field, value in payload.items():
        print(f"  {field}: {describe_field(value)}")
    if not args.send:
        print("โหมดตรวจ (dry-run): ยังไม่ได้ส่งอะไร ใส่ --send เมื่อพร้อมส่งจริง (ส่งแถวของ PR เดียวกันแค่แถวเดียว; ถ้าข้อมูลแถวเปลี่ยนหลังส่งแล้ว ต้องใช้ requestId ใหม่และให้แอดมินปฏิเสธแถวเก่า)")
        return 0
    if not configured:
        print("ยังไม่ได้ตั้ง MASTERLIST_API_URL ในไฟล์ .env จึงไม่ส่ง", file=sys.stderr)
        return 1

    sent, message = send_to_masterlist(payload, request_id=request_id)
    if not sent:
        print(f"ไม่สำเร็จ: {message}", file=sys.stderr)
        return 1
    print("สำเร็จ: Master-List ตอบ ok ตรวจรายการใน Master-List ว่ามี 1 รายการ และห้ามส่ง id อื่นของ PR เดียวกันซ้ำ\nหมายเหตุ: ถ้าข้อมูลของแถวนี้เปลี่ยนหลังส่งแล้ว เว็บจะไม่อัปเดตแถวเดิม ต้องใช้ requestId ใหม่ และให้แอดมินปฏิเสธแถวเก่า")
    return 0


if __name__ == "__main__":
    sys.exit(main())
