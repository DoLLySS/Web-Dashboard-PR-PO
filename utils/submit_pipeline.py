"""ขั้นตอนส่งข้อมูล 1 รายการออกไปทุกปลายทาง (ใช้ร่วมกันทั้งหน้า Upload และหน้ากรอกฟอร์ม)

ลำดับ: (1) เก็บไฟล์ในเครื่อง (+ สร้างโฟลเดอร์บน Desktop อัตโนมัติ ถ้าเปิด LOCAL_DESKTOP_EXPORT) (2) ส่งไฟล์ไปที่เก็บออนไลน์ตามโครง /ปี/เดือน/วัน/ชื่อไฟล์ PR/ (ปี/เดือน/วันตามวันที่ของไฟล์ PR) (3) บันทึกลงฐานข้อมูล = แสดงบนเว็บ
(4) ส่งเฉพาะฟิลด์ที่ Master-List ต้องการ — แต่ละขั้นล้มเหลวแยกกัน ขั้นที่พลาดไม่ทำให้ขั้นอื่นหาย และรายงานผลเป็นรายขั้น
ไฟล์นี้ไม่เรียก Streamlit
"""

import re
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from config.logging_setup import get_logger
from data.database import (
    STATUS_PENDING,
    add_transaction,
    find_transactions_for_folder,
    get_transactions_with_files,
    update_transaction,
)
from utils.local_storage import (
    DESKTOP_EXPORT_ENABLED,
    LocalStorageError,
    export_files_to_desktop,
    get_folder_parts_from_file_paths,
    list_stored_files,
    save_document_locally,
)
from utils.masterlist_client import build_masterlist_payload, send_to_masterlist
from utils.storage_backend import (
    PR_TOKEN_PATTERN,
    SIGNED_SUFFIX_PATTERN,
    StorageError,
    build_dated_folder_name,
    build_storage_folder_parts,
    sanitize_folder_name,
    get_storage_folder_url,
    is_storage_configured,
    upload_files_to_storage,
)
from utils.text_extractor import OWN_COMPANY_TAX_ID, extract_text_from_file, find_all_tax_ids

logger = get_logger(__name__)

FILE_PATH_SEPARATOR: str = "\n"  # ต้องตรงกับ FILE_PATH_SEPARATOR ใน pages_ui/overview.py

# การเทียบไฟล์กับ Description ของแถว PR: แยกเป็นคำแล้วนับว่าพบในไฟล์กี่คำ
DESCRIPTION_WORD_PATTERN: re.Pattern[str] = re.compile(r"[a-z0-9ก-๙]+")
DESCRIPTION_STOP_WORDS: frozenset[str] = frozenset({"และ", "เเละ", "ซื้อ", "นิ้ว", "รายการ"})  # คำทั่วไปที่ไม่ช่วยระบุ PR
MIN_MATCHED_DESCRIPTION_WORDS: int = 2  # ต้องพบอย่างน้อยกี่คำ (และต้องมากกว่าครึ่งของคำทั้งหมด)

# การเทียบไฟล์กับไฟล์อื่นในโฟลเดอร์ของ PR: นับเฉพาะ "คำเด่น" (อังกฤษ/ตัวเลขปนกัน ยาวพอ เช่น thinkpad, e14, p2725h)
DISTINCTIVE_WORD_PATTERN: re.Pattern[str] = re.compile(r"[a-z0-9]{3,}")
MIN_SHARED_FOLDER_WORDS: int = 3  # ต้องซ้ำกับไฟล์ในโฟลเดอร์อย่างน้อยกี่คำ (และมีรหัสรุ่นที่มีตัวเลขอย่างน้อย 1 คำ)
FOLDER_STOP_WORDS: frozenset[str] = frozenset(
    {
        "the", "and", "for", "ltd", "co", "com", "date", "page", "total", "amount", "price", "vat", "tax",
        "invoice", "quotation", "company", "limited", "thailand", "bangkok", "tel", "fax", "email", "unit",
        "item", "items", "description", "qty", "remark", "payment", "approved", "signed", "pdf", "xlsx",
    }
)  # fmt: skip


