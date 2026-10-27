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
TABLE_ROW_HEIGHT_PX: int = 52

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
LAPTOP_MIN_PX: int = 1025  # Laptop: 1025 - 1440 (ขนาดมาตรฐานที่ออกแบบไว้)
LAPTOP_MAX_PX: int = 1440
DESKTOP_MIN_PX: int = 1441  # Desktop จอใหญ่: 1441 ขึ้นไป

# ตัวแปรที่เปลี่ยนค่าตามช่วงจอ (ค่าใน "laptop" คือค่าเริ่มต้นของทุกช่วง ช่วงอื่นระบุเฉพาะที่ต่างออกไป)
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
    "laptop": {
        "heading-scale": "1",
        "card-padding": "24px",  # โปร่งขึ้นจากเดิม 16px
        "inner-padding": "16px",
        "card-title": "28px",
        "metric-value": "30px",
        "main-padding-x": "5rem",
        "main-padding-top": "2.5rem",
        "container-max": "none",
        "block-gap": "1.5rem",  # ช่องไฟระหว่างการ์ด
    },
    "mobile": {
        "heading-scale": "0.8",  # หัวข้อเล็กลง 20% ไม่ให้ล้นจอ
        "card-padding": "16px",  # ประหยัดพื้นที่แต่ยังไม่อึดอัด
        "inner-padding": "12px",
        "card-title": "22px",
        "metric-value": "24px",
        "main-padding-x": "0.75rem",
        "main-padding-top": "3.5rem",
    },
    "tablet": {
        "heading-scale": "0.9",  # ขนาดปานกลาง
        "card-padding": "20px",
        "inner-padding": "14px",
        "card-title": "25px",
        "metric-value": "27px",
        "main-padding-x": "2rem",
        "main-padding-top": "2.5rem",
    },
    "desktop": {
        "heading-scale": "1",
        "card-padding": "32px",  # โปร่งสบายตาบนจอความละเอียดสูง
        "inner-padding": "20px",
        "card-title": "30px",
        "metric-value": "34px",
        "main-padding-x": "3rem",
        "main-padding-top": "2.5rem",
        "container-max": "1800px",  # ขยายเนื้อหาให้กว้างขึ้น ไม่กระจุกอยู่กลางจอ (แต่ไม่ยืดจนอ่านยากบนจอ 4K)
        "block-gap": "1.5rem",
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
/* ตาราง HTML (st.table) ให้ตัวหนังสือในเซลล์ใหญ่ขึ้น */
[data-testid="stTable"] td, [data-testid="stTable"] th { font-size: var(--app-fs-body); padding: 0.6rem 0.75rem; }

/* ===== 10) ซ่อนส่วนเริ่มต้นของ Streamlit ให้ดูเป็น Web App ขององค์กร ===== */
/* เมนูแฮมเบอร์เกอร์ (#MainMenu คือชื่อเดิม, stMainMenu คือชื่อของ Streamlit รุ่นปัจจุบัน) ปุ่ม Deploy และ Footer */
#MainMenu, [data-testid="stMainMenu"], [data-testid="stAppDeployButton"],
[data-testid="stToolbar"], [data-testid="stDecoration"],
footer, [data-testid="stFooter"] {
    visibility: hidden;
}
/* หมายเหตุ: ไม่ซ่อนทั้ง Header (header {visibility: hidden}) เพราะมีปุ่มเปิด/ปิด Sidebar อยู่ ซึ่งจำเป็นบนมือถือ
   จึงทำให้ Header โปร่งใส (ข้อ 2) และซ่อนเฉพาะเมนู/ปุ่ม Deploy/แถบสีด้านบนแทน */

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
    .st-key-page_header [data-testid="stDateInput"] { width: 168px; }
}
.st-key-page_header [data-testid="stDateInputField"] {
    transition: border-color 0.18s ease, box-shadow 0.18s ease, transform 0.18s ease;
}
.st-key-page_header [data-testid="stDateInputField"]:hover {
    border-color: #93C5FD;
    box-shadow: 0 4px 12px -4px rgba(37, 99, 235, 0.35);
    transform: translateY(-1px);
}
.st-key-page_header [data-testid="stDateInputField"]:focus-within { transform: translateY(-1px); }
.st-key-page_header [data-testid="stDateInput"] svg { transition: transform 0.2s ease, color 0.2s ease; }
.st-key-page_header [data-testid="stDateInputField"]:hover ~ * svg,
.st-key-page_header [data-testid="stDateInput"]:hover svg { transform: scale(1.15); color: var(--app-primary); }
/* ตัวคั่น "To" เป็นแคปซูลเล็ก ๆ สีเทาอ่อน */
.date-to-chip {
    display: inline-block; padding: 2px 10px; border-radius: 999px;
    background: #EEF2FF; color: #4F46E5; font-size: 13px; font-weight: 700; letter-spacing: 0.04em;
    position: relative; top: -7px;  /* ยกให้อยู่กึ่งกลางแนวเดียวกับช่องวันที่ */
}
/* ===== 11.1.3) ปฏิทินเลือกวันที่ (ใช้กับ date_input ทุกช่องในแอป) =====
   - ขนาดคงที่ทุกเดือน: กว้าง 300px และสูงเท่ากับเดือนที่มี 6 สัปดาห์ (เดือน 5 สัปดาห์จะเหลือที่ว่างด้านล่างแทนที่จะหดตัว)
   - เซลล์วันกลม 36px, วันที่เลือกเป็นสีไล่ฟ้า, วันของเดือนอื่นจาง
   - เปิดปฏิทินแล้วเด้งนุ่ม (ใช้ opacity/transform เท่านั้น ไม่กระทบตำแหน่ง popover)
   ปรับความกว้างที่ width / ความสูงขั้นต่ำที่ min-height ของ role="application" */
