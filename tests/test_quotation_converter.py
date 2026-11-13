"""ทดสอบตัวแปลงใบเสนอราคา PDF → Excel (utils/quotation_converter/wrapper.py และหน้า pages_ui/quotation_converter.py)

ข้อมูลทั้งหมดเป็นข้อมูลสมมติ PDF สร้างในหน่วยความจำ (make_pdf) ไม่มีไฟล์ .pdf/.xlsx ถูกเขียนลงดิสก์
ไม่แตะ .env ฐานข้อมูล หรือเครือข่าย
"""

import ast
import io
from pathlib import Path
from typing import Any

import openpyxl
import pytest

import utils.quotation_converter.excel_generator as excel_generator
import utils.quotation_converter.wrapper as wrapper
from utils.quotation_converter.extractor import extract_pdf_data

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
WRAPPER_SOURCE: Path = PROJECT_ROOT / "utils" / "quotation_converter" / "wrapper.py"
INIT_SOURCE: Path = PROJECT_ROOT / "utils" / "quotation_converter" / "__init__.py"
PAGE_SOURCE: Path = PROJECT_ROOT / "pages_ui" / "quotation_converter.py"

# ข้อมูลสมมติ
FAKE_SUPPLIER = "Example Supplier Co., Ltd."
FAKE_QT_NO = "QT-TEST/001"

# (x, y, ข้อความ) ตามตำแหน่งบนหน้า A4 (จุดเริ่มอยู่มุมล่างซ้าย)
FAKE_QUOTATION_ROWS: list[tuple[int, int, str]] = [
    (50, 800, FAKE_SUPPLIER),
    (400, 800, f"Quotation No: {FAKE_QT_NO}"),
    (400, 785, "Date: 01/01/2026"),
    (50, 700, "No"),
    (100, 700, "Description"),
    (300, 700, "Qty"),
    (380, 700, "Unit Price"),
    (500, 700, "Amount"),
    (50, 680, "1"),
    (100, 680, "Test valve"),
    (300, 680, "2"),
    (380, 680, "100.00"),
    (500, 680, "200.00"),
    (50, 660, "2"),
    (100, 660, "Test fitting"),
    (300, 660, "1"),
    (380, 660, "50.00"),
    (500, 660, "50.00"),
    (380, 600, "Total"),
    (500, 600, "250.00"),
    (380, 585, "VAT 7%"),
    (500, 585, "17.50"),
    (380, 570, "Grand Total"),
    (500, 570, "267.50"),
]


def make_pdf(rows: list[tuple[int, int, str]]) -> bytes:
    """สร้าง PDF 1 หน้าในหน่วยความจำ (ฟอนต์ Helvetica) จากรายการ (x, y, ข้อความ)

    Args:
        rows: ข้อความที่จะวางบนหน้า ถ้าว่างจะได้หน้าเปล่า (เหมือนไฟล์สแกนที่ไม่มีตัวอักษร)

    Returns:
        bytes ของไฟล์ PDF
    """
    stream = "BT /F1 10 Tf\n" + "".join(f"1 0 0 1 {x} {y} Tm ({text}) Tj\n" for x, y, text in rows) + "ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    output = b"%PDF-1.4\n"
    offsets: list[int] = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(output))
        output += f"{number} 0 obj\n{body}\nendobj\n".encode()
    xref_position = len(output)
    output += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        output += f"{offset:010d} 00000 n \n".encode()
    output += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_position}\n%%EOF".encode()
    return output


@pytest.fixture(autouse=True)
def clear_extraction_cache():
    """ล้างแคชผลอ่าน PDF ก่อนและหลังทุกเทสต์ เพื่อไม่ให้เทสต์กระทบกัน"""
    wrapper.load_pdf_data.clear()
    yield
    wrapper.load_pdf_data.clear()


def _imported_modules(source_path: Path) -> set[str]:
    """รวมชื่อโมดูลที่ไฟล์ซอร์สนี้ import (ชื่อเต็มแบบมีจุด)"""
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


# ---------------------------------------------------------------------------
# ตรวจไฟล์ก่อนอ่าน
# ---------------------------------------------------------------------------


def test_empty_file_is_rejected() -> None:
    with pytest.raises(ValueError, match="ไฟล์ว่างเปล่า"):
        wrapper.convert_pdf_to_excel(b"")


@pytest.mark.parametrize("content", [b"hello world", b"\x89PNG\r\n\x1a\n" + b"0" * 64, b"PK\x03\x04 fake xlsx"])
def test_non_pdf_file_is_rejected(content: bytes) -> None:
    with pytest.raises(ValueError, match="ไม่ใช่ PDF"):
        wrapper.convert_pdf_to_excel(content)


