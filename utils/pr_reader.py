"""อ่านค่าจากไฟล์ PR (Excel หรือ PDF) ตามโครงฟอร์ม Purchase Request และสร้างกุญแจ "PR เดียวกัน"

ค่าที่อ่าน (ตรงกับคอลัมน์ในตาราง):
- Date        = ช่อง Date ใต้ลายเซ็น "ผู้ร้องขอ (Requested by)" (ว่างจึงใช้ช่องผู้ตรวจสอบ แล้วผู้อนุมัติ)
- Description = Description ของตาราง "รายการที่ต้องการให้จัดซื้อ" (หลายรายการ = รายการแรก + " (+N รายการ)")
- Price       = "ราคารวมหลังภาษีมูลค่าเพิ่ม (Grand Total)" (ไม่พบบรรทัดนี้ใช้ผลรวม Unit Price ของทุกรายการแทน)
- Vendor      = "บริษัท (Company)" ในกล่อง "บริษัทที่แนะนำให้ติดต่อ (Suggest source)"
- Tel.        = "โทรศัพท์ (Tel.)" ในกล่องเดียวกัน

PDF อ่านตามพิกัดโดยยึดป้ายภาษาอังกฤษ (ลำดับข้อความใน PDF สลับ และ "(Tel.):" มีสองที่) ส่วนข้อความไทยต้องอ่านตามลำดับตัวอักษร
ในไฟล์ (ไม่เรียงตามตำแหน่ง ไม่อย่างนั้นสระ/วรรณยุกต์จะเลื่อนที่) ไฟล์นี้ไม่เรียก Streamlit และไม่เขียนไฟล์
"""

import io
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any, Optional

import openpyxl
import pdfplumber

from config.logging_setup import get_logger
from utils.text_extractor import find_pr_document_date

logger = get_logger(__name__)

# ป้ายภาษาอังกฤษของฟอร์ม (ใช้ยึดตำแหน่ง ไม่ใช้ข้อความไทยเพราะ PDF อ่านไทยเพี้ยนได้)
LABEL_PURCHASE: str = "Purchase"
LABEL_SUGGEST: str = "(Suggest"
LABEL_COMPANY: str = "(Company):"
LABEL_TEL: str = "(Tel.):"
LABEL_REQUESTED: str = "(Requested"
LABEL_DATE: str = "Date:"
LABEL_DESCRIPTION: str = "Description"
LABEL_ITEM_NO: str = "No."
LABEL_QTY: str = "Qty."
LABEL_DISCOUNT: str = "Discount%"
LABEL_TOTAL: str = "(Total)"
LABEL_UNIT_PRICE: str = "unit price"
LABEL_GRAND: str = "(Grand"
LABEL_GRAND_EXCEL: str = "grand total"
GRAND_VALUE_DOWN: float = 8.0  # ตัวเลขยอดรวมอยู่ต่ำกว่าป้ายเล็กน้อยได้เท่านี้
LABEL_PR_RUN_NO: str = "PR Run No.:"

KEY_FIELD_LABELS: dict[str, str] = {
    "description": "รายการ (Description)",
    "vendor": "บริษัท (Company)",
    "tel": "เบอร์โทรศัพท์ (Tel.)",
}

# ขอบเขตการหาค่าในรูปแบบพิกัด PDF (หน่วย point)
LINE_BAND: float = 4.0  # ค่าที่อยู่ "บรรทัดเดียวกับป้าย" ต่างกันของ top ได้เท่านี้
ITEM_ROW_UP: float = 8.0  # ข้อความของรายการอยู่เหนือเลขลำดับได้เท่านี้
ITEM_ROW_DOWN: float = 2.0
NUMBER_COLUMN_MARGIN: float = 10.0
TABLE_TEXT_MARGIN: float = 10.0  # ช่องว่างระหว่างคอลัมน์ No. กับข้อความ Description

# อักขระไทยที่ตัดออกตอนเทียบ: สระและวรรณยุกต์ (PDF กับ Excel สะกดสระต่างกันได้ จึงเทียบเฉพาะพยัญชนะ)
THAI_VOWEL_RANGES: tuple[tuple[int, int], ...] = ((0x0E30, 0x0E3A), (0x0E40, 0x0E4E))
ITEM_SUMMARY_FORMAT: str = "{first} (+{more} รายการ)"

