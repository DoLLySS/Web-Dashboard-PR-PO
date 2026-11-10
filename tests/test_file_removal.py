"""ทดสอบตรรกะลบไฟล์ที่ใช้ร่วมกับเครื่องมือรันเดี่ยว (utils/file_removal.py) โดยตรง"""

from pathlib import Path

import pytest

from utils.file_removal import (
    count_existing_files,
    execute_removal_plan,
    parse_stored_path,
    parse_stored_paths,
    plan_file_removal,
    prune_empty_parents,
    safe_upload_path,
)

ROW_A = "static/local_uploads/2026/Mar/19/งานA/PR_A.pdf\nstatic/local_uploads/2026/Mar/19/งานA/INV_A.pdf"
ROW_B = "static/local_uploads/2026/Mar/19/งานB/PR_B.pdf"


@pytest.mark.parametrize(
    ("stored", "expected"),
    [
        ("static/local_uploads/2026/Mar/19/x/a.pdf", ["2026", "Mar", "19", "x", "a.pdf"]),
        ("static\\local_uploads\\2026\\a.pdf", ["2026", "a.pdf"]),
        ("a.pdf", ["a.pdf"]),  # โครงเก่า ไม่มีโฟลเดอร์ย่อย
        ("static/local_uploads/../../secret.txt", None),
        ("static/local_uploads/./././x/a.pdf", None),
        ("static/local_uploads/2026/./a.pdf", None),
        ("static/local_uploads/2026//a.pdf", None),
        ("static/local_uploads/", None),
        ("", None),
    ],
)
def test_parse_stored_path(stored: str, expected: object) -> None:
    assert parse_stored_path(stored, "local_uploads") == expected


def test_parse_stored_paths_skips_blank_and_unsafe_entries() -> None:
    value = "static/local_uploads/a/b.pdf\n\n  \nstatic/local_uploads/../x.pdf"
    assert parse_stored_paths(value, "local_uploads") == [("a", "b.pdf")]
    assert parse_stored_paths(None, "local_uploads") == []


def test_plan_removes_whole_folder_only_when_no_other_row_uses_it() -> None:
    plan = plan_file_removal([ROW_A], [ROW_B], "local_uploads")
    assert plan.whole_folders == [("2026", "Mar", "19", "งานA")] and not plan.kept_files
    assert len(plan.own_files) == 2

    shared = plan_file_removal([ROW_A], [ROW_A.split("\n")[0]], "local_uploads")  # แถวอื่นยังอ้าง PR_A.pdf
    assert shared.whole_folders == [] and shared.kept_files == ["2026/Mar/19/งานA/PR_A.pdf"]
    assert [parts[-1] for parts in shared.files_by_folder[("2026", "Mar", "19", "งานA")]] == ["INV_A.pdf"]


def test_flat_legacy_files_are_removed_one_by_one_never_by_folder() -> None:
    plan = plan_file_removal(["static/local_uploads/old.pdf"], [], "local_uploads")
    assert plan.whole_folders == [] and plan.files_by_folder == {(): [("old.pdf",)]}


def test_safe_upload_path_refuses_escapes(tmp_path: Path) -> None:
    upload = tmp_path / "local_uploads"
    upload.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (upload / "link").symlink_to(outside)

    assert safe_upload_path(upload, ["a", "b.pdf"]) == upload / "a" / "b.pdf"
    for bad in ([], ["a", ".."], ["link"], ["link", "x"]):
        with pytest.raises(OSError):
            safe_upload_path(upload, bad)


def test_execute_plan_removes_folders_and_prunes_empty_parents_but_never_the_root(tmp_path: Path) -> None:
    upload = tmp_path / "local_uploads"
    folder = upload / "2026" / "Mar" / "19" / "งานA"
    folder.mkdir(parents=True)
    (folder / "PR_A.pdf").write_bytes(b"1")
    (folder / "orphan.txt").write_bytes(b"2")
    plan = plan_file_removal([ROW_A], [], "local_uploads")
    assert count_existing_files(plan, upload) == (1, 2)  # แถวอ้าง 2 ไฟล์ มีจริง 1 และจะลบจริง 2 (รวมไฟล์กำพร้า)

    result = execute_removal_plan(plan, upload)

    assert result.removed_folders == ["2026/Mar/19/งานA"] and not result.failed
    assert upload.is_dir() and list(upload.iterdir()) == []


def test_execute_plan_reports_failures_and_continues(tmp_path: Path) -> None:
    upload = tmp_path / "local_uploads"
    (upload / "2026" / "Mar" / "19" / "งานB").mkdir(parents=True)
    (upload / "2026" / "Mar" / "19" / "งานB" / "PR_B.pdf").write_bytes(b"1")
    outside = tmp_path / "outside"
    outside.mkdir()
    (upload / "2026" / "Mar" / "19" / "งานA").symlink_to(outside)  # โฟลเดอร์ A เป็น symlink ออกนอก
    plan = plan_file_removal([ROW_A, ROW_B], [], "local_uploads")

    result = execute_removal_plan(plan, upload)

    assert result.failed == ["2026/Mar/19/งานA"] and result.removed_folders == ["2026/Mar/19/งานB"]
    assert outside.is_dir()


def test_prune_stops_at_non_empty_parent(tmp_path: Path) -> None:
    root = tmp_path / "root"
    (root / "a" / "b").mkdir(parents=True)
    (root / "a" / "keep.txt").write_bytes(b"x")
    prune_empty_parents(root / "a" / "b" / "file", root)
    assert (root / "a").is_dir() and not (root / "a" / "b").exists()
