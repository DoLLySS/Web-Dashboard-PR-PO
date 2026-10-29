"""ธีมกลางของระบบ (Enterprise Data Dashboard): ฟอนต์ สี ความมน เงา + CSS ที่ครอบทั้งแอป

หลักการ:
- ค่าสี/ฟอนต์/ความมนทั้งหมดอยู่ใน "ค่าคงที่" ด้านบนไฟล์นี้ที่เดียว (PALETTE, RADIUS_PX ฯลฯ)
  ไฟล์อื่น (sidebar_ui.py, ui_common.py) ดึงค่าจากที่นี่ จึงเปลี่ยนธีมทั้งระบบได้จากไฟล์เดียว
- CSS ด้านล่างใช้ตัวแปร var(--app-...) ไม่ฝังรหัสสีตรง ๆ
- เรียก inject_global_styles() ครั้งเดียวใน app.py (ต้นการทำงานทุกรอบ)
- รองรับ Responsive 4 ช่วงจอ (Mobile / Tablet / Laptop / Desktop) ผ่านตัวแปร CSS ที่เปลี่ยนค่าตามขนาดจอ
  ดูค่าของแต่ละช่วงจอที่ RESPONSIVE_VARIABLES

หมายเหตุเรื่องตัวเลือก CSS:
- ใช้ [data-testid="..."] แทนคลาสอย่าง .css-1d391kg เพราะคลาสแบบ css-xxxx / st-emotion-cache-xxxx
  เป็นรหัสที่ Streamlit สุ่มสร้างและเปลี่ยนทุกเวอร์ชัน ส่วน data-testid คงที่กว่ามาก
- ถ้าอัปเกรด Streamlit แล้วสไตล์ตรงไหนหลุด ให้เปิด DevTools (F12) ดู data-testid ของ element นั้นแล้วแก้ที่นี่
"""

from functools import lru_cache

import streamlit as st

# ---------------------------------------------------------------------------
# ค่าคงที่: ฟอนต์
# ---------------------------------------------------------------------------

# ฟอนต์หลักของระบบ: Inter สำหรับอังกฤษ/ตัวเลข (ตัวเลขเรียงเท่ากัน อ่านง่าย) + Sarabun สำหรับไทย (ออกแบบมาเพื่ออ่านข้อความ ไม่มีหัวกลม)
# ถ้าเครื่องไม่มีอินเทอร์เน็ต จะตกไปใช้ sans-serif ของระบบอัตโนมัติ
# อยากเปลี่ยนเป็น Prompt: แก้ชื่อ Sarabun -> Prompt ทั้งใน FONT_FAMILY และ GOOGLE_FONTS_URL (ต้องตรงกัน)
FONT_FAMILY: str = "'Inter', 'Sarabun', sans-serif"
GOOGLE_FONTS_URL: str = (
    "https://fonts.googleapis.com/css2?"
    "family=Inter:wght@400;500;600;700;800&family=Sarabun:wght@400;500;600;700;800&family=Prompt:wght@500;600;700&display=swap"
)

# ขนาดตัวอักษรของทั้งแอป (px) แก้ตัวเลขที่นี่ที่เดียว แล้วทุกหน้าจะเปลี่ยนตาม (ใช้ผ่านตัวแปร CSS --app-fs-<ชื่อ>)
# ถ้าจะเพิ่มระดับขนาดใหม่ ให้เพิ่มคีย์ที่นี่ แล้วเรียก var(--app-fs-<ชื่อ>) ใน GLOBAL_CSS_RULES
TYPOGRAPHY_PX: dict[str, int] = {
    "body": 16,  # ข้อความทั่วไป
    "caption": 14,  # คำอธิบายตัวเล็ก
    "label": 16,  # ป้ายชื่อช่อง
    "input": 16,  # ข้อความในช่องกรอก/กล่องเลือก
    "button": 16,  # ข้อความบนปุ่ม
    "menu": 16,  # เมนูนำทางใน Sidebar
}

# ความสูงของแถวในตาราง (px) ใช้กับตาราง AgGrid ทุกตัวผ่านธีมใน ui_grid.py
# ยิ่งสูงยิ่งโปร่ง แก้ที่นี่ที่เดียวแล้วทุกตารางเปลี่ยนตาม
TABLE_ROW_HEIGHT_PX: int = 58

# ---------------------------------------------------------------------------
# ค่าคงที่: สี (Color Palette) รหัส HEX
# ---------------------------------------------------------------------------

PALETTE: dict[str, str] = {
    "bg": "#F8FAFC",  # พื้นหลังหลักของแอป (Tertiary)
    "surface": "#FFFFFF",  # พื้นหลัง Sidebar และ Card/กล่องข้อมูล
    "text": "#1E293B",  # สีตัวหนังสือหลัก (Primary)
    "text-muted": "#64748B",  # สีตัวหนังสือรอง (คำอธิบาย, หัวกลุ่ม)
    "primary": "#2563EB",  # สีปุ่มหลัก / ลิงก์ / ไฮไลท์ (Secondary)
    "primary-hover": "#1D4ED8",  # สีปุ่มหลักตอนเอาเมาส์ชี้ (เข้มขึ้น)
    "primary-soft": "#DBEAFE",  # สีฟ้าอ่อน ใช้ไฮไลท์เมนูที่ Active / hover
    "border": "#E2E8F0",  # สีเส้นขอบบาง ๆ ของช่องกรอก/การ์ด/ตาราง
    "table-header": "#F1F5F9",  # สีพื้นหัวตาราง
}

# ---------------------------------------------------------------------------
# ค่าคงที่: ความมน และเงา
# ---------------------------------------------------------------------------

RADIUS_PX: int = 8  # ความมนของ Card / ช่องกรอก / ปุ่ม / ตาราง
# เงาบาง ๆ ให้ Card ลอยขึ้นมา
SHADOW: str = "0 1px 3px rgba(0, 0, 0, 0.1)"

# ---------------------------------------------------------------------------
# ค่าคงที่: Responsive (Breakpoint และขนาดที่เปลี่ยนตามช่วงจอ)
# ---------------------------------------------------------------------------

# ขอบเขตความกว้างจอ (px) ของแต่ละช่วง
MOBILE_MAX_PX: int = 767  # Mobile: 0 - 767
TABLET_MIN_PX: int = 768  # iPad/Tablet: 768 - 1024
TABLET_MAX_PX: int = 1024
DESKTOP_MIN_PX: int = 1025  # Desktop/Laptop: 1025 ขึ้นไป (เนื้อหากว้างสูงสุด CONTENT_MAX_PX)
LARGE_DESKTOP_MIN_PX: int = 1440  # Large Desktop: 1440 ขึ้นไป (ช่องไฟโปร่งขึ้น)
CONTENT_MAX_PX: int = 1200  # ความกว้างสูงสุดของเนื้อหาบน Desktop (แนะนำ 1140 - 1200px)
MENU_GUTTER_MIN_PX: int = 1280  # จอตั้งแต่ค่านี้ขึ้นไปมีช่องว่างข้างเนื้อหาพอวางปุ่ม ☰ (ตอนเมนูพับ) ไว้นอกกรอบเนื้อหา
MENU_BUTTON_PX: int = 44  # ขนาดปุ่ม ☰ (ต้องตรงกับ width/height ในข้อ 10)
MENU_BUTTON_GAP_PX: int = 12  # ระยะเว้นระหว่างปุ่ม ☰ กับเนื้อหา
LARGE_CONTENT_MAX_PX: int = 2200  # ความกว้างสูงสุดของเนื้อหาบน Large Desktop (1440px ขึ้นไป ขยายตามจอจนถึงค่านี้)

