"""ส่งไฟล์เอกสารขึ้น SharePoint ผ่าน Power Automate (Flow ที่เริ่มด้วย "When an HTTP request is received")

แอปส่งไฟล์ทีละไฟล์ไปที่ URL ของ Flow แล้ว Flow สร้างโฟลเดอร์ ปี/เดือน/วัน/ชื่อ ในไลบรารี และตอบลิงก์ไฟล์กลับ
ข้อตกลงกับ Flow (ยังต้องยืนยันกับ Flow จริง ดู handoff/02_S0_IT_REQUEST.md):
    คำขอ  POST JSON  {"requestId": "<uuid>", "folderParts": ["2026","Mar","19","ชื่อ"], "fileName": "...", "contentBase64": "...", "sha256": "..."}
          requestId เท่ากันทุกครั้งที่ retry ของไฟล์เดียว (Flow ควรใช้กันสร้างไฟล์ซ้ำ) fileName ผ่าน sanitize_file_name แล้ว
          header X-Api-Key (ถ้าตั้ง POWER_AUTOMATE_API_KEY)
    คำตอบ 200 JSON   {"fileUrl": "https://...", "folderUrl": "https://..."}  หรือ  {"error": "ข้อความ"}

ตั้งค่าผ่านไฟล์ .env (ห้ามใส่ค่าจริงในโค้ด):
    POWER_AUTOMATE_UPLOAD_URL       URL ของ Flow *มีลายเซ็นลับในตัว ถือเป็นรหัสผ่าน* ห้ามลง log / Git / ข้อความ error
    POWER_AUTOMATE_API_KEY          (ไม่บังคับ) ส่งใน header X-Api-Key ให้ Flow ตรวจซ้ำอีกชั้น
    POWER_AUTOMATE_TIMEOUT_SECONDS  รอ Flow ตอบกี่วินาที (ค่าเริ่มต้น 120)
    POWER_AUTOMATE_MAX_FILE_MB      ไฟล์ใหญ่สุดที่ส่งได้ (ค่าเริ่มต้น 50 ปรับตามเพดานของ Flow)

ไฟล์นี้ไม่เรียก Streamlit: ผิดพลาดจะ raise PowerAutomateError พร้อมข้อความภาษาไทย (ไม่มี URL / คีย์ในข้อความ)
"""

import base64
import hashlib
import http.client
import json
import re
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlparse

from config.logging_setup import get_logger
from config.settings import (
    DEFAULT_POWER_AUTOMATE_MAX_FILE_MB,
    DEFAULT_POWER_AUTOMATE_TIMEOUT_SECONDS,
    get_env_int,
    get_env_text,
)

logger = get_logger(__name__)

URL_SETTING: str = "POWER_AUTOMATE_UPLOAD_URL"
API_KEY_SETTING: str = "POWER_AUTOMATE_API_KEY"
LOOPBACK_HOSTS: frozenset[str] = frozenset({"127.0.0.1", "localhost", "::1"})  # อนุญาต http เฉพาะเครื่องตัวเอง (ทดสอบ)
MAX_RESPONSE_BYTES: int = 64 * 1024
# retry เฉพาะกรณีที่ Flow ยังไม่ได้เริ่มทำงานแน่ ๆ (ถูกจำกัดอัตรา/ปิดชั่วคราว) ส่วน 502/504 อาจเกิดขณะ Flow ทำงานต่อจนสร้างไฟล์เสร็จ จึงไม่ retry
RETRY_STATUS_CODES: frozenset[int] = frozenset({429, 503})
FILE_MAYBE_CREATED_HINT: str = "ไฟล์อาจถูกสร้างบน SharePoint ไปแล้ว ตรวจในไลบรารีก่อนส่งซ้ำ (ไฟล์เก็บในเครื่องแล้ว)"
FALLBACK_FILE_NAME: str = "document"
UNSAFE_FILE_NAME_CHARS: re.Pattern[str] = re.compile(r'[#%:*?"<>|/\\\x00-\x1f\x7f]')
MAX_RETRIES: int = 2
RETRY_DELAYS_SECONDS: tuple[float, ...] = (1.0, 3.0)
MAX_RETRY_AFTER_SECONDS: float = 10.0
MAX_FLOW_MESSAGE_LENGTH: int = 200
BYTES_PER_MB: int = 1024 * 1024