PDF_SUFFIX: str = ".pdf"
EXCEL_SUFFIXES: tuple[str, ...] = (".xlsx",)  # openpyxl อ่าน .xls เก่าไม่ได้


@dataclass
class PrDocument:
    """ค่าที่อ่านได้จาก PR 1 ใบ (ทุกช่องเป็น "" / None ถ้าอ่านไม่ได้)"""

    description: str = ""  # รายการแรก (+N รายการ) ถ้ามีหลายรายการ
    item_count: int = 0
    items: list[str] = field(default_factory=list)  # ชื่อทุกรายการ (ใช้จับคู่ไฟล์อื่นเข้า PR)
    unit_price: Optional[float] = None  # ผลรวม Unit Price ของทุกรายการ
    grand_total: Optional[float] = None  # ราคารวมหลังภาษีมูลค่าเพิ่ม (None = ไม่พบบรรทัดนี้)
    vendor: str = ""
    tel: str = ""
    date: str = ""  # YYYY-MM-DD
    pr_run_no: str = ""

    @property
    def missing_key_fields(self) -> list[str]:
        """ชื่อช่องในกุญแจจับคู่ที่อ่านไม่ได้ (ว่าง = ใช้จับคู่ได้)"""
        values = {"description": self.description, "vendor": self.vendor, "tel": self.tel}
        return [label for key, label in KEY_FIELD_LABELS.items() if not _normalize_field(key, values[key])]

    @property
    def identity_key(self) -> Optional[tuple[str, str, str]]:
        """กุญแจ "PR เดียวกัน" ต้องมีครบทั้ง 3 ช่อง ไม่อย่างนั้น None (ไม่ใช้จับคู่ ไม่เดา)"""
        return build_identity_key(self.description, self.vendor, self.tel)


@dataclass
class PdfSection:
    """ช่วงหน้าของ PDF ที่เป็น PR ใบเดียวกัน"""

    page_numbers: list[int] = field(default_factory=list)
    document: Optional[PrDocument] = None  # None = ไม่พบฟอร์ม PR (เช่น ไฟล์สแกน)


# ---------------------------------------------------------------------------
# กุญแจ "PR เดียวกัน"
# ---------------------------------------------------------------------------


def _is_thai_vowel_or_mark(char: str) -> bool:
    code = ord(char)
    return any(low <= code <= high for low, high in THAI_VOWEL_RANGES)


def _skeleton(text: str) -> str:
    """ข้อความแบบเทียบได้: ไม่สนตัวพิมพ์ ช่องว่าง เครื่องหมาย และสระ/วรรณยุกต์ไทย เหลือเฉพาะตัวอักษรกับตัวเลข"""
    folded = unicodedata.normalize("NFKC", text or "").casefold()
    return "".join(char for char in folded if char.isalnum() and not _is_thai_vowel_or_mark(char))


def _normalize_field(field_name: str, value: Any) -> str:
    text = str(value or "")
    if field_name == "tel":
        return re.sub(r"\D", "", text)
    return _skeleton(text)


def build_identity_key(description: Any, vendor: Any, tel: Any) -> Optional[tuple[str, str, str]]:
    """กุญแจ PR เดียวกันจาก Description + Company + Tel (ต้องไม่ว่างทั้ง 3 ช่อง)

    ไฟล์ Excel กับ PDF ของ PR เดียวกันได้กุญแจเดียวกัน แม้สะกดสระไทยต่างกัน (เทียบเฉพาะพยัญชนะ) หรือใส่ขีดในเบอร์ต่างกัน
    """
    key = (
        _normalize_field("description", description),
        _normalize_field("vendor", vendor),
        _normalize_field("tel", tel),
    )
    return key if all(key) else None


def summarize_items(descriptions: list[str]) -> str:
    """Description ของ PR ที่มีหลายรายการ: รายการแรก + " (+N รายการ)" """
    cleaned = [" ".join(text.split()) for text in descriptions if text and text.strip()]
    if not cleaned:
        return ""
    if len(cleaned) == 1:
        return cleaned[0]
    return ITEM_SUMMARY_FORMAT.format(first=cleaned[0], more=len(cleaned) - 1)


