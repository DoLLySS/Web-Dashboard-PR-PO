"""ทดสอบการล้างแถวที่ถูกซ่อนและรายละเอียดใน Audit Log (scripts/purge_deleted.py)"""

import hashlib
import sqlite3
import tarfile
from contextlib import closing
from pathlib import Path

import pytest

import data.database as database
import scripts.purge_deleted as purge
from data.database import AUDIT_REDACTED_DETAILS, _bump_data_version, _get_connection, get_transactions, update_transaction
from pr_fixtures import make_pr_pdf
from scripts.backup import DATABASE_FILE_NAME, UPLOADS_ARCHIVE_NAME
from utils.upload_processor import process_upload

HIDDEN_ITEM = "Printer Beta Y200"
HIDDEN_VENDOR = "Beta Hidden Co"
ACTIVE_ITEM = "Monitor Dell U2724DE"


def upload(name: str, item: str, vendor: str = "Alpha Co") -> dict:
    process_upload([(name, make_pr_pdf([(item, "9,000.00")], vendor=vendor))], "Hardware", "รอใบกำกับภาษี", lambda n: n, lambda n: None)
    return next(row for row in get_transactions() if row["description"].startswith(item))


def hide(row_id: int) -> None:
    with _get_connection() as conn:
        conn.execute("UPDATE transactions SET is_deleted = 1 WHERE id = ?", (row_id,))
        conn.execute("INSERT INTO audit_logs (action_type, record_id, details) VALUES ('SOFT_DELETE', ?, '{\"is_deleted\": 1}')", (row_id,))
    _bump_data_version()


@pytest.fixture
def rows(isolated_storage: Path) -> tuple[dict, dict]:
    """แถวใช้งาน 1 แถว + แถวที่ถูกซ่อน 1 แถว คนละโฟลเดอร์"""
    active = upload("PR_Active.pdf", ACTIVE_ITEM)
    hidden = upload("PR_Hidden.pdf", HIDDEN_ITEM, HIDDEN_VENDOR)
    assert update_transaction(hidden["id"], vendor=HIDDEN_VENDOR + " 2")  # ให้มี log UPDATE ด้วย
    hide(hidden["id"])
    return active, hidden


def table(name: str, db_path: Path) -> list[tuple]:
    with closing(sqlite3.connect(db_path)) as conn:
        return conn.execute(f"SELECT * FROM {name}").fetchall()  # noqa: S608 - ชื่อตารางจากเทสต์เท่านั้น


def disk_state(root: Path) -> list[tuple[str, str]]:
    return sorted((str(p.relative_to(root)), hashlib.sha256(p.read_bytes()).hexdigest()) for p in root.rglob("*") if p.is_file())


def audit_rows(record_id: int) -> list[tuple]:
    with closing(sqlite3.connect(database.DB_PATH)) as conn:
        return conn.execute(
            "SELECT action_type, details, timestamp FROM audit_logs WHERE record_id = ? ORDER BY log_id", (record_id,)
        ).fetchall()


def run_apply(tmp_path: Path, *extra: str) -> int:
    return purge.main(["--apply", "--yes", "--dest", str(tmp_path / "bk"), *extra])


def only_backup(tmp_path: Path) -> Path:
    folders = list((tmp_path / "bk").iterdir())
    assert len(folders) == 1
    return folders[0]


