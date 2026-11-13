"""สร้างไฟล์ Excel ฟอร์ม Purchase Request (PR) จาก Dictionary ที่ได้จาก extractor.py"""
import io
import math
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from openpyxl import Workbook
from openpyxl.cell.rich_text import CellRichText, TextBlock
from openpyxl.cell.text import InlineFont
from openpyxl.drawing.image import Image as XlImage
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, OneCellAnchor, TwoCellAnchor
from openpyxl.drawing.xdr import XDRPositiveSize2D
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.styles.colors import Color
from openpyxl.utils import column_index_from_string, get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

# ---------- ค่าคงที่ ----------
# จุดแบ่งคอลัมน์ (pt) วัดจาก PDF ตัวอย่าง: A และ O คือขอบกรอบนอก ส่วน B:N คือเนื้อฟอร์ม
COLUMN_EDGES = (12, 22, 64, 119, 202, 257, 312, 326, 353, 381, 409, 422, 436, 491, 574, 583)
FIRST_COL, LAST_COL = "A", "O"
DESC_CHARS = 58  # จำนวนตัวอักษรต่อบรรทัดของช่อง Description ใช้ประมาณความสูงแถว
MIN_TABLE_ROWS = 10  # จำนวนแถวขั้นต่ำของตารางสินค้า (เติมแถวว่างให้เหมือนฟอร์มจริง)
ITEM_ROW_HEIGHT = 24

COMPANY_NAME = "M.J. Bangkok Valve & Fitting Co., Ltd."
COMPANY_ADDRESS = "88/8-10 Moo 14, Kingkaew Road, Rachatewa, Bangplee,\nSamutprakarn 10540 Thailand"
TITLE = "Purchase Request (PR)"
FORM_CODE = "SF-SLD-NA-006, Rev.05, 01-07-2023"
TABLE_HEADERS = (("B", "B", "No."), ("C", "F", "Description"), ("G", "H", "Qty."),
                 ("I", "L", "Unit Price\n(Baht)"), ("M", "M", "Discount%"), ("N", "N", "Total\n(Baht)"))

ASSETS = Path(__file__).parent / "assets"
LOGO_TEXT = "Swagelok Thailand"
LOGO_SIZE = (152, 56)  # px ขนาดสูงสุดของโลโก้
LOGO_FILE = ASSETS / "logo.png"  # โลโก้จริงของบริษัท
LOGO_BOX = ("L", 2, "N", 4)  # กล่องโลโก้: คอลัมน์ซ้าย, แถวบน, คอลัมน์ขวา, แถวล่าง
LOGO_BOX_SIZE = (203, 84)  # px ขนาดอ้างอิงของกล่อง (152 x 63 pt)

# มีเฉพาะข้อมูลผู้ร้องขอ ส่วนผู้ตรวจสอบ/ผู้อนุมัติเว้นลายเซ็น ตำแหน่ง และวันที่ให้กรอกเอง
# image = (ไฟล์, คอลัมน์รูป, ระยะจากขอบซ้าย, ระยะจากขอบบน, กว้าง, สูง) หน่วย pt
SIGNATURES = (
    {"title": "ผู้ร้องขอสั่งซื้อ\n(Requested by)", "position": "Aidthikon",
     "image": ("signature_requested.png", "C", 38.7, 1, 57.7, 21.8)},
    {"title": "ผู้ตรวจสอบคำร้องขอสั่งซื้อ\n(Approved by)"},
    {"title": "ผู้อนุมัติคำร้องขอสั่งซื้อ\n(Authorized by)"},
)
THAI_TZ = timezone(timedelta(hours=7))  # เวลาไทย: วันที่ไม่เพี้ยนแม้แอปรันบนเซิร์ฟเวอร์เขตเวลาอื่น
# กล่องลายเซ็น: (คอลัมน์แรกของกล่อง, คอลัมน์สุดท้าย, ป้ายจบที่คอลัมน์, ช่องค่าเริ่มที่คอลัมน์)
SIGNATURE_BOXES = (("B", "D", "B", "C"), ("E", "I", "E", "F"), ("J", "N", "L", "M"))

