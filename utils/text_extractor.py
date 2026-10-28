"""ดึงข้อมูล Tax ID, ยอดรวม, ชื่อผู้ขาย และฟิลด์ Master-List (PR / Quotation) จากไฟล์ PDF เพื่อ Auto-fill ในฟอร์ม

หลักการสำคัญ (Graceful degradation):
- ทุกฟังก์ชันในไฟล์นี้ "ห้ามโยน Error ออกไป" ถ้าหาไม่เจอหรืออ่านไฟล์ไม่ได้จะคืนค่าว่าง ""
- ไฟล์นี้ไม่ import streamlit ผู้เรียก (หน้าฟอร์ม) เป็นคนแสดงคำเตือนเอง
  โดยดูจาก ExtractedFields.missing_field_labels / warning_message
- รองรับเฉพาะ PDF ที่มีข้อความ (text-based) ถ้าเป็น PDF สแกนหรือรูปภาพ จะได้ข้อความว่าง
  ซึ่งต้องใช้ OCR (ยังไม่ทำ) ผู้ใช้จะต้องกรอกเอง

วิธีเพิ่มกฎค้นหาใหม่: แก้ที่ค่าคงที่ด้านบน (คำนำหน้า / รูปแบบ) ไม่ต้องแก้ logic ในฟังก์ชัน
"""

import re
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, BinaryIO, Optional, Union

import pandas as pd
import pdfplumber
from pdfplumber.utils.exceptions import PdfminerException

from config.logging_setup import get_logger

# บันทึกลง logs/app.log (ดู config/logging_setup.py)
logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# ชนิด Error ที่ "คาดว่าจะเกิด" (ดักเฉพาะเจาะจง เพื่อไม่กลบบั๊กจริงในโค้ดของเราเอง)
# ถ้าเจอ Error ชนิดใหม่ที่ไม่อยู่ในรายการ แอปจะแสดงข้อความผิดพลาดให้เห็น แทนที่จะเงียบหาย ให้เพิ่มชนิดนั้นที่นี่
# ---------------------------------------------------------------------------

# อ่าน PDF: ไม่พบไฟล์/เปิดไม่ได้ (OSError รวม FileNotFoundError), PDF เสียหรือไม่ใช่ PDF (PdfminerException)
PDF_READ_ERRORS: tuple[type[Exception], ...] = (OSError, PdfminerException, ValueError, TypeError)
# อ่าน Excel: ไม่พบไฟล์ (OSError), ไฟล์เสีย/ว่าง/ผิดชนิด (ValueError, BadZipFile, KeyError), ขาด library (ImportError)
EXCEL_READ_ERRORS: tuple[type[Exception], ...] = (
    OSError,
    ValueError,
    TypeError,
    KeyError,
    ImportError,
    zipfile.BadZipFile,
)
# ค้นหาฟิลด์ด้วย RegEx: pattern ผิด (re.error), แปลงตัวเลข/วันที่ไม่ได้ (ValueError), ข้อความไม่ใช่ str (TypeError)
FIND_ERRORS: tuple[type[Exception], ...] = (re.error, ValueError, TypeError, IndexError)

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
    r"ราคารวมหลังภาษี(?:มูลค่าเพิ่ม)?",  # ยอดรวมที่บวก VAT แล้ว (ฟอร์ม PR) ต้องมาก่อน "ราคารวม" ซึ่งเป็นยอดก่อนภาษี
    r"รวมหลังภาษี(?:มูลค่าเพิ่ม)?",
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

# ป้ายกว้างสุด: ตัวเลขต้องอยู่บรรทัดเดียวกับป้ายเท่านั้น (กันไปหยิบเลขลำดับแถวสินค้าจากหัวตาราง "Total")
SAME_LINE_ONLY_TOTAL_LABELS: frozenset[str] = frozenset({r"Total"})

# ตัวเลขเงิน เช่น 1,234.50 / 1234.5 / 1234 (ไม่รับตัวเลขติดตัวอักษร)
MONEY_PATTERN: str = r"\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?"

