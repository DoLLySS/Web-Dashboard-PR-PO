"""หน้า Dashboard: ตัวเลขสรุป (KPI), แนวโน้มยอดซื้อ, สัดส่วนอุปกรณ์ (Equipment) และผู้ขาย (Vendor)

โครงหน้า (การ์ดชั้นเดียว พื้นขาว):
    หัวหน้า (ชื่อหน้า + Date Filter) อยู่ใน app.py
    ภาพรวม  [ชิปวันที่]                                   [Export CSV]
    ┌──────────┬──────────┬──────────┬──────────┐
    │ ยอดรวม   │ ค่าใช้จ่าย │ จำนวนรายการ│ รอใบกำกับ │   <- KPI 4 ช่อง
    └──────────┴──────────┴──────────┴──────────┘
    ┌───────────────────────────┬───────────────┐
    │ แนวโน้มยอดซื้อ [7d▾][Detail]│ Equipment โดนัท │
    └───────────────────────────┴───────────────┘
    ┌───────────────────┬───────────────────────┐
    │ Top Vendors (กราฟ) │ Vendor (ตาราง)         │
    └───────────────────┴───────────────────────┘

ข้อมูลทั้งหมดดึงจาก database.py (ทุกส่วนอิง Date Filter ของ app.py)
"""

import html
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config.constants import EQUIPMENT_CATEGORIES
from data.database import STATUS_PENDING, get_category_counts, get_transactions
from config.styles import FONT_FAMILY, PALETTE
from ui_common import build_css
from config.logging_setup import get_logger
from ui_grid import render_readonly_grid

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# ค่าคงที่ (Configuration)
# ---------------------------------------------------------------------------

# สีของแต่ละหมวดหมู่ในกราฟ (แก้ Theme สีที่นี่ที่เดียว) ใช้รหัสสี HEX
# ชื่อหมวดต้องตรงกับ CATEGORY_OPTIONS ใน pages_ui/overview.py
CATEGORY_COLORS: dict[str, str] = {
    "Hardware": "#2E6FD8",  # น้ำเงิน
    "Software": "#E8832A",  # ส้ม
    "Service": "#2A9D8F",  # เขียวอมฟ้า
    "Network": "#8E5BD0",  # ม่วง
    "อื่น ๆ": "#7A8794",  # เทา
}

# สีของหมวดที่ไม่อยู่ใน CATEGORY_COLORS (เช่นหมวดใหม่ที่ยังไม่ได้กำหนดสี) และรายการที่ไม่ระบุหมวด
FALLBACK_CATEGORY_COLOR: str = "#B0B7C0"
UNSPECIFIED_CATEGORY_LABEL: str = "ไม่ระบุ"

# แสดง Top Vendors กี่อันดับ
TOP_VENDOR_LIMIT: int = 10

# ชื่อผู้ขายในกราฟ/ตารางของ Dashboard แสดงได้กี่ตัวอักษร (ยาวกว่านี้ตัดเป็น …) กันชื่อยาวดันตัวเลขออกนอกการ์ด
VENDOR_NAME_MAX_CHARS: int = 16

# กราฟ Top Vendors by Spend: สีแท่ง, ความสูงต่อแท่ง (px) และความสูงขั้นต่ำของกราฟ
VENDOR_BAR_COLOR: str = "#2E6FD8"
VENDOR_CHART_ROW_HEIGHT: int = 56
VENDOR_CHART_MIN_HEIGHT: int = 480

# ถ้าช่วงวันที่ที่เลือกยาวเกินกี่วัน กราฟแนวโน้มจะรวมเป็นรายเดือนแทนรายวัน
DAILY_CHART_MAX_DAYS: int = 62

# ตัวเลือกช่วงเวลาของการ์ด Price: {ข้อความบนปุ่ม: จำนวนวันย้อนหลังนับจากวันสิ้นสุดของ Date Filter}
# None = ใช้ช่วงวันที่ของ Date Filter ทั้งหมด (ช่วงที่เลือกจะไม่เกินขอบเขตของ Date Filter เสมอ)
# ตัวเลือกแรกคือค่าเริ่มต้น จะเพิ่ม/แก้ตัวเลือกให้แก้ที่นี่ เช่น "14d": 14
PRICE_PERIOD_OPTIONS: dict[str, Optional[int]] = {
    "7d": 7,
    "30d": 30,
    "90d": 90,
    "ตาม Date Filter": None,
}

# เส้นรวมทุกหมวด (ใช้ตอนปิด Detail Graph) ชื่อที่แสดงใน Legend/Tooltip และสีเส้น
TOTAL_LINE_LABEL: str = "รวมทุกหมวด"
TOTAL_LINE_COLOR: str = "#1F2937"

# สัดส่วนความกว้างของแต่ละแถว: [ซ้าย, ขวา]
TREND_ROW_RATIO: list[int] = [2, 1]  # แถวกลาง: แนวโน้มยอดซื้อ | Equipment
VENDOR_ROW_RATIO: list[int] = [2, 3]  # แถวล่าง: กราฟ Top Vendors | ตาราง Vendor

# ข้อความเมื่อไม่มีข้อมูลในการ์ด (แสดงในกล่องสวย ๆ แทน Error / กราฟที่พัง)
EMPTY_STATE_MESSAGE: str = "ยังไม่มีข้อมูล"

# ข้อความใน KPI เมื่อไม่มีข้อมูลราคา (ไม่แสดง 0.00 เพราะจะเข้าใจผิดว่าค่าใช้จ่ายเป็นศูนย์)
KPI_EMPTY_VALUE: str = "–"

# ไอคอนของ KPI แต่ละช่อง (key ของการ์ด -> อีโมจิ)
KPI_ICONS: dict[str, str] = {
    "kpi_total_card": "💰",
    "kpi_spend_card": "🧾",
    "kpi_count_card": "📦",
    "kpi_pending_card": "⏳",
}

# ความสูงกราฟ (px): แถวกลาง กราฟแนวโน้มกับโดนัท+รายการ Equipment ให้สูงใกล้กัน / แถวล่าง กราฟ Vendor กับตาราง
# ปรับเลขเหล่านี้ถ้าอยากให้การ์ดสองฝั่งสูงเท่ากันขึ้น/น้อยลง
TREND_CHART_HEIGHT_PX: int = 380
EQUIPMENT_DONUT_HEIGHT_PX: int = 270

