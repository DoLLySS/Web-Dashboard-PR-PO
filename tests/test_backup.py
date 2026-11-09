"""ทดสอบสคริปต์สำรองข้อมูล: ต้องกู้คืนได้จริง และลบเฉพาะชุดเก่าที่สคริปต์สร้าง"""

import sqlite3
import tarfile
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from scripts.backup import DATABASE_FILE_NAME, UPLOADS_ARCHIVE_NAME, BackupError, create_backup, main

NOW = datetime(2026, 11, 9, 1, 30, 0)
DOCUMENT_BYTES = "เอกสาร".encode()


@pytest.fixture
def source(tmp_path: Path) -> tuple[Path, Path]:
    """ฐานข้อมูลและโฟลเดอร์เอกสารตัวอย่าง ในโครงเดียวกับของจริง (static/local_uploads)"""
    db_path = tmp_path / "source.db"
    with closing(sqlite3.connect(db_path)) as conn:
        conn.execute("CREATE TABLE transactions (id INTEGER PRIMARY KEY, vendor TEXT)")
        conn.execute("INSERT INTO transactions (vendor) VALUES ('บริษัท ก')")
        conn.commit()
    upload_directory = tmp_path / "static" / "local_uploads"
    row_folder = upload_directory / "2026" / "Mar" / "19" / "งาน"
    row_folder.mkdir(parents=True)
    (row_folder / "ใบกำกับ.pdf").write_bytes(DOCUMENT_BYTES)
    return db_path, upload_directory


def vendors(db_path: Path) -> list[str]:
    with closing(sqlite3.connect(db_path)) as conn:
        return [row[0] for row in conn.execute("SELECT vendor FROM transactions ORDER BY id")]


def test_backup_can_be_restored(source: tuple[Path, Path], tmp_path: Path) -> None:
    db_path, upload_directory = source

    folder = create_backup(db_path, upload_directory, tmp_path / "backups", now=NOW)

    assert folder.name == "backup_20261109_013000"
    assert vendors(folder / DATABASE_FILE_NAME) == ["บริษัท ก"]
    restored = tmp_path / "restored"
    with tarfile.open(folder / UPLOADS_ARCHIVE_NAME) as archive:
        archive.extractall(restored, filter="data")
    assert (restored / "local_uploads" / "2026" / "Mar" / "19" / "งาน" / "ใบกำกับ.pdf").read_bytes() == DOCUMENT_BYTES
    assert folder.stat().st_mode & 0o077 == 0  # มีเอกสารของบริษัท ผู้อื่นในเครื่องต้องเข้าไม่ได้


def test_backup_includes_rows_still_in_wal_and_leaves_source_alone(source: tuple[Path, Path], tmp_path: Path) -> None:
    db_path, upload_directory = source
    with closing(sqlite3.connect(db_path)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO transactions (vendor) VALUES ('บริษัท ข')")
        writer.commit()

        folder = create_backup(db_path, upload_directory, tmp_path / "backups", now=NOW)

        assert vendors(folder / DATABASE_FILE_NAME) == ["บริษัท ก", "บริษัท ข"]
    assert vendors(db_path) == ["บริษัท ก", "บริษัท ข"]
    assert (upload_directory / "2026" / "Mar" / "19" / "งาน" / "ใบกำกับ.pdf").is_file()


def test_backup_without_uploads_folder_still_saves_database(source: tuple[Path, Path], tmp_path: Path) -> None:
    db_path, _uploads = source

    folder = create_backup(db_path, tmp_path / "static" / "not_created", tmp_path / "backups", now=NOW)

    assert vendors(folder / DATABASE_FILE_NAME) == ["บริษัท ก"]
    with tarfile.open(folder / UPLOADS_ARCHIVE_NAME) as archive:
        assert archive.getnames() == []


def test_prune_removes_only_old_backups_made_by_this_script(source: tuple[Path, Path], tmp_path: Path) -> None:
    db_path, upload_directory = source
    destination = tmp_path / "backups"
    created = [create_backup(db_path, upload_directory, destination, keep=2, now=NOW + timedelta(days=day)) for day in range(3)]
    (destination / "backup_ของฉัน").mkdir()
    (destination / "notes.txt").write_text("keep")

    newest = create_backup(db_path, upload_directory, destination, keep=2, now=NOW + timedelta(days=3))

    assert sorted(path.name for path in destination.iterdir()) == sorted(
        [created[2].name, newest.name, "backup_ของฉัน", "notes.txt"]
    )


def test_failed_backup_leaves_nothing_and_keeps_old_backups(
    source: tuple[Path, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path, upload_directory = source
    destination = tmp_path / "backups"
    old = create_backup(db_path, upload_directory, destination, keep=1, now=NOW)

    def fail(_directory: Path, _target: Path) -> None:
        raise OSError("disk full")

    monkeypatch.setattr("scripts.backup._archive_uploads", fail)

    with pytest.raises(OSError):
        create_backup(db_path, upload_directory, destination, keep=1, now=NOW + timedelta(days=1))

    assert [path.name for path in destination.iterdir()] == [old.name]


def test_corrupt_database_is_not_saved_as_a_backup(source: tuple[Path, Path], tmp_path: Path) -> None:
    db_path, upload_directory = source
    db_path.write_bytes(b"not a database" * 100)
    destination = tmp_path / "backups"

    with pytest.raises(sqlite3.Error):
        create_backup(db_path, upload_directory, destination, now=NOW)

    assert list(destination.iterdir()) == []


@pytest.mark.parametrize("keep", [0, -1])
def test_invalid_keep_is_refused(source: tuple[Path, Path], tmp_path: Path, keep: int) -> None:
    db_path, upload_directory = source
    with pytest.raises(BackupError):
        create_backup(db_path, upload_directory, tmp_path / "backups", keep=keep, now=NOW)


def test_destination_served_by_web_is_refused(source: tuple[Path, Path]) -> None:
    db_path, upload_directory = source
    with pytest.raises(BackupError):
        create_backup(db_path, upload_directory, upload_directory.parent / "backups", now=NOW)
    assert not (upload_directory.parent / "backups").exists()


def test_missing_database_returns_failure_without_touching_backups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr("scripts.backup.DB_PATH", tmp_path / "missing.db")
    monkeypatch.setattr("scripts.backup.UPLOAD_DIRECTORY", tmp_path / "static" / "local_uploads")
    destination = tmp_path / "backups"

    assert main(["--dest", str(destination)]) == 1

    assert "ไม่พบไฟล์ฐานข้อมูล" in capsys.readouterr().err
    assert not destination.exists()
