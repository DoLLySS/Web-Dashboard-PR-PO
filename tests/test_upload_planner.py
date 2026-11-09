"""ทดสอบการวิเคราะห์และการบันทึกตามที่ผู้ใช้ยืนยันใน utils/upload_planner.py"""

from datetime import date
from pathlib import Path
from typing import Optional

import pytest

import utils.submit_pipeline as pipeline
from data.database import count_transactions, get_transactions, get_transactions_with_files
from pages_ui.overview import build_fields_from_item, clean_pr_file_name, find_rows_outside_range
from utils.submit_pipeline import RecordFields, submit_record
from utils.upload_planner import (
    ACTION_BATCH_PREFIX,
    ACTION_NEW_ROW,
    ACTION_ROW_PREFIX,
    ACTION_SKIP,
    PAGE_NOT_PR,
    ReviewItem,
    UploadPlan,
    build_item_options,
    build_review_items,
    build_upload_plan,
    execute_upload_plan,
    find_review_problems,
    get_default_page_choice,
    page_choice_key,
)

VENDOR_TAX_ID: str = "0105551000001"


def make_pdf(pages: list[str]) -> bytes:
    """สร้าง PDF ข้อความแบบง่าย หน้าละ 1 บรรทัด"""
    objects: list[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{3 + index * 2} 0 R" for index in range(len(pages)))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    font_id = 3 + len(pages) * 2
    for index, text in enumerate(pages):
        content_id = 4 + index * 2
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_id} 0 R "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>".encode()
        )
        stream = f"BT /F1 12 Tf 40 760 Td ({text}) Tj ET".encode()
        objects.append(b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream))
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    output, offsets = b"%PDF-1.4\n", []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output += b"%d 0 obj\n%s\nendobj\n" % (number, body)
    xref_position = len(output)
    output += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    output += b"".join(b"%010d 00000 n \n" % offset for offset in offsets)
    output += b"trailer << /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF" % (len(objects) + 1, xref_position)
    return output


def plan_for(files: list[tuple[str, bytes]]) -> UploadPlan:
    """สร้างข้อเสนอการอัปโหลดสำหรับทดสอบ"""
    return build_upload_plan(files, clean_pr_file_name, "test-plan")


def default_page_choices(plan: UploadPlan) -> dict[str, Optional[str]]:
    """การเลือกหน้าเริ่มต้นตามที่หน้าจอใช้"""
    return {
        page_choice_key(analysis.index, page.number): get_default_page_choice(page)
        for analysis in plan.files
        if analysis.needs_page_review
        for page in analysis.pages
    }


def fields_for(item: ReviewItem) -> RecordFields:
    """สร้างฟิลด์ของแถวใหม่ด้วยฟังก์ชันจริงของหน้า Overview"""
    return build_fields_from_item(item, "Hardware", "ยังไม่มีใบกำกับภาษี")


def count_files(directory: Path) -> int:
    """นับไฟล์ทั้งหมดในโฟลเดอร์เก็บไฟล์"""
    return sum(1 for path in directory.rglob("*") if path.is_file()) if directory.exists() else 0


MULTI_PR_PDF: bytes = make_pdf(
    [
        "PR No: PR-2026-0001 NB Alpha X100",
        "Terms and conditions without a number",
        "PR No: PR-2026-0002 Printer Beta Y200",
    ]
)


def test_analysis_writes_nothing(isolated_storage: Path) -> None:
    """การวิเคราะห์ต้องไม่เขียนไฟล์และไม่สร้างแถว"""
    plan_for([("20260319 PR_Addin_Alpha.pdf", make_pdf(["PR No: PR-2026-0001"])), ("quote.pdf", make_pdf(["quote"]))])
    assert count_transactions() == 0
    assert count_files(isolated_storage) == 0


def test_page_without_number_does_not_inherit_previous_pr(isolated_storage: Path) -> None:
    """หน้าที่อ่านเลข PR ไม่ได้ต้องไม่มีค่าเสนอ และต้องให้ผู้ใช้ระบุก่อนบันทึก"""
    plan = plan_for([("bundle PR.pdf", MULTI_PR_PDF)])
    choices = default_page_choices(plan)

    assert plan.files[0].needs_page_review
    assert choices == {"0:1": "PR-2026-0001", "0:2": None, "0:3": "PR-2026-0002"}
    decisions = {item.item_id: ACTION_NEW_ROW for item in build_review_items(plan, choices)}
    assert any("หน้า 2" in problem for problem in find_review_problems(plan, choices, decisions))


def test_single_pr_number_does_not_need_page_review(isolated_storage: Path) -> None:
    """ไฟล์ที่มีเลข PR เดียวนับเป็นหนึ่งแถว ไม่ต้องแบ่งหน้า"""
    plan = plan_for([("PR single.pdf", make_pdf(["PR No: PR-2026-0001", "second page"]))])
    assert not plan.files[0].needs_page_review
    assert [item.item_id for item in build_review_items(plan, {})] == ["0"]


