"""ทดสอบการส่งไฟล์ผ่าน Power Automate (utils/power_automate_api.py) กับ Flow ปลอมบนเครื่องตัวเอง

ไม่ยิง Flow จริง: ใช้ http.server บนพอร์ตสุ่ม และ conftest.py ล้างตัวแปร POWER_AUTOMATE_* ไว้แล้ว
"""

import base64
import hashlib
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable, Iterator, Optional

import pytest

import utils.power_automate_api as flow_api
from data.database import get_transaction
from utils.power_automate_api import FlowUpload, PowerAutomateError, is_power_automate_configured, upload_file_to_flow
from utils.storage_backend import (
    BACKEND_POWER_AUTOMATE,
    StorageError,
    get_active_backend,
    is_storage_configured,
    upload_files_and_folder_url,
    upload_files_to_storage,
)
from utils.submit_pipeline import RecordFields, submit_record

SECRET_SIGNATURE = "SIG-SECRET-9f3a"
API_KEY = "KEY-SECRET-77c1"
FOLDER = ["2026", "Mar", "19", "20260319_งานทดสอบ"]
FILE_URL = "https://example.sharepoint.test/sites/IT/Shared%20Documents/file.pdf"
FOLDER_URL = "https://example.sharepoint.test/sites/IT/Shared%20Documents/2026/Mar/19"


@dataclass
class Reply:
    status: int = 200
    body: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)
    delay: float = 0.0


@dataclass
class Recorded:
    path: str
    headers: dict[str, str]
    body: bytes

    def json(self) -> dict[str, Any]:
        return json.loads(self.body.decode("utf-8"))


class FakeFlow:
    """Flow ปลอม: บันทึกคำขอทุกอัน และตอบตามที่เทสต์กำหนด (ตอบอันถัดไปจากคิว ถ้าหมดใช้อันสุดท้ายซ้ำ)"""

    def __init__(self) -> None:
        self.requests: list[Recorded] = []
        self.replies: list[Reply] = [Reply(body=json.dumps({"fileUrl": FILE_URL, "folderUrl": FOLDER_URL}).encode())]
        self.responder: Optional[Callable[[Recorded], Reply]] = None
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - ชื่อเมธอดตามที่ http.server กำหนด
                length = int(self.headers.get("Content-Length", 0))
                recorded = Recorded(self.path, {key.lower(): value for key, value in self.headers.items()}, self.rfile.read(length))
                outer.requests.append(recorded)
                index = min(len(outer.requests) - 1, len(outer.replies) - 1)
                reply = outer.responder(recorded) if outer.responder else outer.replies[index]
                if reply.delay:
                    time.sleep(reply.delay)
                try:
                    self.send_response(reply.status)
                    for key, value in reply.headers.items():
                        self.send_header(key, value)
                    self.send_header("Content-Length", str(len(reply.body)))
                    self.end_headers()
                    self.wfile.write(reply.body)
                except OSError:
                    pass  # ผู้เรียกเลิกรอไปแล้ว (เทสต์ timeout)

            def log_message(self, *_args: object) -> None:
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/flow?sig={SECRET_SIGNATURE}"

    def reply_json(self, payload: Any, status: int = 200) -> None:
        self.replies = [Reply(status=status, body=json.dumps(payload).encode("utf-8"))]


@pytest.fixture
def flow(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeFlow]:
    fake = FakeFlow()
    monkeypatch.setenv("POWER_AUTOMATE_UPLOAD_URL", fake.url)
    monkeypatch.setenv("POWER_AUTOMATE_API_KEY", API_KEY)
    monkeypatch.setenv("STORAGE_BACKEND", "powerautomate")
    sleeps: list[float] = []
    # แทนทั้งโมดูล time ของ power_automate_api (ไม่แก้ time.sleep ส่วนกลาง เพราะ Flow ปลอมใช้ตอนหน่วงคำตอบ)
    monkeypatch.setattr(flow_api, "time", SimpleNamespace(sleep=sleeps.append))
    fake.sleeps = sleeps  # type: ignore[attr-defined]
    yield fake
    fake.server.shutdown()
    fake.server.server_close()


class LogCollector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