def test_file_over_limit_is_rejected_before_extraction(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[bytes] = []
    monkeypatch.setattr(wrapper, "load_pdf_data", lambda pdf_bytes: calls.append(pdf_bytes) or {})
    too_big = b"%PDF-" + b"0" * wrapper.MAX_PDF_BYTES  # ใหญ่กว่าเพดาน 5 bytes
    assert wrapper.MAX_PDF_BYTES == 10 * 1024 * 1024
    with pytest.raises(ValueError, match="10 MB"):
        wrapper.convert_pdf_to_excel(too_big)
    assert calls == []


def test_file_exactly_at_limit_passes_size_check() -> None:
    exactly_limit = b"%PDF-" + b"0" * (wrapper.MAX_PDF_BYTES - 5)
    assert len(exactly_limit) == wrapper.MAX_PDF_BYTES
    wrapper.validate_pdf_bytes(exactly_limit)  # ต้องไม่ raise


def test_pdf_without_text_is_reported_as_scanned_image() -> None:
    with pytest.raises(ValueError, match="ภาพสแกน"):
        wrapper.convert_pdf_to_excel(make_pdf([]))


def test_corrupt_pdf_is_reported_as_value_error() -> None:
    with pytest.raises(ValueError):
        wrapper.convert_pdf_to_excel(b"%PDF-1.4\nthis is not a real pdf body")


# ---------------------------------------------------------------------------
# แปลงสำเร็จ
# ---------------------------------------------------------------------------


def _workbook_texts(excel_bytes: bytes) -> tuple[openpyxl.Workbook, list[str]]:
    workbook = openpyxl.load_workbook(io.BytesIO(excel_bytes))
    sheet = workbook["PR"]
    texts = [str(cell.value) for row in sheet.iter_rows() for cell in row if cell.value is not None]
    return workbook, texts


def test_convert_valid_pdf_produces_pr_workbook() -> None:
    result = wrapper.convert_pdf_to_excel(make_pdf(FAKE_QUOTATION_ROWS))

    assert result.file_name == "ใบเสนอราคา_QT-TEST_001.xlsx"
    assert len(result.data["items"]) == 2
    workbook, texts = _workbook_texts(result.excel_bytes)
    assert "PR" in workbook.sheetnames
    joined = "\n".join(texts)
    assert FAKE_QT_NO in joined
    assert "Example Supplier" in joined
    assert "Test valve" in joined


def test_convert_works_without_signature_image(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    empty_assets = tmp_path / "empty_assets"
    empty_assets.mkdir()
    monkeypatch.setattr(excel_generator, "ASSETS", empty_assets)

    result = wrapper.convert_pdf_to_excel(make_pdf(FAKE_QUOTATION_ROWS))

    assert result.excel_bytes.startswith(b"PK")  # ไฟล์ .xlsx คือ zip


# ---------------------------------------------------------------------------
# ชื่อไฟล์และยอดรวม
# ---------------------------------------------------------------------------


def test_build_file_name_removes_forbidden_characters() -> None:
    name = wrapper.build_file_name({"doc_info": {"qt_no": 'a/b:c*d?e"f<g>h|i\\ j'}})
    assert name == "ใบเสนอราคา_a_b_c_d_e_f_g_h_i_j.xlsx"
    stem = name.removesuffix(".xlsx")
    assert not any(char in stem for char in '\\/:*?"<>| \t')


def test_build_file_name_trims_leading_and_trailing_separators() -> None:
    assert wrapper.build_file_name({"doc_info": {"qt_no": " /QT-1/ "}}) == "ใบเสนอราคา_QT-1.xlsx"


@pytest.mark.parametrize("data", [{}, {"doc_info": None}, {"doc_info": {}}, {"doc_info": {"qt_no": None}}, {"doc_info": {"qt_no": "  "}}, {"doc_info": {"qt_no": "///"}}])
def test_build_file_name_falls_back_when_no_quotation_number(data: dict[str, Any]) -> None:
    assert wrapper.build_file_name(data) == "ใบเสนอราคา.xlsx"


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"summary": None},
        {"summary": {}},
        {"summary": {"grand_total": None}},
        {"summary": {"grand_total": {}}},
        {"summary": {"grand_total": {"value": None}}},
        {"summary": {"grand_total": {"value": "abc"}}},
    ],
)
def test_format_grand_total_without_value_returns_dash(data: dict[str, Any]) -> None:
    assert wrapper.format_grand_total(data) == "-"


