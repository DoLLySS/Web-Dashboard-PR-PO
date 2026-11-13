import io
import re
from typing import Any, Optional

import pdfplumber

# ตัวอักษรที่กว้างน้อยกว่าค่านี้ถือว่าเป็นสระ/วรรณยุกต์ลอย (กว้าง 0)
ZERO_WIDTH = 0.05
# บรรทัดเดียวกันต้องมีค่า top ต่างกันไม่เกินค่านี้ (pt) บางไฟล์วางวรรณยุกต์และตัวเลขต่างระดับกันราว 2-4 pt
LINE_TOLERANCE = 4.0
# ช่องว่างระหว่างตัวอักษรที่มากกว่านี้ถือว่าเป็นการเว้นวรรค (pt)
WORD_GAP = 1.0
# ช่องว่างที่มากกว่านี้ถือว่าเป็นคนละช่องข้อความ (pt)
SEGMENT_GAP = 6.0
# ช่องว่างต้องอยู่ห่างจากตัวอักษรระดับเดียวกันไม่เกินค่านี้ ไม่เช่นนั้นถือเป็นช่องว่างลอย (pt)
STRAY_SPACE_TOLERANCE = 0.5
# ไฟล์ที่มีตัวอักษรน้อยกว่านี้ถือว่าเป็นภาพสแกน
MIN_TEXT_CHARS = 50
# ระยะห่างสูงสุดของบรรทัดรายละเอียดในรายการเดียวกัน (pt)
ITEM_LINE_GAP = 22.0
# ระยะห่างสูงสุดของบรรทัดหมายเหตุ และระยะเผื่อจากขอบขวาของข้อความหมายเหตุบรรทัดแรก (pt)
REMARK_LINE_GAP = 30.0
REMARK_COLUMN_MARGIN = 20.0
# ตัวเลขยอดรวมอยู่ต่างระดับกับป้ายได้ไม่เกินค่านี้ (pt)
SUMMARY_TOLERANCE = 5.0
# ระยะเผื่อจากขอบหัวคอลัมน์ เพราะตัวเลขในตารางอาจอยู่นอกแนวหัวคอลัมน์เล็กน้อย (pt)
COLUMN_MARGIN = 8.0
# ระยะเผื่อของช่อง No แคบกว่า เพราะคอลัมน์ถัดไปอยู่ชิดกันมาก (pt)
NO_COLUMN_MARGIN = 3.0

# ฟอนต์บางไฟล์แมปวรรณยุกต์เป็นรหัส cid
CID_FIXES: dict[str, str] = {"(cid:1144)": "้"}

THAI_RE = re.compile(r"[฀-๿]")
# ลำดับสำคัญ: "จำนวนเงิน" ต้องมาก่อน "จำนวน" และ "Unit Price" ต้องมาก่อน "Unit"
HEADER_COLUMNS: tuple[tuple[str, re.Pattern], ...] = (
    ("amount", re.compile(r"^(จำนวนเงิน|รวมเงิน|มูลค่า|amount|total)", re.I)),
    ("price", re.compile(r"^(ราคา|(unit)?price)", re.I)),
    ("discount", re.compile(r"^(ส่วนลด|discount)", re.I)),
    ("qty", re.compile(r"^(จำนวน|qty|quantity|unit$)", re.I)),
    ("part", re.compile(r"^(parts?|รหัส)", re.I)),
    ("description", re.compile(r"^(รายการ|รายละเอียด|description)", re.I)),
    ("no", re.compile(r"^(ลำดับ|#$|item$|no\.?$)", re.I)),
)
NUMERIC_COLUMNS = ("qty", "price", "discount", "amount")

# ลำดับสำคัญ: Grand Total ต้องมาก่อน Total
SUMMARY_LABELS: tuple[tuple[str, re.Pattern], ...] = (
    ("grand_total", re.compile(r"^(?:จำนวนเงินรวมทั้งสิ้น|รวมจำนวนเงิน|ราคารวมสุทธิ|Grand\s*Total)", re.I)),
    ("vat", re.compile(r"^(?:ภาษีมูลค่าเพิ่ม|VAT)\s*(\d*(?:\.\d+)?)\s*%?", re.I)),
    ("total", re.compile(r"^(?:รวมมูลค่าสินค้า|รวมเป็นเงิน|Total\b)", re.I)),
)

