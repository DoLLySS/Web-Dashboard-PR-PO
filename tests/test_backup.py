"""ทดสอบสคริปต์สำรองข้อมูล: ต้องกู้คืนได้จริง และลบเฉพาะชุดเก่าที่สคริปต์สร้าง"""

import ast
import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
from contextlib import closing
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from scripts.backup import (
    CODE_ARCHIVE_NAME,
    DATABASE_FILE_NAME,
    MANIFEST_FILE_NAME,
    PROJECT_ROOT,
    UPLOADS_ARCHIVE_NAME,
    BackupError,
    create_backup,
    default_db_path,
    default_upload_directory,
    main,
)

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
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    destination = tmp_path / "backups"

    assert main(["--db", str(tmp_path / "missing.db"), "--uploads", str(tmp_path / "static" / "local_uploads"), "--dest", str(destination)]) == 1

    assert "ไม่พบไฟล์ฐานข้อมูล" in capsys.readouterr().err
    assert not destination.exists()


def test_default_paths_come_from_environment_not_dotenv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("DB_FILE_PATH", str(tmp_path / "x.db"))
    assert default_db_path() == tmp_path / "x.db"
    monkeypatch.delenv("DB_FILE_PATH")
    assert default_db_path() == PROJECT_ROOT / "data" / "masterlist.db"
    assert default_upload_directory() == PROJECT_ROOT / "static" / "local_uploads"


@pytest.fixture
def project(tmp_path: Path, source: tuple[Path, Path]) -> Path:
    """โปรเจกต์จำลอง: โค้ด + .env + venv + ฐานข้อมูล + ไฟล์เอกสาร + logs + backups"""
    root = tmp_path / "static"  # source ใช้ tmp_path/static/local_uploads อยู่แล้ว
    project_dir = tmp_path / "proj"
    (project_dir / "utils").mkdir(parents=True)
    (project_dir / "app.py").write_text("print('app')\n")
    (project_dir / "utils" / "a.py").write_text("A = 1\n")
    (project_dir / "utils" / "__pycache__").mkdir()
    (project_dir / "utils" / "__pycache__" / "a.pyc").write_bytes(b"x")
    (project_dir / ".env").write_text("SECRET=abc\n")
    (project_dir / "venv" / "bin").mkdir(parents=True)
    (project_dir / "venv" / "bin" / "python").write_text("venv")
    (project_dir / "data").mkdir()
    (project_dir / "data" / "masterlist.db").write_bytes(b"db")
    (project_dir / "data" / "masterlist.db-wal").write_bytes(b"wal")
    (project_dir / "static" / "local_uploads").mkdir(parents=True)
    (project_dir / "static" / "local_uploads" / "doc.pdf").write_bytes(b"doc")
    (project_dir / "logs").mkdir()
    (project_dir / "logs" / "app.log").write_text("log")
    (project_dir / "backups").mkdir()
    (project_dir / "backups" / "old.txt").write_text("old")
    assert root.is_dir()
    return project_dir


def test_code_backup_has_code_and_env_but_no_venv_data_or_uploads(source: tuple[Path, Path], project: Path, tmp_path: Path) -> None:
    db_path, upload_directory = source

    folder = create_backup(db_path, upload_directory, tmp_path / "out", now=NOW, code_directory=project)

    with tarfile.open(folder / CODE_ARCHIVE_NAME) as archive:
        names = set(archive.getnames())
    assert {"proj/app.py", "proj/utils/a.py", "proj/.env"} <= names
    forbidden = ("venv", "__pycache__", "masterlist.db", "local_uploads", "app.log", "old.txt")
    assert not [name for name in names if any(word in name for word in forbidden)]


def test_backup_is_private_and_manifest_verifies(source: tuple[Path, Path], project: Path, tmp_path: Path) -> None:
    db_path, upload_directory = source

    folder = create_backup(db_path, upload_directory, tmp_path / "out", now=NOW, code_directory=project)

    assert folder.stat().st_mode & 0o077 == 0
    assert all(path.stat().st_mode & 0o077 == 0 for path in folder.iterdir())
    lines = (folder / MANIFEST_FILE_NAME).read_text().splitlines()
    assert sorted(line.split("  ")[1] for line in lines) == sorted(
        [CODE_ARCHIVE_NAME, DATABASE_FILE_NAME, UPLOADS_ARCHIVE_NAME]
    )
    for line in lines:
        digest, name = line.split("  ")
        assert hashlib.sha256((folder / name).read_bytes()).hexdigest() == digest


