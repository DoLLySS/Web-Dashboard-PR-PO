"""ตารางกลางของระบบ (streamlit-aggrid): ทุกตารางในโปรเจคเรียกใช้ที่นี่ เพื่อให้หน้าตาเหมือนกันทั้งแอป

ตารางแบบ AgGrid วาดด้วย HTML จึงปรับขนาดตัวหนังสือ / ช่องไฟในเซลล์ / สีหัวตาราง / สีแถวสลับได้จริง
(ต่างจาก st.dataframe ที่วาดด้วย canvas และปรับขนาดตัวหนังสือไม่ได้)

วิธีใช้:
    - ตารางอ่านอย่างเดียว (Dashboard): render_readonly_grid(ตาราง, key="ชื่อไม่ซ้ำ", money_columns=("ยอดรวม",))
    - ตารางที่แก้ไข/เลือกแถวได้ (Overview): สร้าง options ด้วย build_grid_options แล้วเรียก show_grid

อยากเปลี่ยนหน้าตาตารางทั้งระบบ ให้แก้ค่าคงที่ GRID_* ด้านล่างที่เดียว
"""

from typing import Any, Optional

import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, AgGridReturn, GridOptionsBuilder, JsCode
from st_aggrid.shared import StAggridTheme

from config.logging_setup import get_logger
from config.styles import FONT_FAMILY, PALETTE, TABLE_ROW_HEIGHT_PX

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# ค่าคงที่หน้าตาตาราง (แก้ที่นี่ที่เดียว มีผลทุกตาราง)
# ---------------------------------------------------------------------------

GRID_FONT_SIZE_PX: int = 15  # ขนาดตัวหนังสือในเซลล์ (15-16px: ตัวใหญ่กว่านี้ 13 คอลัมน์จะไม่พอดีจอ)
GRID_HEADER_FONT_SIZE_PX: int = 15  # ขนาดตัวหนังสือหัวตาราง
GRID_HEADER_HEIGHT_PX: int = 48  # ความสูงแถวหัวตาราง
GRID_CELL_PADDING_PX: int = 10  # ช่องไฟซ้าย-ขวาในเซลล์ (ยิ่งมากยิ่งโปร่ง)
GRID_HEADER_BACKGROUND: str = "#F1F5F9"  # สีพื้นหัวตาราง
GRID_ZEBRA_COLOR: str = "#fff1cf"  # สีแถวสลับ (แถวที่ 2, 4, 6 ...)
GRID_PAGE_SIZE: int = 15  # จำนวนแถวต่อหน้าของตารางที่เปิด Pagination
GRID_PAGE_SIZE_CHOICES: list[int] = [10, 15, 25, 50, 100]  # ตัวเลือกจำนวนแถวต่อหน้า
GRID_DEFAULT_WIDTH_PX: int = 120  # ความกว้างที่ต้องการของคอลัมน์ที่ไม่ได้ระบุ (ตารางจะปรับตามสัดส่วนให้พอดีจอ)
GRID_FLEXIBLE_WIDTH_PX: int = 200  # ความกว้างที่ต้องการของคอลัมน์ข้อความยาว (เช่น Description) ให้กว้างกว่าคอลัมน์อื่น
# จอแคบย่อคอลัมน์ได้ถึงกี่เท่าของความกว้างที่ต้องการ: คอลัมน์ตัวเลข/วันที่/สถานะย่อได้น้อย (ไม่ให้ตัวเลขถูกตัด)
# ส่วนคอลัมน์ข้อความ (ชื่อผู้ขาย, คำอธิบาย) ย่อได้มาก (ตัดด้วย ... และชี้เมาส์ดูข้อความเต็มได้) ถ้าย่อสุดแล้วยังไม่พอจอ จะมีแถบเลื่อนแนวนอน
GRID_MIN_WIDTH_RATIO_FIXED: float = 0.95
GRID_MIN_WIDTH_RATIO_SHRINKABLE: float = 0.6
GRID_MIN_WIDTH_FLEXIBLE_PX: int = 80  # ความกว้างต่ำสุดของคอลัมน์ข้อความยาว (Description)
GRID_PAGINATION_HEIGHT_PX: int = 56  # ความสูงแถบเปลี่ยนหน้าด้านล่างตาราง (ใช้คำนวณความสูงตาราง)

