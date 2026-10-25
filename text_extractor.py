"""ดึงข้อมูล Tax ID, ยอดรวม และชื่อผู้ขาย จากไฟล์ PDF เพื่อ Auto-fill ในฟอร์ม

หลักการสำคัญ (Graceful degradation):
- ทุกฟังก์ชันในไฟล์นี้ "ห้ามโยน Error ออกไป" ถ้าหาไม่เจอหรืออ่านไฟล์ไม่ได้จะคืนค่าว่าง ""
- ไฟล์นี้ไม่ import streamlit ผู้เรียก (หน้าฟอร์ม) เป็นคนแสดงคำเตือนเอง
  โดยดูจาก ExtractedFields.missing_field_labels / warning_message
- รองรับเฉพาะ PDF ที่มีข้อความ (text-based) ถ้าเป็น PDF สแกนหรือรูปภาพ จะได้ข้อความว่าง
  ซึ่งต้องใช้ OCR (ยังไม่ทำ) ผู้ใช้จะต้องกรอกเอง

วิธีเพิ่มกฎค้นหาใหม่: แก้ที่ค่าคงที่ด้านบน (คำนำหน้า / รูปแบบ) ไม่ต้องแก้ logic ในฟังก์ชัน
"""

import logging
import re
from dataclasses import dataclass
from typing import BinaryIO, Optional, Union

import pdfplumber

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# ค่าคงที่: กฎการค้นหา (แก้ที่นี่เมื่อเอกสารของผู้ขายรูปแบบไม่ตรง)
# ---------------------------------------------------------------------------

# คำนำหน้าที่บอกว่า "ตัวเลขถัดไปคือ Tax ID"
TAX_ID_LABELS: list[str] = [
    r"เลขประจำตัวผู้เสียภาษี(?:อากร)?",
    r"เลขที่ผู้เสียภาษี",
    r"Tax\s*ID",
    r"Tax\s*Identification\s*No\.?",
    r"TIN",
]

# เลข 13 หลัก ยอมให้มี "-" หรือ "เว้นวรรค" คั่นได้ เช่น 0-1055-12345-67-8
# (?<!\d) และ (?!\d) = ห้ามติดกับตัวเลขอื่น กันไปหยิบเลขยาว ๆ มาตัดเอา 13 หลัก
THIRTEEN_DIGIT_PATTERN: str = r"(?<!\d)(?:\d[\s-]?){12}\d(?!\d)"

# คำนำหน้ายอดรวม เรียงจาก "เจาะจงที่สุด" ไป "กว้างที่สุด" ระบบจะลองตามลำดับนี้
# และใช้ผลของคำแรกที่เจอ (กัน "ยอดรวม" ของสินค้าแต่ละบรรทัดมาแทนที่ยอดสุทธิ)
TOTAL_AMOUNT_LABELS: list[str] = [
    r"จำนวนเงินรวมทั้งสิ้น",
    r"ยอดรวมทั้งสิ้น",
    r"รวมเงินทั้งสิ้น",
    r"รวมทั้งสิ้น",
    r"ยอดเงินสุทธิ",
    r"ยอดสุทธิ",
    r"Grand\s*Total",
    r"Total\s*Amount",
    r"Net\s*Total",
    r"Amount\s*Due",
    r"ราคารวม",
    r"Total",
]

# ตัวเลขเงิน เช่น 1,234.50 / 1234.5 / 1234 (ไม่รับตัวเลขติดตัวอักษร)
MONEY_PATTERN: str = r"\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?"

# คำนำหน้าที่บอกว่า "ข้อความถัดไปคือชื่อผู้ขาย"
VENDOR_LABELS: list[str] = [
    r"ชื่อผู้ขาย",
    r"ผู้ขาย",
    r"ผู้จำหน่าย",
    r"Vendor",
    r"Supplier",
    r"Seller",
]

# คำที่บ่งบอกว่าบรรทัดนั้นคือชื่อบริษัท (ใช้เป็นแผนสำรองเมื่อไม่มีคำนำหน้า)
COMPANY_KEYWORD_PATTERN: str = (
    r"บริษัท|บจก\.?|หจก\.?|ห้างหุ้นส่วน|ร้าน|Co\.\s*,?\s*Ltd|Company|Limited|Ltd\.?|Inc\.?|Corp"
)

# แผนสำรองหาชื่อบริษัทเฉพาะ N บรรทัดแรก (หัวกระดาษมักมีชื่อบริษัทอยู่ด้านบน)
COMPANY_SEARCH_LINE_LIMIT: int = 15