@dataclass
class RecordFields:
    """ฟิลด์ของรายการ 1 แถว (ชื่อตรงกับพารามิเตอร์ของ add_transaction)"""

    date: str
    vendor: str
    total_price: float = 0.0
    tax_id: Optional[str] = None
    po_no: Optional[str] = None
    pr_run_no: Optional[str] = None
    category: Optional[str] = None
    invoice_status: str = STATUS_PENDING
    tel: Optional[str] = None
    email: Optional[str] = None
    contact_name: Optional[str] = None
    sharepoint_url: Optional[str] = None
    pr_request_date: Optional[str] = None
    qt_no: Optional[str] = None
    description: Optional[str] = None
    unit_price: Optional[float] = None


@dataclass
class SubmitResult:
    """ผลการส่งรายการ: transaction_id เป็น None = ไม่ได้บันทึกลงฐานข้อมูล (ดู error)"""

    transaction_id: Optional[int] = None
    error: str = ""  # ข้อผิดพลาดที่ทำให้บันทึกรายการไม่ได้
    storage_status: str = "none"  # "none" ไม่มีไฟล์ / "skipped" ยังไม่ตั้งค่าปลายทาง / "ok" / "error"
    storage_message: str = ""
    storage_links: list[str] = field(default_factory=list)
    masterlist_sent: bool = False
    masterlist_message: str = ""
    desktop_folder: str = ""  # โฟลเดอร์บน Desktop ที่สร้างให้ (ว่าง = ไม่ได้เปิดโหมด Desktop / ไม่มีไฟล์ / สร้างไม่สำเร็จ)
    desktop_message: str = ""  # ข้อความเตือนเมื่อสร้างโฟลเดอร์บน Desktop ไม่สำเร็จ
    existing_folder: str = ""  # โฟลเดอร์เดิมที่เก็บไฟล์ครั้งนี้ (ว่าง = ใช้โฟลเดอร์ที่ตั้งจากไฟล์ชุดนี้)
    attached_to_existing: bool = False  # True = เพิ่มไฟล์เข้าแถวเดิม ไม่ได้สร้างแถวใหม่
    attached_file_names: list[str] = field(default_factory=list)  # ไฟล์ใหม่ที่เพิ่มเข้าแถวเดิม (ว่าง = ทุกไฟล์มีอยู่แล้ว)
    record_date: str = ""  # วันที่ของแถว (คอลัมน์ Date ที่ใช้กับ Date Filter)


@dataclass
class StoredFiles:
    """ไฟล์ของรายการใหม่ที่เก็บแล้ว ใช้สร้างได้หลายแถวโดยไม่เก็บหรือส่งไฟล์ซ้ำ"""

    local_paths: Optional[list[str]]  # None = เก็บในเครื่องไม่สำเร็จ (ดู template.error)
    template: SubmitResult  # ผลของขั้นเก็บไฟล์ที่ทุกแถวใช้ร่วมกัน


@dataclass
class FolderMatch:
    """รายการเดิมที่จับคู่ได้ และโฟลเดอร์ที่ไฟล์ของรายการนั้นอยู่จริง"""

    transaction: dict[str, Any]
    folder_parts: list[str]
    match_count: int  # จำนวนรายการที่ตรงทั้งหมด (มากกว่า 1 = เลือกรายการล่าสุดที่ยังมีโฟลเดอร์)
    reason: str = ""  # เหตุผลที่จับคู่ได้ (แสดงให้ผู้ใช้ดูก่อนยืนยัน)


def find_existing_folder(description: Optional[str], tax_id: Optional[str]) -> Optional[FolderMatch]:
    """หาโฟลเดอร์ของรายการเดิมจาก Description (ไฟล์ PR) หรือ Tax ID (ไฟล์อื่น) คืน None ถ้าไม่เจอ"""
    matches = find_transactions_for_folder(description, tax_id)
    for transaction in matches:
        folder_parts = get_folder_parts_from_file_paths(transaction.get("file_path"))
        if folder_parts:
            return FolderMatch(transaction, folder_parts, len(matches))
    return None