# CSS เฉพาะหน้า Dashboard (กฎกลางของการ์ดอยู่ที่ ui_common.py)
PAGE_CSS_RULES: str = """
/* กล่อง "ยังไม่มีข้อมูล": พื้นอ่อน เส้นประ ข้อความกลางกล่อง */
.empty-state {
    display: flex; align-items: center; justify-content: center; min-height: 160px;
    background: var(--ui-inner-bg); border: 1px dashed var(--ui-dashed-border); border-radius: 8px;
    color: var(--ui-text-muted); font-size: 16px;
}
/* การ์ดชั้นเดียว: พื้นขาว + ขอบบาง (พื้นและเงามาจากกฎกลางใน ui_common.py) */
[class*="st-key-"][class*="_card"] { border: 1px solid var(--ui-border); }
/* ---- Animation: เลื่อนขึ้น + จางเข้า / จุดเตือนกะพริบเบา ๆ / ลูกศรเด้งลง ---- */
@keyframes dash-fade-up { from { opacity: 0; transform: translateY(14px); } to { opacity: 1; transform: translateY(0); } }
@keyframes dash-pulse { 0% { box-shadow: 0 0 0 0 rgba(232, 131, 42, 0.55); } 70% { box-shadow: 0 0 0 8px rgba(232, 131, 42, 0); } 100% { box-shadow: 0 0 0 0 rgba(232, 131, 42, 0); } }
@keyframes dash-bounce { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(3px); } }
/* หัวส่วนของหน้า: ชื่อไล่สี + แถบสีนำ + ชิปวันที่ */
.section-head { animation: dash-fade-up 0.5s ease-out both; }
.section-title {
    display: inline-block; font-size: clamp(26px, 1.6vw + 16px, 34px); font-weight: 800; line-height: 1.2; letter-spacing: -0.01em;
    background: linear-gradient(90deg, #1E293B 0%, #2563EB 60%, #8E5BD0 100%); -webkit-background-clip: text; background-clip: text;
    color: transparent; -webkit-text-fill-color: transparent;
}
.section-title::after {
    content: ""; display: block; width: 44px; height: 4px; margin-top: 6px; border-radius: 4px;
    background: linear-gradient(90deg, #2563EB, #8E5BD0); transition: width 0.3s ease;
}
.section-head:hover .section-title::after { width: 72px; }
.section-sub {
    display: inline-flex; align-items: center; gap: 6px; margin-top: 10px; padding: 4px 12px 4px 10px;
    font-size: 14px; font-weight: 600; color: var(--ui-text-muted); font-variant-numeric: tabular-nums;
    background: var(--ui-inner-bg); border: 1px solid var(--ui-border); border-radius: 999px;
}
.section-sub::before { content: "📅"; font-size: 13px; }
/* ชื่อการ์ด (เช่น แนวโน้มยอดซื้อ) และคำอธิบายใต้ชื่อ */
.card-heading { font-size: 18px; font-weight: 800; color: var(--ui-text); line-height: 1.3; }
.card-note { font-size: 14px; color: var(--ui-text-muted); margin-top: 2px; }
/* KPI: การ์ดมีสี accent ของตัวเอง (--kpi-accent) ไล่สีอ่อนมุมขวาบน แถบซ้าย ชิปไอคอน เข้าฉากทีละช่อง ยกขึ้นเมื่อชี้ */
.st-key-kpi_total_card { --kpi-accent: #2563EB; animation-delay: 0ms; }
.st-key-kpi_spend_card { --kpi-accent: #2A9D8F; animation-delay: 80ms; }
.st-key-kpi_count_card { --kpi-accent: #8E5BD0; animation-delay: 160ms; }
.st-key-kpi_pending_card { --kpi-accent: #E8832A; animation-delay: 240ms; }
[class*="st-key-kpi_"][class*="_card"] {
    position: relative; overflow: hidden; border-left: 4px solid var(--kpi-accent); border-radius: 14px;
    container-type: inline-size;
    background-image: linear-gradient(135deg, color-mix(in srgb, var(--kpi-accent) 9%, transparent) 0%, transparent 55%);
    animation: dash-fade-up 0.55s ease-out backwards;
    transition: transform 0.25s ease, box-shadow 0.25s ease, border-left-width 0.25s ease;
}
[class*="st-key-kpi_"][class*="_card"]:hover {
    transform: translateY(-4px); border-left-width: 7px;
    box-shadow: 0 14px 28px -10px color-mix(in srgb, var(--kpi-accent) 45%, transparent), 0 4px 10px rgba(15, 23, 42, 0.06);
}
.kpi-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.kpi-label { display: flex; align-items: center; gap: 8px; font-size: 15px; font-weight: 600; color: var(--ui-text-muted); }
.kpi-icon {
    flex: 0 0 auto; display: grid; place-items: center; width: 38px; height: 38px; border-radius: 12px; font-size: 19px;
    background: color-mix(in srgb, var(--kpi-accent) 14%, #ffffff); transition: transform 0.3s ease;
}
[class*="st-key-kpi_"][class*="_card"]:hover .kpi-icon { transform: rotate(-8deg) scale(1.12); }
.kpi-value {
    font-size: clamp(20px, 15cqi, 40px); font-weight: 800; color: var(--ui-text); line-height: 1.25; margin: 6px 0 4px;
    font-variant-numeric: tabular-nums; white-space: nowrap;
}
/* การ์ดแคบ (เช่น จอ 1100-1500px ที่เปิด sidebar): ซ่อนชิปไอคอนให้ป้ายอยู่บรรทัดเดียว การ์ดทุกช่องสูงเท่ากัน */
@container (max-width: 250px) {
    .kpi-icon { display: none; }
    .kpi-label { font-size: 14px; }
    .kpi-head { min-height: 44px; align-items: flex-start; }
}
.kpi-value.kpi-empty { color: var(--ui-text-muted); }
.kpi-sub { font-size: 14px; color: var(--ui-text-muted); }
.kpi-dot { flex: 0 0 auto; width: 9px; height: 9px; border-radius: 50%; background: #E8832A; animation: dash-pulse 1.8s infinite; }
/* ยอดรวมในช่วงเวลาที่เลือกของการ์ดแนวโน้ม */
.trend-total { font-size: var(--app-metric-value); font-weight: 800; color: var(--ui-text); line-height: 1.2; }
.trend-total small { font-size: 15px; font-weight: 600; color: var(--ui-text-muted); }
/* รายการหมวด Equipment ใต้โดนัท: จุดสี | ชื่อหมวด | จำนวน | ยอดรวม */
.equip-row { display: flex; align-items: center; gap: 10px; padding: 8px 2px; border-bottom: 1px solid var(--ui-border); font-size: 15px; }
.equip-row:last-child { border-bottom: none; }
.equip-dot { width: 10px; height: 10px; border-radius: 50%; flex: 0 0 auto; }
.equip-name { flex: 1 1 auto; font-weight: 600; color: var(--ui-text); }
.equip-qty { color: var(--ui-text-muted); }
.equip-amount { min-width: 96px; text-align: right; font-weight: 700; color: var(--ui-text); }
/* ปุ่ม Export: pill ไล่สีน้ำเงิน→ม่วง เงานุ่ม ชี้แล้วยกขึ้น/ไล่สีเลื่อน/ไอคอนเด้ง กดแล้วยุบ */
.st-key-dashboard_export { animation: dash-fade-up 0.5s ease-out 0.1s backwards; }
.st-key-dashboard_export [data-testid="stDownloadButton"] { display: flex; justify-content: flex-end; }
.st-key-dashboard_export button {
    background: linear-gradient(120deg, #2563EB 0%, #6D5BD0 50%, #8E5BD0 100%); background-size: 200% 100%; background-position: 0% 50%;
    color: #ffffff; border: none; border-radius: 999px; padding: 0.55rem 1.4rem; font-weight: 700; letter-spacing: 0.01em;
    box-shadow: 0 6px 16px -4px rgba(37, 99, 235, 0.55);
    transition: transform 0.2s ease, box-shadow 0.2s ease, background-position 0.5s ease;
}
.st-key-dashboard_export button p, .st-key-dashboard_export button span { color: #ffffff; }
.st-key-dashboard_export button:hover:not(:disabled) {
    background-position: 100% 50%; transform: translateY(-2px); box-shadow: 0 12px 22px -6px rgba(109, 91, 208, 0.65); color: #ffffff; border: none;
}
.st-key-dashboard_export button:hover:not(:disabled) [data-testid="stIconMaterial"] { animation: dash-bounce 0.7s ease-in-out infinite; }
.st-key-dashboard_export button:active:not(:disabled) { transform: translateY(0) scale(0.97); box-shadow: 0 4px 10px -4px rgba(37, 99, 235, 0.6); }
.st-key-dashboard_export button:focus-visible { outline: 3px solid rgba(37, 99, 235, 0.4); outline-offset: 2px; }
.st-key-dashboard_export button:disabled { background: var(--ui-border); box-shadow: none; }
.st-key-dashboard_export button:disabled p, .st-key-dashboard_export button:disabled span { color: var(--ui-text-muted); }
/* จอกลาง (480-1100px): KPI เรียง 2x2 (จอแคบกว่า 480px ซ้อนทีละช่อง) */
@media (min-width: 480px) and (max-width: 1100px) {
    [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .st-key-kpi_total_card) { flex-wrap: wrap; }
    [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .st-key-kpi_total_card) > [data-testid="stColumn"] {
        flex: 1 1 calc(50% - 1rem); min-width: calc(50% - 1rem);
    }
}
/* Tablet ขึ้นไป (768px+): แถวหัวส่วน ชื่อกินที่เหลือ ปุ่ม Export กว้างตามข้อความชิดขวา (ไม่ใช่สัดส่วนที่เหลือที่ว่างกลางแถว) */
@media (min-width: 768px) {
    [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .st-key-dashboard_export) { flex-wrap: nowrap; }
    [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .st-key-dashboard_export) > [data-testid="stColumn"]:first-child {
        flex: 1 1 0; min-width: 0;
    }
    [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .st-key-dashboard_export) > [data-testid="stColumn"]:last-child {
        flex: 0 0 auto; width: auto; min-width: max-content;
    }
    /* หัวการ์ดแนวโน้ม: ชื่อ | ช่วงเวลา | สวิตช์ Detail Graph อยู่แถวเดียวกัน สวิตช์ไม่ถูกตัดข้อความ */
    .st-key-trend_card [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] [data-testid="stSelectbox"]) { flex-wrap: nowrap; gap: 0.75rem; }
    .st-key-trend_card [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] [data-testid="stSelectbox"]) > [data-testid="stColumn"]:first-child {
        flex: 1 1 auto; width: auto; min-width: max-content;
    }
    .st-key-trend_card [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] [data-testid="stSelectbox"]) > [data-testid="stColumn"]:nth-child(2) {
        flex: 0 0 130px; min-width: 110px;
    }
    .st-key-trend_card [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] [data-testid="stSelectbox"]) > [data-testid="stColumn"]:last-child {
        flex: 0 0 auto; width: auto; min-width: max-content;
    }
}
/* มือถือ (<640px): ปุ่ม Export เต็มความกว้างใต้ชื่อ */
@media (max-width: 639px) {
    .st-key-dashboard_export, .st-key-dashboard_export [data-testid="stDownloadButton"], .st-key-dashboard_export button { width: 100%; justify-content: center; }
    .st-key-dashboard_export { margin-top: 10px; }
}
/* มือถือเล็ก (<480px): KPI ทีละช่อง การ์ดกระชับ ไอคอนไปอยู่หน้าป้าย */
@media (max-width: 479px) {
    [class*="st-key-kpi_"][class*="_card"] { border-radius: 12px; }
    .kpi-head { justify-content: flex-start; flex-direction: row-reverse; }
    .kpi-head .kpi-label { flex: 1 1 auto; }
    .kpi-icon { width: 34px; height: 34px; font-size: 17px; }
}
/* อุปกรณ์สัมผัส: ไม่มี hover จึงไม่ยกการ์ด/ปุ่มค้าง */
@media (hover: none) {
    [class*="st-key-kpi_"][class*="_card"]:hover, .st-key-dashboard_export button:hover:not(:disabled) { transform: none; }
}
/* ผู้ใช้ที่ตั้งค่าลดการเคลื่อนไหว: ปิด animation / transition ทั้งหมดของหน้านี้ */
@media (prefers-reduced-motion: reduce) {
    .section-head, .section-title::after, [class*="st-key-kpi_"][class*="_card"], .kpi-icon, .kpi-dot,
    .st-key-dashboard_export, .st-key-dashboard_export button, .st-key-dashboard_export [data-testid="stIconMaterial"] {
        animation: none !important; transition: none !important;
    }
}
"""