# ข้อมูลของบริษัทเราเอง (ผู้ซื้อ) ซึ่งปรากฏในใบเสนอราคาเช่นกัน จึงต้องตัดออกก่อนหาข้อมูลผู้ขาย
MJ_NAME_RE = re.compile(r"เอ็ม\.?\s*เจ|บางกอกวาล์ว|m\.?\s*j\.?\s*bangkok|mjbangkok", re.I)
MJ_EMAIL_DOMAIN = "mjbangkok.com"
MJ_PHONES = ("0863449396", "0863481488", "020621590", "020621599")

COMPANY_RE = re.compile(r"^(?:บริษัท|บจก|หจก|ห้างหุ้นส่วน|ร้าน)|co\.?\s*,?\s*ltd|limited|จำกัด", re.I)
COMPANY_TAIL_RE = re.compile(r"\s*\(?(?:สำนักงานใหญ่|Head\s*Office|เลขที่ผู้เสียภาษี|เลขประจำตัว|Tax\s*ID).*$", re.I)
# ป้ายภาษาอังกฤษต้องมี : ต่อท้าย เพื่อไม่ให้จับตำแหน่งงานอย่าง "Sale Executive"
CONTACT_RE = re.compile(r"(?:ผู้ขาย|ผู้เสนอราคา|\bSales?(?:person)?\s*:)\s*:?\s*(.*)$", re.I)
CONTACT_TAIL_RE = re.compile(r"\s*(?:โทร|Tel\b|E-?mail).*$", re.I)
SIGNER_TAIL_RE = re.compile(r"\s*(?:ผู้จัดการ|Manager).*$", re.I)
PHONE_NUMBER = r"(\d[\d\-]*(?:\s*(?:,|/|ต่อ|ext\.?)\s*\d[\d\-]*)*)"
PHONE_RE = re.compile(rf"(?:เบอร์มือถือ|เบอร์โทร|โทรศัพท์|โทร\.?|Telephone|Tel\.?|Mobile)\s*[.:]?\s*{PHONE_NUMBER}", re.I)
FAX_RE = re.compile(rf"(?:แฟกซ์|แฟ็กซ์|โทรสาร|Fax)\s*[.:]?\s*{PHONE_NUMBER}", re.I)
EMAIL_RE = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")
QUOTATION_RE = re.compile(
    r"(?:QT\s*No|Quote\s*No|Quotation\s*(?:No|Ref)|เลขที่ใบเสนอราคา|เลขที่)\.?\s*:?\s*([A-Za-z0-9][A-Za-z0-9/\-_.]*)",
    re.I,
)
DATE_RE = re.compile(r"(?:Date|วันที่)\s*:?\s*(.*)$", re.I)
OTHER_DATE_RE = re.compile(r"expire|delivery|valid|needed|due", re.I)

WARRANTY_RE = re.compile(r"warranty|ประกัน", re.I)
REMARK_RE = re.compile(r"^[*\s]*(?:หมายเหตุ|Remark)[*\s]*:?\s*(.*)$", re.I)
# บางฟอนต์แมป "า" เป็น "ำ" จึงรองรับทั้งสองแบบ
AMOUNT_IN_WORDS_RE = re.compile(r"บ[าำ]ทถ้วน")


# ---------------------------------------------------------------- ตัวช่วยระดับตัวอักษร
def _center(ch: dict) -> float:
    return (ch["x0"] + ch["x1"]) / 2


def _is_zero_width(ch: dict) -> bool:
    return (ch["x1"] - ch["x0"]) < ZERO_WIDTH


def _clean_chars(chars: list[dict]) -> list[dict]:
    """ซ่อมตัวอักษรที่ฟอนต์แมปผิด แล้วเติม _i = ลำดับใน content stream"""
    cleaned: list[dict] = []
    for ch in chars:
        text = ch["text"]
        if text in CID_FIXES:
            ch = dict(ch, text=CID_FIXES[text], x1=ch["x0"])
        elif text.startswith("(cid:"):
            continue
        elif not text:
            # บางไฟล์เก็บตัว "า" เป็นตัวอักษรว่างที่มีความกว้าง ส่วนตัวว่างหลัง "ำ" คือความกว้างของ "ำ" เอง
            if _is_zero_width(ch) or not (cleaned and THAI_RE.search(cleaned[-1]["text"])):
                continue
            if cleaned[-1]["text"] == "ำ":
                cleaned[-1]["x1"] = ch["x1"]
                continue
            ch = dict(ch, text="า")
        cleaned.append(dict(ch, _i=len(cleaned)))
    return cleaned