# ข้อมูลผู้ร้องขอและเงื่อนไขชำระเงินคงที่ทุกไฟล์ ไม่อ่านจากใบเสนอราคา
REQUESTER = {"name": "Aidthikon", "tel": "08-6348-1488", "email": "aidthikon.ka@mjbangkok.com", "fax": "-"}
PAYMENT_LINE = "เงื่อนไขการชำระเงิน (Terms of payment):   ☐ Cash    ☑ Credit 30 days"
REMARK_CHARS = 62  # จำนวนตัวอักษรต่อบรรทัดของช่องหมายเหตุ ใช้ประมาณความสูงแถว
REMARK_LINE_HEIGHT = 11  # pt ต่อ 1 บรรทัดของช่องหมายเหตุ (ตัวอักษรขนาด 8)
REMARK_ROW_HEIGHTS = (18, 19)  # ความสูงเดิมของ 2 แถวในช่องหมายเหตุ

# ใบเสนอราคาบางแบบเก็บชื่อบริษัทผู้ขายเป็นรูปภาพ จึงเทียบจากโดเมนอีเมลแทน
SUPPLIER_BY_DOMAIN = {"addin.co.th": "บริษัท แอด อิน บิซเนส จำกัด"}

NUMBER_FORMAT = "#,##0.00"
LATIN_FONT = "Calibri"
THAI_FONT = "Tahoma"
HEADER_FONT = "Century Gothic"
BLUE = "0000FF"
GREEN = "008000"
YELLOW_FILL = PatternFill("solid", start_color="FFFF99")
LINE_HEIGHT = 13  # pt ต่อ 1 บรรทัด ใช้ประมาณความสูงแถว (openpyxl ไม่มี auto-fit)
# ก้อนข้อความไทย (รวมช่องว่างระหว่างคำไทยไว้ในก้อนเดียวกัน)
THAI_RUN = re.compile(r"([฀-๿]+(?: +[฀-๿]+)*)")

# เส้นขอบ: กล่องทุกกล่องเป็นเส้นบาง ส่วนกรอบนอกทั้งหน้าเป็นเส้นหนา
THIN = Side(style="thin")
THICK = Side(style="thick")
DASHED = Side(style="dashed")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
LINE_ONLY = Border(bottom=THIN)  # เส้นขีดเขียนที่อยู่ Ship To
DASH_ONLY = Border(bottom=DASHED)  # เส้นประในกล่องลายเซ็น


def _text(value: Any) -> str:
    # None -> "" เพื่อไม่ให้ Excel แสดงคำว่า None
    return "" if value is None else str(value)


def _to_float(value: Any) -> float | None:
    # แปลง "29,500.00" เป็นตัวเลขจริง เพื่อให้ number_format ทำงาน
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


def _num_or_text(value: Any) -> Any:
    # ถ้าแปลงเป็นตัวเลขได้ให้ใช้ตัวเลข ไม่ได้ก็คงข้อความเดิม (เช่น Qty ที่เป็นข้อความ)
    num = _to_float(value)
    return num if num is not None else _text(value)


def _column_width(points: float) -> float:
    # แปลงความกว้าง pt เป็นหน่วยคอลัมน์ของ Excel (Calibri 11: 7px ต่อ 1 หน่วย + padding 5px)
    return max((points * 96 / 72 - 5) / 7, 0.1)


def _mixed_text(text: str, font: Font) -> Any:
    """ข้อความไทยปนอังกฤษ: ไทยใช้ Tahoma อังกฤษใช้ Calibri เหมือนฟอร์มต้นแบบ"""
    runs: list[str] = []
    for run in THAI_RUN.split(text.strip()):
        if run.isspace() and runs:  # ก้อนที่มีแต่ช่องว่าง/ขึ้นบรรทัด ทำให้ Excel เปิดไฟล์ไม่ได้ จึงรวมกับก้อนก่อนหน้า
            runs[-1] += run
        elif run:
            runs.append(run)
    if len(runs) < 2:
        return text
    color = Color(rgb=f"00{font.color.rgb[-6:]}") if font.color is not None else None
    return CellRichText(*[
        TextBlock(InlineFont(rFont=THAI_FONT if THAI_RUN.search(run) else LATIN_FONT, sz=font.sz,
                             b=font.b, u=font.u, color=color), run)
        for run in runs
    ])