def find_pr_folder_candidates() -> list[FolderMatch]:
    """หาแถวที่มีไฟล์ PR และมีโฟลเดอร์จริง เรียงจากล่าสุดไปเก่าสุด (แถวที่ไม่มีไฟล์ PR ไม่ถูกจับคู่)"""
    candidates: list[FolderMatch] = []
    for transaction in get_transactions_with_files():
        file_paths = transaction.get("file_path") or ""
        has_pr_file = any(
            PR_TOKEN_PATTERN.search(Path(path.strip()).name) for path in file_paths.split(FILE_PATH_SEPARATOR)
        )
        folder_parts = get_folder_parts_from_file_paths(file_paths)
        if has_pr_file and folder_parts:
            candidates.append(FolderMatch(transaction, folder_parts, 1))
    return candidates


def _normalize_description(description: Optional[str]) -> str:
    """ทำ Description ให้เทียบกันได้: ไม่สนตัวพิมพ์ และถือว่า _ กับช่องว่างเหมือนกัน"""
    return re.sub(r"[\s_]+", " ", description or "").strip().lower()


def find_pr_folder_by_description(description: Optional[str], candidates: list[FolderMatch]) -> Optional[FolderMatch]:
    """หาแถว PR ที่ Description ตรงกับ Description จากชื่อไฟล์ PR ทั้งข้อความ คืนแถวล่าสุด หรือ None ถ้าไม่เจอ"""
    wanted = _normalize_description(description)
    matches = [
        item for item in candidates if wanted and _normalize_description(item.transaction.get("description")) == wanted
    ]
    if not matches:
        return None
    return FolderMatch(matches[0].transaction, matches[0].folder_parts, len(matches))


def _find_best_description_match(text: str, candidates: list[FolderMatch]) -> Optional[FolderMatch]:
    """หาแถวที่พบคำจาก Description ในไฟล์มากที่สุด คืน None ถ้าไม่ถึงเกณฑ์ หรือคะแนนสูงสุดเท่ากันหลายแถว"""
    document_words = set(DESCRIPTION_WORD_PATTERN.findall(text.lower()))
    scored: list[tuple[float, FolderMatch]] = []
    for candidate in candidates:
        description = (candidate.transaction.get("description") or "").lower()
        words = set(DESCRIPTION_WORD_PATTERN.findall(description)) - DESCRIPTION_STOP_WORDS
        matched_count = len(words & document_words)
        if matched_count >= MIN_MATCHED_DESCRIPTION_WORDS and matched_count * 2 > len(words):
            scored.append((matched_count / len(words), candidate))
    if not scored:
        return None
    best_score = max(score for score, _ in scored)
    best = [candidate for score, candidate in scored if score == best_score]
    return best[0] if len(best) == 1 else None


@dataclass
class FolderProfile:
    """ข้อมูลที่ใช้เทียบของแถว PR: Tax ID และคำเด่นที่พบในทุกไฟล์ของโฟลเดอร์ (ไม่ใช่แค่ไฟล์ PR)"""

    tax_ids: set[str]
    words: set[str]


class FolderProfileCache:
    """สร้าง FolderProfile ของแต่ละแถวเมื่อต้องใช้ แล้วจำไว้ตลอดการ Upload ครั้งเดียว (ไม่อ่านไฟล์ซ้ำ)"""

    def __init__(self) -> None:
        self._profiles: dict[Any, FolderProfile] = {}

    def get(self, candidate: FolderMatch) -> FolderProfile:
        """โปรไฟล์ของแถว: ไฟล์ที่อ่านไม่ได้ (เช่น รูปภาพ หรือไฟล์หาย) ถูกข้าม ไม่ทำให้ล้ม"""
        key = candidate.transaction.get("id")
        if key not in self._profiles:
            self._profiles[key] = self._build(candidate)
        return self._profiles[key]

    @staticmethod
    def _build(candidate: FolderMatch) -> FolderProfile:
        row_tax_id = (candidate.transaction.get("tax_id") or "").strip()
        tax_ids = {row_tax_id} if row_tax_id else set()
        words: set[str] = set()
        for path in list_stored_files(candidate.transaction.get("file_path")):
            text = extract_text_from_file(path, path.name)
            tax_ids.update(find_all_tax_ids(text))
            words.update(_distinctive_words(f"{path.name}\n{text}"))
        return FolderProfile(tax_ids - {OWN_COMPANY_TAX_ID}, words)


