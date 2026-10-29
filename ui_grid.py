"""ตารางกลางของระบบ (streamlit-aggrid): ทุกตารางในโปรเจคเรียกใช้ที่นี่ เพื่อให้หน้าตาเหมือนกันทั้งแอป

ตารางแบบ AgGrid วาดด้วย HTML จึงปรับขนาดตัวหนังสือ / ช่องไฟในเซลล์ / สีหัวตาราง / สีแถวสลับได้จริง
(ต่างจาก st.dataframe ที่วาดด้วย canvas และปรับขนาดตัวหนังสือไม่ได้)

วิธีใช้:
    - ตารางอ่านอย่างเดียว (Dashboard): render_readonly_grid(ตาราง, key="ชื่อไม่ซ้ำ", money_columns=("ยอดรวม",))
    - ตารางที่แก้ไข/เลือกแถวได้ (Overview): สร้าง options ด้วย build_grid_options แล้วเรียก show_grid

อยากเปลี่ยนหน้าตาตารางทั้งระบบ ให้แก้ค่าคงที่ GRID_* ด้านล่างที่เดียว
"""

import json
from typing import Any, Optional

import pandas as pd
import streamlit as st
from st_aggrid import AgGrid, AgGridReturn, GridOptionsBuilder, JsCode
from st_aggrid.shared import StAggridTheme

from config.logging_setup import get_logger
from config.styles import FONT_FAMILY, GOOGLE_FONTS_URL, PALETTE, TABLE_ROW_HEIGHT_PX

logger = get_logger(__name__)

# ---------------------------------------------------------------------------
# ค่าคงที่หน้าตาตาราง (แก้ที่นี่ที่เดียว มีผลทุกตาราง)
# ---------------------------------------------------------------------------

GRID_FONT_SIZE_PX: int = 16  # ขนาดตัวหนังสือในเซลล์ (16px: เล็กพอให้ข้อความแสดงครบในบรรทัดเดียวโดยไม่ต้องเลื่อนแนวนอน)
GRID_HEADER_FONT_SIZE_PX: int = 15  # ขนาดตัวหนังสือหัวตาราง (เล็กกว่าเนื้อหาเล็กน้อย แยกด้วยตัวหนาและสีพื้น)
GRID_HEADER_FONT_WEIGHT: int = 700  # น้ำหนักตัวหนังสือหัวตาราง (700 = bold)
GRID_TEXT_COLOR: str = "#334155"  # สีตัวหนังสือในเซลล์: เทาเข้ม (Charcoal) ไม่ดำสนิท อ่านสบายตา
GRID_BORDER_COLOR: str = "#E8EDF3"  # สีเส้นขอบตาราง/เส้นคั่นแถว: อ่อนมาก ไม่แย่งความสนใจจากตัวหนังสือ
GRID_HEADER_HEIGHT_PX: int = 52  # ความสูงแถวหัวตาราง
GRID_CELL_PADDING_PX: int = 12  # ช่องไฟซ้าย-ขวาในเซลล์ (ยิ่งมากยิ่งโปร่ง)
GRID_HEADER_BACKGROUND: str = "#F4F6F8"  # สีพื้นหัวตาราง
GRID_ZEBRA_COLOR: str = "#FFFBF0"  # สีแถวสลับ (แถวที่ 1, 3, 5 ...) ครีมอ่อนมาก ไม่ให้ป้ายสีสถานะกลืนกับพื้น
GRID_ROW_HOVER_COLOR: str = "#EEF4FF"  # สีแถวเมื่อเอาเมาส์ชี้ (ฟ้าอ่อน ช่วยให้ตามอ่านแถวได้ง่าย)
GRID_PAGE_SIZE: int = 15  # จำนวนแถวต่อหน้าของตารางที่เปิด Pagination
GRID_PAGE_SIZE_CHOICES: list[int] = [10, 15, 25, 50, 100]  # ตัวเลือกจำนวนแถวต่อหน้า
GRID_DEFAULT_WIDTH_PX: int = 120  # ความกว้างที่ต้องการของคอลัมน์ที่ไม่ได้ระบุ (ตารางจะปรับตามสัดส่วนให้พอดีจอ)
GRID_FLEXIBLE_WIDTH_PX: int = 200  # ความกว้างที่ต้องการของคอลัมน์ข้อความยาว (เช่น Description) ให้กว้างกว่าคอลัมน์อื่น
# จอแคบย่อคอลัมน์ได้ถึงกี่เท่าของความกว้างที่ต้องการ: คอลัมน์ตัวเลข/วันที่/สถานะย่อได้น้อย (ไม่ให้ตัวเลขถูกตัด)
# ส่วนคอลัมน์ข้อความ (ชื่อผู้ขาย, คำอธิบาย) ย่อได้มาก (ตัดด้วย ... และชี้เมาส์ดูข้อความเต็มได้) ถ้าย่อสุดแล้วยังไม่พอจอ จะมีแถบเลื่อนแนวนอน
GRID_MIN_WIDTH_RATIO_FIXED: float = 0.95
GRID_MIN_WIDTH_RATIO_SHRINKABLE: float = 0.85  # (เดิม 0.6 ชื่อผู้ขายถูกตัดเป็น "Netwo…" เลื่อนแนวนอนดูแทนการตัดข้อความ)
GRID_MIN_WIDTH_FLEXIBLE_PX: int = 80  # ความกว้างต่ำสุดของคอลัมน์ข้อความยาว (Description)
GRID_PAGINATION_HEIGHT_PX: int = 56  # ความสูงแถบเปลี่ยนหน้าด้านล่างตาราง (ใช้คำนวณความสูงตาราง)