# คำนำหน้าที่บอกว่า "ข้อความถัดไปคือชื่อผู้ขาย"
# (รวม "บริษัทที่ติดต่อสั่งซื้อ" เข้ากับผู้ขายแล้ว: ใช้ฟิลด์ vendor ตัวเดียว ไม่แยก company_name)
VENDOR_LABELS: list[str] = [
    r"บริษัทที่ติดต่อ(?:สั่งซื้อ)?",
    r"ชื่อบริษัท",
    r"Company\s*Name",
    r"ชื่อผู้ขาย",
    r"ผู้ขาย",
    r"ผู้จำหน่าย",
    r"Vendor",
    r"Supplier",
    r"Seller",
]

# หัวข้อกล่อง "บริษัทที่แนะนำให้ติดต่อ (Suggest source)" ใน PR: ชื่อบริษัทผู้ขายและเบอร์โทรของผู้ขายอยู่ในกล่องนี้
SUGGEST_SOURCE_LABEL_PATTERN: str = r"บริษัทที่แนะนำให้ติดต่อ|Suggest\s*source"
# ป้ายชื่อบริษัทในกล่องนั้น เช่น "บริษัท (Company):"
SUGGEST_SOURCE_COMPANY_LABEL_PATTERN: str = r"บริษัท\s*\(\s*Company\s*\)"
# จำนวนบรรทัดหลังหัวข้อที่นับว่าอยู่ในกล่อง (กล่องจริงยาวราว 3 บรรทัด)
SUGGEST_SOURCE_SECTION_LINE_LIMIT: int = 8

# คำที่บ่งบอกว่าบรรทัดนั้นคือชื่อบริษัท (ใช้เป็นแผนสำรองเมื่อไม่มีคำนำหน้า)
COMPANY_KEYWORD_PATTERN: str = (
    r"บริษัท|บจก\.?|หจก\.?|ห้างหุ้นส่วน|ร้าน|Co\.\s*,?\s*Ltd|Company|Limited|Ltd\.?|Inc\.?|Corp"
)

# แผนสำรองหาชื่อบริษัทเฉพาะ N บรรทัดแรก (หัวกระดาษมักมีชื่อบริษัทอยู่ด้านบน)
COMPANY_SEARCH_LINE_LIMIT: int = 15

# ชื่อภาษาไทยของแต่ละฟิลด์ ใช้ตอนสร้างคำเตือน
# หมายเหตุ: ฟิลด์ Master-List ด้านล่าง (tel ... unit_price) ยังเป็นโครงร่าง (Logic จำลอง)
# จึงยังไม่ใส่ที่นี่ เพื่อไม่ให้ขึ้นคำเตือน "ดึงไม่ได้" ทุกครั้ง เมื่อ RegEx จริงใช้ได้แล้วค่อยเพิ่มชื่อฟิลด์ตรงนี้
FIELD_LABELS: dict[str, str] = {
    "tax_id": "Tax ID",
    "total_amount": "ยอดรวม",
    "vendor": "ผู้ขาย",
}

# ---------------------------------------------------------------------------
# ค่าคงที่: กฎค้นหาฟิลด์ Master-List (โครงร่าง RegEx จำลอง ต้องปรับให้ตรงเอกสารจริงภายหลัง)
# แต่ละรายการคือ "คำนำหน้า" ที่บอกว่าข้อความ/ตัวเลขถัดไปคือค่าของฟิลด์นั้น
# ถ้าจะเพิ่มฟิลด์ใหม่: เพิ่มคำนำหน้าที่นี่ + ฟิลด์ใน ExtractedFields + ฟังก์ชัน find_... + extract_fields_from_text
# ---------------------------------------------------------------------------

# เบอร์โทรศัพท์ (ไม่ใช้คำว่า "Fax" เพื่อไม่หยิบเบอร์แฟกซ์) เก็บลงคอลัมน์ tel
TEL_LABELS: list[str] = [
    r"โทรศัพท์",
    r"เบอร์โทร(?:ศัพท์)?",
    r"โทร\.?",
    r"Tel(?:ephone)?\.?",
    r"Phone",
]
# เบอร์โทรไทย เช่น 02-123-4567 / 089 456 7890 / +66 2 123 4567 (ขึ้นต้นด้วย 0 หรือ +66)
TEL_NUMBER_PATTERN: str = r"(?:\+66|0)[\d\s-]{7,13}\d"

