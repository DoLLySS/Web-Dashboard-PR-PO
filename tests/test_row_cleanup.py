"""ทดสอบการลบแถวถาวรพร้อมไฟล์ (utils/row_cleanup.py)"""

from pathlib import Path

import pytest

import utils.local_storage as local_storage
import utils.row_cleanup as row_cleanup
from data.database import (
    AUDIT_REDACTED_DETAILS,
    _bump_data_version,
    _get_connection,
    delete_transaction,
    delete_transactions,
    get_transaction,
    get_transactions,
    update_transaction,
)
from pages_ui.overview import build_delete_confirm_lines
from pr_fixtures import make_pr_pdf
from utils.local_storage import FILE_PATH_SEPARATOR
from utils.row_cleanup import delete_rows_and_files
from utils.upload_processor import KIND_ATTACHED, process_upload

PR_ITEMS = [("Monitor Dell U2724DE", "14,500.00")]
PR_NAME = "20260319_PR_Addin_Monitor.pdf"


def upload(files: list[tuple[str, bytes]]):
    return process_upload(files, "Hardware", "รอใบกำกับภาษี", lambda name: name, lambda name: None)


def only_row() -> dict:
    rows = get_transactions()
    assert len(rows) == 1
    return rows[0]


def row_folder(upload_directory: Path, row: dict) -> Path:
    parts = local_storage.get_folder_parts_from_file_paths(row["file_path"])
    assert parts
    return upload_directory.joinpath(*parts)


def count_rows_in_table() -> int:
    with _get_connection() as conn:
        return conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]


def audit_actions(row_id: int) -> list[str]:
    with _get_connection() as conn:
        rows = conn.execute("SELECT action_type FROM audit_logs WHERE record_id = ? ORDER BY log_id", (row_id,)).fetchall()
    return [row[0] for row in rows]


def test_delete_removes_row_folder_and_empty_date_folders(isolated_storage: Path) -> None:
    upload([(PR_NAME, make_pr_pdf(PR_ITEMS))])
    row = only_row()
    folder = row_folder(isolated_storage, row)
    (folder / "ไฟล์กำพร้า.pdf").write_bytes(b"orphan")

    report = delete_rows_and_files([row["id"]])

    assert report.deleted_count == 1 and not report.failed
    assert count_rows_in_table() == 0  # ลบจริง ไม่ใช่แค่ซ่อน
    assert isolated_storage.is_dir() and list(isolated_storage.iterdir()) == []  # ปี/เดือน/วัน ที่ว่างหายด้วย
    assert audit_actions(row["id"])[-1] == "DELETE"


def test_reupload_after_delete_has_only_new_files(isolated_storage: Path) -> None:
    pr_file = (PR_NAME, make_pr_pdf(PR_ITEMS))
    upload([pr_file])
    old_id = only_row()["id"]
    assert upload([("ใบกำกับภาษี Monitor Dell U2724DE.pdf", b"invoice")]).items[0].kind == KIND_ATTACHED
    delete_rows_and_files([old_id])

    upload([pr_file])

    row = only_row()
    assert row["id"] != old_id and row["invoice_status"] == "รอใบกำกับภาษี"
    assert [path.name for path in row_folder(isolated_storage, row).iterdir()] == [PR_NAME]


def share_folder_with_second_row(isolated_storage: Path, *, hide_second: bool) -> tuple[dict, dict, Path]:
    """แถวที่ 2 อ้างไฟล์ของตัวเองในโฟลเดอร์เดียวกับแถวแรก"""
    upload([(PR_NAME, make_pr_pdf(PR_ITEMS))])
    first = only_row()
    upload([("PR_Other.pdf", make_pr_pdf([("Printer Beta Y200", "9,000.00")], vendor="Beta Co"))])
    second = next(row for row in get_transactions() if row["id"] != first["id"])
    folder = row_folder(isolated_storage, first)
    (folder / "other.pdf").write_bytes(b"other")
    stored = "/".join([*first["file_path"].split("/")[:-1], "other.pdf"])
    assert update_transaction(second["id"], file_path=stored)
    if hide_second:
        with _get_connection() as conn:
            conn.execute("UPDATE transactions SET is_deleted = 1 WHERE id = ?", (second["id"],))
        _bump_data_version()
    return first, second, folder