# ---------------------------------------------------------------------------
# เตรียมข้อมูล
# ---------------------------------------------------------------------------


def load_transaction_table(start_date: date, end_date: date) -> pd.DataFrame:
    """ดึงรายการตามช่วงวันที่ แล้วแปลงเป็น DataFrame ที่พร้อมใช้ทำกราฟ

    Args:
        start_date: วันที่เริ่มต้นจาก Date Filter
        end_date: วันที่สิ้นสุดจาก Date Filter

    Returns:
        DataFrame ที่มีคอลัมน์ตามตาราง transactions โดย date เป็นชนิดวันที่
        และ category ที่ว่างถูกแทนด้วย "ไม่ระบุ" (DataFrame ว่างถ้าไม่มีข้อมูล)
    """
    transactions = get_transactions(start_date=start_date.isoformat(), end_date=end_date.isoformat())
    transaction_table = pd.DataFrame(transactions)
    if transaction_table.empty:
        return transaction_table

    # errors="coerce" = วันที่ผิดรูปแบบจะกลายเป็นค่าว่าง แทนที่จะทำให้ทั้งหน้าพัง
    transaction_table["date"] = pd.to_datetime(transaction_table["date"], errors="coerce")
    transaction_table = transaction_table.dropna(subset=["date"])
    transaction_table["category"] = transaction_table["category"].fillna(UNSPECIFIED_CATEGORY_LABEL)
    return transaction_table