# เลขที่ PR (เช่น PR-2026-0012)
PR_NO_LABELS: list[str] = [
    r"เลขที่\s*PR",
    r"PR\s*(?:Run\s*)?No\.?",
    r"PR\s*Number",
    r"เลขที่ใบขอซื้อ",
]
# เลขเอกสาร: ตัวอักษร/ตัวเลข ขีด ทับ เท่านั้น (ห้ามมีช่องว่าง)
DOCUMENT_NO_PATTERN: str = r"[A-Za-z0-9][A-Za-z0-9\-/_.]{2,}"

# วันที่ PR
PR_DATE_LABELS: list[str] = [
    r"วันที่\s*PR",
    r"PR\s*Date",
    r"วันที่ขอซื้อ",
    r"วันที่ใบขอซื้อ",
]
# วันที่รูปแบบ DD/MM/YYYY หรือ DD-MM-YYYY (ปีเป็น พ.ศ. หรือ ค.ศ. ก็ได้ ระบบแปลงให้เอง)
DATE_PATTERN: str = r"\d{1,2}[/\-.]\d{1,2}[/\-.]\d{4}"
# ปี พ.ศ. มากกว่าปี ค.ศ. อยู่ 543 ปี ถ้าปีที่อ่านได้มากกว่าค่านี้ ถือว่าเป็น พ.ศ.
BUDDHIST_YEAR_THRESHOLD: int = 2400
BUDDHIST_YEAR_OFFSET: int = 543

# เลขที่ Quotation
QT_NO_LABELS: list[str] = [
    r"เลขที่ใบเสนอราคา",
    r"ใบเสนอราคาเลขที่",
    r"Quotation\s*(?:No\.?|Number)",
    r"Quote\s*No\.?",
    r"QT\s*No\.?",
]

# รายละเอียดอุปกรณ์ (เอาข้อความที่เหลือของบรรทัดหลังคำนำหน้า)
DESCRIPTION_LABELS: list[str] = [
    r"รายละเอียด(?:อุปกรณ์|สินค้า)?",
    r"รายการสินค้า",
    r"Item\s*Description",
    r"Description",
]