def _order_chars(chars: list[dict]) -> list[dict]:
    """
    เรียงตัวอักษรของบรรทัดเดียวกัน
    pdfplumber เรียงตาม x0 ทำให้สระ/วรรณยุกต์ (กว้าง 0) ไปอยู่ผิดที่ เช่น "บรษิ ทั"
    จึงยึดลำดับใน content stream: ตัวกว้าง 0 จะผูกติดกับตัวฐานตัวก่อนหน้า
    """
    stream = sorted(chars, key=lambda c: c["_i"])
    keyed: list[tuple[float, int, dict]] = []
    base_x: Optional[float] = None
    attached = 0
    for ch in stream:
        if _is_zero_width(ch) and base_x is not None:
            attached += 1
            keyed.append((base_x, attached, ch))
        else:
            base_x, attached = ch["x0"], 0
            keyed.append((base_x, 0, ch))
    keyed.sort(key=lambda k: (k[0], k[1]))
    return [k[2] for k in keyed]


def _chars_text(chars: list[dict]) -> str:
    """แปลงตัวอักษรเป็นข้อความ พร้อมซ่อมภาษาไทย (วรรณยุกต์/สระ/สระอำ)"""
    parts: list[str] = []
    prev_x1: Optional[float] = None
    for ch in _order_chars(chars):
        text, zero = ch["text"], _is_zero_width(ch)
        if text.isspace():
            # space กว้าง 0 คือนิคหิต (ํ) ที่ฟอนต์แมปเป็น space ไว้ (เช่น "จ ำ" ในไฟล์จริง)
            parts.append("ํ" if zero else " ")
            continue
        if not zero and prev_x1 is not None and ch["x0"] - prev_x1 > WORD_GAP \
                and not (parts and parts[-1] == " "):
            parts.append(" ")
        parts.append(text)
        if not zero:
            prev_x1 = ch["x1"]
    joined = "".join(parts)
    joined = joined.replace("ํา", "ำ").replace("ํ", "")  # ํ + า = ำ
    return re.sub(r"[ \t]+", " ", joined).strip()


def _segments(chars: list[dict]) -> list[dict[str, Any]]:
    """แบ่งตัวอักษรในบรรทัดเป็นช่องข้อความตามระยะห่าง ช่องที่มีแต่ช่องว่างจะถูกตัดทิ้ง"""
    groups: list[list[dict]] = []
    right: Optional[float] = None
    for ch in sorted(chars, key=lambda c: c["x0"]):
        if not groups or (right is not None and ch["x0"] - right > SEGMENT_GAP):
            groups.append([])
            right = None
        groups[-1].append(ch)
        right = max(right or ch["x1"], ch["x1"])

    segments: list[dict[str, Any]] = []
    for group in groups:
        ink = [c for c in group if not c["text"].isspace()]
        if ink:
            segments.append({"text": _chars_text(group), "top": min(c["top"] for c in ink),
                             "x0": min(c["x0"] for c in ink), "x1": max(c["x1"] for c in ink)})
    return segments


def _build_lines(chars: list[dict]) -> list[dict[str, Any]]:
    """จัดกลุ่มตัวอักษรเป็นบรรทัด (บนลงล่าง) ตามค่า top แล้วแบ่งเป็นช่องข้อความ"""
    groups: list[dict[str, Any]] = []
    for ch in sorted(chars, key=lambda c: (c["top"], c["x0"])):
        if groups and abs(ch["top"] - groups[-1]["top"]) <= LINE_TOLERANCE:
            groups[-1]["chars"].append(ch)
        else:
            groups.append({"top": ch["top"], "chars": [ch]})
    lines = []
    for group in groups:
        group["chars"] = _drop_stray_spaces(group["chars"])
        segments = _segments(group["chars"])
        if segments:
            lines.append({**group, "segments": segments, "text": " ".join(s["text"] for s in segments)})
    return lines