# ชื่อภาษาไทยของแต่ละฟิลด์ ใช้ตอนสร้างคำเตือน
FIELD_LABELS: dict[str, str] = {
    "tax_id": "Tax ID",
    "total_amount": "ยอดรวม",
    "vendor": "ผู้ขาย",
}


# ---------------------------------------------------------------------------
# ผลลัพธ์
# ---------------------------------------------------------------------------


@dataclass
class ExtractedFields:
    """ผลลัพธ์ที่ดึงได้จากเอกสาร ทุกฟิลด์เป็น str และเป็น "" ถ้าหาไม่เจอ

    Attributes:
        tax_id: เลขผู้เสียภาษี 13 หลัก (เฉพาะตัวเลข ไม่มี "-")
        total_amount: ยอดรวม เป็นข้อความทศนิยม 2 ตำแหน่ง เช่น "1500.50" (แปลงเป็น float ได้ทันที)
        vendor: ชื่อผู้ขาย
    """

    tax_id: str = ""
    total_amount: str = ""
    vendor: str = ""

    @property
    def missing_field_labels(self) -> list[str]:
        """ชื่อภาษาไทยของฟิลด์ที่หาไม่เจอ (list ว่างแปลว่าได้ครบ)"""
        return [label for key, label in FIELD_LABELS.items() if not getattr(self, key)]

    @property
    def warning_message(self) -> str:
        """ข้อความเตือนให้ผู้ใช้กรอกเอง ("" ถ้าดึงได้ครบทุกฟิลด์)"""
        missing_labels = self.missing_field_labels
        if not missing_labels:
            return ""
        return (
            f"ระบบดึงข้อมูลไม่ได้: {', '.join(missing_labels)} "
            "กรุณาตรวจสอบเอกสารและกรอกข้อมูลส่วนนี้เอง"
        )


# ---------------------------------------------------------------------------
# อ่านข้อความจาก PDF
# ---------------------------------------------------------------------------


def extract_text_from_pdf(pdf_source: Union[str, BinaryIO]) -> str:
    """อ่านข้อความทุกหน้าของ PDF ด้วย pdfplumber

    Args:
        pdf_source: path ของไฟล์ หรือ file object (เช่น UploadedFile จาก st.file_uploader)

    Returns:
        ข้อความรวมทุกหน้า คั่นหน้าด้วยขึ้นบรรทัดใหม่
        คืน "" ถ้าไฟล์เสีย / เป็น PDF สแกนที่ไม่มีข้อความ / อ่านไม่ได้
    """
    try:
        page_texts: list[str] = []
        with pdfplumber.open(pdf_source) as pdf_document:
            for page in pdf_document.pages:
                # extract_text คืน None ถ้าหน้านั้นไม่มีข้อความ (เช่นหน้าสแกน)
                page_texts.append(page.extract_text() or "")
        return "\n".join(page_texts)
    except Exception as error:  # noqa: BLE001 - pdfplumber โยน error หลายชนิด ต้องดักให้หมด
        logger.warning("อ่านไฟล์ PDF ไม่สำเร็จ: %s", error)
        return ""


# ---------------------------------------------------------------------------
# ค้นหาแต่ละฟิลด์จากข้อความ
# ---------------------------------------------------------------------------


def is_valid_thai_tax_id(tax_id: str) -> bool:
    """ตรวจเลขผู้เสียภาษี/บัตรประชาชน 13 หลักด้วยตัวเลข check digit

    ใช้ช่วยเลือกเลข 13 หลักที่ "น่าจะเป็น Tax ID จริง" เมื่อในเอกสารมีเลข 13 หลักหลายตัว
    สูตร: เอาหลักที่ 1-12 คูณ 13,12,...,2 รวมกัน แล้ว (11 - (ผลรวม mod 11)) mod 10 ต้องเท่าหลักที่ 13

    Args:
        tax_id: เลข 13 หลักล้วน

    Returns:
        True ถ้า check digit ถูกต้อง
    """
    if len(tax_id) != 13 or not tax_id.isdigit():
        return False
    weighted_sum = sum(int(digit) * weight for digit, weight in zip(tax_id[:12], range(13, 1, -1)))
    return (11 - weighted_sum % 11) % 10 == int(tax_id[12])