# ราคาสุทธิที่รวม Discount แล้ว (เจาะจงสุดก่อน เหมือน TOTAL_AMOUNT_LABELS)
UNIT_PRICE_LABELS: list[str] = [
    r"ราคาสุทธิ(?:หลังหักส่วนลด)?",
    r"ราคาหลังส่วนลด",
    r"Net\s*Price",
    r"Price\s*after\s*Discount",
    r"Unit\s*Price",
    r"ราคาต่อหน่วย",
]


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
        tel: เบอร์โทรศัพท์ (ตามที่เขียนในเอกสาร เช่น "02-123-4567")
        pr_run_no: เลขที่ PR
        pr_request_date: วันที่ PR รูปแบบ "YYYY-MM-DD" (ค.ศ.)
        qt_no: เลขที่ Quotation
        description: รายละเอียดอุปกรณ์
        unit_price: ราคาสุทธิที่รวม Discount แล้ว ทศนิยม 2 ตำแหน่ง เช่น "1500.50"
    """

    tax_id: str = ""
    total_amount: str = ""
    vendor: str = ""
    # --- ฟิลด์ Master-List (ชื่อตรงกับคอลัมน์ในตาราง transactions ของ database.py) ---
    # ถ้าจะเพิ่มฟิลด์ใหม่ ให้เพิ่มที่นี่ แล้วเพิ่มฟังก์ชัน find_... และเรียกใน extract_fields_from_text
    tel: str = ""
    pr_run_no: str = ""
    pr_request_date: str = ""
    qt_no: str = ""
    description: str = ""
    unit_price: str = ""
    # ตรวจพบว่าไฟล์เป็น/มีใบกำกับภาษีหรือไม่ (ใช้ตั้งสถานะ Completed อัตโนมัติ) ไม่นับเป็นฟิลด์ที่ "ขาด" ใน warning_message
    has_tax_invoice: bool = False

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
    except PDF_READ_ERRORS as error:
        logger.warning("อ่านไฟล์ PDF ไม่สำเร็จ: %s", error, exc_info=True)
        return ""


# ---------------------------------------------------------------------------
# อ่านข้อความจาก Excel (.xlsx / .xls) -- โครงร่าง Logic จำลอง
# ---------------------------------------------------------------------------

# นามสกุลไฟล์ Excel ที่รองรับ (.xlsx ใช้ openpyxl, .xls ใช้ xlrd ซึ่ง pandas เรียกให้เอง)
EXCEL_EXTENSIONS: tuple[str, ...] = (".xlsx", ".xls")
# คั่นระหว่างช่อง (Cell) ที่อยู่แถวเดียวกัน ทำให้ "เลขที่ PR | PR-2026-0012" อ่านเหมือนข้อความ "เลขที่ PR : PR-2026-0012"
EXCEL_CELL_SEPARATOR: str = " : "
# รูปแบบแสดงวันที่ของช่องที่เป็นวันที่ใน Excel (ให้ตรงกับ DATE_PATTERN ที่ใช้หา PR Date)
EXCEL_DATE_FORMAT: str = "%d/%m/%Y"


def _excel_cell_to_text(cell_value: Any) -> str:
    """แปลงค่าในช่อง Excel เป็นข้อความ: ช่องว่าง -> "", วันที่ -> DD/MM/YYYY, เลขลงท้าย .0 -> ตัด .0 ออก

    Args:
        cell_value: ค่าจาก pandas (str / int / float / Timestamp / NaN / None)

    Returns:
        ข้อความของช่องนั้น ("" ถ้าว่าง)
    """
    if cell_value is None or pd.isna(cell_value):
        return ""
    if isinstance(cell_value, (pd.Timestamp, date)):
        return cell_value.strftime(EXCEL_DATE_FORMAT)
    if isinstance(cell_value, float) and cell_value.is_integer():
        return str(int(cell_value))
    return str(cell_value).strip()


def extract_text_from_excel(excel_source: Union[str, BinaryIO]) -> str:
    """อ่านทุก Sheet ของ Excel แล้วแปลงเป็นข้อความ แถวละบรรทัด (ช่องในแถวเดียวกันคั่นด้วย " : ")

    วิธีนี้ทำให้ใช้ฟังก์ชัน find_... ชุดเดียวกับ PDF ได้ เช่น แถว ["เลขที่ PR", "PR-2026-0012"]
    กลายเป็น "เลขที่ PR : PR-2026-0012" ถ้าฟอร์ม Excel จริงวางค่าไว้ตำแหน่งอื่น (เช่นใต้หัวคอลัมน์)
    ให้ปรับฟังก์ชันนี้ให้อ่านตามตำแหน่ง Cell ที่แน่นอน

    Args:
        excel_source: path ของไฟล์ หรือ file object (เช่น UploadedFile จาก st.file_uploader)

    Returns:
        ข้อความรวมทุก Sheet คืน "" ถ้าเปิดไฟล์ไม่ได้ / ไฟล์ว่าง / ขาด library (openpyxl, xlrd)
    """
    try:
        # sheet_name=None = อ่านทุก Sheet, header=None = ไม่ถือว่าแถวแรกเป็นหัวคอลัมน์ (เอกสาร PR เป็นฟอร์ม ไม่ใช่ตาราง)
        # dtype=object = เก็บชนิดข้อมูลตามจริง (วันที่ไม่ถูกแปลงเป็นข้อความแปลก ๆ)
        all_sheets = pd.read_excel(excel_source, sheet_name=None, header=None, dtype=object)
        text_lines: list[str] = []
        for sheet_table in all_sheets.values():
            for row_values in sheet_table.itertuples(index=False):
                cell_texts = [_excel_cell_to_text(value) for value in row_values]
                non_empty_texts = [text for text in cell_texts if text]
                if non_empty_texts:
                    text_lines.append(EXCEL_CELL_SEPARATOR.join(non_empty_texts))
        return "\n".join(text_lines)
    except EXCEL_READ_ERRORS as error:
        logger.warning("อ่านไฟล์ Excel ไม่สำเร็จ: %s", error, exc_info=True)
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
    except FIND_ERRORS as error:
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
            # (?:\n[^\d\n]{0,25})? = ยอมให้ตัวเลขอยู่บรรทัดถัดไปได้ 1 บรรทัด (ฟอร์ม PR เขียน "บาท (Baht) : 47080" ใต้ป้าย)
            # \b นำหน้าคำภาษาอังกฤษ ทำให้ "Subtotal" ไม่ถูกนับว่าเป็น "Total"
            label_prefix = rf"\b{label_pattern}" if label_pattern.isascii() else label_pattern
            gap = r"[^\d\n]{0,25}" + ("" if label_pattern in SAME_LINE_ONLY_TOTAL_LABELS else r"(?:\n[^\d\n]{0,25})?")
            matches = re.findall(rf"{label_prefix}{gap}({MONEY_PATTERN})", text, re.IGNORECASE)
            if matches:
                amount = float(matches[-1].replace(",", ""))
                return f"{amount:.2f}"
        return ""
    except FIND_ERRORS as error:
        logger.warning("หายอดรวมไม่สำเร็จ: %s", error)
        return ""


def _clean_vendor_name(raw_name: str) -> str:
    """ทำความสะอาดชื่อผู้ขายที่ดึงมา: ตัดช่องว่างซ้ำ และตัดส่วนท้ายที่ไม่ใช่ชื่อ (เช่น Tax ID ต่อท้าย)"""
    # ตัดทุกอย่างตั้งแต่คำว่า "เลขประจำตัว..." / "Tax ID" เป็นต้นไป เพราะบางเอกสารเขียนไว้บรรทัดเดียวกัน
    without_tax_part = re.split(r"เลขประจำตัว|เลขที่ผู้เสียภาษี|Tax\s*ID|TIN", raw_name, flags=re.I)[0]
    return re.sub(r"\s+", " ", without_tax_part).strip(" :-\t")


def _get_suggest_source_section(text: str) -> str:
    """คืนข้อความของกล่อง "บริษัทที่แนะนำให้ติดต่อ (Suggest source)" (หัวข้อ + บรรทัดถัดไปตามที่กำหนด)

    Args:
        text: ข้อความทั้งเอกสาร

    Returns:
        ข้อความของกล่อง หรือ "" ถ้าเอกสารไม่มีหัวข้อนี้ (ใช้หัวข้อตัวสุดท้ายที่เจอ)
    """
    lines = text.splitlines()
    heading_indexes = [
        index for index, line in enumerate(lines) if re.search(SUGGEST_SOURCE_LABEL_PATTERN, line, re.IGNORECASE)
    ]
    if not heading_indexes:
        return ""
    start_index = heading_indexes[-1]
    return "\n".join(lines[start_index : start_index + SUGGEST_SOURCE_SECTION_LINE_LIMIT])


def find_vendor(text: str) -> str:
    """หาชื่อผู้ขายจากข้อความ

    ลำดับการค้นหา:
      0) PR: ค่าหลัง "บริษัท (Company):" ในกล่อง "บริษัทที่แนะนำให้ติดต่อ (Suggest source)" (ตัดที่ตัวคั่น " : ")
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
        # ขั้นที่ 0: กำลังค้นหาชื่อบริษัทในกล่อง Suggest source (Excel ต่อเซลล์ด้วย " : " จึงตัดที่ตัวคั่นแรก)
        suggest_section = _get_suggest_source_section(text)
        company_match = re.search(
            rf"{SUGGEST_SOURCE_COMPANY_LABEL_PATTERN}[ \t]*[:：]?[ \t]*(.+)", suggest_section, re.IGNORECASE
        )
        if company_match:
            suggested_name = _clean_vendor_name(re.split(r"\s:\s", company_match.group(1))[0])
            if suggested_name:
                return suggested_name

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
    except FIND_ERRORS as error:
        logger.warning("หาชื่อผู้ขายไม่สำเร็จ: %s", error)
        return ""