# รูปแบบแสดงตัวเลขเงิน: มีคอมม่า ทศนิยม 2 ตำแหน่ง (ช่องว่างแสดงเป็นว่าง) ใช้กับ valueFormatter ของ AgGrid
MONEY_FORMATTER_JS: str = """
function(params) {
    if (params.value === null || params.value === undefined || params.value === '' || isNaN(params.value)) { return ''; }
    return Number(params.value).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
}
"""

# รูปแบบแสดงวันที่: เก็บค่าเป็น "YYYY-MM-DD" แต่แสดงเป็น DD/MM/YYYY
DATE_FORMATTER_JS: str = """
function(params) {
    if (!params.value) { return ''; }
    var parts = String(params.value).substring(0, 10).split('-');
    return parts.length === 3 ? parts[2] + '/' + parts[1] + '/' + parts[0] : params.value;
}
"""


def build_grid_theme() -> StAggridTheme:
    """สร้างธีมของตาราง: ตัวหนังสือใหญ่ แถวสูง ช่องไฟกว้าง หัวตารางสีเทาอ่อน แถวสลับสี

    Returns:
        ธีมสำหรับส่งให้พารามิเตอร์ theme ของ AgGrid
    """
    return StAggridTheme(base="quartz").withParams(
        fontFamily=FONT_FAMILY,  # ฟอนต์เดียวกับทั้งแอป (รองรับภาษาไทย)
        fontSize=GRID_FONT_SIZE_PX,  # ขนาดตัวหนังสือในเซลล์
        rowHeight=TABLE_ROW_HEIGHT_PX,  # ความสูงแถว (ตั้งที่ config/styles.py)
        headerHeight=GRID_HEADER_HEIGHT_PX,  # ความสูงหัวตาราง
        headerFontSize=GRID_HEADER_FONT_SIZE_PX,  # ขนาดตัวหนังสือหัวตาราง
        headerFontWeight=700,  # หัวตารางตัวหนา
        headerBackgroundColor=GRID_HEADER_BACKGROUND,  # สีพื้นหัวตาราง
        headerTextColor=PALETTE["text"],  # สีตัวหนังสือหัวตาราง
        foregroundColor=PALETTE["text"],  # สีตัวหนังสือในเซลล์
        oddRowBackgroundColor=GRID_ZEBRA_COLOR,  # สีแถวสลับ
        cellHorizontalPadding=GRID_CELL_PADDING_PX,  # ช่องไฟซ้าย-ขวาในเซลล์
        borderColor=PALETTE["border"],  # สีเส้นขอบ
        wrapperBorderRadius=8,  # มุมมนของกรอบตาราง
    )


# CSS เสริมในตาราง (ใส่ผ่าน custom_css ของ AgGrid) ใช้ปรับส่วนที่ธีมไม่ครอบคลุม
# ตัวอย่าง: ขนาดตัวหนังสือแถบเปลี่ยนหน้า (Pagination) และช่องกรอก Filter
GRID_CUSTOM_CSS: dict[str, dict[str, str]] = {
    ".ag-paging-panel": {"font-size": f"{GRID_FONT_SIZE_PX}px !important"},  # แถบ Pagination ด้านล่าง
    ".ag-header-cell-text": {"font-size": f"{GRID_HEADER_FONT_SIZE_PX}px !important"},  # ชื่อหัวคอลัมน์
    ".ag-cell": {"line-height": f"{TABLE_ROW_HEIGHT_PX - 2}px !important"},  # จัดตัวหนังสือกึ่งกลางแถวสูง
    # ปุ่มกรองที่หัวคอลัมน์ซ่อนไว้ จนกว่าจะเอาเมาส์ชี้ (ประหยัดที่ให้คอลัมน์ไม่ถูกตัด)
    ".ag-header-cell:not(:hover) .ag-header-cell-filter-button": {"display": "none !important"},
    ".ag-popup, .ag-menu, .ag-filter": {"font-size": f"{GRID_FONT_SIZE_PX}px !important"},  # เมนู Filter / dropdown
}