def resolve_price_window(period_label: str, start_date: date, end_date: date) -> tuple[date, date]:
    """หาช่วงวันที่ของการ์ด Price จากปุ่มช่วงเวลา (เช่น 7d = 7 วันสุดท้ายก่อนวันสิ้นสุดของ Date Filter)

    Args:
        period_label: ข้อความที่ผู้ใช้เลือก (key ของ PRICE_PERIOD_OPTIONS)
        start_date: วันที่เริ่มต้นจาก Date Filter
        end_date: วันที่สิ้นสุดจาก Date Filter

    Returns:
        (วันที่เริ่ม, วันที่สิ้นสุด) ซึ่งอยู่ในขอบเขตของ Date Filter เสมอ
    """
    period_days = PRICE_PERIOD_OPTIONS.get(period_label)
    if period_days is None:
        return start_date, end_date
    # นับรวมวันสิ้นสุดด้วย จึงลบ (จำนวนวัน - 1) แล้วไม่ให้เลยวันเริ่มของ Date Filter
    return max(start_date, end_date - timedelta(days=period_days - 1)), end_date


def build_trend_table(
    transaction_table: pd.DataFrame, start_date: date, end_date: date, split_by_category: bool
) -> pd.DataFrame:
    """รวมยอดเงินตามช่วงเวลา (และหมวดหมู่ถ้าต้องการ) สำหรับกราฟเส้น

    Args:
        transaction_table: ตารางจาก load_transaction_table (กรองช่วงเวลาแล้ว)
        start_date: วันที่เริ่มต้น (ใช้ตัดสินว่าจะรวมรายวันหรือรายเดือน)
        end_date: วันที่สิ้นสุด
        split_by_category: True = แยกเส้นตามหมวดหมู่, False = เส้นเดียวรวมทุกหมวด

    Returns:
        DataFrame คอลัมน์ period (จุดบนแกน X), category (เส้นแต่ละสี), total_price (แกน Y)
    """
    # ช่วงสั้น = แสดงรายวัน, ช่วงยาว = รวมเป็นรายเดือน (ปรับที่ DAILY_CHART_MAX_DAYS)
    is_daily = (end_date - start_date).days <= DAILY_CHART_MAX_DAYS
    period_frequency = "D" if is_daily else "M"

    trend_table = transaction_table.assign(
        period=transaction_table["date"].dt.to_period(period_frequency).dt.to_timestamp()
    )
    if split_by_category:
        return trend_table.groupby(["period", "category"], as_index=False)["total_price"].sum()

    total_trend = trend_table.groupby("period", as_index=False)["total_price"].sum()
    total_trend["category"] = TOTAL_LINE_LABEL  # ตั้งชื่อเส้นเดียวให้ Tooltip อ่านง่าย
    return total_trend


def get_spend_table(transaction_table: pd.DataFrame) -> pd.DataFrame:
    """เลือกเฉพาะรายการที่มีราคา Net Price (unit_price) เพื่อใช้คำนวณค่าใช้จ่าย

    Args:
        transaction_table: ตารางจาก load_transaction_table

    Returns:
        DataFrame เฉพาะแถวที่ unit_price เป็นตัวเลข (ว่างถ้าไม่มีข้อมูลราคา
        หรือฐานข้อมูลเก่ายังไม่มีคอลัมน์ unit_price) จะไม่ทำให้เกิด Error
    """
    if transaction_table.empty or "unit_price" not in transaction_table.columns:
        return transaction_table.iloc[0:0]
    spend_table = transaction_table.assign(
        unit_price=pd.to_numeric(transaction_table["unit_price"], errors="coerce")  # ค่าที่อ่านไม่ได้ = ว่าง
    )
    return spend_table.dropna(subset=["unit_price"])


def build_vendor_spend_table(transaction_table: pd.DataFrame) -> pd.DataFrame:
    """สรุปค่าใช้จ่าย (Net Price) แยกตามผู้ขาย สำหรับกราฟ Top Vendors by Spend

    Args:
        transaction_table: ตารางจาก load_transaction_table

    Returns:
        DataFrame คอลัมน์ vendor / spend เรียงจากยอดสูงสุด จำกัด TOP_VENDOR_LIMIT อันดับ
        (ว่างถ้าไม่มีข้อมูลราคา)
    """
    spend_table = get_spend_table(transaction_table)
    if spend_table.empty:
        return pd.DataFrame(columns=["vendor", "spend"])
    return (
        spend_table.groupby("vendor", as_index=False)["unit_price"]
        .sum()
        .rename(columns={"unit_price": "spend"})
        .sort_values("spend", ascending=False)
        .head(TOP_VENDOR_LIMIT)
    )


def build_top_vendor_table(transaction_table: pd.DataFrame) -> pd.DataFrame:
    """สรุปผู้ขายที่มียอดซื้อสูงสุด

    Args:
        transaction_table: ตารางจาก load_transaction_table

    Returns:
        DataFrame คอลัมน์ ผู้ขาย / จำนวนรายการ / ยอดรวม (บาท) เรียงจากยอดสูงสุด จำกัด TOP_VENDOR_LIMIT อันดับ
    """
    top_vendor_table = (
        transaction_table.groupby("vendor")
        .agg(order_count=("id", "count"), total_price=("total_price", "sum"))
        .sort_values("total_price", ascending=False)
        .head(TOP_VENDOR_LIMIT)
        .reset_index()
    )
    top_vendor_table["vendor"] = top_vendor_table["vendor"].map(shorten_vendor_name)  # แสดงผลเท่านั้น
    top_vendor_table.columns = ["Company", "จำนวนรายการ", "ยอดรวม (บาท)"]
    top_vendor_table.index = range(1, len(top_vendor_table) + 1)  # ให้ลำดับเริ่มที่ 1
    return top_vendor_table