# ---------------------------------------------------------------------------
# ค้นหาฟิลด์ Master-List (โครงร่าง: RegEx จำลอง ต้องทดสอบกับเอกสารจริงแล้วปรับค่าคงที่ด้านบน)
# ทุกฟังก์ชันคืน "" ถ้าหาไม่เจอ และไม่โยน Error
# ---------------------------------------------------------------------------


def _find_text_after_label(text: str, label_patterns: list[str]) -> str:
    """หาข้อความที่เหลือของบรรทัด หลังคำนำหน้าตัวแรกที่เจอ (ตัวช่วยกลางของฟิลด์ข้อความ)

    Args:
        text: ข้อความทั้งเอกสาร
        label_patterns: รายการ RegEx ของคำนำหน้า ลองตามลำดับ

    Returns:
        ข้อความหลังคำนำหน้า (ตัดช่องว่างซ้ำแล้ว) หรือ "" ถ้าหาไม่เจอ
    """
    for label_pattern in label_patterns:
        # \b นำหน้าคำภาษาอังกฤษ กันคำนำหน้าไปติดกลางคำอื่น
        label_prefix = rf"\b{label_pattern}" if label_pattern.isascii() else label_pattern
        # [ \t]*[:：]?[ \t]* = ยอมให้มี ":" หรือเว้นวรรคคั่น แล้ว (.+) = เอาที่เหลือของบรรทัดนั้น
        labeled_match = re.search(rf"{label_prefix}[ \t]*[:：]?[ \t]*(.+)", text, re.IGNORECASE)
        if labeled_match:
            cleaned_value = re.sub(r"\s+", " ", labeled_match.group(1)).strip(" :-\t")
            if cleaned_value:
                return cleaned_value
    return ""