class PowerAutomateError(Exception):
    """ส่งไฟล์ผ่าน Power Automate ไม่สำเร็จ (ข้อความเป็นภาษาไทย แสดงให้ผู้ใช้ได้เลย ไม่มี URL / คีย์)"""


@dataclass(frozen=True)
class FlowUpload:
    """ผลการส่ง 1 ไฟล์: ลิงก์ไฟล์ และลิงก์โฟลเดอร์ (ถ้า Flow ตอบมา)"""

    file_url: str
    folder_url: Optional[str] = None


@dataclass(frozen=True)
class FlowTarget:
    """Flow ปลายทาง 1 ตัวและข้อความที่เกี่ยวกับสิ่งที่ส่ง (ไฟล์ขึ้น SharePoint / แถวเข้า Master-List) ใช้แกนส่ง HTTP เดียวกัน"""

    url_setting: str
    key_setting: str
    timeout_setting: str
    default_timeout: int
    maybe_created_hint: str  # ต่อท้ายข้อความเมื่อไม่รู้ว่า Flow สร้างของไปแล้วหรือยัง (timeout / 502 / 504 / การเชื่อมต่อหลุด)
    what: str  # สิ่งที่ส่ง ใช้ในข้อความ เช่น "ไฟล์" / "รายการ"
    kept_hint: str  # ข้อความในวงเล็บเมื่อส่งไม่สำเร็จ บอกว่าข้อมูลยังอยู่ในเครื่อง


FILE_TARGET: FlowTarget = FlowTarget(
    url_setting=URL_SETTING,
    key_setting=API_KEY_SETTING,
    timeout_setting="POWER_AUTOMATE_TIMEOUT_SECONDS",
    default_timeout=DEFAULT_POWER_AUTOMATE_TIMEOUT_SECONDS,
    maybe_created_hint=FILE_MAYBE_CREATED_HINT,
    what="ไฟล์",
    kept_hint="ไฟล์เก็บในเครื่องแล้ว",
)


@dataclass(frozen=True)
class FlowResponse:
    """คำตอบที่ผ่านการตรวจร่วมแล้ว (สถานะ 2xx และไม่มี error) body เป็น None ถ้าไม่ใช่ JSON object"""

    status: int
    body: Optional[dict[str, Any]]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """ไม่ตาม redirect: URL ของ Flow มีลายเซ็นลับ ห้ามส่งต่อไปที่อื่น"""

    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def is_power_automate_configured() -> bool:
    """ตั้ง POWER_AUTOMATE_UPLOAD_URL แล้วหรือยัง (ไม่ตรวจรูปแบบ ถ้าผิดจะแจ้งตอนส่ง)"""
    return bool(get_env_text(URL_SETTING))


def _load_url(target: FlowTarget = FILE_TARGET) -> str:
    """อ่าน URL ของ Flow และตรวจรูปแบบ: ต้องเป็น https (ยกเว้นเครื่องตัวเองเพื่อทดสอบ)

    Raises:
        PowerAutomateError: ไม่ได้ตั้งค่า หรือรูปแบบไม่ถูกต้อง (ไม่แสดงค่า URL ในข้อความ)
    """
    url = get_env_text(target.url_setting)
    if not url:
        raise PowerAutomateError(f"ยังไม่ได้ตั้งค่า Power Automate: ไม่พบ {target.url_setting} ในไฟล์ .env แล้วรีสตาร์ทแอป")
    try:
        parsed = urlparse(url)
        host = parsed.hostname
    except ValueError:
        host = None
        parsed = urlparse("")
    if not host or not (parsed.scheme == "https" or (parsed.scheme == "http" and host in LOOPBACK_HOSTS)):
        raise PowerAutomateError(f"{target.url_setting} ไม่ถูกต้อง: ต้องขึ้นต้นด้วย https:// และมีชื่อเซิร์ฟเวอร์ ตรวจค่าในไฟล์ .env")
    return url


