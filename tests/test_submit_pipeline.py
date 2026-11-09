"""ทดสอบการจับคู่ไฟล์กับแถว PR และการบันทึกใน utils/submit_pipeline.py

ผลการจับคู่ใช้ในการอัปโหลดอัตโนมัติ (ดู utils/upload_processor.py และ tests/test_upload_processor.py)
"""

from pathlib import Path
from typing import Any

import pytest

import utils.submit_pipeline as pipeline
from data.database import count_transactions, get_transactions_with_files
from utils.submit_pipeline import (
    FolderMatch,
    FolderProfile,
    FolderProfileCache,
    RecordFields,
    attach_files_to_record,
    find_pr_folder_candidates,
    match_document_to_pr,
    submit_record,
)
from utils.text_extractor import OWN_COMPANY_TAX_ID

VENDOR_A_TAX_ID: str = "0105551000001"
VENDOR_B_TAX_ID: str = "0105552000002"
PR_FILE: tuple[str, bytes] = ("20260319_PR_Addin_ซื้อ NB Alpha X100.pdf", b"pr-content")


class FakeProfiles(FolderProfileCache):
    """โปรไฟล์โฟลเดอร์ที่กำหนดเอง เพื่อทดสอบการจับคู่โดยไม่ต้องอ่านไฟล์จริง"""

    def __init__(self, profiles: dict[int, FolderProfile]) -> None:
        super().__init__()
        self._profiles = profiles


def make_candidate(row_id: int, description: str = "", tax_id: str = "") -> FolderMatch:
    """สร้างแถว PR สำหรับทดสอบ"""
    transaction: dict[str, Any] = {
        "id": row_id,
        "description": description,
        "tax_id": tax_id,
        "file_path": f"static/local_uploads/2026/Jan/01/row{row_id}/PR_{row_id}.pdf",
    }
    return FolderMatch(transaction, ["2026", "Jan", "01", f"row{row_id}"], 1)


def make_fields(description: str = "NB Alpha X100", vendor: str = "Alpha") -> RecordFields:
    """สร้างฟิลด์ของรายการสำหรับทดสอบ"""
    return RecordFields(date="2026-03-19", vendor=vendor, description=description, tax_id=VENDOR_A_TAX_ID)


# ---------------------------------------------------------------------------
# กติกาการจับคู่ที่ตั้งใจไว้
# ---------------------------------------------------------------------------


def test_own_company_tax_id_in_document_is_ignored() -> None:
    """เลขบริษัทเราอยู่ในเอกสารทุกใบ จึงต้องไม่ทำให้จับคู่ได้ แม้โปรไฟล์ของแถวจะมีเลขนี้"""
    candidate = make_candidate(1, "Server Rack")
    profiles = FakeProfiles({1: FolderProfile({OWN_COMPANY_TAX_ID}, set())})
    assert match_document_to_pr(f"ผู้ซื้อ {OWN_COMPANY_TAX_ID}", [candidate], profiles) is None


def test_own_company_tax_id_is_removed_from_folder_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    """โปรไฟล์ที่สร้างจากไฟล์ในโฟลเดอร์ต้องไม่เก็บเลขบริษัทเรา แต่เก็บเลขผู้ขาย"""
    candidate = make_candidate(1, "Server Rack", OWN_COMPANY_TAX_ID)
    monkeypatch.setattr(pipeline, "list_stored_files", lambda _paths: [Path("quote.pdf")])
    monkeypatch.setattr(
        pipeline, "extract_text_from_file", lambda _path, _name: f"{OWN_COMPANY_TAX_ID} {VENDOR_A_TAX_ID}"
    )
    assert FolderProfileCache().get(candidate).tax_ids == {VENDOR_A_TAX_ID}