@pytest.mark.parametrize(("value", "expected"), [(1234.5, "1,234.50"), (0, "0.00"), (267.5, "267.50")])
def test_format_grand_total_formats_number(value: float, expected: str) -> None:
    assert wrapper.format_grand_total({"summary": {"grand_total": {"value": value}}}) == expected


# ---------------------------------------------------------------------------
# คีย์ชื่อผู้ขาย: หน้า UI ต้องอ่านคีย์ที่ extractor.py คืนมาจริง
# ---------------------------------------------------------------------------


def test_extractor_returns_supplier_key_not_supplier_name() -> None:
    doc_info = extract_pdf_data(make_pdf(FAKE_QUOTATION_ROWS))["doc_info"]

    assert doc_info["supplier"] == FAKE_SUPPLIER
    assert doc_info["qt_no"] == FAKE_QT_NO
    assert "supplier_name" not in doc_info


def test_page_reads_only_doc_info_keys_that_extractor_returns() -> None:
    real_keys = set(extract_pdf_data(make_pdf(FAKE_QUOTATION_ROWS))["doc_info"])
    tree = ast.parse(PAGE_SOURCE.read_text(encoding="utf-8"))
    used_keys = {
        node.args[0].value
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "get"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "doc_info"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    }

    assert "supplier" in used_keys  # หน้าต้องแสดงชื่อผู้ขาย
    assert used_keys <= real_keys, f"หน้าอ่านคีย์ที่ extractor ไม่คืน: {used_keys - real_keys}"


# ---------------------------------------------------------------------------
# แคช: ใช้ ttl + max_entries และอยู่ในหน่วยความจำ
# ---------------------------------------------------------------------------


def test_cache_limits_are_configured() -> None:
    assert wrapper.CACHE_TTL_SECONDS > 0
    assert isinstance(wrapper.CACHE_MAX_ENTRIES, int) and wrapper.CACHE_MAX_ENTRIES > 0
    source = WRAPPER_SOURCE.read_text(encoding="utf-8")
    assert "ttl=CACHE_TTL_SECONDS" in source and "max_entries=CACHE_MAX_ENTRIES" in source


def test_same_pdf_is_extracted_only_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []
    original = wrapper.extract_pdf_data

    def counting_extract(pdf_bytes: bytes) -> dict[str, Any]:
        calls.append(len(pdf_bytes))
        return original(pdf_bytes)

    monkeypatch.setattr(wrapper, "extract_pdf_data", counting_extract)
    pdf_bytes = make_pdf(FAKE_QUOTATION_ROWS)

    wrapper.convert_pdf_to_excel(pdf_bytes)
    wrapper.convert_pdf_to_excel(pdf_bytes)

    assert len(calls) == 1


# ---------------------------------------------------------------------------
# หน้านี้ต้องไม่ส่งข้อมูลออก และไม่เขียนไฟล์ลงดิสก์
# ---------------------------------------------------------------------------

FORBIDDEN_IMPORT_ROOTS: tuple[str, ...] = (
    "utils.masterlist_client",
    "utils.power_automate_api",
    "utils.storage_backend",
    "utils.local_storage",
    "utils.submit_pipeline",
    "utils.gdrive_api",
    "data.database",
    "requests",
    "urllib",
    "http",
    "smtplib",
    "socket",
)


@pytest.mark.parametrize("source", [WRAPPER_SOURCE, INIT_SOURCE, PAGE_SOURCE], ids=lambda path: path.name)
def test_modules_do_not_import_outbound_or_storage_modules(source: Path) -> None:
    imported = _imported_modules(source)
    violations = sorted(
        name for name in imported for root in FORBIDDEN_IMPORT_ROOTS if name == root or name.startswith(f"{root}.")
    )
    assert violations == []


@pytest.mark.parametrize("source", [WRAPPER_SOURCE, PAGE_SOURCE], ids=lambda path: path.name)
def test_modules_do_not_write_files(source: Path) -> None:
    tree = ast.parse(source.read_text(encoding="utf-8"))
    forbidden_attributes = {"write_bytes", "write_text", "save", "NamedTemporaryFile", "mkstemp", "TemporaryDirectory"}
    writes: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id in {"open", "NamedTemporaryFile"}:
            writes.append(node.func.id)
        elif isinstance(node.func, ast.Attribute) and node.func.attr in forbidden_attributes:
            writes.append(node.func.attr)
    assert writes == []