# ---------------------------------------------------------------------------
# ตัวช่วยแปลงค่า
# ---------------------------------------------------------------------------


def _parse_money(value: Any) -> Optional[float]:
    """แปลง "29,500.00" / 29500 เป็น float (อ่านไม่ได้ = None)"""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    match = re.search(r"\d[\d,]*(?:\.\d+)?", str(value or ""))
    if not match:
        return None
    try:
        return float(match.group(0).replace(",", ""))
    except ValueError:
        return None


def _parse_date_value(value: Any) -> str:
    """แปลงค่าวันที่ (datetime หรือข้อความเช่น "19-Mar-26") เป็น YYYY-MM-DD ("" = อ่านไม่ได้)"""
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    text = str(value or "").strip()
    return find_pr_document_date(f"Date: {text}") if text else ""


def _collapse(text: str) -> str:
    return " ".join(text.split())


def _first_valid_date(values: list[Any]) -> str:
    return next((iso for iso in map(_parse_date_value, values) if iso), "")


# ---------------------------------------------------------------------------
# PDF
# ---------------------------------------------------------------------------


def _find_words(words: list[dict[str, Any]], text: str) -> list[dict[str, Any]]:
    """คำที่ลงท้ายด้วย text (ป้ายอาจติดกับตัวอักษรไทยหน้ามัน)"""
    return [word for word in words if word["text"].endswith(text)]


def _chars_text(
    chars: list[dict[str, Any]], x_min: float, x_max: float, top_min: float, top_max: float
) -> str:
    """ข้อความจากตัวอักษรในกรอบ เรียงตามลำดับในไฟล์ (ไม่เรียงตามตำแหน่ง เพื่อให้สระ/วรรณยุกต์ไทยอยู่ถูกที่)"""
    picked: list[str] = []
    for char in chars:
        is_zero_width_space = char["text"].isspace() and (char["x1"] - char["x0"]) < 0.5
        if is_zero_width_space:
            continue
        if x_min <= char["x0"] < x_max and top_min <= char["top"] <= top_max:
            picked.append(char["text"])
    return _collapse("".join(picked))


def _value_right_of(
    chars: list[dict[str, Any]], label: dict[str, Any], stop_x: Optional[float], page_width: float
) -> str:
    """ข้อความทางขวาของป้ายในบรรทัดเดียวกัน จนถึงป้ายถัดไป (stop_x)"""
    return _chars_text(
        chars,
        label["x1"] + 0.5,
        (stop_x - 1) if stop_x is not None else page_width,
        label["top"] - LINE_BAND,
        label["top"] + LINE_BAND,
    )


def _same_line(words: list[dict[str, Any]], label: dict[str, Any]) -> list[dict[str, Any]]:
    return [word for word in words if abs(word["top"] - label["top"]) <= LINE_BAND and word is not label]


def _next_label_x(words: list[dict[str, Any]], label: dict[str, Any], suffixes: tuple[str, ...]) -> Optional[float]:
    """x ของป้ายถัดไปทางขวาในบรรทัดเดียวกัน (ใช้กั้นค่าไม่ให้ล้ำไปช่องอื่น)"""
    candidates = [
        word["x0"]
        for word in _same_line(words, label)
        if word["x0"] > label["x1"] and word["text"].endswith(suffixes)
    ]
    return min(candidates) if candidates else None


def _is_pr_form_page(words: list[dict[str, Any]]) -> bool:
    texts = {word["text"] for word in words}
    return LABEL_PURCHASE in texts and LABEL_SUGGEST in texts and LABEL_DESCRIPTION in texts