def test_every_item_needs_an_explicit_decision(isolated_storage: Path) -> None:
    """ไม่มีการเลือกปลายทางให้ล่วงหน้า แม้จะมีแถวที่แนะนำ"""
    submit_record(RecordFields(date="2026-03-19", vendor="A", description="Alpha"), [("PR_old.pdf", b"old")])
    plan = plan_for([("20261105 PR_Addin_Alpha.pdf", make_pdf(["x"]))])

    items = build_review_items(plan, {})

    assert items[0].suggestion is not None
    assert "ซื้อซ้ำ" in items[0].suggestion.reason
    assert find_review_problems(plan, {}, {}) != []
    assert find_review_problems(plan, {}, {"0": ACTION_NEW_ROW}) == []


def test_repeat_purchase_creates_new_row_when_user_chooses_it(isolated_storage: Path) -> None:
    """ชื่อเดิมคนละวัน: ถ้าผู้ใช้เลือกสร้างแถวใหม่ ต้องได้แถวใหม่และโฟลเดอร์ตามวันที่ใหม่"""
    submit_record(RecordFields(date="2026-03-19", vendor="A", description="Alpha"), [("PR_old.pdf", b"old")])
    plan = plan_for([("20261105 PR_Addin_Alpha.pdf", make_pdf(["x"]))])

    outcomes = execute_upload_plan(plan, {}, {"0": ACTION_NEW_ROW}, fields_for)

    assert outcomes["0"].transaction_id is not None
    assert count_transactions() == 2
    assert (isolated_storage / "2026" / "Nov" / "05").is_dir()


def test_user_can_attach_to_suggested_row_without_new_row(isolated_storage: Path) -> None:
    """ถ้าผู้ใช้เลือกแถวที่แนะนำ ไฟล์ต้องเข้าแถวนั้นและไม่เกิดแถวใหม่"""
    old_id = submit_record(
        RecordFields(date="2026-03-19", vendor="A", tax_id=VENDOR_TAX_ID, description="Alpha"), [("PR_old.pdf", b"old")]
    ).transaction_id
    plan = plan_for([("quotation.pdf", make_pdf([f"Tax ID {VENDOR_TAX_ID} something"]))])
    assert plan.suggestions["0"].transaction["id"] == old_id

    execute_upload_plan(plan, {}, {"0": f"{ACTION_ROW_PREFIX}{old_id}"}, fields_for)

    assert count_transactions() == 1
    assert "quotation.pdf" in get_transactions_with_files()[0]["file_path"]


def test_two_pr_files_create_two_rows_and_other_file_joins_the_chosen_one(isolated_storage: Path) -> None:
    """PR สองไฟล์ได้สองแถว และไฟล์อื่นแนบกับ PR ใหม่ในชุดเดียวกันที่ผู้ใช้เลือก"""
    plan = plan_for(
        [
            ("20260319 PR_Addin_Alpha.pdf", make_pdf(["PR No: PR-2026-0001"])),
            ("20260320 PR_Addin_Beta.pdf", make_pdf(["PR No: PR-2026-0002"])),
            ("quotation.pdf", make_pdf(["quote"])),
        ]
    )
    items = build_review_items(plan, {})
    assert f"{ACTION_BATCH_PREFIX}1" in build_item_options(plan, items[2], items)
    decisions = {"0": ACTION_NEW_ROW, "1": ACTION_NEW_ROW, "2": f"{ACTION_BATCH_PREFIX}1"}
    assert find_review_problems(plan, {}, decisions) == []

    execute_upload_plan(plan, {}, decisions, fields_for)

    rows = {row["pr_run_no"]: row for row in get_transactions_with_files()}
    assert set(rows) == {"PR-2026-0001", "PR-2026-0002"}
    assert "quotation.pdf" in rows["PR-2026-0002"]["file_path"]
    assert "quotation.pdf" not in rows["PR-2026-0001"]["file_path"]


def test_attaching_to_a_pr_that_is_not_created_is_rejected(isolated_storage: Path) -> None:
    """ห้ามเลือกแนบกับ PR ในชุดที่ผู้ใช้ไม่ได้เลือกสร้างแถว"""
    plan = plan_for([("PR_a.pdf", make_pdf(["a"])), ("quote.pdf", make_pdf(["quote"]))])
    problems = find_review_problems(plan, {}, {"0": ACTION_SKIP, "1": f"{ACTION_BATCH_PREFIX}0"})
    assert any("ไม่ได้สร้างแถวใหม่" in problem for problem in problems)