def _find_pattern_after_label(text: str, label_patterns: list[str], value_pattern: str) -> str:
    """หาค่าที่ตรงกับ value_pattern ซึ่งตามหลังคำนำหน้าในบรรทัดเดียวกัน (ตัวช่วยกลางของฟิลด์เลขที่/เบอร์/วันที่)

    Args:
        text: ข้อความทั้งเอกสาร
        label_patterns: รายการ RegEx ของคำนำหน้า ลองตามลำดับ
        value_pattern: RegEx ของค่าที่ต้องการ (ไม่ต้องมีวงเล็บ capture)

    Returns:
        ค่าที่เจอ (ตัดช่องว่างหัวท้าย) หรือ "" ถ้าหาไม่เจอ
    """
    for label_pattern in label_patterns:
        label_prefix = rf"\b{label_pattern}" if label_pattern.isascii() else label_pattern
        # [^\w\n+]{0,15} = ยอมให้มี ":" หรือเว้นวรรคคั่นสั้น ๆ ในบรรทัดเดียวกัน
        labeled_match = re.search(
            rf"{label_prefix}[^\w\n+]{{0,15}}({value_pattern})", text, re.IGNORECASE
        )
        if labeled_match:
            return labeled_match.group(1).strip()
    return ""


def find_tel(text: str) -> str:
    """หาเบอร์โทรศัพท์ของบริษัท (คืนตามที่เขียนในเอกสาร ไม่แปลงรูปแบบ)

    ถ้าเป็น PR จะหาในกล่อง "บริษัทที่แนะนำให้ติดต่อ (Suggest source)" ก่อน (เบอร์ผู้ขาย ไม่ใช่เบอร์ผู้ร้องขอ)
    ไม่เจอจึงหาทั้งเอกสาร

    Args:
        text: ข้อความทั้งเอกสาร

    Returns:
        เบอร์โทร เช่น "02-123-4567" หรือ "" ถ้าหาไม่เจอ
    """
    try:
        suggest_section = _get_suggest_source_section(text)
        tel_number = ""
        if suggest_section:
            tel_number = _find_pattern_after_label(suggest_section, TEL_LABELS, TEL_NUMBER_PATTERN)
        if not tel_number:
            tel_number = _find_pattern_after_label(text, TEL_LABELS, TEL_NUMBER_PATTERN)
        return re.sub(r"\s+", " ", tel_number)
    except FIND_ERRORS as error:
        logger.warning("หาเบอร์โทรไม่สำเร็จ: %s", error)
        return ""


def find_pr_run_no(text: str) -> str:
    """หาเลขที่ PR เช่น "PR-2026-0012"

    Args:
        text: ข้อความทั้งเอกสาร

    Returns:
        เลขที่ PR หรือ "" ถ้าหาไม่เจอ
    """
    try:
        return _find_pattern_after_label(text, PR_NO_LABELS, DOCUMENT_NO_PATTERN)
    except FIND_ERRORS as error:
        logger.warning("หาเลขที่ PR ไม่สำเร็จ: %s", error)
        return ""


def _normalize_date_to_iso(day_text: str, month_text: str, year_text: str) -> str:
    """แปลงวัน/เดือน/ปี (ข้อความ) เป็น "YYYY-MM-DD" ค.ศ. ถ้าปีเป็น พ.ศ. จะลบ 543 ให้

    Args:
        day_text: วันที่ เช่น "5"
        month_text: เดือน เช่น "10"
        year_text: ปี เช่น "2569" (พ.ศ.) หรือ "2026" (ค.ศ.)

    Returns:
        วันที่รูปแบบ ISO หรือ "" ถ้าเป็นวันที่ที่ไม่มีจริง (เช่น 31/02)
    """
    year_number = int(year_text)
    if year_number > BUDDHIST_YEAR_THRESHOLD:
        year_number -= BUDDHIST_YEAR_OFFSET
    try:
        return date(year_number, int(month_text), int(day_text)).isoformat()
    except ValueError:
        return ""


