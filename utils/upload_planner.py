"""วางแผนการอัปโหลด: วิเคราะห์ไฟล์เป็นข้อเสนอให้ผู้ใช้ยืนยัน แล้วค่อยบันทึกตามที่ผู้ใช้เลือก

ขั้นวิเคราะห์ (build_upload_plan) ไม่เขียนไฟล์หรือฐานข้อมูล การเขียนเกิดใน execute_upload_plan เท่านั้น
ไฟล์นี้ไม่เรียก Streamlit
"""

import io
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Callable, Optional

from data.database import get_transactions_with_files
from utils.local_storage import get_folder_parts_from_file_paths
from utils.storage_backend import PR_TOKEN_PATTERN
from utils.submit_pipeline import (
    FolderMatch,
    FolderProfileCache,
    RecordFields,
    StoredFiles,
    SubmitResult,
    add_record_from_stored_files,
    attach_files_to_record,
    find_pr_folder_by_description,
    find_pr_folder_candidates,
    match_document_to_pr,
    store_files_for_new_record,
)
from utils.text_extractor import extract_page_texts_from_pdf, extract_text_from_file, find_pr_run_no

# การตัดสินใจของแต่ละรายการ: ค่าคงที่ หรือคำนำหน้าตามด้วยรหัส เช่น "row:12", "batch:0:PR-1"
ACTION_NEW_ROW: str = "new"
ACTION_SKIP: str = "skip"
ACTION_ROW_PREFIX: str = "row:"
ACTION_BATCH_PREFIX: str = "batch:"
PAGE_NOT_PR: str = "__not_pr__"  # ค่าที่ผู้ใช้เลือกให้หน้าที่ไม่ใช่ PR

MIN_PR_NUMBERS_FOR_PAGE_REVIEW: int = 2  # ไฟล์ที่พบเลข PR ตั้งแต่กี่เลข จึงต้องแบ่งหน้า


@dataclass
class PageInfo:
    """ข้อมูล 1 หน้าของ PDF"""

    number: int  # เลขหน้า เริ่มที่ 1
    text: str
    detected_pr_no: str  # เลข PR ที่อ่านได้จากหน้านี้เอง ("" = อ่านไม่ได้ ไม่สืบทอดจากหน้าก่อน)


@dataclass
class FileAnalysis:
    """ผลการวิเคราะห์ไฟล์ที่อัปโหลด 1 ไฟล์"""

    index: int
    name: str
    data: bytes
    is_pr_file: bool
    text: str
    pages: list[PageInfo] = field(default_factory=list)

    @property
    def pr_numbers(self) -> list[str]:
        """เลข PR ไม่ซ้ำ เรียงตามหน้าที่พบ"""
        return list(dict.fromkeys(page.detected_pr_no for page in self.pages if page.detected_pr_no))

    @property
    def needs_page_review(self) -> bool:
        """ไฟล์นี้มีหลาย PR จึงต้องให้ผู้ใช้ยืนยันการแบ่งหน้าหรือไม่"""
        return len(self.pr_numbers) >= MIN_PR_NUMBERS_FOR_PAGE_REVIEW


@dataclass
class ReviewItem:
    """สิ่งที่ผู้ใช้ต้องตัดสินใจ 1 รายการ: ไฟล์ทั้งไฟล์ หรือ 1 PR ในไฟล์ที่มีหลาย PR"""

    item_id: str
    file_index: int
    file_name: str
    text: str
    is_pr: bool
    pr_no: str
    description: str
    suggestion: Optional[FolderMatch]


@dataclass
class UploadPlan:
    """ข้อเสนอของการอัปโหลด 1 ครั้ง และความคืบหน้าของการบันทึก"""

    plan_id: str
    files: list[FileAnalysis]
    descriptions: dict[str, str]
    suggestions: dict[str, Optional[FolderMatch]]
    attachable_rows: list[dict[str, Any]]  # ทุกแถวที่มีโฟลเดอร์ เรียงจากล่าสุด (รวมแถวที่ชื่อไฟล์ไม่มีคำว่า PR)
    stored: dict[int, StoredFiles] = field(default_factory=dict)  # ไฟล์ที่เก็บแล้ว (กดซ้ำไม่เก็บและไม่ส่งซ้ำ)
    completed: dict[str, SubmitResult] = field(default_factory=dict)  # รายการที่บันทึกสำเร็จแล้ว (กดซ้ำไม่ทำซ้ำ)


