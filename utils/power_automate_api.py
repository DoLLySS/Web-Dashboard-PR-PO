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
from dataclasses import dataclass
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


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """ไม่ตาม redirect: URL ของ Flow มีลายเซ็นลับ ห้ามส่งต่อไปที่อื่น"""

    def redirect_request(self, *_args: Any, **_kwargs: Any) -> None:
        return None


def is_power_automate_configured() -> bool:
    """ตั้ง POWER_AUTOMATE_UPLOAD_URL แล้วหรือยัง (ไม่ตรวจรูปแบบ ถ้าผิดจะแจ้งตอนส่ง)"""
    return bool(get_env_text(URL_SETTING))


def _load_url() -> str:
    """อ่าน URL ของ Flow และตรวจรูปแบบ: ต้องเป็น https (ยกเว้นเครื่องตัวเองเพื่อทดสอบ)

    Raises:
        PowerAutomateError: ไม่ได้ตั้งค่า หรือรูปแบบไม่ถูกต้อง (ไม่แสดงค่า URL ในข้อความ)
    """
    url = get_env_text(URL_SETTING)
    if not url:
        raise PowerAutomateError(f"ยังไม่ได้ตั้งค่า Power Automate: ไม่พบ {URL_SETTING} ในไฟล์ .env แล้วรีสตาร์ทแอป")
    try:
        parsed = urlparse(url)
        host = parsed.hostname
    except ValueError:
        host = None
        parsed = urlparse("")
    if not host or not (parsed.scheme == "https" or (parsed.scheme == "http" and host in LOOPBACK_HOSTS)):
        raise PowerAutomateError(f"{URL_SETTING} ไม่ถูกต้อง: ต้องขึ้นต้นด้วย https:// และมีชื่อเซิร์ฟเวอร์ ตรวจค่าในไฟล์ .env")
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


def _send(request: urllib.request.Request, host: str, timeout: int) -> tuple[int, bytes]:
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
                f"Flow ตอบช้าเกิน {timeout} วินาที จึงหยุดรอ ไฟล์อาจถูกสร้างบน SharePoint ไปแล้ว "
                "ตรวจในไลบรารีก่อนส่งซ้ำ (ไฟล์เก็บในเครื่องแล้ว)"
            ) from error
        except urllib.error.URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise PowerAutomateError(
                    f"เชื่อมต่อ Flow ไม่ทันภายใน {timeout} วินาที ตรวจอินเทอร์เน็ตแล้วลองใหม่ (ไฟล์เก็บในเครื่องแล้ว)"
                ) from error
            logger.warning("เชื่อมต่อ Power Automate ไม่ได้ (host=%s): %s", host, type(error.reason).__name__)
            raise PowerAutomateError("เชื่อมต่อ Flow ไม่ได้: ตรวจอินเทอร์เน็ต/ไฟร์วอลล์ และค่า POWER_AUTOMATE_UPLOAD_URL") from error
        except (OSError, http.client.HTTPException) as error:
            # HTTPException (เช่น คำตอบที่ไม่ใช่ HTTP) ไม่ใช่ OSError แต่เกิดหลังส่งคำขอไปแล้วเช่นกัน
            logger.warning("ติดต่อ Power Automate ไม่สำเร็จ (host=%s): %s", host, type(error).__name__)
            raise PowerAutomateError(f"ติดต่อ Flow ไม่สำเร็จ: การเชื่อมต่อหลุดระหว่างส่ง {FILE_MAYBE_CREATED_HINT}") from error
        if status in RETRY_STATUS_CODES and attempt < MAX_RETRIES:
            time.sleep(_retry_delay(attempt, retry_after))
            continue
        return status, body
    raise AssertionError("unreachable")  # pragma: no cover - ลูปด้านบนคืนค่าหรือ raise เสมอ