def _distinctive_words(text: str) -> set[str]:
    """คำเด่นในข้อความ: อังกฤษ/ตัวเลขปนกันยาว ≥3 ตัว มีตัวอักษรอย่างน้อย 1 ตัว ไม่ใช่คำทั่วไป (กันเลขราคา/คำสามัญ)"""
    return {
        word
        for word in DISTINCTIVE_WORD_PATTERN.findall(text.lower())
        if not word.isdigit() and word not in FOLDER_STOP_WORDS
    }


def _find_best_folder_match(
    text: str, candidates: list[FolderMatch], profiles: FolderProfileCache
) -> Optional[FolderMatch]:
    """หาแถวที่คำเด่นในไฟล์ซ้ำกับไฟล์ในโฟลเดอร์มากที่สุด คืน None ถ้าไม่ถึงเกณฑ์ หรือคะแนนสูงสุดเท่ากันหลายแถว"""
    document_words = _distinctive_words(text)
    scored: list[tuple[int, FolderMatch]] = []
    for item in candidates:
        shared = document_words & profiles.get(item).words
        # ต้องมีคำที่เป็นรหัสรุ่น (มีตัวเลข เช่น e14, 16gb) อย่างน้อย 1 คำ กันเอกสารที่ซ้ำกันแค่คำอังกฤษทั่วไป
        if len(shared) >= MIN_SHARED_FOLDER_WORDS and any(any(c.isdigit() for c in word) for word in shared):
            scored.append((len(shared), item))
    if not scored:
        return None
    best_score = max(score for score, _ in scored)
    best = [item for score, item in scored if score == best_score]
    return best[0] if len(best) == 1 else None


def match_document_to_pr(
    text: str, candidates: list[FolderMatch], profiles: Optional[FolderProfileCache] = None
) -> Optional[FolderMatch]:
    """หาแถว PR ที่แนะนำสำหรับไฟล์ที่ไม่ใช่ PR ผลนี้เป็นเพียงคำแนะนำ ผู้ใช้ต้องยืนยันก่อนบันทึก

    ลำดับ: Tax ID ของแถว (ไม่นับเลขบริษัทเรา) -> Description ของแถว -> Tax ID ที่พบในไฟล์ของโฟลเดอร์
    -> คำเด่นที่ซ้ำกับไฟล์ในโฟลเดอร์ สองขั้นหลังต้องอ่านไฟล์ จึงทำเมื่อขั้นก่อนหน้าตัดสินไม่ได้เท่านั้น

    Args:
        text: ข้อความในไฟล์รวมกับชื่อไฟล์
        candidates: แถว PR (ได้จาก find_pr_folder_candidates)
        profiles: ตัวจำโปรไฟล์โฟลเดอร์ (ไม่ส่ง = สร้างใหม่สำหรับการเรียกนี้)

    Returns:
        แถวที่ตรงแถวเดียวพร้อมเหตุผล หรือ None ถ้าไม่พบ / ตัดสินไม่ได้
    """
    profiles = profiles or FolderProfileCache()
    tax_ids = set(find_all_tax_ids(text)) - {OWN_COMPANY_TAX_ID}

    row_matches = [item for item in candidates if (item.transaction.get("tax_id") or "").strip() in tax_ids]
    if len(row_matches) == 1:
        return replace(row_matches[0], reason="Tax ID ตรงกับแถวนี้")
    pool = row_matches or candidates

    description_match = _find_best_description_match(text, pool)
    if description_match:
        return replace(description_match, reason="คำในเอกสารตรงกับ Description ของแถวนี้")

    # Tax ID ในโฟลเดอร์อาจเป็นของผู้ขายคู่เทียบ จึงแยกเหตุผลให้ผู้ใช้เห็น (ไม่เทียบซ้ำถ้าแถวมี Tax ID ตรงอยู่แล้ว)
    if tax_ids and not row_matches:
        folder_matches = [item for item in pool if tax_ids & profiles.get(item).tax_ids]
        if len(folder_matches) == 1:
            return replace(folder_matches[0], reason="Tax ID ตรงกับไฟล์ในโฟลเดอร์นี้ (อาจเป็นใบเสนอราคาคู่เทียบ)")
        pool = folder_matches or pool

    folder_match = _find_best_folder_match(text, pool, profiles)
    return replace(folder_match, reason="คำเด่นตรงกับไฟล์ในโฟลเดอร์นี้") if folder_match else None


