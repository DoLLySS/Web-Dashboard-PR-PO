"""หน้าตาและพฤติกรรมของ Sidebar (โลโก้ + ชื่อเว็บ + เมนูแบบจัดกลุ่ม + Custom CSS)

แยกออกมาจาก app.py เพื่อให้ app.py เป็น Router อย่างเดียว
อยากเปลี่ยนสี / ชื่อเว็บ / โลโก้ ให้แก้ที่ "ค่าคงที่" ด้านบนไฟล์นี้ ไม่ต้องแตะ CSS ด้านล่าง
"""

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

import streamlit as st

from config.styles import PALETTE, RADIUS_PX

# ---------------------------------------------------------------------------
# ค่าคงที่: ข้อความและโลโก้ (แก้ที่นี่)
# ---------------------------------------------------------------------------

# ชื่อเว็บและคำอธิบายเล็ก ๆ ใต้ชื่อ (ตามดีไซน์: "Website Name" / URL)
WEBSITE_NAME: str = "Website Name"
WEBSITE_SUBTITLE: str = "untitled.com/sis"

# ไฟล์โลโก้ ถ้ามีไฟล์นี้จะแสดงรูปจริง ถ้าไม่มีจะแสดงวงกลมเขียนว่า "LOGO" แทน
# (วางรูปโลโก้ขนาดสี่เหลี่ยมจัตุรัสที่ assets/logo.png)
LOGO_PATH: Path = Path(__file__).parent / "assets" / "logo.png"

# ---------------------------------------------------------------------------
# ค่าคงที่: ธีมสีของ Sidebar (แก้ที่นี่ รหัสสี HEX)
# ---------------------------------------------------------------------------

# สีมาจากธีมกลาง (styles.PALETTE) จึงเปลี่ยนธีมทั้งระบบได้ที่เดียว ถ้าอยากเปลี่ยนเฉพาะ Sidebar ให้ใส่รหัสสีตรงนี้
SIDEBAR_COLORS: dict[str, str] = {
    "sidebar-bg": PALETTE["surface"],  # พื้นหลัง Sidebar (ขาว)
    "group-bg": PALETTE["surface"],  # พื้นของแต่ละกลุ่มเมนู
    "group-border": PALETTE["border"],  # เส้นขอบบาง ๆ ของกลุ่มเมนู
    "text": PALETTE["text"],  # สีตัวอักษรเมนู
    "text-muted": PALETTE["text-muted"],  # สีตัวอักษรรอง (หัวกลุ่ม, คำอธิบายใต้ชื่อเว็บ)
    "hover-bg": PALETTE["bg"],  # สีพื้นเมื่อเอาเมาส์ชี้ที่เมนู
    "active-bg": PALETTE["primary-soft"],  # สีพื้นของเมนูที่เลือกอยู่ (ไฮไลท์ฟ้าอ่อน #DBEAFE)
    "active-text": PALETTE["primary"],  # สีตัวอักษร/ไอคอนของเมนูที่เลือกอยู่
    "active-bar": PALETTE["primary"],  # แถบสีด้านซ้ายของเมนูที่เลือกอยู่
}

# ความมนของมุม (px) ใช้ค่าเดียวกันทั้งระบบ (styles.RADIUS_PX = 8)
SIDEBAR_RADIUS_PX: int = RADIUS_PX  # มุมของ Sidebar ทั้งแผง
GROUP_RADIUS_PX: int = RADIUS_PX  # มุมของกลุ่มเมนู
BUTTON_RADIUS_PX: int = RADIUS_PX  # มุมของปุ่มเมนู

# ชื่อ key ใน st.session_state ที่เก็บ "หน้าปัจจุบัน"
SESSION_KEY_CURRENT_PAGE: str = "current_page"


# ---------------------------------------------------------------------------
# โครงสร้างข้อมูลของเมนู
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MenuItem:
    """เมนู 1 รายการใน Sidebar

    Attributes:
        label: ข้อความบนปุ่ม (ต้องไม่ซ้ำกันทุกเมนู ใช้เป็นรหัสหน้า)
        icon: ไอคอนของปุ่ม เป็น Material Icon รูปแบบ ":material/ชื่อไอคอน:"
              ดูชื่อไอคอนได้ที่ https://fonts.google.com/icons
        render: ฟังก์ชันวาดหน้านี้ รับ (start_date, end_date)
        subtitle: คำอธิบายสั้น ๆ ใต้ชื่อหน้า (แสดงในแถบหัวหน้าของ app.py)
    """

    label: str
    icon: str
    render: Callable[[date, date], None]
    subtitle: str = ""