def _clean_message(value: Any, secrets: tuple[str, ...]) -> str:
    """ข้อความ error จาก Flow แบบปลอดภัย: ตัด HTML / อักขระควบคุม / ค่าลับที่อาจสะท้อนกลับมา และจำกัดความยาว"""
    if not isinstance(value, str):
        return ""
    text = re.sub(r"<[^>]*>", " ", value)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "***")
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()[:MAX_FLOW_MESSAGE_LENGTH]


def _is_http_url(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        parsed = urlparse(value.strip())
        return parsed.scheme in ("http", "https") and bool(parsed.hostname)
    except ValueError:
        return False


def _parse_json_object(body: bytes) -> Optional[dict[str, Any]]:
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def sanitize_file_name(name: str) -> str:
    """ชื่อไฟล์ที่ SharePoint รับได้: แทนอักขระต้องห้าม (# % : * ? " < > | / \\ และอักขระควบคุม) ด้วย _ ตัดจุด/ช่องว่างท้ายชื่อ

    ภาษาไทยและช่องว่างกลางชื่อคงเดิม ถ้าไม่เหลืออะไรเลยใช้ "document"
    """
    cleaned = UNSAFE_FILE_NAME_CHARS.sub("_", name).strip().rstrip(". ")
    return cleaned or FALLBACK_FILE_NAME


def _retry_delay(attempt: int, retry_after: Optional[str]) -> float:
    delay = RETRY_DELAYS_SECONDS[min(attempt, len(RETRY_DELAYS_SECONDS) - 1)]
    if retry_after and retry_after.strip().isdigit():
        delay = float(retry_after.strip())
    return min(delay, MAX_RETRY_AFTER_SECONDS)


def _send(request: urllib.request.Request, host: str, timeout: int, target: FlowTarget = FILE_TARGET) -> tuple[int, bytes]:
    """ส่งคำขอ (retry เฉพาะ 429/503) คืน (สถานะ, เนื้อหาคำตอบ)

    ไม่ retry เมื่อรอนานเกินกำหนด / 502 / 504 / การเชื่อมต่อหลุด เพราะ Flow อาจสร้างไฟล์ไปแล้ว การส่งซ้ำจะทำให้ได้ไฟล์ซ้ำ
    """
    handlers: list[Any] = [_NoRedirect()]
    if host in LOOPBACK_HOSTS:
        handlers.append(urllib.request.ProxyHandler({}))  # เครื่องตัวเองไม่ต้องผ่าน proxy ของระบบ
    opener = urllib.request.build_opener(*handlers)
    for attempt in range(MAX_RETRIES + 1):
        retry_after: Optional[str] = None
        try:
            with opener.open(request, timeout=timeout) as response:
                status, body = response.status, response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            status = error.code
            retry_after = error.headers.get("Retry-After") if error.headers else None
            try:
                body = error.read(MAX_RESPONSE_BYTES + 1)
            except OSError:
                body = b""
            finally:
                error.close()
        except TimeoutError as error:
            raise PowerAutomateError(
                f"Flow ตอบช้าเกิน {timeout} วินาที จึงหยุดรอ {target.maybe_created_hint}"
            ) from error
        except urllib.error.URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise PowerAutomateError(
                    f"เชื่อมต่อ Flow ไม่ทันภายใน {timeout} วินาที ตรวจอินเทอร์เน็ตแล้วลองใหม่ ({target.kept_hint})"
                ) from error
            logger.warning("เชื่อมต่อ Power Automate ไม่ได้ (host=%s): %s", host, type(error.reason).__name__)
            raise PowerAutomateError(f"เชื่อมต่อ Flow ไม่ได้: ตรวจอินเทอร์เน็ต/ไฟร์วอลล์ และค่า {target.url_setting}") from error
        except (OSError, http.client.HTTPException) as error:
            # HTTPException (เช่น คำตอบที่ไม่ใช่ HTTP) ไม่ใช่ OSError แต่เกิดหลังส่งคำขอไปแล้วเช่นกัน
            logger.warning("ติดต่อ Power Automate ไม่สำเร็จ (host=%s): %s", host, type(error).__name__)
            raise PowerAutomateError(f"ติดต่อ Flow ไม่สำเร็จ: การเชื่อมต่อหลุดระหว่างส่ง {target.maybe_created_hint}") from error
        if status in RETRY_STATUS_CODES and attempt < MAX_RETRIES:
            time.sleep(_retry_delay(attempt, retry_after))
            continue
        return status, body
    raise AssertionError("unreachable")  # pragma: no cover - ลูปด้านบนคืนค่าหรือ raise เสมอ


@dataclass(frozen=True)
class PreparedCall:
    """ค่าที่อ่านและตรวจแล้วก่อนส่ง (URL / คีย์ / timeout) ห้ามพิมพ์หรือ log ทั้งก้อน เพราะมีความลับ"""

    target: FlowTarget
    url: str = field(repr=False)
    api_key: str = field(repr=False)
    host: str
    timeout: int


def prepare_flow_call(target: FlowTarget) -> PreparedCall:
    """อ่านค่าตั้ง URL / คีย์ / timeout ของ Flow แล้วตรวจก่อนสร้างคำขอ

    Raises:
        PowerAutomateError: ไม่ได้ตั้งค่า / URL ไม่ปลอดภัย / คีย์มีอักขระที่ใช้ไม่ได้ (ไม่แสดงค่าลับในข้อความ)
    """
    url = _load_url(target)
    api_key = get_env_text(target.key_setting)
    if api_key and not all(32 <= ord(char) < 127 for char in api_key):
        # ขึ้นบรรทัดใหม่/อักขระนอก ASCII ใส่ใน header ไม่ได้ (ถ้าปล่อยไป urllib จะ error แบบอ่านไม่รู้เรื่องตอนส่ง) ไม่แสดงค่าคีย์
        raise PowerAutomateError(f"{target.key_setting} มีอักขระที่ใช้ไม่ได้ (ขึ้นบรรทัดใหม่ แท็บ หรือตัวอักษรนอก ASCII) ตรวจค่าในไฟล์ .env")
    timeout = get_env_int(target.timeout_setting, target.default_timeout)
    return PreparedCall(target=target, url=url, api_key=api_key, host=urlparse(url).hostname or "", timeout=timeout)


def post_json_to_flow(prepared: PreparedCall, payload: dict[str, Any]) -> FlowResponse:
    """POST JSON ไปที่ Flow แล้วตรวจคำตอบส่วนที่ใช้ร่วมกัน (สถานะ / ขนาด / error ที่ Flow แจ้ง)

    retry เฉพาะ 429/503 (payload เดิมจึงมี requestId เดิม) คืนเฉพาะคำตอบ 2xx ที่ Flow ไม่ได้แจ้ง error
    ผู้เรียกตรวจรูปแบบเนื้อหาเอง (fileUrl / ok)

    Raises:
        PowerAutomateError: ส่งไม่สำเร็จหรือ Flow ปฏิเสธ (ข้อความไทย ไม่มี URL / คีย์)
    """
    target = prepared.target
    secrets = (prepared.url, prepared.api_key)
    headers = {"Content-Type": "application/json; charset=utf-8", "Accept": "application/json"}
    if prepared.api_key:
        headers["X-Api-Key"] = prepared.api_key
    request = urllib.request.Request(
        prepared.url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers=headers, method="POST"
    )

    status, body = _send(request, prepared.host, prepared.timeout, target)
    if len(body) > MAX_RESPONSE_BYTES:
        raise PowerAutomateError("Flow ตอบกลับข้อมูลใหญ่ผิดปกติ จึงไม่รับ ตรวจ Response ของ Flow")
    reply = _parse_json_object(body)
    flow_message = _clean_message((reply or {}).get("error"), secrets)

    if 300 <= status < 400:
        raise PowerAutomateError("Flow ตอบเปลี่ยนเส้นทาง (redirect) ซึ่งไม่รองรับ ตรวจ URL ของ Flow")
    if status in (401, 403):
        raise PowerAutomateError(f"Flow ปฏิเสธการเรียก: ตรวจ {target.key_setting} และสิทธิ์เรียกใช้ Flow")
    if status == 404:
        raise PowerAutomateError("ไม่พบ Flow: URL อาจเก่าหรือ Flow ถูกปิด/ลบ ตรวจกับผู้ดูแล Flow")
    if status >= 400:
        logger.warning("Flow ตอบสถานะ %s (host=%s)", status, prepared.host)
        detail = f": {flow_message}" if flow_message else ""
        hint = f" {target.maybe_created_hint}" if status in (502, 504) else ""
        raise PowerAutomateError(f"Flow ตอบกลับข้อผิดพลาด (HTTP {status}){detail}{hint}")
    if flow_message:
        raise PowerAutomateError(f"Flow แจ้งว่าส่ง{target.what}ไม่สำเร็จ: {flow_message}")
    return FlowResponse(status=status, body=reply)


def upload_file_to_flow(file_name: str, data: bytes, folder_parts: list[str]) -> FlowUpload:
    """ส่ง 1 ไฟล์ไปที่ Flow แล้วคืนลิงก์ไฟล์ (และลิงก์โฟลเดอร์ถ้า Flow ตอบมา)

    Args:
        file_name: ชื่อไฟล์
        data: เนื้อไฟล์
        folder_parts: โครงโฟลเดอร์ เช่น ["2026", "Mar", "19", "20260319_Addin"]

    Raises:
        PowerAutomateError: ตั้งค่าไม่ถูกต้อง / ไฟล์ว่างหรือใหญ่เกิน / Flow ปฏิเสธ ล้มเหลว หรือตอบรูปแบบไม่ถูกต้อง
    """
    prepared = prepare_flow_call(FILE_TARGET)
    if not data:
        raise PowerAutomateError(f"ไฟล์ '{file_name}' ว่างเปล่า (0 ไบต์): เลือกไฟล์ใหม่แล้วลองอีกครั้ง")
    max_mb = get_env_int("POWER_AUTOMATE_MAX_FILE_MB", DEFAULT_POWER_AUTOMATE_MAX_FILE_MB)
    if len(data) > max_mb * BYTES_PER_MB:
        raise PowerAutomateError(
            f"ไฟล์ '{file_name}' ใหญ่เกิน {max_mb} MB ส่งผ่าน Power Automate ไม่ได้ (เก็บในเครื่องแล้ว) "
            "ถ้า Flow รับไฟล์ใหญ่ได้ ปรับ POWER_AUTOMATE_MAX_FILE_MB ใน .env"
        )

    payload = {
        "requestId": str(uuid.uuid4()),  # คงเดิมทุกครั้งที่ retry ของไฟล์นี้ ให้ Flow ตรวจซ้ำและไม่สร้างไฟล์ซ้ำ
        "folderParts": list(folder_parts),
        "fileName": sanitize_file_name(file_name),
        "contentBase64": base64.b64encode(data).decode("ascii"),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    response = post_json_to_flow(prepared, payload)
    reply = response.body
    if reply is None or not _is_http_url(reply.get("fileUrl")):
        raise PowerAutomateError(
            f"Flow ตอบกลับรูปแบบไม่ถูกต้อง (HTTP {response.status}): ต้องตอบ JSON ที่มี fileUrl เป็นลิงก์ http(s) "
            f"ตรวจ Response action ของ Flow; {FILE_MAYBE_CREATED_HINT}"
        )
    folder_url = reply.get("folderUrl")
    if folder_url is not None and not _is_http_url(folder_url):
        logger.warning("Flow ตอบ folderUrl ที่ไม่ใช่ลิงก์ http(s) จึงไม่ใช้ (host=%s)", prepared.host)
        folder_url = None
    logger.info("ส่งไฟล์ '%s' ผ่าน Power Automate สำเร็จ (host=%s)", file_name, prepared.host)
    return FlowUpload(file_url=reply["fileUrl"].strip(), folder_url=folder_url.strip() if folder_url else None)