def _put(ws: Worksheet, ref: str, value: Any, *, bold: bool = False, size: int = 10,
         h: str = "left", v: str = "center", wrap: bool = False, color: str | None = None,
         fill: PatternFill | None = None, fmt: str | None = None, underline: str | None = None,
         font: str | None = None, indent: int = 0) -> None:
    """เขียนค่าลงเซลล์พร้อมจัดรูปแบบในครั้งเดียว"""
    cell = ws[ref]
    is_thai = isinstance(value, str) and THAI_RUN.search(value) is not None
    base = Font(name=font or (THAI_FONT if is_thai else LATIN_FONT), bold=bold, size=size,
                color=color, underline=underline)
    cell.value = _mixed_text(value, base) if is_thai and not font else value
    cell.font = base
    cell.alignment = Alignment(horizontal=h, vertical=v, wrap_text=wrap, indent=indent)
    if fill:
        cell.fill = fill
    if fmt:
        cell.number_format = fmt


def _cells(ws: Worksheet, rng: str) -> tuple[tuple[Any, ...], ...]:
    # ws["A1:A1"] คืน tuple ซ้อน tuple เสมอ ส่วนช่องเดียวแบบ "A1" คืน cell ตัวเดียว จึงรวมให้เป็นรูปแบบเดียว
    block = ws[rng]
    return block if isinstance(block, tuple) else ((block,),)


def _grid(ws: Worksheet, rng: str, border: Border = BORDER) -> None:
    """ใส่เส้นขอบให้ทุกเซลล์ในช่วง (รวมเซลล์ที่ถูก merge) ไม่งั้นเส้นขอบแหว่ง"""
    for row in _cells(ws, rng):
        for cell in row:
            cell.border = border


def _outline(ws: Worksheet, rng: str, side: Side = THIN, keep_inner: bool = False) -> None:
    """ใส่เส้นขอบเฉพาะกรอบนอกของช่วง ถ้า keep_inner=True จะคงเส้นภายในเดิมไว้"""
    rows = _cells(ws, rng)
    last_r, last_c = len(rows) - 1, len(rows[0]) - 1
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            old = cell.border if keep_inner else Border()
            cell.border = Border(left=side if c == 0 else old.left,
                                 right=side if c == last_c else old.right,
                                 top=side if r == 0 else old.top,
                                 bottom=side if r == last_r else old.bottom)


def _block(ws: Worksheet, rng: str, value: Any = "", *, grid: bool = True, **style: Any) -> None:
    """กล่องหนึ่งช่อง: merge (ถ้ามากกว่า 1 เซลล์) -> เขียนค่า/สไตล์ที่เซลล์แรก -> ใส่เส้นขอบทั้งช่วง"""
    first, _, last = rng.partition(":")
    if last and first != last:
        ws.merge_cells(rng)
    _put(ws, first, value, **style)
    if style.get("fill"):  # เติมสีทั้งช่วง เผื่อโปรแกรมอื่นแสดงเซลล์ที่ถูก merge แยกกัน
        for row in _cells(ws, rng):
            for cell in row:
                cell.fill = style["fill"]
    if grid:
        _grid(ws, rng if last else f"{first}:{first}")


def _height(ws: Worksheet, row: int, height: float) -> None:
    ws.row_dimensions[row].height = height


def _heading(ws: Worksheet, row: int, title: str, height: float) -> int:
    # หัวข้อส่วนต่างๆ (ตัวหนา ตัวอักษรเขียว ไม่มีเส้นขอบ) เยื้องเข้ามาเล็กน้อยตามฟอร์ม
    _block(ws, f"B{row}:N{row}", title, grid=False, bold=True, size=11, color=GREEN, v="bottom", indent=1)
    _height(ws, row, height)
    return row + 1


def _warranty_line(item: dict) -> str:
    # ย่อข้อความประกัน เช่น "Warranty 3Y Premier..." -> "ประกัน 3 ปี" ถ้าไม่พบระยะเวลาให้ใช้ข้อความเดิม
    text = _text(item.get("warranty")).strip()
    m = re.search(r"(\d+)\s*(y(?:ears?|rs?)?\b|ปี|m(?:onths?)?\b|เดือน)", text, flags=re.I)
    if not m:
        return text
    unit = "ปี" if m.group(2)[0] in "yYป" else "เดือน"
    return f"ประกัน {m.group(1)} {unit}"


def _discount_ratio(item: dict) -> float:
    # แปลงส่วนลดเป็นสัดส่วนสำหรับช่อง Discount%: "5%" -> 0.05 และจำนวนเงินจะคำนวณจาก จำนวน x ราคา ไม่มีส่วนลด = 0
    text = _text(item.get("discount")).strip()
    value = _to_float(text.rstrip("%"))
    if not value:
        return 0
    qty, price, amount = (_to_float(item.get(key)) for key in ("unit", "price", "amount"))
    gross = qty * price if qty and price else None
    is_baht = gross and amount is not None and abs(gross - amount - value) < 0.01
    if is_baht and not text.endswith("%"):
        return value / gross
    return value / 100