@pytest.mark.parametrize("hide_second", [False, True])
def test_shared_folder_keeps_other_rows_files(isolated_storage: Path, hide_second: bool) -> None:
    """แถวอื่นใช้โฟลเดอร์ร่วม (รวมแถวที่ถูกซ่อนจากรุ่นก่อน): ลบเฉพาะไฟล์ของแถวที่ลบ"""
    first, _second, folder = share_folder_with_second_row(isolated_storage, hide_second=hide_second)

    report = delete_rows_and_files([first["id"]])

    assert report.deleted_count == 1 and not report.failed and not report.removed_folders
    assert [path.name for path in folder.iterdir()] == ["other.pdf"]


def test_deleting_all_rows_of_shared_folder_removes_it(isolated_storage: Path) -> None:
    first, second, folder = share_folder_with_second_row(isolated_storage, hide_second=False)

    report = delete_rows_and_files([first["id"], second["id"]])

    assert report.deleted_count == 2 and not report.failed
    assert not folder.exists()


def test_file_used_by_other_row_is_kept(isolated_storage: Path) -> None:
    first, second, folder = share_folder_with_second_row(isolated_storage, hide_second=False)
    assert update_transaction(second["id"], file_path=first["file_path"])
    (folder / "other.pdf").unlink()

    report = delete_rows_and_files([first["id"]])

    assert get_transaction(first["id"]) is None
    assert [path.name for path in folder.iterdir()] == [PR_NAME]
    assert [path.rsplit("/", 1)[-1] for path in report.kept_files] == [PR_NAME]  # บอกผู้ใช้ว่าไฟล์นี้ยังไม่ถูกลบ


def test_hidden_row_is_not_deleted_and_keeps_files(isolated_storage: Path) -> None:
    upload([(PR_NAME, make_pr_pdf(PR_ITEMS))])
    row = only_row()
    with _get_connection() as conn:
        conn.execute("UPDATE transactions SET is_deleted = 1 WHERE id = ?", (row["id"],))
    _bump_data_version()

    report = delete_rows_and_files([row["id"]])

    assert report.deleted_count == 0
    assert count_rows_in_table() == 1 and row_folder(isolated_storage, row).is_dir()


@pytest.mark.parametrize(
    "stored_path",
    ["static/local_uploads/../../secret.txt", "static/local_uploads/2026/../../../secret.txt"],
)
def test_path_outside_uploads_is_never_removed(isolated_storage: Path, tmp_path: Path, stored_path: str) -> None:
    secret = isolated_storage.parent.parent / "secret.txt"
    secret.write_text("keep")
    upload([(PR_NAME, make_pr_pdf(PR_ITEMS))])
    row = only_row()
    assert update_transaction(row["id"], file_path=stored_path)

    report = delete_rows_and_files([row["id"]])

    assert report.deleted_count == 1 and secret.read_text() == "keep"