# --- Animation แถว: หน้าจอใส่ค่าในคอลัมน์ ROW_FX_COLUMN แล้วตารางเปลี่ยนเป็น class ให้ CSS เล่น animation ---
ROW_FX_COLUMN: str = "row_fx"  # คอลัมน์ (ซ่อน) บอกว่าแถวนี้ต้องเล่น animation อะไร ("" = ไม่เล่น)
ROW_FX_NEW: str = "new"  # แถวที่เพิ่งเพิ่ม: ไฮไลต์เขียวแล้วจางลง
ROW_FX_UPDATED: str = "updated"  # แถวที่เพิ่งแก้ไข/เปลี่ยนสถานะ: ไฮไลต์เหลืองแล้วจางลง
ROW_FX_DELETING: str = "deleting"  # แถวที่กำลังจะลบ: จางหายไปก่อนถูกถอดออกจากตาราง
ROW_FX_DELETE_MS: int = 450  # เวลาที่รอให้ animation ลบเล่นจบก่อนถอดแถวจริง (ms) ต้องไม่น้อยกว่าเวลาใน CSS
ROW_FX_HIGHLIGHT_MS: int = 1600  # ระยะเวลา animation ไฮไลต์แถวใหม่/แถวที่แก้ (ms)
CELL_FLASH_MS: int = 700  # เซลล์ที่ค่าเปลี่ยนจะกะพริบสีนี้นานเท่านี้ (ms)

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

# ตัวกรองเหตุการณ์ที่ให้ตารางส่งค่ากลับไป Python (should_grid_return ของ AgGrid)
# cellClicked ส่งกลับเฉพาะตอนกดคอลัมน์ File: ถ้ากดคอลัมน์สถานะแล้วส่งกลับด้วย หน้าจะรีรันกลางคันและปิด dropdown ที่เพิ่งเปิด
CLICK_ONLY_COLUMN_RETURN_JS: str = """
function(params) {
    if (params.streamlitRerunEventTriggerName !== 'cellClicked') { return true; }
    var colDef = params.eventData && params.eventData.colDef;
    return !!colDef && colDef.field === 'CLICK_COLUMN_ID';
}
"""

GRID_PIN_MIN_WIDTH_PX: int = (
    520  # กล่องตารางกว้างอย่างน้อยเท่านี้และต้องเลื่อนแนวนอน จึงตรึงคอลัมน์แรกไว้ซ้าย (แคบกว่านี้ไม่ตรึง เหลือที่ให้ดูข้อมูลน้อยเกิน)
)
GRID_VERTICAL_SCROLLBAR_RESERVE_PX: int = 17  # เผื่อที่แถบเลื่อนแนวตั้งของตาราง เวลาแบ่งพื้นที่ให้คอลัมน์ข้อความยาว
GRID_SCROLLBAR_HEIGHT_PX: int = 12  # ความหนาแถบเลื่อนแนวนอน (ตารางต้องเผื่อความสูงส่วนนี้)
GRID_PAGING_NARROW_PX: int = 720  # กล่องตารางแคบกว่านี้ = ย่อแถบ Pagination (ลดฟอนต์ ซ่อนคำ "Size:"/"Page" และปุ่มหน้าแรก/สุดท้าย)
GRID_PAGING_TINY_PX: int = 460  # แคบกว่านี้อีก = ซ่อนข้อความสรุปจำนวนแถว "1 - 9 / 9" เหลือแต่ตัวเลือก/ปุ่มเปลี่ยนหน้า
GRID_PAGING_FONT_NARROW_PX: int = 14  # ขนาดตัวหนังสือแถบ Pagination ตอนจอแคบ
# ข้อความสั้นลงของแถบ Pagination: "1 to 9 of 9" -> "1 - 9 / 9", "Page 1 of 1" -> "Page 1 / 1"
GRID_LOCALE_TEXT: dict[str, str] = {"to": "-", "of": "/"}

GRID_REVEAL_SETTLE_MS: int = 350  # หลังฟอนต์พร้อม รอให้เลย์เอาต์นิ่งแล้วจัดคอลัมน์รอบสุดท้ายก่อนเปิดตาราง
GRID_REVEAL_FALLBACK_MS: int = 1800  # เปิดตารางเองเมื่อครบเวลานี้ แม้โค้ดจัดคอลัมน์ไม่ทำงาน (กันตารางค้างหาย)