# ตัวแปรที่เปลี่ยนค่าตามช่วงจอ
#   ค่าของ "desktop" คือค่าเริ่มต้นของทุกช่วง (ใช้ clamp ให้ไหลต่อเนื่องจาก 320px ถึง 1200px จึงไม่กระโดดที่ขอบช่วง)
#   "mobile" / "tablet" / "large" ระบุเฉพาะตัวแปรที่ต่างออกไป
#   heading-scale    : ตัวคูณขนาดหัวข้อ h1/h2/h3 (0.8 = เล็กลง 20%)
#   card-padding     : ระยะห่างภายในการ์ด/ฟอร์ม
#   inner-padding    : ระยะห่างภายในกล่องด้านใน
#   card-title       : ขนาดตัวอักษรหัวข้อใหญ่ในการ์ด ("กรอกข้อมูล")
#   metric-value     : ขนาดตัวเลขสรุปยอดรวม
#   main-padding-x   : ระยะห่างซ้าย-ขวาของพื้นที่เนื้อหาหลัก
#   main-padding-top : ระยะห่างด้านบนของพื้นที่เนื้อหาหลัก
#   container-max    : ความกว้างสูงสุดของเนื้อหาหลัก (none = เต็มพื้นที่)
#   block-gap        : ช่องไฟระหว่างกล่องแนวตั้งในพื้นที่เนื้อหาหลัก
RESPONSIVE_VARIABLES: dict[str, dict[str, str]] = {
    "desktop": {
        "heading-scale": "1",
        # ไหลต่อเนื่อง: ค่าต่ำสุดที่จอ 320px → ค่าสูงสุดที่จอ 1200px (สูตร = ความชัน * vw + ค่าตั้งต้น)
        "card-padding": "clamp(16px, 1.82vw + 10.2px, 32px)",
        "inner-padding": "clamp(12px, 0.91vw + 9.1px, 20px)",
        "card-title": "clamp(22px, 0.91vw + 19.1px, 30px)",
        "metric-value": "clamp(24px, 1.14vw + 20.4px, 34px)",
        "main-padding-x": "clamp(0.75rem, 4.09vw - 1px, 3rem)",
        "main-padding-top": "2.5rem",
        "container-max": f"{CONTENT_MAX_PX}px",
        "block-gap": "1.5rem",  # ช่องไฟระหว่างการ์ด
    },
    "mobile": {
        "heading-scale": "0.8",  # หัวข้อเล็กลง 20% ไม่ให้ล้นจอ
        "main-padding-top": "1.25rem",  # ปุ่ม ☰ ลอยอยู่ขวาบนแล้ว ไม่ต้องเว้นที่ด้านบนฝั่งซ้าย
    },
    "tablet": {
        "heading-scale": "0.9",  # ขนาดปานกลาง
    },
    "large": {
        # Large Desktop (>= 1440px): เนื้อหาขยายตามความกว้างจอแบบไหลต่อเนื่อง (ค่าเริ่มต้นที่ 1440px เท่ากับค่าสูงสุดของ desktop จึงไม่กระโดด)
        # container-max: 84vw แต่ไม่ต่ำกว่า CONTENT_MAX_PX และไม่เกิน LARGE_CONTENT_MAX_PX (กันบรรทัดยาวเกินบนจอ ultrawide)
        "container-max": f"clamp({CONTENT_MAX_PX}px, 84vw, {LARGE_CONTENT_MAX_PX}px)",
        "card-padding": "clamp(32px, 0.9vw + 19px, 44px)",
        "inner-padding": "clamp(20px, 0.4vw + 14.2px, 28px)",
        "card-title": "clamp(30px, 0.5vw + 22.8px, 38px)",
        "metric-value": "clamp(34px, 0.8vw + 22.5px, 46px)",
        "block-gap": "2rem",  # Large Desktop: ช่องไฟโปร่งขึ้น
    },
}

# ---------------------------------------------------------------------------
# CSS (RADIUS ในข้อความด้านล่างจะถูกแทนด้วยค่า RADIUS_PX ตอนประกอบ)
# ---------------------------------------------------------------------------