# ---------------------------------------------------------------------------
# CSS (ใช้ตัวแปร var(--...) ที่สร้างจาก SIDEBAR_COLORS ด้านบน จึงไม่ต้องแก้สีใน CSS)
# ---------------------------------------------------------------------------

SIDEBAR_CSS_RULES: str = """
/* 1) Sidebar ทั้งแผง: พื้นขาว + ขอบมน + เงาบาง + เว้นระยะรอบนอกให้ดูเป็นการ์ดลอย (ไม่มีเส้นขอบทึบ) */
[data-testid="stSidebar"] {
    background: transparent;
    padding: 12px 0 12px 12px;
}
[data-testid="stSidebar"] > div:first-child,
[data-testid="stSidebarContent"] {
    background: var(--sidebar-bg);
    border-radius: SIDEBAR_RADIUS;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05), 0 1px 3px rgba(0, 0, 0, 0.05);  /* เงาบาง ๆ ให้ลอยขึ้น */
}

/* 2) ส่วนหัว (โลโก้ + ชื่อเว็บ) */
.sidebar-brand { display: flex; align-items: center; gap: 12px; padding: 4px 4px 14px 4px; }
.sidebar-logo {
    width: 48px; height: 48px; flex-shrink: 0;
    border-radius: 50%;
    border: 2px solid var(--text);
    display: flex; align-items: center; justify-content: center;
    font-size: 11px; font-weight: 700; color: var(--text); background: var(--group-bg);
}
.sidebar-title { font-size: 17px; font-weight: 700; color: var(--text); line-height: 1.2; }
.sidebar-subtitle { font-size: 11px; color: var(--text-muted); margin-top: 2px; }

/* 3) การ์ดกลุ่มเมนู (st.expander): พื้นขาว ขอบมน เส้นขอบบาง */
[data-testid="stSidebar"] [data-testid="stExpander"] {
    background: var(--group-bg);
    border: 1px solid var(--group-border);
    border-radius: GROUP_RADIUS;
    margin-bottom: 10px;
}
/* หัวกลุ่ม (DASHBOARD / ORGANIZATION): ตัวเล็ก สีจาง ตัวพิมพ์ใหญ่ */
[data-testid="stSidebar"] [data-testid="stExpander"] summary p {
    font-size: 11px; font-weight: 700; letter-spacing: 0.08em; color: var(--text-muted);
}

/* 4) ปุ่มเมนูทุกปุ่ม: โปร่งใส จัดชิดซ้าย ไม่มีขอบ
      ใช้ class st-key-menu_button_* (Streamlit สร้างจาก key ของปุ่ม) เพื่อให้กระทบเฉพาะปุ่มเมนู
      ไม่กระทบปุ่มอื่นใน Sidebar เช่นปุ่มพับ Sidebar */
[class*="st-key-menu_button_"] button {
    justify-content: flex-start;
    background: transparent;
    border: none;
    border-radius: BUTTON_RADIUS;
    color: var(--text);
    box-shadow: none;
    padding: 6px 10px;
}
/* ข้อความ+ไอคอนอยู่ใน div ชั้นใน ต้องสั่งชิดซ้ายที่ชั้นนี้ด้วย ไม่งั้นจะอยู่กลางปุ่ม */
[class*="st-key-menu_button_"] button > div,
[class*="st-key-menu_button_"] button > div > span {
    justify-content: flex-start !important;
    width: 100%;
    text-align: left !important;
}
[class*="st-key-menu_button_"] button:hover {
    background: var(--hover-bg);
}

/* 5) ปุ่มเมนูที่ "เลือกอยู่" (type="primary"): ไฮไลท์พื้นสีฟ้า + แถบสีด้านซ้าย + ตัวหนา */
[class*="st-key-menu_button_"] button[data-testid="stBaseButton-primary"] {
    background: var(--active-bg);
    color: var(--active-text);
    font-weight: 700;
    box-shadow: inset 4px 0 0 var(--active-bar);
}
[class*="st-key-menu_button_"] button[data-testid="stBaseButton-primary"]:hover {
    background: var(--active-bg);
}
"""