def test_symlink_folder_is_refused(isolated_storage: Path, tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.pdf").write_bytes(b"keep")
    date_folder = isolated_storage / "2026" / "Mar" / "19"
    date_folder.mkdir(parents=True)
    (date_folder / "linked").symlink_to(outside)
    upload([(PR_NAME, make_pr_pdf(PR_ITEMS))])
    row = only_row()
    assert update_transaction(row["id"], file_path="static/local_uploads/2026/Mar/19/linked/keep.pdf")

    report = delete_rows_and_files([row["id"]])

    assert report.deleted_count == 1 and report.failed
    assert (outside / "keep.pdf").is_file()


def test_flat_legacy_file_removes_only_that_file(isolated_storage: Path) -> None:
    upload([(PR_NAME, make_pr_pdf(PR_ITEMS))])
    row = only_row()
    (isolated_storage / "old.pdf").write_bytes(b"old")
    (isolated_storage / "neighbor.pdf").write_bytes(b"neighbor")
    assert update_transaction(row["id"], file_path=f"static/local_uploads/old.pdf{FILE_PATH_SEPARATOR}")

    delete_rows_and_files([row["id"]])

    assert not (isolated_storage / "old.pdf").exists()
    assert (isolated_storage / "neighbor.pdf").is_file()


def test_file_error_is_reported_but_row_is_gone(isolated_storage: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    upload([(PR_NAME, make_pr_pdf(PR_ITEMS))])
    row = only_row()

    def fail(_parts: list[str]) -> None:
        raise PermissionError("locked")

    monkeypatch.setattr(row_cleanup, "remove_upload_folder", fail)

    report = delete_rows_and_files([row["id"]])

    assert report.deleted_count == 1 and len(report.failed) == 1
    assert count_rows_in_table() == 0


def test_no_files_removed_when_other_rows_cannot_be_read(isolated_storage: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    upload([(PR_NAME, make_pr_pdf(PR_ITEMS))])
    row = only_row()
    folder = row_folder(isolated_storage, row)
    monkeypatch.setattr(row_cleanup, "get_all_file_paths", lambda: None)

    report = delete_rows_and_files([row["id"]])

    assert report.failed and folder.is_dir()


def test_failed_row_delete_leaves_files(isolated_storage: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    upload([(PR_NAME, make_pr_pdf(PR_ITEMS))])
    row = only_row()
    monkeypatch.setattr(row_cleanup, "delete_transactions", lambda _ids: 0)

    report = delete_rows_and_files([row["id"]])

    assert report.deleted_count == 0 and row_folder(isolated_storage, row).is_dir()


def test_desktop_copy_is_removed_when_enabled(isolated_storage: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    desktop = tmp_path / "Desktop"
    monkeypatch.setattr(local_storage, "get_desktop_directory", lambda: desktop)
    monkeypatch.setattr(local_storage, "DESKTOP_EXPORT_ENABLED", True)
    upload([(PR_NAME, make_pr_pdf(PR_ITEMS))])
    row = only_row()
    parts = local_storage.get_folder_parts_from_file_paths(row["file_path"])
    copy = desktop.joinpath(*parts)
    copy.mkdir(parents=True, exist_ok=True)
    (copy / PR_NAME).write_bytes(b"copy")
    (desktop / "my_notes.txt").write_text("keep")

    report = delete_rows_and_files([row["id"]])

    assert not report.failed and not copy.exists()
    assert (desktop / "my_notes.txt").is_file() and [path.name for path in desktop.iterdir()] == ["my_notes.txt"]


def make_rows(count: int) -> list[dict]:
    return [{"id": n, "date": "2026-03-19", "description": f"งาน {n}", "vendor": "บริษัท ก"} for n in range(1, count + 1)]


def test_delete_confirm_lists_every_selected_row_up_to_the_limit() -> None:
    lines = build_delete_confirm_lines(make_rows(10))
    assert len(lines) == 10
    assert lines[0] == "2026-03-19 · งาน 1 · บริษัท ก · รหัสรายการ 1"


def test_delete_confirm_summarises_rows_beyond_the_limit() -> None:
    lines = build_delete_confirm_lines(make_rows(13))
    assert len(lines) == 11 and lines[-1] == "และอีก 3 รายการ"


def audit_details(row_id: int) -> list[str]:
    with _get_connection() as conn:
        rows = conn.execute("SELECT details FROM audit_logs WHERE record_id = ? ORDER BY log_id", (row_id,)).fetchall()
    return [row[0] for row in rows]


def test_delete_redacts_only_that_rows_audit_details(isolated_storage: Path) -> None:
    first, second, _folder = share_folder_with_second_row(isolated_storage, hide_second=False)
    second_details = audit_details(second["id"])
    assert any("Monitor Dell" in details for details in audit_details(first["id"]))

    delete_rows_and_files([first["id"]])

    details = audit_details(first["id"])
    assert details[-1] == '{"deleted": true}'
    assert set(details[:-1]) == {AUDIT_REDACTED_DETAILS}
    assert audit_details(second["id"]) == second_details


def test_failed_delete_keeps_audit_details(isolated_storage: Path) -> None:
    upload([(PR_NAME, make_pr_pdf(PR_ITEMS))])
    row = only_row()
    before = audit_details(row["id"])
    with _get_connection() as conn:
        conn.execute("CREATE TRIGGER block_log BEFORE INSERT ON audit_logs BEGIN SELECT RAISE(ABORT, 'blocked'); END")

    assert delete_transactions([row["id"]]) == 0

    assert audit_details(row["id"]) == before and count_rows_in_table() == 1


def test_single_delete_redacts_audit_details(isolated_storage: Path) -> None:
    upload([(PR_NAME, make_pr_pdf(PR_ITEMS))])
    row = only_row()

    assert delete_transaction(row["id"])

    assert audit_details(row["id"]) == [AUDIT_REDACTED_DETAILS, '{"deleted": true}']