def _read_pdf_items(page: Any, words: list[dict[str, Any]]) -> tuple[list[str], list[float]]:
    """รายการในตาราง "รายการที่ต้องการให้จัดซื้อ": (Description, Unit Price) ของแต่ละแถวที่มีเลขลำดับ"""
    header = next((word for word in words if word["text"] == LABEL_DESCRIPTION), None)
    if header is None:
        return [], []
    on_header = [word for word in words if abs(word["top"] - header["top"]) <= LINE_BAND]
    no_header = next((word for word in on_header if word["text"] == LABEL_ITEM_NO), None)
    qty_header = next((word for word in on_header if word["text"] == LABEL_QTY), None)
    discount_header = next((word for word in on_header if word["text"] == LABEL_DISCOUNT), None)
    if no_header is None or qty_header is None or discount_header is None:
        return [], []
    end_top = min(
        (word["top"] for word in words if word["text"] == LABEL_TOTAL and word["top"] > header["top"]),
        default=float(page.height),
    )
    number_words = sorted(
        (
            word
            for word in words
            if word["text"].isdigit()
            and no_header["x0"] - NUMBER_COLUMN_MARGIN <= word["x0"] <= no_header["x1"] + NUMBER_COLUMN_MARGIN
            and header["top"] + LINE_BAND < word["top"] < end_top
        ),
        key=lambda word: word["top"],
    )
    descriptions: list[str] = []
    prices: list[float] = []
    for number in number_words:
        text = _chars_text(
            page.chars,
            no_header["x1"] + TABLE_TEXT_MARGIN,
            qty_header["x0"] - 3,
            number["top"] - ITEM_ROW_UP,
            number["top"] + ITEM_ROW_DOWN,
        )
        price_text = _chars_text(
            page.chars,
            qty_header["x1"],
            discount_header["x0"],
            number["top"] - LINE_BAND,
            number["top"] + LINE_BAND,
        )
        descriptions.append(text)
        price = _parse_money(price_text)
        if price is not None:
            prices.append(price)
    return descriptions, prices


def _read_pdf_page(page: Any) -> Optional[PrDocument]:
    """อ่านค่าจากหน้าที่เป็นฟอร์ม PR (หน้าที่ไม่ใช่ฟอร์มคืน None)"""
    words = page.extract_words(use_text_flow=True)
    if not _is_pr_form_page(words):
        return None
    document = PrDocument()
    width = float(page.width)

    suggest = next(iter(_find_words(words, LABEL_SUGGEST)), None)
    if suggest is not None:
        company = next((w for w in _find_words(words, LABEL_COMPANY) if w["top"] > suggest["top"] - 2), None)
        if company is not None:
            stop = _next_label_x(words, company, ("E-Mail:",))
            document.vendor = _value_right_of(page.chars, company, stop, width)
        tel = next((w for w in _find_words(words, LABEL_TEL) if w["top"] > suggest["top"] - 2), None)
        if tel is not None:
            stop = _next_label_x(words, tel, ("Quotation", "Ref.:"))
            document.tel = _value_right_of(page.chars, tel, stop, width)

    descriptions, prices = _read_pdf_items(page, words)
    document.description = summarize_items(descriptions)
    document.item_count = len([text for text in descriptions if text.strip()])
    document.items = [text.strip() for text in descriptions if text.strip()]
    document.unit_price = sum(prices) if prices else None
    grand = next(iter(_find_words(words, LABEL_GRAND)), None)
    if grand is not None:
        document.grand_total = _parse_money(
            _chars_text(page.chars, grand["x1"] + 0.5, width, grand["top"] - 2, grand["top"] + GRAND_VALUE_DOWN)
        )

    requested = next(iter(_find_words(words, LABEL_REQUESTED)), None)
    signature_top = requested["top"] if requested is not None else float(page.height) * 0.6
    date_labels = sorted(
        (w for w in _find_words(words, LABEL_DATE) if w["top"] > signature_top), key=lambda word: word["x0"]
    )
    date_values: list[str] = []
    for label in date_labels:
        stop = min((w["x0"] for w in date_labels if w["x0"] > label["x0"]), default=None)
        date_values.append(_value_right_of(page.chars, label, stop, width))
    document.date = _first_valid_date(date_values)

    run_no = next((w for w in _find_words(words, "No.:") if w["top"] < signature_top), None)
    if run_no is not None:
        document.pr_run_no = _value_right_of(page.chars, run_no, None, width)
    return document