def _drop_stray_spaces(chars: list[dict]) -> list[dict]:
    # บางไฟล์มีช่องว่างลอยจากระดับอื่นมาซ้อนกลางคำ เช่น "s/ n" จึงเก็บเฉพาะช่องว่างที่ติดกับตัวอักษรระดับเดียวกัน
    ink = [c for c in chars if not c["text"].isspace()]

    def keep(ch: dict) -> bool:
        return not ch["text"].isspace() or any(
            abs(c["top"] - ch["top"]) <= STRAY_SPACE_TOLERANCE
            and (abs(c["x1"] - ch["x0"]) <= STRAY_SPACE_TOLERANCE or abs(c["x0"] - ch["x1"]) <= STRAY_SPACE_TOLERANCE)
            for c in ink)

    return [c for c in chars if keep(c)]


def _clean_number(text: str, *, allow_percent: bool = False) -> str:
    """"2 ,527.00" -> "2,527.00", "1,000-" -> "1,000" ถ้าไม่ใช่ตัวเลขคืนค่าว่าง"""
    compact = re.sub(r"\s+", "", text).rstrip("-")
    pattern = r"\d[\d,]*(?:\.\d+)?%?" if allow_percent else r"\d[\d,]*(?:\.\d+)?"
    return compact if re.fullmatch(pattern, compact) else ""


def _to_number(text: str) -> Optional[float]:
    """แปลงข้อความตัวเลขแบบมี comma เป็น float (แปลงไม่ได้คืน None)"""
    try:
        return float(text.replace(",", ""))
    except ValueError:
        return None


def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def _is_mj_phone(text: str) -> bool:
    digits = _digits(text)
    return any(phone in digits for phone in MJ_PHONES)


# ---------------------------------------------------------------- หัวตาราง
def _find_header(lines: list[dict[str, Any]]) -> Optional[tuple[int, dict[str, dict]]]:
    """หาบรรทัดหัวตารางจากชื่อคอลัมน์ คืน (ลำดับบรรทัด, {ชื่อคอลัมน์: ช่องข้อความ})"""
    for index, line in enumerate(lines):
        columns: dict[str, dict] = {}
        for segment in line["segments"]:
            compact = re.sub(r"\s+", "", segment["text"])
            for name, pattern in HEADER_COLUMNS:
                if pattern.match(compact):
                    columns.setdefault(name, segment)
                    break
        if "no" in columns and "description" in columns and len(columns) >= 3:
            return index, columns
    return None


def _column_bands(columns: dict[str, dict]) -> dict[str, Any]:
    """แปลงตำแหน่งหัวคอลัมน์เป็นช่วง x ของแต่ละช่อง"""
    numeric = sorted(((columns[n], n) for n in NUMERIC_COLUMNS if n in columns), key=lambda c: c[0]["x0"])
    text_end = numeric[0][0]["x0"] - COLUMN_MARGIN if numeric else float("inf")
    bands: list[tuple[str, float, float]] = []
    for i, (segment, name) in enumerate(numeric):
        lo = text_end if i == 0 else (numeric[i - 1][0]["x1"] + segment["x0"]) / 2
        hi = (segment["x1"] + numeric[i + 1][0]["x0"]) / 2 if i + 1 < len(numeric) else float("inf")
        bands.append((name, lo, hi))
    part = columns.get("part")
    return {"no_end": columns["no"]["x1"] + NO_COLUMN_MARGIN, "text_end": text_end,
            "numeric": bands, "part_end": part["x1"] if part else None}


# ---------------------------------------------------------------- ตารางสินค้า
def _is_summary_segment(segment: dict) -> bool:
    return any(pattern.match(segment["text"]) for _, pattern in SUMMARY_LABELS)


def _read_numbers(line: dict[str, Any], bands: dict[str, Any], item: dict[str, Any]) -> None:
    # ราคาอาจไม่อยู่บรรทัดแรกของรายการ จึงใช้ค่าแรกที่พบในแต่ละคอลัมน์
    keys = {"qty": "unit", "price": "price", "discount": "discount", "amount": "amount"}
    for name, lo, hi in bands["numeric"]:
        text = _chars_text([c for c in line["chars"] if lo <= _center(c) < hi])
        if name == "qty":  # "1 งาน", "1 Unit" -> ใช้เฉพาะตัวเลข
            match = re.match(r"\d[\d,]*(?:\.\d+)?", text)
            value = match.group(0) if match else ""
        else:
            value = _clean_number(text, allow_percent=name == "discount")
        if value and not item[keys[name]]:
            item[keys[name]] = value