GLOBAL_CSS_RULES: str = """
/* ===== 1) ฟอนต์: ใช้ Inter + Sarabun ทั้งระบบ + ทำให้ตัวหนังสือคมชัด (Anti-aliased) ===== */
html, body, .stApp {
    -webkit-font-smoothing: antialiased;  /* ขอบตัวอักษรเนียนบน Chrome/Safari/Mac */
    -moz-osx-font-smoothing: grayscale;   /* เช่นเดียวกันบน Firefox (Mac) */
    text-rendering: optimizeLegibility;
}
html, body, .stApp, [data-testid="stApp"],
.stApp button, .stApp input, .stApp textarea, .stApp select,
.stApp p, .stApp label, .stApp h1, .stApp h2, .stApp h3, .stApp h4, .stApp li, .stApp td, .stApp th {
    font-family: var(--app-font) !important;
}
/* ไอคอน (Material Icons) ต้องใช้ฟอนต์ไอคอนของมันเอง ไม่งั้นจะแสดงเป็นตัวหนังสือ เช่น "upload" */
[data-testid="stIconMaterial"] {
    font-family: "Material Symbols Rounded", "Material Symbols Outlined" !important;
}

/* ===== 2) พื้นหลังแอป + สีตัวหนังสือหลัก ===== */
.stApp, [data-testid="stApp"] {
    background: var(--app-bg);
    color: var(--app-text);
}
[data-testid="stHeader"] { background: transparent; }  /* แถบบนสุดโปร่งใส กลืนกับพื้นหลัง */
.stApp h1, .stApp h2, .stApp h3, .stApp h4,
[data-testid="stMarkdownContainer"], [data-testid="stWidgetLabel"] {
    color: var(--app-text);
}
[data-testid="stCaptionContainer"] { color: var(--app-text-muted); }  /* ข้อความอธิบายตัวเล็ก */

/* ===== 3) Sidebar: พื้นขาว มีเงา ไม่มีเส้นขอบทึบเดิม ===== */
[data-testid="stSidebar"] {
    background: transparent;
    border-right: none;  /* ปิดเส้นขอบทึบด้านขวาของ Sidebar แบบเดิม */
}
[data-testid="stSidebarContent"] {
    background: var(--app-surface);
    box-shadow: var(--app-shadow);
}

/* ===== 4) Card / กล่องข้อมูลของ Streamlit: พื้นขาว ขอบมน เงาบาง ===== */
[data-testid="stExpander"], [data-testid="stForm"], [data-testid="stMetric"] {
    background: var(--app-surface);
    border: 1px solid var(--app-border);
    border-radius: RADIUS;
}
[data-testid="stExpander"] { box-shadow: var(--app-shadow); }
[data-testid="stAlert"] { border-radius: RADIUS; }  /* กล่องแจ้งเตือน (warning/info/error) */

/* ===== 5) ช่องกรอกข้อมูล (Input): พื้นขาว เส้นขอบบาง มุม 8px และเน้นสีฟ้าตอนคลิก ===== */
[data-testid="stTextInputRootElement"],
[data-testid="stNumberInputContainer"],
[data-testid="stDateInputField"],
[data-testid="stSelectbox"] [role="group"],
[data-testid="stTextArea"] > div > div {
    background: var(--app-surface);
    border: 1px solid var(--app-border);
    border-radius: RADIUS;
    box-shadow: none;
}
[data-testid="stTextInputRootElement"]:focus-within,
[data-testid="stNumberInputContainer"]:focus-within,
[data-testid="stDateInputField"]:focus-within,
[data-testid="stSelectbox"] [role="group"]:focus-within {
    border-color: var(--app-primary);
    box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.15);  /* วงเรืองสีฟ้าอ่อนรอบช่องที่กำลังพิมพ์ */
}
[data-testid="stTextInputRootElement"] input,
[data-testid="stDateInputField"] input { border-radius: RADIUS; }

/* ===== 6) ปุ่มทั้งหมด: มุม 8px ปุ่มหลักเป็นสีฟ้า ปุ่มรองเป็นสีขาวขอบบาง ===== */
[data-testid^="stBaseButton-"] { border-radius: RADIUS; font-weight: 600; transition: all 0.15s ease; }
/* ปุ่มหลัก (Submit / Upload): พื้นฟ้า ตัวอักษรขาว hover เข้มขึ้น */
[data-testid="stBaseButton-primary"],
[data-testid="stBaseButton-primaryFormSubmit"] {
    background: var(--app-primary);
    border: 1px solid var(--app-primary);
    color: #FFFFFF;
}
[data-testid="stBaseButton-primary"]:hover,
[data-testid="stBaseButton-primaryFormSubmit"]:hover {
    background: var(--app-primary-hover);
    border-color: var(--app-primary-hover);
    color: #FFFFFF;
}
/* ปุ่มรอง (เช่น Export, Browse files): พื้นขาว ขอบบาง hover แล้วเป็นสีฟ้า */
[data-testid="stBaseButton-secondary"],
[data-testid="stBaseButton-secondaryFormSubmit"] {
    background: var(--app-surface);
    border: 1px solid var(--app-border);
    color: var(--app-text);
}
[data-testid="stBaseButton-secondary"]:hover,
[data-testid="stBaseButton-secondaryFormSubmit"]:hover {
    border-color: var(--app-primary);
    color: var(--app-primary);
}

/* ข้อความในปุ่มต้องสืบทอดสีจากปุ่ม (ไม่งั้นกฎสีตัวหนังสือข้อ 2 จะทำให้ตัวหนังสือบนปุ่มฟ้ากลายเป็นสีเข้ม) */
[data-testid^="stBaseButton-"] [data-testid="stMarkdownContainer"],
[data-testid^="stBaseButton-"] [data-testid="stMarkdownContainer"] p { color: inherit; }

/* ความกว้างปุ่ม: บนจอใหญ่ปุ่มกว้างพอดีข้อความ (ไม่ขยายเต็มจอ) ยกเว้นปุ่มที่ระบุให้เต็มความกว้างเท่านั้น */
[data-testid="stButton"] button,
[data-testid="stDownloadButton"] button,
[data-testid="stFormSubmitButton"] button {
    width: auto;
    min-width: 7rem;
}
/* ข้อยกเว้น: (1) ปุ่มเมนูใน Sidebar (2) ปุ่มที่ตั้ง key ลงท้ายด้วย _full ให้เต็มความกว้างของที่ว่าง
   (ปุ่มอัปโหลดในฟอร์มก็เต็มความกว้างด้วยกฎของหน้า Overview) */
[class*="st-key-menu_button_"] button,
[class*="st-key-"][class*="_full"] button {
    width: 100%;
}

/* ===== 7) ตารางข้อมูล (st.dataframe / st.table): ขอบมน 8px หัวตารางสี #F1F5F9 ตัวอักษร #1E293B ===== */
[data-testid="stDataFrame"] {
    border: 1px solid var(--app-border);
    border-radius: RADIUS;
    overflow: hidden;  /* ตัดมุมของตารางให้มนตามกรอบ */
}
/* ตารางหลักของแอปใช้ AgGrid (ui_grid.py) ตั้งหน้าตาเองในธีมของตาราง กฎด้านล่างนี้ใช้กับ st.table เท่านั้น */
[data-testid="stTable"] table { border-collapse: separate; border-spacing: 0; border-radius: RADIUS; overflow: hidden; }
[data-testid="stTable"] thead th { background: var(--app-table-header); color: var(--app-text); }
[data-testid="stTable"] td { color: var(--app-text); }

/* ===== 8) ตัวเลขสรุป (st.metric) ===== */
/* KPI Card: พื้นขาว ขอบมน 8px เงาบาง ๆ และ padding ภายใน */
[data-testid="stMetric"] {
    padding: 16px 20px;
    background: #FFFFFF;
    border-radius: 8px;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
}
[data-testid="stMetricLabel"] { color: var(--app-text-muted); }
[data-testid="stMetricValue"] { font-size: var(--app-metric-value); }  /* ขนาดตัวเลขเปลี่ยนตามช่วงจอ กันตัวเลขถูกตัดบนจอแคบ */

/* ===== 9) ขนาดหัวข้อ: อ้างอิงตัวคูณ --app-heading-scale ที่เปลี่ยนตามช่วงจอ (ดู Media Queries ด้านล่าง) ===== */
.stApp h1 { font-size: calc(2.75rem * var(--app-heading-scale)) !important; }
.stApp h2 { font-size: calc(2.25rem * var(--app-heading-scale)) !important; }
.stApp h3 { font-size: calc(1.75rem * var(--app-heading-scale)) !important; }

/* ===== 9.1) Typography: ขยายตัวหนังสือทั้งแอป (แก้ขนาดที่ TYPOGRAPHY_PX ด้านบนไฟล์ ไม่ต้องแก้ตรงนี้) =====
   ไม่สั่ง span ทั้งหมด เพราะจะทำให้ไอคอน Material ของ Streamlit เพี้ยน */
/* ข้อความทั่วไปในเนื้อหาหลักและ Sidebar */
[data-testid="stMainBlockContainer"] [data-testid="stMarkdownContainer"] p,
[data-testid="stMainBlockContainer"] [data-testid="stMarkdownContainer"] li,
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p {
    font-size: var(--app-fs-body);
    line-height: 1.55;
}
/* คำอธิบายตัวเล็ก (caption) และข้อความรองใต้ชื่อหน้า */
[data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] p { font-size: var(--app-fs-caption) !important; }
/* ป้ายชื่อช่อง (Label) และข้อความในช่องกรอก/กล่องเลือก */
[data-testid="stWidgetLabel"] p { font-size: var(--app-fs-label) !important; font-weight: 600; }
[data-testid="stMainBlockContainer"] input,
[data-testid="stMainBlockContainer"] textarea,
[data-testid="stMainBlockContainer"] [data-baseweb="select"] { font-size: var(--app-fs-input) !important; }
/* ปุ่มทุกปุ่มในเนื้อหาหลัก (เช่น เพิ่มข้อมูล / Export) ใหญ่และหนา */
[data-testid="stMainBlockContainer"] [data-testid^="stBaseButton-"],
[data-testid="stMainBlockContainer"] [data-testid^="stBaseButton-"] p { font-size: var(--app-fs-button) !important; font-weight: 700 !important; }
/* หัวข้อกลุ่มใน expander (เช่น "ดูรายการที่ค้าง") */
[data-testid="stExpander"] summary p { font-size: var(--app-fs-body) !important; font-weight: 600; }
/* เมนูนำทางใน Sidebar: ใหญ่ขึ้น (หัวกลุ่ม DASHBOARD ใหญ่ขึ้นเล็กน้อย) */
[class*="st-key-menu_button_"] button p { font-size: var(--app-fs-menu) !important; }
[data-testid="stSidebar"] [data-testid="stExpander"] summary p { font-size: 13px !important; }
/* ชื่อ/คำอธิบายเว็บใน Sidebar */
.sidebar-title { font-size: 19px !important; }
.sidebar-subtitle { font-size: 13px !important; }
/* ตัวเลขสรุป (Metric): ป้ายชื่อใหญ่ขึ้น ตัวเลขหนาเด่น */
[data-testid="stMetricLabel"] p { font-size: var(--app-fs-label) !important; font-weight: 600; }
[data-testid="stMetricValue"] { font-weight: 800; }
/* ตัวเลขใน Metric ต้องสืบทอดขนาดใหญ่จากกล่อง ไม่ถูกกฎข้อความทั่วไป (16px) ทับ */
[data-testid="stMetricValue"] p, [data-testid="stMetricValue"] div { font-size: inherit !important; }
/* ตัวเลขยาว (เช่น 207,800.00) ในการ์ดแคบ: ขึ้นบรรทัดใหม่แทนการถูกตัดเป็น "..." */
[data-testid="stMetricValue"], [data-testid="stMetricValue"] > div { overflow: visible !important; text-overflow: clip !important; white-space: normal !important; overflow-wrap: anywhere; }
/* ตาราง HTML (st.table) ให้ตัวหนังสือในเซลล์ใหญ่ขึ้น */
[data-testid="stTable"] td, [data-testid="stTable"] th { font-size: var(--app-fs-body); padding: 0.6rem 0.75rem; }

/* ===== 10) ซ่อนส่วนเริ่มต้นของ Streamlit ให้ดูเป็น Web App ขององค์กร ===== */
/* เมนูแฮมเบอร์เกอร์ (#MainMenu คือชื่อเดิม, stMainMenu คือชื่อของ Streamlit รุ่นปัจจุบัน) ปุ่ม Deploy และ Footer */
#MainMenu, [data-testid="stMainMenu"], [data-testid="stAppDeployButton"],
[data-testid="stDecoration"],
footer, [data-testid="stFooter"] {
    visibility: hidden;
}
/* หมายเหตุ: ไม่ซ่อนทั้ง Header (header {visibility: hidden}) และไม่ซ่อน stToolbar ทั้งก้อน
   เพราะปุ่มเปิด Sidebar ตอนพับ (stExpandSidebarButton) อยู่ใน stToolbar ถ้าซ่อนจะไม่มีทางเปิดเมนูกลับมา
   จึงซ่อนเฉพาะเมนู/ปุ่ม Deploy/แถบสีด้านบน (ด้านบน) และทำให้ปุ่มเปิด Sidebar เห็นชัดตามด้านล่าง */
[data-testid="stExpandSidebarButton"] {
    visibility: visible;
    background: var(--app-surface);
    border: 1px solid var(--app-border);
    width: 44px;
    height: 44px;
    border-radius: 12px;
    box-shadow: 0 2px 8px rgba(37, 99, 235, 0.15);
    color: var(--app-primary);
    position: relative;
    transition: scale 0.25s cubic-bezier(0.34, 1.56, 0.64, 1),
                box-shadow 0.25s ease, border-color 0.25s ease;
}
/* ซ่อนไอคอนลูกศร » เดิม (เป็นตัวอักษร Material) แล้ววาดไอคอน 3 ขีดแทนด้วย CSS */
[data-testid="stExpandSidebarButton"] span {
    visibility: hidden;
}
[data-testid="stExpandSidebarButton"]::before {
    content: "";
    position: absolute;
    inset: 0;
    margin: auto;
    width: 22px;
    height: 16px;
    background:
        linear-gradient(var(--app-primary), var(--app-primary)) top / 100% 3px no-repeat,
        linear-gradient(var(--app-primary), var(--app-primary)) center / 100% 3px no-repeat,
        linear-gradient(var(--app-primary), var(--app-primary)) bottom / 100% 3px no-repeat;
    border-radius: 3px;
    transition: height 0.25s cubic-bezier(0.34, 1.56, 0.64, 1),
                background-size 0.25s ease;
}
/* ชี้เมาส์: ปุ่มขยาย + เรืองแสงรอบปุ่ม ขีดทั้ง 3 ห่างขึ้นและขีดกลางสั้นลง */
[data-testid="stExpandSidebarButton"]:hover {
    scale: 1.1;
    border-color: var(--app-primary);
    box-shadow: 0 6px 16px rgba(37, 99, 235, 0.3), 0 0 0 4px rgba(37, 99, 235, 0.12);
}
[data-testid="stExpandSidebarButton"]:hover::before {
    height: 20px;
    background-size: 100% 3px, 70% 3px, 100% 3px;
}
/* กด: ปุ่มยุบลงเหมือนถูกกดจริง */
[data-testid="stExpandSidebarButton"]:active {
    scale: 0.92;
    box-shadow: 0 1px 4px rgba(37, 99, 235, 0.2), 0 0 0 2px rgba(37, 99, 235, 0.15);
}
[data-testid="stExpandSidebarButton"]:focus-visible {
    outline: 2px solid var(--app-primary);
    outline-offset: 3px;
}
@media (prefers-reduced-motion: reduce) {
    [data-testid="stExpandSidebarButton"],
    [data-testid="stExpandSidebarButton"]::before { transition: none; }
}

/* หัวข้อทุกระดับใช้ตัวหนาปานกลาง (600) ให้เด่นกว่าเนื้อหาแต่ไม่หนาเกิน */
.stApp h1, .stApp h2, .stApp h3, .stApp h4 { font-weight: 600; }

/* ===== 11) พื้นที่เนื้อหาหลัก: ระยะห่างและความกว้างสูงสุดตามช่วงจอ ===== */
[data-testid="stMainBlockContainer"], .block-container {
    padding-left: var(--app-main-padding-x);
    padding-right: var(--app-main-padding-x);
    padding-top: var(--app-main-padding-top);
    max-width: var(--app-container-max);
    margin-left: auto;
    margin-right: auto;  /* จัดกึ่งกลางเมื่อมีการจำกัดความกว้างสูงสุด (จอใหญ่) */
}
[data-testid="stMainBlockContainer"] > [data-testid="stVerticalBlock"] { gap: var(--app-block-gap); }

/* ===== 11.1) ช่องไฟภายในการ์ด: ให้องค์ประกอบในการ์ด (หัวข้อ ตาราง กราฟ ปุ่ม) ไม่ชิดกันเกินไป ===== */
[class*="st-key-"][class*="_card"] > [data-testid="stVerticalBlock"],
[class*="st-key-"][class*="_inner"] > [data-testid="stVerticalBlock"] { gap: 1rem; }
/* ช่องไฟระหว่างคอลัมน์ซ้าย-ขวา (เช่น ตาราง | ฟอร์ม) */
[data-testid="stMainBlockContainer"] [data-testid="stHorizontalBlock"] { gap: 1.5rem; }
/* หัวหน้าแถบบนสุด: เว้นระยะด้านล่างก่อนถึงเนื้อหา */
.st-key-page_header { margin-bottom: 0.5rem; }
/* ชื่อหน้าชิดบน: ตัด margin/padding เดิมของ st.header ออก ไม่ให้มีที่ว่างเหนือหัวข้อ */
.st-key-page_header h2 { margin: 0; padding: 0; line-height: 1.2; }
.st-key-page_header [data-testid="stCaptionContainer"] { margin-top: 2px; }

/* ===== 11.1.1) หัวข้อหน้า: ตัวใหญ่หนา ไล่สีตัวอักษร มีแท่งสีสั้นใต้หัวข้อ และเลื่อนเข้าตอนโหลดหน้า =====
   แก้ขนาดที่ font-size (หัวข้อ) / กว้าง-สูงของแท่งสีที่ ::after / สีไล่ที่ linear-gradient */
.st-key-page_header h2 {
    position: relative;
    font-size: clamp(1.9rem, 1.4rem + 1.6vw, 2.6rem) !important;
    font-weight: 800 !important;
    letter-spacing: -0.02em;
    padding-bottom: 12px;
    background: linear-gradient(100deg, #0F172A 0%, #1D4ED8 70%, #0D9488 100%);
    -webkit-background-clip: text;
    background-clip: text;
    -webkit-text-fill-color: transparent;
    animation: page-title-in 0.45s cubic-bezier(.2,.8,.2,1) both;
}
.st-key-page_header h2::after {
    content: "";
    position: absolute;
    left: 0; bottom: 0;
    width: 48px; height: 4px;
    border-radius: 999px;
    background: linear-gradient(90deg, #2563EB, #2DD4BF);
    animation: page-title-bar 0.6s 0.15s cubic-bezier(.2,.8,.2,1) both;
}
.st-key-page_header [data-testid="stCaptionContainer"] {
    margin-top: 6px;
    animation: page-title-in 0.45s 0.08s cubic-bezier(.2,.8,.2,1) both;
}
.st-key-page_header [data-testid="stCaptionContainer"] p {
    font-size: 1.05rem !important;
    color: #475569 !important;
    letter-spacing: 0.01em;
}
/* ===== 11.1.0) สลับหน้า (Overview <-> Dashboard) ให้นุ่ม =====
   เนื้อหาหน้าอยู่ใน container key=page_view_<ชื่อหน้า> (app.py) เปลี่ยนหน้า = DOM ใหม่ จึงเล่น fade-in + เลื่อนขึ้นเล็กน้อยครั้งเดียว
   (rerun ปกติเช่นกดปุ่มช่วงเวลา ใช้ DOM เดิม ไม่เล่นซ้ำ) ใช้ opacity/translate เท่านั้น ไม่แตะ transform ของ popover */
[class*="st-key-page_view_"] { animation: page-view-in 0.38s cubic-bezier(.2,.8,.2,1) backwards; }
[class*="st-key-page_view_"] > [data-testid="stVerticalBlock"] { gap: var(--app-block-gap); }
@keyframes page-view-in { from { opacity: 0; translate: 0 12px; } to { opacity: 1; translate: 0 0; } }
/* ตอน rerun Streamlit หรี่ element เก่าลง (stale) ให้ค่อย ๆ หรี่/คืน ไม่วูบ */
[data-testid="stMainBlockContainer"] [data-testid="stElementContainer"],
[data-testid="stMainBlockContainer"] [data-testid="stLayoutWrapper"] { transition: opacity 0.25s ease; }
@keyframes page-title-in { from { opacity: 0; transform: translateY(8px); } to { opacity: 1; transform: none; } }
@keyframes page-title-bar { from { width: 0; } to { width: 48px; } }

/* ===== 11.1.2) Date Filter (วันที่ To วันที่): ช่องแคบพอดีวันที่ ชิดขวา ตอบสนองตอนชี้/คลิก (เฉพาะจอ >= 768px) =====
   ปรับความกว้างช่องที่ width ของ stDateInput (ตอนนี้ 168px) */
@media (min-width: 768px) {
    .st-key-page_header [data-testid="stColumn"] [data-testid="stHorizontalBlock"] {
        flex-wrap: nowrap; justify-content: flex-end; align-items: center; gap: 0.6rem;
    }
    .st-key-page_header [data-testid="stColumn"] [data-testid="stColumn"] {
        flex: 0 0 auto !important; width: auto !important; min-width: 0 !important;
    }
    .st-key-page_header [data-testid="stDateInput"] { width: 272px; }  /* ความกว้างช่องวันที่ */
    .st-key-page_header [data-testid="stDateInput"] [data-baseweb="input"],
    .st-key-page_header [data-testid="stDateInputField"] { min-height: 58px; height: 58px; }
    .st-key-page_header [data-testid="stDateInput"] input { font-size: 20px !important; font-weight: 600; letter-spacing: 0.03em; padding-left: 16px; }
    /* ตัวเลข วัน/เดือน/ปี จริงเป็น span (spinbutton) และตัวคั่น "/" ต้องปรับขนาดที่ตัวเหล่านี้ */
    .st-key-page_header [data-testid="stDateInputField"] [role="group"],
    .st-key-page_header [data-testid="stDateInputField"] [role="group"] span { font-size: 20px; font-weight: 600; line-height: 1.3; }
    .st-key-page_header [data-testid="stDateInputField"] [role="group"] { height: auto; min-height: 0; padding-left: 4px; }
    .st-key-page_header [data-testid="stDateInputField"] [role="spinbutton"] { padding: 2px 3px; }
    .st-key-page_header [data-testid="stDateInputField"] > div { align-items: center; }
    /* กล่องของตัวคั่น To ต้องสูงเท่าแคปซูล ไม่งั้นถูกจัดกลางตามกล่อง 42px แล้วตกลงต่ำกว่าช่องวันที่ */
    .st-key-page_header [data-testid="stElementContainer"]:has(.date-to-chip),
    .st-key-page_header [data-testid="stMarkdown"]:has(.date-to-chip),
    .st-key-page_header [data-testid="stMarkdown"]:has(.date-to-chip) > div { height: auto !important; min-height: 0 !important; }
    .st-key-page_header [data-testid="stDateInput"] svg { width: 30px; height: 30px; }
}
/* Streamlit ใส่ margin-bottom ติดลบให้ markdown ทำให้กล่องหดสั้นกว่าแคปซูล ต้องยกเลิก (ทุกขนาดจอ) */
.st-key-page_header [data-testid="stMarkdownContainer"]:has(.date-to-chip) { margin-bottom: 0 !important; }
.st-key-page_header [data-testid="stElementContainer"]:has(.date-to-chip),
.st-key-page_header [data-testid="stMarkdown"]:has(.date-to-chip),
.st-key-page_header [data-testid="stMarkdown"]:has(.date-to-chip) > div { height: auto !important; min-height: 0 !important; }
.st-key-page_header [data-testid="stDateInputField"] {
    background: #FFFFFF; border: 1.5px solid #E2E8F0; border-radius: 16px;
    box-shadow: 0 1px 2px rgba(15, 23, 42, 0.06), 0 6px 16px -8px rgba(37, 99, 235, 0.25);
    transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}
/* จัดตัวเลข วัน/เดือน/ปี ให้อยู่กึ่งกลางช่อง (แนวนอนและแนวตั้ง) ส่วนไอคอนอยู่ขวาเหมือนเดิม */
.st-key-page_header [data-testid="stDateInputField"] [role="group"] {
    flex: 1 1 auto; display: flex; align-items: center; justify-content: center;
    padding-left: 0 !important; padding-right: 0 !important;
}
.st-key-page_header [data-testid="stDateInputField"]:hover {
    border-color: #93C5FD;
    box-shadow: 0 8px 20px -8px rgba(37, 99, 235, 0.45);
    transform: translateY(-1px);
}
.st-key-page_header [data-testid="stDateInputField"]:focus-within {
    transform: translateY(-1px); border-color: #2563EB;
    box-shadow: 0 0 0 4px rgba(37, 99, 235, 0.15), 0 8px 20px -8px rgba(37, 99, 235, 0.45);
}
.st-key-page_header [data-testid="stDateInput"] svg { transition: transform 0.2s ease, color 0.2s ease; }
.st-key-page_header [data-testid="stDateInput"]:hover svg { transform: scale(1.12) rotate(-4deg); }
/* ตัวคั่น "To": แคปซูลไล่สีฟ้า-ม่วง ตัวขาว สูงเท่ากล่องวันที่ มุมโค้งเท่ากัน (สมมาตร) */
.date-to-chip {
    display: inline-flex; align-items: center; justify-content: center;
    width: 44px; height: 44px; border-radius: 14px;
    background: linear-gradient(135deg, #2563EB, #7C3AED); color: #FFFFFF;
    font-size: 12px; font-weight: 700; letter-spacing: 0.02em;
    box-shadow: 0 6px 14px -4px rgba(79, 70, 229, 0.55);
}
@media (min-width: 768px) { .date-to-chip { width: 64px; height: 58px; border-radius: 16px; font-size: 16px; } }
/* จอ 768-1279px พื้นที่ฝั่งขวาแคบ: ย่อช่องลงเล็กน้อยไม่ให้ทับคำอธิบายหน้า (To สูงเท่ากล่องเสมอ) */
@media (min-width: 768px) and (max-width: 1279px) {
    .st-key-page_header [data-testid="stDateInput"] { width: 188px; }
    .st-key-page_header [data-testid="stDateInput"] [data-baseweb="input"],
    .st-key-page_header [data-testid="stDateInputField"] { min-height: 50px; height: 50px; }
    .st-key-page_header [data-testid="stDateInput"] input { font-size: 17px !important; padding-left: 10px; }
    .st-key-page_header [data-testid="stDateInputField"] [role="group"],
    .st-key-page_header [data-testid="stDateInputField"] [role="group"] span { font-size: 17px; }
    .st-key-page_header [data-testid="stDateInput"] svg { width: 24px; height: 24px; }
    .date-to-chip { width: 44px; height: 50px; font-size: 15px; border-radius: 14px; }
}
/* ===== 11.1.3) ปฏิทินเลือกวันที่ (ใช้กับ date_input ทุกช่องในแอป) =====
   - ขนาดคงที่ทุกเดือน: กว้าง 300px และสูงเท่ากับเดือนที่มี 6 สัปดาห์ (เดือน 5 สัปดาห์จะเหลือที่ว่างด้านล่างแทนที่จะหดตัว)
   - เซลล์วันกลม 36px, วันที่เลือกเป็นสีไล่ฟ้า, วันของเดือนอื่นจาง
   - เปิดปฏิทินแล้วเด้งนุ่ม (ใช้ opacity/transform เท่านั้น ไม่กระทบตำแหน่ง popover)
   ปรับความกว้างที่ width / ความสูงขั้นต่ำที่ min-height ของ role="application" */
[data-testid="stDateInputCalendar"] {
    width: 320px; max-width: calc(100vw - 16px); box-sizing: border-box;
    border-radius: 14px; overflow: hidden;
    box-shadow: 0 4px 6px rgba(15, 23, 42, 0.05), 0 18px 40px -8px rgba(37, 99, 235, 0.28) !important;
    transform-origin: top left;
    animation: calendar-pop-in 0.18s cubic-bezier(.2,.8,.2,1) both;
}
[data-testid="stDateInputCalendar"] [role="application"] { width: 100%; min-height: 336px; box-sizing: border-box; }
[data-testid="stDateInputCalendar"] table[role="grid"] { width: 100%; table-layout: fixed; }
[data-testid="stDateInputCalendar"] th { font-size: 12px; font-weight: 700; color: #64748B; text-align: center; padding: 6px 0; }
[data-testid="stDateInputCalendar"] td { height: 44px !important; padding: 2px 0 !important; text-align: center; }
[data-testid="stDateInputCalendar"] td > [role="button"] {
    width: 40px !important; height: 40px !important; margin: 0 auto; border-radius: 50% !important;
    display: flex; align-items: center; justify-content: center;
    font-size: 15px; font-weight: 500; cursor: pointer;
    transition: background-color 0.15s ease, color 0.15s ease, transform 0.15s ease, box-shadow 0.15s ease;
}
[data-testid="stDateInputCalendar"] td > [role="button"]:hover:not([data-selected="true"]):not([data-disabled="true"]) {
    background: #DBEAFE !important; color: #1D4ED8; transform: scale(1.08);
}
[data-testid="stDateInputCalendar"] td > [data-selected="true"] {
    background: linear-gradient(135deg, #2563EB, #0EA5E9) !important; color: #FFFFFF !important; font-weight: 700;
    box-shadow: 0 6px 14px -4px rgba(37, 99, 235, 0.6);
}
[data-testid="stDateInputCalendar"] td > [data-outside-month="true"] { opacity: 0.35; }
/* ใช้ translate/scale แยก ไม่แตะ transform เพราะ popover ใช้ transform จัดตำแหน่งอยู่ */
@keyframes calendar-pop-in { from { opacity: 0; translate: 0 -8px; scale: 0.97; } to { opacity: 1; translate: 0 0; scale: 1; } }

/* ไอคอนปฏิทินในช่องวันที่: เส้นมน ไล่สีฟ้า-เขียวอมฟ้า (ซ่อนเส้นของไอคอนเดิมแล้ววาดใหม่ด้วย mask) ยังกดเปิดปฏิทินได้เหมือนเดิม */
[data-testid="stDateInput"] svg path { display: none; }
[data-testid="stDateInput"] svg {
    width: 22px; height: 22px;
    background: linear-gradient(135deg, #2563EB, #0D9488);
    -webkit-mask: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'%3E%3Crect x='3.5' y='5' width='17' height='15.5' rx='3.5'/%3E%3Cpath d='M3.5 10h17M8 3v4M16 3v4'/%3E%3Ccircle cx='8.5' cy='14.5' r='0.8' fill='black'/%3E%3Ccircle cx='12' cy='14.5' r='0.8' fill='black'/%3E%3Ccircle cx='15.5' cy='14.5' r='0.8' fill='black'/%3E%3C/svg%3E") center / contain no-repeat;
    mask: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 24 24' fill='none' stroke='black' stroke-width='1.8' stroke-linecap='round' stroke-linejoin='round'%3E%3Crect x='3.5' y='5' width='17' height='15.5' rx='3.5'/%3E%3Cpath d='M3.5 10h17M8 3v4M16 3v4'/%3E%3Ccircle cx='8.5' cy='14.5' r='0.8' fill='black'/%3E%3Ccircle cx='12' cy='14.5' r='0.8' fill='black'/%3E%3Ccircle cx='15.5' cy='14.5' r='0.8' fill='black'/%3E%3C/svg%3E") center / contain no-repeat;
}
@media (prefers-reduced-motion: reduce) {
    [data-testid="stDateInputCalendar"], [data-testid="stDateInputCalendar"] td > [role="button"] { animation: none; transition: none; }
}
@media (prefers-reduced-motion: reduce) {
    [class*="st-key-page_view_"] { animation: none; }
    [data-testid="stMainBlockContainer"] [data-testid="stElementContainer"],
    [data-testid="stMainBlockContainer"] [data-testid="stLayoutWrapper"] { transition: none; }
}
@media (prefers-reduced-motion: reduce) {
    .st-key-page_header h2,.st-key-page_header h2::after, .st-key-page_header [data-testid="stCaptionContainer"] { animation: none; }
    .st-key-page_header [data-testid="stDateInputField"], .st-key-page_header [data-testid="stDateInput"] svg { transition: none; transform: none !important; }
}

/* กล่องสคริปต์พับ Sidebar อัตโนมัติ (sidebar_ui.py) ไม่มีเนื้อหาที่มองเห็น ไม่ให้กินช่องว่างในหน้า */
.st-key-sidebar_collapse_script,
[data-testid="stLayoutWrapper"]:has(> .st-key-sidebar_collapse_script) { display: none; }

/* ===== 11.2) ตารางข้อมูล (st.dataframe / data_editor): พื้นขาว เงาบาง ๆ เหมือน Card ===== */
[data-testid="stDataFrame"], [data-testid="stDataFrameResizable"] {
    background: var(--app-surface);
    box-shadow: var(--app-shadow);
    border-radius: RADIUS;
}
/* กล่องอัปโหลดไฟล์ + ช่องข้อมูลอื่นที่เป็นกล่อง: มุม 8px เหมือนกัน */
[data-testid="stFileUploaderDropzone"] { border-radius: RADIUS; }
"""


