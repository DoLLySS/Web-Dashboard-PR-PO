"""หน้า Dashboard: ตัวเลขสรุป (KPI), แนวโน้มยอดซื้อ, สัดส่วนอุปกรณ์ (Equipment) และผู้ขาย (Vendor)

โครงหน้า (การ์ดชั้นเดียว พื้นขาว):
    หัวหน้า (ชื่อหน้า + Date Filter) อยู่ใน app.py
    ภาพรวม  [ชิปวันที่]                                   [Export CSV]
    ┌────────────────┬────────────────┬────────────────┐
    │ ยอดรวม         │ จำนวนรายการ     │ รอใบกำกับภาษี   │   <- KPI 3 ช่อง
    └────────────────┴────────────────┴────────────────┘
    ┌───────────────────────────┬───────────────┐
    │ แนวโน้มยอดซื้อ [1M..1Y][Detail]│ Equipment โดนัท │
    └───────────────────────────┴───────────────┘
    ┌───────────────────────────────────────────┐
    │ Vendor (อันดับ + แถบสัดส่วน เต็มความกว้าง)     │
    └───────────────────────────────────────────┘

ข้อมูลทั้งหมดดึงจาก database.py (ทุกส่วนอิง Date Filter ของ app.py)
"""

import html
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config.constants import EQUIPMENT_CATEGORIES
from config.logging_setup import get_logger
from config.styles import FONT_FAMILY, PALETTE
from data.database import STATUS_PENDING, get_category_counts, get_transactions
from ui_common import build_css

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

# ถ้าช่วงวันที่ที่เลือกยาวเกินกี่วัน กราฟแนวโน้มจะรวมเป็นรายเดือนแทนรายวัน
DAILY_CHART_MAX_DAYS: int = 62

# ตัวเลือกช่วงเวลาของการ์ด Price: {ข้อความบนปุ่ม: (ชนิดช่วง, ค่า)} ตัวเลือกแรกคือค่าเริ่มต้น
#   ("days", N)    = N วันย้อนหลังนับจากวันสิ้นสุดของ Date Filter
#   ("quarter", Q) = ไตรมาสที่ Q (1-4) ของปีที่วันสิ้นสุด Date Filter อยู่ (Q1 = ม.ค.-มี.ค. ...)
#   ("year", 0)    = ทั้งปีปฏิทิน (รวม 4 ไตรมาส) ของปีที่วันสิ้นสุด Date Filter อยู่
# ช่วงที่เลือกจะถูกตัดไม่ให้เกินขอบเขตของ Date Filter เสมอ
PRICE_PERIOD_OPTIONS: dict[str, tuple[str, int]] = {
    "1M": ("days", 30),  # 1 เดือน = 30 วันย้อนหลัง
    "Q1": ("quarter", 1),
    "Q2": ("quarter", 2),
    "Q3": ("quarter", 3),
    "Q4": ("quarter", 4),
    "1Y": ("year", 0),  # ยาวกว่า DAILY_CHART_MAX_DAYS กราฟจึงรวมเป็นรายเดือนเอง
}

# key ของช่อง Date Filter ที่ app.py สร้างไว้ (ต้องตรงกับ render_date_filter ใน app.py) ปุ่มช่วงเวลาจะเขียนค่าลง key เหล่านี้
FILTER_START_KEY: str = "filter_start_date"
FILTER_END_KEY: str = "filter_end_date"

# เส้นรวมทุกหมวด (ใช้ตอนปิด Detail Graph) ชื่อที่แสดงใน Legend/Tooltip และสีเส้น
TOTAL_LINE_LABEL: str = "รวมทุกหมวด"
TOTAL_LINE_COLOR: str = "#2563EB"

# สัดส่วนความกว้างของแต่ละแถว: [ซ้าย, ขวา]
TREND_ROW_RATIO: list[int] = [2, 1]  # แถวกลาง: แนวโน้มยอดซื้อ | Equipment

# ข้อความเมื่อไม่มีข้อมูลในการ์ด (แสดงในกล่องสวย ๆ แทน Error / กราฟที่พัง)
EMPTY_STATE_MESSAGE: str = "ยังไม่มีข้อมูล"

# ไอคอน SVG เส้นเดียวของ KPI แต่ละช่อง (key ของการ์ด -> SVG) สีตามสี accent ของการ์ด (currentColor)
SVG_ATTRS: str = 'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"'
KPI_ICONS: dict[str, str] = {
    "kpi_total_card": f'<svg {SVG_ATTRS}><path d="M3 7h15a3 3 0 0 1 3 3v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7z"/><path d="M3 7l12-3v3"/><circle cx="16.5" cy="14" r="1.2"/></svg>',
    "kpi_count_card": f'<svg {SVG_ATTRS}><path d="M4 6h16M4 12h16M4 18h10"/></svg>',
    "kpi_pending_card": f'<svg {SVG_ATTRS}><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
}
# ไอคอนปฏิทินหน้าชิปช่วงวันที่ในหัวส่วน
CALENDAR_ICON: str = f'<svg {SVG_ATTRS} stroke="#64748B"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>'

# ความสูงกราฟ (px): แถวกลาง กราฟแนวโน้มกับโดนัท+รายการ Equipment ให้สูงใกล้กัน / แถวล่าง กราฟ Vendor กับตาราง
# ปรับเลขเหล่านี้ถ้าอยากให้การ์ดสองฝั่งสูงเท่ากันขึ้น/น้อยลง (การ์ดคู่เดียวกันยืดให้สูงเท่ากันอยู่แล้วด้วย CSS)
TREND_CHART_HEIGHT_PX: int = 400
# ถ้าจุดบนเส้นมีเกินจำนวนนี้ จะซ่อนจุดทั้งหมดให้เห็นแต่เส้น (กราฟช่วงยาวจะได้ไม่แน่น) เหลือแค่จุดสูงสุด
TREND_MARKER_MAX_POINTS: int = 31
# ไอคอนของช่องสรุปใต้กราฟ (ยอดสูงสุด / เฉลี่ยต่อวัน / จำนวนรายการ) และสีประจำช่อง
TREND_STAT_ICONS: dict[str, str] = {
    "peak": f'<svg {SVG_ATTRS}><path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/></svg>',
    "average": f'<svg {SVG_ATTRS}><path d="M4 12h16"/><path d="M4 6v12M20 6v12"/><circle cx="12" cy="12" r="2.5"/></svg>',
    "count": f'<svg {SVG_ATTRS}><path d="M9 6h11M9 12h11M9 18h11"/><path d="M4 6h.01M4 12h.01M4 18h.01"/></svg>',
}
# ไอคอนกราฟในกล่อง "ยังไม่มีข้อมูล" ของการ์ดแนวโน้ม
TREND_EMPTY_ICON: str = (
    f'<svg {SVG_ATTRS} stroke="#94A3B8" stroke-width="1.5"><path d="M3 3v18h18"/><path d="M7 15l4-4 3 3 5-6"/></svg>'
)
EQUIPMENT_DONUT_HEIGHT_PX: int = 270
EQUIPMENT_DONUT_HOLE: float = 0.6  # ขนาดรูตรงกลางโดนัท (0-1) ยิ่งมากวงยิ่งบาง
EQUIPMENT_TOP_PULL: float = 0.03  # ดึงชิ้นที่ใหญ่สุดออกจากวงเล็กน้อยเพื่อเน้น

# กราฟใช้พื้นโปร่งใสให้กลืนกับการ์ดขาว เส้นกริดสีอ่อน และเวลา transition ของ Plotly ตอนข้อมูลเปลี่ยน (มิลลิวินาที)
CHART_GRID_COLOR: str = "#EEF2F6"
CHART_TRANSITION_MS: int = 400
TRANSPARENT: str = "rgba(0,0,0,0)"