# ---------------------------------------------------------------------------
# ส่วนแสดงผล
# ---------------------------------------------------------------------------


def render_header_row(start_date: date, end_date: date) -> None:
    """วาดแถวหัวส่วน: ชื่อ 'ภาพรวม' + ช่วงวันที่ที่เลือก ทางซ้าย และปุ่ม Export CSV ชิดขวา

    Args:
        start_date: วันที่เริ่มต้นจาก Date Filter
        end_date: วันที่สิ้นสุดจาก Date Filter
    """
    export_csv = build_export_csv(start_date, end_date)
    title_column, export_column = st.columns([3, 1], vertical_alignment="center")
    title_column.markdown(
        '<div class="section-head"><div class="section-title">ภาพรวม</div><br>'
        f'<span class="section-sub">{start_date:%d/%m/%Y} – {end_date:%d/%m/%Y}</span></div>',
        unsafe_allow_html=True,
    )
    export_column.download_button(
        "Export CSV",
        icon=":material/download:",
        data=export_csv,
        file_name=f"masterlist_{start_date.isoformat()}_{end_date.isoformat()}.csv",
        mime="text/csv",
        disabled=not export_csv,  # ไม่มีข้อมูลให้ปิดปุ่ม
        key="dashboard_export",
    )


def render_kpi_tile(
    card_key: str, label: str, value: str, sub_text: str, is_empty: bool = False, show_alert: bool = False
) -> None:
    """วาดการ์ดตัวเลขสรุป 1 ช่อง: ป้าย / ตัวเลขใหญ่ / ข้อความรอง

    Args:
        card_key: key ของการ์ด (ต้องลงท้ายด้วย _card และตรงกับสีแถบด้านซ้ายใน PAGE_CSS_RULES)
        label: ป้ายหัวช่อง
        value: ตัวเลขที่แสดง
        sub_text: ข้อความรองใต้ตัวเลข
        is_empty: True = ไม่มีข้อมูล แสดงตัวเลขเป็นสีเทา
        show_alert: True = แสดงจุดกะพริบหน้าป้าย (ใช้กับช่องที่มีรายการค้างต้องติดตาม)
    """
    alert_dot = '<span class="kpi-dot"></span>' if show_alert else ""
    value_class = "kpi-value kpi-empty" if is_empty else "kpi-value"
    with st.container(key=card_key):
        st.markdown(
            f'<div class="kpi-head"><div class="kpi-label">{alert_dot}{html.escape(label)}</div>'
            f'<div class="kpi-icon">{KPI_ICONS.get(card_key, "")}</div></div>'
            f'<div class="{value_class}">{html.escape(value)}</div>'
            f'<div class="kpi-sub">{html.escape(sub_text)}</div>',
            unsafe_allow_html=True,
        )


def render_kpi_row(transaction_table: pd.DataFrame) -> None:
    """วาดแถวตัวเลขสรุป 4 ช่อง: ยอดรวม / ค่าใช้จ่าย (Net Price) / จำนวนรายการ / รอใบกำกับภาษี

    Args:
        transaction_table: ตารางจาก load_transaction_table (ตาม Date Filter)
    """
    total_price = float(transaction_table["total_price"].sum()) if not transaction_table.empty else 0.0
    spend_table = get_spend_table(transaction_table)
    if transaction_table.empty:
        pending_table = transaction_table
        vendor_count = 0
    else:
        pending_table = transaction_table[transaction_table["invoice_status"] == STATUS_PENDING]
        vendor_count = int(transaction_table["vendor"].nunique())
    pending_price = float(pending_table["total_price"].sum()) if not pending_table.empty else 0.0

    total_column, spend_column, count_column, pending_column = st.columns(4, gap="medium")
    with total_column:
        render_kpi_tile("kpi_total_card", "ยอดรวมทั้งหมด (บาท)", f"{total_price:,.2f}", f"จาก {len(transaction_table):,} รายการ")
    with spend_column:
        # ยังไม่มีข้อมูลราคา = แสดง "–" แทน 0.00 เพื่อไม่ให้เข้าใจผิดว่าไม่มีค่าใช้จ่าย
        if spend_table.empty:
            render_kpi_tile("kpi_spend_card", "ค่าใช้จ่าย Net Price (บาท)", KPI_EMPTY_VALUE, "ยังไม่มีข้อมูลราคา", is_empty=True)
        else:
            render_kpi_tile(
                "kpi_spend_card", "ค่าใช้จ่าย Net Price (บาท)", f"{spend_table['unit_price'].sum():,.2f}", "ผลรวม Net Price"
            )
    with count_column:
        render_kpi_tile("kpi_count_card", "จำนวนรายการ", f"{len(transaction_table):,}", f"ผู้ขาย {vendor_count:,} ราย")
    with pending_column:
        render_kpi_tile(
            "kpi_pending_card",
            "รอใบกำกับภาษี",
            f"{len(pending_table):,}",
            f"ยอด {pending_price:,.2f} บาท",
            show_alert=not pending_table.empty,
        )