@pytest.fixture
def logs() -> Iterator[LogCollector]:
    collector = LogCollector()
    logger = logging.getLogger("masterlist")
    logger.addHandler(collector)
    previous = logger.level
    logger.setLevel(logging.DEBUG)
    yield collector
    logger.removeHandler(collector)
    logger.setLevel(previous)


def assert_no_secret(text: str) -> None:
    for secret in (SECRET_SIGNATURE, API_KEY, "sig="):
        assert secret not in text


# ---------------------------------------------------------------------------
# คำขอและคำตอบปกติ
# ---------------------------------------------------------------------------


def test_request_carries_file_folder_hash_and_key(flow: FakeFlow) -> None:
    data = "เนื้อหาไฟล์ภาษาไทย".encode()

    result = upload_file_to_flow("ใบกำกับภาษี 01.pdf", data, FOLDER)

    assert result == FlowUpload(file_url=FILE_URL, folder_url=FOLDER_URL)
    (request,) = flow.requests
    body = request.json()
    assert body["folderParts"] == FOLDER and body["fileName"] == "ใบกำกับภาษี 01.pdf"
    assert base64.b64decode(body["contentBase64"]) == data
    assert body["sha256"] == hashlib.sha256(data).hexdigest()
    assert request.headers["x-api-key"] == API_KEY
    assert request.headers["content-type"].startswith("application/json")
    assert request.path == f"/flow?sig={SECRET_SIGNATURE}"


def test_no_key_header_when_not_configured(flow: FakeFlow, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("POWER_AUTOMATE_API_KEY")
    upload_file_to_flow("a.pdf", b"x", FOLDER)
    assert "x-api-key" not in flow.requests[0].headers


def test_missing_folder_url_is_allowed(flow: FakeFlow) -> None:
    flow.reply_json({"fileUrl": FILE_URL})
    assert upload_file_to_flow("a.pdf", b"x", FOLDER) == FlowUpload(file_url=FILE_URL, folder_url=None)


def test_invalid_folder_url_is_dropped_but_file_url_kept(flow: FakeFlow) -> None:
    flow.reply_json({"fileUrl": FILE_URL, "folderUrl": "javascript:alert(1)"})
    assert upload_file_to_flow("a.pdf", b"x", FOLDER) == FlowUpload(file_url=FILE_URL, folder_url=None)


def test_configured_flag_follows_url_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    assert is_power_automate_configured() is False
    monkeypatch.setenv("POWER_AUTOMATE_UPLOAD_URL", "https://x.test/flow?sig=1")
    assert is_power_automate_configured() is True


# ---------------------------------------------------------------------------
# ข้อผิดพลาดจาก Flow
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected_word"),
    [(401, "POWER_AUTOMATE_API_KEY"), (403, "POWER_AUTOMATE_API_KEY"), (404, "ไม่พบ Flow"), (400, "HTTP 400"), (500, "HTTP 500")],
)
def test_error_statuses_give_thai_messages_without_secrets(flow: FakeFlow, status: int, expected_word: str) -> None:
    flow.replies = [Reply(status=status, body=b"{}")]

    with pytest.raises(PowerAutomateError) as error:
        upload_file_to_flow("a.pdf", b"x", FOLDER)

    assert expected_word in str(error.value)
    assert_no_secret(str(error.value))
    assert len(flow.requests) == 1  # 4xx และ 500 ไม่ retry


def test_flow_error_message_is_cleaned_and_secrets_are_masked(flow: FakeFlow) -> None:
    message = f"<script>x</script><b>ไลบรารีเต็ม</b> {flow.url} {API_KEY}\n" + "ยาว" * 500
    flow.reply_json({"error": message}, status=400)

    with pytest.raises(PowerAutomateError) as error:
        upload_file_to_flow("a.pdf", b"x", FOLDER)

    text = str(error.value)
    assert "ไลบรารีเต็ม" in text and "<" not in text and "\n" not in text
    assert_no_secret(text)
    assert len(text) < 400


def test_error_field_in_a_200_reply_is_a_failure(flow: FakeFlow) -> None:
    flow.reply_json({"error": "ไม่มีสิทธิ์เขียนไลบรารี", "fileUrl": FILE_URL})
    with pytest.raises(PowerAutomateError, match="ไม่มีสิทธิ์เขียนไลบรารี"):
        upload_file_to_flow("a.pdf", b"x", FOLDER)