def test_description_words_pick_the_matching_row() -> None:
    """ไม่มี Tax ID ตรงกัน ใช้คำจาก Description"""
    alpha, beta = make_candidate(1, "NB Alpha X100"), make_candidate(2, "Printer Beta Y200")
    profiles = FakeProfiles({1: FolderProfile(set(), set()), 2: FolderProfile(set(), set())})
    assert match_document_to_pr("ใบเสนอราคา printer beta y200", [alpha, beta], profiles).transaction["id"] == 2


def test_equal_description_scores_do_not_guess() -> None:
    """คะแนนสูงสุดเท่ากันหลายแถว ต้องไม่เดา"""
    first, second = make_candidate(1, "NB Alpha"), make_candidate(2, "NB Alpha")
    profiles = FakeProfiles({1: FolderProfile(set(), set()), 2: FolderProfile(set(), set())})
    assert match_document_to_pr("nb alpha", [first, second], profiles) is None


def test_description_separates_two_rows_of_the_same_vendor() -> None:
    """Tax ID ตรงหลายแถว ใช้ Description ตัดสินเฉพาะในแถวของผู้ขายนั้น"""
    alpha, beta = make_candidate(1, "NB Alpha X100"), make_candidate(2, "Printer Beta Y200")
    same_vendor = FolderProfile({VENDOR_A_TAX_ID}, set())
    profiles = FakeProfiles({1: same_vendor, 2: same_vendor})
    assert match_document_to_pr(f"{VENDOR_A_TAX_ID} printer beta y200", [alpha, beta], profiles).transaction["id"] == 2


def test_folder_words_require_a_model_code_with_digits() -> None:
    """คำอังกฤษซ้ำกันอย่างเดียวไม่พอ ต้องมีรหัสรุ่นที่มีตัวเลขด้วย"""
    candidate = make_candidate(1, "ไม่ตรงกับเอกสาร")
    profiles = FakeProfiles({1: FolderProfile(set(), {"lenovo", "thinkpad", "laptop", "e14"})})
    assert match_document_to_pr("lenovo thinkpad laptop", [candidate], profiles) is None
    assert match_document_to_pr("lenovo thinkpad e14", [candidate], profiles).transaction["id"] == 1


def test_no_matching_information_returns_none() -> None:
    """ไม่มีข้อมูลตรงกันเลย ต้องไม่จับคู่"""
    candidate = make_candidate(1, "Server Rack")
    profiles = FakeProfiles({1: FolderProfile({VENDOR_A_TAX_ID}, {"rack42"})})
    assert match_document_to_pr("เอกสารอื่นที่ไม่เกี่ยวข้อง", [candidate], profiles) is None


# ---------------------------------------------------------------------------
# การบันทึกไฟล์และรายการ
# ---------------------------------------------------------------------------


def test_submit_record_stores_file_in_dated_folder_and_reports_each_step(isolated_storage: Path) -> None:
    """รายการใหม่เก็บไฟล์ตามวันที่ของ PR และรายงานว่าปลายทางออนไลน์ถูกข้าม"""
    result = submit_record(make_fields(), [PR_FILE])

    assert result.transaction_id is not None
    assert count_transactions() == 1
    assert (isolated_storage / "2026" / "Mar" / "19").is_dir()
    assert result.storage_status == "skipped"
    assert result.masterlist_sent is False


def test_attach_adds_file_to_existing_row_without_new_row(isolated_storage: Path) -> None:
    """ไฟล์ที่แนบเข้าแถวเดิมต้องไม่สร้างแถวใหม่"""
    submit_record(make_fields(), [PR_FILE])
    match = find_pr_folder_candidates()[0]

    result = attach_files_to_record(match, [("quotation.pdf", b"quote")])

    assert result.attached_file_names == ["quotation.pdf"]
    assert count_transactions() == 1
    assert "quotation.pdf" in get_transactions_with_files()[0]["file_path"]