def build_trend_figure(trend_table: pd.DataFrame) -> go.Figure:
    """สร้างกราฟเส้นแนวโน้มยอดซื้อ แยกสีตามหมวดหมู่

    Args:
        trend_table: ตารางจาก build_trend_table

    Returns:
        Figure ของ Plotly พร้อมส่งให้ st.plotly_chart
    """
    # สร้างแผนที่สีให้ครบทุกหมวดที่มีในข้อมูล หมวดที่ไม่มีใน CATEGORY_COLORS ใช้สีสำรอง
    color_map = {
        category_name: CATEGORY_COLORS.get(category_name, FALLBACK_CATEGORY_COLOR)
        for category_name in trend_table["category"].unique()
    }
    color_map[TOTAL_LINE_LABEL] = TOTAL_LINE_COLOR  # เส้นรวมทุกหมวด (โหมดปิด Detail Graph)
    # เรียงเส้นใน Legend ตามหมวดอุปกรณ์หลักก่อน (Hardware, Software, Network, Service) ที่เหลือต่อท้าย
    category_order = [name for name in EQUIPMENT_CATEGORIES if name in color_map] + sorted(
        name for name in color_map if name not in EQUIPMENT_CATEGORIES
    )

    figure = px.line(
        trend_table,  # ตารางข้อมูลที่ใช้วาด
        x="period",  # แกน X: ช่วงเวลา (คอลัมน์ period) เปลี่ยนเป็นคอลัมน์อื่นเพื่อเปลี่ยนแกน X
        y="total_price",  # แกน Y: ยอดเงินรวม (คอลัมน์ total_price) เปลี่ยนเป็น count ฯลฯ ได้
        color="category",  # แยกเป็นเส้นตามหมวดหมู่ (ไม่ต้องการแยกเส้น ให้ลบบรรทัดนี้)
        color_discrete_map=color_map,  # สีของแต่ละเส้น มาจาก CATEGORY_COLORS ด้านบนไฟล์
        category_orders={"category": category_order},  # ลำดับเส้นใน Legend
        markers=True,  # แสดงจุดบนเส้น (จำเป็น เพราะช่วงที่มีข้อมูลวันเดียวจะไม่เห็นเส้น)
        labels={  # ชื่อที่แสดงใน Tooltip และ Legend
            "period": "ช่วงเวลา",  # ชื่อแกน X
            "total_price": "ยอดรวม (บาท)",  # ชื่อแกน Y
            "category": "หมวดหมู่",  # ชื่อ Legend
        },
    )
    figure.update_xaxes(
        title_text="ช่วงเวลา",  # หัวข้อแกน X
        tickformat="%d/%m/%Y",  # รูปแบบวันที่ที่แสดงบนแกน X (วัน/เดือน/ปี)
    )
    # ช่วงสั้น (<= 14 วัน) ให้แกน X ขีดทีละ 1 วันพอดี ไม่เช่นนั้น Plotly จะขีดทุกครึ่งวันแล้วได้วันที่ซ้ำกัน
    if (trend_table["period"].max() - trend_table["period"].min()).days <= 14:
        figure.update_xaxes(dtick=86400000)  # 86,400,000 มิลลิวินาที = 1 วัน
    figure.update_yaxes(
        title_text="ยอดรวม (บาท)",  # หัวข้อแกน Y
        tickformat=",.0f",  # ตัวเลขแกน Y มี , คั่นหลัก ไม่มีทศนิยม
        rangemode="tozero",  # บังคับให้แกน Y เริ่มที่ 0 กันกราฟดูผันผวนเกินจริง
    )
    figure.update_layout(
        legend_title_text="หมวดหมู่",  # หัวข้อกล่อง Legend
        margin={"l": 0, "r": 0, "t": 10, "b": 0},  # ระยะขอบกราฟ (ซ้าย ขวา บน ล่าง)
        font={"family": FONT_FAMILY, "color": PALETTE["text"]},  # ฟอนต์และสีตัวอักษรในกราฟ ให้ตรงกับธีมกลาง
        hovermode="x unified",  # เอาเมาส์ชี้แล้วแสดงทุกหมวดของวันนั้นพร้อมกัน
        showlegend=len(color_map) > 1 and TOTAL_LINE_LABEL not in trend_table["category"].unique(),  # เส้นเดียวไม่ต้องมี Legend
    )
    return figure


def render_empty_state(message: str = EMPTY_STATE_MESSAGE) -> None:
    """แสดงกล่อง 'ยังไม่มีข้อมูล' ในการ์ด (ใช้เมื่อกราฟหรือตารางไม่มีข้อมูลให้วาด)

    Args:
        message: ข้อความที่แสดงกลางกล่อง
    """
    st.markdown(f'<div class="empty-state">{message}</div>', unsafe_allow_html=True)


def render_trend_card(
    transaction_table: pd.DataFrame, start_date: date, end_date: date
) -> None:
    """วาดการ์ดแนวโน้มยอดซื้อ: ชื่อ + ปุ่มเลือกช่วงเวลา + สวิตช์ Detail Graph + ยอดรวมในช่วง + กราฟเส้น

    - ปุ่มช่วงเวลา (7d / 30d / ...): เลือกช่วงวันที่ของยอดรวมและกราฟ (ไม่เกินขอบเขต Date Filter)
    - สวิตช์ Detail Graph: ปิด = เส้นเดียวรวมทุกหมวด, เปิด = แยกเส้นตามหมวดหมู่ (Multi Line)

    Args:
        transaction_table: ตารางจาก load_transaction_table (ตาม Date Filter)
        start_date: วันที่เริ่มต้นจาก Date Filter
        end_date: วันที่สิ้นสุดจาก Date Filter
    """
    with st.container(key="trend_card"):
        title_column, range_column, detail_column = st.columns([1.2, 1.4, 1.4], vertical_alignment="center")
        title_column.markdown(
            '<div class="card-heading">แนวโน้มยอดซื้อ</div><div class="card-note">ยอดรวมตามช่วงเวลา</div>',
            unsafe_allow_html=True,
        )
        period_label = range_column.selectbox(
            "ช่วงเวลา", list(PRICE_PERIOD_OPTIONS.keys()), label_visibility="collapsed", key="price_range"
        )
        show_detail_graph = detail_column.toggle("Detail Graph", key="price_detail_graph")

        window_start, window_end = resolve_price_window(period_label, start_date, end_date)
        window_table = transaction_table
        if not transaction_table.empty:
            window_table = transaction_table[
                (transaction_table["date"] >= pd.Timestamp(window_start))
                & (transaction_table["date"] <= pd.Timestamp(window_end))
            ]

        window_total = window_table["total_price"].sum() if not window_table.empty else 0
        st.markdown(
            f'<div class="trend-total">{window_total:,.2f} <small>บาท</small></div>'
            f'<div class="card-note">ช่วง {window_start:%d/%m/%Y} – {window_end:%d/%m/%Y}</div>',
            unsafe_allow_html=True,
        )
        if window_table.empty:
            render_empty_state("ยังไม่มีข้อมูลในช่วงเวลาที่เลือก ลองเลือกช่วงที่ยาวขึ้น หรือขยาย Date Filter")
            return
        try:
            trend_table = build_trend_table(window_table, window_start, window_end, show_detail_graph)
            trend_figure = build_trend_figure(trend_table)
            trend_figure.update_layout(height=TREND_CHART_HEIGHT_PX)  # ให้สูงสมดุลกับการ์ด Equipment
            st.plotly_chart(trend_figure, width="stretch")
        except Exception as error:  # noqa: BLE001 - กราฟพังไม่ให้ทั้งหน้าล่ม
            logger.error("สร้างกราฟแนวโน้มไม่สำเร็จ: %s", error, exc_info=True)
            render_empty_state("แสดงกราฟไม่สำเร็จ ลองรีเฟรชหน้าเว็บ")


