"""ขั้นตอนส่งข้อมูล 1 รายการออกไปทุกปลายทาง (ใช้ร่วมกันทั้งหน้า Upload และหน้ากรอกฟอร์ม)

ลำดับ: (1) เก็บไฟล์ในเครื่อง (+ สร้างโฟลเดอร์บน Desktop อัตโนมัติ ถ้าเปิด LOCAL_DESKTOP_EXPORT) (2) ส่งไฟล์ไปที่เก็บออนไลน์ตามโครง /ปี/เดือน/วัน/ชื่อไฟล์ PR/ (ปี/เดือน/วันตามวันที่ของไฟล์ PR) (3) บันทึกลงฐานข้อมูล = แสดงบนเว็บ
(4) ส่งเฉพาะฟิลด์ที่ Master-List ต้องการ — แต่ละขั้นล้มเหลวแยกกัน ขั้นที่พลาดไม่ทำให้ขั้นอื่นหาย และรายงานผลเป็นรายขั้น
ไฟล์นี้ไม่เรียก Streamlit
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Optional

from config.logging_setup import get_logger
from data.database import STATUS_PENDING, add_transaction
from utils.local_storage import (
    DESKTOP_EXPORT_ENABLED,
    LocalStorageError,
    export_files_to_desktop,
    save_document_locally,
)
from utils.masterlist_client import build_masterlist_payload, send_to_masterlist
from utils.storage_backend import (
    StorageError,
    build_folder_name_from_files,
    build_storage_folder_parts,
    get_storage_folder_url,
    is_storage_configured,
    upload_files_to_storage,
)

logger = get_logger(__name__)

FILE_PATH_SEPARATOR: str = "\n"  # ต้องตรงกับ FILE_PATH_SEPARATOR ใน pages_ui/overview.py


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


def submit_record(
    fields: RecordFields,
    files: list[tuple[str, bytes]],
    when: Optional[datetime] = None,
) -> SubmitResult:
    """ส่งรายการเดียวออกทุกปลายทาง

    Args:
        fields: ฟิลด์ของรายการ
        files: ไฟล์แนบ (ชื่อไฟล์, เนื้อไฟล์) ว่างได้
        when: วันที่สำรองสำหรับตั้งชื่อโฟลเดอร์ ปี/เดือน/วัน (ค่าเริ่มต้น = ตอนนี้) ใช้เมื่อ fields.date อ่านเป็นวันที่ไม่ได้
            ปกติโฟลเดอร์ตั้งตามวันที่ของไฟล์ PR (fields.date)
    """
    when = when or datetime.now()
    result = SubmitResult()
    # โฟลเดอร์ ปี/เดือน/วัน ตามวันที่ของไฟล์ PR (fields.date) ไม่ใช่วันที่ Upload (แปลงไม่ได้ = ใช้ when)
    try:
        when = datetime.fromisoformat(f"{fields.date}T00:00:00")
    except ValueError:
        pass

    # (1) เก็บไฟล์ในเครื่อง: ถ้าพลาดไม่บันทึกรายการ เพื่อไม่ให้ไฟล์หายไปเงียบๆ
    # ไฟล์ทุกไฟล์ในการส่งครั้งนี้รวมอยู่โฟลเดอร์เดียว ปี/เดือน/วัน/ชื่อไฟล์ PR (โครงเดียวกับที่เก็บออนไลน์)
    local_paths: list[str] = []
    folder_name = build_folder_name_from_files([name for name, _ in files])
    folder_parts = build_storage_folder_parts(when, folder_name)
    try:
        for file_name, file_bytes in files:
            local_paths.append(save_document_locally(file_bytes, file_name, folder_parts))
    except LocalStorageError as error:
        result.error = str(error)
        return result

    # (1.1) โหมดทดสอบบนเครื่องตัวเอง: สร้างโฟลเดอร์บน Desktop + คัดลอกไฟล์ทันทีที่ Upload (พลาดไม่ทำให้ขั้นอื่นล้ม)
    if DESKTOP_EXPORT_ENABLED and local_paths:
        try:
            result.desktop_folder = str(export_files_to_desktop(FILE_PATH_SEPARATOR.join(local_paths), when))
        except LocalStorageError as error:
            logger.error("สร้างโฟลเดอร์บน Desktop ไม่สำเร็จ: %s", type(error).__name__)
            result.desktop_message = str(error)

    # (2) ส่งไฟล์ไปที่เก็บออนไลน์ (ยังไม่ตั้งค่า = ข้าม ไม่ถือเป็น error)
    if files and not is_storage_configured():
        result.storage_status = "skipped"
        result.storage_message = "ยังไม่ได้ตั้งค่าที่เก็บไฟล์ออนไลน์ (ดู NEXT_STEPS.md) ไฟล์เก็บในเครื่องแล้ว"
    elif files:
        try:
            result.storage_links = upload_files_to_storage(files, folder_name, when)
            folder_url = get_storage_folder_url(folder_name, when)  # SharePoint: ลิงก์ไปโฟลเดอร์ของไฟล์ PR
            if folder_url:
                result.storage_links.insert(0, folder_url)
            result.storage_status = "ok"
        except StorageError as error:
            logger.error("ส่งไฟล์ไปที่เก็บออนไลน์ไม่สำเร็จ: %s", type(error).__name__)
            result.storage_status = "error"
            result.storage_message = str(error)

    # (3) บันทึกลงฐานข้อมูล -> ขึ้นตารางบนเว็บ (ลิงก์ที่กรอกเองมาก่อน ไม่มีก็ใช้ลิงก์ไฟล์แรกที่ส่งขึ้น)
    record = asdict(fields)
    record["sharepoint_url"] = fields.sharepoint_url or (result.storage_links[0] if result.storage_links else None)
    new_id = add_transaction(**record, file_path=FILE_PATH_SEPARATOR.join(local_paths) or None)
    if new_id is None:
        result.error = "บันทึกรายการลงฐานข้อมูลไม่สำเร็จ"  # add_transaction แสดงรายละเอียดให้แล้ว
        return result
    result.transaction_id = new_id

    # (4) Master-List: เฉพาะฟิลด์ที่ต้องการ ไม่ส่งไฟล์
    result.masterlist_sent, message = send_to_masterlist(build_masterlist_payload(record))
    result.masterlist_message = message or ""
    return result