def _extract_items(lines: list[dict[str, Any]], bands: dict[str, Any]) -> list[dict[str, Any]]:
    """
    สกัดสินค้าด้วยตำแหน่งตัวอักษร
    - บรรทัดที่ช่อง No เป็นตัวเลข = เริ่มสินค้าใหม่
    - บรรทัดแบบ "ชื่อ | ค่า" = ตารางสเปก ไม่นำเข้า Description ยกเว้นระยะประกัน
    - บรรทัดข้อความช่องเดียวที่อยู่ติดกัน = รายละเอียดของสินค้านั้น
    """
    items: list[dict[str, Any]] = []
    current: Optional[dict[str, Any]] = None
    in_specs = False
    last_top = 0.0
    for line in lines:
        if any(_is_summary_segment(s) for s in line["segments"]):
            break
        no = _chars_text([c for c in line["chars"] if _center(c) < bands["no_end"]])
        texts = _segments([c for c in line["chars"]
                           if bands["no_end"] <= _center(c) < bands["text_end"]])
        if re.fullmatch(r"\d+", no) and texts:
            # ช่องแรกที่อยู่ในแนวคอลัมน์ Part No. คือรหัสสินค้า ไม่ใช่ชื่อสินค้า
            if bands["part_end"] and len(texts) > 1 and (texts[0]["x0"] + texts[0]["x1"]) / 2 < bands["part_end"]:
                texts = texts[1:]
            current = {"item": no, "description": " ".join(s["text"] for s in texts), "unit": "",
                       "price": "", "discount": "", "amount": "", "warranty": ""}
            items.append(current)
            _read_numbers(line, bands, current)
            in_specs, last_top = False, line["top"]
            continue
        if current is None:
            continue
        if line["top"] - last_top > ITEM_LINE_GAP or REMARK_RE.match(line["segments"][0]["text"]):
            current = None  # ข้อความที่อยู่ห่างออกไป หรือหมายเหตุ ไม่ใช่รายละเอียดของสินค้า
            continue
        last_top = line["top"]
        text = " ".join(s["text"] for s in texts)
        if WARRANTY_RE.search(text):
            current["warranty"] = current["warranty"] or text
            continue
        if in_specs or len(texts) > 1:
            in_specs = True
            continue
        _read_numbers(line, bands, current)
        if text:
            current["description"] = f"{current['description']}\n{text}"
    return items


# ---------------------------------------------------------------- ยอดรวม
def _extract_summary(lines: list[dict[str, Any]]) -> dict[str, Any]:
    """หาป้ายยอดรวม แล้วจับตัวเลขที่อยู่ทางขวาในระดับใกล้กัน ป้ายที่ไม่มีตัวเลขจะไม่ถูกนับ"""
    summary: dict[str, Any] = {key: {"text": "", "value": None} for key, _ in SUMMARY_LABELS}
    segments = [s for line in lines for s in line["segments"]]
    for segment in segments:
        for key, pattern in SUMMARY_LABELS:
            match = pattern.match(segment["text"])
            if not match:
                continue
            nearby = [s["text"] for s in sorted(segments, key=lambda s: s["x0"])
                      if s["x0"] > segment["x0"] and abs(s["top"] - segment["top"]) <= SUMMARY_TOLERANCE]
            for text in (segment["text"][match.end():], *nearby):
                raw = _clean_number(re.sub(r"บาท|THB|Baht", "", text, flags=re.I))
                if raw and summary[key]["value"] is None:
                    summary[key] = {"text": raw, "value": _to_number(raw)}
                    if key == "vat":  # เก็บอัตราภาษี เช่น "7" เพื่อใช้เป็นป้ายในฟอร์ม
                        summary[key]["rate"] = match.group(1)
                    break
            break
    return summary


# ---------------------------------------------------------------- ข้อมูลผู้ขาย
def _next_value(segments: list[dict], index: int) -> str:
    # ค่าอาจอยู่คนละช่องกับป้าย และบางไฟล์แยก ":" เป็นอีกช่อง เช่น "วันที่ | : | 8 กันยายน 2569"
    return next((s["text"] for s in segments[index + 1:] if s["text"].strip(" :")), "")


