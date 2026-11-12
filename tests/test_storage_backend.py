"""ทดสอบการตั้งชื่อโฟลเดอร์และการเลือกปลายทางใน utils/storage_backend.py"""

from datetime import datetime

import pytest

from utils.storage_backend import (
    BACKEND_GDRIVE,
    BACKEND_POWER_AUTOMATE,
    MAX_FOLDER_NAME_LENGTH,
    PR_TOKEN_PATTERN,
    UNKNOWN_VENDOR_FOLDER,
    build_dated_folder_name,
    build_folder_name_from_files,
    build_storage_folder_parts,
    build_storage_path,
    get_active_backend,
    is_storage_configured,
    sanitize_folder_name,
    upload_files_to_storage,
)


@pytest.mark.parametrize(
    ("file_name", "is_pr"),
    [
        ("20260319_PR_Addin.pdf", True),
        ("pr-1001.xlsx", True),
        ("PR.pdf", True),
        ("PRINT_manual.pdf", False),
        ("SPRINT_PR2.pdf", False),
    ],
)
def test_pr_token_matches_only_standalone_word(file_name: str, is_pr: bool) -> None:
    """คำว่า PR ต้องเป็นคำเดี่ยว ไม่นับ PR ที่อยู่ในคำอื่น เช่น PRINT"""
    assert bool(PR_TOKEN_PATTERN.search(file_name)) is is_pr


def test_folder_name_removes_extension_pr_and_signed_suffix() -> None:
    """ตัวอย่างจาก docstring: ตัดนามสกุล, คำว่า PR และท้าย -signed_N"""
    assert build_folder_name_from_files(["20260319_PR_Addin_ซื้อ_NB-signed_5.pdf"]) == "20260319_Addin_ซื้อ_NB"


def test_folder_name_prefers_signed_file_over_other_pr_files() -> None:
    """ไฟล์ที่เซ็นแล้วมาก่อนไฟล์ PR อื่น ไม่ว่าจะอยู่ลำดับไหน"""
    assert build_folder_name_from_files(["PR_Draft.pdf", "quote.pdf", "PR_Final-signed.pdf"]) == "Final"


def test_folder_name_without_files_is_unknown() -> None:
    """ไม่มีไฟล์เลย ใช้ชื่อสำรอง"""
    assert build_folder_name_from_files([]) == UNKNOWN_VENDOR_FOLDER


def test_dated_folder_name_prefers_real_file_name_date_over_when() -> None:
    """วันที่จริงที่นำหน้าชื่อไฟล์ชนะ when; ไม่มีวันที่ใช้ when"""
    assert build_dated_folder_name(datetime(2026, 3, 19), ["20250101_PR_Addin.pdf"]) == "20250101_Addin"
    assert build_dated_folder_name(datetime(2026, 3, 19), ["PR_Addin.pdf"]) == "20260319_Addin"


@pytest.mark.parametrize(
    ("file_name", "expected"),
    [
        ("20261112_PR_บริษัทA_ปั๊มน้ำ.pdf", ["2026", "Nov", "12", "20261112_บริษัทA_ปั๊มน้ำ"]),
        ("PR_บริษัทA_ปั๊มน้ำ.pdf", ["2026", "Jan", "05", "20260105_บริษัทA_ปั๊มน้ำ"]),  # ไม่มีวันที่ -> when
        ("20261399_PR_x.pdf", ["2026", "Jan", "05", "20260105_20261399_PR_x"]),  # ไม่ใช่วันที่จริง
        ("20261112_บริษัทA_PR_ปั๊ม.pdf", ["2026", "Nov", "12", "20261112_บริษัทA_PR_ปั๊ม"]),  # PR กลางชื่อไม่ตัด
        ("PROJECT-A.pdf", ["2026", "Jan", "05", "20260105_PROJECT-A"]),
        ("20261112_PR.pdf", ["2026", "Nov", "12", "20261112_PR"]),
        ("PR.pdf", ["2026", "Jan", "05", "20260105_PR"]),
        ("20261028_134912_664797_PR_x.pdf", ["2026", "Jan", "05", "20260105_x"]),  # เวลาอัปโหลดไม่ใช่วันที่ PR
    ],
)
def test_build_storage_path_for_real_file_name_pattern(file_name: str, expected: list[str]) -> None:
    """รูปแบบจริง YYYYMMDD_PR_คู่ค้า_รายละเอียด: ดึงวันที่ ตัด PR เฉพาะต้นชื่อ ไม่ซ้ำวันที่"""
    assert build_storage_path(datetime(2026, 1, 5), [file_name]) == expected


def test_storage_folder_parts_use_english_month_and_padded_day() -> None:
    """ชื่อเดือนเป็นอังกฤษเสมอ ไม่ขึ้นกับ locale ของเครื่อง"""
    assert build_storage_folder_parts(datetime(2026, 3, 9), "A/B") == ["2026", "Mar", "09", "A_B"]


@pytest.mark.parametrize("unsafe_name", ["../../etc", "..", "a\\b", "x:y*z", "a\x00b"])
def test_sanitize_folder_name_removes_path_characters(unsafe_name: str) -> None:
    """ชื่อโฟลเดอร์ต้องไม่มีอักขระที่พาออกนอกโฟลเดอร์ปลายทางได้"""
    cleaned = sanitize_folder_name(unsafe_name)
    assert cleaned
    assert not set("/\\:*\x00") & set(cleaned)
    assert cleaned not in (".", "..")