def build_sidebar_css() -> str:
    """ประกอบ CSS ของ Sidebar: แปลงสีใน SIDEBAR_COLORS เป็นตัวแปร CSS และแทนค่าความมนของมุม

    Returns:
        ข้อความ <style>...</style> พร้อมส่งให้ st.markdown(unsafe_allow_html=True)
    """
    # สร้างตัวแปร CSS เช่น --sidebar-bg: #f0f2f6;
    css_variables = "\n".join(f"--{name}: {value};" for name, value in SIDEBAR_COLORS.items())
    css_rules = (
        SIDEBAR_CSS_RULES.replace("SIDEBAR_RADIUS", f"{SIDEBAR_RADIUS_PX}px")
        .replace("GROUP_RADIUS", f"{GROUP_RADIUS_PX}px")
        .replace("BUTTON_RADIUS", f"{BUTTON_RADIUS_PX}px")
    )
    return f"<style>\n:root {{\n{css_variables}\n}}\n{css_rules}</style>"


# ---------------------------------------------------------------------------
# ฟังก์ชันวาด
# ---------------------------------------------------------------------------


def _select_page(page_label: str) -> None:
    """เก็บหน้าที่ผู้ใช้กดเลือกลง session_state (ใช้เป็น on_click ของปุ่ม)

    ใช้ callback แทนการเช็ค if st.button(...) เพราะ callback ทำงานก่อนวาดหน้าใหม่
    ปุ่มที่ไฮไลท์จึงเปลี่ยนทันที ไม่ช้าไป 1 จังหวะ

    Args:
        page_label: ชื่อเมนูที่ถูกกด
    """
    st.session_state[SESSION_KEY_CURRENT_PAGE] = page_label


def _render_brand_header() -> None:
    """วาดส่วนหัวของ Sidebar: โลโก้ + ชื่อเว็บ + คำอธิบายเล็ก ๆ"""
    if LOGO_PATH.exists():
        logo_columns = st.columns([1, 3], vertical_alignment="center")
        logo_columns[0].image(str(LOGO_PATH))
        logo_columns[1].markdown(
            f'<div class="sidebar-title">{WEBSITE_NAME}</div>'
            f'<div class="sidebar-subtitle">{WEBSITE_SUBTITLE}</div>',
            unsafe_allow_html=True,
        )
        return

    # ยังไม่มีไฟล์โลโก้: แสดงวงกลมเขียนว่า LOGO แทน (สไตล์อยู่ในข้อ 2 ของ CSS)
    st.markdown(
        '<div class="sidebar-brand">'
        '<div class="sidebar-logo">LOGO</div>'
        f'<div><div class="sidebar-title">{WEBSITE_NAME}</div>'
        f'<div class="sidebar-subtitle">{WEBSITE_SUBTITLE}</div></div>'
        "</div>",
        unsafe_allow_html=True,
    )


def render_sidebar(menu_groups: dict[str, list[MenuItem]]) -> MenuItem:
    """วาด Sidebar ทั้งแผง แล้วคืนเมนูที่ถูกเลือกอยู่ในขณะนี้

    Args:
        menu_groups: กลุ่มเมนู {ชื่อกลุ่ม: [MenuItem, ...]} เรียงตามลำดับที่จะแสดง
                     เมนูแรกของกลุ่มแรกเป็นหน้าเริ่มต้น

    Returns:
        MenuItem ที่เลือกอยู่ (app.py ใช้เรียก item.render(...))
    """
    all_menu_items = [item for items in menu_groups.values() for item in items]
    menu_items_by_label = {item.label: item for item in all_menu_items}

    # ถ้ายังไม่เคยเลือก หรือชื่อหน้าที่จำไว้ไม่มีแล้ว (เช่นเปลี่ยนชื่อเมนู) ให้กลับไปหน้าแรก
    if st.session_state.get(SESSION_KEY_CURRENT_PAGE) not in menu_items_by_label:
        st.session_state[SESSION_KEY_CURRENT_PAGE] = all_menu_items[0].label
    current_page_label: str = st.session_state[SESSION_KEY_CURRENT_PAGE]

    with st.sidebar:
        st.markdown(build_sidebar_css(), unsafe_allow_html=True)
        _render_brand_header()

        # วาดแต่ละกลุ่มเป็น Expander (กดยุบ/ขยายได้) เปิดไว้เป็นค่าเริ่มต้น
        for group_title, menu_items in menu_groups.items():
            with st.expander(group_title.upper(), expanded=True):
                for menu_item in menu_items:
                    is_current_page = menu_item.label == current_page_label
                    st.button(
                        menu_item.label,
                        icon=menu_item.icon,
                        # primary = ปุ่มที่เลือกอยู่ (CSS ข้อ 5 ไฮไลท์ให้) / secondary = ปุ่มปกติ
                        type="primary" if is_current_page else "secondary",
                        width="stretch",
                        key=f"menu_button_{menu_item.label}",
                        on_click=_select_page,
                        args=(menu_item.label,),
                    )

    return menu_items_by_label[current_page_label]