def _store_files(
    files: list[tuple[str, bytes]],
    folder_parts: list[str],
    when: datetime,
    result: SubmitResult,
    known_paths: Optional[list[str]] = None,
) -> Optional[list[str]]:
    """เก็บไฟล์ในเครื่อง + Desktop + ที่เก็บออนไลน์ (ผลของแต่ละขั้นบันทึกลง result)

    Args:
        files: ไฟล์แนบ (ชื่อไฟล์, เนื้อไฟล์) ว่างได้
        folder_parts: โครงโฟลเดอร์ปลายทาง
        when: วันที่สำรองของไฟล์เก่าที่ไม่มีโฟลเดอร์ย่อย
        result: ผลการส่งที่จะเขียนสถานะของแต่ละขั้นลงไป
        known_paths: ที่อยู่ไฟล์ที่รายการมีอยู่แล้ว (ไม่ส่งซ้ำ)

    Returns:
        ที่อยู่ไฟล์ใหม่ในเครื่อง หรือ None ถ้าเก็บในเครื่องไม่สำเร็จ (ดู result.error)
    """
    # (1) เก็บไฟล์ในเครื่อง: ถ้าพลาดไม่บันทึกรายการ เพื่อไม่ให้ไฟล์หายไปเงียบๆ
    # ไฟล์ทุกไฟล์ในการส่งครั้งนี้รวมอยู่โฟลเดอร์เดียว ปี/เดือน/วัน/ชื่อไฟล์ PR (โครงเดียวกับที่เก็บออนไลน์)
    local_paths: list[str] = []
    new_files: list[tuple[str, bytes]] = []
    try:
        for file_name, file_bytes in files:
            local_path = save_document_locally(file_bytes, file_name, folder_parts)
            if local_path not in (known_paths or []) and local_path not in local_paths:
                local_paths.append(local_path)
                new_files.append((file_name, file_bytes))
    except LocalStorageError as error:
        result.error = str(error)
        return None

    # (1.1) โหมดทดสอบบนเครื่องตัวเอง: สร้างโฟลเดอร์บน Desktop + คัดลอกไฟล์ทันทีที่ Upload (พลาดไม่ทำให้ขั้นอื่นล้ม)
    if DESKTOP_EXPORT_ENABLED and local_paths:
        try:
            result.desktop_folder = str(export_files_to_desktop(FILE_PATH_SEPARATOR.join(local_paths), when))
        except LocalStorageError as error:
            logger.error("สร้างโฟลเดอร์บน Desktop ไม่สำเร็จ: %s", type(error).__name__)
            result.desktop_message = str(error)

    # (2) ส่งไฟล์ไปที่เก็บออนไลน์ (ยังไม่ตั้งค่า = ข้าม ไม่ถือเป็น error)
    if new_files and not is_storage_configured():
        result.storage_status = "skipped"
        result.storage_message = "ยังไม่ได้ตั้งค่าที่เก็บไฟล์ออนไลน์ (ดู NEXT_STEPS.md) ไฟล์เก็บในเครื่องแล้ว"
    elif new_files:
        try:
            result.storage_links = upload_files_to_storage(new_files, folder_parts)
            folder_url = get_storage_folder_url(folder_parts)  # SharePoint: ลิงก์ไปโฟลเดอร์ของไฟล์ PR
            if folder_url:
                result.storage_links.insert(0, folder_url)
            result.storage_status = "ok"
        except StorageError as error:
            logger.error("ส่งไฟล์ไปที่เก็บออนไลน์ไม่สำเร็จ: %s", type(error).__name__)
            result.storage_status = "error"
            result.storage_message = str(error)
    return local_paths


