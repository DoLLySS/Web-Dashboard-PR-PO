"""หน้า Dashboard: กราฟราคา (Price), รายการอุปกรณ์ (Equipment) และผู้ขาย (Vendor)

โครงหน้า (ตามดีไซน์):
    หัวหน้า (ชื่อหน้า + Date Filter) อยู่ใน app.py
                                            [Export 📥]  <- ดาวน์โหลด CSV ของช่วงวันที่ที่เลือก
    ┌────────────────────────────────┬───────────────┐
    │ การ์ด Price [7d ▾] [Detail Graph]│ การ์ด Vendor  │
    │   ยอดรวม + กราฟเส้น            │  รายชื่อบริษัท │
    ├────────────────────────────────┤               │
    │ การ์ด Equipment (List)          │               │
    └────────────────────────────────┴───────────────┘

ข้อมูลทั้งหมดดึงจาก database.py (Price/Vendor/Export อิง Date Filter ของ app.py)
"""

from datetime import date, timedelta
from typing import Optional

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from config import EQUIPMENT_CATEGORIES
from data.database import STATUS_PENDING, get_category_counts, get_transactions
from styles import FONT_FAMILY, PALETTE
from ui_common import build_css

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

# กราฟ Top Vendors by Spend: สีแท่ง, ความสูงต่อแท่ง (px) และความสูงขั้นต่ำของกราฟ
VENDOR_BAR_COLOR: str = "#2E6FD8"
VENDOR_CHART_ROW_HEIGHT: int = 32
VENDOR_CHART_MIN_HEIGHT: int = 160

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

# สัดส่วนความกว้างของหน้า: [ฝั่งซ้าย (Price + Equipment), ฝั่งขวา (Vendor)]
PAGE_COLUMN_RATIO: list[int] = [3, 2]

