"""ตัวสร้างไฟล์ PR จำลองสำหรับทดสอบ (โครงเดียวกับฟอร์ม Purchase Request จริง แต่เนื้อหาเป็นข้อมูลสมมติ)

ไม่ใช้ไฟล์จริงของผู้ใช้ จึงไม่มีข้อมูลจริงเข้า repo
"""

import io
from datetime import datetime
from typing import Optional

import openpyxl

PAGE_HEIGHT: int = 842
PAGE_WIDTH: int = 595

# พิกัด (x, top) ของป้ายในฟอร์ม อ้างจากไฟล์ PR จริง
ROW_FIRST_TOP: float = 231.0
ROW_STEP: float = 48.0


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def build_pdf(pages: list[list[tuple[float, float, str]]]) -> bytes:
    """สร้าง PDF จากข้อความที่วางตามพิกัด: แต่ละหน้าเป็นรายการ (x, top, ข้อความ) ใช้ฟอนต์ Helvetica 8 (ASCII เท่านั้น)"""
    objects: list[bytes] = [b"<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{3 + index * 2} 0 R" for index in range(len(pages)))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    font_id = 3 + len(pages) * 2
    for index, items in enumerate(pages):
        content_id = 4 + index * 2
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] /Contents {content_id} 0 R "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> >>".encode()
        )
        stream = "".join(
            f"BT /F1 8 Tf {x} {PAGE_HEIGHT - top - 8} Td ({_escape(text)}) Tj ET\n" for x, top, text in items
        ).encode()
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


def pr_form_items(
    items: list[tuple[str, str]],
    vendor: str = "Alpha Trading Co Ltd",
    tel: Optional[str] = "092-849-6930",
    dates: tuple[str, str, str] = ("19-Mar-26", "19-Mar-2026", "19-Mar-2026"),
    with_grand_total: bool = True,
) -> list[tuple[float, float, str]]:
    """ข้อความของฟอร์ม PR 1 หน้า (items = [(Description, Unit Price)])"""
    form: list[tuple[float, float, str]] = [
        (138, 90, "Purchase Request (PR)"),
        (424, 87, "PR Run No.:"),
        (30, 135, "Name):"),
        (195, 135, "Requester Person"),
        (92, 150, "(Tel.):"),
        (189, 150, "099-0547405"),
        (35, 207, "No."),
        (164, 207, "Description"),
        (324, 207, "Qty."),
        (442, 207, "Discount%"),
        (466, 468, "(Total)"),
        (150, 573, "(Suggest"),
        (191, 573, "source)"),
        (68, 585, "(Company):"),
        (120, 585, vendor),
        (327, 588, "E-Mail:"),
        (410, 585, "someone@example.com"),
        (92, 615, "(Tel.):"),
        (327, 615, "Quotation"),
        (372, 615, "Ref.:"),
        (80, 729, "(Requested"),
        (130, 729, "by)"),
    ]
    if tel:
        form.append((120, 615, tel))
    if with_grand_total:
        total = sum(float(price.replace(",", "")) for _, price in items)
        # ป้ายอยู่ต่ำกว่า (Total) ตามไฟล์จริง ตัวเลขต่ำกว่าป้ายราว 5 pt
        form += [(441, 517, "(Grand"), (473, 517, "Total)"), (523, 522, f"{total * 1.07:,.2f}")]
    for index, (description, price) in enumerate(items):
        top = ROW_FIRST_TOP + index * ROW_STEP
        form += [(42, top + 3, str(index + 1)), (65, top, description), (330, top + 3, "1"), (391, top + 3, price)]
    for (x, label_x), text in zip([(53, 111), (232, 283), (411, 459)], dates):
        form.append((x, 792, "Date:"))
        if text:
            form.append((label_x, 792, text))
    return form


def make_pr_pdf(
    items: list[tuple[str, str]],
    vendor: str = "Alpha Trading Co Ltd",
    tel: Optional[str] = "092-849-6930",
    dates: tuple[str, str, str] = ("19-Mar-26", "19-Mar-2026", "19-Mar-2026"),
    extra_pages: int = 0,
    with_grand_total: bool = True,
) -> bytes:
    """PDF ฟอร์ม PR 1 ใบ (ต่อท้ายด้วยหน้าที่ไม่ใช่ฟอร์ม extra_pages หน้า)"""
    pages = [pr_form_items(items, vendor, tel, dates, with_grand_total)]
    pages += [[(40, 100, "Terms and conditions")] for _ in range(extra_pages)]
    return build_pdf(pages)


def make_text_pdf(text: str) -> bytes:
    """PDF ข้อความบรรทัดเดียว (ใช้เป็นใบเสนอราคา/ใบกำกับภาษีจำลอง ไม่ใช่ฟอร์ม PR)"""
    return build_pdf([[(40, 60, text)]])


def make_pr_excel(
    items: list[tuple[str, float]],
    vendor: str = "Alpha Trading Co Ltd",
    tel: Optional[str] = "092-849-6930",
    when: datetime = datetime(2026, 3, 19),
    with_grand_total: bool = True,
) -> bytes:
    """ไฟล์ Excel ฟอร์ม PR 1 ใบ ตำแหน่งเซลล์เหมือนไฟล์จริง (เลขลำดับอยู่คอลัมน์ C คนละคอลัมน์กับหัว No. ใน B)"""
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "PR"
    sheet["B7"] = "Purchase Request (PR)"
    sheet["AE7"] = "PR Run No.:"
    sheet["B11"] = "โทรศัพท์ (Tel.):"
    sheet["I11"] = "099-0547405"
    sheet["B14"], sheet["E14"], sheet["W14"], sheet["Z14"] = "No.", "Description", "Qty.", "Unit Price"
    for index, (description, price) in enumerate(items):
        row = 16 + index * 2
        sheet.cell(row, 3, index + 1)
        sheet.cell(row, 5, description)
        sheet.cell(row, 24, 1)
        sheet.cell(row, 26, price)
        sheet.cell(row + 1, 5, "continuation line")
    sheet["W27"] = "ราคารวม (Total)"
    if with_grand_total:
        total = sum(price for _, price in items)
        sheet["W29"] = "ราคารวมหลังภาษีมูลค่าเพิ่ม (Grand Total)\nบาท (Baht)"
        sheet["AJ29"] = round(total * 1.07, 2)
    sheet["B31"] = "บริษัทที่แนะนำให้ติดต่อ  (Suggest source) "
    sheet["B32"], sheet["I32"], sheet["X32"] = "บริษัท (Company):", vendor, "E-Mail:"
    sheet["B34"], sheet["X34"] = "โทรศัพท์ (Tel.):", "Quotation Ref.:"
    if tel:
        sheet["I34"] = tel
    sheet["B44"] = "ผู้ร้องขอสั่งซื้อ\n(Requested by)"
    sheet["C48"], sheet["F48"], sheet["P48"], sheet["AC48"] = "Date:", when, "Date:", "Date:"
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()
