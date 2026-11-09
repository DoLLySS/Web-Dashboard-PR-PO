"""ประมวลผลการอัปโหลดอัตโนมัติจากไฟล์ PR: สร้างแถวใหม่ หรือส่งไฟล์เข้าโฟลเดอร์ของ PR เดียวกัน ไม่ถามผู้ใช้

กติกา:
- ไฟล์ PR (Excel/PDF ที่เป็นฟอร์ม PR หรือชื่อมีคำว่า PR) ประมวลผลก่อนไฟล์อื่น
- PR เดียวกัน = Description + Company + Tel ตรงกันทั้ง 3 ช่อง (ดู utils/pr_reader.py) Excel กับ PDF จึงเข้าโฟลเดอร์เดียวกัน
  ตรงกับแถวเดิม (หรือแถวที่เพิ่งสร้างในชุดนี้) = แนบไฟล์เข้าแถว/โฟลเดอร์นั้น ไม่ตรง = สร้างแถวใหม่ทันที
- ช่องใดช่องหนึ่งอ่านไม่ได้ = ไม่รวมกับแถวเดิม สร้างแถวใหม่ พร้อมแจ้งเตือน (ไม่เดา)
- ไฟล์ที่ไม่ใช่ PR (ใบเสนอราคา ใบกำกับภาษี ฯลฯ) จับคู่กับ PR จากเนื้อหาไฟล์ ไม่เจอหรือกำกวม = ไม่บันทึกไฟล์นั้นและแจ้งเหตุผล
- รายการหนึ่งล้มเหลวไม่ย้อนรายการอื่น

ไฟล์นี้ไม่เรียก Streamlit
"""

import io
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Optional

from data.database import STATUS_PENDING, get_transaction, get_transactions_with_identity_fields, mark_invoice_received
from utils.pr_reader import (
    PrDocument,
    PdfSection,
    _skeleton,
    build_identity_key,
    read_pdf_sections,
    read_pr_excel,
)
from utils.storage_backend import PR_TOKEN_PATTERN, UNKNOWN_VENDOR_FOLDER
from utils.submit_pipeline import (
    FolderMatch,
    FolderProfileCache,
    RecordFields,
    SubmitResult,
    attach_files_to_record,
    find_pr_folder_candidates,
    match_document_to_pr,
    resolve_row_folder,
    submit_record,
)
from utils.text_extractor import extract_text_from_file

KIND_CREATED: str = "created"
KIND_ATTACHED: str = "attached"
KIND_BLOCKED: str = "blocked"

PDF_SUFFIX: str = ".pdf"
EXCEL_SUFFIX: str = ".xlsx"