def upload_file_to_flow(file_name: str, data: bytes, folder_parts: list[str]) -> FlowUpload:
    """ส่ง 1 ไฟล์ไปที่ Flow แล้วคืนลิงก์ไฟล์ (และลิงก์โฟลเดอร์ถ้า Flow ตอบมา)

    Args:
        file_name: ชื่อไฟล์
        data: เนื้อไฟล์
        folder_parts: โครงโฟลเดอร์ เช่น ["2026", "Mar", "19", "20260319_Addin"]

    Raises:
        PowerAutomateError: ตั้งค่าไม่ถูกต้อง / ไฟล์ว่างหรือใหญ่เกิน / Flow ปฏิเสธ ล้มเหลว หรือตอบรูปแบบไม่ถูกต้อง
    """
    url = _load_url()
    api_key = get_env_text(API_KEY_SETTING)
    secrets = (url, api_key)
    host = urlparse(url).hostname or ""
    if api_key and not all(32 <= ord(char) < 127 for char in api_key):
        # ขึ้นบรรทัดใหม่/อักขระนอก ASCII ใส่ใน header ไม่ได้ (ถ้าปล่อยไป urllib จะ error แบบอ่านไม่รู้เรื่องตอนส่ง) ไม่แสดงค่าคีย์
        raise PowerAutomateError("POWER_AUTOMATE_API_KEY มีอักขระที่ใช้ไม่ได้ (ขึ้นบรรทัดใหม่ แท็บ หรือตัวอักษรนอก ASCII) ตรวจค่าในไฟล์ .env")
    if not data:
        raise PowerAutomateError(f"ไฟล์ '{file_name}' ว่างเปล่า (0 ไบต์): เลือกไฟล์ใหม่แล้วลองอีกครั้ง")
    max_mb = get_env_int("POWER_AUTOMATE_MAX_FILE_MB", DEFAULT_POWER_AUTOMATE_MAX_FILE_MB)
    if len(data) > max_mb * BYTES_PER_MB:
        raise PowerAutomateError(
            f"ไฟล์ '{file_name}' ใหญ่เกิน {max_mb} MB ส่งผ่าน Power Automate ไม่ได้ (เก็บในเครื่องแล้ว) "
            "ถ้า Flow รับไฟล์ใหญ่ได้ ปรับ POWER_AUTOMATE_MAX_FILE_MB ใน .env"
        )
    timeout = get_env_int("POWER_AUTOMATE_TIMEOUT_SECONDS", DEFAULT_POWER_AUTOMATE_TIMEOUT_SECONDS)

    payload = {
        "requestId": str(uuid.uuid4()),  # คงเดิมทุกครั้งที่ retry ของไฟล์นี้ ให้ Flow ตรวจซ้ำและไม่สร้างไฟล์ซ้ำ
        "folderParts": list(folder_parts),
        "fileName": sanitize_file_name(file_name),
        "contentBase64": base64.b64encode(data).decode("ascii"),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    headers = {"Content-Type": "application/json; charset=utf-8", "Accept": "application/json"}
    if api_key:
        headers["X-Api-Key"] = api_key
    request = urllib.request.Request(
        url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers=headers, method="POST"
    )

    status, body = _send(request, host, timeout)
    if len(body) > MAX_RESPONSE_BYTES:
        raise PowerAutomateError("Flow ตอบกลับข้อมูลใหญ่ผิดปกติ จึงไม่รับ ตรวจ Response ของ Flow")
    reply = _parse_json_object(body)
    flow_message = _clean_message((reply or {}).get("error"), secrets)

    if 300 <= status < 400:
        raise PowerAutomateError("Flow ตอบเปลี่ยนเส้นทาง (redirect) ซึ่งไม่รองรับ ตรวจ URL ของ Flow")
    if status in (401, 403):
        raise PowerAutomateError("Flow ปฏิเสธการเรียก: ตรวจ POWER_AUTOMATE_API_KEY และสิทธิ์เรียกใช้ Flow")
    if status == 404:
        raise PowerAutomateError("ไม่พบ Flow: URL อาจเก่าหรือ Flow ถูกปิด/ลบ ตรวจกับผู้ดูแล Flow")
    if status >= 400:
        logger.warning("Flow ตอบสถานะ %s (host=%s)", status, host)
        detail = f": {flow_message}" if flow_message else ""
        hint = f" {FILE_MAYBE_CREATED_HINT}" if status in (502, 504) else ""
        raise PowerAutomateError(f"Flow ตอบกลับข้อผิดพลาด (HTTP {status}){detail}{hint}")
    if flow_message:
        raise PowerAutomateError(f"Flow แจ้งว่าส่งไฟล์ไม่สำเร็จ: {flow_message}")
    if reply is None or not _is_http_url(reply.get("fileUrl")):
        raise PowerAutomateError(
            f"Flow ตอบกลับรูปแบบไม่ถูกต้อง (HTTP {status}): ต้องตอบ JSON ที่มี fileUrl เป็นลิงก์ http(s) "
            f"ตรวจ Response action ของ Flow; {FILE_MAYBE_CREATED_HINT}"
        )
    folder_url = reply.get("folderUrl")
    if folder_url is not None and not _is_http_url(folder_url):
        logger.warning("Flow ตอบ folderUrl ที่ไม่ใช่ลิงก์ http(s) จึงไม่ใช้ (host=%s)", host)
        folder_url = None
    logger.info("ส่งไฟล์ '%s' ผ่าน Power Automate สำเร็จ (host=%s)", file_name, host)
    return FlowUpload(file_url=reply["fileUrl"].strip(), folder_url=folder_url.strip() if folder_url else None)