def test_one_file_with_two_prs_creates_two_rows_sharing_one_file(
    isolated_storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """หนึ่ง PR ได้หนึ่งแถว อ้างอิงไฟล์เดียวกัน และเก็บกับส่งออนไลน์ครั้งเดียว"""
    uploads: list[list[str]] = []
    monkeypatch.setattr(pipeline, "is_storage_configured", lambda: True)
    monkeypatch.setattr(pipeline, "get_storage_folder_url", lambda _parts: None)

    def fake_upload(files: list[tuple[str, bytes]], _parts: list[str]) -> list[str]:
        uploads.append([name for name, _ in files])
        return ["https://example.invalid/file"]

    monkeypatch.setattr(pipeline, "upload_files_to_storage", fake_upload)
    plan = plan_for([("bundle PR.pdf", MULTI_PR_PDF)])
    choices = {**default_page_choices(plan), "0:2": "PR-2026-0002"}
    decisions = {item.item_id: ACTION_NEW_ROW for item in build_review_items(plan, choices)}
    assert find_review_problems(plan, choices, decisions) == []

    execute_upload_plan(plan, choices, decisions, fields_for)

    rows = get_transactions_with_files()
    assert sorted(row["pr_run_no"] for row in rows) == ["PR-2026-0001", "PR-2026-0002"]
    assert len({row["file_path"] for row in rows}) == 1
    assert len({row["description"] for row in rows}) == 2
    assert count_files(isolated_storage) == 1
    assert uploads == [["bundle PR.pdf"]]


def test_pages_marked_not_pr_are_excluded_from_extraction(isolated_storage: Path) -> None:
    """ข้อความในหน้าที่ผู้ใช้ระบุว่าไม่ใช่ PR ต้องไม่ถูกใช้ดึงข้อมูลของแถว"""
    plan = plan_for([("bundle PR.pdf", MULTI_PR_PDF)])
    choices = {**default_page_choices(plan), "0:2": PAGE_NOT_PR}
    texts = {item.pr_no: item.text for item in build_review_items(plan, choices)}
    assert all("Terms and conditions" not in text for text in texts.values())


def test_marking_every_page_not_pr_leaves_one_whole_file_item(isolated_storage: Path) -> None:
    """ไฟล์ที่ผู้ใช้ระบุว่าไม่มี PR ยังเลือกปลายทางของทั้งไฟล์ได้"""
    plan = plan_for([("quote bundle.pdf", MULTI_PR_PDF)])
    choices = {key: PAGE_NOT_PR for key in default_page_choices(plan)}
    items = build_review_items(plan, choices)
    assert [(item.item_id, item.is_pr) for item in items] == [("0", False)]


def test_retry_after_partial_failure_only_repeats_failed_items(
    isolated_storage: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """แถวที่สำเร็จแล้วต้องไม่ถูกสร้างซ้ำ และไฟล์ต้องไม่ถูกเก็บซ้ำเมื่อกดบันทึกอีกครั้ง"""
    plan = plan_for([("bundle PR.pdf", MULTI_PR_PDF)])
    choices = {**default_page_choices(plan), "0:2": PAGE_NOT_PR}
    decisions = {item.item_id: ACTION_NEW_ROW for item in build_review_items(plan, choices)}
    real_add = pipeline.add_transaction

    def fail_second_row(**kwargs: object) -> Optional[int]:
        return None if kwargs.get("pr_run_no") == "PR-2026-0002" else real_add(**kwargs)

    monkeypatch.setattr(pipeline, "add_transaction", fail_second_row)
    first_round = execute_upload_plan(plan, choices, decisions, fields_for)
    assert first_round["0:PR-2026-0002"].transaction_id is None
    assert count_transactions() == 1

    monkeypatch.setattr(pipeline, "add_transaction", real_add)
    second_round = execute_upload_plan(plan, choices, decisions, fields_for)

    assert set(second_round) == {"0:PR-2026-0002"}
    assert count_transactions() == 2
    assert count_files(isolated_storage) == 1


def test_skipped_item_writes_nothing(isolated_storage: Path) -> None:
    """รายการที่เลือกไม่บันทึกต้องไม่เกิดไฟล์หรือแถว"""
    plan = plan_for([("PR_a.pdf", make_pdf(["a"]))])
    assert execute_upload_plan(plan, {}, {"0": ACTION_SKIP}, fields_for) == {}
    assert count_transactions() == 0
    assert count_files(isolated_storage) == 0


def test_existing_rows_are_not_changed_by_new_uploads(isolated_storage: Path) -> None:
    """การอัปโหลดใหม่ต้องไม่แก้ไขแถวเดิมที่ผู้ใช้ไม่ได้เลือก"""
    submit_record(RecordFields(date="2026-03-19", vendor="A", description="Alpha"), [("PR_old.pdf", b"old")])
    before = get_transactions()
    plan = plan_for([("PR_new.pdf", make_pdf(["new"]))])
    execute_upload_plan(plan, {}, {"0": ACTION_NEW_ROW}, fields_for)
    assert [row for row in get_transactions() if row["id"] == before[0]["id"]] == before


def test_rows_outside_filter_range_are_found() -> None:
    """แจ้งเฉพาะแถวที่อยู่นอกช่วง และข้ามแถวที่วันที่อ่านไม่ได้"""
    rows = [(1, "2026-03-19"), (2, "2026-11-01"), (3, "ไม่ใช่วันที่")]
    assert find_rows_outside_range(rows, date(2026, 10, 10), date(2026, 11, 9)) == [(1, date(2026, 3, 19))]