def _today_text() -> str:
    # วันที่ทำการแปลงไฟล์ เช่น 02-Nov-26
    return datetime.now(THAI_TZ).strftime("%d-%b-%y")


def _supplier_name(doc: dict) -> str:
    # ใช้ชื่อที่อ่านได้จาก PDF ก่อน ถ้าไม่มีให้เทียบจากโดเมนอีเมลผู้ขาย
    supplier = _text(doc.get("supplier")).strip()
    if supplier:
        return supplier
    domain = _text(doc.get("sale_email")).rpartition("@")[2].strip().lower()
    return SUPPLIER_BY_DOMAIN.get(domain, "")


# ---------- รูปภาพ ----------
def _place_image(ws: Worksheet, image: XlImage, col: str, row: int, dx: float, dy: float,
                 width: float, height: float) -> None:
    """วางรูปโดยระบุระยะจากมุมเซลล์ (pt) เพื่อให้ตรงตำแหน่งในฟอร์มต้นแบบ"""
    emu = 12700  # 1 pt = 12700 EMU
    marker = AnchorMarker(col=column_index_from_string(col) - 1, colOff=round(dx * emu),
                          row=row - 1, rowOff=round(dy * emu))
    image.anchor = OneCellAnchor(_from=marker, ext=XDRPositiveSize2D(round(width * emu), round(height * emu)))
    ws.add_image(image)