BLOCKED_NO_MATCH_REASON: str = (
    "ไม่พบ PR ที่ตรงกับไฟล์นี้ (หรือตรงหลายรายการจนตัดสินไม่ได้) จึงไม่ได้บันทึก "
    "กรุณาอัปโหลดไฟล์ PR (Excel หรือ PDF) ของงานนี้ก่อนหรือพร้อมกัน"
)
UNREADABLE_FILE_REASON: str = (
    "อ่านข้อความในไฟล์ไม่ได้ (ไฟล์สแกนหรือรูปภาพ) จึงจับคู่กับ PR อัตโนมัติไม่ได้และไม่ได้บันทึก "
    "ระบบยังไม่รองรับการอ่านไฟล์สแกน (OCR) ตั้งชื่อไฟล์ให้มีชื่อรุ่นตามรายการใน PR (เช่น Dell U2724DE) แล้วอัปโหลดใหม่"
)
TAX_INVOICE_KEYWORDS: tuple[str, ...] = ("ใบกำกับภาษี", "Tax Invoice")  # เทียบแบบไม่สนช่องว่าง/ตัวพิมพ์/สระ
TAX_INVOICE_STATUS_WARNING: str = "พบใบกำกับภาษี: เปลี่ยนสถานะของแถวนี้เป็น Completed แล้ว"
INFERRED_INVOICE_STATUS_WARNING: str = (
    "ไม่พบคำว่าใบกำกับภาษีในไฟล์ แต่ไฟล์ตรงกับ PR และไม่ใช่เอกสารอื่น จึงถือเป็นใบกำกับและเปลี่ยนสถานะของแถวนี้เป็น Completed แล้ว "
    "ถ้าไม่ใช่ใบกำกับ ให้แก้สถานะกลับเป็น Pending ในตาราง"
)
# ไฟล์ที่จับคู่กับ PR ได้แต่ไม่มีคำว่าใบกำกับ ถือเป็นใบกำกับ ยกเว้นมีคำเหล่านี้ที่ชื่อไฟล์หรือหัวเอกสาร (เทียบแบบไม่สนช่องว่าง/ตัวพิมพ์/สระ)
NON_INVOICE_KEYWORDS: tuple[str, ...] = (
    "ใบเสนอราคา",
    "Quotation",
    "คู่เทียบ",
    "เปรียบเทียบ",
    "Comparison",
    "ใบสั่งซื้อ",
    "Purchase Order",
)
NON_INVOICE_NAME_WORD_PATTERN: re.Pattern[str] = re.compile(r"(?<![a-z0-9])(?:po|quote)(?![a-z0-9])", re.IGNORECASE)  # คำสั้น เทียบเฉพาะคำเต็มในชื่อไฟล์
DOCUMENT_HEADER_LENGTH: int = 400  # ดูเฉพาะหัวเอกสาร เพราะใบกำกับจริงอาจอ้างถึง "ใบสั่งซื้อ" ในเนื้อหา
INVOICE_CHOOSE_ROW_REASON: str = "ระบบจับคู่ใบกำกับภาษีนี้กับแถวเองไม่ได้ ยังไม่ได้บันทึก กรุณาเลือกแถวที่จะแนบ"
UNREADABLE_PR_WARNING: str = "อ่านค่าจากไฟล์ PR ไม่ได้ (เช่น ไฟล์สแกน) ต้องกรอก/แก้ค่าในตารางเอง"


@dataclass
class ItemOutcome:
    """ผลของรายการ 1 รายการ: PR 1 ใบ หรือไฟล์ที่ไม่ใช่ PR 1 ไฟล์"""

    kind: str  # KIND_CREATED / KIND_ATTACHED / KIND_BLOCKED
    file_name: str
    label: str  # ชื่อที่แสดงในสรุป (Description หรือชื่อไฟล์)
    result: Optional[SubmitResult] = None
    reason: str = ""  # เหตุผลที่ไม่บันทึก หรือข้อผิดพลาด
    warnings: list[str] = field(default_factory=list)
    needs_row_choice: bool = False  # ใบกำกับภาษีที่จับคู่แถวเองไม่ได้ ให้ผู้ใช้เลือกแถว (ใช้ data ที่เก็บไว้)
    data: bytes = b""  # เนื้อไฟล์ (เก็บเฉพาะกรณี needs_row_choice)


@dataclass
class UploadReport:
    """ผลของการอัปโหลดทั้งชุด"""

    items: list[ItemOutcome] = field(default_factory=list)

    def of_kind(self, kind: str) -> list[ItemOutcome]:
        return [item for item in self.items if item.kind == kind]

    @property
    def results(self) -> list[SubmitResult]:
        """ผลของทุกรายการที่บันทึกลงฐานข้อมูลสำเร็จ (ไฟล์หลายไฟล์ของแถวเดียวกันมีผลแยกกัน)"""
        return [item.result for item in self.items if item.result is not None and item.result.transaction_id is not None]

    @property
    def saved_results(self) -> list[SubmitResult]:
        """ผลต่อแถวที่บันทึก (แถวละ 1 ผล ใช้ผลแรกที่เกิดกับแถวนั้น คือผลการสร้างแถว) ใช้แจ้งเตือนแถวนอกช่วงวันที่"""
        unique: dict[int, SubmitResult] = {}
        for result in self.results:
            unique.setdefault(int(result.transaction_id), result)
        return list(unique.values())


@dataclass
class _PrUnit:
    """PR 1 ใบที่พบในไฟล์ที่อัปโหลด"""

    file_name: str
    data: bytes
    document: Optional[PrDocument]  # None = อ่านค่าไม่ได้


