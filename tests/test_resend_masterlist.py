"""ทดสอบ scripts/resend_masterlist.py กับเซิร์ฟเวอร์ปลอมบน 127.0.0.1 และฐานข้อมูลชั่วคราว (ไม่ส่งไป Master-List จริง)"""

import hashlib
import json
import sqlite3
import uuid
from pathlib import Path

import pytest
from test_masterlist_flow import ML_KEY, UUID_PATTERN, FakeFlow, Reply, ml_flow  # noqa: F401 - fixture ใช้ร่วมกัน

import data.database as database
from scripts.resend_masterlist import REQUEST_ID_NAMESPACE, main, make_request_id
from utils.masterlist_client import MASTERLIST_FIELDS

VENDOR = "บริษัท ทดสอบ จำกัด"
DESCRIPTION = "NB Alpha X100"


def add_row(**overrides: object) -> int:
    fields = {"date": "2026-03-19", "vendor": VENDOR, "total_price": 12345.5, "pr_run_no": "PR-001", "description": DESCRIPTION, "unit_price": 12345.5}
    fields.update(overrides)
    new_id = database.add_transaction(**fields)  # type: ignore[arg-type]
    assert new_id is not None
    return new_id


def db_digest() -> str:
    return hashlib.sha256(Path(database.DB_PATH).read_bytes()).hexdigest()


def test_dry_run_sends_nothing_and_prints_no_values(isolated_storage: Path, ml_flow: FakeFlow, capsys: pytest.CaptureFixture[str]) -> None:  # noqa: F811
    row_id = add_row()
    before = db_digest()

    assert main(["--id", str(row_id)]) == 0

    output = capsys.readouterr()
    text = output.out + output.err
    assert ml_flow.requests == []
    assert "dry-run" in text and "13 ฟิลด์" in text
    for secret in (VENDOR, DESCRIPTION, "PR-001", ML_KEY, ml_flow.url, "12345"):
        assert secret not in text
    assert db_digest() == before


def test_send_posts_one_request_with_a_stable_request_id_and_does_not_touch_db(isolated_storage: Path, ml_flow: FakeFlow, capsys: pytest.CaptureFixture[str]) -> None:  # noqa: F811
    row_id = add_row()
    before = db_digest()

    assert main(["--id", str(row_id), "--send"]) == 0

    (request,) = ml_flow.requests
    body = request.json()
    assert set(body) == {"requestId", "record"} and UUID_PATTERN.match(body["requestId"])
    assert list(body["record"]) == list(MASTERLIST_FIELDS)
    assert body["record"]["vendor"] == VENDOR and body["record"]["pr_run_no"] == "PR-001"
    assert "file_path" not in json.dumps(body)
    assert db_digest() == before  # ไม่แก้ฐานข้อมูล ไม่สร้างแถวใหม่
    assert not list(isolated_storage.parent.glob("**/*.pdf"))  # ไม่มีไฟล์ถูกสร้าง/อัปโหลด
    text = capsys.readouterr()
    assert VENDOR not in text.out + text.err and ML_KEY not in text.out + text.err


def test_same_row_and_db_resend_uses_the_same_request_id(isolated_storage: Path, ml_flow: FakeFlow) -> None:  # noqa: F811
    row_id = add_row()
    assert main(["--id", str(row_id), "--send"]) == 0
    assert main(["--id", str(row_id), "--send"]) == 0
    ids = [request.json()["requestId"] for request in ml_flow.requests]
    assert len(ids) == 2 and ids[0] == ids[1] and UUID_PATTERN.match(ids[0])


def test_request_id_differs_by_row_id_and_by_db_file_name(tmp_path: Path) -> None:
    db_a, db_b = tmp_path / "a.db", tmp_path / "b.db"
    assert make_request_id(db_a, 6) == make_request_id(db_a, 6)
    assert make_request_id(db_a, 6) != make_request_id(db_a, 7)
    assert make_request_id(db_a, 6) != make_request_id(db_b, 6)
    assert make_request_id(tmp_path / "x" / "a.db", 6) == make_request_id(db_a, 6)  # ใช้เฉพาะชื่อไฟล์
    assert make_request_id(db_a, 6) == str(uuid.uuid5(REQUEST_ID_NAMESPACE, "a.db:6"))


def test_different_rows_send_different_request_ids(isolated_storage: Path, ml_flow: FakeFlow) -> None:  # noqa: F811
    first, second = add_row(), add_row(description="อีกรายการ")
    assert main(["--id", str(first), "--send"]) == 0
    assert main(["--id", str(second), "--send"]) == 0
    assert len({request.json()["requestId"] for request in ml_flow.requests}) == 2


def test_output_never_prints_host_and_warns_about_changed_rows(isolated_storage: Path, ml_flow: FakeFlow, capsys: pytest.CaptureFixture[str]) -> None:  # noqa: F811
    row_id = add_row()
    assert main(["--id", str(row_id)]) == 0
    text = capsys.readouterr().out
    assert "127.0.0.1" not in text and "ตั้งค่าแล้ว" in text and "requestId ใหม่" in text and "ปฏิเสธแถวเก่า" in text
    assert main(["--id", str(row_id), "--send"]) == 0
    text = capsys.readouterr().out
    assert "127.0.0.1" not in text and "requestId ใหม่" in text and "ปฏิเสธแถวเก่า" in text


def test_missing_row_is_not_sent(isolated_storage: Path, ml_flow: FakeFlow, capsys: pytest.CaptureFixture[str]) -> None:  # noqa: F811
    assert main(["--id", "999", "--send"]) == 1
    assert ml_flow.requests == [] and "ไม่พบแถว" in capsys.readouterr().err


def test_deleted_row_is_not_sent(isolated_storage: Path, ml_flow: FakeFlow) -> None:  # noqa: F811
    row_id = add_row()
    with sqlite3.connect(database.DB_PATH) as connection:
        connection.execute("UPDATE transactions SET is_deleted = 1 WHERE id = ?", (row_id,))

    assert main(["--id", str(row_id), "--send"]) == 1
    assert ml_flow.requests == []


def test_over_length_value_is_not_sent_and_not_shown(isolated_storage: Path, ml_flow: FakeFlow, capsys: pytest.CaptureFixture[str]) -> None:  # noqa: F811
    too_long = "ก" * 301
    row_id = add_row(vendor=too_long)

    assert main(["--id", str(row_id), "--send"]) == 1

    output = capsys.readouterr()
    assert ml_flow.requests == [] and "vendor" in output.err and "301" in output.err
    assert too_long not in output.out + output.err


def test_server_400_is_reported_without_values_and_returns_failure(isolated_storage: Path, ml_flow: FakeFlow, capsys: pytest.CaptureFixture[str]) -> None:  # noqa: F811
    row_id = add_row()
    ml_flow.replies = [Reply(status=400, body=json.dumps({"error": "record.vendor: too long (max 300)"}).encode())]

    assert main(["--id", str(row_id), "--send"]) == 1

    err = capsys.readouterr().err
    assert "HTTP 400" in err and "record.vendor" in err and VENDOR not in err
    assert len(ml_flow.requests) == 1


def test_send_without_configured_url_fails_without_network(isolated_storage: Path, ml_flow: FakeFlow, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:  # noqa: F811
    row_id = add_row()
    monkeypatch.setenv("MASTERLIST_API_URL", "")

    assert main(["--id", str(row_id), "--send"]) == 1
    assert ml_flow.requests == [] and "MASTERLIST_API_URL" in capsys.readouterr().err