def build_grid_options(
    table: pd.DataFrame,
    *,
    header_names: Optional[dict[str, str]] = None,
    column_widths: Optional[dict[str, Optional[int]]] = None,
    shrinkable_columns: tuple[str, ...] = (),
    editable_columns: tuple[str, ...] = (),
    money_columns: tuple[str, ...] = (),
    date_columns: tuple[str, ...] = (),
    hidden_columns: tuple[str, ...] = (),
    selectable: bool = False,
    paginated: bool = False,
    filterable: bool = False,
    extra_column_options: Optional[dict[str, dict[str, Any]]] = None,
) -> dict[str, Any]:
    """สร้าง gridOptions ของ AgGrid: ขยายคอลัมน์ให้พอดีหน้าจอ + เรียงลำดับ + (ตัวกรอง / Pagination / เลือกแถว) ตามที่ขอ

    Args:
        table: ตารางที่จะแสดง (ชื่อคอลัมน์ = field)
        header_names: {ชื่อคอลัมน์: หัวคอลัมน์ที่แสดง} ถ้าไม่ระบุใช้ชื่อคอลัมน์
        column_widths: {ชื่อคอลัมน์: ความกว้างที่ต้องการ px} ตารางจะย่อ/ขยายทุกคอลัมน์ตามสัดส่วนให้พอดีหน้าจอ
            (จอแคบ = ย่อได้ตามอัตรา GRID_MIN_WIDTH_RATIO_* แล้วข้อความยาวจะถูกตัดด้วย ... และชี้เมาส์ดูข้อความเต็มได้)
            ค่า None = คอลัมน์ข้อความยาว (GRID_FLEXIBLE_WIDTH_PX) คอลัมน์ที่ไม่ได้ระบุใช้ GRID_DEFAULT_WIDTH_PX
        shrinkable_columns: คอลัมน์ข้อความที่ยอมให้ย่อได้มากเมื่อจอแคบ (คอลัมน์อื่นย่อได้น้อย จะได้ไม่ตัดตัวเลข/วันที่)
            คอลัมน์ที่ไม่ได้ระบุใน column_widths ถือเป็นคอลัมน์ที่ย่อได้มากเสมอ
        editable_columns: คอลัมน์ที่ผู้ใช้แก้ไขได้ในตาราง
        money_columns: คอลัมน์ตัวเลขเงิน (แสดงมีคอมม่า ทศนิยม 2 ตำแหน่ง ชิดขวา)
        date_columns: คอลัมน์วันที่ที่เก็บเป็นข้อความ "YYYY-MM-DD" (แสดงเป็น DD/MM/YYYY)
        hidden_columns: คอลัมน์ที่ซ่อน (ใช้เก็บ id / ลำดับแถว)
        selectable: True = มีช่องติ๊กเลือกหลายแถว (ใช้คู่กับปุ่มลบ)
        paginated: True = แบ่งหน้า (GRID_PAGE_SIZE แถวต่อหน้า)
        filterable: True = มีตัวกรองที่หัวคอลัมน์
        extra_column_options: ตั้งค่าคอลัมน์เพิ่มเอง {ชื่อคอลัมน์: {ตัวเลือกของ AgGrid}} เช่น dropdown / ไอคอนลิงก์

    Returns:
        dict พร้อมส่งให้พารามิเตอร์ gridOptions ของ AgGrid
    """
    header_names = header_names or {}
    column_widths = column_widths or {}
    extra_column_options = extra_column_options or {}

    builder = GridOptionsBuilder.from_dataframe(table)
    # ค่าเริ่มต้นของทุกคอลัมน์: เรียงลำดับได้ / ลากปรับความกว้างได้ / ตัวกรองตามที่ขอ (ความกว้างตั้งรายคอลัมน์ด้านล่าง)
    builder.configure_default_column(
        sortable=True,
        resizable=True,
        filter=filterable,
        width=GRID_DEFAULT_WIDTH_PX,
        minWidth=int(GRID_DEFAULT_WIDTH_PX * GRID_MIN_WIDTH_RATIO_SHRINKABLE),
        wrapHeaderText=False,
        tooltipValueGetter=JsCode("function(params) { return params.value; }"),  # เอาเมาส์ชี้เซลล์เพื่อดูข้อความเต็ม
    )

    for column in table.columns:
        if column in hidden_columns:
            builder.configure_column(column, hide=True)
            continue

        column_options: dict[str, Any] = {"headerName": header_names.get(column, column)}
        # ความกว้างที่ต้องการ (None = คอลัมน์ข้อความยาว) และความกว้างต่ำสุดที่ย่อได้เมื่อจอแคบ
        is_flexible_text = column in column_widths and column_widths[column] is None
        preferred_width = column_widths.get(column, GRID_DEFAULT_WIDTH_PX) or GRID_FLEXIBLE_WIDTH_PX
        if is_flexible_text:
            minimum_width = GRID_MIN_WIDTH_FLEXIBLE_PX
        elif column in shrinkable_columns or column not in column_widths:
            minimum_width = int(preferred_width * GRID_MIN_WIDTH_RATIO_SHRINKABLE)
        else:
            minimum_width = int(preferred_width * GRID_MIN_WIDTH_RATIO_FIXED)
        column_options["width"] = preferred_width
        column_options["minWidth"] = minimum_width
        if column in editable_columns:
            column_options["editable"] = True
        if column in money_columns:
            column_options.update(
                {"type": ["numericColumn"], "valueFormatter": JsCode(MONEY_FORMATTER_JS)}
            )
        if column in date_columns:
            column_options["valueFormatter"] = JsCode(DATE_FORMATTER_JS)
        column_options.update(extra_column_options.get(column, {}))
        builder.configure_column(column, **column_options)

    if selectable:
        # ติ๊กเลือกหลายแถวด้วยช่อง checkbox (คลิกที่แถวเฉย ๆ ไม่เลือก กันกดผิดตอนจะแก้ไขค่า)
        # ใช้รูปแบบ rowSelection ของ AG Grid รุ่นใหม่ (configure_selection ของไลบรารีไม่สร้างช่อง checkbox ให้)
        builder.configure_grid_options(
            rowSelection={"mode": "multiRow", "checkboxes": True, "headerCheckbox": True, "enableClickSelection": False},
            selectionColumnDef={"width": 44, "minWidth": 44, "maxWidth": 44, "pinned": "left"},
        )
    if paginated:
        builder.configure_pagination(enabled=True, paginationAutoPageSize=False, paginationPageSize=GRID_PAGE_SIZE)
        builder.configure_grid_options(paginationPageSizeSelector=GRID_PAGE_SIZE_CHOICES)

    # autoSizeStrategy=fitGridWidth: ขยาย/หดคอลัมน์ให้พอดีความกว้างหน้าจอ ไม่มีแถบเลื่อนแนวนอน
    builder.configure_grid_options(
        tooltipShowDelay=400,
        autoSizeStrategy={"type": "fitGridWidth"},
        suppressMovableColumns=True,
        enableCellTextSelection=True,  # ลากคลุมข้อความในเซลล์เพื่อคัดลอกได้
        singleClickEdit=False,  # ดับเบิลคลิกเพื่อแก้ไข กันแก้ไขโดยไม่ตั้งใจ
        stopEditingWhenCellsLoseFocus=True,  # คลิกที่อื่นแล้วถือว่ายืนยันค่าที่พิมพ์
    )
    return builder.build()