def _extract_supplier_name(lines: list[dict[str, Any]]) -> str:
    # ชื่อบริษัทหรือร้านแรกที่ไม่ใช่บริษัทเรา (ถ้าโลโก้เป็นรูปจะได้ค่าว่าง)
    for line in lines:
        for segment in line["segments"]:
            text = segment["text"]
            if COMPANY_RE.search(text) and not MJ_NAME_RE.search(text):
                return COMPANY_TAIL_RE.sub("", text).strip()
    return ""


def _extract_contact(lines: list[dict[str, Any]]) -> str:
    for index, line in enumerate(lines):
        for i, segment in enumerate(line["segments"]):
            match = CONTACT_RE.search(segment["text"])
            if not match:
                continue
            value = match.group(1).strip()
            if value.startswith("ในนาม"):  # "ผู้เสนอราคาในนามร้าน..." ใช้ชื่อในบรรทัดลงนามถัดลงมา
                for below in lines[index + 1:]:
                    for other in below["segments"]:
                        if other["x0"] < segment["x1"] and other["x1"] > segment["x0"]:
                            return SIGNER_TAIL_RE.sub("", other["text"]).strip()
                return ""
            value = CONTACT_TAIL_RE.sub("", value or _next_value(line["segments"], i)).strip()
            if value:
                return value
    return ""


def _first_phone(lines: list[dict[str, Any]], pattern: re.Pattern) -> str:
    for line in lines:
        for match in pattern.finditer(line["text"]):
            if not _is_mj_phone(match.group(1)):
                return match.group(1).strip()
    return ""


def _extract_email(lines: list[dict[str, Any]]) -> str:
    for line in lines:
        for email in EMAIL_RE.findall(line["text"]):
            if not email.lower().endswith(MJ_EMAIL_DOMAIN):
                return email
    return ""


def _extract_quotation_no(lines: list[dict[str, Any]]) -> str:
    for line in lines:
        for match in QUOTATION_RE.finditer(line["text"]):
            value = match.group(1).rstrip(".")
            if re.search(r"\d", value):
                return value
    return ""


def _extract_date(lines: list[dict[str, Any]]) -> str:
    # วันที่ของเอกสารตามที่เขียนไว้ ไม่นับวันหมดอายุหรือวันส่งของ
    for line in lines:
        for i, segment in enumerate(line["segments"]):
            match = DATE_RE.search(segment["text"])
            if not match or OTHER_DATE_RE.search(segment["text"]):
                continue
            value = match.group(1).strip(" :") or _next_value(line["segments"], i)
            if re.search(r"\d", value):
                return value
    return ""


def _extract_doc_info(lines: list[dict[str, Any]], head_lines: list[dict[str, Any]]) -> dict[str, str]:
    return {
        "issue_date": _extract_date(head_lines),
        "qt_no": _extract_quotation_no(head_lines),
        "supplier": _extract_supplier_name(lines),
        "sale": _extract_contact(lines),
        "sale_tel": _first_phone(lines, PHONE_RE),
        "sale_email": _extract_email(lines),
        "sale_fax": _first_phone(lines, FAX_RE),
    }


# ---------------------------------------------------------------- หมายเหตุ
def _left_group(segments: list[dict], limit: float) -> str:
    # เก็บข้อความกลุ่มซ้ายของบรรทัด ตัดส่วนที่อยู่นอกแนวหมายเหตุ (ลายเซ็น) และยอดรวมทิ้ง
    texts: list[str] = []
    right: Optional[float] = None
    for segment in segments:
        outside = segment["x0"] >= limit and right is not None and segment["x0"] - right > REMARK_COLUMN_MARGIN
        if _is_summary_segment(segment) or outside:
            break
        texts.append(segment["text"])
        right = segment["x1"]
    return " ".join(texts)


