"""ตั้งค่าร่วมของชุดทดสอบ: แยกการทดสอบออกจากข้อมูลจริงและปลายทางออนไลน์ทั้งหมด

ต้องตั้งตัวแปรก่อน import โค้ดของโปรเจค เพราะหลายค่าถูกอ่านตอน import
load_dotenv ไม่เขียนทับตัวแปรที่มีอยู่แล้ว ค่าว่างด้านล่างจึงมีผลเหนือไฟล์ .env
"""

import os
import sys
import tempfile
from pathlib import Path

import pytest

_ISOLATED_DIRECTORY: Path = Path(tempfile.mkdtemp(prefix="masterlist_tests_"))
_ISOLATED_SETTINGS: dict[str, str] = {
    "DB_FILE_PATH": str(_ISOLATED_DIRECTORY / "default.db"),
    "DB_JOURNAL_MODE": "DELETE",
    "STORAGE_BACKEND": "gdrive",
    "GDRIVE_SERVICE_ACCOUNT_FILE": "",
    "GDRIVE_ROOT_FOLDER_ID": "",
    "SHAREPOINT_URL": "",
    "SHAREPOINT_CLIENT_ID": "",
    "SHAREPOINT_CLIENT_SECRET": "",
    "SHAREPOINT_USERNAME": "",
    "SHAREPOINT_PASSWORD": "",
    "SHAREPOINT_FOLDER_PATH": "",
    "MASTERLIST_API_URL": "",
    "MASTERLIST_API_KEY": "",
    "MASTERLIST_TIMEOUT_SECONDS": "",
    "POWER_AUTOMATE_UPLOAD_URL": "",
    "POWER_AUTOMATE_API_KEY": "",
    "POWER_AUTOMATE_TIMEOUT_SECONDS": "",
    "POWER_AUTOMATE_MAX_FILE_MB": "",
    "LOCAL_DESKTOP_EXPORT": "0",
}
os.environ.update(_ISOLATED_SETTINGS)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture
def isolated_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """ชี้ฐานข้อมูลและโฟลเดอร์เก็บไฟล์ไปที่โฟลเดอร์ชั่วคราวของแต่ละ test

    Args:
        tmp_path: โฟลเดอร์ชั่วคราวจาก pytest
        monkeypatch: ตัวช่วยเปลี่ยนค่าชั่วคราวจาก pytest

    Returns:
        โฟลเดอร์เก็บไฟล์ชั่วคราว
    """
    import data.database as database
    import utils.local_storage as local_storage

    upload_directory = tmp_path / "static" / "local_uploads"
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(local_storage, "UPLOAD_DIRECTORY", upload_directory)
    monkeypatch.setattr(local_storage, "LEGACY_UPLOAD_DIRECTORY", tmp_path / "data" / "local_uploads")
    assert database.init_db()
    return upload_directory