def _whole_file_item_id(file_index: int) -> str:
    """รหัสรายการที่แทนไฟล์ทั้งไฟล์"""
    return str(file_index)


def _section_item_id(file_index: int, pr_no: str) -> str:
    """รหัสรายการที่แทน 1 PR ในไฟล์ที่มีหลาย PR"""
    return f"{file_index}:{pr_no}"


def _find_row_by_pr_no(pr_no: str, candidates: list[FolderMatch]) -> Optional[FolderMatch]:
    """หาแถวล่าสุดที่เลข PR ตรงกันทุกตัวอักษร (candidates เรียงจากล่าสุด)"""
    wanted = pr_no.strip().lower()
    matches = [item for item in candidates if wanted and (item.transaction.get("pr_run_no") or "").strip().lower() == wanted]
    if not matches:
        return None
    return replace(matches[0], match_count=len(matches), reason="เลข PR ตรงกับแถวนี้ (อาจเป็นเอกสารเดิม)")


def _suggest_row_for_pr(pr_no: str, description: str, candidates: list[FolderMatch]) -> Optional[FolderMatch]:
    """แนะนำแถวเดิมของ PR: เลข PR ตรงกันก่อน แล้วจึงดู Description ที่อาจเป็นการซื้อซ้ำ"""
    by_pr_no = _find_row_by_pr_no(pr_no, candidates)
    if by_pr_no:
        return by_pr_no
    by_description = find_pr_folder_by_description(description, candidates)
    if by_description:
        return replace(by_description, reason="ชื่อตรงกับ Description ของแถวนี้ (อาจเป็นการซื้อซ้ำ)")
    return None


def _analyze_file(index: int, name: str, data: bytes) -> FileAnalysis:
    """อ่านข้อความของไฟล์ และเลข PR รายหน้าถ้าเป็น PDF (ไม่เขียนอะไรลงเครื่อง)"""
    is_pr_file = bool(PR_TOKEN_PATTERN.search(name))
    if Path(name).suffix.lower() != ".pdf":
        return FileAnalysis(index, name, data, is_pr_file, extract_text_from_file(io.BytesIO(data), name))
    page_texts = extract_page_texts_from_pdf(io.BytesIO(data))
    pages = [PageInfo(number, text, find_pr_run_no(text)) for number, text in enumerate(page_texts, start=1)]
    return FileAnalysis(index, name, data, is_pr_file, "\n".join(page_texts), pages)


def build_upload_plan(files: list[tuple[str, bytes]], describe_file: Callable[[str], str], plan_id: str) -> UploadPlan:
    """วิเคราะห์ไฟล์ที่วางเป็นข้อเสนอ ขั้นนี้ไม่เขียนไฟล์และไม่เขียนฐานข้อมูล

    Args:
        files: ไฟล์ที่วาง (ชื่อไฟล์, เนื้อไฟล์)
        describe_file: ฟังก์ชันแปลงชื่อไฟล์เป็น Description
        plan_id: รหัสของการอัปโหลดครั้งนี้ (ใช้แยก key ของช่องเลือก)

    Returns:
        ข้อเสนอพร้อมแถวที่แนะนำของแต่ละรายการ
    """
    candidates = find_pr_folder_candidates()
    profiles = FolderProfileCache()  # อ่านไฟล์ในโฟลเดอร์ของแต่ละ PR ครั้งเดียวต่อการ Upload
    attachable_rows = [
        transaction
        for transaction in get_transactions_with_files()
        if get_folder_parts_from_file_paths(transaction.get("file_path"))
    ]
    plan = UploadPlan(plan_id, [], {}, {}, attachable_rows)

    for index, (name, data) in enumerate(files):
        analysis = _analyze_file(index, name, data)
        plan.files.append(analysis)
        base_description = describe_file(name)

        whole_id = _whole_file_item_id(index)
        plan.descriptions[whole_id] = base_description
        if analysis.is_pr_file:
            pr_no = find_pr_run_no(analysis.text)
            plan.suggestions[whole_id] = _suggest_row_for_pr(pr_no, base_description, candidates)
        else:
            # รวมชื่อไฟล์ด้วย เพราะไฟล์สแกนอาจมีคำจาก Description เฉพาะในชื่อไฟล์
            plan.suggestions[whole_id] = match_document_to_pr(f"{name}\n{analysis.text}", candidates, profiles)

        if analysis.needs_page_review:
            for pr_no in analysis.pr_numbers:
                section_id = _section_item_id(index, pr_no)
                plan.descriptions[section_id] = f"{base_description} {pr_no}"
                plan.suggestions[section_id] = _suggest_row_for_pr(pr_no, plan.descriptions[section_id], candidates)
    return plan