[data-testid="stDateInputCalendar"] {
    width: 300px; max-width: calc(100vw - 16px); box-sizing: border-box;
    border-radius: 14px; overflow: hidden;
    box-shadow: 0 4px 6px rgba(15, 23, 42, 0.05), 0 18px 40px -8px rgba(37, 99, 235, 0.28) !important;
    transform-origin: top left;
    animation: calendar-pop-in 0.18s cubic-bezier(.2,.8,.2,1) both;
}
[data-testid="stDateInputCalendar"] [role="application"] { width: 100%; min-height: 304px; box-sizing: border-box; }
[data-testid="stDateInputCalendar"] table[role="grid"] { width: 100%; table-layout: fixed; }
[data-testid="stDateInputCalendar"] th { font-size: 12px; font-weight: 700; color: #64748B; text-align: center; padding: 6px 0; }
[data-testid="stDateInputCalendar"] td { height: 40px !important; padding: 2px 0 !important; text-align: center; }
[data-testid="stDateInputCalendar"] td > [role="button"] {
    width: 36px !important; height: 36px !important; margin: 0 auto; border-radius: 50% !important;
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
    .st-key-page_header h2,.st-key-page_header h2::after, .st-key-page_header [data-testid="stCaptionContainer"] { animation: none; }
    .st-key-page_header [data-testid="stDateInputField"], .st-key-page_header [data-testid="stDateInput"] svg { transition: none; transform: none !important; }
}

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
        ข้อความ CSS ของ @media ทั้ง 4 ช่วง (Mobile, Tablet, Laptop, Desktop)
    """

    def variables_block(breakpoint_name: str) -> str:
        """แปลง dict ค่าของช่วงจอเป็นข้อความตัวแปร CSS เช่น --app-card-padding: 10px;"""
        return "\n".join(
            f"    --app-{name}: {value};" for name, value in RESPONSIVE_VARIABLES[breakpoint_name].items()
        )

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

/* ===== 14) Responsive: Laptop ({LAPTOP_MIN_PX}-{LAPTOP_MAX_PX}px) ใช้ค่ามาตรฐาน (ค่าใน :root ด้านบน) ไม่ต้องปรับเพิ่ม ===== */
@media (min-width: {LAPTOP_MIN_PX}px) and (max-width: {LAPTOP_MAX_PX}px) {{
  :root {{
{variables_block("laptop")}
  }}
}}

/* ===== 15) Responsive: Desktop จอใหญ่ ({DESKTOP_MIN_PX}px ขึ้นไป) ===== */
@media (min-width: {DESKTOP_MIN_PX}px) {{
  :root {{
{variables_block("desktop")}
  }}
  /* เพิ่มช่องไฟระหว่างคอลัมน์ให้โปร่งขึ้น */
  [data-testid="stMainBlockContainer"] [data-testid="stHorizontalBlock"] {{ gap: 1.5rem; }}
}}
"""


def build_global_css() -> str:
    """ประกอบ CSS ทั้งแอป: นำเข้าฟอนต์ + ตัวแปรสี (:root) + กฎ CSS

    Returns:
        ข้อความ <style>...</style> พร้อมส่งให้ st.markdown(unsafe_allow_html=True)
    """
    # สร้างตัวแปร CSS จาก PALETTE เช่น --app-bg: #F8FAFC;
    css_variables = "\n".join(f"--app-{name}: {value};" for name, value in PALETTE.items())
    css_variables += f"\n--app-font: {FONT_FAMILY};\n--app-shadow: {SHADOW};"
    # ตัวแปรขนาดตัวอักษร เช่น --app-fs-body: 16px;
    css_variables += "\n" + "\n".join(f"--app-fs-{name}: {size}px;" for name, size in TYPOGRAPHY_PX.items())
    # ค่าเริ่มต้นของตัวแปร responsive = ค่าของ Laptop (ช่วงจออื่นจะถูกแทนที่ด้วย Media Query ด้านล่าง)
    css_variables += "\n" + "\n".join(f"--app-{n}: {v};" for n, v in RESPONSIVE_VARIABLES["laptop"].items())
    css_rules = GLOBAL_CSS_RULES.replace("RADIUS", f"{RADIUS_PX}px")
    # @import ต้องอยู่บรรทัดแรกสุดของ <style> เสมอ ไม่เช่นนั้นเบราว์เซอร์จะข้ามไป
    return (
        f"<style>\n@import url('{GOOGLE_FONTS_URL}');\n:root {{\n{css_variables}\n}}\n"
        f"{css_rules}{build_responsive_css()}</style>"
    )


def inject_global_styles() -> None:
    """ฉีด CSS ธีมกลางเข้าหน้าเว็บ (เรียกครั้งเดียวต้น app.py ทุกครั้งที่สคริปต์รัน)"""
    st.markdown(build_global_css(), unsafe_allow_html=True)