# CSS เฉพาะหน้า Dashboard (กฎกลางของการ์ดอยู่ที่ ui_common.py)
PAGE_CSS_RULES: str = """
/* ---- ระบบดีไซน์ของหน้านี้: เวลา/จังหวะ animation อยู่ที่เดียว แก้ตัวแปรแล้วทั้งหน้าเปลี่ยนตาม ---- */
:root { --dash-ease: cubic-bezier(0.22, 0.61, 0.36, 1); --dash-in: 0.5s; }
/* กล่อง "ยังไม่มีข้อมูล": พื้นอ่อน เส้นประ ข้อความกลางกล่อง */
.empty-state {
    display: flex; align-items: center; justify-content: center; min-height: 160px; text-align: center; padding: 0 16px;
    background: var(--ui-inner-bg); border: 1px dashed var(--ui-dashed-border); border-radius: 8px;
    color: var(--ui-text-muted); font-size: 16px;
}
/* การ์ดชั้นเดียว: พื้นขาว + ขอบบาง + เงานุ่ม ชี้แล้วเงาลึกขึ้นเล็กน้อย (พื้นและเงาหลักมาจากกฎกลางใน ui_common.py) */
[class*="st-key-"][class*="_card"] { border: 1px solid var(--ui-border); transition: box-shadow 0.25s ease, border-color 0.25s ease; }
[class*="st-key-"][class*="_card"]:hover { border-color: #CBD5E1; box-shadow: 0 8px 24px -12px rgba(15, 23, 42, 0.18); }
/* การ์ดที่อยู่แถวเดียวกันสูงเท่ากัน: ให้กล่องห่อการ์ดยืดเต็มคอลัมน์ (คอลัมน์ของ Streamlit ยืดเท่ากันอยู่แล้ว) */
[data-testid="stColumn"] > [data-testid="stVerticalBlock"] > [data-testid="stLayoutWrapper"]:has(> [class*="st-key-"][class*="_card"]) { flex: 1 1 auto; }
/* ---- Animation: เลื่อนขึ้น + จางเข้า / เปิดเผยกราฟ / จุดเตือนกะพริบเบา ๆ / ลูกศรเด้งลง ---- */
@property --reveal-angle { syntax: "<angle>"; inherits: false; initial-value: 360deg; }
@keyframes dash-fade-up { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: translateY(0); } }
@keyframes dash-fade { from { opacity: 0; } to { opacity: 1; } }
@keyframes dash-wipe { from { clip-path: inset(0 100% 0 0); } to { clip-path: inset(0 -2% 0 0); } }
@keyframes dash-pop { from { opacity: 0; transform: scale(0.85); } to { opacity: 1; transform: scale(1); } }
@keyframes dash-sweep { from { --reveal-angle: 0deg; } to { --reveal-angle: 360deg; } }
@keyframes dash-grow-x { from { transform: scaleX(0); } to { transform: scaleX(1); } }
@keyframes dash-slide-in { from { opacity: 0; transform: translateX(-10px); } to { opacity: 1; transform: translateX(0); } }
@keyframes dash-pulse { 0% { box-shadow: 0 0 0 0 rgba(232, 131, 42, 0.55); } 70% { box-shadow: 0 0 0 8px rgba(232, 131, 42, 0); } 100% { box-shadow: 0 0 0 0 rgba(232, 131, 42, 0); } }
@keyframes dash-bounce { 0%, 100% { transform: translateY(0); } 50% { transform: translateY(3px); } }
/* เข้าฉากเป็นลำดับ: หัวหน้า -> KPI -> แถวกลาง -> แถวล่าง (ตั้งค่าหน่วงที่การ์ดแต่ละใบ) */
[class*="st-key-"][class*="_card"] { animation: dash-fade-up var(--dash-in) var(--dash-ease) var(--enter-delay, 0ms) backwards; }
.st-key-trend_card { --enter-delay: 320ms; }
.st-key-equipment_card { --enter-delay: 400ms; }
.st-key-vendor_table_card { --enter-delay: 480ms; }
/* หัวส่วนของหน้า: ชื่อสีเข้มเรียบ + ขีดสี accent + ชิปวันที่ */
.section-head { animation: dash-fade-up var(--dash-in) var(--dash-ease) both; }
.section-title { font-size: clamp(22px, 1vw + 14px, 28px); font-weight: 800; line-height: 1.2; letter-spacing: -0.01em; color: var(--ui-text); }
.section-title::after {
    content: ""; display: block; width: 32px; height: 3px; margin-top: 6px; border-radius: 3px;
    background: var(--ui-accent); transition: width 0.3s var(--dash-ease);
}
.section-head:hover .section-title::after { width: 56px; }
.section-sub {
    display: inline-flex; align-items: center; gap: 8px; margin-top: 10px; padding: 4px 12px;
    font-size: 14px; font-weight: 600; color: var(--ui-text-muted); font-variant-numeric: tabular-nums;
    background: var(--ui-card-bg); border: 1px solid var(--ui-border); border-radius: 8px;
}
.section-sub svg { width: 14px; height: 14px; flex: 0 0 auto; }
/* ชื่อการ์ด + คำอธิบายใต้ชื่อ */
.card-heading { font-size: 17px; font-weight: 800; color: var(--ui-text); line-height: 1.3; letter-spacing: -0.005em; }
.card-note { font-size: 14px; color: var(--ui-text-muted); margin-top: 2px; }
/* KPI: แถบสี accent บาง ๆ ด้านบน (สีละช่อง) ชิปไอคอน SVG เรียบ ๆ เข้าฉากทีละช่อง ยกขึ้นเมื่อชี้ */
.st-key-kpi_total_card { --kpi-accent: #2563EB; --enter-delay: 0ms; }
.st-key-kpi_count_card { --kpi-accent: #8E5BD0; --enter-delay: 70ms; }
.st-key-kpi_pending_card { --kpi-accent: #E8832A; --enter-delay: 140ms; }
[class*="st-key-kpi_"][class*="_card"] {
    position: relative; overflow: hidden; container-type: inline-size;
    transition: transform 0.25s var(--dash-ease), box-shadow 0.25s ease, border-color 0.25s ease;
}
[class*="st-key-kpi_"][class*="_card"]::before {
    content: ""; position: absolute; left: 0; top: 0; right: 0; height: 3px; background: var(--kpi-accent);
    transform-origin: left; animation: dash-grow-x 0.7s var(--dash-ease) calc(var(--enter-delay) + 150ms) backwards;
}
[class*="st-key-kpi_"][class*="_card"]:hover {
    transform: translateY(-3px); border-color: color-mix(in srgb, var(--kpi-accent) 40%, var(--ui-border));
    box-shadow: 0 14px 28px -14px color-mix(in srgb, var(--kpi-accent) 55%, transparent), 0 2px 6px rgba(15, 23, 42, 0.05);
}
.kpi-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.kpi-label { display: flex; align-items: center; gap: 8px; font-size: 16px; font-weight: 700; letter-spacing: 0.01em; color: #475569; }
.kpi-icon {
    flex: 0 0 auto; display: grid; place-items: center; width: 36px; height: 36px; border-radius: 10px;
    background: color-mix(in srgb, var(--kpi-accent) 12%, #ffffff); color: var(--kpi-accent); transition: transform 0.3s var(--dash-ease);
}
.kpi-icon svg { width: 19px; height: 19px; }
[class*="st-key-kpi_"][class*="_card"]:hover .kpi-icon { transform: scale(1.1); }
/* ตัวเลขหลักไล่สีตาม accent ของการ์ด (color สำรองไว้เผื่อเบราว์เซอร์ไม่รองรับ background-clip: text) */
.kpi-value {
    font-size: clamp(26px, 17cqi, 46px); font-weight: 800; color: var(--kpi-accent); line-height: 1.2; margin: 10px 0 6px;
    font-variant-numeric: tabular-nums; white-space: nowrap; animation: dash-slide-in 0.6s var(--dash-ease) calc(var(--enter-delay) + 120ms) backwards;
}
@supports (-webkit-background-clip: text) or (background-clip: text) {
    .kpi-value {
        background: linear-gradient(100deg, color-mix(in srgb, var(--kpi-accent) 62%, #0f172a), var(--kpi-accent));
        -webkit-background-clip: text; background-clip: text; -webkit-text-fill-color: transparent;
    }
}
/* ทศนิยมเล็กและเบากว่า ให้ตัวเลขหลักเด่น */
.kpi-decimal { font-size: 0.6em; font-weight: 700; opacity: 0.7; }
/* การ์ดแคบ (เช่น จอ 1100-1500px ที่เปิด sidebar): ซ่อนชิปไอคอนให้ป้ายอยู่บรรทัดเดียว การ์ดทุกช่องสูงเท่ากัน */
@container (max-width: 205px) {
    .kpi-icon { display: none; }
    .kpi-label { font-size: 15px; }
    .kpi-head { min-height: 44px; align-items: flex-start; }
}
.kpi-sub { font-size: 15px; font-weight: 500; color: #475569; }
.kpi-em { font-weight: 800; color: color-mix(in srgb, var(--kpi-accent) 80%, #0f172a); font-variant-numeric: tabular-nums; }
.kpi-dot { flex: 0 0 auto; width: 9px; height: 9px; border-radius: 50%; background: #E8832A; animation: dash-pulse 1.8s infinite; }
/* ---- การ์ดแนวโน้มยอดซื้อ: ตัวอักษรใหญ่อ่านง่าย + ยอดรวมไล่สี + ชิป % + ช่องสรุป 3 ช่องมีไอคอน ----
   ส่วนที่ถูกวาดใหม่ทุกครั้งที่เปลี่ยนช่วงเวลา (ยอดรวม/แถบสรุป) ใช้ animation สั้นและไม่หน่วง เพื่อไม่ให้กะพริบ */
.st-key-trend_card .card-heading { display: flex; align-items: center; gap: 12px; font-size: 24px; font-weight: 800; letter-spacing: -0.01em; }
.st-key-trend_card .card-heading::before {
    content: ""; flex: 0 0 auto; width: 5px; height: 26px; border-radius: 3px; background: linear-gradient(180deg, #2563EB, #2DD4BF);
}
.st-key-trend_card .card-note { font-size: 15px; }
.st-key-trend_card .card-heading + .card-note { margin-left: 17px; }
.trend-clamp { white-space: nowrap; color: #B45309; font-weight: 600; }
.trend-hero-row { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 14px; margin-top: 4px; }
.trend-total {
    font-size: clamp(36px, 1.6vw + 24px, 48px); font-weight: 800; line-height: 1.12; letter-spacing: -0.025em; font-variant-numeric: tabular-nums;
    color: #1E3A8A; background: linear-gradient(135deg, #1E3A8A 10%, #2563EB 90%); -webkit-background-clip: text; background-clip: text;
    -webkit-text-fill-color: transparent; animation: dash-fade-up 0.4s var(--dash-ease) backwards;
}
.trend-total small {
    display: inline-block; vertical-align: middle; margin-left: 4px; padding: 3px 12px; border-radius: 999px; background: #EFF6FF;
    font-size: 16px; font-weight: 700; letter-spacing: 0; -webkit-text-fill-color: #2563EB; color: #2563EB;
}
.trend-total.trend-total-empty { background: none; -webkit-text-fill-color: var(--ui-text-muted); color: var(--ui-text-muted); }
.trend-delta {
    display: inline-flex; align-items: center; gap: 8px; padding: 6px 14px 6px 8px; border-radius: 999px;
    font-size: 17px; font-weight: 800; font-variant-numeric: tabular-nums; animation: dash-pop 0.45s var(--dash-ease) 0.1s backwards;
}
.trend-delta em { font-style: normal; font-size: 15px; font-weight: 500; opacity: 0.8; }
.trend-delta-arrow { display: inline-grid; place-items: center; width: 22px; height: 22px; border-radius: 50%; font-size: 10px; background: rgba(255, 255, 255, 0.85); }
.trend-delta-up { color: #1D4ED8; background: #DBEAFE; }
.trend-delta-down { color: #475569; background: #E2E8F0; }
.trend-delta-flat { color: #64748B; background: #F1F5F9; }
.trend-stats { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; margin-top: 6px; container-type: inline-size; }
.trend-stat {
    --stat-color: #2563EB; --stat-tint: #EFF6FF;
    position: relative; overflow: hidden; padding: 16px 18px 14px; background: var(--ui-inner-bg); border: 1px solid var(--ui-border); border-radius: 14px;
    transition: transform 0.2s var(--dash-ease), box-shadow 0.2s ease, border-color 0.2s ease; animation: dash-fade-up 0.4s var(--dash-ease) backwards;
}
.trend-stat::before { content: ""; position: absolute; inset: 0 0 auto 0; height: 4px; background: var(--stat-color); opacity: 0.85; }
.trend-stat-average { --stat-color: #0D9488; --stat-tint: #F0FDFA; }
.trend-stat-count { --stat-color: #4F46E5; --stat-tint: #EEF2FF; }
/* การ์ดสูงกว่าเนื้อหา (คู่กับ Equipment ที่สูงกว่า): ดันแถบสรุปลงชิดล่างการ์ด ที่ว่างไปอยู่ระหว่างกราฟกับแถบ ไม่ใช่ใต้การ์ด */
.st-key-trend_card > [data-testid="stElementContainer"]:has(.trend-stats) { margin-top: auto; }
.trend-stat:nth-child(2) { animation-delay: 0.06s; }
.trend-stat:nth-child(3) { animation-delay: 0.12s; }
.trend-stat:hover { transform: translateY(-3px); border-color: var(--stat-color); box-shadow: 0 10px 22px -12px rgba(15, 23, 42, 0.35); }
.trend-stat-head { display: flex; align-items: center; gap: 10px; }
.trend-stat-icon { display: inline-grid; place-items: center; flex: 0 0 auto; width: 32px; height: 32px; border-radius: 10px; background: var(--stat-tint); color: var(--stat-color); }
.trend-stat-icon svg { width: 18px; height: 18px; }
.trend-stat-label { font-size: 15px; font-weight: 700; color: var(--ui-text-muted); }
.trend-stat-value { margin-top: 10px; font-size: 32px; font-weight: 800; color: var(--ui-text); line-height: 1.15; letter-spacing: -0.02em; font-variant-numeric: tabular-nums; }
.trend-stat-value small { margin-left: 6px; font-size: 15px; font-weight: 600; letter-spacing: 0; color: var(--ui-text-muted); }
.trend-stat-note { margin-top: 4px; font-size: 14px; color: var(--ui-text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
/* การ์ดแคบ (จอ ~1280px ที่เปิด sidebar): ลดขนาดช่องสรุปให้พอดี หน่วยไปอยู่บรรทัดใต้ตัวเลข ป้ายไม่ตัดบรรทัด */
@container (max-width: 600px) {
    .trend-stat { padding: 14px 12px 12px; }
    .trend-stat-head { gap: 8px; }
    .trend-stat-icon { display: none; }
    .trend-stat-label { font-size: 14px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .trend-stat-value { font-size: 28px; }
    .trend-stat-value small { display: block; margin: 0; font-size: 14px; }
}
/* กล่อง "ยังไม่มีข้อมูล" ของการ์ดแนวโน้ม: สูงเท่ากราฟ+แถบสรุป การ์ดจึงไม่ยุบ */
.trend-empty {
    display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px; min-height: 400px; margin-top: 8px;
    text-align: center; padding: 0 16px; background: var(--ui-inner-bg); border: 1px dashed var(--ui-dashed-border); border-radius: 12px;
    animation: dash-fade 0.5s ease backwards;
}
.trend-empty svg { width: 52px; height: 52px; margin-bottom: 4px; color: #94A3B8; }
.trend-empty-title { font-size: 19px; font-weight: 700; color: var(--ui-text); }
.trend-empty-text { font-size: 16px; color: var(--ui-text-muted); }
.st-key-price_detail_graph label p { font-size: 15px; font-weight: 600; }
/* ปุ่มช่วงเวลา (segmented): 6 ช่องกว้างเท่ากัน (1M Q1 Q2 Q3 Q4 1Y) แผ่นขาว ::before เลื่อนไปอยู่ใต้ปุ่มที่เลือก (left/width เปลี่ยนแบบนุ่ม) */
.st-key-price_range [data-testid="stButtonGroup"] {
    display: block; padding: 4px; width: 330px; max-width: 100%; margin-left: auto; background: #E9EEF5; border-radius: 14px;
    box-shadow: inset 0 1px 2px rgba(15, 23, 42, 0.08);
}
.st-key-price_range [role="radiogroup"] {
    --pill-left: 0; --pill-width: 0.16667; position: relative; display: grid; grid-template-columns: repeat(6, 1fr); gap: 0; width: 100%;
}
.st-key-price_range [role="radiogroup"]::before {
    content: ""; position: absolute; top: 0; bottom: 0; left: calc(100% * var(--pill-left)); width: calc(100% * var(--pill-width));
    background: #FFFFFF; border-radius: 10px; box-shadow: 0 2px 6px rgba(15, 23, 42, 0.16), 0 1px 1px rgba(15, 23, 42, 0.06);
    transition: left 0.38s cubic-bezier(0.34, 1.12, 0.5, 1), width 0.38s cubic-bezier(0.34, 1.12, 0.5, 1);
}
.st-key-price_range [role="radiogroup"]:has(> button:nth-child(2)[aria-checked="true"]) { --pill-left: 0.16667; }
.st-key-price_range [role="radiogroup"]:has(> button:nth-child(3)[aria-checked="true"]) { --pill-left: 0.33333; }
.st-key-price_range [role="radiogroup"]:has(> button:nth-child(4)[aria-checked="true"]) { --pill-left: 0.5; }
.st-key-price_range [role="radiogroup"]:has(> button:nth-child(5)[aria-checked="true"]) { --pill-left: 0.66667; }
.st-key-price_range [role="radiogroup"]:has(> button:nth-child(6)[aria-checked="true"]) { --pill-left: 0.83333; }
.st-key-price_range button {
    position: relative; z-index: 1; border: none !important; background: transparent !important; box-shadow: none !important; border-radius: 10px !important;
    padding: 4px 2px; min-height: 42px; justify-content: center; transition: transform 0.15s ease;
}
.st-key-price_range button p { font-size: 16px; font-weight: 600; color: var(--ui-text-muted); transition: color 0.25s ease; white-space: nowrap; }
.st-key-price_range button:hover:not([aria-checked="true"]):not([data-testid*="Active"]) p { color: var(--ui-text); }
.st-key-price_range button:active { transform: scale(0.95); }
.st-key-price_range button[data-testid*="Active"] p, .st-key-price_range button[aria-checked="true"] p { color: var(--ui-accent); font-weight: 800; }
.st-key-price_range button:focus-visible { outline: 3px solid rgba(37, 99, 235, 0.4); outline-offset: 1px; }
/* กราฟเส้น: เปิดเผยจากซ้ายไปขวา / โดนัท: กวาดตามเข็มนาฬิกา (ใช้ transform/opacity/mask ลื่น ไม่ดัน layout) */
.st-key-trend_card [data-testid="stPlotlyChart"] { animation: dash-wipe 1s var(--dash-ease) 0.55s backwards; }
.st-key-equipment_card [data-testid="stPlotlyChart"] {
    animation: dash-sweep 1s var(--dash-ease) 0.55s backwards;
    -webkit-mask-image: conic-gradient(#000 var(--reveal-angle), transparent 0); mask-image: conic-gradient(#000 var(--reveal-angle), transparent 0);
}
/* รายการหมวด Equipment ใต้โดนัท: จุดสี | ชื่อหมวด | จำนวน | ยอดรวม ไหลเข้าทีละแถว ชี้แล้วพื้นสว่างขึ้น */
.st-key-equipment_card .card-heading { display: flex; align-items: center; gap: 12px; font-size: 24px; font-weight: 800; letter-spacing: -0.01em; }
.st-key-equipment_card .card-heading::before {
    content: ""; flex: 0 0 auto; width: 5px; height: 26px; border-radius: 3px; background: linear-gradient(180deg, #8B5CF6, #2563EB);
}
.st-key-equipment_card .card-note { font-size: 15px; }
.st-key-equipment_card .card-heading + .card-note { margin-left: 17px; }
/* ส่วนรายการหมวดชิดล่างการ์ด: การ์ดสูงกว่าเนื้อหาเมื่อถูกยืดให้เท่าการ์ดแนวโน้ม ที่ว่างไปอยู่ระหว่างโดนัทกับรายการ */
.st-key-equipment_card > [data-testid="stElementContainer"]:has(.equip-title) { margin-top: auto; }
.equip-title {
    display: flex; align-items: center; gap: 10px; margin: 6px 0 10px; font-size: 13px; font-weight: 700; letter-spacing: 0.08em;
    color: var(--ui-text-muted);
}
.equip-title::after { content: ""; flex: 1 1 auto; height: 1px; background: var(--ui-border); }
.equip-list { display: flex; flex-direction: column; gap: 6px; }
/* การ์ดเล็กต่อหมวด: แถบสีหมวดด้านซ้าย / บน = ชื่อ + ยอดรวม / ล่าง = จำนวน + แถบสัดส่วน + % */
.equip-row {
    position: relative; padding: 9px 14px 9px 18px; border-radius: 10px; background: var(--ui-inner-bg); font-size: 16px;
    transition: transform 0.2s ease, box-shadow 0.2s ease, background-color 0.2s ease; animation: dash-slide-in 0.5s var(--dash-ease) backwards;
}
.equip-row::before { content: ""; position: absolute; left: 0; top: 9px; bottom: 9px; width: 5px; border-radius: 0 4px 4px 0; background: var(--cat); }
.equip-row:hover { background: #FFFFFF; transform: translateY(-2px); box-shadow: 0 8px 18px -10px rgba(15, 23, 42, 0.28); }
.equip-row:nth-child(1) { animation-delay: 0.70s; }
.equip-row:nth-child(2) { animation-delay: 0.78s; }
.equip-row:nth-child(3) { animation-delay: 0.86s; }
.equip-row:nth-child(4) { animation-delay: 0.94s; }
.equip-row:nth-child(n+5) { animation-delay: 1.02s; }
.equip-row-zero { opacity: 0.55; }
.equip-top, .equip-sub { display: flex; align-items: center; gap: 12px; }
.equip-name { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 17px; font-weight: 700; color: var(--ui-text); }
.equip-amount { flex: 0 0 auto; white-space: nowrap; font-size: 18px; font-weight: 800; color: var(--ui-text); font-variant-numeric: tabular-nums; }
.equip-sub { margin-top: 4px; font-size: 15px; }
.equip-qty { flex: 0 0 auto; white-space: nowrap; min-width: 74px; color: #475569; font-variant-numeric: tabular-nums; }
.equip-bar { flex: 1 1 auto; height: 6px; border-radius: 6px; background: #E2E8F0; overflow: hidden; }
.equip-bar i {
    display: block; height: 100%; width: calc(var(--share) * 100%); border-radius: 6px; background: var(--cat);
    transform-origin: left center; animation: dash-grow-x 0.8s var(--dash-ease) 0.9s backwards;
}
.equip-pct { flex: 0 0 auto; min-width: 46px; text-align: right; font-weight: 700; color: var(--ui-text); font-variant-numeric: tabular-nums; }
/* การ์ด Equipment แคบ (จอ ~1280px): แถบสัดส่วนหดลง ยอดรวมลงบรรทัดล่างของชื่อหมวด ข้อความไม่ถูกตัด */
.st-key-equipment_card { container-type: inline-size; }
@container (max-width: 300px) {
    .equip-top { flex-wrap: wrap; row-gap: 0; }
    .equip-name { flex: 1 0 100%; }
    .equip-amount { font-size: 17px; }
    .equip-qty { min-width: 0; font-size: 14px; }
}
/* การ์ด Vendor: ขีดไล่สีบางด้านบน + หัวการ์ดแบบเดียวกับ Equipment + ตารางจัดอันดับ (เหรียญ | ชื่อ | แถบสัดส่วน+% | จำนวน | ยอดรวม) */
.st-key-vendor_table_card { position: relative; overflow: hidden; container-type: inline-size; }
.st-key-vendor_table_card::before {
    content: ""; position: absolute; left: 0; top: 0; right: 0; height: 3px; background: linear-gradient(90deg, #2563EB, #8B5CF6);
    transform-origin: left; animation: dash-grow-x 0.8s var(--dash-ease) calc(var(--enter-delay) + 150ms) backwards;
}
.st-key-vendor_table_card .card-heading { display: flex; align-items: center; gap: 12px; font-size: 24px; font-weight: 800; letter-spacing: -0.01em; }
.st-key-vendor_table_card .card-heading::before {
    content: ""; flex: 0 0 auto; width: 5px; height: 26px; border-radius: 3px; background: linear-gradient(180deg, #2563EB, #8B5CF6);
}
.st-key-vendor_table_card .card-note { font-size: 15px; }
.st-key-vendor_table_card .card-heading + .card-note { margin-left: 17px; }
.vendor-list { display: flex; flex-direction: column; gap: 8px; margin-top: 14px; }
.vendor-head, .vendor-row {
    display: grid; grid-template-columns: 44px minmax(0, 1.2fr) minmax(0, 1.5fr) 110px 160px; align-items: center; column-gap: 18px;
}
.vendor-head { padding: 0 18px; font-size: 13px; font-weight: 700; letter-spacing: 0.08em; color: var(--ui-text-muted); }
.vendor-head span:nth-child(n+4) { text-align: right; }
.vendor-row {
    position: relative; padding: 12px 18px; border-radius: 12px; background: var(--ui-inner-bg); font-size: 16px;
    transition: transform 0.2s ease, box-shadow 0.2s ease, background-color 0.2s ease;
    animation: dash-slide-in 0.5s var(--dash-ease) calc(0.65s + var(--i) * 0.06s) backwards;
}
.vendor-row:hover { background: #FFFFFF; transform: translateY(-2px); box-shadow: 0 8px 18px -10px rgba(15, 23, 42, 0.28); }
.vendor-rank {
    display: grid; place-items: center; width: 34px; height: 34px; border-radius: 50%; font-size: 15px; font-weight: 800;
    color: #475569; background: #E2E8F0; font-variant-numeric: tabular-nums;
}
/* ลูกคนแรกของ .vendor-list คือแถวหัวคอลัมน์ จึงนับอันดับ 1-3 เป็นลูกคนที่ 2-4 */
.vendor-row:nth-child(2) .vendor-rank { color: #7A5200; background: linear-gradient(135deg, #FDE68A, #F5B73B); }
.vendor-row:nth-child(3) .vendor-rank { color: #3F4B5B; background: linear-gradient(135deg, #E5E9EF, #B8C1CD); }
.vendor-row:nth-child(4) .vendor-rank { color: #6B3410; background: linear-gradient(135deg, #F6C9A0, #D98E55); }
.vendor-name { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 18px; font-weight: 700; color: var(--ui-text); }
.vendor-share { display: flex; align-items: center; gap: 12px; min-width: 0; }
.vendor-bar { flex: 1 1 auto; height: 8px; border-radius: 8px; background: #E2E8F0; overflow: hidden; }
.vendor-bar i {
    display: block; height: 100%; width: calc(var(--share) * 100%); border-radius: 8px;
    background: linear-gradient(90deg, #60A5FA, #2563EB); opacity: calc(0.55 + var(--share) * 0.45);
    transform-origin: left center; animation: dash-grow-x 0.8s var(--dash-ease) calc(0.85s + var(--i) * 0.06s) backwards;
}
.vendor-pct { flex: 0 0 auto; min-width: 52px; text-align: right; font-size: 16px; font-weight: 700; color: #475569; font-variant-numeric: tabular-nums; }
.vendor-qty { justify-self: end; box-sizing: border-box; width: 104px; text-align: center; padding: 3px 12px; border-radius: 999px; font-size: 15px; font-weight: 600; color: #475569; background: #FFFFFF; border: 1px solid var(--ui-border); white-space: nowrap; font-variant-numeric: tabular-nums; }
.vendor-amount { text-align: right; white-space: nowrap; font-size: 20px; font-weight: 800; color: var(--ui-text); font-variant-numeric: tabular-nums; }
/* การ์ด Vendor แคบ (ดูจากความกว้างการ์ดจริง): ซ่อนหัวคอลัมน์ แถวเป็น 2 บรรทัด (เหรียญ+ชื่อ+ยอดรวม / แถบ+จำนวน) */
@container (max-width: 720px) {
    .vendor-head { display: none; }
    .vendor-row { grid-template-columns: 34px minmax(0, 1fr) auto; grid-template-areas: "rank name amount" ". share qty"; row-gap: 8px; column-gap: 12px; }
    .vendor-rank { grid-area: rank; }
    .vendor-name { grid-area: name; }
    .vendor-amount { grid-area: amount; font-size: 18px; }
    .vendor-share { grid-area: share; }
    .vendor-qty { grid-area: qty; width: 104px; }
}
/* การ์ด Vendor แคบมาก (มือถือ): ชิปจำนวนกว้างตามเนื้อหา ชื่อบริษัทจะได้มีที่มากขึ้น */
@container (max-width: 420px) {
    .vendor-row { padding: 12px 14px; column-gap: 10px; }
    .vendor-qty { width: auto; padding: 2px 10px; font-size: 14px; }
    .vendor-name { font-size: 17px; }
    .vendor-amount { font-size: 17px; }
}
/* ปุ่ม Export: ปุ่มสี accent เรียบ มุม 8px ชี้แล้วยกขึ้น/เข้มขึ้น ไอคอนเด้ง กดแล้วยุบ */
.st-key-dashboard_export { animation: dash-fade-up var(--dash-in) var(--dash-ease) 0.1s backwards; }
.st-key-dashboard_export [data-testid="stDownloadButton"] { display: flex; justify-content: flex-end; }
.st-key-dashboard_export button {
    background: var(--ui-accent); color: #ffffff; border: none; border-radius: 8px; padding: 0.55rem 1.3rem; font-weight: 700;
    box-shadow: 0 4px 12px -4px rgba(37, 99, 235, 0.5);
    transition: transform 0.2s ease, box-shadow 0.2s ease, background-color 0.2s ease;
}
.st-key-dashboard_export button p, .st-key-dashboard_export button span { color: #ffffff; }
.st-key-dashboard_export button:hover:not(:disabled) {
    background: var(--ui-accent-hover); transform: translateY(-2px); box-shadow: 0 10px 20px -6px rgba(37, 99, 235, 0.6); color: #ffffff; border: none;
}
.st-key-dashboard_export button:hover:not(:disabled) [data-testid="stIconMaterial"] { animation: dash-bounce 0.7s ease-in-out infinite; }
.st-key-dashboard_export button:active:not(:disabled) { transform: translateY(0) scale(0.97); box-shadow: 0 3px 8px -4px rgba(37, 99, 235, 0.6); }
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
    /* การ์ดแนวโน้ม: แถวหัว (ชื่อ | ปุ่มช่วงเวลา) และแถวยอดรวม (ยอดรวม | Detail Graph) ฝั่งขวากว้างตามเนื้อหา ฝั่งซ้ายกินที่เหลือ */
    .st-key-trend_card [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .st-key-price_range),
    .st-key-trend_card [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .st-key-price_detail_graph) { flex-wrap: nowrap; gap: 0.75rem; }
    .st-key-trend_card [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .st-key-price_range) > [data-testid="stColumn"]:first-child,
    .st-key-trend_card [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .st-key-price_detail_graph) > [data-testid="stColumn"]:first-child {
        flex: 1 1 0; width: auto; min-width: 0;
    }
    .st-key-trend_card [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .st-key-price_range) > [data-testid="stColumn"]:last-child,
    .st-key-trend_card [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .st-key-price_detail_graph) > [data-testid="stColumn"]:last-child {
        flex: 0 0 auto; width: auto; min-width: max-content;
    }
}
/* การ์ดแนวโน้มแคบกว่า 680px (ดูจากความกว้างการ์ดจริง ไม่ใช่หน้าจอ เพราะ sidebar กินที่): ปุ่มช่วงเวลาลงไปแถวใต้ชื่อ เต็มความกว้าง
   ชื่อการ์ดจะได้ไม่ถูกบีบจนตกบรรทัด */
.st-key-trend_card { container: trend-card / inline-size; }
@container trend-card (max-width: 680px) {
    .st-key-trend_card [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .st-key-price_range) { flex-wrap: wrap; row-gap: 10px; }
    .st-key-trend_card [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] .st-key-price_range) > [data-testid="stColumn"]:is(:first-child, :last-child) {
        flex: 1 1 100%; width: 100%; min-width: 0;
    }
    .st-key-price_range, .st-key-price_range [data-testid="stButtonGroup"] { width: 100%; margin-left: 0; }
    .st-key-price_range { margin-top: 6px; }
}
/* มือถือ: แถบสรุปเรียงทีละช่อง ปุ่มช่วงเวลาเต็มแถวและชิดซ้าย */
@media (max-width: 479px) {
    .trend-stats { grid-template-columns: 1fr; }
    .st-key-price_range [data-testid="stButtonGroup"] { margin-left: 0; width: 100%; }
    .st-key-price_range button { padding: 4px 4px; }
    .st-key-price_range button p { font-size: 15px; }
    .trend-stat-value { font-size: 30px; }
    .trend-stat-icon { display: inline-grid; }  /* ช่องเรียงทีละแถวกว้างพอ: คืนไอคอนและให้หน่วยอยู่บรรทัดเดียวกับตัวเลข */
    .trend-stat-value small { display: inline; margin-left: 6px; }
    .trend-delta em { display: none; }
}
/* มือถือ (<640px): ปุ่ม Export เต็มความกว้างใต้ชื่อ */
@media (max-width: 639px) {
    .st-key-dashboard_export, .st-key-dashboard_export [data-testid="stDownloadButton"], .st-key-dashboard_export button { width: 100%; justify-content: center; }
    .st-key-dashboard_export { margin-top: 10px; }
}
/* มือถือเล็ก (<480px): KPI ทีละช่อง การ์ดกระชับ ไอคอนไปอยู่หน้าป้าย */
@media (max-width: 479px) {
    .kpi-head { justify-content: flex-start; flex-direction: row-reverse; }
    .kpi-head .kpi-label { flex: 1 1 auto; }
    .kpi-icon { width: 34px; height: 34px; }
}
/* อุปกรณ์สัมผัส: ไม่มี hover จึงไม่ยกการ์ด/ปุ่มค้าง */
@media (hover: none) {
    [class*="st-key-kpi_"][class*="_card"]:hover, .st-key-dashboard_export button:hover:not(:disabled) { transform: none; }
}
/* ผู้ใช้ที่ตั้งค่าลดการเคลื่อนไหว: ปิด animation / transition ทั้งหมดของหน้านี้ (กราฟแสดงครบทันที) */
@media (prefers-reduced-motion: reduce) {
    .section-head, .section-title::after, [class*="st-key-"][class*="_card"], [class*="st-key-kpi_"][class*="_card"]::before,
    .kpi-value, .kpi-icon, .kpi-dot, .equip-row, .equip-bar i, .vendor-row, .vendor-bar i, .st-key-vendor_table_card::before, .st-key-trend_card [data-testid="stPlotlyChart"],
    .trend-total, .trend-delta, .trend-stat, .trend-empty, .st-key-price_range button, .st-key-price_range [role="radiogroup"]::before,
    .st-key-equipment_card [data-testid="stPlotlyChart"], .st-key-dashboard_export, .st-key-dashboard_export button,
    .st-key-dashboard_export [data-testid="stIconMaterial"] {
        animation: none !important; transition: none !important;
    }
    .st-key-equipment_card [data-testid="stPlotlyChart"] { -webkit-mask-image: none; mask-image: none; }
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


def resolve_full_price_window(period_label: str, end_date: date) -> tuple[date, date]:
    """หาช่วงวันที่เต็มของปุ่มช่วงเวลา ก่อนตัดตามขอบเขต Date Filter

    Args:
        period_label: ข้อความที่ผู้ใช้เลือก (key ของ PRICE_PERIOD_OPTIONS)
        end_date: วันที่สิ้นสุดจาก Date Filter (ใช้หาปีของ Quarter / 1Y และวันสุดท้ายของ 1M)

    Returns:
        (วันที่เริ่ม, วันที่สิ้นสุด) ของช่วงเต็ม เช่น Q2 ของปี 2026 = 2026-04-01 ถึง 2026-06-30
    """
    period_kind, period_value = PRICE_PERIOD_OPTIONS.get(period_label, ("days", 30))
    if period_kind == "quarter":
        first_month = (period_value - 1) * 3 + 1
        quarter_start = date(end_date.year, first_month, 1)
        next_quarter_start = date(end_date.year + (first_month == 10), (first_month + 3 - 1) % 12 + 1, 1)
        return quarter_start, next_quarter_start - timedelta(days=1)
    if period_kind == "year":
        return date(end_date.year, 1, 1), date(end_date.year, 12, 31)
    # นับรวมวันสิ้นสุดด้วย จึงลบ (จำนวนวัน - 1)
    return end_date - timedelta(days=period_value - 1), end_date


def resolve_price_window(period_label: str, start_date: date, end_date: date) -> tuple[date, date]:
    """หาช่วงวันที่ของการ์ด Price จากปุ่มช่วงเวลา แล้วตัดให้อยู่ในขอบเขต Date Filter

    Args:
        period_label: ข้อความที่ผู้ใช้เลือก (key ของ PRICE_PERIOD_OPTIONS)
        start_date: วันที่เริ่มต้นจาก Date Filter
        end_date: วันที่สิ้นสุดจาก Date Filter

    Returns:
        (วันที่เริ่ม, วันที่สิ้นสุด) ซึ่งอยู่ในขอบเขตของ Date Filter เสมอ
        ถ้าช่วงที่เลือกอยู่นอก Date Filter ทั้งหมด (เช่น Q1 แต่ Date Filter เริ่มเดือนมิถุนายน) จะได้วันเริ่มหลังวันสิ้นสุด
    """
    full_start, full_end = resolve_full_price_window(period_label, end_date)
    return max(start_date, full_start), min(end_date, full_end)


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


def build_top_vendor_table(transaction_table: pd.DataFrame) -> pd.DataFrame:
    """สรุปผู้ขายที่มียอดซื้อสูงสุด

    Args:
        transaction_table: ตารางจาก load_transaction_table

    Returns:
        DataFrame คอลัมน์ vendor / order_count / total_price เรียงจากยอดสูงสุด จำกัด TOP_VENDOR_LIMIT อันดับ
    """
    return (
        transaction_table.groupby("vendor")
        .agg(order_count=("id", "count"), total_price=("total_price", "sum"))
        .sort_values("total_price", ascending=False)
        .head(TOP_VENDOR_LIMIT)
        .reset_index()
    )


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
        '<div class="section-head"><div class="section-title">ภาพรวม</div>'
        f'<span class="section-sub">{CALENDAR_ICON}{start_date:%d/%m/%Y} – {end_date:%d/%m/%Y}</span></div>',
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


def format_kpi_value(value: str) -> str:
    """แปลงตัวเลขเป็น HTML โดยแยกทศนิยมให้เล็กและเบากว่าส่วนจำนวนเต็ม (เช่น 332,830 + .00)

    Args:
        value: ตัวเลขที่จัดรูปแล้ว เช่น "332,830.00" หรือ "14" (ไม่มีทศนิยมก็แสดงตามเดิม)

    Returns:
        สตริง HTML ที่ escape แล้ว พร้อมใส่ใน .kpi-value
    """
    whole_part, dot, decimal_part = value.partition(".")
    if not dot:
        return html.escape(value)
    return f'{html.escape(whole_part)}<span class="kpi-decimal">.{html.escape(decimal_part)}</span>'


def render_kpi_tile(
    card_key: str,
    label: str,
    value: str,
    sub_parts: tuple[str, str, str],
    show_alert: bool = False,
) -> None:
    """วาดการ์ดตัวเลขสรุป 1 ช่อง: ป้าย / ตัวเลขใหญ่ / ข้อความรอง (เน้นตัวเลข)

    Args:
        card_key: key ของการ์ด (ต้องลงท้ายด้วย _card และตรงกับสีแถบด้านซ้ายใน PAGE_CSS_RULES)
        label: ป้ายหัวช่อง
        value: ตัวเลขที่แสดง
        sub_parts: ข้อความรองใต้ตัวเลขแบ่งเป็น (ข้อความหน้า, ตัวเลขที่เน้นสี accent, ข้อความหลัง)
        show_alert: True = แสดงจุดกะพริบหน้าป้าย (ใช้กับช่องที่มีรายการค้างต้องติดตาม)
    """
    alert_dot = '<span class="kpi-dot"></span>' if show_alert else ""
    sub_prefix, sub_highlight, sub_suffix = sub_parts
    with st.container(key=card_key):
        st.markdown(
            f'<div class="kpi-head"><div class="kpi-label">{alert_dot}{html.escape(label)}</div>'
            f'<div class="kpi-icon">{KPI_ICONS.get(card_key, "")}</div></div>'
            f'<div class="kpi-value">{format_kpi_value(value)}</div>'
            f'<div class="kpi-sub">{html.escape(sub_prefix)}<b class="kpi-em">{html.escape(sub_highlight)}</b>{html.escape(sub_suffix)}</div>',
            unsafe_allow_html=True,
        )


def render_kpi_row(transaction_table: pd.DataFrame) -> None:
    """วาดแถวตัวเลขสรุป 3 ช่อง: ยอดรวม / จำนวนรายการ / รอใบกำกับภาษี

    Args:
        transaction_table: ตารางจาก load_transaction_table (ตาม Date Filter)
    """
    total_price = float(transaction_table["total_price"].sum()) if not transaction_table.empty else 0.0
    if transaction_table.empty:
        pending_table = transaction_table
        vendor_count = 0
    else:
        pending_table = transaction_table[transaction_table["invoice_status"] == STATUS_PENDING]
        vendor_count = int(transaction_table["vendor"].nunique())
    pending_price = float(pending_table["total_price"].sum()) if not pending_table.empty else 0.0

    total_column, count_column, pending_column = st.columns(3, gap="medium")
    with total_column:
        render_kpi_tile(
            "kpi_total_card",
            "ยอดรวมทั้งหมด (บาท)",
            f"{total_price:,.2f}",
            ("จาก ", f"{len(transaction_table):,}", " รายการ"),
        )
    with count_column:
        render_kpi_tile(
            "kpi_count_card", "จำนวนรายการ", f"{len(transaction_table):,}", ("ผู้ขาย ", f"{vendor_count:,}", " ราย")
        )
    with pending_column:
        render_kpi_tile(
            "kpi_pending_card",
            "รอใบกำกับภาษี",
            f"{len(pending_table):,}",
            ("ยอด ", f"{pending_price:,.2f}", " บาท"),
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
        tickformat="%d/%m",  # รูปแบบวันที่บนแกน X (วัน/เดือน สั้นพอให้ไม่ซ้อนกัน ปีดูได้จากช่วงวันที่ใต้ชื่อการ์ด)
        hoverformat="%d/%m/%Y",  # หัว Tooltip แสดงวันที่เต็ม
        nticks=7,  # ขีดแกน X ไม่เกินราว 7 ขีด
    )
    # ช่วงยาวรวมเป็นรายเดือน: จุดคือต้นเดือน แสดงเป็น เดือน/ปี
    if (
        trend_table["period"].nunique() > 1
        and trend_table["period"].drop_duplicates().sort_values().diff().dt.days.min() > 20
    ):
        figure.update_xaxes(tickformat="%m/%Y")
    # ช่วงสั้น (<= 14 วัน) ให้แกน X ขีดทีละ 1 วันพอดี ไม่เช่นนั้น Plotly จะขีดทุกครึ่งวันแล้วได้วันที่ซ้ำกัน
    if (trend_table["period"].max() - trend_table["period"].min()).days <= 14:
        figure.update_xaxes(dtick=86400000)  # 86,400,000 มิลลิวินาที = 1 วัน
    figure.update_yaxes(
        title_text="ยอดรวม (บาท)",  # หัวข้อแกน Y
        tickformat="~s",  # ตัวเลขแกน Y แบบย่อ (10k, 50k, 1M) อ่านง่ายกว่าเลขยาว ๆ
        nticks=5,  # ขีดแกน Y ไม่เกินราว 5 ขีด ไม่แน่น
        rangemode="tozero",  # บังคับให้แกน Y เริ่มที่ 0 กันกราฟดูผันผวนเกินจริง
    )
    is_single_line = TOTAL_LINE_LABEL in trend_table["category"].unique()
    # เส้นเรียบโค้ง หนา 3px จุดเล็ก; โหมดเส้นเดียวเติมสีอ่อนใต้เส้นให้กราฟดูมีน้ำหนักแบบ modern
    # จุดเยอะเกิน TREND_MARKER_MAX_POINTS ซ่อนจุดไว้ ให้เห็นแต่เส้นเรียบ ๆ
    point_count = int(trend_table.groupby("category").size().max())
    figure.update_traces(
        line={
            "width": 4,
            "shape": "spline" if TOTAL_LINE_LABEL in trend_table["category"].unique() else "linear",
            "smoothing": 0.6,
        },
        marker={
            "size": 9 if point_count <= TREND_MARKER_MAX_POINTS else 0,
            "line": {"width": 2, "color": "#FFFFFF"},
        },  # จุดมีขอบขาวให้ลอยเด่นจากเส้น
        cliponaxis=False,
        hovertemplate="<b>%{y:,.0f}</b> บาท<extra>%{fullData.name}</extra>",
    )
    if is_single_line:
        # โหมดเส้นเดียว: เติมไล่สีจางลงล่าง + วงกลมที่จุดสูงสุดพร้อมป้ายค่า (ขยายแกน Y เผื่อที่ให้ป้าย)
        figure.update_traces(
            fill="tozeroy",
            fillgradient={
                "type": "vertical",
                "colorscale": [[0, "rgba(37, 99, 235, 0)"], [1, "rgba(37, 99, 235, 0.28)"]],
            },
        )
        peak_row = trend_table.loc[trend_table["total_price"].idxmax()]
        figure.add_trace(
            go.Scatter(
                x=[peak_row["period"]],
                y=[peak_row["total_price"]],
                mode="markers+text",
                text=[f"{peak_row['total_price']:,.0f}"],
                textposition="top center",
                textfont={"size": 16, "color": TOTAL_LINE_COLOR, "family": FONT_FAMILY},
                marker={"size": 15, "color": "#FFFFFF", "line": {"width": 4, "color": TOTAL_LINE_COLOR}},
                cliponaxis=False,
                hoverinfo="skip",
                showlegend=False,
            )
        )
        figure.update_yaxes(range=[0, float(trend_table["total_price"].max()) * 1.2])
    figure.update_xaxes(
        showgrid=False,
        linecolor=CHART_GRID_COLOR,
        title_text="",
        tickfont={"size": 14, "color": "#475569"},
        showspikes=True,
        spikemode="across",
        spikethickness=1,
        spikecolor="#94A3B8",
        spikedash="dot",
        spikesnap="cursor",
    )
    figure.update_yaxes(
        gridcolor=CHART_GRID_COLOR, zeroline=False, title_text="", tickfont={"size": 14, "color": "#475569"}
    )
    figure.update_layout(
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "left",
            "x": 0,
            "title_text": "",
            "font": {"size": 15},
        },
        hoverlabel={
            "bgcolor": "#FFFFFF",
            "bordercolor": "#E2E8F0",
            "font": {"family": FONT_FAMILY, "size": 16, "color": PALETTE["text"]},
        },
        margin={"l": 4, "r": 16, "t": 34, "b": 0},  # ระยะขอบกราฟ (ซ้าย ขวา บน ล่าง) เผื่อขวาให้จุดสุดท้ายไม่ถูกตัด
        font={"family": FONT_FAMILY, "color": PALETTE["text"]},  # ฟอนต์และสีตัวอักษรในกราฟ ให้ตรงกับธีมกลาง
        hovermode="x unified",  # เอาเมาส์ชี้แล้วแสดงทุกหมวดของวันนั้นพร้อมกัน
        showlegend=len(color_map) > 1 and not is_single_line,  # เส้นเดียวไม่ต้องมี Legend
        paper_bgcolor=TRANSPARENT,  # พื้นโปร่งใส กลืนกับการ์ด
        plot_bgcolor=TRANSPARENT,
        transition={"duration": CHART_TRANSITION_MS, "easing": "cubic-in-out"},  # ข้อมูลเปลี่ยนแล้วเส้นเลื่อนนุ่ม
    )
    return figure


def render_empty_state(message: str = EMPTY_STATE_MESSAGE) -> None:
    """แสดงกล่อง 'ยังไม่มีข้อมูล' ในการ์ด (ใช้เมื่อกราฟหรือตารางไม่มีข้อมูลให้วาด)

    Args:
        message: ข้อความที่แสดงกลางกล่อง
    """
    st.markdown(f'<div class="empty-state">{message}</div>', unsafe_allow_html=True)


@dataclass(frozen=True)
class TrendSummary:
    """ตัวเลขสรุปของการ์ดแนวโน้มยอดซื้อในช่วงเวลาที่เลือก"""

    total: float  # ยอดรวมในช่วง (บาท)
    transaction_count: int  # จำนวนรายการในช่วง
    average_per_day: float  # ยอดเฉลี่ยต่อวัน (หารด้วยจำนวนวันของช่วงทั้งหมด ไม่ใช่เฉพาะวันที่มีข้อมูล)
    peak_date: Optional[date]  # วันที่ยอดสูงสุด (None = ไม่มีข้อมูล)
    peak_total: float  # ยอดของวันที่สูงสุด
    change_percent: Optional[float]  # % เปลี่ยนจากช่วงก่อนหน้าที่ยาวเท่ากัน (None = เทียบไม่ได้)


def get_trend_summary(
    transaction_table: pd.DataFrame, window_start: date, window_end: date, data_start: Optional[date] = None
) -> TrendSummary:
    """สรุปยอดรวม / วันที่สูงสุด / เฉลี่ยต่อวัน / % เทียบช่วงก่อนหน้า จากตารางที่โหลดอยู่แล้ว (ไม่ query เพิ่ม)

    ช่วงก่อนหน้า = ช่วงที่ยาวเท่ากันและต่อท้ายก่อนวันเริ่ม ถ้า Date Filter ไม่ครอบคลุมช่วงนั้น
    หรือยอดช่วงก่อนหน้าเป็น 0 จะเทียบไม่ได้ (change_percent = None) เพื่อไม่แสดงตัวเลขที่เข้าใจผิด

    Args:
        transaction_table: ตารางจาก load_transaction_table (ตาม Date Filter)
        window_start: วันแรกของช่วงที่เลือก
        window_end: วันสุดท้ายของช่วงที่เลือก
        data_start: วันแรกที่ข้อมูลครอบคลุม (Date Filter) ถ้าช่วงก่อนหน้าเริ่มก่อนวันนี้ แปลว่าข้อมูลไม่ครบ
            จะไม่เทียบ % (ไม่งั้นได้ตัวเลขสูงเกินจริง) None = ไม่เช็ก

    Returns:
        TrendSummary (ตารางว่าง = ทุกค่าเป็น 0 / None)
    """
    window_days = (window_end - window_start).days + 1
    if transaction_table.empty:
        return TrendSummary(0.0, 0, 0.0, None, 0.0, None)

    def rows_between(first_day: date, last_day: date) -> pd.DataFrame:
        """แถวที่วันที่อยู่ระหว่าง first_day ถึง last_day (รวมทั้งสองวัน)"""
        return transaction_table[
            (transaction_table["date"] >= pd.Timestamp(first_day))
            & (transaction_table["date"] <= pd.Timestamp(last_day))
        ]

    window_table = rows_between(window_start, window_end)
    total = float(window_table["total_price"].sum())
    peak_date: Optional[date] = None
    peak_total = 0.0
    if not window_table.empty:
        daily_total = window_table.groupby(window_table["date"].dt.normalize())["total_price"].sum()
        peak_date, peak_total = daily_total.idxmax().date(), float(daily_total.max())

    previous_end = window_start - timedelta(days=1)
    previous_table = rows_between(previous_end - timedelta(days=window_days - 1), previous_end)
    previous_total = float(previous_table["total_price"].sum())
    previous_start = previous_end - timedelta(days=window_days - 1)
    previous_covered = data_start is None or previous_start >= data_start  # ช่วงก่อนหน้าต้องอยู่ใน Date Filter ทั้งช่วง
    change_percent = (
        (total - previous_total) / previous_total * 100 if previous_total > 0 and previous_covered else None
    )
    return TrendSummary(total, len(window_table), total / window_days, peak_date, peak_total, change_percent)


def format_trend_delta(change_percent: Optional[float]) -> str:
    """สร้าง HTML ชิป % เปลี่ยนจากช่วงก่อนหน้า (ยอดซื้อขึ้น/ลงไม่ใช่ดี/ร้าย จึงใช้สีกลาง ไม่ใช่เขียว/แดง)

    Args:
        change_percent: % เปลี่ยน (None = เทียบไม่ได้ จึงไม่แสดงชิป)

    Returns:
        HTML ของชิป หรือสตริงว่างถ้าเทียบไม่ได้
    """
    if change_percent is None:
        return ""
    direction, arrow = (
        ("up", "▲") if change_percent > 0.05 else ("down", "▼") if change_percent < -0.05 else ("flat", "■")
    )
    return (
        f'<span class="trend-delta trend-delta-{direction}"><span class="trend-delta-arrow">{arrow}</span>{abs(change_percent):,.1f}%'
        f"<em>จากช่วงก่อน</em></span>"
    )


def render_trend_summary_strip(summary: TrendSummary) -> None:
    """แถบสรุป 3 ช่องใต้กราฟแนวโน้ม: วันที่ยอดสูงสุด / เฉลี่ยต่อวัน / จำนวนรายการ

    Args:
        summary: ตัวเลขจาก get_trend_summary (ต้องมีข้อมูลอย่างน้อย 1 รายการ)
    """
    peak_note = f"วันที่ {summary.peak_date:%d/%m/%Y}" if summary.peak_date else "–"
    # (คลาสสีประจำช่อง, ไอคอน, ป้าย, ตัวเลขหลัก, หน่วย, บรรทัดล่าง)
    stat_cells = [
        ("peak", "ยอดสูงสุดต่อวัน", f"{summary.peak_total:,.0f}", "บาท", peak_note),
        ("average", "เฉลี่ยต่อวัน", f"{summary.average_per_day:,.0f}", "บาท", "เฉลี่ยทุกวันในช่วงนี้"),
        ("count", "จำนวนรายการ", f"{summary.transaction_count:,}", "รายการ", "ที่บันทึกในช่วงนี้"),
    ]
    cells_html = "".join(
        f'<div class="trend-stat trend-stat-{kind}"><div class="trend-stat-head">'
        f'<span class="trend-stat-icon">{TREND_STAT_ICONS[kind]}</span><span class="trend-stat-label">{label}</span></div>'
        f'<div class="trend-stat-value">{value}<small>{unit}</small></div><div class="trend-stat-note">{note}</div></div>'
        for kind, label, value, unit, note in stat_cells
    )
    st.markdown(f'<div class="trend-stats">{cells_html}</div>', unsafe_allow_html=True)


def render_trend_empty(message: str) -> None:
    """กล่อง 'ยังไม่มีข้อมูล' ของการ์ดแนวโน้ม: ไอคอนกราฟ + ข้อความ สูงเท่าพื้นที่กราฟ+แถบสรุป การ์ดไม่ยุบ

    Args:
        message: ข้อความอธิบายและวิธีแก้ (เช่น เลือกช่วงที่ยาวขึ้น)
    """
    st.markdown(
        f'<div class="trend-empty">{TREND_EMPTY_ICON}<div class="trend-empty-title">ยังไม่มีข้อมูลในช่วงนี้</div>'
        f'<div class="trend-empty-text">{message}</div></div>',
        unsafe_allow_html=True,
    )


def keep_period_selected() -> None:
    """เมื่อกดปุ่มช่วงเวลา: ปรับ Date Filter ตามช่วงที่เลือก (Equipment / Vendor ใช้ Date Filter เดียวกันจึงเปลี่ยนตาม)

    - กดช่วงที่เลือกอยู่ซ้ำ segmented_control จะยกเลิกการเลือก: คืนช่วงล่าสุดไว้ให้มีช่วงที่เลือกเสมอ และไม่แตะวันที่
    - ทำใน on_change callback เพราะ Streamlit แก้ค่า widget ที่วาดไปแล้วในรอบเดียวกันไม่ได้ แต่แก้ก่อน rerun ได้
    """
    period_label = st.session_state.get("price_range")
    if period_label is None:
        st.session_state["price_range"] = st.session_state.get("price_range_last", next(iter(PRICE_PERIOD_OPTIONS)))
        return
    today = date.today()
    current_end = st.session_state.get(FILTER_END_KEY, today)
    # 1M นับย้อนจากวันนี้ (กันไปติดวันสิ้นสุดในอนาคต) ส่วนไตรมาส/ปีใช้ปีของวันสิ้นสุดปัจจุบัน
    anchor = today if PRICE_PERIOD_OPTIONS[period_label][0] == "days" else current_end
    st.session_state[FILTER_START_KEY], st.session_state[FILTER_END_KEY] = resolve_full_price_window(
        period_label, anchor
    )


def render_trend_card(transaction_table: pd.DataFrame, start_date: date, end_date: date) -> None:
    """วาดการ์ดแนวโน้มยอดซื้อ: หัวการ์ด + ปุ่มช่วงเวลา + ยอดรวม/% เทียบช่วงก่อน + Detail Graph + กราฟ + แถบสรุป

    - ปุ่มช่วงเวลา (1M / Q1-Q4 / 1Y): คลิกแล้วตั้ง Date Filter เป็นช่วงนั้น (ดู keep_period_selected) กล่อง Equipment / Vendor จึงตามด้วย
      ถ้าผู้ใช้แก้วันที่เองภายหลัง ช่วงของกราฟจะถูกตัดไม่เกินขอบเขต Date Filter
    - สวิตช์ Detail Graph: ปิด = เส้นเดียวรวมทุกหมวด, เปิด = แยกเส้นตามหมวดหมู่ (Multi Line)

    Args:
        transaction_table: ตารางจาก load_transaction_table (ตาม Date Filter)
        start_date: วันที่เริ่มต้นจาก Date Filter
        end_date: วันที่สิ้นสุดจาก Date Filter
    """
    with st.container(key="trend_card"):
        title_column, range_column = st.columns([1, 1], vertical_alignment="center")
        title_column.markdown(
            '<div class="card-heading">แนวโน้มยอดซื้อ</div><div class="card-note">ยอดรวมตามช่วงเวลา</div>',
            unsafe_allow_html=True,
        )
        period_options = list(PRICE_PERIOD_OPTIONS.keys())
        # ค่าเก่าที่ค้างใน session (เช่น "30d" จากเวอร์ชันก่อน) ไม่อยู่ในตัวเลือกแล้ว ต้องล้างทิ้ง ไม่งั้น widget จะ error
        for stale_key in ("price_range", "price_range_last"):
            if st.session_state.get(stale_key) not in period_options + [None]:
                st.session_state.pop(stale_key, None)
        st.session_state.setdefault(
            "price_range", period_options[0]
        )  # ค่าเริ่มต้นตั้งทาง session_state (ไม่ใช้ default= ซ้ำซ้อน)
        period_label = range_column.segmented_control(
            "ช่วงเวลา",
            period_options,
            label_visibility="collapsed",
            key="price_range",
            on_change=keep_period_selected,
        ) or st.session_state.get("price_range_last", period_options[0])
        st.session_state["price_range_last"] = period_label

        window_start, window_end = resolve_price_window(period_label, start_date, end_date)
        full_start, full_end = resolve_full_price_window(period_label, end_date)
        is_outside_filter = window_start > window_end  # เช่น เลือก Q1 แต่ Date Filter เริ่มเดือนมิถุนายน
        summary = (
            None
            if is_outside_filter
            else get_trend_summary(transaction_table, window_start, window_end, data_start=start_date)
        )

        hero_column, detail_column = st.columns([3, 1], vertical_alignment="center")
        if is_outside_filter:
            hero_range, clamped_note = f"{full_start:%d/%m/%Y} – {full_end:%d/%m/%Y}", ""
        else:
            hero_range = f"{window_start:%d/%m/%Y} – {window_end:%d/%m/%Y}"
            clamped_note = (  # ช่วงที่เลือกกว้างกว่า Date Filter: บอกผู้ใช้ว่าถูกตัดตามขอบเขต ไม่ให้งงว่าทำไม 1Y ได้แค่ไม่กี่เดือน
                ' · <span class="trend-clamp">จำกัดตาม Date Filter</span>'
                if (window_start, window_end) != (full_start, full_end)
                else ""
            )
        has_data = summary is not None and summary.transaction_count > 0
        hero_column.markdown(
            f'<div class="trend-hero"><div class="card-note">ยอดรวมช่วง {hero_range}{clamped_note}</div>'
            f'<div class="trend-hero-row"><span class="trend-total{"" if has_data else " trend-total-empty"}">'
            f"{summary.total if summary else 0:,.2f} <small>บาท</small></span>{format_trend_delta(summary.change_percent if has_data else None)}</div></div>",
            unsafe_allow_html=True,
        )
        show_detail_graph = detail_column.toggle(
            "Detail Graph", key="price_detail_graph", help="เปิด = แยกเส้นตามหมวดหมู่ / ปิด = เส้นเดียวรวมทุกหมวด"
        )

        if is_outside_filter:
            render_trend_empty("ช่วงนี้อยู่นอก Date Filter ลองขยาย Date Filter หรือเลือกช่วงอื่น")
            return
        if not has_data:
            render_trend_empty("ลองเลือกช่วงอื่น หรือขยาย Date Filter")
            return
        try:
            window_table = transaction_table[
                (transaction_table["date"] >= pd.Timestamp(window_start))
                & (transaction_table["date"] <= pd.Timestamp(window_end))
            ]
            trend_table = build_trend_table(window_table, window_start, window_end, show_detail_graph)
            trend_figure = build_trend_figure(trend_table)
            trend_figure.update_layout(height=TREND_CHART_HEIGHT_PX)  # ให้สูงสมดุลกับการ์ด Equipment
            st.plotly_chart(
                trend_figure, width="stretch", config={"displayModeBar": False}
            )  # ซ่อนแถบเครื่องมือไม่ให้ทับ Legend
            render_trend_summary_strip(summary)
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
    colors = [CATEGORY_COLORS.get(name, FALLBACK_CATEGORY_COLOR) for name in shown_table["Equipment"]]
    top_index = int(shown_table["Qty."].reset_index(drop=True).idxmax())
    # ดึงเฉพาะชิ้นที่ใหญ่สุด (ถ้ามีหลายหมวด) ส่วนกรณีหมวดเดียวเต็มวงไม่ต้องดึง
    pulls = [
        EQUIPMENT_TOP_PULL if (index == top_index and len(shown_table) > 1) else 0 for index in range(len(shown_table))
    ]
    figure = go.Figure(
        go.Pie(
            labels=shown_table["Equipment"],
            values=shown_table["Qty."],
            customdata=shown_table["ยอดรวม (บาท)"],
            hole=EQUIPMENT_DONUT_HOLE,
            pull=pulls,
            marker={"colors": colors, "line": {"color": "#FFFFFF", "width": 3}},  # เส้นขาวหนาคั่นชิ้นให้ดูสะอาด
            sort=False,  # คงลำดับหมวดตามตาราง
            direction="clockwise",
            textinfo="percent",
            textfont={"size": 14, "color": "#FFFFFF", "family": FONT_FAMILY},
            textposition="inside",  # ป้ายอยู่ในวงเสมอ (ถ้าปล่อยอัตโนมัติ Plotly จะย้ายออกนอกวงเป็นสีขาวบนพื้นขาวจนมองไม่เห็น)
            insidetextorientation="horizontal",
            hovertemplate="<b>%{label}</b><br>%{value} รายการ (%{percent})<br>ยอดรวม %{customdata:,.2f} บาท<extra></extra>",
            hoverlabel={
                "bgcolor": "#FFFFFF",
                "bordercolor": "#CBD5E1",
                "font": {"size": 15, "color": PALETTE["text"], "family": FONT_FAMILY},
            },
        )
    )
    figure.update_layout(
        showlegend=False,  # รายการหมวดวาดเองใต้กราฟ
        height=EQUIPMENT_DONUT_HEIGHT_PX,
        margin={"l": 0, "r": 0, "t": 6, "b": 6},
        font={"family": FONT_FAMILY, "color": PALETTE["text"]},
        paper_bgcolor=TRANSPARENT,
        plot_bgcolor=TRANSPARENT,
        annotations=[
            {
                "text": f"<b>{int(shown_table['Qty.'].sum()):,}</b>",
                "x": 0.5,
                "y": 0.54,
                "showarrow": False,
                "font": {"size": 42, "color": PALETTE["text"]},
            },
            {
                "text": "รายการทั้งหมด",
                "x": 0.5,
                "y": 0.42,
                "showarrow": False,
                "font": {"size": 15, "color": "#64748B"},
            },
        ],
    )
    return figure


def build_equipment_rows_html(equipment_table: pd.DataFrame) -> str:
    """สร้าง HTML รายการหมวดอุปกรณ์ใต้โดนัท: การ์ดเล็กต่อหมวด (ชื่อ + ยอดรวม / จำนวน + แถบสัดส่วน + %)

    Args:
        equipment_table: ตารางจาก build_equipment_list

    Returns:
        ข้อความ HTML (ชื่อหมวดผ่าน html.escape แล้ว) หัวส่วน "แยกตามหมวด" แล้วตามด้วยรายการ
    """
    total_quantity = int(equipment_table["Qty."].sum())
    rows_html = []
    for row in equipment_table.itertuples(index=False):
        category_name = row[0]
        quantity = int(row[1])
        share = quantity / total_quantity if total_quantity else 0.0
        color = CATEGORY_COLORS.get(category_name, FALLBACK_CATEGORY_COLOR)
        zero_class = " equip-row-zero" if quantity == 0 else ""  # หมวดที่ไม่มีรายการแสดงจางลง
        rows_html.append(
            f'<div class="equip-row{zero_class}" style="--cat:{color};--share:{share:.4f}">'
            '<div class="equip-top">'
            f'<span class="equip-name">{html.escape(str(category_name))}</span>'
            f'<span class="equip-amount">{float(row[2]):,.2f}</span>'
            "</div>"
            '<div class="equip-sub">'
            f'<span class="equip-qty">{quantity:,} รายการ</span>'
            '<span class="equip-bar"><i></i></span>'
            f'<span class="equip-pct">{share * 100:.1f}%</span>'
            "</div>"
            "</div>"
        )
    return f'<div class="equip-title">แยกตามหมวด</div><div class="equip-list">{"".join(rows_html)}</div>'


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
        st.plotly_chart(
            build_equipment_donut_figure(equipment_table), width="stretch", config={"displayModeBar": False}
        )  # ซ่อนแถบเครื่องมือกล้อง/ขยายเต็มจอ
        st.markdown(build_equipment_rows_html(equipment_table), unsafe_allow_html=True)


def build_vendor_rows_html(top_vendor_table: pd.DataFrame, grand_total: float) -> str:
    """สร้าง HTML ตารางจัดอันดับผู้ขาย: หัวคอลัมน์ + แถวละบริษัท (เหรียญอันดับ / ชื่อ / แถบสัดส่วน+% / จำนวน / ยอดรวม)

    Args:
        top_vendor_table: ตารางจาก build_top_vendor_table (เรียงยอดสูงสุดก่อน)
        grand_total: ยอดรวมของทุกผู้ขายในช่วงวันที่ (ใช้คำนวณ % ของแต่ละบริษัท)

    Returns:
        ข้อความ HTML (ชื่อผู้ขายผ่าน html.escape แล้ว) ความยาวแถบเทียบกับบริษัทอันดับ 1
    """
    top_amount = float(top_vendor_table["total_price"].max()) if len(top_vendor_table) else 0.0
    rows_html = [
        '<div class="vendor-head"><span>#</span><span>บริษัท</span><span>สัดส่วนยอดซื้อ</span>'
        "<span>จำนวนรายการ</span><span>ยอดรวม (บาท)</span></div>"
    ]
    for rank, row in enumerate(top_vendor_table.itertuples(index=False), start=1):
        vendor_name = html.escape(str(row.vendor))
        amount = float(row.total_price)
        bar_share = amount / top_amount if top_amount else 0.0
        percent = amount / grand_total * 100 if grand_total else 0.0
        rows_html.append(
            f'<div class="vendor-row" style="--share:{bar_share:.4f};--i:{rank - 1}">'
            f'<span class="vendor-rank">{rank}</span>'
            f'<span class="vendor-name" title="{vendor_name}">{vendor_name}</span>'
            f'<span class="vendor-share"><span class="vendor-bar"><i></i></span><span class="vendor-pct">{percent:.1f}%</span></span>'
            f'<span class="vendor-qty">{int(row.order_count):,} รายการ</span>'
            f'<span class="vendor-amount">{amount:,.2f}</span>'
            "</div>"
        )
    return '<div class="vendor-list">' + "".join(rows_html) + "</div>"


def render_vendor_table_card(transaction_table: pd.DataFrame) -> None:
    """วาดการ์ด Vendor: ตารางจัดอันดับผู้ขายตามยอดซื้อ (แถบสัดส่วน + จำนวนรายการ + ยอดรวม)

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
        top_vendor_table = build_top_vendor_table(transaction_table)
        grand_total = float(transaction_table["total_price"].sum())
        st.markdown(build_vendor_rows_html(top_vendor_table, grand_total), unsafe_allow_html=True)


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

    # ส่วนที่ 2: ตัวเลขสรุป 3 ช่อง
    render_kpi_row(transaction_table)

    # ส่วนที่ 3: แถวกลาง ซ้าย = แนวโน้มยอดซื้อ / ขวา = Equipment (โดนัท + รายการหมวด)
    trend_column, equipment_column = st.columns(TREND_ROW_RATIO, gap="medium")
    with trend_column:
        render_trend_card(transaction_table, start_date, end_date)
    with equipment_column:
        render_equipment_card(start_date, end_date)

    # ส่วนที่ 4: แถวล่าง ตาราง Vendor เต็มความกว้าง
    render_vendor_table_card(transaction_table)