def get_default_page_choice(page: PageInfo) -> Optional[str]:
    """ค่าเสนอของหน้า: เลข PR ที่อ่านได้จากหน้านั้น หน้าอื่นไม่มีค่าเสนอ ผู้ใช้ต้องระบุเอง"""
    return page.detected_pr_no or None


def build_review_items(plan: UploadPlan, page_choices: dict[str, Optional[str]]) -> list[ReviewItem]:
    """สร้างรายการที่ต้องตัดสินใจตามการแบ่งหน้าปัจจุบัน

    Args:
        plan: ข้อเสนอการอัปโหลด
        page_choices: {"<ลำดับไฟล์>:<เลขหน้า>": เลข PR / PAGE_NOT_PR / None} ของไฟล์ที่ต้องแบ่งหน้า

    Returns:
        รายการต่อไฟล์ หรือต่อ PR สำหรับไฟล์ที่มีหลาย PR
    """
    items: list[ReviewItem] = []
    for analysis in plan.files:
        sections: dict[str, list[str]] = {}
        if analysis.needs_page_review:
            for page in analysis.pages:
                choice = page_choices.get(page_choice_key(analysis.index, page.number))
                if choice and choice != PAGE_NOT_PR:
                    sections.setdefault(choice, []).append(page.text)
        for pr_no in analysis.pr_numbers:
            if pr_no not in sections:
                continue
            item_id = _section_item_id(analysis.index, pr_no)
            items.append(
                ReviewItem(
                    item_id,
                    analysis.index,
                    analysis.name,
                    "\n".join(sections[pr_no]),
                    True,
                    pr_no,
                    plan.descriptions[item_id],
                    plan.suggestions[item_id],
                )
            )
        if not sections:
            # ไฟล์ปกติ หรือไฟล์ที่ผู้ใช้ระบุว่าไม่มีหน้าไหนเป็น PR
            item_id = _whole_file_item_id(analysis.index)
            items.append(
                ReviewItem(
                    item_id,
                    analysis.index,
                    analysis.name,
                    analysis.text,
                    analysis.is_pr_file and not analysis.needs_page_review,
                    find_pr_run_no(analysis.text) if not analysis.needs_page_review else "",
                    plan.descriptions[item_id],
                    plan.suggestions[item_id],
                )
            )
    return items


def page_choice_key(file_index: int, page_number: int) -> str:
    """key ของการเลือกในหน้า 1 หน้า"""
    return f"{file_index}:{page_number}"


