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


def send() -> tuple[bool, str]:
    sent, message = send_to_masterlist(build_masterlist_payload(RECORD))
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