def test_attach_identical_file_again_changes_nothing(isolated_storage: Path) -> None:
    """ไฟล์เดิมเนื้อเหมือนกันทุกไบต์ ต้องไม่สร้างสำเนา"""
    submit_record(make_fields(), [PR_FILE])
    match = find_pr_folder_candidates()[0]

    result = attach_files_to_record(match, [PR_FILE])

    assert result.attached_file_names == []
    assert len(list(isolated_storage.rglob("*.pdf"))) == 1


def test_attach_same_name_with_new_content_keeps_both_files(isolated_storage: Path) -> None:
    """ชื่อซ้ำแต่เนื้อต่างกัน ต้องไม่เขียนทับไฟล์เดิม"""
    submit_record(make_fields(), [PR_FILE])
    match = find_pr_folder_candidates()[0]

    result = attach_files_to_record(match, [(PR_FILE[0], b"changed-content")])

    assert len(result.attached_file_names) == 1
    contents = sorted(path.read_bytes() for path in isolated_storage.rglob("*.pdf"))
    assert contents == [b"changed-content", b"pr-content"]


# ---------------------------------------------------------------------------
# คำแนะนำและจำนวนไฟล์ที่ต้องอ่าน
# ---------------------------------------------------------------------------


def test_tax_id_of_the_row_is_reported_as_the_reason() -> None:
    """Tax ID ตรงกับแถวเดียว ได้คำแนะนำพร้อมเหตุผล แม้เนื้อหาจะไม่เกี่ยวกัน เพราะผู้ใช้เป็นคนตัดสิน"""
    old_row = make_candidate(1, "NB Alpha X100", VENDOR_A_TAX_ID)
    match = match_document_to_pr(f"{VENDOR_A_TAX_ID} printer beta y200", [old_row], FakeProfiles({}))
    assert match is not None
    assert match.transaction["id"] == 1
    assert "Tax ID ตรงกับแถวนี้" in match.reason


def test_tax_id_found_only_in_folder_warns_it_may_be_a_competitor(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tax ID ที่พบเฉพาะในไฟล์ของโฟลเดอร์ ต้องบอกว่าอาจเป็นคู่เทียบ"""
    vendor_a_row = make_candidate(1, "NB Alpha X100", VENDOR_A_TAX_ID)
    monkeypatch.setattr(pipeline, "list_stored_files", lambda _paths: [Path("competitor_quote.pdf")])
    monkeypatch.setattr(pipeline, "extract_text_from_file", lambda _path, _name: f"คู่เทียบ {VENDOR_B_TAX_ID}")

    match = match_document_to_pr(f"{VENDOR_B_TAX_ID} ใบแจ้งหนี้งานอื่น", [vendor_a_row])

    assert match is not None
    assert "คู่เทียบ" in match.reason


@pytest.mark.parametrize(
    ("document", "expected_reads"),
    [
        pytest.param("item model7 series7", 0, id="description-decides"),
        pytest.param(f"{VENDOR_A_TAX_ID} เอกสาร", 0, id="row-tax-id-decides"),
        pytest.param("เอกสารที่ไม่มีข้อมูลตรงกัน", 50, id="needs-folder-words"),
    ],
)
def test_folder_files_are_read_only_when_earlier_steps_cannot_decide(
    document: str, expected_reads: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """อ่านไฟล์ในโฟลเดอร์เฉพาะเมื่อข้อมูลของแถวตัดสินไม่ได้"""
    read_files: list[str] = []

    def fake_extract(path: Path, _name: str) -> str:
        read_files.append(str(path))
        return ""

    candidates = [make_candidate(row_id, f"Item Model{row_id} Series{row_id}") for row_id in range(1, 51)]
    candidates[0].transaction["tax_id"] = VENDOR_A_TAX_ID
    monkeypatch.setattr(pipeline, "list_stored_files", lambda paths: [Path(paths)])
    monkeypatch.setattr(pipeline, "extract_text_from_file", fake_extract)

    match_document_to_pr(document, candidates)

    assert len(read_files) == expected_reads