# ---------------------------------------------------------------------------
# ฟังก์ชัน
# ---------------------------------------------------------------------------


def build_responsive_css() -> str:
    """สร้าง Media Queries ของแต่ละช่วงจอ (เปลี่ยนค่าตัวแปร CSS + กฎเฉพาะช่วงจอ)

    Returns:
        ข้อความ CSS ของ @media (Mobile, Tablet, Large Desktop; Desktop ใช้ค่าใน :root)
    """

    def variables_block(breakpoint_name: str) -> str:
        """แปลง dict ค่าของช่วงจอเป็นข้อความตัวแปร CSS เช่น --app-card-padding: 10px;"""
        return "\n".join(f"    --app-{name}: {value};" for name, value in RESPONSIVE_VARIABLES[breakpoint_name].items())

    return f"""
/* ===== 12) Responsive: Mobile (กว้างไม่เกิน {MOBILE_MAX_PX}px) ===== */
@media (max-width: {MOBILE_MAX_PX}px) {{
  :root {{
{variables_block("mobile")}
  }}
  /* ตารางเลื่อนซ้าย-ขวาด้วยนิ้วได้ โดยไม่ทำให้ Layout ของทั้งหน้าพัง */
  [data-testid="stDataFrame"], [data-testid="stTable"] {{
    overflow-x: auto;
    overflow-y: hidden;
    -webkit-overflow-scrolling: touch;  /* ให้ปัดลื่นบน iOS */
  }}
  /* ปุ่มเต็มความกว้างบนมือถือ เพื่อให้กดด้วยนิ้วง่าย */
  [data-testid="stButton"], [data-testid="stDownloadButton"], [data-testid="stFormSubmitButton"],
  [data-testid="stButton"] button, [data-testid="stDownloadButton"] button,
  [data-testid="stFormSubmitButton"] button {{ width: 100%; }}
  .st-key-dashboard_export [data-testid="stDownloadButton"] {{ justify-content: stretch; }}
  .st-key-page_header [data-testid="stColumn"]:has(.header-spacer) {{ display: none; }}  /* ซ่อนคอลัมน์ว่างของแถบหัว */

  /* ทุกแถวคอลัมน์ในเนื้อหาหลักเรียงต่อกันแนวตั้ง (Streamlit ทำเองที่ < 640px เราครอบคลุมถึง 767px ด้วย) */
  [data-testid="stMainBlockContainer"] [data-testid="stHorizontalBlock"] {{ flex-wrap: wrap; gap: 0.75rem; }}
  [data-testid="stMainBlockContainer"] [data-testid="stColumn"] {{ min-width: 100%; flex-basis: 100%; }}
  /* คอลัมน์ว่างตัวดันปุ่มชิดขอบ (กึ่งกลางของแถบปุ่มใต้ตัวกรอง) ไม่จำเป็นเมื่อเรียงแนวตั้ง */
  .st-key-table_action_bar > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:not(:has([data-testid="stButton"], [data-testid="stDownloadButton"])) {{ display: none; }}

  .st-key-table_action_bar.st-key-table_action_bar > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {{
    min-width: 0; max-width: 100%; flex: 1 1 100%;  /* คอลัมน์เต็มแถวแต่ไม่เกินความกว้างของแถบ (กัน padding ดันล้น) */
  }}
  /* แถบปุ่ม Export บนมือถือ: CSV กับ Excel แบ่งครึ่งความกว้างเท่ากัน ปุ่มเต็มช่อง ไม่ล้นขอบจอ (class ซ้อนสองชั้นเพื่อให้ชนะกฎของหน้า) */
  .st-key-table_action_bar.st-key-table_action_bar [data-testid="stColumn"] [data-testid="stHorizontalBlock"] {{ flex-wrap: nowrap; width: 100%; }}
  .st-key-table_action_bar.st-key-table_action_bar [data-testid="stColumn"] [data-testid="stColumn"] {{ flex: 1 1 0; min-width: 0; }}
  .st-key-table_action_bar.st-key-table_action_bar [data-testid="stColumn"] [data-testid="stColumn"] [data-testid="stDownloadButton"],
  .st-key-table_action_bar.st-key-table_action_bar [data-testid="stColumn"] [data-testid="stColumn"] button {{ width: 100%; padding-left: 8px; padding-right: 8px; }}

  /* Popup: กว้างเกือบเต็มจอ ช่องฟอร์มเรียงแนวตั้ง ปุ่ม "บันทึก" ขึ้นก่อน "ย้อนกลับ" (กดง่ายด้วยนิ้วโป้ง) */
  div[data-testid="stDialog"] div[role="dialog"] {{ width: calc(100vw - 1rem); max-width: calc(100vw - 1rem); }}
  div[data-testid="stDialog"] [data-testid="stHorizontalBlock"] {{ flex-wrap: wrap; gap: 0.5rem; }}
  div[data-testid="stDialog"] [data-testid="stColumn"] {{ min-width: 100%; flex-basis: 100%; }}
  div[data-testid="stDialog"] [data-testid="stHorizontalBlock"]:has([data-testid="stFormSubmitButton"]) {{
    flex-direction: column-reverse;
  }}
  div[data-testid="stDialog"] [data-testid="stHorizontalBlock"]:has([data-testid="stFormSubmitButton"]) > [data-testid="stColumn"]:nth-child(2) {{
    display: none;  /* ช่องว่างกลางแถวปุ่ม */
  }}

  /* ปุ่ม/ช่องกรอกสูงพอสำหรับนิ้ว (>= 44px) และฟอนต์ช่องกรอก >= 16px กัน iOS ซูมหน้าเองตอนแตะ */
  button, [data-baseweb="select"] > div, [data-baseweb="input"] {{ min-height: 44px; }}
  input, textarea {{ font-size: 16px !important; }}

  /* Date Filter (วันที่เริ่ม · To · วันที่สิ้นสุด) บนมือถือ: เรียงแถวเดียว ช่องเล็กลง ประหยัดพื้นที่
     (ใส่ไว้หลังกฎ "คอลัมน์เต็มแถว" ด้านบน และใช้ class ซ้อนสองชั้นให้ชนะกฎนั้น) */
  .st-key-page_header.st-key-page_header [data-testid="stColumn"] [data-testid="stHorizontalBlock"] {{
    flex-wrap: nowrap; gap: 0.4rem; align-items: center;
  }}
  .st-key-page_header.st-key-page_header [data-testid="stColumn"] [data-testid="stColumn"] {{
    flex: 1 1 0; min-width: 0; width: auto;
  }}
  .st-key-page_header.st-key-page_header [data-testid="stColumn"] [data-testid="stColumn"]:nth-child(2) {{
    flex: 0 0 auto;  /* คอลัมน์ "To" กว้างเท่าแคปซูล */
  }}
  .date-to-chip {{ width: 36px; height: 44px; font-size: 12px; border-radius: 12px; }}
  .st-key-page_header [data-testid="stDateInput"] [data-baseweb="input"],
  .st-key-page_header [data-testid="stDateInputField"] {{ min-height: 44px; height: 44px; }}
  .st-key-page_header [data-testid="stDateInput"] input {{ font-size: 15px !important; padding-left: 10px; padding-right: 4px; }}
  .st-key-page_header [data-testid="stDateInputField"] [role="group"],
  .st-key-page_header [data-testid="stDateInputField"] [role="group"] span {{ font-size: 15px; font-weight: 600; }}
  .st-key-page_header [data-testid="stDateInput"] svg {{ width: 20px; height: 20px; }}

  /* Menu อยู่ฝั่งขวาบนมือถือ: สลับลำดับ Sidebar/เนื้อหา, ปุ่ม ☰ ลอยมุมขวาบน, แผงเมนูเลื่อนเข้า-ออกทางขวา */
  [data-testid="stAppViewContainer"] {{ flex-direction: row-reverse; }}
  [data-testid="stSidebar"] {{ padding: 12px 12px 12px 0; }}
  [data-testid="stSidebar"][data-collapsed="true"] {{ transform: translateX(100%) !important; }}
  [data-testid="stSidebar"][data-collapsed="false"] {{ transform: none !important; }}
  [data-testid="stSidebarCollapseButton"] {{ scale: -1 1; }}  /* ลูกศร « กลับเป็น » ชี้ไปทางขวาที่แผงจะเลื่อนกลับ */
  [data-testid="stExpandSidebarButton"] {{ position: fixed; top: calc(var(--app-main-padding-top) - 4px); right: 12px; left: auto; z-index: 999990; }}
  /* กล่องที่มีแต่ <style> (CSS ของหน้า) ไม่มีเนื้อหาที่มองเห็น แต่ถูกนับเป็นบล็อกและเพิ่มช่องไฟด้านบน ซ่อนกล่องแล้วกฎ CSS ยังทำงานเหมือนเดิม */
  [data-testid="stMainBlockContainer"] [data-testid="stElementContainer"]:has(style) {{ display: none; }}
  /* ชื่อหน้าชิดซ้ายบน: ไม่ต้องเว้นที่ให้ปุ่ม ☰ แล้ว แต่กันข้อความยาววิ่งไปทับปุ่มด้านขวา */
  .st-key-page_header h2, .st-key-page_header [data-testid="stCaptionContainer"] {{ padding-right: 56px; }}
}}

/* ===== 12.1) มือถือจอเล็ก (กว้างไม่เกิน 360px เช่น 320px): ย่อช่อง Date ให้เห็นปีครบ ไม่ถูกตัด ===== */
@media (max-width: 360px) {{
  .st-key-page_header [data-testid="stDateInput"] input {{ font-size: 12px !important; padding-left: 6px; padding-right: 2px; }}
  .st-key-page_header [data-testid="stDateInputField"] [role="group"],
  .st-key-page_header [data-testid="stDateInputField"] [role="group"] span {{ font-size: 12px; }}
  .st-key-page_header [data-testid="stDateInput"] svg {{ width: 14px; height: 14px; }}
  .st-key-page_header [data-testid="stDateInput"] [data-baseweb="input"],
  .st-key-page_header [data-testid="stDateInputField"] {{ min-height: 40px; height: 40px; }}
  .date-to-chip {{ width: 26px; height: 40px; font-size: 10px; border-radius: 10px; }}
}}

/* ===== 13) Responsive: iPad/Tablet ({TABLET_MIN_PX}-{TABLET_MAX_PX}px) ===== */
@media (min-width: {TABLET_MIN_PX}px) and (max-width: {TABLET_MAX_PX}px) {{
  :root {{
{variables_block("tablet")}
  }}
  /* กันตารางและกราฟถูกบีบจนอ่านไม่ได้: คอลัมน์ที่มีการ์ดอยู่ต้องกว้างอย่างน้อย 400px
     ถ้าที่ไม่พอ คอลัมน์จะตกลงมาเรียงต่อกันแนวตั้งแทนการบีบ */
  [data-testid="stHorizontalBlock"]:has([class*="st-key-"][class*="_card"]) {{ flex-wrap: wrap; }}
  [data-testid="stColumn"]:has([class*="st-key-"][class*="_card"]) {{
    min-width: min(100%, 400px);
    flex-basis: 400px;
  }}
  [data-testid="stDataFrame"], [data-testid="stPlotlyChart"] {{ min-width: 300px; }}
  /* เมนูข้างแคบลง (240px) ให้เนื้อหาหลักมีพื้นที่มากขึ้นบน iPad
     ใช้เฉพาะตอนเมนูเปิด: ถ้าบังคับกว้าง 240px ตอนพับด้วย จะเกิดช่องว่างผีทางซ้ายดันเนื้อหาไปทางขวา */
  [data-testid="stSidebar"][data-collapsed="false"] {{ width: 240px !important; min-width: 240px !important; }}
  /* แถบหัวหน้า: ถ้าที่ไม่พอ ให้ตัวกรองวันที่ (Date To Date) ตกลงมาบรรทัดล่าง แทนการบีบจนเหลือแค่ตัวเลขวัน
     (เลือกเฉพาะ block ที่มีคอลัมน์ซ้อนอยู่ข้างใน คือแถวหัวหน้า ไม่กระทบคอลัมน์ From/To ด้านใน) */
  .st-key-page_header [data-testid="stHorizontalBlock"]:has([data-testid="stColumn"] [data-testid="stColumn"]) {{
    flex-wrap: wrap;
  }}
  .st-key-page_header [data-testid="stColumn"]:has([data-testid="stColumn"]) {{
    min-width: min(100%, 340px);
    flex-basis: 340px;
  }}
  /* คอลัมน์ว่างตัวดัน Date Filter ไปขวา ไม่จำเป็นบนจอแคบ (ซ่อนไม่ให้กินบรรทัด) */
  .st-key-page_header [data-testid="stColumn"]:has(.header-spacer) {{ display: none; }}

  /* แถบตัวกรองของตาราง: ช่องค้นหาเต็มบรรทัด ส่วน Item/Vendor แบ่งครึ่งบรรทัดถัดไป */
  .st-key-table_card [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] [data-testid="stTextInput"]) {{
    flex-wrap: wrap;
    gap: 0.75rem;
  }}
  .st-key-table_card [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] [data-testid="stTextInput"]) > [data-testid="stColumn"]:first-child {{
    flex-basis: 100%;
    min-width: 100%;
  }}
  .st-key-table_card [data-testid="stHorizontalBlock"]:has(> [data-testid="stColumn"] [data-testid="stTextInput"]) > [data-testid="stColumn"]:not(:first-child) {{
    flex: 1 1 200px;
    min-width: 200px;
  }}
  /* แถบปุ่มใต้ตัวกรอง: ปุ่มลบ | (ช่องว่าง) | Export ถ้าที่ไม่พอให้ตกบรรทัด และซ่อนช่องว่างตัวดัน */
  .st-key-table_action_bar > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] {{ flex-wrap: wrap; }}
  .st-key-table_action_bar > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:not(:has([data-testid="stButton"], [data-testid="stDownloadButton"])) {{ display: none; }}
  .st-key-table_action_bar > [data-testid="stLayoutWrapper"] > [data-testid="stHorizontalBlock"] > [data-testid="stColumn"]:has([data-testid="stButton"], [data-testid="stDownloadButton"]) {{
    flex: 0 0 auto;  /* ปุ่มกว้างตามเนื้อหา ชิดซ้าย/ขวาด้วย space-between ของ PAGE_CSS_RULES ข้อ 1.5 */
  }}
  /* ฟอร์มใน Popup: Tablet ยังคง 2 คอลัมน์ ส่วนปุ่ม ย้อนกลับ/บันทึก ไม่ให้ถูกบีบแคบกว่าความกว้างตัวอักษร */
  div[data-testid="stDialog"] [data-testid="stHorizontalBlock"]:has([data-testid="stFormSubmitButton"]) > [data-testid="stColumn"]:not(:nth-child(2)) {{
    min-width: 140px;
  }}
}}

/* ===== 13.1) Tablet ขึ้นไปตอนเมนูพับ: Streamlit เหลือแถบว่าง 12px ทางซ้าย ลดขอบซ้ายลง 12px ให้ขอบซ้าย-ขวาเท่ากัน ===== */
@media (min-width: {TABLET_MIN_PX}px) {{
  .stApp:has([data-testid="stSidebar"][data-collapsed="true"]) [data-testid="stMainBlockContainer"] {{
    padding-left: calc(var(--app-page-padding-x, var(--app-main-padding-x)) - 12px) !important;  /* หน้าที่จำกัดขอบเองให้ตั้ง --app-page-padding-x */
  }}
}}

/* ===== 13.2) แถบหัวหน้า: ชื่อหน้า (ซ้าย) กับ Date To Date (ขวา) อยู่แถวเดียวกันเสมอ + ลดช่องว่างก่อนเนื้อหาถัดไป =====
   เดิม Streamlit ตัดบรรทัดคอลัมน์ [4,2,4] เมื่อเนื้อหากว้างไม่พอ (เช่น จอ 1440px ตอนเมนูเปิด) Date จึงตกลงบรรทัดล่าง
   ตอนนี้: ชื่อหน้ากินที่ที่เหลือ (ข้อความยาวตัดบรรทัดในคอลัมน์ตัวเอง) / Date กว้างตามเนื้อหาชิดขวา / ซ่อนคอลัมน์ว่าง
   จอ Tablet (768-1024px) ตอนเมนูเปิด เนื้อหาแคบมาก จึงยกเว้นให้ Date ตกบรรทัดล่างได้ (กฎข้อ 13) */
@media (min-width: 1025px) {{
  .st-key-page_header.st-key-page_header [data-testid="stHorizontalBlock"]:has([data-testid="stColumn"] [data-testid="stColumn"]) {{
    flex-wrap: nowrap; align-items: center;
  }}
  .st-key-page_header.st-key-page_header [data-testid="stColumn"]:has(.header-spacer) {{ display: none; }}
  .st-key-page_header.st-key-page_header [data-testid="stHorizontalBlock"]:has([data-testid="stColumn"] [data-testid="stColumn"]) > [data-testid="stColumn"]:first-child {{
    flex: 1 1 0; min-width: 0; width: auto;
  }}
  .st-key-page_header.st-key-page_header [data-testid="stColumn"]:has([data-testid="stColumn"]) {{
    flex: 0 0 auto; width: auto; min-width: max-content;
  }}
}}
@media (min-width: {TABLET_MIN_PX}px) and (max-width: 1024px) {{
  .stApp:has([data-testid="stSidebar"][data-collapsed="true"]) .st-key-page_header.st-key-page_header [data-testid="stHorizontalBlock"]:has([data-testid="stColumn"] [data-testid="stColumn"]) {{
    flex-wrap: nowrap; align-items: center;
  }}
  .stApp:has([data-testid="stSidebar"][data-collapsed="true"]) .st-key-page_header.st-key-page_header [data-testid="stHorizontalBlock"]:has([data-testid="stColumn"] [data-testid="stColumn"]) > [data-testid="stColumn"]:first-child {{
    flex: 1 1 0; min-width: 0; width: auto;
  }}
  .stApp:has([data-testid="stSidebar"][data-collapsed="true"]) .st-key-page_header.st-key-page_header [data-testid="stColumn"]:has([data-testid="stColumn"]) {{
    flex: 0 0 auto; width: auto; min-width: max-content;
  }}
}}
@media (min-width: {TABLET_MIN_PX}px) {{
  /* กล่องที่มีแต่ <style> (CSS ของหน้า) ไม่มีเนื้อหาที่มองเห็น แต่ถูกนับเป็นบล็อกและเพิ่มช่องไฟ 1rem ซ่อนกล่อง (กฎ CSS ยังทำงานเหมือนเดิม) */
  [data-testid="stMainBlockContainer"] [data-testid="stElementContainer"]:has(style) {{ display: none; }}
  .st-key-page_header {{ margin-bottom: -0.25rem; }}  /* ลดช่องว่างระหว่างแถบหัวหน้ากับแถบแจ้งเตือน (ปรับเลขนี้ถ้าต้องการชิด/ห่างขึ้น) */
}}

/* ===== 13.3) ตำแหน่งปุ่มเมนู ☰ ตอนเมนูพับ: อยู่คู่กับเนื้อหา ไม่ลอยโดดเดี่ยวมุมจอ และไม่ทับชื่อหน้า =====
   --app-content-left = ขอบซ้ายของเนื้อหาตอนเมนูพับ (ตรงกับข้อ 13.1)
   Tablet/Laptop เล็ก: ปุ่มอยู่แถวเดียวกับชื่อหน้า แล้วดันชื่อหน้าหนีปุ่ม (วิธีเดียวกับมือถือที่เว้นด้านขวา)
   จอ {MENU_GUTTER_MIN_PX}px ขึ้นไป: ปุ่มอยู่ในช่องว่างซ้ายของเนื้อหา ชิดแนวเดียวกับชื่อหน้า */
@media (min-width: {TABLET_MIN_PX}px) {{
  .stApp:has([data-testid="stSidebar"][data-collapsed="true"]) {{
    --app-content-left: calc(max(0px, (100vw - var(--app-container-max)) / 2) + var(--app-page-padding-x, var(--app-main-padding-x)) - 12px);
  }}
  .stApp:has([data-testid="stSidebar"][data-collapsed="true"]) [data-testid="stExpandSidebarButton"] {{
    position: fixed; z-index: 999990;
    left: var(--app-content-left);
    top: calc(var(--app-main-padding-top) - 4px);
  }}
  .stApp:has([data-testid="stSidebar"][data-collapsed="true"]) .st-key-page_header h2,
  .stApp:has([data-testid="stSidebar"][data-collapsed="true"]) .st-key-page_header [data-testid="stCaptionContainer"] {{
    padding-left: {MENU_BUTTON_PX + MENU_BUTTON_GAP_PX}px;
  }}
}}
@media (min-width: {TABLET_MIN_PX}px) and (max-width: {MENU_GUTTER_MIN_PX - 1}px) {{
  /* เนื้อหาเต็มความกว้าง: แถบว่าง 12px ของ Streamlit ยังอยู่ทางซ้าย จึงบวกกลับให้ปุ่มตรงขอบเนื้อหา */
  .stApp:has([data-testid="stSidebar"][data-collapsed="true"]) {{ --app-content-left: calc(var(--app-page-padding-x, var(--app-main-padding-x))); }}
}}
@media (min-width: {MENU_GUTTER_MIN_PX}px) {{
  .stApp:has([data-testid="stSidebar"][data-collapsed="true"]) [data-testid="stExpandSidebarButton"] {{
    left: max({MENU_BUTTON_GAP_PX}px, calc(var(--app-content-left) - {MENU_BUTTON_PX + MENU_BUTTON_GAP_PX}px));
  }}
  .stApp:has([data-testid="stSidebar"][data-collapsed="true"]) .st-key-page_header h2,
  .stApp:has([data-testid="stSidebar"][data-collapsed="true"]) .st-key-page_header [data-testid="stCaptionContainer"] {{
    padding-left: 0;
  }}
}}

/* ===== 14) Desktop/Laptop ({DESKTOP_MIN_PX}px ขึ้นไป): ใช้ค่าใน :root (เนื้อหากว้างสูงสุด {CONTENT_MAX_PX}px จัดกึ่งกลาง) ไม่ต้องมี Media Query แยก ===== */

/* ===== 15) Responsive: Large Desktop ({LARGE_DESKTOP_MIN_PX}px ขึ้นไป) เนื้อหาขยายตามจอ (ไม่เกิน {LARGE_CONTENT_MAX_PX}px) การ์ด/ตัวเลข/ช่องไฟโตตาม ===== */
@media (min-width: {LARGE_DESKTOP_MIN_PX}px) {{
  :root {{
{variables_block("large")}
  }}
  /* เพิ่มช่องไฟระหว่างคอลัมน์ให้โปร่งขึ้น */
  [data-testid="stMainBlockContainer"] [data-testid="stHorizontalBlock"] {{ gap: 2rem; }}
  /* Streamlit คำนวณความกว้างคอลัมน์โดยเผื่อช่องไฟ 1rem เมื่อช่องไฟใหญ่ขึ้นผลรวมเกินแถว คอลัมน์สุดท้ายจึงตกบรรทัดใหม่
     จอใหญ่มีที่พอเสมอ จึงห้ามตัดบรรทัด (คอลัมน์หดตามสัดส่วนแทน) */
  [data-testid="stMainBlockContainer"] [data-testid="stHorizontalBlock"] {{ flex-wrap: nowrap; }}
  [data-testid="stMainBlockContainer"] [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {{ min-width: 0; }}
  /* หัวข้อหน้าโตต่อจากค่าเดิม (2.6rem ที่ 1440px) ไหลต่อเนื่องจนถึง 3.2rem */
  .st-key-page_header h2 {{ font-size: clamp(2.6rem, 1.52rem + 1.2vw, 3.2rem) !important; }}
}}
"""