def build_equipment_list(start_date: date, end_date: date) -> pd.DataFrame:
    """สร้างรายการอุปกรณ์แยกตามหมวด: จำนวนรายการและยอดรวม (นับด้วย COUNT/SUM ใน SQLite)

    Args:
        start_date: วันที่เริ่มต้นจาก Date Filter
        end_date: วันที่สิ้นสุดจาก Date Filter

    Returns:
        DataFrame คอลัมน์ Equipment / Qty. / ยอดรวม (บาท) หมวดหลักเรียงตาม EQUIPMENT_CATEGORIES
        (แสดงครบแม้เป็น 0) แล้วตามด้วยหมวดอื่นที่มีข้อมูล
    """
    summary_by_category = {
        row["category"]: row for row in get_category_counts(start_date.isoformat(), end_date.isoformat())
    }
    other_categories = sorted(name for name in summary_by_category if name not in EQUIPMENT_CATEGORIES)
    rows = []
    for category_name in [*EQUIPMENT_CATEGORIES, *other_categories]:
        summary = summary_by_category.get(category_name, {})
        rows.append(
            {
                "Equipment": category_name,
                "Qty.": summary.get("quantity", 0),
                "ยอดรวม (บาท)": float(summary.get("total_price", 0)),
            }
        )
    return pd.DataFrame(rows)


def build_equipment_donut_figure(equipment_table: pd.DataFrame) -> go.Figure:
    """สร้างกราฟโดนัทสัดส่วนจำนวนรายการแยกตามหมวดอุปกรณ์ (สีตาม CATEGORY_COLORS)

    Args:
        equipment_table: ตารางจาก build_equipment_list (ต้องมี Qty. รวมมากกว่า 0)

    Returns:
        Figure ของ Plotly พร้อมส่งให้ st.plotly_chart (ตรงกลางโดนัทแสดงจำนวนรวม)
    """
    shown_table = equipment_table[equipment_table["Qty."] > 0]  # ตัดหมวดที่เป็น 0 ออก ไม่ให้เกิดชิ้นว่าง
    figure = go.Figure(
        go.Pie(
            labels=shown_table["Equipment"],
            values=shown_table["Qty."],
            hole=0.62,  # ขนาดรูตรงกลาง (0-1) ยิ่งมากวงยิ่งบาง
            marker={"colors": [CATEGORY_COLORS.get(name, FALLBACK_CATEGORY_COLOR) for name in shown_table["Equipment"]]},
            sort=False,  # คงลำดับหมวดตามตาราง
            textinfo="percent",
            hovertemplate="%{label}<br>%{value} รายการ (%{percent})<extra></extra>",
        )
    )
    figure.update_layout(
        showlegend=False,  # รายการหมวดวาดเองใต้กราฟ
        height=EQUIPMENT_DONUT_HEIGHT_PX,
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
        font={"family": FONT_FAMILY, "color": PALETTE["text"]},
        annotations=[
            {
                "text": f"<b>{int(shown_table['Qty.'].sum()):,}</b><br>รายการ",
                "x": 0.5, "y": 0.5, "showarrow": False, "font": {"size": 18},
            }
        ],
    )
    return figure


def build_equipment_rows_html(equipment_table: pd.DataFrame) -> str:
    """สร้าง HTML รายการหมวดอุปกรณ์ใต้โดนัท: จุดสี | ชื่อหมวด | จำนวน | ยอดรวม

    Args:
        equipment_table: ตารางจาก build_equipment_list

    Returns:
        ข้อความ HTML (ชื่อหมวดผ่าน html.escape แล้ว)
    """
    rows_html = []
    for row in equipment_table.itertuples(index=False):
        category_name = row[0]
        color = CATEGORY_COLORS.get(category_name, FALLBACK_CATEGORY_COLOR)
        rows_html.append(
            '<div class="equip-row">'
            f'<span class="equip-dot" style="background:{color}"></span>'
            f'<span class="equip-name">{html.escape(str(category_name))}</span>'
            f'<span class="equip-qty">{int(row[1]):,} รายการ</span>'
            f'<span class="equip-amount">{float(row[2]):,.2f}</span>'
            "</div>"
        )
    return "".join(rows_html)


def render_equipment_card(start_date: date, end_date: date) -> None:
    """วาดการ์ด Equipment: โดนัทสัดส่วนจำนวนรายการ + รายการหมวด (จำนวนและยอดรวม)

    Args:
        start_date: วันที่เริ่มต้นจาก Date Filter
        end_date: วันที่สิ้นสุดจาก Date Filter
    """
    with st.container(key="equipment_card"):
        st.markdown(
            '<div class="card-heading">Equipment</div><div class="card-note">สัดส่วนรายการตามหมวด</div>',
            unsafe_allow_html=True,
        )
        equipment_table = build_equipment_list(start_date, end_date)
        # ทุกหมวดเป็น 0 = ช่วงวันที่นี้ไม่มีรายการเลย
        if equipment_table.empty or equipment_table["Qty."].sum() == 0:
            render_empty_state()
            return
        st.plotly_chart(build_equipment_donut_figure(equipment_table), width="stretch")
        st.markdown(build_equipment_rows_html(equipment_table), unsafe_allow_html=True)


def shorten_vendor_name(vendor_name: str) -> str:
    """ตัดชื่อผู้ขายที่ยาวเกิน VENDOR_NAME_MAX_CHARS ให้ลงท้ายด้วย … (ใช้แสดงผลเท่านั้น ข้อมูลจริงไม่เปลี่ยน)

    Args:
        vendor_name: ชื่อผู้ขายเต็ม

    Returns:
        ชื่อที่ตัดแล้ว (ถ้าสั้นพออยู่แล้วคืนชื่อเดิม)
    """
    name = str(vendor_name)
    return name if len(name) <= VENDOR_NAME_MAX_CHARS else name[: VENDOR_NAME_MAX_CHARS - 1] + "…"


