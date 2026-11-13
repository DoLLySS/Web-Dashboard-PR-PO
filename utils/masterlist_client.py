"""ส่งข้อมูลแถวเข้า Master-List ผ่าน HTTP API ของเว็บ Master-List (เจ้าของเว็บยืนยันสเปกแล้ว แต่ยังไม่เคยส่งจริง ทดสอบกับเซิร์ฟเวอร์ปลอมเท่านั้น)

ข้อตกลงกับ Master-List (ปลายทางปัจจุบัน POST <host>/api/pr-po/ingest ตั้งเป็น MASTERLIST_API_URL):
    คำขอ  POST JSON  {"requestId": "<uuid>", "record": {13 ฟิลด์ใน MASTERLIST_FIELDS}}  header X-Api-Key (ถ้าตั้ง)
          requestId สร้างใหม่ (uuid4) ต่อการส่ง 1 แถว และเท่าเดิมทุกครั้งที่ retry
          เว็บกันซ้ำด้วย requestId (unique index): ส่งซ้ำ requestId เดิมตอบ 200 {"ok": true} โดยไม่สร้างแถวซ้ำ
          แต่ถ้าส่ง requestId เดิมพร้อมข้อมูลที่แก้แล้ว เว็บไม่อัปเดตแถวเดิม (ต้องใช้ requestId ใหม่ และให้แอดมินปฏิเสธแถวเก่า)
    คำตอบ 200 JSON  {"ok": true}
          ข้อมูลผิด 400 JSON  {"error": "record.vendor: too long (max 300)"}  (บอกชื่อฟิลด์ที่ผิด)
    ความยาวสูงสุดที่ทราบ: ดู MASTERLIST_MAX_LENGTHS
ตั้งค่าใน .env: MASTERLIST_API_URL (มีลายเซ็นลับ ถือเป็นรหัสผ่าน), MASTERLIST_API_KEY (ไม่บังคับ), MASTERLIST_TIMEOUT_SECONDS (ค่าเริ่มต้น 30)
          MASTERLIST_ALLOW_HTTP=1 (ค่าเริ่มต้นปิด) ให้ใช้ http:// ไป IP ภายใน 10.x / 172.16-31.x / 192.168.x ได้ (ส่งแบบไม่เข้ารหัส ใช้ทดสอบเท่านั้น; มีผลเฉพาะ Master-List)
ส่งเฉพาะฟิลด์ที่ Master-List ต้องการ (เท่ากับคอลัมน์ในตาราง Overview) ไม่ส่งไฟล์ ไม่ส่ง path ในเครื่อง
"""

import uuid
from typing import Any, Mapping, Optional

from config.logging_setup import get_logger
from config.settings import DEFAULT_MASTERLIST_TIMEOUT_SECONDS, get_env_text
from utils.power_automate_api import FlowTarget, PowerAutomateError, post_json_to_flow, prepare_flow_call

logger = get_logger(__name__)

URL_SETTING: str = "MASTERLIST_API_URL"
MASTERLIST_TARGET: FlowTarget = FlowTarget(
    url_setting=URL_SETTING,
    key_setting="MASTERLIST_API_KEY",
    timeout_setting="MASTERLIST_TIMEOUT_SECONDS",
    default_timeout=DEFAULT_MASTERLIST_TIMEOUT_SECONDS,
    maybe_created_hint="รายการอาจถูกสร้างใน Master-List ไปแล้ว ตรวจใน Master-List ก่อนส่งซ้ำ (รายการเก็บในเครื่องแล้ว)",
    what="รายการ",
    kept_hint="รายการเก็บในเครื่องแล้ว",
    allow_http_setting="MASTERLIST_ALLOW_HTTP",
)

# ความยาวสูงสุดที่เจ้าของเว็บ Master-List แจ้ง (ฟิลด์อื่นยังไม่ทราบขีดจำกัด จึงไม่ตรวจ) นับเป็นจำนวนอักขระ
# TODO: ยังไม่ทราบว่าเว็บนับเป็นอักขระ / byte / UTF-16 ถ้านับ byte ภาษาไทยจะเกินเร็วกว่านี้ (ถามเจ้าของเว็บ)
MASTERLIST_MAX_LENGTHS: dict[str, int] = {
    "vendor": 300,
    "description": 5000,
    "invoice_status": 100,
    "date": 64,
}

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


