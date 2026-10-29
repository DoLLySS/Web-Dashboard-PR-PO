"""ส่วนหน้าตาที่ใช้ร่วมกันหลายหน้า: ธีมการ์ด (CSS) และตารางสรุปจำนวนอุปกรณ์

วิธีใช้การ์ดในหน้าใดก็ได้:
    1) เรียก st.markdown(build_css(), unsafe_allow_html=True) หนึ่งครั้งต้นหน้า
    2) วาดการ์ดด้วย st.container(key="ชื่อ_card") -> ได้พื้นเทาอ่อนขอบมน
       วาดกล่องขาวด้านในด้วย st.container(key="ชื่อ_inner")
    ชื่อ key ต้องลงท้ายด้วย _card หรือ _inner CSS จึงจะจับได้
"""

import html
from datetime import date

import pandas as pd
import streamlit as st

from config.constants import EQUIPMENT_CATEGORIES
from config.styles import PALETTE, RADIUS_PX, SHADOW
from data.database import get_category_counts
from ui_grid import render_readonly_grid

# ---------------------------------------------------------------------------
# ค่าคงที่: ธีมสีและความมน (แก้ที่นี่)
# ---------------------------------------------------------------------------

# สีมาจากธีมกลาง (config.styles.PALETTE) เปลี่ยนธีมทั้งระบบได้ที่ config/styles.py
THEME_COLORS: dict[str, str] = {
    "card-bg": PALETTE["surface"],  # พื้นการ์ดด้านนอก (ขาว + เงาบาง)
    "inner-bg": PALETTE["bg"],  # พื้นกล่องด้านใน (Tertiary #F8FAFC)
    "field-bg": PALETTE["surface"],  # พื้นช่องกรอกข้อมูล
    "text": PALETTE["text"],  # สีตัวอักษรหลัก
    "text-muted": PALETTE["text-muted"],  # สีตัวอักษรรอง
    "accent": PALETTE["primary"],  # สีฟ้าของปุ่มหลัก
    "accent-hover": PALETTE["primary-hover"],  # สีฟ้าตอนเอาเมาส์ชี้
    "border": PALETTE["border"],  # สีเส้นขอบบาง
    "dashed-border": "#CBD5E1",  # สีเส้นประของกล่องลากไฟล์
}
CARD_RADIUS_PX: int = RADIUS_PX  # มุมของการ์ดด้านนอก
INNER_RADIUS_PX: int = RADIUS_PX  # มุมของกล่องด้านใน
BUTTON_RADIUS_PX: int = RADIUS_PX  # มุมของปุ่ม

# CSS กลางของการ์ด (ตัวแปรสีขึ้นต้นด้วย --ui- เพื่อไม่ชนกับตัวแปรของ Sidebar)
BASE_CSS_RULES: str = """
/* การ์ดด้านนอกทุกใบ: container ที่ key ลงท้ายด้วย _card */
[class*="st-key-"][class*="_card"] {
    background: var(--ui-card-bg);
    border-radius: CARD_RADIUS;
    padding: var(--app-card-padding);  /* ระยะห่างภายในการ์ด เปลี่ยนตามขนาดจอ (config/styles.py) */
    box-shadow: CARD_SHADOW;  /* เงาบาง ๆ ให้การ์ดลอยขึ้น */
}
/* กล่องขาวด้านใน: container ที่ key ลงท้ายด้วย _inner */
[class*="st-key-"][class*="_inner"] {
    background: var(--ui-inner-bg);
    border: 1px solid var(--ui-border);
    border-radius: INNER_RADIUS;
    padding: var(--app-inner-padding);
}
/* หัวข้อใหญ่ในการ์ด และป้ายหัวข้อแบบแคปซูล (เช่น "Price", "Vendor") */
.card-title {
    font-size: var(--app-card-title); font-weight: 800; color: var(--ui-text);
    text-align: center; line-height: 1.2; margin: 0 0 12px 0;
}
.card-pill {
    display: inline-block; background: var(--ui-inner-bg); color: var(--ui-text);
    border-radius: INNER_RADIUS; padding: 4px 16px; font-size: 15px; font-weight: 700;
}
.card-section-label { font-size: 13px; color: var(--ui-text-muted); margin: 8px 0 4px 2px; }
"""


def apply_radius(css_rules: str) -> str:
    """แทนคำว่า CARD_RADIUS / INNER_RADIUS / BUTTON_RADIUS ใน CSS ด้วยค่า px จริง

    Args:
        css_rules: ข้อความ CSS ที่ใช้คำสามคำข้างต้นเป็นตัวแทน

    Returns:
        ข้อความ CSS ที่แทนค่าแล้ว
    """
    return (
        css_rules.replace("CARD_RADIUS", f"{CARD_RADIUS_PX}px")
        .replace("INNER_RADIUS", f"{INNER_RADIUS_PX}px")
        .replace("BUTTON_RADIUS", f"{BUTTON_RADIUS_PX}px")
        .replace("CARD_SHADOW", SHADOW)
    )