# จัดคอลัมน์ใหม่ทุกครั้งที่กล่องตารางเปลี่ยนขนาด (เปิด/พับเมนู ย่อ-ขยายหน้าต่าง หมุนจอ)
# autoSizeStrategy ทำงานแค่ตอนสร้างตาราง จึงไม่ปรับตามขนาดที่เปลี่ยนทีหลัง คอลัมน์จะค้างกว้างเกินแล้วล้นจอ
# - คอลัมน์ทั่วไป: กว้างตามเนื้อหาจริง (ตัวเลข/วันที่/สถานะไม่ถูกตัด)
# - คอลัมน์ข้อความยาว (Description / Vendor): รับพื้นที่ที่เหลือของกล่อง และตัดบรรทัด (ไม่ขยายตามความยาวข้อความ) จึงไม่ล้นจอ
# - ถ้าจอแคบจนคอลัมน์ข้อความยาวถึงความกว้างต่ำสุดแล้วยังไม่พอ = เลื่อนแนวนอนดูที่เหลือ + ตรึงคอลัมน์แรกของข้อมูลไว้ซ้าย
_FIT_COLUMNS_BODY_JS: str = (
    """
function fitColumns(api, force) {
    var wrapper = document.querySelector('.ag-root-wrapper');
    var boxWidth = wrapper ? wrapper.clientWidth - 2 : 0;
    if (!boxWidth) { return; }
    // กล่องกว้างเท่าเดิม (เช่น เปลี่ยนแค่ความสูง/แถบเลื่อนแนวตั้งโผล่) = ไม่จัดคอลัมน์ใหม่ ความกว้างต้องคงที่
    if (wrapper.__lastFitWidth === boxWidth && wrapper.__fitDone && !force) { return; }
    wrapper.__lastFitWidth = boxWidth;
    wrapper.__fitDone = true;
    // สลับ class ตามความกว้างกล่อง ให้ CSS ย่อแถบ Pagination (ดู GRID_CUSTOM_CSS)
    wrapper.classList.toggle('grid-narrow', boxWidth < __PAGING_NARROW_PX__);
    wrapper.classList.toggle('grid-tiny', boxWidth < __PAGING_TINY_PX__);
    var wrapIds = __WRAP_IDS__;
    var columns = api.getAllDisplayedColumns().filter(function(column) {
        return column.getColId().indexOf('ag-Grid') !== 0;
    });
    if (!columns.length) { return; }
    var wrapColumns = columns.filter(function(column) { return wrapIds.indexOf(column.getColId()) >= 0; });
    var fixedColumns = columns.filter(function(column) { return wrapIds.indexOf(column.getColId()) < 0; });
    // ขั้นแรก: ทุกคอลัมน์กว้างตามเนื้อหาจริง (ข้อความไม่ถูกตัด) ถ้าทั้งหมดพอดีกล่องก็จบแค่นี้ ไม่ต้องตัดบรรทัด
    api.autoSizeAllColumns();
    // คอลัมน์ข้อความยาว: autoSize วัดความกว้างบรรทัดเดียวไม่ได้ (เซลล์ตัดบรรทัด) จึงวัดข้อความเองด้วย canvas แล้วตั้งเป็นความกว้างตามเนื้อหา
    if (wrapColumns.length) {
        var ctx = document.createElement('canvas').getContext('2d');
        ctx.font = '__FONT_SIZE__px ' + window.getComputedStyle(wrapper).fontFamily;
        var measured = {};
        api.forEachNode(function(node) {
            wrapColumns.forEach(function(column) {
                var text = node.data ? node.data[column.getColId()] : '';
                if (text === null || text === undefined) { return; }
                var width = ctx.measureText(String(text)).width;
                if (width > (measured[column.getColId()] || 0)) { measured[column.getColId()] = width; }
            });
        });
        api.applyColumnState({state: wrapColumns.map(function(column) {
            var natural = Math.ceil((measured[column.getColId()] || 0) + 2 * __CELL_PADDING__ + 6);
            return {colId: column.getColId(), width: Math.max(natural, column.getActualWidth(), column.getMinWidth())};
        })});
    }
    var fixedWidth = 0;
    var wrapNatural = 0;
    api.getAllDisplayedColumns().forEach(function(column) {
        if (wrapIds.indexOf(column.getColId()) < 0) { fixedWidth += column.getActualWidth(); }
        else { wrapNatural += column.getActualWidth(); }
    });
    // ขั้นสอง: ไม่พอ = คอลัมน์ทั่วไปคงกว้างตามเนื้อหา คอลัมน์ข้อความยาวแบ่งพื้นที่ที่เหลือตามสัดส่วนความยาวข้อความ (เผื่อแถบเลื่อนแนวตั้ง)
    // และตัดบรรทัดแทน ไม่ต่ำกว่าความกว้างต่ำสุด
    var available = boxWidth - fixedWidth - __SCROLLBAR_RESERVE__;
    if (wrapColumns.length && fixedWidth + wrapNatural > boxWidth) {
        api.applyColumnState({state: wrapColumns.map(function(column) {
            var share = Math.floor(available * column.getActualWidth() / wrapNatural);
            return {colId: column.getColId(), width: Math.max(share, __WRAP_MIN__, column.getMinWidth())};
        })});
    }
    var totalWidth = 0;
    api.getAllDisplayedColumns().forEach(function(column) { totalWidth += column.getActualWidth(); });
    var needsScroll = totalWidth > boxWidth;
    if (!needsScroll && wrapColumns.length) {
        // เหลือที่ว่าง: แบ่งให้คอลัมน์ข้อความยาวตามสัดส่วน (คอลัมน์ทั่วไปไม่ถูกยืด) ไม่มีคอลัมน์ข้อความยาวก็ยืดทุกคอลัมน์ให้เต็มกล่อง
        var slack = boxWidth - totalWidth - 2;
        api.applyColumnState({state: wrapColumns.map(function(column) {
            return {colId: column.getColId(), width: column.getActualWidth() + Math.floor(slack / wrapColumns.length)};
        })});
    } else if (!needsScroll) { api.sizeColumnsToFit(); }
    var shouldPin = needsScroll && boxWidth >= __PIN_MIN_WIDTH__;
    var firstColumn = columns[0];
    var isPinned = firstColumn.getPinned() === 'left';
    if (shouldPin !== isPinned) {
        api.applyColumnState({state: [{colId: firstColumn.getColId(), pinned: shouldPin ? 'left' : null}]});
    }
}
""".replace("__PIN_MIN_WIDTH__", str(GRID_PIN_MIN_WIDTH_PX))
    .replace("__PAGING_NARROW_PX__", str(GRID_PAGING_NARROW_PX))
    .replace("__PAGING_TINY_PX__", str(GRID_PAGING_TINY_PX))
    .replace("__SCROLLBAR_RESERVE__", str(GRID_VERTICAL_SCROLLBAR_RESERVE_PX))
    .replace("__WRAP_MIN__", str(GRID_MIN_WIDTH_FLEXIBLE_PX))
    .replace("__CELL_PADDING__", str(GRID_CELL_PADDING_PX))
    .replace("__FONT_SIZE__", str(GRID_FONT_SIZE_PX))
)