# CSS เฉพาะหน้า Dashboard (กฎกลางของการ์ดอยู่ที่ ui_common.py)
PAGE_CSS_RULES: str = """
/* (ปุ่ม ช่องกรอก และมุม 8px มาจากธีมกลาง styles.py แล้ว) */
/* ปุ่ม Export: ชิดขวา กว้างพอดีข้อความ พื้นขาว ขอบสีเข้ม (ตามดีไซน์) */
.st-key-dashboard_export [data-testid="stDownloadButton"] { display: flex; justify-content: flex-end; }
.st-key-dashboard_export button {
    background: #ffffff; color: var(--ui-text); border: 1.5px solid var(--ui-text); font-weight: 600;
}
.st-key-dashboard_export button:hover { background: var(--ui-inner-bg); color: var(--ui-text); border-color: var(--ui-text); }
/* ตัวเลขยอดรวมในการ์ด Price */
.st-key-price_inner [data-testid="stMetricValue"] { font-size: var(--app-metric-value); font-weight: 800; }
/* การ์ดยอดรวมค่าใช้จ่าย: ตัวเลขใหญ่แบบเดียวกับการ์ด Price และไม่มีกรอบซ้อน */
.st-key-spend_inner [data-testid="stMetricValue"] { font-size: var(--app-metric-value); font-weight: 800; }
.st-key-spend_inner [data-testid="stMetric"] { border: none; box-shadow: none; background: transparent; padding: 0; }
/* st.metric ในกล่องนี้ไม่ต้องมีกรอบ/เงาซ้อน (กล่องด้านนอกมีอยู่แล้ว) */
.st-key-price_inner [data-testid="stMetric"] { border: none; box-shadow: none; background: transparent; padding: 0; }
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
    top_vendor_table.columns = ["Company", "จำนวนรายการ", "ยอดรวม (บาท)"]
    top_vendor_table.index = range(1, len(top_vendor_table) + 1)  # ให้ลำดับเริ่มที่ 1
    return top_vendor_table


# ---------------------------------------------------------------------------
# ส่วนแสดงผล
# ---------------------------------------------------------------------------


def render_metrics(transaction_table: pd.DataFrame) -> None:
    """แสดงตัวเลขสรุป 4 ช่อง (ไม่ได้ใช้ใน layout ตามดีไซน์ปัจจุบัน เก็บไว้เผื่อนำกลับมาใช้)

    Args:
        transaction_table: ตารางจาก load_transaction_table
    """
    pending_table = transaction_table[transaction_table["invoice_status"] == STATUS_PENDING]

    metric_columns = st.columns(4)
    metric_columns[0].metric("จำนวนรายการ", f"{len(transaction_table):,}")
    metric_columns[1].metric("ยอดรวม (บาท)", f"{transaction_table['total_price'].sum():,.2f}")
    metric_columns[2].metric("จำนวนผู้ขาย", f"{transaction_table['vendor'].nunique():,}")
    metric_columns[3].metric(
        "รอใบกำกับภาษี",
        f"{len(pending_table):,} รายการ",
        help=f"ยอดรวม {pending_table['total_price'].sum():,.2f} บาท",
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


def render_price_card(
    transaction_table: pd.DataFrame, start_date: date, end_date: date
) -> None:
    """วาดการ์ด Price: ปุ่มเลือกช่วงเวลา + สวิตช์ Detail Graph + ยอดรวม + กราฟเส้น

    - ปุ่มช่วงเวลา (7d / 30d / ...): เลือกช่วงวันที่ของยอดรวมและกราฟ (ไม่เกินขอบเขต Date Filter)
    - สวิตช์ Detail Graph: ปิด = เส้นเดียวรวมทุกหมวด, เปิด = แยกเส้นตามหมวดหมู่ (Multi Line)

    Args:
        transaction_table: ตารางจาก load_transaction_table (ตาม Date Filter)
        start_date: วันที่เริ่มต้นจาก Date Filter
        end_date: วันที่สิ้นสุดจาก Date Filter
    """
    with st.container(key="price_card"):
        title_column, range_column, detail_column = st.columns([1.2, 1.4, 1.4], vertical_alignment="center")
        title_column.markdown('<span class="card-pill">Price</span>', unsafe_allow_html=True)
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

        with st.container(key="price_inner"):
            st.metric(
                "ยอดรวม (บาท)",
                f"{window_table['total_price'].sum() if not window_table.empty else 0:,.2f}",
                help=f"ช่วง {window_start:%d/%m/%Y} - {window_end:%d/%m/%Y}",
            )
            if window_table.empty:
                st.info("ไม่พบรายการในช่วงเวลาที่เลือก ลองเลือกช่วงที่ยาวขึ้น หรือขยาย Date Filter ที่มุมขวาบน")
                return
            trend_table = build_trend_table(window_table, window_start, window_end, show_detail_graph)
            st.plotly_chart(build_trend_figure(trend_table), width="stretch")


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


def render_equipment_card(start_date: date, end_date: date) -> None:
    """วาดการ์ด Equipment: รายการ (List) จำนวนและยอดรวมแยกตามหมวด

    Args:
        start_date: วันที่เริ่มต้นจาก Date Filter
        end_date: วันที่สิ้นสุดจาก Date Filter
    """
    with st.container(key="equipment_card"):
        st.markdown('<span class="card-pill">Equipment</span>', unsafe_allow_html=True)
        with st.container(key="equipment_inner"):
            st.dataframe(
                build_equipment_list(start_date, end_date),
                hide_index=True,
                width="stretch",
                column_config={"ยอดรวม (บาท)": st.column_config.NumberColumn(format="%.2f")},
            )


def build_vendor_spend_figure(vendor_spend_table: pd.DataFrame) -> go.Figure:
    """สร้างกราฟแท่งแนวนอน Top Vendors by Spend

    Args:
        vendor_spend_table: ตารางจาก build_vendor_spend_table (ต้องไม่ว่าง)

    Returns:
        Figure ของ Plotly พร้อมส่งให้ st.plotly_chart
    """
    figure = px.bar(
        vendor_spend_table,  # ตารางข้อมูลที่ใช้วาด
        x="spend",  # แกน X: ค่าใช้จ่ายรวม (Net Price)
        y="vendor",  # แกน Y: ชื่อผู้ขาย
        orientation="h",  # แท่งแนวนอน ชื่อบริษัทยาวอ่านง่ายกว่า
        text="spend",  # แสดงตัวเลขที่ปลายแท่ง
        labels={"spend": "ค่าใช้จ่าย (บาท)", "vendor": "ผู้ขาย"},  # ชื่อใน Tooltip
    )
    figure.update_traces(
        marker_color=VENDOR_BAR_COLOR,  # สีแท่ง (แก้ที่ค่าคงที่ด้านบนไฟล์)
        texttemplate="%{x:,.2f}",  # ตัวเลขมี , คั่นหลัก ทศนิยม 2 ตำแหน่ง
        hovertemplate="%{y}<br>%{x:,.2f} บาท<extra></extra>",  # ข้อความ Tooltip
    )
    figure.update_xaxes(title_text="", tickformat=",.0f", rangemode="tozero")  # แกน X เริ่มที่ 0
    figure.update_yaxes(title_text="", autorange="reversed")  # กลับแกน Y ให้อันดับ 1 อยู่บนสุด
    figure.update_layout(
        margin={"l": 0, "r": 0, "t": 10, "b": 0},  # ระยะขอบกราฟ (ซ้าย ขวา บน ล่าง)
        font={"family": FONT_FAMILY, "color": PALETTE["text"]},  # ฟอนต์ให้ตรงกับธีมกลาง
        height=max(VENDOR_CHART_MIN_HEIGHT, VENDOR_CHART_ROW_HEIGHT * len(vendor_spend_table)),  # สูงตามจำนวนแท่ง
    )
    return figure


def render_spend_metric(transaction_table: pd.DataFrame) -> None:
    """วาดการ์ดสรุป 'ยอดรวมค่าใช้จ่ายทั้งหมด' (ผลรวม Net Price / unit_price)

    Args:
        transaction_table: ตารางจาก load_transaction_table
    """
    spend_table = get_spend_table(transaction_table)
    # ถ้ายังไม่มีข้อมูลราคาเลย แสดง 'ยังไม่มีข้อมูล' แทนที่จะแสดง 0.00
    spend_text = "ยังไม่มีข้อมูล" if spend_table.empty else f"{spend_table['unit_price'].sum():,.2f} บาท"
    with st.container(key="spend_card"):
        with st.container(key="spend_inner"):
            st.metric(
                "ยอดรวมค่าใช้จ่ายทั้งหมด",
                spend_text,
                help="ผลรวม Net Price (unit_price) ของรายการในช่วงวันที่ที่เลือก",
            )


def render_vendor_card(transaction_table: pd.DataFrame) -> None:
    """วาดการ์ด Vendor: กราฟ Top Vendors by Spend + รายชื่อบริษัท (Company) เรียงตามยอดซื้อ

    Args:
        transaction_table: ตารางจาก load_transaction_table
    """
    with st.container(key="vendor_card"):
        st.markdown('<span class="card-pill">Vendor</span>', unsafe_allow_html=True)  # รายชื่อบริษัทผู้จัดจำหน่ายหลัก
        with st.container(key="vendor_inner"):
            if transaction_table.empty:
                st.info("ยังไม่มีข้อมูลผู้ขายในช่วงวันที่ที่เลือก")
                return
            st.caption("Top Vendors by Spend (Net Price)")
            vendor_spend_table = build_vendor_spend_table(transaction_table)
            if vendor_spend_table.empty:
                st.info("ยังไม่มีข้อมูลราคา (Net Price) จึงยังสร้างกราฟค่าใช้จ่ายไม่ได้")
            else:
                st.plotly_chart(build_vendor_spend_figure(vendor_spend_table), width="stretch")
            st.dataframe(
                build_top_vendor_table(transaction_table),
                width="stretch",
                column_config={"ยอดรวม (บาท)": st.column_config.NumberColumn(format="%.2f")},
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

    # ส่วนที่ 1: ปุ่ม Export 📥 ขวาบน (ดาวน์โหลด CSV ตามช่วงวันที่ของ Date Filter)
    export_csv = build_export_csv(start_date, end_date)
    transaction_table = load_transaction_table(start_date, end_date)
    spend_column, export_column = st.columns([3, 1], vertical_alignment="center")
    with spend_column:
        render_spend_metric(transaction_table)  # การ์ดยอดรวมค่าใช้จ่ายทั้งหมด (ซ้าย)
    export_column.download_button(
        "Export 📥",
        data=export_csv,
        file_name=f"masterlist_{start_date.isoformat()}_{end_date.isoformat()}.csv",
        mime="text/csv",
        disabled=not export_csv,  # ไม่มีข้อมูลให้ปิดปุ่ม
        key="dashboard_export",
    )

    left_column, right_column = st.columns(PAGE_COLUMN_RATIO, gap="medium")

    # ส่วนที่ 2: ฝั่งซ้าย = การ์ด Price (บน) + การ์ด Equipment (ล่าง)
    with left_column:
        render_price_card(transaction_table, start_date, end_date)
        render_equipment_card(start_date, end_date)

    # ส่วนที่ 3: ฝั่งขวา = การ์ด Vendor
    with right_column:
        render_vendor_card(transaction_table)