def find_pr_request_date(text: str) -> str:
    """หาวันที่ PR แล้วแปลงเป็น "YYYY-MM-DD" (ค.ศ.) ตรงกับคอลัมน์ pr_request_date

    Args:
        text: ข้อความทั้งเอกสาร

    Returns:
        วันที่รูปแบบ ISO หรือ "" ถ้าหาไม่เจอ / วันที่ไม่ถูกต้อง
    """
    try:
        date_text = _find_pattern_after_label(text, PR_DATE_LABELS, DATE_PATTERN)
        date_parts = re.split(r"[/\-.]", date_text)
        if len(date_parts) != 3:
            return ""
        return _normalize_date_to_iso(*date_parts)
    except FIND_ERRORS as error:
        logger.warning("หาวันที่ PR ไม่สำเร็จ: %s", error)
        return ""


def find_qt_no(text: str) -> str:
    """หาเลขที่ Quotation เช่น "QT-2026-0345"

    Args:
        text: ข้อความทั้งเอกสาร

    Returns:
        เลขที่ Quotation หรือ "" ถ้าหาไม่เจอ
    """
    try:
        return _find_pattern_after_label(text, QT_NO_LABELS, DOCUMENT_NO_PATTERN)
    except FIND_ERRORS as error:
        logger.warning("หาเลขที่ Quotation ไม่สำเร็จ: %s", error)
        return ""


def find_description(text: str) -> str:
    """หารายละเอียดอุปกรณ์ (โครงร่าง: เอาข้อความที่เหลือของบรรทัดหลังคำว่า "รายละเอียด" / "Description")

    หมายเหตุ: เอกสารจริงมักเป็นตารางหลายบรรทัด ต้องปรับ Logic ให้ดึงหลายบรรทัดเมื่อเห็นรูปแบบจริง

    Args:
        text: ข้อความทั้งเอกสาร

    Returns:
        รายละเอียดอุปกรณ์ หรือ "" ถ้าหาไม่เจอ
    """
    try:
        return _find_text_after_label(text, DESCRIPTION_LABELS)
    except FIND_ERRORS as error:
        logger.warning("หารายละเอียดอุปกรณ์ไม่สำเร็จ: %s", error)
        return ""


def find_unit_price(text: str) -> str:
    """หาราคาสุทธิที่รวม Discount แล้ว (ตัวเลขหลังคำว่า "ราคาสุทธิ" / "Net Price" ฯลฯ)

    ถ้าคำนำหน้าปรากฏหลายที่ จะใช้ตำแหน่งสุดท้ายในเอกสาร (เหมือน find_total_amount)

    Args:
        text: ข้อความทั้งเอกสาร

    Returns:
        ราคาทศนิยม 2 ตำแหน่ง ไม่มีเครื่องหมาย "," เช่น "1500.50" หรือ "" ถ้าหาไม่เจอ
    """
    try:
        for label_pattern in UNIT_PRICE_LABELS:
            label_prefix = rf"\b{label_pattern}" if label_pattern.isascii() else label_pattern
            matches = re.findall(
                rf"{label_prefix}[^\d\n]{{0,25}}({MONEY_PATTERN})", text, re.IGNORECASE
            )
            if matches:
                return f"{float(matches[-1].replace(',', '')):.2f}"
        return ""
    except FIND_ERRORS as error:
        logger.warning("หาราคาสุทธิไม่สำเร็จ: %s", error)
        return ""


# ---------------------------------------------------------------------------
# ฟังก์ชันหลักที่หน้าฟอร์มเรียกใช้
# ---------------------------------------------------------------------------