def build_css(extra_rules: str = "") -> str:
    """ประกอบ CSS ของการ์ด: ตัวแปรสีจาก THEME_COLORS + กฎกลาง + กฎเฉพาะหน้า (ถ้ามี)

    Args:
        extra_rules: CSS เพิ่มเติมเฉพาะหน้า (ใช้ var(--ui-ชื่อสี) และ CARD_RADIUS ฯลฯ ได้)

    Returns:
        ข้อความ <style>...</style> พร้อมส่งให้ st.markdown(unsafe_allow_html=True)
    """
    css_variables = "\n".join(f"--ui-{name}: {value};" for name, value in THEME_COLORS.items())
    css_rules = apply_radius(BASE_CSS_RULES + extra_rules)
    return f"<style>\n:root {{\n{css_variables}\n}}\n{css_rules}</style>"


# ---------------------------------------------------------------------------
# ตารางสรุปจำนวนอุปกรณ์ (ใช้ทั้งหน้า Overview และ Dashboard)
# ---------------------------------------------------------------------------


def get_equipment_quantities(start_date: date, end_date: date) -> list[tuple[str, int]]:
    """นับจำนวนรายการแต่ละหมวดอุปกรณ์ในช่วงวันที่ (หมวดที่ไม่มีรายการได้ 0 เพื่อให้มีครบทุกแถวเสมอ)

    Args:
        start_date: วันที่เริ่มต้นจาก Date Filter
        end_date: วันที่สิ้นสุดจาก Date Filter

    Returns:
        รายการ (ชื่อหมวด, จำนวน) เรียงตาม EQUIPMENT_CATEGORIES
    """
    quantity_by_category = {
        row["category"]: row["quantity"] for row in get_category_counts(start_date.isoformat(), end_date.isoformat())
    }
    return [(name, int(quantity_by_category.get(name, 0))) for name in EQUIPMENT_CATEGORIES]


def build_equipment_cards_html(rows: list[tuple[str, int]]) -> str:
    """สร้าง HTML ตารางสรุปอุปกรณ์แบบ modern: ชื่อหมวด | แถบสัดส่วน | จำนวน + แถวรวม (สไตล์อยู่ใน CSS ของหน้า Overview)

    Args:
        rows: รายการ (ชื่อหมวด, จำนวน)

    Returns:
        สตริง HTML (ชื่อหมวดผ่าน html.escape แล้ว)
    """
    total = sum(quantity for _, quantity in rows)
    max_quantity = max((quantity for _, quantity in rows), default=0)
    parts: list[str] = [
        '<div class="eq-table">',
        '<div class="eq-head"><span>Equipment</span><span></span><span>Qty.</span></div>',
    ]
    for index, (name, quantity) in enumerate(rows):
        # ความยาวแถบเทียบกับหมวดที่มากที่สุด (ไม่มีข้อมูลเลย = 0% ไม่หารศูนย์)
        percent = round(quantity / max_quantity * 100) if max_quantity else 0
        parts.append(
            f'<div class="eq-row" style="--i:{index}">'
            f'<span class="eq-name"><i class="eq-dot eq-dot-{index % 4}"></i>{html.escape(name)}</span>'
            f'<span class="eq-bar"><b class="eq-fill eq-dot-{index % 4}" style="width:{percent}%"></b></span>'
            f'<span class="eq-qty">{quantity:,}</span></div>'
        )
    parts.append(
        f'<div class="eq-row eq-total" style="--i:{len(rows)}"><span class="eq-name">Total</span>'
        f'<span></span><span class="eq-qty">{total:,}</span></div></div>'
    )
    return "".join(parts)


def render_equipment_table(start_date: date, end_date: date, key_prefix: str = "overview") -> None:
    """แสดงตาราง Equipment / Qty. = จำนวนรายการในแต่ละหมวด (Hardware, Software, Network, Service)

    Args:
        start_date: วันที่เริ่มต้นจาก Date Filter
        end_date: วันที่สิ้นสุดจาก Date Filter
        key_prefix: คำนำหน้า key ของตาราง (ต้องต่างกันในแต่ละหน้า)
    """
    quantities = get_equipment_quantities(start_date, end_date)
    equipment_table = pd.DataFrame(
        {"Equipment": [name for name, _ in quantities], "Qty.": [quantity for _, quantity in quantities]}
    )
    # เรียกได้ทั้งหน้า Overview และ Dashboard จึงต้องแยก key ด้วย key_prefix
    render_readonly_grid(
        equipment_table,
        key=f"{key_prefix}_equipment",
        right_aligned_columns=("Qty.",),
    )