def read_pdf_sections(data: bytes) -> list[PdfSection]:
    """แบ่ง PDF เป็นช่วงหน้าต่อ PR 1 ใบ: หน้าที่เป็นฟอร์ม PR เริ่ม PR ใหม่ หน้าอื่นเป็นของ PR ก่อนหน้า

    หน้าก่อนฟอร์มแรกรวมเข้า PR แรก ไม่พบฟอร์มเลย (เช่น ไฟล์สแกน หรือไฟล์เสีย) = ช่วงเดียวที่ document เป็น None
    """
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            sections: list[PdfSection] = []
            leading_pages: list[int] = []
            for number, page in enumerate(pdf.pages, start=1):
                document = _read_pdf_page(page)
                if document is not None:
                    sections.append(PdfSection([*leading_pages, number], document))
                    leading_pages = []
                elif sections:
                    sections[-1].page_numbers.append(number)
                else:
                    leading_pages.append(number)
            if not sections:
                return [PdfSection(leading_pages, None)]
            return sections
    except Exception as error:  # noqa: BLE001 - ไฟล์จากผู้ใช้เสียได้หลายแบบ ต้องไม่ทำให้การอัปโหลดทั้งชุดล้ม
        logger.warning("อ่านโครงฟอร์ม PR จาก PDF ไม่สำเร็จ: %s", type(error).__name__)
        return [PdfSection([], None)]


# ---------------------------------------------------------------------------
# Excel
# ---------------------------------------------------------------------------


def _cell_text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _find_cells(sheet: Any, needle: str) -> list[tuple[int, int]]:
    """เซลล์ (แถว, คอลัมน์) ที่มีข้อความนี้ เรียงตามแถวแล้วคอลัมน์"""
    found: list[tuple[int, int]] = []
    lowered = needle.lower()
    for row in sheet.iter_rows():
        for cell in row:
            if isinstance(cell.value, str) and lowered in cell.value.lower():
                found.append((cell.row, cell.column))
    return found


def _value_right_of_cell(sheet: Any, row: int, column: int, stop_column: Optional[int] = None) -> Any:
    """ค่าแรกที่ไม่ว่างทางขวาของป้าย ถ้าเจอป้ายอื่น (ลงท้ายด้วย ":") ก่อน แปลว่าช่องนี้ว่าง"""
    last = (stop_column - 1) if stop_column else sheet.max_column
    for col in range(column + 1, last + 1):
        value = sheet.cell(row, col).value
        text = _cell_text(value)
        if not text:
            continue
        return None if text.endswith(":") else value
    return None