def _parse_row_date(transaction: dict[str, Any]) -> datetime:
    """วันที่ของ PR ของแถว: pr_request_date ก่อน ไม่มีหรืออ่านไม่ได้ใช้ date (ไม่ใช่วันอัปโหลด)"""
    for key in ("pr_request_date", "date"):
        try:
            return datetime.fromisoformat(f"{str(transaction.get(key) or '').strip()[:10]}T00:00:00")
        except ValueError:
            continue
    return datetime.now()


def resolve_row_folder(transaction: dict[str, Any], file_names: list[str]) -> tuple[list[str], bool]:
    """โฟลเดอร์ที่ไฟล์ของแถว PR ต้องอยู่ ไฟล์ทั้งหมดของแถวอยู่โฟลเดอร์เดียว

    แถวที่มีโฟลเดอร์แล้วใช้โฟลเดอร์เดิม แถวที่ยังไม่มี (เช่น มาจาก Excel) ตั้งตามวันที่ PR ของแถว:
    ปี/เดือน/วัน/YYYYMMDD_<ชื่อไฟล์ PR ตัดคำว่า PR> ถ้าชุดที่อัปโหลดไม่มีไฟล์ PR ใช้ YYYYMMDD_<เลข PR ของแถว> แทน

    Args:
        transaction: แถวปลายทาง
        file_names: ชื่อไฟล์ที่กำลังอัปโหลด

    Returns:
        (โครงโฟลเดอร์, True ถ้าเป็นโฟลเดอร์ใหม่ที่ยังไม่มีในแถว)
    """
    existing = get_folder_parts_from_file_paths(transaction.get("file_path"))
    if existing:
        return existing, False
    when = _parse_row_date(transaction)
    has_pr_file = any(
        PR_TOKEN_PATTERN.search(name) or SIGNED_SUFFIX_PATTERN.search(name.rsplit(".", 1)[0]) for name in file_names
    )
    if has_pr_file:
        folder_name = build_dated_folder_name(when, file_names)
    else:
        pr_no = str(transaction.get("pr_run_no") or "").strip()
        folder_name = sanitize_folder_name(f"{when:%Y%m%d}_{pr_no}" if pr_no else f"{when:%Y%m%d}")
    return build_storage_folder_parts(when, folder_name), True


def attach_files_to_record(match: FolderMatch, files: list[tuple[str, bytes]]) -> SubmitResult:
    """เพิ่มไฟล์เข้ารายการเดิมและโฟลเดอร์เดิม: ไม่สร้างแถวใหม่ ไม่แก้ข้อมูลอื่นในแถว ไม่ส่ง Master-List ซ้ำ

    Args:
        match: รายการเดิมและโฟลเดอร์ (ได้จาก find_existing_folder)
        files: ไฟล์แนบ (ชื่อไฟล์, เนื้อไฟล์)
    """
    transaction = match.transaction
    result = SubmitResult(
        attached_to_existing=True,
        existing_folder="/".join(match.folder_parts),
        record_date=str(transaction.get("date") or ""),
    )
    known_paths = [
        path.strip() for path in (transaction.get("file_path") or "").split(FILE_PATH_SEPARATOR) if path.strip()
    ]
    new_paths = _store_files(files, match.folder_parts, datetime.now(), result, known_paths)
    if new_paths is None:
        return result
    result.attached_file_names = [Path(path).name for path in new_paths]
    if new_paths:
        updates: dict[str, str] = {"file_path": FILE_PATH_SEPARATOR.join([*known_paths, *new_paths])}
        if not transaction.get("sharepoint_url") and result.storage_links:
            updates["sharepoint_url"] = result.storage_links[0]
        if not update_transaction(int(transaction["id"]), **updates):
            result.error = "บันทึกไฟล์ใหม่เข้ารายการเดิมไม่สำเร็จ"  # update_transaction แสดงรายละเอียดให้แล้ว
            return result
    result.transaction_id = int(transaction["id"])
    return result