# คำที่บ่งบอกว่าเอกสารเป็นใบกำกับภาษี (แก้/เพิ่มคำที่นี่ถ้า Vendor ใช้คำอื่น)
TAX_INVOICE_PATTERN: str = r"ใบกำกับภาษี|tax\s*invoice"
# คำที่อยู่ก่อนหน้าแล้วแปลว่าเป็นแค่การ "กล่าวถึง" ในเงื่อนไข/หมายเหตุ ไม่ใช่ตัวเอกสาร (เช่น "กรุณาออกใบกำกับภาษี")
TAX_INVOICE_MENTION_PREFIXES: tuple[str, ...] = (
    "ขอ", "ออก", "รอ", "ส่ง", "แนบ", "พร้อม", "กรุณา", "ต้องการ", "request", "issue", "send", "attach", "for",
)


def detect_tax_invoice(text: str) -> bool:
    """ตรวจว่าข้อความในไฟล์เป็น/มีใบกำกับภาษีหรือไม่ (ไม่โยน Error)

    นับเมื่อพบคำว่า "ใบกำกับภาษี" / "Tax Invoice" ที่ไม่ได้ตามหลังคำเชิงขอ/สัญญา เช่น "ขอ" "ออก" "กรุณา"
    (กันกรณีใบเสนอราคาที่เขียนเงื่อนไขว่า "จะออกใบกำกับภาษีให้ภายหลัง")

    Args:
        text: ข้อความทั้งเอกสาร

    Returns:
        True ถ้าพบคำว่าใบกำกับภาษีในฐานะตัวเอกสาร
    """
    try:
        for match in re.finditer(TAX_INVOICE_PATTERN, text or "", flags=re.IGNORECASE):
            text_before = text[max(0, match.start() - 12): match.start()].rstrip().lower()
            if not text_before.endswith(TAX_INVOICE_MENTION_PREFIXES):
                return True
        return False
    except (re.error, TypeError) as error:
        logger.warning("ตรวจใบกำกับภาษีไม่สำเร็จ: %s", error)
        return False


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
        tel=find_tel(text),
        pr_run_no=find_pr_run_no(text),
        pr_request_date=find_pr_request_date(text),
        qt_no=find_qt_no(text),
        description=find_description(text),
        unit_price=find_unit_price(text),
        has_tax_invoice=detect_tax_invoice(text),
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


def extract_fields_from_excel(excel_source: Optional[Union[str, BinaryIO]]) -> ExtractedFields:
    """อ่านไฟล์ Excel (.xlsx / .xls) แล้วดึงฟิลด์ทั้งหมดในขั้นตอนเดียว (ฟังก์ชันนี้ไม่โยน Error)

    กฎ Graceful Fallback: เปิดไฟล์ไม่ได้ หรือหาช่องไม่เจอ ฟิลด์นั้นจะเป็น "" แล้วให้ผู้ใช้กรอกในฟอร์มเอง

    Args:
        excel_source: path หรือ file object ของ Excel (None ได้ ถ้ายังไม่ได้อัปโหลด)

    Returns:
        ExtractedFields (ฟิลด์ที่หาไม่เจอเป็น "")
    """
    if excel_source is None:
        return ExtractedFields()
    return extract_fields_from_text(extract_text_from_excel(excel_source))


def extract_fields_from_file(file_source: Any, file_name: str) -> ExtractedFields:
    """เลือกวิธีอ่านตามนามสกุลไฟล์: .pdf -> PDF, .xlsx / .xls -> Excel (ฟังก์ชันนี้ไม่โยน Error)

    ถ้าจะรองรับไฟล์ชนิดใหม่: เพิ่มนามสกุลและเงื่อนไขตรงนี้

    Args:
        file_source: path หรือ file object ของไฟล์
        file_name: ชื่อไฟล์ (ใช้ดูนามสกุล)

    Returns:
        ExtractedFields (นามสกุลที่ไม่รองรับ เช่นรูปภาพ จะได้ฟิลด์ว่างทั้งหมด)
    """
    file_extension = Path(file_name or "").suffix.lower()
    if file_extension == ".pdf":
        extracted_fields = extract_fields_from_pdf(file_source)
    elif file_extension in EXCEL_EXTENSIONS:
        extracted_fields = extract_fields_from_excel(file_source)
    else:
        logger.info("ไม่ดึงข้อมูลอัตโนมัติ: ไม่รองรับนามสกุลไฟล์ '%s'", file_extension)
        return ExtractedFields()

    if extracted_fields.missing_field_labels:
        logger.info("ดึงข้อมูลจาก '%s' ได้ไม่ครบ: ขาด %s", file_name, ", ".join(extracted_fields.missing_field_labels))
    return extracted_fields