def _split_files(files: list[tuple[str, bytes]]) -> tuple[list[_PrUnit], list[tuple[str, bytes]]]:
    """แยกไฟล์ที่วางเป็น PR (1 ใบ/รายการ; PDF หลาย PR ได้หลายรายการ) กับไฟล์อื่น ตามลำดับที่วาง"""
    pr_units: list[_PrUnit] = []
    others: list[tuple[str, bytes]] = []
    for name, data in files:
        lowered = name.lower()
        has_pr_name = bool(PR_TOKEN_PATTERN.search(name))
        if lowered.endswith(PDF_SUFFIX):
            sections: list[PdfSection] = read_pdf_sections(data)
            forms = [section for section in sections if section.document is not None]
            if forms:
                pr_units.extend(_PrUnit(name, data, section.document) for section in forms)
            elif has_pr_name:
                pr_units.append(_PrUnit(name, data, None))
            else:
                others.append((name, data))
        elif lowered.endswith(EXCEL_SUFFIX):
            document = read_pr_excel(data)
            if document is not None or has_pr_name:
                pr_units.append(_PrUnit(name, data, document))
            else:
                others.append((name, data))
        elif has_pr_name:
            pr_units.append(_PrUnit(name, data, None))
        else:
            others.append((name, data))
    return pr_units, others


def _find_row_by_identity(key: tuple[str, str, str]) -> tuple[Optional[dict], int]:
    """แถวล่าสุดที่ Description + Company + Tel ตรงกัน และจำนวนแถวที่ตรงทั้งหมด"""
    matches = [
        row
        for row in get_transactions_with_identity_fields()
        if build_identity_key(row.get("description"), row.get("vendor"), row.get("tel")) == key
    ]
    return (matches[0] if matches else None), len(matches)


def _build_fields(
    document: PrDocument,
    file_name: str,
    category: str,
    invoice_status: str,
    describe_file: Callable[[str], str],
    date_from_name: Callable[[str], Optional[date]],
) -> RecordFields:
    """ฟิลด์ของแถวใหม่จากค่าใน PR: วันที่ = ช่องลายเซ็น ไม่มีใช้วันที่นำหน้าชื่อไฟล์ ไม่มีอีกใช้วันนี้"""
    row_date = document.date or (date_from_name(file_name) or date.today()).isoformat()
    return RecordFields(
        date=row_date,
        vendor=document.vendor or UNKNOWN_VENDOR_FOLDER,
        total_price=document.grand_total or document.unit_price or 0.0,  # ราคารวมหลังภาษี ไม่พบใช้ผลรวม Unit Price
        pr_run_no=document.pr_run_no or None,
        category=category,
        invoice_status=invoice_status,
        tel=document.tel or None,
        description=document.description or describe_file(file_name),
        unit_price=document.unit_price,
    )


def is_tax_invoice(name: str, text: str) -> bool:
    """ชื่อไฟล์หรือข้อความในไฟล์มีคำว่า "ใบกำกับภาษี" / "Tax Invoice" (PDF ไทยสะกดสระเพี้ยนได้ จึงเทียบแบบไม่สนสระ)"""
    haystack = _skeleton(f"{name}\n{text}")
    return any(_skeleton(keyword) in haystack for keyword in TAX_INVOICE_KEYWORDS)


def looks_like_other_document(name: str, text: str) -> bool:
    """ชื่อไฟล์หรือหัวเอกสารบอกว่าเป็นเอกสารอื่นที่ไม่ใช่ใบกำกับ เช่น ใบเสนอราคา คู่เทียบ ใบสั่งซื้อ"""
    if NON_INVOICE_NAME_WORD_PATTERN.search(name):
        return True
    haystack = _skeleton(f"{name}\n{text[:DOCUMENT_HEADER_LENGTH]}")
    return any(_skeleton(keyword) in haystack for keyword in NON_INVOICE_KEYWORDS)


def _attach_to_row(transaction: dict, file_name: str, data: bytes) -> SubmitResult:
    """แนบไฟล์เข้าแถวเดิม โดยอ่านแถวล่าสุดมาก่อน (รายการไฟล์ของแถวอาจเพิ่งเปลี่ยนในชุดเดียวกัน)"""
    fresh = get_transaction(int(transaction["id"])) or transaction
    folder_parts, _is_new = resolve_row_folder(fresh, [file_name])
    return attach_files_to_record(FolderMatch(fresh, folder_parts, 1), [(file_name, data)])