def store_files_for_new_record(
    fields: RecordFields,
    files: list[tuple[str, bytes]],
    when: Optional[datetime] = None,
    existing_folder_parts: Optional[list[str]] = None,
) -> StoredFiles:
    """เก็บไฟล์ของรายการใหม่ในเครื่องและที่เก็บออนไลน์ ยังไม่บันทึกแถวลงฐานข้อมูล

    Args:
        fields: ฟิลด์ของรายการ (ใช้ fields.date ตั้งโฟลเดอร์)
        files: ไฟล์แนบ (ชื่อไฟล์, เนื้อไฟล์) ว่างได้
        when: วันที่สำรองสำหรับตั้งชื่อโฟลเดอร์ ปี/เดือน/วัน (ค่าเริ่มต้น = ตอนนี้) ใช้เมื่อ fields.date อ่านเป็นวันที่ไม่ได้
            ปกติโฟลเดอร์ตั้งตามวันที่ของไฟล์ PR (fields.date)
        existing_folder_parts: โฟลเดอร์ของรายการเดิมที่จะเก็บไฟล์ร่วมกัน (ไม่ระบุ = ตั้งโฟลเดอร์จากไฟล์ชุดนี้)

    Returns:
        ที่อยู่ไฟล์และผลของขั้นเก็บไฟล์ (local_paths เป็น None = เก็บในเครื่องไม่สำเร็จ)
    """
    when = when or datetime.now()
    template = SubmitResult()
    # โฟลเดอร์ ปี/เดือน/วัน ตามวันที่ของไฟล์ PR (fields.date) ไม่ใช่วันที่ Upload (แปลงไม่ได้ = ใช้ when)
    try:
        when = datetime.fromisoformat(f"{fields.date}T00:00:00")
    except ValueError:
        pass

    if existing_folder_parts:
        template.existing_folder = "/".join(existing_folder_parts)
    folder_parts = existing_folder_parts or build_storage_folder_parts(
        when, build_dated_folder_name(when, [name for name, _ in files])
    )
    return StoredFiles(_store_files(files, folder_parts, when, template), template)


def add_record_from_stored_files(fields: RecordFields, stored: StoredFiles) -> SubmitResult:
    """สร้าง 1 แถวจากไฟล์ที่เก็บแล้ว หลายแถวเรียกซ้ำด้วย stored เดียวกันได้ โดยไฟล์ไม่ถูกเก็บหรือส่งซ้ำ

    Args:
        fields: ฟิลด์ของรายการ
        stored: ผลจาก store_files_for_new_record

    Returns:
        ผลการบันทึกของแถวนี้
    """
    result = replace(stored.template, storage_links=list(stored.template.storage_links), record_date=fields.date)
    if stored.local_paths is None:
        return result

    # (3) บันทึกลงฐานข้อมูล -> ขึ้นตารางบนเว็บ (ลิงก์ที่กรอกเองมาก่อน ไม่มีก็ใช้ลิงก์ไฟล์แรกที่ส่งขึ้น)
    record = asdict(fields)
    record["sharepoint_url"] = fields.sharepoint_url or (result.storage_links[0] if result.storage_links else None)
    new_id = add_transaction(**record, file_path=FILE_PATH_SEPARATOR.join(stored.local_paths) or None)
    if new_id is None:
        result.error = "บันทึกรายการลงฐานข้อมูลไม่สำเร็จ"  # add_transaction แสดงรายละเอียดให้แล้ว
        return result
    result.transaction_id = new_id

    # (4) Master-List: เฉพาะฟิลด์ที่ต้องการ ไม่ส่งไฟล์
    result.masterlist_sent, message = send_to_masterlist(build_masterlist_payload(record))
    result.masterlist_message = message or ""
    return result


def submit_record(
    fields: RecordFields,
    files: list[tuple[str, bytes]],
    when: Optional[datetime] = None,
    existing_folder_parts: Optional[list[str]] = None,
) -> SubmitResult:
    """ส่งรายการเดียวออกทุกปลายทาง

    Args:
        fields: ฟิลด์ของรายการ
        files: ไฟล์แนบ (ชื่อไฟล์, เนื้อไฟล์) ว่างได้
        when: ดู store_files_for_new_record
        existing_folder_parts: ดู store_files_for_new_record
    """
    return add_record_from_stored_files(fields, store_files_for_new_record(fields, files, when, existing_folder_parts))