def find_tax_id(text: str) -> str:
    """หา Tax ID 13 หลักจากข้อความ

    ลำดับการค้นหา:
      1) เลข 13 หลักที่อยู่หลังคำว่า "เลขประจำตัวผู้เสียภาษี" / "Tax ID" ฯลฯ (เชื่อถือสุด)
      2) เลข 13 หลักที่ไหนก็ได้ในเอกสาร โดยเลือกตัวที่ check digit ถูกก่อน
      3) ถ้าไม่มีตัวที่ check digit ถูก ใช้เลข 13 หลักตัวแรกที่เจอ

    Args:
        text: ข้อความทั้งเอกสาร

    Returns:
        เลข 13 หลักล้วน (ไม่มี "-" หรือเว้นวรรค) หรือ "" ถ้าหาไม่เจอ
    """
    try:
        # ขั้นที่ 1: กำลังค้นหาเลข 13 หลักที่ตามหลังคำนำหน้า Tax ID
        # [^\d\n]{0,30} = ยอมให้มีตัวอักษร/เครื่องหมาย (เช่น ":" หรือ "No.") คั่นได้ไม่เกิน 30 ตัว ในบรรทัดเดียวกัน
        for label_pattern in TAX_ID_LABELS:
            labeled_match = re.search(
                rf"{label_pattern}[^\d\n]{{0,30}}({THIRTEEN_DIGIT_PATTERN})", text, re.IGNORECASE
            )
            if labeled_match:
                return re.sub(r"\D", "", labeled_match.group(1))

        # ขั้นที่ 2-3: กำลังค้นหาเลข 13 หลักที่ไหนก็ได้ แล้วเอาตัวเลขล้วนมาเทียบ
        all_candidates = [
            re.sub(r"\D", "", found) for found in re.findall(THIRTEEN_DIGIT_PATTERN, text)
        ]
        for candidate in all_candidates:
            if is_valid_thai_tax_id(candidate):
                return candidate
        return all_candidates[0] if all_candidates else ""
    except Exception as error:  # noqa: BLE001 - กันทุกกรณีไม่ให้ระบบพัง
        logger.warning("หา Tax ID ไม่สำเร็จ: %s", error)
        return ""


def find_total_amount(text: str) -> str:
    """หายอดรวมสุทธิจากข้อความ

    เงื่อนไข: ลองคำนำหน้าตามลำดับใน TOTAL_AMOUNT_LABELS (เจาะจงสุดก่อน เช่น "จำนวนเงินรวมทั้งสิ้น")
    เมื่อเจอคำไหนแล้วจะหยุดลองคำถัดไป ถ้าคำนั้นปรากฏหลายที่ จะใช้ตำแหน่ง "สุดท้าย" ในเอกสาร
    เพราะยอดสุทธิมักอยู่ท้ายสุด ส่วนยอดรวมย่อยอยู่ก่อนหน้า
    ถ้าไม่เจอคำนำหน้าเลยจะ "ไม่เดา" ว่าตัวเลขไหนคือยอดรวม เพื่อไม่ให้เติมตัวเลขผิดลงฟอร์ม

    Args:
        text: ข้อความทั้งเอกสาร

    Returns:
        ยอดรวมทศนิยม 2 ตำแหน่ง ไม่มีเครื่องหมาย "," เช่น "1500.50" หรือ "" ถ้าหาไม่เจอ
    """
    try:
        for label_pattern in TOTAL_AMOUNT_LABELS:
            # กำลังค้นหาตัวเลขเงินที่ตามหลังคำนำหน้ายอดรวม
            # [^\d\n]{0,25} = ยอมให้มี ":" หรือ "บาท" หรือเว้นวรรคคั่นได้ ในบรรทัดเดียวกัน
            # \b นำหน้าคำภาษาอังกฤษ ทำให้ "Subtotal" ไม่ถูกนับว่าเป็น "Total"
            label_prefix = rf"\b{label_pattern}" if label_pattern.isascii() else label_pattern
            matches = re.findall(
                rf"{label_prefix}[^\d\n]{{0,25}}({MONEY_PATTERN})", text, re.IGNORECASE
            )
            if matches:
                amount = float(matches[-1].replace(",", ""))
                return f"{amount:.2f}"
        return ""
    except Exception as error:  # noqa: BLE001 - กันทุกกรณีไม่ให้ระบบพัง
        logger.warning("หายอดรวมไม่สำเร็จ: %s", error)
        return ""


def _clean_vendor_name(raw_name: str) -> str:
    """ทำความสะอาดชื่อผู้ขายที่ดึงมา: ตัดช่องว่างซ้ำ และตัดส่วนท้ายที่ไม่ใช่ชื่อ (เช่น Tax ID ต่อท้าย)"""
    # ตัดทุกอย่างตั้งแต่คำว่า "เลขประจำตัว..." / "Tax ID" เป็นต้นไป เพราะบางเอกสารเขียนไว้บรรทัดเดียวกัน
    without_tax_part = re.split(r"เลขประจำตัว|เลขที่ผู้เสียภาษี|Tax\s*ID|TIN", raw_name, flags=re.I)[0]
    return re.sub(r"\s+", " ", without_tax_part).strip(" :-\t")