def build_fit_columns_js(wrap_column_ids: list[str]) -> tuple[str, str]:
    """สร้างโค้ด JS จัดคอลัมน์ให้พอดีกล่อง โดยระบุคอลัมน์ข้อความยาวที่ให้ตัดบรรทัดและรับพื้นที่ที่เหลือ

    Args:
        wrap_column_ids: ชื่อคอลัมน์ข้อความยาว (เช่น description, vendor)

    Returns:
        (โค้ดตอนกล่องเปลี่ยนขนาด, โค้ดตอนแสดงข้อมูลครั้งแรก)
        ครั้งแรกจัดทันที แล้วจัดซ้ำหลังฟอนต์โหลดเสร็จ (ก่อนฟอนต์โหลด วัดความกว้างข้อความแคบกว่าจริง)
    """
    body = _FIT_COLUMNS_BODY_JS.replace("__WRAP_IDS__", json.dumps(wrap_column_ids))
    # กันตารางค้างซ่อน: ถ้าโค้ดจัดคอลัมน์ครั้งแรกไม่ทำงาน (เช่น ไม่มีข้อมูล) ให้เปิดตารางเองหลังครบเวลา (onGridSizeChanged ยิงตอนสร้างตารางเสมอ)
    reveal_fallback = (
        "\n    var fallbackWrapper = document.querySelector('.ag-root-wrapper');"
        "\n    if (fallbackWrapper && !fallbackWrapper.__revealTimer) {"
        " fallbackWrapper.__revealTimer = setTimeout(function() { fallbackWrapper.classList.add('grid-ready'); }, __REVEAL_FALLBACK_MS__); }"
    ).replace("__REVEAL_FALLBACK_MS__", str(GRID_REVEAL_FALLBACK_MS))
    on_resize = body.replace(
        "function fitColumns(api, force) {",
        "function(params) {\n    var api = params.api;\n    var force = false;" + reveal_fallback,
        1,
    )
    # ครั้งแรก/หลังฟอนต์โหลดต้องจัดจริงเสมอ (force) ส่วนตอนกล่องเปลี่ยนขนาดจัดเฉพาะเมื่อความกว้างกล่องเปลี่ยน
    # ตารางถูกซ่อนไว้ (ดู GRID_CUSTOM_CSS) จนจัดคอลัมน์ครบทุกรอบ + ฟอนต์พร้อม แล้วค่อยเปิดทีเดียว ผู้ใช้จึงไม่เห็นคอลัมน์ขยับ
    on_first_render = (
        "function(params) {\n    var api = params.api;\n    var run = (" + body.strip() + ");\n"
        "    var reveal = function() {\n"
        "        run(api, true);\n"
        "        var revealWrapper = document.querySelector('.ag-root-wrapper');\n"
        "        if (revealWrapper) { revealWrapper.classList.add('grid-ready'); }\n"
        "    };\n"
        "    run(api, true);\n"
        "    var fontsReady = (document.fonts && document.fonts.ready) ? document.fonts.ready : Promise.resolve();\n"
        "    fontsReady.then(function() { setTimeout(reveal, __REVEAL_SETTLE_MS__); });\n}"
    ).replace("__REVEAL_SETTLE_MS__", str(GRID_REVEAL_SETTLE_MS))
    return on_resize, on_first_render


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
        headerFontWeight=GRID_HEADER_FONT_WEIGHT,  # หัวตารางตัวหนา
        headerBackgroundColor=GRID_HEADER_BACKGROUND,  # สีพื้นหัวตาราง
        headerTextColor=PALETTE["text"],  # สีตัวหนังสือหัวตาราง
        foregroundColor=GRID_TEXT_COLOR,  # สีตัวหนังสือในเซลล์
        oddRowBackgroundColor=GRID_ZEBRA_COLOR,  # สีแถวสลับ
        rowHoverColor=GRID_ROW_HOVER_COLOR,  # สีแถวตอนเมาส์ชี้
        cellHorizontalPadding=GRID_CELL_PADDING_PX,  # ช่องไฟซ้าย-ขวาในเซลล์
        borderColor=GRID_BORDER_COLOR,  # สีเส้นขอบ
        wrapperBorderRadius=12,  # มุมมนของกรอบตาราง
    )