@pytest.mark.parametrize(
    "reply",
    [
        Reply(body=b"not json"),
        Reply(body=b"[]"),
        Reply(body=b"{}"),
        Reply(body=json.dumps({"fileUrl": ""}).encode()),
        Reply(body=json.dumps({"fileUrl": 123}).encode()),
        Reply(body=json.dumps({"fileUrl": "ftp://x.test/f"}).encode()),
        Reply(body=json.dumps({"fileUrl": "javascript:alert(1)"}).encode()),
        Reply(status=202, body=b""),
        Reply(body=b"\xff\xfe"),
    ],
)
def test_malformed_replies_are_rejected(flow: FakeFlow, reply: Reply) -> None:
    flow.replies = [reply]
    with pytest.raises(PowerAutomateError, match="รูปแบบไม่ถูกต้อง"):
        upload_file_to_flow("a.pdf", b"x", FOLDER)


def test_oversized_reply_is_rejected(flow: FakeFlow) -> None:
    flow.replies = [Reply(body=b"x" * (flow_api.MAX_RESPONSE_BYTES + 10))]
    with pytest.raises(PowerAutomateError, match="ใหญ่ผิดปกติ"):
        upload_file_to_flow("a.pdf", b"x", FOLDER)


def test_redirect_is_not_followed(flow: FakeFlow) -> None:
    flow.replies = [Reply(status=302, headers={"Location": f"http://127.0.0.1:{flow.port}/evil?stolen=1"})]

    with pytest.raises(PowerAutomateError, match="redirect"):
        upload_file_to_flow("a.pdf", b"x", FOLDER)

    assert [request.path.split("?")[0] for request in flow.requests] == ["/flow"]  # ไม่มีคำขอที่สองไป /evil


# ---------------------------------------------------------------------------
# retry และ timeout
# ---------------------------------------------------------------------------


def test_retries_503_then_succeeds(flow: FakeFlow) -> None:
    ok = Reply(body=json.dumps({"fileUrl": FILE_URL}).encode())
    flow.replies = [Reply(status=503, body=b"{}"), Reply(status=429, headers={"Retry-After": "99"}, body=b"{}"), ok]

    assert upload_file_to_flow("a.pdf", b"x", FOLDER).file_url == FILE_URL

    assert len(flow.requests) == 3
    assert flow.sleeps == [1.0, flow_api.MAX_RETRY_AFTER_SECONDS]  # type: ignore[attr-defined]  # Retry-After 99 ถูกจำกัดที่ 10


def test_gives_up_after_the_retry_limit(flow: FakeFlow) -> None:
    flow.replies = [Reply(status=503, body=b"{}")]

    with pytest.raises(PowerAutomateError, match="HTTP 503"):
        upload_file_to_flow("a.pdf", b"x", FOLDER)

    assert len(flow.requests) == flow_api.MAX_RETRIES + 1