def find_vendor(text: str) -> str:
    """หาชื่อผู้ขายจากข้อความ

    ลำดับการค้นหา:
      1) ข้อความหลังคำว่า "ผู้ขาย" / "ผู้จำหน่าย" / "Vendor" / "Supplier" ในบรรทัดเดียวกัน (เชื่อถือสุด)
      2) แผนสำรอง: บรรทัดแรก (ภายใน COMPANY_SEARCH_LINE_LIMIT บรรทัดแรก)
         ที่มีคำบอกชื่อบริษัท เช่น "บริษัท", "หจก.", "Co., Ltd."
         ข้อควรระวัง: แผนสำรองอาจได้ชื่อบริษัทเราเอง (ผู้ซื้อ) ถ้าเอกสารไม่มีคำว่า "ผู้ขาย"
         ผู้ใช้จึงควรตรวจค่าที่เติมให้ทุกครั้ง

    Args:
        text: ข้อความทั้งเอกสาร

    Returns:
        ชื่อผู้ขาย หรือ "" ถ้าหาไม่เจอ
    """
    try:
        # ขั้นที่ 1: กำลังค้นหาข้อความหลังคำนำหน้าผู้ขาย
        # [ \t]*[:：]?[ \t]* = ยอมให้มี ":" หรือเว้นวรรคคั่น แล้ว (.+) = เอาที่เหลือของบรรทัดนั้น
        for label_pattern in VENDOR_LABELS:
            labeled_match = re.search(
                rf"{label_pattern}[ \t]*[:：]?[ \t]*(.+)", text, re.IGNORECASE
            )
            if labeled_match:
                vendor_name = _clean_vendor_name(labeled_match.group(1))
                if vendor_name:
                    return vendor_name

        # ขั้นที่ 2: กำลังค้นหาบรรทัดที่มีคำบอกชื่อบริษัท ในส่วนหัวของเอกสาร
        for line in text.splitlines()[:COMPANY_SEARCH_LINE_LIMIT]:
            if re.search(COMPANY_KEYWORD_PATTERN, line, re.IGNORECASE):
                vendor_name = _clean_vendor_name(line)
                if vendor_name:
                    return vendor_name
        return ""
    except Exception as error:  # noqa: BLE001 - กันทุกกรณีไม่ให้ระบบพัง
        logger.warning("หาชื่อผู้ขายไม่สำเร็จ: %s", error)
        return ""


# ---------------------------------------------------------------------------
# ฟังก์ชันหลักที่หน้าฟอร์มเรียกใช้
# ---------------------------------------------------------------------------


def extract_fields_from_text(text: str) -> ExtractedFields:
    """ดึงทุกฟิลด์จากข้อความที่อ่านมาแล้ว (แยกออกมาเพื่อให้ทดสอบโดยไม่ต้องมีไฟล์ PDF)

    Args:
        text: ข้อความทั้งเอกสาร

    Returns:
        ExtractedFields (ฟิลด์ที่หาไม่เจอเป็น "")
    """
    return ExtractedFields(
        tax_id=find_tax_id(text),
        total_amount=find_total_amount(text),
        vendor=find_vendor(text),
    )


def extract_fields_from_pdf(pdf_source: Optional[Union[str, BinaryIO]]) -> ExtractedFields:
    """อ่าน PDF แล้วดึง Tax ID, ยอดรวม, ผู้ขาย ในขั้นตอนเดียว (ฟังก์ชันนี้ไม่โยน Error)

    ตัวอย่างการใช้ในหน้าฟอร์ม:
        extracted = extract_fields_from_pdf(uploaded_po_document)
        if extracted.warning_message:
            st.warning(extracted.warning_message)

    Args:
        pdf_source: path หรือ file object ของ PDF (None ได้ ถ้ายังไม่ได้อัปโหลด)

    Returns:
        ExtractedFields ถ้าอ่านไฟล์ไม่ได้ทั้งไฟล์ ทุกฟิลด์จะเป็น "" และ warning_message จะเตือนให้กรอกเอง
    """
    if pdf_source is None:
        return ExtractedFields()
    return extract_fields_from_text(extract_text_from_pdf(pdf_source))
