"""เก็บไฟล์เอกสาร (PR/PO/ใบกำกับภาษี) ลงโฟลเดอร์ data/local_uploads/ ภายในโปรเจค

ใช้แทน SharePoint ชั่วคราวระหว่างรอสิทธิ์ (sharepoint_api.py ยังเก็บไว้ เตรียมต่อภายหลัง)
ไฟล์ไม่มี Streamlit: ถ้าผิดพลาดจะ raise LocalStorageError พร้อมข้อความภาษาไทย ให้หน้า UI เป็นคนแสดงผลเอง
"""

import re
from datetime import datetime
from pathlib import Path

# โฟลเดอร์เก็บไฟล์ data/local_uploads/ (ถัดจาก utils/ ขึ้นไป 1 ชั้น แล้วเข้า data/ — ถ้าไม่มีจะถูกสร้างให้อัตโนมัติตอนบันทึกไฟล์แรก)
UPLOAD_DIRECTORY: Path = Path(__file__).parent.parent / "data" / "local_uploads"


class LocalStorageError(Exception):
    """ข้อผิดพลาดการบันทึกไฟล์ในเครื่อง (ข้อความเป็นภาษาไทย แสดงให้ผู้ใช้ได้เลย)"""


def save_document_locally(file_bytes: bytes, file_name: str) -> str:
    """บันทึกไฟล์ลง local_uploads/ แล้วคืนที่อยู่ไฟล์ (เทียบจากโฟลเดอร์โปรเจค) เพื่อเก็บลงฐานข้อมูล

    Args:
        file_bytes: เนื้อไฟล์ (bytes)
        file_name: ชื่อไฟล์เดิม (ระบบใส่เวลานำหน้าเพื่อกันชื่อซ้ำ และแทนอักขระแปลกๆ ด้วย _)

    Returns:
        ที่อยู่ไฟล์แบบ relative เช่น "data/local_uploads/20260101_093000_PO_1001.pdf"

    Raises:
        LocalStorageError: ไฟล์ว่าง / สร้างโฟลเดอร์หรือเขียนไฟล์ไม่ได้
    """
    if not file_bytes:
        raise LocalStorageError("ไฟล์ที่เลือกว่างเปล่า (0 ไบต์): เลือกไฟล์ใหม่แล้วลองอีกครั้ง")

    # ตัดส่วน path ออก และแทนอักขระที่ไม่ปลอดภัยด้วย _ (ภาษาไทยยังใช้ได้)
    # (฀-๿ = ตัวอักษร/สระ/วรรณยุกต์ไทย)
    cleaned_name = re.sub(r"[^\w฀-๿.\-]", "_", Path(file_name).name) or "document"
    stored_file_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{cleaned_name}"

    try:
        UPLOAD_DIRECTORY.mkdir(parents=True, exist_ok=True)  # สร้างโฟลเดอร์ให้เองถ้ายังไม่มี
        (UPLOAD_DIRECTORY / stored_file_name).write_bytes(file_bytes)
    except OSError as error:
        raise LocalStorageError(
            "บันทึกไฟล์ไม่สำเร็จ: ตรวจว่าดิสก์ไม่เต็ม และโฟลเดอร์ local_uploads/ ไม่ถูกล็อกหรือเป็นแบบอ่านอย่างเดียว"
            f"\n\nรายละเอียดทางเทคนิค: {error}"
        ) from error

    return f"{UPLOAD_DIRECTORY.parent.name}/{UPLOAD_DIRECTORY.name}/{stored_file_name}"