def build_vendor_spend_figure(vendor_spend_table: pd.DataFrame) -> go.Figure:
    """สร้างกราฟแท่งแนวนอน Top Vendors by Spend

    Args:
        vendor_spend_table: ตารางจาก build_vendor_spend_table (ต้องไม่ว่าง)

    Returns:
        Figure ของ Plotly พร้อมส่งให้ st.plotly_chart
    """
    chart_table = vendor_spend_table.assign(label=vendor_spend_table["vendor"].map(shorten_vendor_name))
    figure = px.bar(
        chart_table,  # ตารางข้อมูลที่ใช้วาด
        x="spend",  # แกน X: ค่าใช้จ่ายรวม (Net Price)
        y="label",  # แกน Y: ชื่อผู้ขาย (ตัดให้สั้น กันชื่อยาวแย่งที่แท่ง)
        orientation="h",  # แท่งแนวนอน ชื่อบริษัทยาวอ่านง่ายกว่า
        text="spend",  # แสดงตัวเลขที่ปลายแท่ง
        custom_data=["vendor"],  # ชื่อเต็มไว้แสดงใน Tooltip
        labels={"spend": "ค่าใช้จ่าย (บาท)", "label": "ผู้ขาย"},  # ชื่อใน Tooltip
    )
    figure.update_traces(
        marker_color=VENDOR_BAR_COLOR,  # สีแท่ง (แก้ที่ค่าคงที่ด้านบนไฟล์)
        texttemplate="%{x:,.0f}",  # ตัวเลขมี , คั่นหลัก ไม่มีทศนิยม (ค่าเต็มดูได้ใน Tooltip / ตาราง)
        textposition="outside",  # ตัวเลขอยู่ปลายแท่ง ไม่ซ้อนในแท่งสั้น
        cliponaxis=False,  # ไม่ตัดตัวเลขที่ปลายแท่งยาวสุด
        hovertemplate="%{customdata[0]}<br>%{x:,.2f} บาท<extra></extra>",  # ข้อความ Tooltip
    )
    # ซ่อนตัวเลขแกน X (มีตัวเลขที่ปลายแท่งแล้ว) เหลือพื้นที่ให้แท่ง; เว้นขวา 20% ให้ตัวเลขปลายแท่งไม่ล้น
    figure.update_xaxes(title_text="", showticklabels=False, showgrid=False, rangemode="tozero")
    figure.update_xaxes(range=[0, float(vendor_spend_table["spend"].max()) * 1.35])
    figure.update_yaxes(title_text="", autorange="reversed", automargin=True)  # กลับแกน Y ให้อันดับ 1 อยู่บนสุด
    figure.update_layout(
        margin={"l": 0, "r": 0, "t": 10, "b": 0},  # ระยะขอบกราฟ (ซ้าย ขวา บน ล่าง)
        font={"family": FONT_FAMILY, "color": PALETTE["text"]},  # ฟอนต์ให้ตรงกับธีมกลาง
        height=max(VENDOR_CHART_MIN_HEIGHT, VENDOR_CHART_ROW_HEIGHT * len(vendor_spend_table)),  # สูงตามจำนวนแท่ง
    )
    return figure


def render_vendor_chart_card(transaction_table: pd.DataFrame) -> None:
    """วาดการ์ด Top Vendors: กราฟแท่งแนวนอนค่าใช้จ่าย (Net Price) แยกตามผู้ขาย

    Args:
        transaction_table: ตารางจาก load_transaction_table
    """
    with st.container(key="vendor_chart_card"):
        st.markdown(
            '<div class="card-heading">Top Vendors</div><div class="card-note">ค่าใช้จ่าย (Net Price) แยกตามผู้ขาย</div>',
            unsafe_allow_html=True,
        )
        if transaction_table.empty:
            render_empty_state("ยังไม่มีข้อมูลผู้ขายในช่วงวันที่ที่เลือก")
            return
        vendor_spend_table = build_vendor_spend_table(transaction_table)
        if vendor_spend_table.empty:
            render_empty_state("ยังไม่มีข้อมูลราคา (Net Price) จึงยังสร้างกราฟค่าใช้จ่ายไม่ได้")
            return
        st.plotly_chart(build_vendor_spend_figure(vendor_spend_table), width="stretch")


def render_vendor_table_card(transaction_table: pd.DataFrame) -> None:
    """วาดการ์ด Vendor: ตารางรายชื่อบริษัท (Company) เรียงตามยอดซื้อ

    Args:
        transaction_table: ตารางจาก load_transaction_table
    """
    with st.container(key="vendor_table_card"):
        st.markdown(
            '<div class="card-heading">Vendor</div><div class="card-note">ผู้ขายเรียงตามยอดซื้อ</div>',
            unsafe_allow_html=True,
        )
        if transaction_table.empty:
            render_empty_state("ยังไม่มีข้อมูลผู้ขายในช่วงวันที่ที่เลือก")
            return
        render_readonly_grid(
            build_top_vendor_table(transaction_table),
            key="dashboard_top_vendor",
            money_columns=("ยอดรวม (บาท)",),
            right_aligned_columns=("จำนวนรายการ",),
        )


def build_export_csv(start_date: date, end_date: date) -> bytes:
    """สร้างไฟล์ CSV ของรายการทั้งหมดในช่วงวันที่ (ใช้กับปุ่ม Export)

    Args:
        start_date: วันที่เริ่มต้นจาก Date Filter
        end_date: วันที่สิ้นสุดจาก Date Filter

    Returns:
        ข้อมูล CSV แบบ UTF-8 มี BOM เพื่อให้ Excel เปิดภาษาไทยได้ถูกต้อง (ว่างถ้าไม่มีข้อมูล)
    """
    transactions = get_transactions(start_date=start_date.isoformat(), end_date=end_date.isoformat())
    if not transactions:
        return b""
    return pd.DataFrame(transactions).to_csv(index=False).encode("utf-8-sig")


def render(start_date: date, end_date: date) -> None:
    """แสดงเนื้อหาหน้า Dashboard (app.py เรียกฟังก์ชันนี้ หลังวาดหัวหน้าและ Date Filter แล้ว)

    Args:
        start_date: วันที่เริ่มต้นจาก Date Filter
        end_date: วันที่สิ้นสุดจาก Date Filter

    Returns:
        ไม่มีค่าคืน (วาดหน้าจอด้วย Streamlit)
    """
    st.markdown(build_css(PAGE_CSS_RULES), unsafe_allow_html=True)

    transaction_table = load_transaction_table(start_date, end_date)

    # ส่วนที่ 1: หัวส่วน (ชื่อ + ช่วงวันที่) และปุ่ม Export ชิดขวา
    render_header_row(start_date, end_date)

    # ส่วนที่ 2: ตัวเลขสรุป 4 ช่อง
    render_kpi_row(transaction_table)

    # ส่วนที่ 3: แถวกลาง ซ้าย = แนวโน้มยอดซื้อ / ขวา = Equipment (โดนัท + รายการหมวด)
    trend_column, equipment_column = st.columns(TREND_ROW_RATIO, gap="medium")
    with trend_column:
        render_trend_card(transaction_table, start_date, end_date)
    with equipment_column:
        render_equipment_card(start_date, end_date)

    # ส่วนที่ 4: แถวล่าง ซ้าย = กราฟ Top Vendors / ขวา = ตาราง Vendor
    chart_column, table_column = st.columns(VENDOR_ROW_RATIO, gap="medium")
    with chart_column:
        render_vendor_chart_card(transaction_table)
    with table_column:
        render_vendor_table_card(transaction_table)