@lru_cache(maxsize=1)
def build_global_css() -> str:
    """ประกอบ CSS ทั้งแอป: นำเข้าฟอนต์ + ตัวแปรสี (:root) + กฎ CSS (ประกอบครั้งเดียวต่อโปรเซส เพราะผลเหมือนเดิมทุกรอบ)

    Returns:
        ข้อความ <style>...</style> พร้อมส่งให้ st.markdown(unsafe_allow_html=True)
    """
    # สร้างตัวแปร CSS จาก PALETTE เช่น --app-bg: #F8FAFC;
    css_variables = "\n".join(f"--app-{name}: {value};" for name, value in PALETTE.items())
    css_variables += f"\n--app-font: {FONT_FAMILY};\n--app-shadow: {SHADOW};"
    # ตัวแปรขนาดตัวอักษร เช่น --app-fs-body: 16px;
    css_variables += "\n" + "\n".join(f"--app-fs-{name}: {size}px;" for name, size in TYPOGRAPHY_PX.items())
    # ค่าเริ่มต้นของตัวแปร responsive = ค่าของ Desktop (ช่วงจออื่นจะถูกแทนที่ด้วย Media Query ด้านล่าง)
    css_variables += "\n" + "\n".join(f"--app-{n}: {v};" for n, v in RESPONSIVE_VARIABLES["desktop"].items())
    css_rules = GLOBAL_CSS_RULES.replace("RADIUS", f"{RADIUS_PX}px")
    # @import ต้องอยู่บรรทัดแรกสุดของ <style> เสมอ ไม่เช่นนั้นเบราว์เซอร์จะข้ามไป
    return (
        f"<style>\n@import url('{GOOGLE_FONTS_URL}');\n:root {{\n{css_variables}\n}}\n"
        f"{css_rules}{build_responsive_css()}</style>"
    )


def inject_global_styles() -> None:
    """ฉีด CSS ธีมกลางเข้าหน้าเว็บ (เรียกครั้งเดียวต้น app.py ทุกครั้งที่สคริปต์รัน)"""
    st.markdown(build_global_css(), unsafe_allow_html=True)
