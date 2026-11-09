"""ทดสอบการตั้งชื่อโฟลเดอร์และการเลือกปลายทางใน utils/storage_backend.py"""

from datetime import datetime

import pytest

from utils.storage_backend import (
    BACKEND_GDRIVE,
    BACKEND_SHAREPOINT,
    MAX_FOLDER_NAME_LENGTH,
    PR_TOKEN_PATTERN,
    UNKNOWN_VENDOR_FOLDER,
    build_dated_folder_name,
    build_folder_name_from_files,
    build_storage_folder_parts,
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


def test_dated_folder_name_uses_given_date_instead_of_file_name_date() -> None:
    """วันที่นำหน้าชื่อโฟลเดอร์มาจาก when ไม่ใช่วันที่ที่ติดมากับชื่อไฟล์"""
    assert build_dated_folder_name(datetime(2026, 3, 19), ["20250101_PR_Addin.pdf"]) == "20260319_Addin"


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


def test_sanitize_folder_name_handles_empty_and_long_names() -> None:
    """ชื่อว่างใช้ชื่อสำรอง และชื่อยาวถูกตัดไม่เกินเพดาน"""
    assert sanitize_folder_name("") == UNKNOWN_VENDOR_FOLDER
    assert len(sanitize_folder_name("ก" * 200)) <= MAX_FOLDER_NAME_LENGTH


@pytest.mark.parametrize(
    ("configured_value", "expected"),
    [("sharepoint", BACKEND_SHAREPOINT), ("SharePoint", BACKEND_SHAREPOINT), ("gdrive", BACKEND_GDRIVE), ("อื่นๆ", BACKEND_GDRIVE)],
)
def test_active_backend_follows_setting(configured_value: str, expected: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """ค่าที่ไม่รู้จักใช้ gdrive และไม่สนตัวพิมพ์"""
    monkeypatch.setenv("STORAGE_BACKEND", configured_value)
    assert get_active_backend() == expected


def test_online_storage_is_off_and_empty_upload_sends_nothing() -> None:
    """ชุดทดสอบต้องไม่มีปลายทางออนไลน์ และไม่มีไฟล์ก็ไม่เรียกปลายทาง"""
    assert is_storage_configured() is False
    assert upload_files_to_storage([], ["2026", "Mar", "19", "X"]) == []