def find_review_problems(
    plan: UploadPlan, page_choices: dict[str, Optional[str]], decisions: dict[str, Optional[str]]
) -> list[str]:
    """ตรวจว่าเลือกครบหรือไม่ (ต้องไม่มีปัญหาเหลือ จึงบันทึกได้)

    Args:
        plan: ข้อเสนอการอัปโหลด
        page_choices: การเลือกของแต่ละหน้า
        decisions: {item_id: การตัดสินใจ}

    Returns:
        ข้อความปัญหาที่ต้องแก้ (ว่าง = บันทึกได้)
    """
    problems: list[str] = []
    for analysis in plan.files:
        if analysis.needs_page_review:
            missing = [
                str(page.number)
                for page in analysis.pages
                if not page_choices.get(page_choice_key(analysis.index, page.number))
            ]
            if missing:
                problems.append(f"{analysis.name}: ยังไม่ได้ระบุหน้า {', '.join(missing)}")

    items = build_review_items(plan, page_choices)
    new_row_ids = {
        item.item_id for item in items if item.item_id in plan.completed or decisions.get(item.item_id) == ACTION_NEW_ROW
    }
    for item in items:
        if item.item_id in plan.completed:
            continue
        decision = decisions.get(item.item_id)
        if not decision:
            problems.append(f"{describe_item(item)}: ยังไม่ได้เลือกปลายทาง")
        elif decision.startswith(ACTION_BATCH_PREFIX) and decision.removeprefix(ACTION_BATCH_PREFIX) not in new_row_ids:
            problems.append(f"{describe_item(item)}: PR ที่เลือกไว้ไม่ได้สร้างแถวใหม่ในชุดนี้")
    return problems


def describe_item(item: ReviewItem) -> str:
    """ชื่อรายการสำหรับแสดงให้ผู้ใช้"""
    return f"{item.file_name} ({item.pr_no})" if item.pr_no else item.file_name


def _describe_row(transaction: dict[str, Any]) -> str:
    """ชื่อแถวสำหรับแสดงในตัวเลือก"""
    name = transaction.get("description") or transaction.get("vendor") or "-"
    return f"แถว {transaction.get('id')}: {name} ({transaction.get('date')})"


def build_item_options(plan: UploadPlan, item: ReviewItem, items: list[ReviewItem]) -> dict[str, str]:
    """ตัวเลือกของรายการ {ค่า: ข้อความ} โดยแถวที่แนะนำอยู่บนสุดพร้อมเหตุผล แต่ไม่ถูกเลือกไว้ให้

    Args:
        plan: ข้อเสนอการอัปโหลด
        item: รายการที่กำลังเลือก
        items: รายการทั้งหมดในชุด (ใช้สร้างตัวเลือกแนบกับ PR ใหม่ในชุดนี้)

    Returns:
        ตัวเลือกเรียงตามลำดับที่แสดง
    """
    options: dict[str, str] = {}
    suggested_id: Optional[int] = None
    if item.suggestion:
        suggested_id = int(item.suggestion.transaction["id"])
        count_note = f" · ตรง {item.suggestion.match_count} แถว ใช้แถวล่าสุด" if item.suggestion.match_count > 1 else ""
        options[f"{ACTION_ROW_PREFIX}{suggested_id}"] = (
            f"แนะนำ: แนบกับ{_describe_row(item.suggestion.transaction)} · {item.suggestion.reason}{count_note}"
        )
    options[ACTION_NEW_ROW] = "สร้างแถวใหม่"
    if not item.is_pr:
        for other in items:
            if other.is_pr and other.item_id != item.item_id:
                options[f"{ACTION_BATCH_PREFIX}{other.item_id}"] = f"แนบกับ PR ในชุดนี้: {describe_item(other)}"
    for transaction in plan.attachable_rows:
        row_id = int(transaction["id"])
        if row_id != suggested_id:
            options[f"{ACTION_ROW_PREFIX}{row_id}"] = f"แนบกับ{_describe_row(transaction)}"
    options[ACTION_SKIP] = "ไม่บันทึกรายการนี้"
    return options


def _load_attach_target(row_id: int) -> Optional[FolderMatch]:
    """อ่านแถวล่าสุดจากฐานข้อมูลสำหรับแนบไฟล์ (ต้องอ่านใหม่ เพราะรายการไฟล์ของแถวอาจเปลี่ยนแล้ว)"""
    for transaction in get_transactions_with_files():
        if int(transaction["id"]) == row_id:
            folder_parts = get_folder_parts_from_file_paths(transaction.get("file_path"))
            return FolderMatch(transaction, folder_parts, 1) if folder_parts else None
    return None