def _read_excel_sheet(sheet: Any) -> Optional[PrDocument]:
    """อ่านค่าจาก 1 sheet ที่เป็นฟอร์ม PR (ไม่ใช่ฟอร์มคืน None) โดยค้นป้ายก่อน ไม่ฟิกซ์เลขเซลล์"""
    purchase = _find_cells(sheet, "Purchase Request")
    suggest_cells = _find_cells(sheet, "(Suggest source)")
    description_header = [
        cell for cell in _find_cells(sheet, LABEL_DESCRIPTION) if _cell_text(sheet.cell(*cell).value).lower() == "description"
    ]
    if not purchase or not suggest_cells or not description_header:
        return None
    document = PrDocument()
    suggest_row = suggest_cells[0][0]

    company = next((cell for cell in _find_cells(sheet, LABEL_COMPANY) if cell[0] > suggest_row), None)
    if company:
        document.vendor = _collapse(_cell_text(_value_right_of_cell(sheet, *company)))
    tel = next((cell for cell in _find_cells(sheet, LABEL_TEL) if cell[0] > suggest_row), None)
    if tel:
        document.tel = _collapse(_cell_text(_value_right_of_cell(sheet, *tel)))

    header_row, description_col = description_header[0]
    columns: dict[str, int] = {}
    for col in range(1, sheet.max_column + 1):
        text = _cell_text(sheet.cell(header_row, col).value).lower()
        if text == "no.":
            columns["no"] = col
        elif text.startswith(LABEL_UNIT_PRICE):
            columns["price"] = col
    descriptions: list[str] = []
    prices: list[float] = []
    if "no" in columns:
        for row in range(header_row + 1, sheet.max_row + 1):
            row_texts = " ".join(_cell_text(sheet.cell(row, col).value) for col in range(1, sheet.max_column + 1))
            if LABEL_TOTAL in row_texts or "Ship To" in row_texts:
                break
            # เลขลำดับอาจอยู่คนละคอลัมน์กับหัว "No." (เซลล์ที่ merge) จึงดูทุกคอลัมน์ตั้งแต่ No. ถึงก่อน Description
            numbers = [sheet.cell(row, col).value for col in range(columns["no"], description_col)]
            if not any(isinstance(n, (int, float)) or _cell_text(n).isdigit() for n in numbers if n is not None):
                continue
            descriptions.append(_cell_text(sheet.cell(row, description_col).value))
            price = _parse_money(sheet.cell(row, columns["price"]).value) if "price" in columns else None
            if price is not None:
                prices.append(price)
    document.description = summarize_items(descriptions)
    document.item_count = len([text for text in descriptions if text.strip()])
    document.items = [text.strip() for text in descriptions if text.strip()]
    document.unit_price = sum(prices) if prices else None
    grand = next(iter(_find_cells(sheet, LABEL_GRAND_EXCEL)), None)
    if grand:
        document.grand_total = _parse_money(_value_right_of_cell(sheet, *grand))

    requested = next(iter(_find_cells(sheet, "(Requested by)")), None)
    signature_row = requested[0] if requested else 0
    date_labels = sorted(
        (cell for cell in _find_cells(sheet, LABEL_DATE) if cell[0] > signature_row and _cell_text(sheet.cell(*cell).value) == LABEL_DATE),
        key=lambda cell: (cell[0], cell[1]),
    )
    date_values: list[Any] = []
    for row, col in date_labels:
        stop = min((c for r, c in date_labels if r == row and c > col), default=None)
        date_values.append(_value_right_of_cell(sheet, row, col, stop))
    document.date = _first_valid_date(date_values)

    run_no = next(iter(_find_cells(sheet, LABEL_PR_RUN_NO)), None)
    if run_no:
        document.pr_run_no = _collapse(_cell_text(_value_right_of_cell(sheet, *run_no)))
    return document


def read_pr_excel(data: bytes) -> Optional[PrDocument]:
    """อ่านค่าจากไฟล์ Excel ที่เป็นฟอร์ม PR (ไม่ใช่ฟอร์ม/อ่านไม่ได้ = None) นับเป็น PR 1 ใบต่อไฟล์"""
    try:
        workbook = openpyxl.load_workbook(io.BytesIO(data), data_only=True)
        for sheet in workbook.worksheets:
            document = _read_excel_sheet(sheet)
            if document is not None:
                return document
        return None
    except Exception as error:  # noqa: BLE001 - ไฟล์จากผู้ใช้เสียได้หลายแบบ
        logger.warning("อ่านฟอร์ม PR จาก Excel ไม่สำเร็จ: %s", type(error).__name__)
        return None


_ITEM_NAMES_CACHE: dict[tuple[str, int], list[str]] = {}


def read_item_names(path: Path) -> list[str]:
    """ชื่อทุกรายการของไฟล์ PR (PDF/Excel) ที่เก็บในเครื่อง ไม่ใช่ฟอร์ม PR/อ่านไม่ได้ = [] (ไม่โยน Error)

    จำผลตาม (ที่อยู่ไฟล์, เวลาแก้ไข) ไว้ จึงไม่อ่านไฟล์ซ้ำทุกครั้งที่อัปโหลด
    """
    suffix = path.suffix.lower()
    if suffix != PDF_SUFFIX and suffix not in EXCEL_SUFFIXES:
        return []
    try:
        key = (str(path), path.stat().st_mtime_ns)
        if key in _ITEM_NAMES_CACHE:
            return _ITEM_NAMES_CACHE[key]
        data = path.read_bytes()
    except OSError:
        return []
    names: list[str] = []
    if suffix == PDF_SUFFIX:
        for section in read_pdf_sections(data):
            if section.document is not None:
                names.extend(section.document.items)
    else:
        document = read_pr_excel(data)
        names = list(document.items) if document is not None else []
    _ITEM_NAMES_CACHE[key] = names
    return names