def test_timeout_is_not_retried_because_the_file_may_exist(flow: FakeFlow, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POWER_AUTOMATE_TIMEOUT_SECONDS", "1")
    flow.replies = [Reply(delay=2.5, body=b"{}")]

    with pytest.raises(PowerAutomateError) as error:
        upload_file_to_flow("a.pdf", b"x", FOLDER)

    assert "ตอบช้าเกิน 1 วินาที" in str(error.value) and "ตรวจในไลบรารีก่อนส่งซ้ำ" in str(error.value)
    assert_no_secret(str(error.value))
    time.sleep(0.2)
    assert len(flow.requests) == 1


def test_connection_refused_is_reported_without_secrets(monkeypatch: pytest.MonkeyPatch, logs: LogCollector) -> None:
    fake = FakeFlow()
    url = fake.url
    fake.server.shutdown()
    fake.server.server_close()  # พอร์ตนี้ไม่มีคนฟังแล้ว
    monkeypatch.setenv("POWER_AUTOMATE_UPLOAD_URL", url)
    monkeypatch.setenv("POWER_AUTOMATE_API_KEY", API_KEY)

    with pytest.raises(PowerAutomateError) as error:
        upload_file_to_flow("a.pdf", b"x", FOLDER)

    assert "เชื่อมต่อ Flow ไม่ได้" in str(error.value)
    assert_no_secret(str(error.value) + "\n".join(logs.lines))


# ---------------------------------------------------------------------------
# ตรวจก่อนส่ง
# ---------------------------------------------------------------------------


def test_empty_and_oversized_files_never_reach_the_flow(flow: FakeFlow, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("POWER_AUTOMATE_MAX_FILE_MB", "1")

    with pytest.raises(PowerAutomateError, match="ว่างเปล่า"):
        upload_file_to_flow("a.pdf", b"", FOLDER)
    with pytest.raises(PowerAutomateError, match="ใหญ่เกิน 1 MB"):
        upload_file_to_flow("big.pdf", b"x" * (1024 * 1024 + 1), FOLDER)

    assert flow.requests == []


@pytest.mark.parametrize(
    "url",
    [
        "http://flow.example.com/run?sig=" + SECRET_SIGNATURE,  # http ที่ไม่ใช่เครื่องตัวเอง
        "ftp://flow.example.com/run?sig=" + SECRET_SIGNATURE,
        "https://",
        "not a url",
        "javascript:alert(1)",
    ],
)
def test_unsafe_or_malformed_urls_are_refused_without_echoing_them(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setenv("POWER_AUTOMATE_UPLOAD_URL", url)

    with pytest.raises(PowerAutomateError) as error:
        upload_file_to_flow("a.pdf", b"x", FOLDER)

    assert "ไม่ถูกต้อง" in str(error.value)
    assert "flow.example.com" not in str(error.value)
    assert_no_secret(str(error.value))


def test_unset_url_gives_setup_message() -> None:
    with pytest.raises(PowerAutomateError, match="POWER_AUTOMATE_UPLOAD_URL"):
        upload_file_to_flow("a.pdf", b"x", FOLDER)


# ---------------------------------------------------------------------------
# ความลับต้องไม่หลุดลง log
# ---------------------------------------------------------------------------


def test_secrets_never_appear_in_logs_for_success_and_failures(flow: FakeFlow, logs: LogCollector) -> None:
    ok = Reply(body=json.dumps({"fileUrl": FILE_URL}).encode())
    flow.replies = [ok, Reply(status=500, body=b'{"error":"boom"}'), Reply(status=503, body=b"{}"), Reply(status=403, body=b"{}")]

    upload_file_to_flow("a.pdf", b"x", FOLDER)
    for _ in range(2):
        with pytest.raises(PowerAutomateError) as error:
            upload_file_to_flow("a.pdf", b"x", FOLDER)
        assert_no_secret(str(error.value))

    assert logs.lines, "ต้องมี log อย่างน้อยผลสำเร็จ"
    assert_no_secret("\n".join(logs.lines))


# ---------------------------------------------------------------------------
# ตัวเลือกปลายทาง (storage_backend)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", ["powerautomate", "PowerAutomate", "power-automate", "power_automate", " Power Automate "])
def test_backend_name_variants_select_power_automate(value: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORAGE_BACKEND", value)
    assert get_active_backend() == BACKEND_POWER_AUTOMATE


def test_storage_is_configured_only_when_the_url_is_set(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORAGE_BACKEND", "powerautomate")
    assert is_storage_configured() is False
    monkeypatch.setenv("POWER_AUTOMATE_UPLOAD_URL", "https://x.test/flow?sig=1")
    assert is_storage_configured() is True


def test_files_go_one_by_one_in_order_and_folder_url_comes_from_the_flow(flow: FakeFlow) -> None:
    flow.responder = lambda request: Reply(
        body=json.dumps({"fileUrl": f"https://x.test/{request.json()['fileName']}", "folderUrl": FOLDER_URL}).encode()
    )

    links, folder_url = upload_files_and_folder_url([("a.pdf", b"1"), ("b.pdf", b"2")], FOLDER)

    assert links == ["https://x.test/a.pdf", "https://x.test/b.pdf"] and folder_url == FOLDER_URL
    assert [request.json()["fileName"] for request in flow.requests] == ["a.pdf", "b.pdf"]
    assert upload_files_to_storage([("c.pdf", b"3")], FOLDER) == ["https://x.test/c.pdf"]


def test_failure_on_second_file_names_it_and_stops(flow: FakeFlow) -> None:
    ok = Reply(body=json.dumps({"fileUrl": FILE_URL}).encode())
    flow.replies = [ok, Reply(status=500, body=b"{}"), ok]

    with pytest.raises(StorageError) as error:
        upload_files_and_folder_url([("a.pdf", b"1"), ("b.pdf", b"2"), ("c.pdf", b"3")], FOLDER)

    assert "'b.pdf'" in str(error.value) and "ส่งสำเร็จแล้ว 1 ไฟล์" in str(error.value)
    assert len(flow.requests) == 2
    assert_no_secret(str(error.value))


def test_no_files_means_no_request(flow: FakeFlow) -> None:
    assert upload_files_and_folder_url([], FOLDER) == ([], None)
    assert flow.requests == []


# ---------------------------------------------------------------------------
# ใช้กับการบันทึกรายการจริง (submit_pipeline)
# ---------------------------------------------------------------------------


def make_fields() -> RecordFields:
    return RecordFields(date="2026-03-19", vendor="Alpha Co", description="NB Alpha X100")


def test_saved_row_links_to_the_folder_returned_by_the_flow(isolated_storage: Path, flow: FakeFlow) -> None:
    result = submit_record(make_fields(), [("20260319_PR_Addin_NB.pdf", b"pr-content")])

    assert result.storage_status == "ok" and result.transaction_id is not None
    assert get_transaction(result.transaction_id)["sharepoint_url"] == FOLDER_URL
    assert result.storage_links[0] == FOLDER_URL
    assert len(flow.requests) == 1 and flow.requests[0].json()["folderParts"][:3] == ["2026", "Mar", "19"]
    assert list(isolated_storage.rglob("*.pdf"))  # ไฟล์ในเครื่องยังอยู่


def test_flow_failure_keeps_the_row_and_local_file_and_hides_the_url(isolated_storage: Path, flow: FakeFlow, logs: LogCollector) -> None:
    flow.replies = [Reply(status=500, body=b'{"error":"flow broke"}')]

    result = submit_record(make_fields(), [("20260319_PR_Addin_NB.pdf", b"pr-content")])

    assert result.transaction_id is not None and result.storage_status == "error"
    assert "flow broke" in result.storage_message
    assert_no_secret(result.storage_message + "\n".join(logs.lines))
    assert get_transaction(result.transaction_id)["sharepoint_url"] in (None, "")
    assert list(isolated_storage.rglob("*.pdf"))


def test_not_configured_flow_is_skipped_not_an_error(isolated_storage: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("STORAGE_BACKEND", "powerautomate")

    result = submit_record(make_fields(), [("20260319_PR_Addin_NB.pdf", b"pr-content")])

    assert result.storage_status == "skipped" and result.transaction_id is not None


# ---------------------------------------------------------------------------
# scripts/check_flow.py (ให้ IT ตรวจ Flow)
# ---------------------------------------------------------------------------


def test_check_flow_sends_only_a_test_file_and_prints_no_secrets(flow: FakeFlow, capsys: pytest.CaptureFixture[str]) -> None:
    from scripts import check_flow

    assert check_flow.main() == 0

    (request,) = flow.requests
    body = request.json()
    assert body["folderParts"] == ["_connection_test"] and body["fileName"].startswith("check_flow_")
    output = capsys.readouterr()
    assert FILE_URL in output.out and "127.0.0.1" in output.out
    assert_no_secret(output.out + output.err)


def test_check_flow_reports_failure_with_exit_code_one(flow: FakeFlow, capsys: pytest.CaptureFixture[str]) -> None:
    from scripts import check_flow

    flow.replies = [Reply(status=403, body=b"{}")]

    assert check_flow.main() == 1
    assert "POWER_AUTOMATE_API_KEY" in capsys.readouterr().err


def test_check_flow_without_configuration_exits_with_one(capsys: pytest.CaptureFixture[str]) -> None:
    from scripts import check_flow

    assert check_flow.main() == 1
    assert "POWER_AUTOMATE_UPLOAD_URL" in capsys.readouterr().err