def _save_new_row(plan: UploadPlan, item: ReviewItem, fields: RecordFields) -> SubmitResult:
    """สร้างแถวใหม่ โดยเก็บและส่งไฟล์เพียงครั้งเดียวต่อไฟล์ แม้หลายแถวจะอ้างอิงไฟล์เดียวกัน"""
    stored = plan.stored.get(item.file_index)
    if stored is None or stored.local_paths is None:
        analysis = plan.files[item.file_index]
        stored = store_files_for_new_record(fields, [(analysis.name, analysis.data)])
        plan.stored[item.file_index] = stored
    return add_record_from_stored_files(fields, stored)


def execute_upload_plan(
    plan: UploadPlan,
    page_choices: dict[str, Optional[str]],
    decisions: dict[str, Optional[str]],
    build_fields: Callable[[ReviewItem], RecordFields],
) -> dict[str, SubmitResult]:
    """บันทึกตามที่ผู้ใช้ยืนยัน: สร้างแถวใหม่ก่อน แล้วจึงแนบไฟล์ (รายการที่สำเร็จแล้วไม่ทำซ้ำเมื่อเรียกอีกครั้ง)

    ถ้าบางรายการล้มเหลว จะไม่ย้อนลบรายการที่สำเร็จแล้ว

    Args:
        plan: ข้อเสนอการอัปโหลด (บันทึกความคืบหน้าลงในนี้)
        page_choices: การเลือกของแต่ละหน้า
        decisions: {item_id: การตัดสินใจ} ต้องผ่าน find_review_problems แล้ว
        build_fields: ฟังก์ชันสร้างฟิลด์ของแถวใหม่จากรายการ

    Returns:
        ผลของแต่ละรายการที่ทำในรอบนี้ รวมรายการที่ล้มเหลว {item_id: ผล}
    """
    items = [item for item in build_review_items(plan, page_choices) if item.item_id not in plan.completed]
    outcomes: dict[str, SubmitResult] = {}

    for item in items:
        if decisions.get(item.item_id) == ACTION_NEW_ROW:
            outcomes[item.item_id] = _save_new_row(plan, item, build_fields(item))
            if outcomes[item.item_id].transaction_id is not None:
                plan.completed[item.item_id] = outcomes[item.item_id]

    # รวมไฟล์ตามแถวปลายทาง: หลาย PR จากไฟล์เดียวที่แนบแถวเดียวกันจะแนบไฟล์นั้นครั้งเดียว
    items_by_target: dict[int, list[ReviewItem]] = {}
    for item in items:
        decision = decisions.get(item.item_id) or ""
        if decision.startswith(ACTION_ROW_PREFIX):
            items_by_target.setdefault(int(decision.removeprefix(ACTION_ROW_PREFIX)), []).append(item)
        elif decision.startswith(ACTION_BATCH_PREFIX):
            target = plan.completed.get(decision.removeprefix(ACTION_BATCH_PREFIX))
            if target is None or target.transaction_id is None:
                outcomes[item.item_id] = SubmitResult(error=f"{describe_item(item)}: สร้างแถว PR ปลายทางไม่สำเร็จ จึงยังไม่ได้แนบไฟล์")
            else:
                items_by_target.setdefault(target.transaction_id, []).append(item)

    for row_id, target_items in items_by_target.items():
        match = _load_attach_target(row_id)
        if match is None:
            for item in target_items:
                outcomes[item.item_id] = SubmitResult(error=f"{describe_item(item)}: ไม่พบแถว {row_id} หรือโฟลเดอร์ของแถวนั้น")
            continue
        file_indexes = list(dict.fromkeys(item.file_index for item in target_items))
        files = [(plan.files[index].name, plan.files[index].data) for index in file_indexes]
        result = attach_files_to_record(match, files)
        for item in target_items:
            outcomes[item.item_id] = result
            if result.transaction_id is not None:
                plan.completed[item.item_id] = result
    return outcomes
