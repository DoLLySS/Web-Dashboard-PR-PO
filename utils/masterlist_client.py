"""ส่งข้อมูลแถวเข้า Master-List ผ่าน Flow ของ Power Automate (ยังทดสอบกับ Flow ปลอมเท่านั้น สัญญารอ IT ยืนยัน)

ข้อตกลงกับ Flow (ข้อเสนอ ดู handoff/02_S0_IT_REQUEST.md):
    คำขอ  POST JSON  {"requestId": "<uuid>", "record": {13 ฟิลด์ใน MASTERLIST_FIELDS}}  header X-Api-Key (ถ้าตั้ง)
          requestId สร้างใหม่ต่อการส่ง 1 แถว และเท่าเดิมทุกครั้งที่ retry (Flow ควรใช้กันสร้างแถวซ้ำ)
    คำตอบ 200 JSON  {"ok": true}  หรือ  {"error": "ข้อความ"}
ตั้งค่าใน .env: MASTERLIST_API_URL (มีลายเซ็นลับ ถือเป็นรหัสผ่าน), MASTERLIST_API_KEY (ไม่บังคับ), MASTERLIST_TIMEOUT_SECONDS (ค่าเริ่มต้น 30)
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
)

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
    return bool(get_env_text(URL_SETTING))


def send_to_masterlist(payload: dict[str, Any]) -> tuple[bool, Optional[str]]:
    """ส่ง payload เข้า Master-List ผ่าน Flow (POST {"requestId", "record"}; Flow ต้องตอบ {"ok": true})

    ไม่ raise: การส่งล้มเหลวต้องไม่ทำให้การบันทึกรายการล้ม (แถวและไฟล์ในเครื่องบันทึกไปก่อนแล้ว)
    retry เฉพาะ 429/503 ด้วย requestId เดิม ส่วน timeout / 502 / 504 / การเชื่อมต่อหลุด / คำตอบรูปแบบผิดไม่ retry
    เพราะ Flow อาจสร้างรายการไปแล้ว

    Returns:
        (ส่งแล้วหรือไม่, ข้อความอธิบายเมื่อยังไม่ได้ส่ง; ไม่มี URL / คีย์)
    """
    if not is_masterlist_configured():
        logger.info("ข้ามการส่ง Master-List: ยังไม่ได้ตั้ง %s (เตรียม payload %d ฟิลด์ไว้แล้ว)", URL_SETTING, len(payload))
        return False, "ยังไม่ได้ตั้งค่า Master-List (เตรียมข้อมูลไว้แล้ว ยังไม่ได้ส่ง)"
    try:
        prepared = prepare_flow_call(MASTERLIST_TARGET)
        response = post_json_to_flow(prepared, {"requestId": str(uuid.uuid4()), "record": payload})
    except PowerAutomateError as error:
        logger.warning("ส่ง Master-List ไม่สำเร็จ: %s", error)
        return False, str(error)
    if response.body is None or response.body.get("ok") is not True:
        message = f"Flow ของ Master-List ตอบกลับรูปแบบไม่ถูกต้อง (HTTP {response.status}): ต้องตอบ JSON ที่มี ok เป็น true ตรวจ Response action ของ Flow; {MASTERLIST_TARGET.maybe_created_hint}"
        logger.warning("Flow ของ Master-List ตอบรูปแบบไม่ถูกต้อง (host=%s)", prepared.host)
        return False, message
    logger.info("ส่งรายการเข้า Master-List ผ่าน Flow สำเร็จ (host=%s)", prepared.host)
    return True, None
