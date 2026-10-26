"""ไฟล์หลักของระบบ IT PR/PO & Tax Invoice MasterList (ตัวควบคุม / Router)

หน้าที่ของไฟล์นี้มีแค่ 3 อย่าง: ตั้งค่าหน้าเว็บ, ฉีดธีม (config/styles.py), วาด Sidebar + แถบหัวหน้า (ชื่อหน้า + Date Filter), และเรียกหน้าที่ถูกเลือก
ห้ามใส่เนื้อหาของหน้าจอหรือ SQL ในไฟล์นี้ ให้ไปแก้ในโฟลเดอร์ pages_ui/ หรือ database.py

วิธีรัน: streamlit run app.py
"""

from datetime import date, timedelta

import streamlit as st

from data.database import init_db
from pages_ui import dashboard, overview
from sidebar_ui import MenuItem, render_sidebar
from config.logging_setup import get_logger
from config.styles import inject_global_styles

# ---------------------------------------------------------------------------
# ค่าคงที่
# ---------------------------------------------------------------------------

# เมนูใน Sidebar แบ่งตามกลุ่ม: {ชื่อกลุ่ม: [MenuItem(ชื่อเมนู, ไอคอน, ฟังก์ชัน render ของหน้า)]}
# จะเพิ่มหน้าใหม่ ให้สร้างไฟล์ใน pages_ui/ แล้วเพิ่ม MenuItem ที่นี่ (เมนูแรกสุดคือหน้าเริ่มต้น)
# ไอคอนใช้ Material Icons ดูชื่อได้ที่ https://fonts.google.com/icons
# หน้าตา/สี/โลโก้ของ Sidebar แก้ที่ sidebar_ui.py
MENU_GROUPS: dict[str, list[MenuItem]] = {
    "Dashboard": [
        MenuItem("Overview", ":material/description:", overview.render, "ภาพรวมรายการ PR/PO และใบกำกับภาษี"),  # ไอคอนรูปเอกสาร
        MenuItem("Dashboard", ":material/bar_chart:", dashboard.render, "สรุปยอดซื้อและแนวโน้ม"),  # ไอคอนรูปกราฟ
    ],
}

# ช่วงวันที่เริ่มต้นของ Date Filter (ย้อนหลังกี่วัน)
DEFAULT_RANGE_DAYS: int = 30


# ---------------------------------------------------------------------------
# ฟังก์ชัน
# ---------------------------------------------------------------------------


# บันทึกลง logs/app.log
logger = get_logger(__name__)


def render_date_filter() -> tuple[date, date]:
    """วาด Date Filter แบบ "Date  To  Date" และคืนช่วงวันที่ที่เลือก

    Returns:
        (วันที่เริ่ม, วันที่สิ้นสุด) ถ้าผู้ใช้เลือกวันเริ่มหลังวันสิ้นสุด จะแจ้งเตือนและสลับให้เอง
    """
    today = date.today()
    start_column, to_column, end_column = st.columns([5, 1, 5], vertical_alignment="center")

    start_date = start_column.date_input(
        "วันที่เริ่ม",
        value=today - timedelta(days=DEFAULT_RANGE_DAYS),
        format="DD/MM/YYYY",
        key="filter_start_date",
        label_visibility="collapsed",
    )
    to_column.markdown("<div style='text-align:center'>To</div>", unsafe_allow_html=True)
    end_date = end_column.date_input(
        "วันที่สิ้นสุด",
        value=today,
        format="DD/MM/YYYY",
        key="filter_end_date",
        label_visibility="collapsed",
    )

    # กันกรณีเลือกวันเริ่มหลังวันสิ้นสุด (จะไม่มีข้อมูลเลย) ให้สลับกันแทนการแสดงผลว่าง
    if start_date > end_date:
        st.warning("⚠️ วันที่เริ่มอยู่หลังวันที่สิ้นสุด ระบบสลับให้อัตโนมัติ")
        start_date, end_date = end_date, start_date
    return start_date, end_date


def render_page_header(menu_item: MenuItem) -> tuple[date, date]:
    """วาดแถบหัวหน้า: ชื่อหน้า + คำอธิบาย (ซ้าย) และ Date Filter (ขวา) แล้วคืนช่วงวันที่ที่เลือก

    Args:
        menu_item: เมนูที่เลือกอยู่ (ใช้ชื่อและคำอธิบายของหน้า)

    Returns:
        (วันที่เริ่ม, วันที่สิ้นสุด) จาก Date Filter
    """
    # key="page_header" ใช้ให้ CSS ใน config/styles.py จับแถบนี้ได้ (บนจอแคบ ตัวกรองวันที่จะตกลงมาอยู่บรรทัดล่าง)
    with st.container(key="page_header"):
        title_column, filter_column = st.columns([3, 2], vertical_alignment="center")
        with title_column:
            st.header(menu_item.label)
            if menu_item.subtitle:
                st.caption(menu_item.subtitle)
        with filter_column:
            return render_date_filter()


def main() -> None:
    """จุดเริ่มต้นของแอป: ตั้งค่าหน้า, เตรียม DB, แล้วส่งต่อให้หน้าที่ถูกเลือก"""
    st.set_page_config(page_title="IT PR/PO MasterList", page_icon="📋", layout="wide")

    # ฉีด CSS ธีมกลาง (ฟอนต์ สี ความมน เงา) ให้ทั้งระบบ ต้องทำก่อนวาดส่วนอื่น (โค้ดอยู่ใน config/styles.py)
    inject_global_styles()

    # ถ้าเตรียมฐานข้อมูลไม่สำเร็จ init_db จะแสดง error ให้แล้ว จึงหยุดการทำงานต่อ
    if not init_db():
        st.stop()

    # วาด Sidebar (โค้ดอยู่ใน sidebar_ui.py) แล้วรับเมนูที่ผู้ใช้เลือกอยู่กลับมา
    selected_menu_item = render_sidebar(MENU_GROUPS)
    start_date, end_date = render_page_header(selected_menu_item)

    try:
        selected_menu_item.render(start_date, end_date)
    except Exception as error:  # noqa: BLE001 - จุดดักสุดท้ายของทั้งแอป (ตั้งใจให้กว้าง) กันหน้าจอขาวทั้งหน้า
        # บันทึก traceback เต็มลง logs/app.log ให้ทีม IT ย้อนดูได้ (เดิมแสดงบนหน้าจออย่างเดียว)
        logger.exception("แสดงหน้า '%s' ไม่สำเร็จ", selected_menu_item.label)
        st.error(
            f"❌ แสดงหน้า '{selected_menu_item.label}' ไม่สำเร็จ: ลองรีเฟรชหน้าเว็บ "
            f"หากยังเกิดซ้ำให้แจ้งทีม IT พร้อมข้อความนี้\n\nรายละเอียด: {error}"
        )


main()