def _make_logo() -> io.BytesIO:
    """วาดโลโก้ Swagelok Thailand ด้วย Pillow (ไม่พึ่งไฟล์ภายนอก จึงมีโลโก้ทุกไฟล์)"""
    from PIL import Image, ImageDraw, ImageFont

    scale = 3  # วาดขยายแล้วย่อ เพื่อให้ขอบเรียบ
    w, h = LOGO_SIZE[0] * scale, LOGO_SIZE[1] * scale
    img = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(img)

    def load(names: tuple[str, ...], size: int) -> Any:
        for name in names:
            try:
                return ImageFont.truetype(name, size * scale)
            except OSError:
                continue
        return ImageFont.load_default()

    brand = "#0A8FC7"
    # คลื่นด้านบนคำว่า Swagelok
    wave = [(x, int(h * 0.20 + math.sin(x / (w / 9.0)) * h * 0.07)) for x in range(int(w * 0.12), int(w * 0.88))]
    draw.line(wave, fill=brand, width=3 * scale)
    word_font = load(("ariali.ttf", "Arial Italic.ttf", "DejaVuSans-Oblique.ttf"), 20)
    sub_font = load(("tahomabd.ttf", "Tahoma Bold.ttf", "DejaVuSans-Bold.ttf"), 9)
    draw.text((w / 2, h * 0.50), "Swagelok", font=word_font, fill=brand, anchor="mm")
    draw.text((w / 2, h * 0.82), LOGO_TEXT, font=sub_font, fill=brand, anchor="mm")

    img = img.resize(LOGO_SIZE, Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf


def _load_logo() -> XlImage:
    """ใช้โลโก้จริงจาก assets/logo.png ก่อน ถ้าไม่มีไฟล์/เปิดไม่ได้ ให้ใช้ภาพที่วาดด้วย Pillow แทน"""
    from PIL import Image

    try:
        with Image.open(LOGO_FILE) as src:
            ratio = min(LOGO_SIZE[0] / src.width, LOGO_SIZE[1] / src.height)  # คงสัดส่วนเดิม
            size = (round(src.width * ratio), round(src.height * ratio))
            logo = src.convert("RGBA").resize(size, Image.LANCZOS)
    except Exception:
        logo = Image.open(_make_logo()).convert("RGBA")

    # วางโลโก้กลางผืนโปร่งใสขนาดเท่ากล่อง เมื่อรูปยืดตามกล่อง โลโก้จึงอยู่กึ่งกลางเสมอ
    canvas = Image.new("RGBA", LOGO_BOX_SIZE, (255, 255, 255, 0))
    canvas.paste(logo, ((LOGO_BOX_SIZE[0] - logo.width) // 2, (LOGO_BOX_SIZE[1] - logo.height) // 2))
    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    buf.seek(0)
    return XlImage(buf)


def _add_logo(ws: Worksheet) -> None:
    # โลโก้ต้องมีเสมอ: ถ้าใส่รูปไม่สำเร็จ ให้ใส่ข้อความ Swagelok Thailand แทน
    first, top, last, bottom = LOGO_BOX
    try:
        image = _load_logo()
        # ความกว้างคอลัมน์จริงเปลี่ยนตาม DPI จึงยึดรูปกับมุมกล่อง แทนการกำหนดระยะตายตัว
        image.anchor = TwoCellAnchor(editAs="twoCell",
                                     _from=AnchorMarker(col=column_index_from_string(first) - 1, row=top - 1),
                                     to=AnchorMarker(col=column_index_from_string(last), row=bottom))
        ws.add_image(image)
    except Exception:
        _put(ws, f"{first}{top}", LOGO_TEXT, bold=True, size=12, color=BLUE, h="center", wrap=True)


def _add_signature(ws: Worksheet, spec: tuple, row: int) -> None:
    # ไม่มีไฟล์ลายเซ็น/เปิดไม่ได้ ให้เว้นช่องว่างไว้ ไฟล์ยังสร้างได้ตามปกติ
    name, col, dx, dy, width, height = spec
    try:
        _place_image(ws, XlImage(str(ASSETS / name)), col, row, dx, dy, width, height)
    except Exception:
        pass


# ---------- แต่ละส่วนของเอกสาร ----------
def _write_header(ws: Worksheet, data: dict) -> int:
    # --- 1. Header: กล่องบน (ชื่อบริษัท+ที่อยู่ | โลโก้) / กล่องล่าง (ชื่อฟอร์ม | PR Run No., Date) ---
    doc = data.get("doc_info") or {}
    _height(ws, 1, 8)
    _block(ws, "B2:K2", COMPANY_NAME, grid=False, bold=True, size=18, color=BLUE, h="center",
           v="bottom", font=HEADER_FONT)
    _block(ws, "B3:K4", COMPANY_ADDRESS, grid=False, size=10, h="center", wrap=True, font=HEADER_FONT)
    _outline(ws, "B2:K4")
    _block(ws, "L2:N4", "", grid=False)
    _outline(ws, "L2:N4")
    _add_logo(ws)
    for r, height in ((2, 27), (3, 18), (4, 18), (5, 2)):
        _height(ws, r, height)

    _block(ws, "B6:K7", TITLE, grid=False, bold=True, size=18, color=BLUE, h="center")
    _outline(ws, "B6:K7")
    _block(ws, "L6:N6", "PR Run No.:", grid=False, bold=True)
    _block(ws, "L7:N7", f"PR Request Date: {_text(doc.get('issue_date'))}".rstrip(), grid=False, bold=True)
    _outline(ws, "L6:N7")
    _height(ws, 6, 14.5)
    _height(ws, 7, 14.5)
    return 8


def _write_requester(ws: Worksheet, row: int) -> int:
    # --- 2. Requester detail: ป้ายพื้นเหลือง + ค่า ซ้าย = ชื่อ/โทร/อีเมล ขวา = Fax / Reference ---
    row = _heading(ws, row, "รายละเอียดผู้ร้องขอ (Requester detail)", 18)
    labels = ("ชื่อผู้ร้องขอ (Name):", "โทรศัพท์ (Tel.):", "E-Mail:")
    values = (REQUESTER["name"], REQUESTER["tel"], REQUESTER["email"])
    for i, (label, value) in enumerate(zip(labels, values)):
        r = row + i
        _block(ws, f"B{r}:C{r}", label, bold=True, h="right", fill=YELLOW_FILL)
        is_email = label == "E-Mail:"
        _block(ws, f"D{r}:F{r}", value, h="center", bold=not is_email, size=11 if is_email else 10,
               color=BLUE if is_email else None, underline="single" if is_email else None)
        if is_email and value:
            ws[f"D{r}"].hyperlink = f"mailto:{value}"
        _height(ws, r, 14.7)

    _block(ws, f"G{row}:K{row}", "โทรสาร (Fax):", bold=True, h="right", fill=YELLOW_FILL)
    _block(ws, f"L{row}:N{row}", REQUESTER["fax"], h="center", color=BLUE)
    _block(ws, f"G{row + 1}:K{row + 2}", "Reference MJ Project\nNo. (if any):", bold=True, h="right",
           wrap=True, fill=YELLOW_FILL)
    _block(ws, f"L{row + 1}:N{row + 2}", "-", h="center", bold=True)
    return row + len(labels)


def _write_items(ws: Worksheet, items: list[dict], row: int) -> int:
    # --- 3. ตารางรายการสินค้า: แต่ละรายการมีแถวชื่อสินค้า + แถวประกัน (ถ้ามี) ---
    row = _heading(ws, row, "รายการที่ต้องการให้จัดซื้อดังต่อไปนี้ (The items to be purchased are as follows)", 19)
    head_top = row
    for first, last, title in TABLE_HEADERS:
        _block(ws, f"{first}{head_top}:{last}{head_top + 1}", title, bold=True, h="center", wrap=True,
               fill=YELLOW_FILL)
    _height(ws, head_top, 14.5)
    _height(ws, head_top + 1, 14.5)
    row = head_top + 2

    def table_row(r: int, no: Any = "", desc: str = "", qty: Any = "", price: Any = "",
                  discount: Any = "", total: Any = "") -> None:
        _block(ws, f"B{r}", no, bold=True, h="center")
        _block(ws, f"C{r}:F{r}", desc, wrap=True)
        _block(ws, f"G{r}:H{r}", qty, h="center")
        _block(ws, f"I{r}:L{r}", price, h="right", fmt=NUMBER_FORMAT)
        # ส่วนลดที่ไม่เป็นจำนวนเต็ม เช่น 2.5% ต้องแสดงทศนิยม ไม่ให้ปัดเป็น 3%
        is_whole = not isinstance(discount, float) or float(round(discount * 100, 6)).is_integer()
        _block(ws, f"M{r}", discount, h="right", fmt="0%" if is_whole else "0.00%")
        _block(ws, f"N{r}", total, h="right", fmt=NUMBER_FORMAT)
        lines = sum(max(1, math.ceil(len(part) / DESC_CHARS)) for part in desc.split("\n"))
        _height(ws, r, max(ITEM_ROW_HEIGHT, lines * LINE_HEIGHT + 4))

    used = 0
    for item in items:  # แถวขยับตามจำนวนรายการ (Dynamic)
        table_row(row, _text(item.get("item")), _text(item.get("description")), _num_or_text(item.get("unit")),
                  _num_or_text(item.get("price")), _discount_ratio(item), _num_or_text(item.get("amount")))
        row += 1
        used += 1
        warranty = _warranty_line(item)
        if warranty:
            table_row(row, desc=warranty)
            row += 1
            used += 1
    for _ in range(MIN_TABLE_ROWS - used):  # เติมแถวว่างให้ครบตามฟอร์ม
        table_row(row)
        row += 1
    return row


def _write_summary(ws: Worksheet, data: dict, row: int) -> int:
    # --- 4. Ship To (ซ้าย: หัวข้อ + เส้นเขียน 3 เส้น) และสรุปยอด (ขวา: ป้าย H:M, ค่า N) ---
    summary = data.get("summary") or {}
    _block(ws, f"B{row}:F{row}", "สถานที่ต้องการให้จัดส่ง (Ship To)", grid=False, bold=True, size=11, color=GREEN)
    for r in range(row + 1, row + 4):
        _grid(ws, f"B{r}:F{r}", LINE_ONLY)

    rate = _text((summary.get("vat") or {}).get("rate")) or "7"  # อัตราภาษีจากเอกสาร (ค่าเริ่มต้น 7%)
    lines = (
        ("ราคารวม (Total)\nบาท (Baht)", "total"),
        (f"ภาษีมูลค่าเพิ่ม {rate}% (VAT {rate}%)\nบาท (Baht)", "vat"),
        ("ราคารวมหลังภาษีมูลค่าเพิ่ม (Grand Total)\nบาท (Baht)", "grand_total"),
    )
    for i, (label, key) in enumerate(lines):
        r = row + i
        is_grand = key == "grand_total"
        value = (summary.get(key) or {}).get("value")
        _block(ws, f"H{r}:M{r}", label, grid=False, size=9, h="right", wrap=True)
        _block(ws, f"N{r}", _num_or_text(value) if value is not None else "", bold=is_grand, size=11,
               h="right", fmt=NUMBER_FORMAT)
        _height(ws, r, 24.5)
    _height(ws, row + 3, 23)
    return row + 4


def _write_suggest_source(ws: Worksheet, data: dict, row: int) -> int:
    # --- 5. บริษัทที่แนะนำให้ติดต่อ: ข้อมูลผู้ขายจากใบเสนอราคา ---
    doc = data.get("doc_info") or {}
    row = _heading(ws, row, "บริษัทที่แนะนำให้ติดต่อ (Suggest source)", 20)
    email = _text(doc.get("sale_email"))
    rows = (
        ("บริษัท (Company):", _supplier_name(doc), "E-Mail:", email),
        ("ชื่อผู้ติดต่อ (Name):", _text(doc.get("sale")), "โทรสาร (Fax):", _text(doc.get("sale_fax"))),
        ("โทรศัพท์ (Tel.):", _text(doc.get("sale_tel")), "Quotation Ref.:", _text(doc.get("qt_no"))),
    )
    for i, (l_label, l_value, r_label, r_value) in enumerate(rows):
        r = row + i
        is_email = r_label == "E-Mail:"
        _block(ws, f"B{r}:C{r}", l_label, bold=True, h="right", fill=YELLOW_FILL)
        _block(ws, f"D{r}:G{r}", l_value)
        _block(ws, f"H{r}:J{r}", r_label, bold=True, fill=YELLOW_FILL)
        _block(ws, f"K{r}:N{r}", r_value, size=11 if is_email else 10, color=BLUE if is_email else None,
               underline="single" if is_email else None)
        if is_email and r_value:
            ws[f"K{r}"].hyperlink = f"mailto:{r_value}"
        _height(ws, r, 14.7)
    row += len(rows)
    _height(ws, row, 5)  # ช่องว่างก่อนแถวเงื่อนไขชำระเงิน
    return row + 1


def _write_payment(ws: Worksheet, row: int) -> int:
    # --- 6. เงื่อนไขการชำระเงิน / วันที่ต้องการสินค้า (แถบพื้นเหลือง) ---
    _block(ws, f"B{row}:G{row}", PAYMENT_LINE, bold=True, size=9, fill=YELLOW_FILL)
    _block(ws, f"H{row}:N{row}", "วันที่ต้องการสินค้า (Needed Date): ____________________", bold=True, size=9,
           fill=YELLOW_FILL)
    _height(ws, row, 21)
    return row + 1


def _remark_row_heights(remark: str) -> tuple[float, float]:
    # หมายเหตุยาวกว่าช่องเดิม ให้เพิ่มความสูงแถวเท่าๆ กัน (openpyxl ไม่มี auto-fit)
    lines = sum(max(1, math.ceil(len(part) / REMARK_CHARS)) for part in remark.split("\n")) if remark else 0
    needed = lines * REMARK_LINE_HEIGHT + 4
    if needed <= sum(REMARK_ROW_HEIGHTS):
        return REMARK_ROW_HEIGHTS
    return needed / 2, needed / 2


def _write_attachment(ws: Worksheet, data: dict, row: int) -> int:
    # --- 7. เอกสารแนบ (ช่องติ๊ก 4 ช่อง) / หมายเหตุ (จากใบเสนอราคา ถ้าไม่มีเว้นว่าง) ---
    remark = _text(data.get("remark")).strip()
    _block(ws, f"B{row}:G{row}", "เอกสารแนบเพื่อประกอบการเสนอราคา (ถ้ามี) (Attachment)", grid=False, bold=True, indent=1)
    _block(ws, f"H{row}:N{row}", "หมายเหตุ (Remark)", grid=False, bold=True)
    choices = (("☐ Drawing (Hard Copy)", "☐ รูปภาพชิ้นงานตัวอย่าง"), ("☐ CAD File", "☐ อื่นๆ ______________________"))
    for i, (left, right) in enumerate(choices):
        r = row + 1 + i
        _block(ws, f"B{r}:C{r}", left, grid=False, size=8, indent=1)
        _block(ws, f"D{r}:G{r}", right, grid=False, size=8, indent=5)
    _block(ws, f"H{row + 1}:N{row + 2}", remark, grid=False, size=8, wrap=True, v="top")
    _outline(ws, f"B{row}:G{row + 2}")
    _outline(ws, f"H{row}:N{row + 2}")
    first_height, second_height = _remark_row_heights(remark)
    for r, height in ((row, 16), (row + 1, first_height), (row + 2, second_height), (row + 3, 5)):
        _height(ws, r, height)
    return row + 4


def _write_signatures(ws: Worksheet, row: int) -> int:
    # --- 8. ลายเซ็น 3 กล่อง: หัวเหลือง -> ช่องเซ็น -> Position -> Date ---
    head, sign, position, date, pad = row, row + 2, row + 3, row + 4, row + 5
    for sig, (first, last, label_end, value_start) in zip(SIGNATURES, SIGNATURE_BOXES):
        _block(ws, f"{first}{head}:{last}{head + 1}", sig["title"], bold=True, h="center", wrap=True,
               fill=YELLOW_FILL)
        _grid(ws, f"{first}{sign}:{last}{sign}", DASH_ONLY)
        # กล่องที่ไม่มีข้อมูลผู้เซ็น (ผู้ตรวจสอบ/ผู้อนุมัติ) คงป้ายและเส้นไว้ แต่เว้นค่าว่างให้กรอกเอง
        signer = sig.get("position", "")
        for r, label, value in ((position, "Position:", signer), (date, "Date:", _today_text() if signer else "")):
            if first != label_end:
                ws.merge_cells(f"{first}{r}:{label_end}{r}")
            _put(ws, f"{first}{r}", label, bold=True, h="right")
            _block(ws, f"{value_start}{r}:{last}{r}", value, grid=False, h="center")
            _grid(ws, f"{value_start}{r}:{last}{r}", DASH_ONLY)
        _outline(ws, f"{first}{sign}:{last}{pad}", keep_inner=True)
        if sig.get("image"):
            _add_signature(ws, sig["image"], sign)
    for r, height in ((head, 15), (head + 1, 15), (sign, 26), (position, 18), (date, 18), (pad, 6)):
        _height(ws, r, height)
    return pad + 1


def _outer_frame(ws: Worksheet, row: int) -> int:
    # --- 9. กรอบหนารอบทั้งหน้า และรหัสฟอร์มใต้กรอบ ---
    _height(ws, row, 5)
    _outline(ws, f"{FIRST_COL}1:{LAST_COL}{row}", THICK, keep_inner=True)
    code_row = row + 1
    _block(ws, f"J{code_row}:{LAST_COL}{code_row}", FORM_CODE, grid=False, size=9, h="right")
    return code_row


def _setup_page(ws: Worksheet, last_row: int, one_page: bool) -> None:
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.orientation = "portrait"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 1 if one_page else 0  # รายการเยอะให้ขึ้นหน้าใหม่ ไม่ย่อจนอ่านไม่ออก
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.page_margins.left = ws.page_margins.right = 0.15
    ws.page_margins.top = ws.page_margins.bottom = 0.15
    ws.page_margins.header = ws.page_margins.footer = 0
    ws.print_options.horizontalCentered = True
    ws.print_area = f"{FIRST_COL}1:{LAST_COL}{last_row}"
    ws.sheet_view.showGridLines = False


def generate_pr_excel(data_dict: dict) -> io.BytesIO:
    """สร้างไฟล์ .xlsx ฟอร์ม PR จากข้อมูลที่สกัดได้ แล้วคืนค่าเป็น BytesIO พร้อมให้ Streamlit ดาวน์โหลด"""
    try:
        wb = Workbook()
        ws = wb.active
        ws.title = "PR"
        for i in range(len(COLUMN_EDGES) - 1):
            ws.column_dimensions[get_column_letter(i + 1)].width = _column_width(COLUMN_EDGES[i + 1] - COLUMN_EDGES[i])

        data = data_dict or {}
        row = _write_header(ws, data)  # เรียงจากบนลงล่างตามฟอร์มต้นแบบ
        row = _write_requester(ws, row)
        items_top = row + 3
        row = _write_items(ws, data.get("items") or [], row)
        one_page = row - items_top <= MIN_TABLE_ROWS
        row = _write_summary(ws, data, row)
        row = _write_suggest_source(ws, data, row)
        row = _write_payment(ws, row)
        row = _write_attachment(ws, data, row)
        row = _write_signatures(ws, row)
        last_row = _outer_frame(ws, row)
        _setup_page(ws, last_row, one_page)

        buffer = io.BytesIO()
        wb.save(buffer)
        buffer.seek(0)  # เลื่อนกลับต้นไฟล์ เพื่อให้ st.download_button อ่านได้ทันที
        return buffer
    except Exception as exc:
        raise ValueError(f"สร้างไฟล์ Excel ไม่สำเร็จ: {exc}") from exc