def validate_masterlist_payload(payload: Mapping[str, Any]) -> Optional[str]:
    """ตรวจความยาวของฟิลด์ที่ทราบขีดจำกัด คืนข้อความบอกฟิลด์ที่เกิน (ชื่อฟิลด์กับความยาวเท่านั้น ไม่แสดงค่า) หรือ None ถ้าผ่าน"""
    problems: list[str] = []
    for field, limit in MASTERLIST_MAX_LENGTHS.items():
        value = payload.get(field)
        if isinstance(value, str) and len(value) > limit:
            problems.append(f"{field} ยาว {len(value)} ตัวอักษร (Master-List รับสูงสุด {limit})")
    if not problems:
        return None
    return "ไม่ได้ส่งเข้า Master-List เพราะข้อมูลยาวเกิน: " + "; ".join(problems) + " แก้ข้อมูลแล้วส่งใหม่ (รายการเก็บในเครื่องแล้ว)"


def is_masterlist_configured() -> bool:
    """ตั้ง MASTERLIST_API_URL แล้วหรือยัง"""
    return bool(get_env_text(URL_SETTING))


def send_to_masterlist(payload: dict[str, Any], request_id: Optional[str] = None) -> tuple[bool, Optional[str]]:
    """ส่ง payload เข้า Master-List (POST {"requestId", "record"}; ต้องตอบ 200 {"ok": true})

    ไม่ raise: การส่งล้มเหลวต้องไม่ทำให้การบันทึกรายการล้ม (แถวและไฟล์ในเครื่องบันทึกไปก่อนแล้ว)
    retry เฉพาะ 429/503 ด้วย requestId เดิม ส่วน timeout / 502 / 504 / การเชื่อมต่อหลุด / คำตอบรูปแบบผิดไม่ retry
    เพราะปลายทางอาจสร้างรายการไปแล้ว ฟิลด์ที่ยาวเกินขีดจำกัดที่ทราบจะไม่ถูกส่ง (ดู validate_masterlist_payload)

    Args:
        request_id: ไม่ระบุ = uuid4 ใหม่ทุกครั้ง (แอปหลักใช้แบบนี้) สคริปต์ส่งซ้ำระบุค่าคงที่ต่อแถวเพื่อให้เว็บกันซ้ำ

    Returns:
        (ส่งแล้วหรือไม่, ข้อความอธิบายเมื่อยังไม่ได้ส่ง; ไม่มี URL / คีย์)
    """
    if not is_masterlist_configured():
        logger.info("ข้ามการส่ง Master-List: ยังไม่ได้ตั้ง %s (เตรียม payload %d ฟิลด์ไว้แล้ว)", URL_SETTING, len(payload))
        return False, "ยังไม่ได้ตั้งค่า Master-List (เตรียมข้อมูลไว้แล้ว ยังไม่ได้ส่ง)"
    too_long = validate_masterlist_payload(payload)
    if too_long:
        logger.warning("ไม่ส่ง Master-List: %s", too_long)  # มีแต่ชื่อฟิลด์และความยาว ไม่มีค่าของข้อมูล
        return False, too_long
    try:
        prepared = prepare_flow_call(MASTERLIST_TARGET)
        response = post_json_to_flow(prepared, {"requestId": request_id or str(uuid.uuid4()), "record": payload})
    except PowerAutomateError as error:
        logger.warning("ส่ง Master-List ไม่สำเร็จ: %s", error)
        return False, str(error)
    if response.body is None or response.body.get("ok") is not True:
        message = f"Master-List ตอบกลับรูปแบบไม่ถูกต้อง (HTTP {response.status}): ต้องตอบ JSON ที่มี ok เป็น true ตรวจสัญญากับเจ้าของเว็บ; {MASTERLIST_TARGET.maybe_created_hint}"
        logger.warning("Master-List ตอบรูปแบบไม่ถูกต้อง (host=%s)", prepared.host)
        return False, message
    logger.info("ส่งรายการเข้า Master-List สำเร็จ (host=%s)", prepared.host)
    return True, None