# CSS เสริมในตาราง (ใส่ผ่าน custom_css ของ AgGrid) ใช้ปรับส่วนที่ธีมไม่ครอบคลุม
# ตัวอย่าง: ขนาดตัวหนังสือแถบเปลี่ยนหน้า (Pagination) และช่องกรอก Filter
GRID_CUSTOM_CSS: dict[str, dict[str, str]] = {
    # ตารางอยู่ใน iframe แยก จึงไม่ได้รับฟอนต์จากหน้าหลัก ต้อง @import ฟอนต์ซ้ำที่นี่
    # (ไลบรารีประกอบ CSS เป็น "ชื่อ { คุณสมบัติ }" จึงใส่ @import ไว้หน้าชื่อ selector แรก ต้องอยู่บนสุดของ dict)
    f"@import url('{GOOGLE_FONTS_URL}'); .ag-root-wrapper": {
        "-webkit-font-smoothing": "antialiased",  # ตัวหนังสือคมชัด เนียน
        "text-rendering": "optimizeLegibility",
    },
    # ซ่อนตารางจนจัดคอลัมน์เสร็จ (JS เติม class grid-ready) แล้วค่อยโผล่ทีเดียว: ไม่เห็นคอลัมน์ไหลไปมา/ไอคอนวาบ
    # ช่วงซ่อนปิด transition/animation ทุกอย่างในตาราง คอลัมน์จะปรับความกว้างทันทีโดยไม่เคลื่อนไหวให้เห็น
    ".ag-root-wrapper": {"opacity": "0"},
    ".ag-root-wrapper:not(.grid-ready), .ag-root-wrapper:not(.grid-ready) *": {
        "transition": "none !important",
        "animation": "none !important",
    },
    ".ag-root-wrapper.grid-ready": {"opacity": "1", "transition": "opacity 0.25s ease"},
    ".ag-header-cell-text": {
        "font-size": f"{GRID_HEADER_FONT_SIZE_PX}px !important",
        "font-weight": f"{GRID_HEADER_FONT_WEIGHT} !important",
        "letter-spacing": "0.01em",
    },
    # แถบ Pagination ด้านล่าง: ไม่ตกบรรทัด ความสูงคงที่ตรงกับ GRID_PAGINATION_HEIGHT_PX
    ".ag-paging-panel": {
        "font-size": f"{GRID_FONT_SIZE_PX}px !important",
        "height": f"{GRID_PAGINATION_HEIGHT_PX}px !important",
        "min-height": f"{GRID_PAGINATION_HEIGHT_PX}px !important",
        "flex-wrap": "nowrap !important",
        "white-space": "nowrap !important",
        "overflow": "hidden",
    },
    ".ag-paging-panel > *, .ag-paging-row-summary-panel, .ag-paging-page-summary-panel, .ag-paging-page-size": {
        "white-space": "nowrap !important",
        "flex-shrink": "0",
    },
    # จอแคบ (class grid-narrow/grid-tiny สลับโดย FIT_COLUMNS_*_JS ตามความกว้างกล่องจริง)
    ".grid-narrow .ag-paging-panel": {
        "font-size": f"{GRID_PAGING_FONT_NARROW_PX}px !important",
        "gap": "4px !important",
        "padding": "0 6px !important",
        "justify-content": "space-between !important",
    },
    ".grid-narrow .ag-paging-page-size .ag-label, .grid-narrow .ag-paging-page-summary-panel .ag-paging-description > span:first-child, "
    ".grid-narrow .ag-paging-button[ref='btFirst'], .grid-narrow .ag-paging-button[ref='btLast'], "
    ".grid-narrow [data-ref='btFirst'], .grid-narrow [data-ref='btLast']": {"display": "none !important"},
    ".grid-narrow .ag-paging-row-summary-panel, .grid-narrow .ag-paging-page-summary-panel": {"margin": "0 !important"},
    ".grid-tiny .ag-paging-row-summary-panel": {"display": "none !important"},
    ".ag-cell": {"line-height": f"{TABLE_ROW_HEIGHT_PX - 2}px !important"},  # จัดตัวหนังสือกึ่งกลางแถวสูง
    # คอลัมน์ข้อความยาว (Description / Vendor): ตัดบรรทัดได้ 2 บรรทัดในแถวสูงเท่าเดิม (2 x 26px < ความสูงแถว)
    ".ag-cell.grid-wrap-cell": {
        "white-space": "normal !important",
        "line-height": "26px !important",
        "display": "flex",
        "align-items": "center",
        "word-break": "break-word",
    },
    ".ag-cell.grid-wrap-cell .ag-cell-wrapper": {
        "display": "flex",
        "align-items": "center",
        "height": f"{TABLE_ROW_HEIGHT_PX - 2}px",
        "width": "100%",
    },
    # ยาวเกิน 2 บรรทัด: ตัดท้ายด้วย … (ไม่ให้ตัวอักษรครึ่งบรรทัดโผล่ล้นแถว)
    ".ag-cell.grid-wrap-cell .ag-cell-value": {
        "display": "-webkit-box !important",
        "-webkit-line-clamp": "2",
        "-webkit-box-orient": "vertical",
        "overflow": "hidden",
        "max-height": "52px",
        "height": "auto !important",
        "line-height": "26px !important",
    },
    # ปุ่มกรองที่หัวคอลัมน์ซ่อนไว้ จนกว่าจะเอาเมาส์ชี้ (ประหยัดที่ให้คอลัมน์ไม่ถูกตัด)
    ".ag-header-cell:not(:hover) .ag-header-cell-filter-button": {"display": "none !important"},
    # เซลล์สถานะตอนกด/แก้ไข: ไม่มีพื้นขาวและกรอบฟ้า เห็นแค่ป้ายสี (ตัวเลือกอยู่ใน popup ที่ pages_ui/overview.py)
    '.ag-cell[col-id="invoice_status"].ag-cell-focus, .ag-cell[col-id="invoice_status"].ag-cell-editing, .ag-cell[col-id="invoice_status"].ag-cell-inline-editing': {
        "background-color": "transparent !important",
        "border": "1px solid transparent !important",
        "box-shadow": "none !important",
        "outline": "none !important",
    },
    # แถบเลื่อนแนวนอนหนาและเห็นชัด (จอแคบต้องเลื่อนดูคอลัมน์ที่เหลือ) เลื่อนด้วยนิ้วบนมือถือไม่ดันหน้าเว็บ
    ".ag-body-horizontal-scroll-viewport, .ag-center-cols-viewport": {"overscroll-behavior-x": "contain"},
    ".ag-body-horizontal-scroll-viewport::-webkit-scrollbar, .ag-center-cols-viewport::-webkit-scrollbar": {
        "height": f"{GRID_SCROLLBAR_HEIGHT_PX}px",
    },
    ".ag-body-horizontal-scroll-viewport::-webkit-scrollbar-thumb, .ag-center-cols-viewport::-webkit-scrollbar-thumb": {
        "background": "#94A3B8",
        "border-radius": "6px",
    },
    ".ag-popup, .ag-menu, .ag-filter": {"font-size": f"{GRID_FONT_SIZE_PX}px !important"},  # เมนู Filter / dropdown
    # --- Animation แถว (เพิ่ม / แก้ไข / ลบ) ---
    # ไลบรารีประกอบ CSS เป็น "ชื่อ { คุณสมบัติ }" ไม่รองรับ @keyframes/@media ตรง ๆ จึงใส่ at-rule ไว้หน้า selector ตัวสุดท้าย (เทคนิคเดียวกับ @import ด้านบน)
    # ไฮไลต์ไม่ระบุสี "to" จึงจางกลับเป็นสีพื้นของแถว (แถวสลับสีก็ถูกต้อง)
    f"@keyframes rowFxNew {{ from {{ background-color: #BBF7D0; }} }} "
    # แถวที่แก้: สีเหลืองไล่ขึ้นนุ่ม ๆ ใน ~0.15 วินาทีแล้วจางลง (ไม่วาบขึ้นทันที)
    f"@keyframes rowFxUpdated {{ 0% {{ background-color: rgba(253, 230, 138, 0); }} 10% {{ background-color: #FDE68A; }} }} "
    "@keyframes rowFxDelete { to { opacity: 0; background-color: #FECACA; } } "
    ".ag-fx-keyframes": {"display": "none"},
    ".ag-row.row-fx-new": {"animation": f"rowFxNew {ROW_FX_HIGHLIGHT_MS}ms ease-out"},
    ".ag-row.row-fx-updated": {"animation": f"rowFxUpdated {ROW_FX_HIGHLIGHT_MS}ms ease-out"},
    ".ag-row.row-fx-deleting": {"animation": f"rowFxDelete {ROW_FX_DELETE_MS - 50}ms ease-in forwards"},
    # ผู้ใช้ปิดแอนิเมชันในระบบปฏิบัติการ (prefers-reduced-motion) = ไม่เล่นเอฟเฟกต์
    "@media (prefers-reduced-motion: reduce) { .ag-row.row-fx-new, .ag-row.row-fx-updated, .ag-row.row-fx-deleting "
    "{ animation: none !important; } .ag-cell-data-changed, .ag-cell-data-changed-animation { transition: none !important; } } "
    ".ag-fx-reduced-motion": {"display": "none"},
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
    row_id_column: Optional[str] = None,
    row_fx_column: Optional[str] = None,
) -> dict[str, Any]:
    """สร้าง gridOptions ของ AgGrid: ขยายคอลัมน์ให้พอดีหน้าจอ + เรียงลำดับ + (ตัวกรอง / Pagination / เลือกแถว) ตามที่ขอ

    Args:
        table: ตารางที่จะแสดง (ชื่อคอลัมน์ = field)
        header_names: {ชื่อคอลัมน์: หัวคอลัมน์ที่แสดง} ถ้าไม่ระบุใช้ชื่อคอลัมน์
        column_widths: {ชื่อคอลัมน์: ความกว้างที่ต้องการ px} ตารางจะย่อ/ขยายทุกคอลัมน์ตามสัดส่วนให้พอดีหน้าจอ
            (จอแคบ = ย่อได้ตามอัตรา GRID_MIN_WIDTH_RATIO_* แล้วข้อความยาวจะถูกตัดด้วย ... ไม่มี tooltip ตอนชี้เมาส์)
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
        row_id_column: คอลัมน์ที่ค่าไม่ซ้ำกันทุกแถว ใช้เป็น id ของแถว (None = ให้ AgGrid สร้างเอง และเตือนใน Console)
            ควรเป็น id จริงของข้อมูล (ไม่ใช่ลำดับแถว) เพื่อให้ข้อมูลเปลี่ยนแล้วตารางเพิ่ม/ลบ/แก้เฉพาะแถวนั้นโดยไม่ต้องวาดใหม่ทั้งตาราง
        row_fx_column: คอลัมน์ที่บอก animation ของแถว (ROW_FX_*) ใส่ class row-fx-xxx ให้แถวตามค่าในคอลัมน์นี้ (None = ไม่ใช้)

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
        enableCellChangeFlash=True,  # เซลล์ที่ค่าเปลี่ยนกะพริบสีสั้น ๆ (แก้ไข/เปลี่ยนสถานะ)
    )  # ไม่ตั้ง tooltip ให้เซลล์ (ชี้เมาส์แล้วไม่มีกล่องข้อความลอย) ถ้าอยากให้กลับมา เพิ่ม tooltipValueGetter ตรงนี้

    wrap_column_ids: list[str] = []  # คอลัมน์ข้อความยาวที่ตัดบรรทัดและรับพื้นที่ที่เหลือ (ส่งให้ JS จัดคอลัมน์)
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
        if is_flexible_text or column in shrinkable_columns:
            # ข้อความยาวตัดขึ้นบรรทัดใหม่ในแถวสูงเท่าเดิม (ไม่ล้นจอ ไม่ต้องเลื่อนแนวนอน) ดู .grid-wrap-cell ใน GRID_CUSTOM_CSS
            column_options.update({"wrapText": True, "cellClass": "grid-wrap-cell"})
            wrap_column_ids.append(column)
        if column in editable_columns:
            column_options["editable"] = True
        if column in money_columns:
            column_options.update({"type": ["numericColumn"], "valueFormatter": JsCode(MONEY_FORMATTER_JS)})
        if column in date_columns:
            column_options["valueFormatter"] = JsCode(DATE_FORMATTER_JS)
        column_options.update(extra_column_options.get(column, {}))
        builder.configure_column(column, **column_options)

    if selectable:
        # ติ๊กเลือกหลายแถวด้วยช่อง checkbox (คลิกที่แถวเฉย ๆ ไม่เลือก กันกดผิดตอนจะแก้ไขค่า)
        # ใช้รูปแบบ rowSelection ของ AG Grid รุ่นใหม่ (configure_selection ของไลบรารีไม่สร้างช่อง checkbox ให้)
        builder.configure_grid_options(
            rowSelection={
                "mode": "multiRow",
                "checkboxes": True,
                "headerCheckbox": True,
                "enableClickSelection": False,
            },
            selectionColumnDef={"width": 44, "minWidth": 44, "maxWidth": 44, "pinned": "left"},
        )
    if paginated:
        builder.configure_pagination(enabled=True, paginationAutoPageSize=False, paginationPageSize=GRID_PAGE_SIZE)
        builder.configure_grid_options(paginationPageSizeSelector=GRID_PAGE_SIZE_CHOICES, localeText=GRID_LOCALE_TEXT)

    # autoSizeStrategy=fitGridWidth: ขยาย/หดคอลัมน์ให้พอดีความกว้างหน้าจอ ไม่มีแถบเลื่อนแนวนอน
    fit_on_resize_js, fit_on_first_render_js = build_fit_columns_js(wrap_column_ids)
    builder.configure_grid_options(
        autoSizeStrategy={"type": "fitGridWidth"},
        onGridSizeChanged=JsCode(fit_on_resize_js),  # จัดคอลัมน์ใหม่เมื่อกล่องเปลี่ยนขนาด
        onFirstDataRendered=JsCode(fit_on_first_render_js),  # จัดคอลัมน์ตอนแสดงข้อมูลครั้งแรก + หลังฟอนต์โหลด
        animateRows=True,  # แถวเลื่อน/แทรก/หายแบบเคลื่อนไหว
        cellFlashDuration=CELL_FLASH_MS,
        cellFadeDuration=CELL_FLASH_MS,
        suppressMovableColumns=True,
        enableCellTextSelection=True,  # ลากคลุมข้อความในเซลล์เพื่อคัดลอกได้
        singleClickEdit=False,  # ดับเบิลคลิกเพื่อแก้ไข กันแก้ไขโดยไม่ตั้งใจ
        stopEditingWhenCellsLoseFocus=True,  # คลิกที่อื่นแล้วถือว่ายืนยันค่าที่พิมพ์
    )
    if row_fx_column:
        # ใส่ class ตามค่าในคอลัมน์ row_fx (ประเมินใหม่ทุกครั้งที่ข้อมูลแถวเปลี่ยน; CSS อยู่ใน GRID_CUSTOM_CSS)
        fx_rules = {
            f"row-fx-{fx}": JsCode(
                f"function(params) {{ return !!params.data && params.data[{json.dumps(row_fx_column)}] === {json.dumps(fx)}; }}"
            )
            for fx in (ROW_FX_NEW, ROW_FX_UPDATED, ROW_FX_DELETING)
        }
        builder.configure_grid_options(rowClassRules=fx_rules)
        # ผู้ใช้แก้เซลล์แล้วไฮไลต์แถวทันทีที่ฝั่งเบราว์เซอร์ ไม่รอเซิร์ฟเวอร์ตอบกลับ (เดิมไฮไลต์วาบขึ้นช้ากว่าการเปลี่ยนค่าราวครึ่งวินาที)
        # ค่าเดียวกับที่เซิร์ฟเวอร์ส่งมาทีหลัง class จึงไม่ถูกถอดแล้วใส่ใหม่ (ไม่เล่น animation ซ้ำ) คอลัมน์ row_fx ไม่อยู่ในคอลัมน์ที่แก้ได้ จึงไม่ถูกนับเป็นการแก้ข้อมูล
        builder.configure_grid_options(
            onCellValueChanged=JsCode(
                "function(params) {"
                f" const fxColumn = {json.dumps(row_fx_column)};"
                " if (!params.node || !params.data || params.colDef.field === fxColumn) return;"
                f" if (params.data[fxColumn] !== {json.dumps(ROW_FX_NEW)} && params.data[fxColumn] !== {json.dumps(ROW_FX_DELETING)})"
                f" params.node.setDataValue(fxColumn, {json.dumps(ROW_FX_UPDATED)});"
                " }"
            )
        )
    if row_id_column:
        # id ของแถวต้องเป็นข้อความ และคงที่แม้ข้อมูลถูกโหลดใหม่ (เลือกแถว/ตำแหน่งเลื่อนจึงไม่หลุด)
        builder.configure_grid_options(
            getRowId=JsCode(f"function(params) {{ return String(params.data[{json.dumps(row_id_column)}]); }}")
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
    # ตารางแบ่งหน้าสูงคงที่เท่าหนึ่งหน้าเต็มเสมอ: ลบ/เพิ่มแถวแล้วกรอบตารางต้องไม่หด/ขยาย
    visible_rows = GRID_PAGE_SIZE if is_paginated else max(1, row_count)
    pagination_height = GRID_PAGINATION_HEIGHT_PX if is_paginated else 0
    # +4 = เส้นขอบ, + แถบเลื่อนแนวนอน (ขึ้นเมื่อจอแคบ ไม่ให้ทับแถวสุดท้าย)
    return GRID_HEADER_HEIGHT_PX + visible_rows * TABLE_ROW_HEIGHT_PX + pagination_height + 4 + GRID_SCROLLBAR_HEIGHT_PX


def show_grid(
    table: pd.DataFrame,
    grid_options: dict[str, Any],
    key: str,
    *,
    update_on: Optional[list[str]] = None,
    server_wins: bool = False,
    click_only_column: Optional[str] = None,
) -> Optional[AgGridReturn]:
    """วาดตาราง AgGrid ด้วยธีมกลาง

    Args:
        table: ตารางที่จะแสดง
        grid_options: ได้จาก build_grid_options
        key: key ของตาราง (ต้องไม่ซ้ำในหน้า) เปลี่ยน key = ล้างสถานะการแก้ไข/เลือกแถวเดิม
        update_on: เหตุการณ์ที่ให้ตารางส่งค่ากลับมา (ว่าง = ตารางอ่านอย่างเดียว ไม่ส่งอะไรกลับ)
        server_wins: True = ข้อมูลจากเซิร์ฟเวอร์ทับตารางเสมอแม้ผู้ใช้เคยแก้ในตารางแล้ว (จำเป็นกับตารางแก้ไขได้ที่ใช้ key คงที่
            ไม่งั้นหลังแก้ครั้งแรก ตารางจะเมินข้อมูลใหม่จากเซิร์ฟเวอร์) ใช้คู่กับ getRowId ที่เป็น id จริงเพื่อให้อัปเดตเฉพาะแถวที่เปลี่ยน
        click_only_column: ถ้าระบุ เหตุการณ์ cellClicked จะส่งกลับเฉพาะตอนกดคอลัมน์นี้ (คอลัมน์อื่นกดแล้วไม่รีรัน)

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
            server_sync_strategy="server_wins" if server_wins else "client_wins",
            should_grid_return=(
                JsCode(CLICK_ONLY_COLUMN_RETURN_JS.replace("CLICK_COLUMN_ID", click_only_column))
                if click_only_column
                else None
            ),
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
    # key คงที่: ข้อมูลเปลี่ยน (เช่น เปลี่ยน Date Filter) ตารางอัปเดตข้อมูลในตัวเดิม ไม่วาดใหม่ทั้งกล่อง (ตารางนี้อ่านอย่างเดียว
    # ไม่เคยถูกแก้ในหน้าจอ จึงรับข้อมูลใหม่จากเซิร์ฟเวอร์เสมอ)
    show_grid(table, grid_options, key)