def _process_pr_unit(
    unit: _PrUnit,
    created_by_key: dict[tuple[str, str, str], int],
    category: str,
    invoice_status: str,
    describe_file: Callable[[str], str],
    date_from_name: Callable[[str], Optional[date]],
) -> ItemOutcome:
    document = unit.document or PrDocument()
    warnings: list[str] = []
    if unit.document is None:
        warnings.append(UNREADABLE_PR_WARNING)
    elif document.missing_key_fields:
        warnings.append(
            f"อ่านค่าไม่ได้: {', '.join(document.missing_key_fields)} จึงไม่รวมกับแถวเดิม (สร้างแถวใหม่) กรุณาตรวจค่าในตาราง"
        )
    if unit.document is not None and not document.date:
        warnings.append("อ่านวันที่จากช่องลายเซ็นไม่ได้ ใช้วันที่จากชื่อไฟล์หรือวันนี้แทน")
    label = document.description or describe_file(unit.file_name)

    key = document.identity_key
    target: Optional[dict] = None
    if key is not None:
        if key in created_by_key:
            target = get_transaction(created_by_key[key])
        else:
            target, match_count = _find_row_by_identity(key)
            if match_count > 1:
                warnings.append(f"พบ {match_count} แถวที่ตรงกัน จึงใช้แถวล่าสุด (รหัสรายการ {target['id']})")

    if target is not None:
        result = _attach_to_row(target, unit.file_name, unit.data)
        if result.transaction_id is None:
            return ItemOutcome(KIND_BLOCKED, unit.file_name, label, result, result.error or "แนบไฟล์ไม่สำเร็จ", warnings)
        return ItemOutcome(KIND_ATTACHED, unit.file_name, label, result, warnings=warnings)

    fields = _build_fields(document, unit.file_name, category, invoice_status, describe_file, date_from_name)
    result = submit_record(fields, [(unit.file_name, unit.data)])
    if result.transaction_id is None:
        return ItemOutcome(KIND_BLOCKED, unit.file_name, label, result, result.error or "สร้างแถวไม่สำเร็จ", warnings)
    if key is not None:
        created_by_key[key] = result.transaction_id
    return ItemOutcome(KIND_CREATED, unit.file_name, label, result, warnings=warnings)


def _row_candidates(touched_ids: list[int]) -> list[FolderMatch]:
    """แถว PR ที่ไฟล์อื่นจะแนบได้: แถวที่มีไฟล์ PR ในโฟลเดอร์ + แถวที่เพิ่งสร้าง/แนบในชุดนี้ (แม้ชื่อไฟล์ไม่มีคำว่า PR)"""
    candidates = find_pr_folder_candidates()
    known = {int(item.transaction["id"]) for item in candidates}
    for row_id in touched_ids:
        if row_id in known:
            continue
        transaction = get_transaction(row_id)
        if transaction is None:
            continue
        folder_parts, _is_new = resolve_row_folder(transaction, [])
        candidates.append(FolderMatch(transaction, folder_parts, 1))
        known.add(row_id)
    return candidates


def _process_other_file(
    name: str, data: bytes, candidates: list[FolderMatch], profiles: FolderProfileCache
) -> ItemOutcome:
    text = extract_text_from_file(io.BytesIO(data), name)
    # รวมชื่อไฟล์ด้วย เพราะไฟล์สแกนอาจมีคำจาก Description เฉพาะในชื่อไฟล์
    match = match_document_to_pr(f"{name}\n{text}", candidates, profiles)
    named_invoice = is_tax_invoice(name, text)
    if match is None:
        reason = BLOCKED_NO_MATCH_REASON if text.strip() else UNREADABLE_FILE_REASON
        if named_invoice:
            return ItemOutcome(KIND_BLOCKED, name, name, reason=INVOICE_CHOOSE_ROW_REASON, needs_row_choice=True, data=data)
        return ItemOutcome(KIND_BLOCKED, name, name, reason=reason)
    result = _attach_to_row(match.transaction, name, data)
    label = match.transaction.get("description") or name
    if result.transaction_id is None:
        return ItemOutcome(KIND_BLOCKED, name, label, result, result.error or "แนบไฟล์ไม่สำเร็จ")
    warnings = [f"จับคู่จากเนื้อหาไฟล์: {match.reason}"]
    # มีคำว่าใบกำกับ = ใบกำกับเสมอ; ไม่มีคำนี้แต่จับคู่กับ PR ได้ = ถือเป็นใบกำกับ ยกเว้นเอกสารอื่น
    if (named_invoice or not looks_like_other_document(name, text)) and _mark_received_if_pending(result.transaction_id):
        warnings.append(TAX_INVOICE_STATUS_WARNING if named_invoice else INFERRED_INVOICE_STATUS_WARNING)
    return ItemOutcome(KIND_ATTACHED, name, label, result, warnings=warnings)