def test_code_backup_inside_the_project_does_not_include_itself(source: tuple[Path, Path], project: Path) -> None:
    db_path, upload_directory = source
    destination = project / "my_backups"

    folder = create_backup(db_path, upload_directory, destination, now=NOW, code_directory=project)

    with tarfile.open(folder / CODE_ARCHIVE_NAME) as archive:
        assert not [name for name in archive.getnames() if "my_backups" in name]


def test_missing_code_directory_is_refused(source: tuple[Path, Path], tmp_path: Path) -> None:
    db_path, upload_directory = source
    with pytest.raises(BackupError):
        create_backup(db_path, upload_directory, tmp_path / "out", now=NOW, code_directory=tmp_path / "nope")
    assert not (tmp_path / "out").exists()


def test_main_warns_when_code_backup_contains_env(source: tuple[Path, Path], project: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    db_path, upload_directory = source
    code = main(["--db", str(db_path), "--uploads", str(upload_directory), "--code", str(project), "--dest", str(tmp_path / "out")])
    assert code == 0 and ".env" in capsys.readouterr().out


def test_scripts_run_standalone_without_the_application(tmp_path: Path, source: tuple[Path, Path]) -> None:
    """คัดลอก scripts/ + utils/file_removal.py ไปโฟลเดอร์อื่น แล้วรันด้วย Python เปล่า (ไม่มี streamlit/config/data) ได้"""
    bundle = tmp_path / "bundle"
    (bundle / "scripts").mkdir(parents=True)
    (bundle / "utils").mkdir()
    for name in ("__init__.py", "backup.py", "purge_deleted.py"):
        shutil.copy(PROJECT_ROOT / "scripts" / name, bundle / "scripts" / name)
    for name in ("__init__.py", "file_removal.py"):
        shutil.copy(PROJECT_ROOT / "utils" / name, bundle / "utils" / name)
    db_path, upload_directory = source
    with closing(sqlite3.connect(db_path)) as conn:  # ทำให้เป็นโครงสร้างที่ purge ยอมรับ
        conn.executescript(
            "ALTER TABLE transactions ADD COLUMN is_deleted INTEGER DEFAULT 0;"
            "ALTER TABLE transactions ADD COLUMN file_path TEXT;"
            "ALTER TABLE transactions ADD COLUMN sharepoint_url TEXT;"
            "CREATE TABLE audit_logs (log_id INTEGER PRIMARY KEY AUTOINCREMENT, action_type TEXT, record_id INTEGER, details TEXT, timestamp TEXT);"
        )
        conn.commit()
    environment = {"PATH": os.environ["PATH"], "PYTHONDONTWRITEBYTECODE": "1"}

    for tool, extra in (("backup.py", []), ("purge_deleted.py", [])):
        result = subprocess.run(
            [sys.executable, "-I", "-S", str(bundle / "scripts" / tool), "--db", str(db_path), "--uploads", str(upload_directory),
             "--dest", str(tmp_path / "out"), *extra],
            capture_output=True, text=True, env=environment, cwd=tmp_path, check=False,
        )
        assert result.returncode == 0, result.stderr
    assert [path.name for path in (tmp_path / "out").iterdir()] and "ModuleNotFoundError" not in result.stderr


@pytest.mark.parametrize("module", ["scripts/backup.py", "scripts/purge_deleted.py", "utils/file_removal.py"])
def test_tool_modules_import_only_the_standard_library(module: str) -> None:
    allowed_local = {"scripts", "utils"}
    tree = ast.parse((PROJECT_ROOT / module).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= set(sys.stdlib_module_names) | allowed_local, imported - set(sys.stdlib_module_names)


def test_main_prints_the_database_it_uses(source: tuple[Path, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """ผู้ใช้ต้องเห็นว่าสำรองไฟล์ฐานข้อมูลไหน จะได้จับได้ทันทีถ้าชี้ผิดไฟล์"""
    db_path, upload_directory = source

    assert main(["--db", str(db_path), "--uploads", str(upload_directory), "--dest", str(tmp_path / "out")]) == 0

    assert f"ฐานข้อมูล: {db_path}" in capsys.readouterr().out


def test_deploy_cron_example_names_the_database_explicitly() -> None:
    """สคริปต์ไม่อ่าน .env จึงต้องระบุ --db ในตัวอย่าง cron ไม่เช่นนั้นจะสำรองไฟล์ data/masterlist.db ที่อาจไม่ใช่ไฟล์จริง"""
    lines = [line for line in (PROJECT_ROOT / "DEPLOY.md").read_text(encoding="utf-8").splitlines() if "scripts/backup.py" in line and "cd " in line]

    assert lines, "ไม่พบตัวอย่าง cron ใน DEPLOY.md"
    assert all("--db" in line for line in lines)