def _extract_remark(lines: list[dict[str, Any]], rules: list[float]) -> str:
    """เก็บข้อความหลังคำว่าหมายเหตุ หยุดที่เส้นแนวนอน ช่องว่างใหญ่ รายการถัดไป หรือจำนวนเงินเป็นตัวอักษร"""
    for index, line in enumerate(lines):
        segments = line["segments"]
        match = REMARK_RE.match(segments[0]["text"])
        if not match:
            continue
        first = match.group(1).strip()
        if first:
            own = [{**segments[0], "text": first}, *segments[1:]]
        else:  # คำว่าหมายเหตุอยู่คนละช่องกับข้อความ
            own = segments[1:]
        limit = own[0]["x1"] + REMARK_COLUMN_MARGIN if own else float("inf")
        found = [_left_group(own, limit)]
        last_top = line["top"]
        for below in lines[index + 1:]:
            head = below["segments"][0]["text"]
            crossed = any(last_top < rule < below["top"] for rule in rules)
            if crossed or below["top"] - last_top > REMARK_LINE_GAP or re.fullmatch(r"\d+", head) \
                    or AMOUNT_IN_WORDS_RE.search(below["text"]):
                break
            text = _left_group(below["segments"], limit)
            if text:
                found.append(text)
            last_top = below["top"]
        return "\n".join(t for t in found if t)
    return ""


def _horizontal_rules(page: pdfplumber.page.Page) -> list[float]:
    # เส้นแนวนอนยาว เก็บได้ทั้งแบบ rect และ line ขึ้นกับโปรแกรมที่สร้าง PDF
    return [shape["top"] for shape in (*page.rects, *page.lines)
            if shape["bottom"] - shape["top"] <= 2 and shape["x1"] - shape["x0"] >= 100]


# ---------------------------------------------------------------- ฟังก์ชันหลัก
def extract_pdf_data(pdf_file_bytes: bytes) -> dict[str, Any]:
    """
    สกัดข้อมูลใบเสนอราคาจากไฟล์ PDF (bytes)
    คืน {"doc_info", "items", "summary", "remark"}
    หากส่วนใดส่วนหนึ่งพัง จะไม่กระทบส่วนอื่น และใส่ข้อความ error ไว้ใน key "errors"
    """
    try:
        pdf = pdfplumber.open(io.BytesIO(pdf_file_bytes))
    except Exception as exc:
        raise ValueError(f"ไม่สามารถอ่านไฟล์ PDF ได้: {exc}") from exc

    data: dict[str, Any] = {"doc_info": {}, "items": [], "summary": {}, "remark": ""}
    errors: list[str] = []

    def run(name: str, func) -> None:
        # กันไม่ให้ส่วนใดส่วนหนึ่งพังแล้วลากส่วนอื่นพังตาม
        try:
            func()
        except Exception as exc:
            errors.append(f"สกัดส่วน {name} ไม่สำเร็จ: {exc}")

    with pdf:
        pages = [(page, _build_lines(_clean_chars(page.chars))) for page in pdf.pages]

    text_chars = sum(len(line["text"].replace(" ", "")) for _, lines in pages for line in lines)
    if text_chars < MIN_TEXT_CHARS:
        data["errors"] = ["ไฟล์นี้เป็นภาพสแกน ไม่มีตัวอักษรให้อ่าน กรุณาใช้ไฟล์ PDF ที่เลือกข้อความได้"]
        return data

    all_lines = [line for _, lines in pages for line in lines]
    found = next(((p, h) for p, (_, lines) in enumerate(pages) if (h := _find_header(lines))), None)
    if found is None:
        errors.append("ไม่พบหัวตารางรายการสินค้าในไฟล์ PDF นี้")
    else:
        first_page, (header_index, columns) = found
        bands = _column_bands(columns)
        head_lines = pages[first_page][1][:header_index]

        def read_items() -> None:
            # หน้าที่มีหัวตารางซ้ำให้เริ่มอ่านใต้หัวตาราง หน้าที่ไม่มีให้อ่านต่อด้วยคอลัมน์เดิม
            for _, lines in pages[first_page:]:
                header = _find_header(lines)
                data["items"].extend(_extract_items(lines[header[0] + 1:] if header else lines, bands))

        rules = [rule for page, _ in pages for rule in _horizontal_rules(page)]
        below_header = pages[first_page][1][header_index + 1:] + [
            line for _, lines in pages[first_page + 1:] for line in lines]
        run("doc_info", lambda: data.update(doc_info=_extract_doc_info(all_lines, head_lines)))
        run("items", read_items)
        run("summary", lambda: data.update(summary=_extract_summary(below_header)))
        run("remark", lambda: data.update(remark=_extract_remark(below_header, rules)))

    if errors:
        data["errors"] = errors
    return data