@pytest.mark.parametrize(
    ("when", "file_name", "expected"),
    [
        (datetime(2026, 1, 1), "PR-ตัวอย่าง.pdf", ["2026", "Jan", "01", "20260101_ตัวอย่าง"]),
        (datetime(2026, 1, 1), "PR_12345.pdf", ["2026", "Jan", "01", "20260101_12345"]),
        (datetime(2026, 1, 1), "PROJECT-A.pdf", ["2026", "Jan", "01", "20260101_PROJECT-A"]),
        (datetime(2026, 1, 1), "ใบขอซื้อ_อุปกรณ์.pdf", ["2026", "Jan", "01", "20260101_ใบขอซื้อ_อุปกรณ์"]),
        (datetime(2026, 12, 31), "PR_12345.pdf", ["2026", "Dec", "31", "20261231_12345"]),
        (datetime(2026, 2, 1), "PR_A.pdf", ["2026", "Feb", "01", "20260201_A"]),
        (datetime(2026, 1, 1), "PR.pdf", ["2026", "Jan", "01", "20260101_PR"]),
        (datetime(2026, 1, 1), "PRINT_x.pdf", ["2026", "Jan", "01", "20260101_PRINT_x"]),
    ],
)
def test_build_storage_path_covers_requested_cases(when: datetime, file_name: str, expected: list[str]) -> None:
    """จุดคำนวณ path เดียว: ปี/เดือนย่ออังกฤษ/วัน/YYYYMMDD_ชื่อที่ตัด PR คำเดี่ยว"""
    assert build_storage_path(when, [file_name]) == expected


def test_build_storage_path_falls_back_to_pr_number_without_pr_file() -> None:
    """ไม่มีไฟล์ PR ใช้เลข PR ของแถว ไม่มีเลขใช้แค่วันที่"""
    when = datetime(2026, 1, 1)
    assert build_storage_path(when, ["quote.pdf"], "PR-77") == ["2026", "Jan", "01", "20260101_PR-77"]
    assert build_storage_path(when, ["quote.pdf"], "") == ["2026", "Jan", "01", "20260101"]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("CON", "CON_"),
        ("nul", "nul_"),
        ("COM1", "COM1_"),
        (".lock", "lock"),  # จุดนำหน้าถูกตัด จึงไม่ใช่ชื่อสงวนอีก
        ("desktop.ini", "desktop.ini_"),
        ("~$draft", "_$draft"),
        ("a_vti_b", "a_b"),
        ("a~{b}", "a__b_"),
        ("x#y%z", "x_y_z"),
    ],
)
def test_sanitize_folder_name_handles_sharepoint_reserved_names(name: str, expected: str) -> None:
    """ชื่อสงวนและอักขระต้องห้ามของ SharePoint (ชุดเข้ม)"""
    assert sanitize_folder_name(name) == expected


def test_build_storage_path_is_what_both_backends_receive(monkeypatch: pytest.MonkeyPatch) -> None:
    """โหมดส่ง Power Automate รับ folder_parts เดียวกับที่คำนวณจากฟังก์ชันเดียว (เก็บในเครื่องใช้ list เดียวกัน)"""
    import utils.storage_backend as backend

    received: list[list[str]] = []

    class _Uploaded:
        file_url = "u"
        folder_url = "f"

    monkeypatch.setenv("STORAGE_BACKEND", "powerautomate")
    monkeypatch.setattr(backend, "upload_file_to_flow", lambda name, data, parts: received.append(parts) or _Uploaded())
    parts = build_storage_path(datetime(2026, 12, 31), ["PR_12345.pdf"])
    backend.upload_files_and_folder_url([("PR_12345.pdf", b"x")], parts)
    assert received == [["2026", "Dec", "31", "20261231_12345"]]


def test_sanitize_folder_name_handles_empty_and_long_names() -> None:
    """ชื่อว่างใช้ชื่อสำรอง และชื่อยาวถูกตัดไม่เกินเพดาน"""
    assert sanitize_folder_name("") == UNKNOWN_VENDOR_FOLDER
    assert len(sanitize_folder_name("ก" * 200)) <= MAX_FOLDER_NAME_LENGTH


@pytest.mark.parametrize(
    ("configured_value", "expected"),
    [
        ("powerautomate", BACKEND_POWER_AUTOMATE),
        ("Power-Automate", BACKEND_POWER_AUTOMATE),
        ("sharepoint", BACKEND_GDRIVE),  # แบบเดิม (ACS) เลิกใช้แล้ว ค่านี้ตกไปใช้ gdrive
        ("gdrive", BACKEND_GDRIVE),
        ("อื่นๆ", BACKEND_GDRIVE),
    ],
)
def test_active_backend_follows_setting(configured_value: str, expected: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """ค่าที่ไม่รู้จักใช้ gdrive และไม่สนตัวพิมพ์"""
    monkeypatch.setenv("STORAGE_BACKEND", configured_value)
    assert get_active_backend() == expected


def test_online_storage_is_off_and_empty_upload_sends_nothing() -> None:
    """ชุดทดสอบต้องไม่มีปลายทางออนไลน์ และไม่มีไฟล์ก็ไม่เรียกปลายทาง"""
    assert is_storage_configured() is False
    assert upload_files_to_storage([], ["2026", "Mar", "19", "X"]) == []