def test_dry_run_changes_nothing_and_counts_are_right(
    rows: tuple[dict, dict], isolated_storage: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = (table("transactions", database.DB_PATH), table("audit_logs", database.DB_PATH), disk_state(isolated_storage))

    assert purge.main(["--dest", str(tmp_path / "bk")]) == 0

    assert before == (table("transactions", database.DB_PATH), table("audit_logs", database.DB_PATH), disk_state(isolated_storage))
    assert not (tmp_path / "bk").exists()
    output = capsys.readouterr().out
    assert "แถวที่ถูกซ่อน ที่จะลบ: 1 แถว" in output
    assert "แถวที่ใช้งานอยู่ (ไม่แตะ): 1 แถว" in output
    assert "ไฟล์ในเครื่องที่จะลบ: 1 ไฟล์" in output
    summary = purge.read_summary(database.DB_PATH)
    assert summary.audit_counts == {"INSERT": 1, "UPDATE": 1, "SOFT_DELETE": 1}


def test_apply_removes_hidden_row_and_keeps_active_row(rows: tuple[dict, dict], isolated_storage: Path, tmp_path: Path) -> None:
    active, hidden = rows
    active_logs = audit_rows(active["id"])
    hidden_logs = audit_rows(hidden["id"])

    assert run_apply(tmp_path) == 0

    assert [row[0] for row in table("transactions", database.DB_PATH)] == [active["id"]]
    assert audit_rows(active["id"]) == active_logs  # log ของแถวที่ใช้งานไม่ถูกแตะ
    after = audit_rows(hidden["id"])
    # เก็บวันเวลาและประเภทการกระทำเดิม ล้างเฉพาะ details และเพิ่ม log การลบ
    assert [(action, stamp) for action, _details, stamp in after[:-1]] == [(action, stamp) for action, _details, stamp in hidden_logs]
    assert all(details == AUDIT_REDACTED_DETAILS for _action, details, _stamp in after[:-1])
    assert after[-1][0] == "DELETE"
    assert [Path(name).name for name, _hash in disk_state(isolated_storage)] == ["PR_Active.pdf"]


def test_old_text_is_gone_from_database_file_but_kept_in_backup(rows: tuple[dict, dict], tmp_path: Path) -> None:
    assert HIDDEN_VENDOR.encode() in database.DB_PATH.read_bytes()

    assert run_apply(tmp_path) == 0

    raw = database.DB_PATH.read_bytes()
    assert HIDDEN_VENDOR.encode() not in raw and HIDDEN_ITEM.encode() not in raw
    assert ACTIVE_ITEM.encode() in raw
    assert HIDDEN_VENDOR.encode() in (only_backup(tmp_path) / DATABASE_FILE_NAME).read_bytes()


def test_backup_restores_everything(rows: tuple[dict, dict], isolated_storage: Path, tmp_path: Path) -> None:
    before = (table("transactions", database.DB_PATH), table("audit_logs", database.DB_PATH), disk_state(isolated_storage))
    assert run_apply(tmp_path) == 0
    backup = only_backup(tmp_path)

    # ทำตามขั้นตอนกู้คืนที่สคริปต์พิมพ์ให้
    database.DB_PATH.write_bytes((backup / DATABASE_FILE_NAME).read_bytes())
    with tarfile.open(backup / UPLOADS_ARCHIVE_NAME) as archive:
        archive.extractall(isolated_storage.parent, filter="data")

    assert before == (table("transactions", database.DB_PATH), table("audit_logs", database.DB_PATH), disk_state(isolated_storage))


def test_file_shared_with_active_row_is_kept(rows: tuple[dict, dict], isolated_storage: Path, tmp_path: Path) -> None:
    active, hidden = rows
    with _get_connection() as conn:
        conn.execute("UPDATE transactions SET file_path = ? WHERE id = ?", (active["file_path"], hidden["id"]))
    summary = purge.read_summary(database.DB_PATH)
    assert summary.files_on_disk == 0 and len(summary.plan.kept_files) == 1

    assert run_apply(tmp_path) == 0

    assert "PR_Active.pdf" in [Path(name).name for name, _hash in disk_state(isolated_storage)]


def test_logs_of_rows_already_gone_are_redacted(isolated_storage: Path, tmp_path: Path) -> None:
    """แถวที่ลบถาวรด้วยรุ่นก่อนหน้า: ไม่มีแถวในตารางแล้ว แต่ log ยังเก็บค่าเดิม"""
    with _get_connection() as conn:
        conn.execute("INSERT INTO audit_logs (action_type, record_id, details) VALUES ('INSERT', 999, '{\"vendor\": \"Old Co\"}')")
        conn.execute("INSERT INTO audit_logs (action_type, record_id, details) VALUES ('DELETE', 999, '{\"deleted\": true}')")

    assert run_apply(tmp_path) == 0

    assert [details for _action, details, _stamp in audit_rows(999)] == [AUDIT_REDACTED_DETAILS, '{"deleted": true}']


def test_backup_failure_changes_nothing(
    rows: tuple[dict, dict], isolated_storage: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = (table("transactions", database.DB_PATH), table("audit_logs", database.DB_PATH), disk_state(isolated_storage))

    def fail(*_args: object) -> Path:
        raise OSError("disk full")

    monkeypatch.setattr(purge, "create_backup", fail)

    assert run_apply(tmp_path) == 1

    assert before == (table("transactions", database.DB_PATH), table("audit_logs", database.DB_PATH), disk_state(isolated_storage))


def test_failure_during_database_step_rolls_back_and_keeps_files(
    rows: tuple[dict, dict], isolated_storage: Path, tmp_path: Path
) -> None:
    before = (table("transactions", database.DB_PATH), table("audit_logs", database.DB_PATH), disk_state(isolated_storage))
    with closing(sqlite3.connect(database.DB_PATH)) as conn:
        conn.execute("CREATE TRIGGER block_audit BEFORE UPDATE ON audit_logs BEGIN SELECT RAISE(ABORT, 'blocked'); END")
        conn.commit()

    assert run_apply(tmp_path) == 1

    with closing(sqlite3.connect(database.DB_PATH)) as conn:
        conn.execute("DROP TRIGGER block_audit")
        conn.commit()
    assert before == (table("transactions", database.DB_PATH), table("audit_logs", database.DB_PATH), disk_state(isolated_storage))


def test_data_changed_after_summary_stops_before_deleting(rows: tuple[dict, dict], tmp_path: Path) -> None:
    active, hidden = rows
    summary = purge.read_summary(database.DB_PATH)
    hide(active["id"])  # มีแถวถูกซ่อนเพิ่มหลังผู้ใช้ดูสรุปแล้ว

    with pytest.raises(purge.PurgeError):
        purge.apply_purge(database.DB_PATH, summary, tmp_path / "bk")

    assert {row[0] for row in table("transactions", database.DB_PATH)} == {active["id"], hidden["id"]}


@pytest.mark.parametrize("answer", ["", "no", "purge"])
def test_wrong_confirmation_changes_nothing(rows: tuple[dict, dict], tmp_path: Path, answer: str) -> None:
    before = table("transactions", database.DB_PATH)

    assert purge.main(["--apply", "--dest", str(tmp_path / "bk")], ask=lambda _prompt: answer) == 1

    assert table("transactions", database.DB_PATH) == before and not (tmp_path / "bk").exists()


def test_closed_input_counts_as_no_confirmation(rows: tuple[dict, dict], tmp_path: Path) -> None:
    def closed(_prompt: str) -> str:
        raise EOFError

    assert purge.main(["--apply", "--dest", str(tmp_path / "bk")], ask=closed) == 1
    assert not (tmp_path / "bk").exists()


def test_correct_confirmation_runs(rows: tuple[dict, dict], tmp_path: Path) -> None:
    active, _hidden = rows
    assert purge.main(["--apply", "--dest", str(tmp_path / "bk")], ask=lambda _prompt: purge.CONFIRM_WORD) == 0
    assert [row[0] for row in table("transactions", database.DB_PATH)] == [active["id"]]


def test_second_run_does_nothing(rows: tuple[dict, dict], tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert run_apply(tmp_path) == 0
    backup = only_backup(tmp_path)
    logs = table("audit_logs", database.DB_PATH)

    assert run_apply(tmp_path) == 0

    assert only_backup(tmp_path) == backup and table("audit_logs", database.DB_PATH) == logs
    assert "ไม่มีข้อมูลต้องล้าง" in capsys.readouterr().out


def test_compact_failure_still_reports_backup_location(
    rows: tuple[dict, dict], tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def locked(_db_path: Path) -> None:
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(purge, "_compact_database", locked)

    assert run_apply(tmp_path) == 1

    captured = capsys.readouterr()
    assert str(only_backup(tmp_path)) in captured.out and "--apply ซ้ำ" in captured.err
    monkeypatch.undo()


def test_missing_database_fails_without_creating_it(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    missing = tmp_path / "missing.db"
    monkeypatch.setattr(database, "DB_PATH", missing)

    assert purge.main([]) == 1

    assert not missing.exists()


def test_old_schema_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    old_db = tmp_path / "old.db"
    with closing(sqlite3.connect(old_db)) as conn:
        conn.execute("CREATE TABLE transactions (id INTEGER PRIMARY KEY)")
        conn.commit()
    monkeypatch.setattr(database, "DB_PATH", old_db)

    assert purge.main([]) == 1
