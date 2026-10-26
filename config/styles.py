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

# ฟอนต์หลักของระบบ (Inter สำหรับอังกฤษ/ตัวเลข, Noto Sans Thai สำหรับไทย)
# ถ้าเครื่องไม่มีอินเทอร์เน็ต จะตกไปใช้ sans-serif ของระบบอัตโนมัติ
FONT_FAMILY: str = "'Inter', 'Noto Sans Thai', sans-serif"
GOOGLE_FONTS_URL: str = (
    "https://fonts.googleapis.com/css2?"
    "family=Inter:wght@400;500;600;700;800&family=Noto+Sans+Thai:wght@400;500;600;700;800&display=swap"
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
TABLE_ROW_HEIGHT_PX: int = 44

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
        "main-padding-top": "6rem",
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
        "main-padding-top": "4rem",
    },
    "tablet": {
        "heading-scale": "0.9",  # ขนาดปานกลาง
        "card-padding": "20px",
        "inner-padding": "14px",
        "card-title": "25px",
        "metric-value": "27px",
        "main-padding-x": "2rem",
        "main-padding-top": "5rem",
    },
    "desktop": {
        "heading-scale": "1",
        "card-padding": "32px",  # โปร่งสบายตาบนจอความละเอียดสูง
        "inner-padding": "20px",
        "card-title": "30px",
        "metric-value": "34px",
        "main-padding-x": "3rem",
        "main-padding-top": "6rem",
        "container-max": "1800px",  # ขยายเนื้อหาให้กว้างขึ้น ไม่กระจุกอยู่กลางจอ (แต่ไม่ยืดจนอ่านยากบนจอ 4K)
        "block-gap": "1.5rem",
    },
}

# ---------------------------------------------------------------------------
# CSS (RADIUS ในข้อความด้านล่างจะถูกแทนด้วยค่า RADIUS_PX ตอนประกอบ)
# ---------------------------------------------------------------------------

GLOBAL_CSS_RULES: str = """
/* ===== 1) ฟอนต์: ใช้ Inter + Noto Sans Thai ทั้งระบบ ===== */
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
[data-testid="stMetric"] { padding: 12px 16px; box-shadow: var(--app-shadow); }
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
footer, [data-testid="stFooter"] {
    visibility: hidden;
}
/* หมายเหตุ: ไม่ซ่อนทั้ง Header เพราะมีปุ่มเปิด/ปิด Sidebar อยู่ ซึ่งจำเป็นบนมือถือ */

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