def calculate_grid_height(row_count: int, is_paginated: bool) -> int:
    """คำนวณความสูงตาราง (px) ให้พอดีกับจำนวนแถวที่แสดง จะได้ไม่มีพื้นที่ว่างหรือแถบเลื่อนซ้อนในตาราง

    (ใช้ความสูงคงที่แทน autoHeight ของ AgGrid เพราะ autoHeight ทำให้กรอบตารางสูง 0 ใน Streamlit รุ่นนี้)

    Args:
        row_count: จำนวนแถวข้อมูลทั้งหมด
        is_paginated: ตารางแบ่งหน้าหรือไม่ (แบ่งหน้า = แสดงไม่เกิน GRID_PAGE_SIZE แถวต่อหน้า และมีแถบเปลี่ยนหน้า)

    Returns:
        ความสูงเป็นพิกเซล
    """
    visible_rows = max(1, min(row_count, GRID_PAGE_SIZE) if is_paginated else row_count)
    pagination_height = GRID_PAGINATION_HEIGHT_PX if is_paginated else 0
    return GRID_HEADER_HEIGHT_PX + visible_rows * TABLE_ROW_HEIGHT_PX + pagination_height + 4  # +4 = เส้นขอบ


def show_grid(
    table: pd.DataFrame,
    grid_options: dict[str, Any],
    key: str,
    *,
    update_on: Optional[list[str]] = None,
) -> Optional[AgGridReturn]:
    """วาดตาราง AgGrid ด้วยธีมกลาง

    Args:
        table: ตารางที่จะแสดง
        grid_options: ได้จาก build_grid_options
        key: key ของตาราง (ต้องไม่ซ้ำในหน้า) เปลี่ยน key = ล้างสถานะการแก้ไข/เลือกแถวเดิม
        update_on: เหตุการณ์ที่ให้ตารางส่งค่ากลับมา (ว่าง = ตารางอ่านอย่างเดียว ไม่ส่งอะไรกลับ)

    Returns:
        ผลจากตาราง (มี .data, .selected_rows); None ถ้าวาดตารางไม่สำเร็จ (แจ้ง error ให้ผู้ใช้แล้ว)
    """
    try:
        return AgGrid(
            table,
            gridOptions=grid_options,
            height=calculate_grid_height(len(table), bool(grid_options.get("pagination"))),
            theme=build_grid_theme(),
            custom_css=GRID_CUSTOM_CSS,
            allow_unsafe_jscode=True,  # จำเป็นสำหรับ JsCode (รูปแบบตัวเลข/วันที่/ไอคอนลิงก์) เป็นโค้ดของเราเอง ไม่ใช่ข้อมูลผู้ใช้
            update_on=update_on or [],
            data_return_mode="AS_INPUT",  # ส่งกลับตามลำดับเดิมพร้อมค่าที่แก้ (จับคู่แถวด้วยคอลัมน์ลำดับ)
            key=key,
            show_toolbar=False,
        )
    except Exception as error:  # noqa: BLE001 - ไลบรารีตารางล้ม ไม่ให้ทั้งหน้าพัง
        logger.error("วาดตาราง '%s' ไม่สำเร็จ: %s", key, error, exc_info=True)
        st.error(f"❌ แสดงตารางไม่สำเร็จ: ลองรีเฟรชหน้าเว็บ รายละเอียด: {error}")
        return None


