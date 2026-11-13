"""ทดสอบการส่งข้อมูลแถวเข้า Master-List ผ่าน Flow (utils/masterlist_client.py) กับ Flow ปลอมบนเครื่องตัวเอง

ไม่ยิง Flow จริง: ใช้ FakeFlow จาก test_power_automate (http.server บนพอร์ตสุ่ม) และ conftest.py ล้างตัวแปร MASTERLIST_* ไว้แล้ว
"""

import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator

import pytest
from test_power_automate import (
    API_KEY,
    FILE_URL,
    SECRET_SIGNATURE,
    FakeFlow,
    LogCollector,
    Reply,
    assert_no_secret,
    logs,  # noqa: F401 - fixture ใช้ร่วมกัน
)
from test_submit_pipeline import make_fields

import utils.power_automate_api as flow_api
from data.database import count_transactions
from utils.masterlist_client import MASTERLIST_FIELDS, build_masterlist_payload, is_masterlist_configured, send_to_masterlist
from utils.submit_pipeline import attach_files_to_record, find_pr_folder_candidates, submit_record

UUID_PATTERN = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
ML_KEY = "ML-KEY-SECRET-42d8"
RECORD = {
    "date": "2026-03-19",
    "vendor": "บริษัท ทดสอบ จำกัด",
    "category": "Hardware",
    "total_price": 12345.5,
    "invoice_status": "Completed",
    "tel": "02-000-0000",
    "tax_id": "0105500000000",
    "pr_run_no": "PR-001",
    "pr_request_date": "2026-03-01",
    "qt_no": "QT-9",
    "description": "NB Alpha X100",
    "unit_price": 12345.5,
    "sharepoint_url": FILE_URL,
    "file_path": "/ห้ามส่ง/path/ในเครื่อง.pdf",  # ฟิลด์นอกรายการ ต้องไม่ถูกส่ง
    "id": 77,
}
OK_REPLY = {"ok": True}


@pytest.fixture
def ml_flow(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeFlow]:
    fake = FakeFlow()
    fake.reply_json(OK_REPLY)
    monkeypatch.setenv("MASTERLIST_API_URL", fake.url)
    monkeypatch.setenv("MASTERLIST_API_KEY", ML_KEY)
    sleeps: list[float] = []
    monkeypatch.setattr(flow_api, "time", SimpleNamespace(sleep=sleeps.append))
    fake.sleeps = sleeps  # type: ignore[attr-defined]
    yield fake
    fake.server.shutdown()
    fake.server.server_close()


@pytest.fixture
def file_flow(monkeypatch: pytest.MonkeyPatch) -> Iterator[FakeFlow]:
    """Flow ตัวแรก (ส่งไฟล์) แยกจาก Flow ของ Master-List"""
    fake = FakeFlow()
    monkeypatch.setenv("POWER_AUTOMATE_UPLOAD_URL", fake.url)
    monkeypatch.setenv("POWER_AUTOMATE_API_KEY", API_KEY)
    monkeypatch.setenv("STORAGE_BACKEND", "powerautomate")
    yield fake
    fake.server.shutdown()
    fake.server.server_close()


def assert_no_ml_secret(text: str) -> None:
    assert_no_secret(text)
    assert ML_KEY not in text


def send(request_id: str | None = None) -> tuple[bool, str]:
    sent, message = send_to_masterlist(build_masterlist_payload(RECORD), request_id=request_id)
    return sent, message or ""


# ---------------------------------------------------------------------------
# คำขอและคำตอบปกติ
# ---------------------------------------------------------------------------