def _mark_received_if_pending(transaction_id: int) -> bool:
    """เปลี่ยนแถวเป็น Completed ถ้ายังรอใบกำกับ (Pending/Overdue ในตารางคือ "รอใบกำกับภาษี" เหมือนกันในฐานข้อมูล) แถวที่ Completed อยู่แล้วไม่แตะ"""
    current = get_transaction(transaction_id)
    return current is not None and current.get("invoice_status") == STATUS_PENDING and mark_invoice_received(transaction_id)


def attach_invoice_to_row(transaction_id: int, name: str, data: bytes) -> ItemOutcome:
    """แนบใบกำกับภาษีเข้าแถวที่ผู้ใช้เลือกเอง (ใช้เมื่อจับคู่อัตโนมัติไม่ได้) แล้วเปลี่ยนแถวเป็น Completed"""
    transaction = get_transaction(transaction_id)
    if transaction is None:
        return ItemOutcome(KIND_BLOCKED, name, name, reason="ไม่พบแถวที่เลือก (อาจถูกลบไปแล้ว)")
    label = transaction.get("description") or name
    result = _attach_to_row(transaction, name, data)
    if result.transaction_id is None:
        return ItemOutcome(KIND_BLOCKED, name, label, result, result.error or "แนบไฟล์ไม่สำเร็จ")
    warnings = ["ผู้ใช้เลือกแถวเอง"]
    if _mark_received_if_pending(result.transaction_id):
        warnings.append(TAX_INVOICE_STATUS_WARNING)
    return ItemOutcome(KIND_ATTACHED, name, label, result, warnings=warnings)


def process_upload(
    files: list[tuple[str, bytes]],
    category: str,
    invoice_status: str,
    describe_file: Callable[[str], str],
    date_from_name: Callable[[str], Optional[date]],
) -> UploadReport:
    """อ่านไฟล์ PR แล้วสร้างแถว/จัดเข้าโฟลเดอร์ทันที จากนั้นจับคู่ไฟล์อื่นเข้า PR

    Args:
        files: ไฟล์ที่วาง (ชื่อไฟล์, เนื้อไฟล์)
        category: หมวดหมู่ (Item) ของแถวที่สร้างใหม่
        invoice_status: สถานะใบกำกับภาษีของแถวที่สร้างใหม่
        describe_file: แปลงชื่อไฟล์เป็น Description (ใช้เมื่ออ่าน Description จากไฟล์ไม่ได้)
        date_from_name: อ่านวันที่นำหน้าชื่อไฟล์ (ใช้เมื่ออ่านวันที่จากไฟล์ไม่ได้)

    Returns:
        ผลของทุกรายการ (บางรายการไม่สำเร็จได้ รายการอื่นยังบันทึกอยู่)
    """
    report = UploadReport()
    pr_units, others = _split_files(files)

    created_by_key: dict[tuple[str, str, str], int] = {}
    touched_ids: list[int] = []
    for unit in pr_units:
        outcome = _process_pr_unit(unit, created_by_key, category, invoice_status, describe_file, date_from_name)
        report.items.append(outcome)
        if outcome.result is not None and outcome.result.transaction_id is not None:
            touched_ids.append(outcome.result.transaction_id)

    if others:
        candidates = _row_candidates(touched_ids)
        profiles = FolderProfileCache()  # อ่านไฟล์ในโฟลเดอร์ของแต่ละ PR ครั้งเดียวต่อการอัปโหลด
        for name, data in others:
            outcome = _process_other_file(name, data, candidates, profiles)
            report.items.append(outcome)
    return report