def render_readonly_grid(
    table: pd.DataFrame,
    key: str,
    *,
    money_columns: tuple[str, ...] = (),
    right_aligned_columns: tuple[str, ...] = (),
) -> None:
    """วาดตารางอ่านอย่างเดียว (ใช้ใน Dashboard): ตัวหนังสือใหญ่ แถวสลับสี คลิกหัวคอลัมน์เพื่อเรียงลำดับ

    Args:
        table: ตารางที่จะแสดง
        key: key ของตาราง (ต้องไม่ซ้ำในหน้า)
        money_columns: คอลัมน์ตัวเลขเงิน (มีคอมม่า ทศนิยม 2 ตำแหน่ง)
        right_aligned_columns: คอลัมน์จำนวนเต็มที่อยากให้ชิดขวา (เช่น Qty.)
    """
    extra_options = {column: {"type": ["numericColumn"]} for column in right_aligned_columns}
    grid_options = build_grid_options(table, money_columns=money_columns, extra_column_options=extra_options)
    # ต่อท้าย key ด้วยค่าแฮชของข้อมูล: ข้อมูลเปลี่ยน (เช่น เปลี่ยน Date Filter) ตารางจะวาดใหม่ ไม่ค้างข้อมูลเก่า
    content_hash = int(pd.util.hash_pandas_object(table.reset_index(drop=True), index=False).sum() % 10**9)
    show_grid(table, grid_options, f"{key}_{content_hash}")