def test_sends_exactly_the_masterlist_fields_with_request_id_and_key(ml_flow: FakeFlow) -> None:
    sent, message = send()

    assert sent is True and message == ""
    (request,) = ml_flow.requests
    body = request.json()
    assert set(body) == {"requestId", "record"}
    assert UUID_PATTERN.match(body["requestId"])
    assert list(body["record"]) == list(MASTERLIST_FIELDS)
    assert body["record"]["vendor"] == "บริษัท ทดสอบ จำกัด" and body["record"]["total_price"] == 12345.5
    assert "file_path" not in json.dumps(body) and "ห้ามส่ง" not in json.dumps(body)  # ไม่ส่ง path/รหัสแถวภายใน
    assert request.headers["x-api-key"] == ML_KEY
    assert request.headers["content-type"].startswith("application/json")
    assert request.path == f"/flow?sig={SECRET_SIGNATURE}"


def test_no_key_header_when_not_configured(ml_flow: FakeFlow, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MASTERLIST_API_KEY")
    assert send()[0] is True
    assert "x-api-key" not in ml_flow.requests[0].headers


def test_each_send_gets_a_new_request_id(ml_flow: FakeFlow) -> None:
    send()
    send()
    ids = {request.json()["requestId"] for request in ml_flow.requests}
    assert len(ids) == 2


def test_explicit_request_id_is_used_as_given(ml_flow: FakeFlow) -> None:
    fixed = "11111111-2222-4333-8444-555555555555"
    assert send(request_id=fixed)[0] is True and send(request_id=fixed)[0] is True
    assert [request.json()["requestId"] for request in ml_flow.requests] == [fixed, fixed]


def test_item_url_in_reply_is_optional(ml_flow: FakeFlow) -> None:
    ml_flow.reply_json({"ok": True, "itemUrl": "https://example.sharepoint.test/lists/ml/1"})
    assert send()[0] is True


def test_not_configured_skips_without_network(ml_flow: FakeFlow, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASTERLIST_API_URL", "")
    assert is_masterlist_configured() is False

    sent, message = send()

    assert sent is False and "ยังไม่ได้ตั้งค่า" in message
    assert ml_flow.requests == []


# ---------------------------------------------------------------------------
# retry: เฉพาะ 429/503 และใช้ requestId เดิม
# ---------------------------------------------------------------------------


def test_retry_on_429_keeps_the_same_request_id(ml_flow: FakeFlow) -> None:
    ml_flow.replies = [
        Reply(status=429, body=b"{}", headers={"Retry-After": "2"}),
        Reply(status=503, body=b"{}"),
        Reply(body=json.dumps(OK_REPLY).encode()),
    ]

    assert send()[0] is True

    assert len(ml_flow.requests) == 3
    assert len({request.json()["requestId"] for request in ml_flow.requests}) == 1
    assert ml_flow.sleeps[0] == 2.0  # type: ignore[attr-defined]


def test_503_beyond_retry_limit_fails_with_thai_message(ml_flow: FakeFlow) -> None:
    ml_flow.replies = [Reply(status=503, body=b"{}")]

    sent, message = send()

    assert sent is False and "503" in message
    assert len(ml_flow.requests) == 3  # ครั้งแรก + retry 2 ครั้ง
    assert_no_ml_secret(message)


@pytest.mark.parametrize("status", [502, 504])
def test_gateway_errors_are_not_retried_and_warn_it_may_exist(ml_flow: FakeFlow, status: int) -> None:
    ml_flow.replies = [Reply(status=status, body=b"{}")]

    sent, message = send()

    assert sent is False and len(ml_flow.requests) == 1
    assert "Master-List" in message and "ตรวจ" in message and "ส่งซ้ำ" in message


def test_timeout_is_not_retried_and_warns_it_may_exist(ml_flow: FakeFlow, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASTERLIST_TIMEOUT_SECONDS", "1")
    ml_flow.replies = [Reply(body=json.dumps(OK_REPLY).encode(), delay=2.5)]

    sent, message = send()

    assert sent is False and len(ml_flow.requests) == 1
    assert "1 วินาที" in message and "Master-List" in message and "ส่งซ้ำ" in message


def test_connection_drop_is_not_retried_and_warns_it_may_exist(ml_flow: FakeFlow) -> None:
    ml_flow.replies = [Reply(drop=True)]

    sent, message = send()

    assert sent is False and len(ml_flow.requests) == 1
    assert "Master-List" in message and "ส่งซ้ำ" in message


def test_default_timeout_is_shorter_than_the_file_flow(ml_flow: FakeFlow) -> None:
    from config.settings import DEFAULT_MASTERLIST_TIMEOUT_SECONDS, DEFAULT_POWER_AUTOMATE_TIMEOUT_SECONDS

    assert DEFAULT_MASTERLIST_TIMEOUT_SECONDS == 30
    assert DEFAULT_MASTERLIST_TIMEOUT_SECONDS < DEFAULT_POWER_AUTOMATE_TIMEOUT_SECONDS


# ---------------------------------------------------------------------------
# ข้อผิดพลาดจาก Flow
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status", [401, 403])
def test_rejected_call_points_to_key_setting(ml_flow: FakeFlow, status: int) -> None:
    ml_flow.replies = [Reply(status=status, body=b"{}")]
    sent, message = send()
    assert sent is False and "MASTERLIST_API_KEY" in message
    assert len(ml_flow.requests) == 1


def test_404_means_flow_is_gone(ml_flow: FakeFlow) -> None:
    ml_flow.replies = [Reply(status=404, body=b"{}")]
    sent, message = send()
    assert sent is False and "ไม่พบ Flow" in message


def test_500_with_error_text_shows_a_cleaned_flow_message(ml_flow: FakeFlow) -> None:
    ml_flow.replies = [Reply(status=500, body=json.dumps({"error": f"<b>พัง</b> {ML_KEY}"}).encode())]

    sent, message = send()

    assert sent is False and "HTTP 500" in message and "พัง" in message
    assert "<b>" not in message
    assert_no_ml_secret(message)
    assert len(ml_flow.requests) == 1


FASTAPI_422 = {"detail": [{"loc": ["body", "record", "pr_run_no"], "msg": "none is not an allowed value", "type": "type_error.none.not_allowed"}]}


def test_422_detail_list_shows_which_field_is_wrong(ml_flow: FakeFlow, logs: LogCollector) -> None:  # noqa: F811
    ml_flow.replies = [Reply(status=422, body=json.dumps(FASTAPI_422).encode())]

    sent, message = send()

    assert sent is False and "HTTP 422" in message
    assert "pr_run_no" in message and "none is not an allowed value" in message
    assert any("422" in line and "pr_run_no" in line for line in logs.lines)  # log มีรายละเอียดด้วย
    assert len(ml_flow.requests) == 1  # 4xx ไม่ retry


@pytest.mark.parametrize("key", ["errors", "details", "message", "detail"])
def test_422_other_detail_keys_are_shown(ml_flow: FakeFlow, key: str) -> None:
    ml_flow.replies = [Reply(status=422, body=json.dumps({key: "วันที่ผิดรูปแบบ", "error": "ข้อมูลไม่ถูกต้อง"}).encode())]

    sent, message = send()

    assert sent is False and "ข้อมูลไม่ถูกต้อง" in message and "วันที่ผิดรูปแบบ" in message


def test_422_detail_is_truncated_and_cleaned(ml_flow: FakeFlow) -> None:
    ml_flow.replies = [Reply(status=422, body=json.dumps({"detail": "<i>x</i>\n" + "ยาว" * 1000}).encode())]

    _, message = send()

    assert "<i>" not in message and "\n" not in message
    assert len(message) < flow_api.MAX_FLOW_ERROR_DETAIL_LENGTH + 100


def test_422_echoed_record_values_url_and_key_are_masked_in_message_and_log(ml_flow: FakeFlow, logs: LogCollector) -> None:  # noqa: F811
    echo = {"detail": [{"msg": "bad value", "input": RECORD["vendor"], "ctx": f"{RECORD['description']} {RECORD['tax_id']} {ml_flow.url} {ML_KEY}"}]}
    ml_flow.replies = [Reply(status=422, body=json.dumps(echo, ensure_ascii=False).encode())]

    sent, message = send()

    assert sent is False and "bad value" in message
    combined = message + "\n" + "\n".join(logs.lines)
    for value in (RECORD["vendor"], RECORD["description"], RECORD["tax_id"]):
        assert value not in combined
    assert "***" in message
    assert_no_ml_secret(combined)


TRICKY_DESCRIPTION = 'NB "Alpha" X100\nขนาด 15\\16 นิ้ว'


def test_422_echoed_value_with_quotes_backslash_and_newline_is_masked(ml_flow: FakeFlow, logs: LogCollector) -> None:  # noqa: F811
    echo = {"detail": [{"msg": "bad value", "input": TRICKY_DESCRIPTION}], "message": TRICKY_DESCRIPTION}
    ml_flow.replies = [Reply(status=422, body=json.dumps(echo, ensure_ascii=False).encode())]

    sent, message = send_to_masterlist(build_masterlist_payload({**RECORD, "description": TRICKY_DESCRIPTION}))
    message = message or ""

    assert sent is False and "bad value" in message and "***" in message
    combined = message + "\n" + "\n".join(logs.lines)
    escaped = json.dumps(TRICKY_DESCRIPTION, ensure_ascii=False)[1:-1]
    for leaked in (TRICKY_DESCRIPTION, escaped, "Alpha", "15\\16", "15\\\\16"):
        assert leaked not in combined


@pytest.mark.parametrize("body", [
    json.dumps([{"loc": ["body", "record", "pr_run_no"], "msg": "field required", "input": "NB Alpha X100"}]),
    json.dumps(["pr_run_no is required", "NB Alpha X100"]),
])
def test_422_array_reply_shows_masked_detail_without_crashing(ml_flow: FakeFlow, logs: LogCollector, body: str) -> None:  # noqa: F811
    ml_flow.replies = [Reply(status=422, body=body.encode())]

    sent, message = send()

    assert sent is False and "HTTP 422" in message and "pr_run_no" in message
    combined = message + "\n" + "\n".join(logs.lines)
    assert RECORD["description"] not in combined and "***" in message
    assert_no_ml_secret(combined)


@pytest.mark.parametrize("body", [b"", b"{}", b"[]", b"null", b"42", b'""', b"not json", b"<html>boom</html>"])
def test_422_without_any_detail_does_not_crash(ml_flow: FakeFlow, body: bytes) -> None:
    ml_flow.replies = [Reply(status=422, body=body)]

    sent, message = send()

    assert sent is False
    assert "HTTP 422" in message
    assert not message.rstrip().endswith(":")
    assert "boom" not in message


def test_400_error_from_masterlist_shows_which_field_is_wrong(ml_flow: FakeFlow, logs: LogCollector) -> None:  # noqa: F811
    ml_flow.replies = [Reply(status=400, body=json.dumps({"error": "record.vendor: too long (max 300)"}).encode())]

    sent, message = send()

    assert sent is False and "HTTP 400" in message and "record.vendor: too long (max 300)" in message
    assert any("400" in line and "record.vendor" in line for line in logs.lines)
    assert len(ml_flow.requests) == 1  # 4xx ไม่ retry


def test_400_error_echoing_record_values_is_masked(ml_flow: FakeFlow, logs: LogCollector) -> None:  # noqa: F811
    ml_flow.replies = [Reply(status=400, body=json.dumps({"error": f"record.vendor: invalid {RECORD['vendor']} ({ML_KEY})"}, ensure_ascii=False).encode())]

    sent, message = send()

    combined = message + "\n" + "\n".join(logs.lines)
    assert sent is False and "record.vendor" in message and "***" in message
    assert RECORD["vendor"] not in combined
    assert_no_ml_secret(combined)


@pytest.mark.parametrize(("field", "limit"), [("vendor", 300), ("description", 5000), ("invoice_status", 100), ("date", 64)])
def test_value_over_known_limit_is_not_sent_and_value_is_not_shown(ml_flow: FakeFlow, logs: LogCollector, field: str, limit: int) -> None:  # noqa: F811
    too_long = "ก" * (limit + 1)

    sent, message = send_to_masterlist(build_masterlist_payload({**RECORD, field: too_long}))

    assert sent is False and field in message and str(limit + 1) in message and str(limit) in message
    assert too_long not in message and too_long not in "\n".join(logs.lines)
    assert ml_flow.requests == []  # ไม่ยิงคำขอที่รู้ว่าถูกปฏิเสธ


@pytest.mark.parametrize(("field", "limit"), [("vendor", 300), ("description", 5000), ("invoice_status", 100), ("date", 64)])
def test_value_exactly_at_limit_is_sent(ml_flow: FakeFlow, field: str, limit: int) -> None:
    sent, _ = send_to_masterlist(build_masterlist_payload({**RECORD, field: "ก" * limit}))

    assert sent is True and len(ml_flow.requests) == 1


def test_200_with_error_field_fails(ml_flow: FakeFlow) -> None:
    ml_flow.reply_json({"error": "ไม่มีสิทธิ์เขียนรายการ"})
    sent, message = send()
    assert sent is False and "ไม่มีสิทธิ์เขียนรายการ" in message


@pytest.mark.parametrize("body", [b"not json", b"[]", b"{}", b'{"ok": false}', b'{"ok": "true"}', b'{"fileUrl": "https://x.test/a"}'])
def test_200_without_ok_true_is_not_success_and_not_retried(ml_flow: FakeFlow, body: bytes) -> None:
    ml_flow.replies = [Reply(body=body)]

    sent, message = send()

    assert sent is False and len(ml_flow.requests) == 1
    assert "รูปแบบไม่ถูกต้อง" in message and "ตรวจ" in message and "ส่งซ้ำ" in message


def test_oversized_reply_is_rejected(ml_flow: FakeFlow) -> None:
    ml_flow.replies = [Reply(body=b'{"ok": true, "pad": "' + b"x" * (70 * 1024) + b'"}')]
    sent, message = send()
    assert sent is False and "ใหญ่ผิดปกติ" in message


def test_redirect_is_not_followed(ml_flow: FakeFlow) -> None:
    other = FakeFlow()
    other.reply_json(OK_REPLY)
    try:
        ml_flow.replies = [Reply(status=302, headers={"Location": other.url})]
        sent, message = send()
        assert sent is False and "redirect" in message
        assert other.requests == []  # ไม่ส่งต่อลายเซ็นลับไปที่อื่น
    finally:
        other.server.shutdown()
        other.server.server_close()


@pytest.mark.parametrize("url", ["http://example.test/flow?sig=1", "ftp://example.test/x", "not a url"])
def test_unsafe_or_malformed_url_is_rejected_without_leaking_it(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setenv("MASTERLIST_API_URL", url)
    sent, message = send()
    assert sent is False and "MASTERLIST_API_URL" in message and url not in message


# ---------------------------------------------------------------------------
# MASTERLIST_ALLOW_HTTP: รับ http เฉพาะ IP ภายใน และเฉพาะ Master-List (ทุกเทสต์ในหมวดนี้ดัก _send ไว้ ไม่มีอะไรออกเครือข่าย)
# ---------------------------------------------------------------------------

PRIVATE_HTTP_URL = "http://10.1.2.3:8080/api/masterlist?token=PATH-SECRET-1"


@pytest.fixture
def stub_send(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """แทน _send: จดว่าถูกเรียกด้วย URL / host ใด แล้วตอบ {"ok": true} โดยไม่ต่อเครือข่าย"""
    calls: list[tuple[str, str]] = []

    def fake_send(request, host, timeout, target=None):  # type: ignore[no-untyped-def]  # noqa: ANN001, ANN202
        calls.append((request.full_url, host))
        return 200, b'{"ok": true}'

    monkeypatch.setattr(flow_api, "_send", fake_send)
    return calls


@pytest.mark.parametrize("host", ["10.1.2.3", "10.0.0.1", "10.255.255.254", "172.16.0.5", "172.31.255.1", "192.168.1.10", "192.168.0.1"])
def test_allow_http_on_accepts_private_ip(stub_send: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch, host: str) -> None:
    monkeypatch.setenv("MASTERLIST_ALLOW_HTTP", "1")
    monkeypatch.setenv("MASTERLIST_API_URL", f"http://{host}:8080/api?token=PATH-SECRET-1")
    sent, message = send()
    assert sent is True and message == ""
    assert [call[1] for call in stub_send] == [host]


@pytest.mark.parametrize("value", ["", "0", "false", "off", "no", "maybe"])
def test_allow_http_off_by_default_or_falsy_rejects_private_ip(stub_send: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("MASTERLIST_ALLOW_HTTP", value)
    monkeypatch.setenv("MASTERLIST_API_URL", PRIVATE_HTTP_URL)
    sent, message = send()
    assert sent is False and "MASTERLIST_API_URL" in message and "https://" in message
    assert "10.1.2.3" not in message and "PATH-SECRET-1" not in message
    assert stub_send == []


@pytest.mark.parametrize(
    "host",
    [
        "8.8.8.8",  # IP สาธารณะ
        "172.15.255.255",  # ติดขอบล่างของ 172.16/12
        "172.32.0.1",  # เลยขอบบนของ 172.16/12
        "11.0.0.1",
        "192.169.1.1",
        "100.64.0.1",  # CGNAT ไม่ใช่ IP ภายในตาม RFC 1918
        "169.254.169.254",  # link-local (metadata ของคลาวด์) ต้องไม่ผ่าน
        "0.0.0.0",
        "intranet.local",  # ชื่อโฮสต์ ไม่ใช่ IP: ไม่รับ (ชื่อชี้ไปที่ไหนก็ได้)
        "flow.example.com",
        "[fc00::1]",  # IPv6 ภายใน ยังไม่รองรับ
    ],
)
def test_allow_http_on_still_rejects_non_private_hosts(stub_send: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch, host: str) -> None:
    monkeypatch.setenv("MASTERLIST_ALLOW_HTTP", "1")
    url = f"http://{host}/api?token=PATH-SECRET-1"
    monkeypatch.setenv("MASTERLIST_API_URL", url)
    sent, message = send()
    assert sent is False and "MASTERLIST_API_URL" in message
    assert "PATH-SECRET-1" not in message and host.strip("[]") not in message
    assert stub_send == []


def test_allow_http_does_not_break_https(stub_send: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASTERLIST_ALLOW_HTTP", "1")
    monkeypatch.setenv("MASTERLIST_API_URL", "https://prod-00.example.com/workflows/x?sig=PATH-SECRET-1")
    assert send() == (True, "")
    assert stub_send[0][1] == "prod-00.example.com"


def test_loopback_http_still_works_without_the_flag(ml_flow: FakeFlow) -> None:
    assert send() == (True, "")


def test_allow_http_does_not_apply_to_the_file_flow(monkeypatch: pytest.MonkeyPatch, stub_send: list[tuple[str, str]]) -> None:
    monkeypatch.setenv("MASTERLIST_ALLOW_HTTP", "1")
    monkeypatch.setenv("POWER_AUTOMATE_UPLOAD_URL", "http://10.1.2.3/upload?sig=PATH-SECRET-1")
    with pytest.raises(flow_api.PowerAutomateError, match="POWER_AUTOMATE_UPLOAD_URL") as error:
        flow_api.upload_file_to_flow("a.pdf", b"x", ["2026"])
    assert "10.1.2.3" not in str(error.value) and "PATH-SECRET-1" not in str(error.value)
    assert stub_send == []


def test_plain_http_to_private_ip_logs_an_unencrypted_warning_without_secrets(
    stub_send: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch, logs: LogCollector  # noqa: F811
) -> None:
    monkeypatch.setenv("MASTERLIST_ALLOW_HTTP", "1")
    monkeypatch.setenv("MASTERLIST_API_URL", PRIVATE_HTTP_URL)
    monkeypatch.setenv("MASTERLIST_API_KEY", ML_KEY)
    assert send() == (True, "")
    text = "\n".join(logs.lines)
    assert "ไม่เข้ารหัส" in text and "MASTERLIST_API_URL" in text
    assert PRIVATE_HTTP_URL not in text and "PATH-SECRET-1" not in text and "/api/masterlist" not in text
    assert ML_KEY not in text


def test_https_and_loopback_do_not_log_the_unencrypted_warning(
    stub_send: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch, logs: LogCollector  # noqa: F811
) -> None:
    monkeypatch.setenv("MASTERLIST_ALLOW_HTTP", "1")
    for url in ("https://prod-00.example.com/x?sig=1", "http://127.0.0.1:9/x?sig=1"):
        monkeypatch.setenv("MASTERLIST_API_URL", url)
        assert send() == (True, "")
    assert not any("ไม่เข้ารหัส" in line for line in logs.lines)


def test_http_to_private_ip_bypasses_the_system_proxy(monkeypatch: pytest.MonkeyPatch) -> None:
    """IP ภายในต้องไม่ถูกส่งผ่าน proxy ของระบบ (เหมือนเครื่องตัวเอง) ดักที่ build_opener จึงไม่ต่อเครือข่าย"""
    import urllib.request

    captured: list[list[object]] = []

    class StopHere(Exception):
        pass

    def fake_build_opener(*handlers: object) -> object:
        captured.append(list(handlers))
        raise StopHere

    monkeypatch.setattr(urllib.request, "build_opener", fake_build_opener)
    request = urllib.request.Request("http://10.1.2.3/x", data=b"{}")
    with pytest.raises(StopHere):
        flow_api._send(request, "10.1.2.3", 5)
    assert any(isinstance(handler, urllib.request.ProxyHandler) for handler in captured[0])


def test_key_with_newline_is_rejected_without_leaking_it(ml_flow: FakeFlow, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASTERLIST_API_KEY", "bad\nkey-VALUE")
    sent, message = send()
    assert sent is False and "MASTERLIST_API_KEY" in message and "bad" not in message
    assert ml_flow.requests == []


def test_secrets_never_reach_logs_or_messages(ml_flow: FakeFlow, logs: LogCollector) -> None:  # noqa: F811
    for reply in (Reply(status=500, body=json.dumps({"error": ML_KEY}).encode()), Reply(drop=True), Reply(body=b"{}"), Reply(status=429)):
        ml_flow.replies = [reply]
        _, message = send()
        assert_no_ml_secret(message)
    for line in logs.lines:
        assert_no_ml_secret(line)


# ---------------------------------------------------------------------------
# ผสมกับขั้นตอนบันทึกรายการ
# ---------------------------------------------------------------------------

PR_NAME = "20260319_PR_Addin_NB.pdf"


def test_new_record_is_sent_after_it_is_saved(isolated_storage: Path, ml_flow: FakeFlow) -> None:
    result = submit_record(make_fields(), [(PR_NAME, b"pr-content")])

    assert result.transaction_id is not None
    assert result.masterlist_sent is True and result.masterlist_message == ""
    (request,) = ml_flow.requests
    assert request.json()["record"]["description"] == "NB Alpha X100"


def test_masterlist_failure_keeps_row_and_local_file(isolated_storage: Path, ml_flow: FakeFlow) -> None:
    ml_flow.replies = [Reply(status=500, body=b"{}")]

    result = submit_record(make_fields(), [(PR_NAME, b"pr-content")])

    assert result.transaction_id is not None and count_transactions() == 1
    assert list(isolated_storage.rglob("*.pdf"))
    assert result.masterlist_sent is False and "HTTP 500" in result.masterlist_message
    assert not result.error


def test_file_flow_ok_but_masterlist_down(isolated_storage: Path, ml_flow: FakeFlow, file_flow: FakeFlow) -> None:
    file_flow.reply_json({"fileUrl": FILE_URL})
    ml_flow.replies = [Reply(drop=True)]

    result = submit_record(make_fields(), [(PR_NAME, b"pr-content")])

    assert result.storage_status == "ok" and result.masterlist_sent is False
    assert count_transactions() == 1
    sent_record = ml_flow.requests[0].json()["record"]
    assert sent_record["sharepoint_url"] == FILE_URL  # Master-List ได้ลิงก์ไฟล์ที่ขึ้นออนไลน์แล้ว


def test_file_flow_down_but_masterlist_ok(isolated_storage: Path, ml_flow: FakeFlow, file_flow: FakeFlow) -> None:
    file_flow.replies = [Reply(status=500, body=b"{}")]

    result = submit_record(make_fields(), [(PR_NAME, b"pr-content")])

    assert result.storage_status == "error" and result.masterlist_sent is True
    assert count_transactions() == 1
    assert ml_flow.requests[0].json()["record"]["sharepoint_url"] is None


def test_attaching_files_to_an_existing_row_does_not_call_masterlist(isolated_storage: Path, ml_flow: FakeFlow) -> None:
    submit_record(make_fields(), [(PR_NAME, b"pr-content")])
    assert len(ml_flow.requests) == 1

    attach_files_to_record(find_pr_folder_candidates()[0], [("quotation.pdf", b"quote")])

    assert len(ml_flow.requests) == 1


def test_submit_does_not_touch_network_when_masterlist_not_configured(isolated_storage: Path, ml_flow: FakeFlow, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MASTERLIST_API_URL", "")

    result = submit_record(make_fields(), [(PR_NAME, b"pr-content")])

    assert result.masterlist_sent is False and "ยังไม่ได้ตั้งค่า" in result.masterlist_message
    assert ml_flow.requests == []


# ---------------------------------------------------------------------------
# สรุปผลหลังอัปโหลดต้องบอกเมื่อ Master-List ส่งไม่สำเร็จ (ไม่เงียบ)
# ---------------------------------------------------------------------------


def _summary_for(results: list) -> str:
    from pages_ui.overview import build_upload_summary
    from utils.upload_processor import KIND_ATTACHED, KIND_CREATED, ItemOutcome, UploadReport

    items = [ItemOutcome(KIND_CREATED, f"pr{i}.pdf", f"งาน {i}", result) for i, result in enumerate(results)]
    return build_upload_summary(UploadReport(items=items))


def test_upload_summary_reports_masterlist_failure_once_per_message(isolated_storage: Path, ml_flow: FakeFlow) -> None:
    ml_flow.replies = [Reply(status=500, body=b"{}")]
    first = submit_record(make_fields(description="A"), [("20260319_PR_A.pdf", b"a")])
    second = submit_record(make_fields(description="B"), [("20260319_PR_B.pdf", b"b")])

    summary = _summary_for([first, second])

    assert summary.count("HTTP 500") == 1 and "ส่งไม่สำเร็จ 2 แถว" in summary  # ข้อความเดียวกันรวมเป็นบรรทัดเดียว
    assert "ส่งเข้า Master-List แล้ว" not in summary
    assert_no_ml_secret(summary)


def test_upload_summary_counts_sent_and_failed_separately(isolated_storage: Path, ml_flow: FakeFlow) -> None:
    ok = submit_record(make_fields(description="A"), [("20260319_PR_A.pdf", b"a")])
    ml_flow.replies = [Reply(status=500, body=b"{}")]
    failed = submit_record(make_fields(description="B"), [("20260319_PR_B.pdf", b"b")])

    summary = _summary_for([ok, failed])

    assert "ส่งเข้า Master-List แล้ว 1 แถว" in summary and "HTTP 500" in summary


def test_upload_summary_stays_quiet_when_masterlist_not_configured(isolated_storage: Path) -> None:
    result = submit_record(make_fields(), [(PR_NAME, b"pr-content")])

    summary = _summary_for([result])

    assert "Master-List" not in summary  # ป้ายบนหน้าอัปโหลดบอกอยู่แล้วว่ายังไม่ตั้งค่า ไม่ต้องเตือนทุกครั้ง
