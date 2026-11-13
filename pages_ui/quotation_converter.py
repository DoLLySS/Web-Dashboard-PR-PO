"""หน้า Quotation → Excel: แปลงใบเสนอราคา PDF เป็นฟอร์ม PR (.xlsx)

ประมวลผลในหน่วยความจำล้วน ไม่บันทึกไฟล์ และไม่ส่งไป SharePoint / Power Automate / Master-List
"""

from datetime import date
from pathlib import Path

import streamlit as st

from config.logging_setup import get_logger
from utils.quotation_converter import convert_pdf_to_excel
from utils.quotation_converter.wrapper import format_grand_total

logger = get_logger(__name__)

SIGNATURE_FILE: Path = Path(__file__).resolve().parent.parent / "utils" / "quotation_converter" / "assets" / "signature_requested.png"
XLSX_MIME: str = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def render(start_date: date, end_date: date) -> None:
    """วาดหน้าตัวแปลง (ไม่ใช้ Date Filter)"""
    st.info("ไฟล์ถูกประมวลผลในหน่วยความจำเท่านั้น ไม่บันทึกลงเครื่องเซิร์ฟเวอร์ และไม่ส่งไป SharePoint, Power Automate หรือ Master-List")
    if not SIGNATURE_FILE.exists():
        st.warning("ไม่พบไฟล์ลายเซ็น (utils/quotation_converter/assets/signature_requested.png) ช่องลายเซ็นใน Excel จะว่าง")

    uploaded = st.file_uploader("อัปโหลดใบเสนอราคา (PDF)", type=["pdf"], accept_multiple_files=False, key="qc_uploader")
    if uploaded is None:
        return

    try:
        result = convert_pdf_to_excel(uploaded.getvalue())
    except ValueError as exc:
        st.error(f"❌ แปลงไฟล์ไม่สำเร็จ: {exc}")
        return
    except Exception:
        logger.exception("แปลงใบเสนอราคาไม่สำเร็จ")
        st.error("❌ แปลงไฟล์ไม่สำเร็จ: เกิดข้อผิดพลาดที่ไม่คาดคิด")
        return

    doc_info = result.data.get("doc_info") or {}
    left, middle, right, last = st.columns(4)
    left.metric("เลขที่ใบเสนอราคา", str(doc_info.get("qt_no") or "-"))
    middle.metric("ผู้ขาย", str(doc_info.get("supplier") or "-"))
    right.metric("จำนวนรายการ", len(result.data.get("items") or []))
    last.metric("ยอดรวมสุทธิ", format_grand_total(result.data))

    st.download_button(
        "⬇️ ดาวน์โหลด Excel",
        data=result.excel_bytes,
        file_name=result.file_name,
        mime=XLSX_MIME,
        key="qc_download",
        type="primary",
    )
