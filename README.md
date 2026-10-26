# IT PR/PO & Tax Invoice MasterList

## 📌 ภาพรวมของระบบ

เครื่องมือภายในสำหรับทีม IT Support ใช้บันทึกและติดตามเอกสารจัดซื้อ (PR/PO) และใบกำกับภาษี
สร้างด้วย Python + Streamlit เก็บข้อมูลในไฟล์ SQLite (`data/masterlist.db`) ไม่ต้องติดตั้งฐานข้อมูลแยก

**ทำอะไรได้บ้าง**

| หน้า | ฟีเจอร์ |
|---|---|
| **Overview** | ฟอร์มเพิ่มรายการ (ผู้ขาย, เบอร์โทร, Tax ID, เลขที่ PR, วันที่ PR, QT No., รายละเอียด, Net Price, หมวดหมู่ ฯลฯ) + แนบไฟล์ PDF / Excel / รูป, ช่องค้นหา, ตารางแก้ไขได้, **แจ้งเตือนเมื่อใบกำกับภาษีค้างเกิน 14 วัน** |
| **Dashboard** | การ์ด **ยอดรวมค่าใช้จ่ายทั้งหมด** (รวม Net Price), กราฟเส้นแนวโน้มราคา, สรุปอุปกรณ์, กราฟแท่ง **Top Vendors by Spend** และตารางผู้ขาย |
| **Date Filter** | ตัวกรองช่วงวันที่มุมขวาบน ใช้กับทั้งสองหน้า (ค่าเริ่มต้นคือย้อนหลัง 30 วัน) |

**สถานะของฟีเจอร์ (ตรงไปตรงมา)**

| ฟีเจอร์ | สถานะ |
|---|---|
| บันทึก / ค้นหา / แก้ไข / ลบ / แจ้งเตือน / Dashboard | ✅ ใช้งานได้ |
| ดึงข้อความจากไฟล์ PDF และ Excel (`.xlsx`, `.xls`) ลงฟอร์มอัตโนมัติ | ✅ ใช้งานได้ (ต้องตรวจค่าก่อนกด Upload ทุกครั้ง ถ้าอ่านไม่ได้ ระบบแจ้งให้กรอกเอง) |
| เก็บไฟล์เอกสารในเครื่อง (`data/local_uploads/`) | ✅ ใช้งานได้ |
| เชื่อม SharePoint | 🟡 เขียนโค้ดไว้แล้วแต่ **ปิดไว้** รอสิทธิ์จากทีม IT (ดูหัวข้อ "การเตรียมตัวสำหรับ SharePoint") |
| OCR สำหรับ PDF สแกน / รูปภาพ | ❌ ยังไม่ได้ทำ (ต้องกรอกเอง) |
| ทดสอบบนเบราว์เซอร์จริงหลายเครื่อง / หลายผู้ใช้พร้อมกัน | ⚠️ ยังไม่ได้ทดสอบ ทดสอบอัตโนมัติด้วย Streamlit AppTest เท่านั้น |

---

## 🛠️ วิธีการติดตั้งแบบ Step-by-step

ต้องมี **Python 3.11** (ทดสอบแล้ว) ตรวจสอบด้วย `python --version`
ตัวอย่างด้านล่างใช้ **PowerShell** บน Windows

**1. เปิดโฟลเดอร์โปรเจคใน Terminal**
```powershell
cd "path\to\Project ฝึกงาน"
```

**2. สร้าง Virtual Environment (venv)** — เพื่อไม่ให้ Library ปนกับโปรเจคอื่นในเครื่อง
```powershell
python -m venv venv
```

**3. เปิดใช้งาน venv** (ต้องทำทุกครั้งที่เปิด Terminal ใหม่)
```powershell
.\venv\Scripts\Activate.ps1
```
ถ้าขึ้น error เรื่อง *running scripts is disabled* ให้รันครั้งเดียวแล้วลองใหม่:
```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```
เมื่อสำเร็จ หน้าบรรทัดคำสั่งจะมี `(venv)` นำหน้า

**4. ติดตั้ง Library**
```powershell
pip install -r requirements.txt
```

**5. รันระบบ**
```powershell
python -m streamlit run app.py
```
(หรือพิมพ์สั้น ๆ ว่า `streamlit run app.py` ถ้าเครื่องหาคำสั่ง `streamlit` เจอ)

เบราว์เซอร์จะเปิดที่ http://localhost:8501 ครั้งแรกระบบจะสร้างไฟล์ `data/masterlist.db` ให้เอง

**6. (ไม่บังคับ) ใส่ข้อมูลจำลองเพื่อลองใช้ระบบ** — ทำเฉพาะตอนฐานข้อมูลยังว่าง
```powershell
python generate_mock_data.py
```

> 💡 ใช้ `python -m streamlit ...` แทนการพิมพ์ `streamlit ...` ตรง ๆ เพราะบางเครื่อง PowerShell หาคำสั่ง `streamlit` ไม่เจอ (error: *'streamlit' is not recognized*)

### ปัญหาที่พบบ่อย

| อาการ | วิธีแก้ |
|---|---|
| `'streamlit' is not recognized` | ใช้ `python -m streamlit run app.py` |
| `ModuleNotFoundError` | ยังไม่ได้เปิด venv (ขั้นที่ 3) หรือยังไม่ได้ `pip install -r requirements.txt` |
| หน้าเว็บแจ้ง "ฐานข้อมูลถูกใช้งานอยู่" | รอสักครู่แล้วลองใหม่ และปิดโปรแกรมอื่น (เช่น DB Browser) ที่เปิด `masterlist.db` ค้างไว้ |
| แจ้งว่าไม่มีสิทธิ์เขียนไฟล์ | ตรวจสิทธิ์โฟลเดอร์ `data/` |
| เปิดพอร์ต 8501 ไม่ได้ | รันด้วยพอร์ตอื่น: `python -m streamlit run app.py --server.port 8502` |

---

## 🔐 การเตรียมตัวสำหรับ SharePoint

ตอนนี้ไฟล์ที่อัปโหลดถูกเก็บในเครื่องที่ `data/local_uploads/` และระบบ **รันได้ปกติโดยไม่ต้องมีไฟล์ `.env`**
โค้ดเชื่อม SharePoint เขียนเสร็จแล้วใน `utils/sharepoint_api.py` แต่ยังปิดการเรียกใช้อยู่ เมื่อทีม IT ได้รับสิทธิ์แล้วให้ทำตามนี้

**ขั้นที่ 1 — ใส่รหัสในไฟล์ `.env`**
1. คัดลอก `.env.example` เป็น `.env` (อยู่โฟลเดอร์เดียวกับ `app.py`)
2. กรอกค่าจริงตามตาราง
3. **ห้ามนำ `.env` ขึ้น Git หรือส่งต่อในแชท** (`.gitignore` กันไฟล์นี้ไว้แล้ว ส่วน `.env.example` เป็นข้อมูลปลอมทั้งหมด)

| Key | ความหมาย | หาได้จากที่ไหน |
|---|---|---|
| `SHAREPOINT_URL` | URL ของ SharePoint Site เช่น `https://yourcompany.sharepoint.com/sites/IT` | ผู้ดูแล SharePoint |
| `SHAREPOINT_CLIENT_ID` | รหัสแอปที่ลงทะเบียน | Azure Portal → App registrations → *Application (client) ID* |
| `SHAREPOINT_CLIENT_SECRET` | รหัสลับของแอป (**เป็นความลับ** มีวันหมดอายุ) | App registrations → Certificates & secrets |
| `SHAREPOINT_USERNAME` / `SHAREPOINT_PASSWORD` | วิธีสำรอง: ล็อกอินด้วยบัญชีผู้ใช้ (ใช้ไม่ได้ถ้าเปิด MFA) | บัญชีของทีม IT |
| `SHAREPOINT_FOLDER_PATH` | (ไม่บังคับ) โฟลเดอร์ปลายทาง ต้องมีอยู่แล้ว ค่าเริ่มต้น `Shared Documents/PR-PO` | ผู้ดูแล SharePoint |

ผู้ดูแล Azure ต้องให้สิทธิ์แอป (เช่น `Sites.Selected` หรือ `Sites.ReadWrite.All`) และกด *Grant admin consent* ก่อน

**ขั้นที่ 2 — ปลดคอมเมนต์โค้ด**
- `pages_ui/overview.py` ฟังก์ชัน `save_document_and_get_path()`: เปิด `import` ของ `utils.sharepoint_api` ใกล้บรรทัด 37 และเปลี่ยนไปเรียก `upload_document_to_sharepoint()` ตามคอมเมนต์ "SharePoint ปิดไว้" ในฟังก์ชันนั้น
- `utils/sharepoint_api.py`: โค้ดวิธีหลัก (Client ID/Secret) ทำงานอยู่แล้ว **ปลดคอมเมนต์เฉพาะเมื่อต้องใช้วิธีสำรอง** (Username/Password) ตามขั้นตอนในคอมเมนต์ของไฟล์

**ขั้นที่ 3 — ทดสอบ** ลองอัปโหลดไฟล์ทดสอบ 1 ไฟล์ แล้วตรวจว่าไฟล์ขึ้นในโฟลเดอร์บน SharePoint และไอคอนไฟล์ในตารางเปิดลิงก์ได้ ถ้า error ระบบจะแสดงข้อความภาษาไทยบอกสาเหตุที่ควรตรวจ

> ⚠️ ยังไม่เคยทดสอบกับ SharePoint จริง (ไม่มีสิทธิ์ตอนพัฒนา) อาจต้องปรับเล็กน้อยตอนต่อจริง

---

## 📂 คำอธิบายโครงสร้างโฟลเดอร์สั้นๆ

```
Project ฝึกงาน/
├── app.py                 # ตัวควบคุมหลัก (Router): Sidebar + Date Filter + เรียกหน้าที่เลือก
├── config.py              # ค่าคงที่ที่ใช้หลายหน้า (หมวดหมู่)
├── ui_common.py           # ธีมการ์ด (CSS) + ตารางสรุปอุปกรณ์ ที่ใช้ร่วมกัน
├── styles.py              # ธีมกลางของทั้งระบบ: ฟอนต์ สี ความมน เงา + CSS (ฉีดจาก app.py)
├── sidebar_ui.py          # หน้าตา Sidebar: โลโก้, ชื่อเว็บ, เมนูแบบจัดกลุ่ม, สี/CSS
├── pages_ui/
│   ├── overview.py        # หน้า Overview: แจ้งเตือน + ฟอร์ม + ตาราง
│   ├── dashboard.py       # หน้า Dashboard: Metric + กราฟ + Top Vendors
│   └── settings.py        # หน้า Setting (โครงเปล่า)
├── .streamlit/config.toml # ตั้งค่าธีมสว่างของ Streamlit
├── utils/
│   ├── text_extractor.py  # อ่าน PDF / Excel แล้วหา Tax ID / ผู้ขาย / เลขที่ PR / Net Price ฯลฯ
│   ├── local_storage.py   # บันทึกไฟล์เอกสารลง data/local_uploads/
│   └── sharepoint_api.py  # โค้ดเชื่อม SharePoint (เขียนแล้ว แต่ปิดการเรียกใช้ไว้)
├── data/
│   ├── database.py        # ที่เดียวที่เขียน SQL: สร้างตาราง + เพิ่ม/ดู/แก้/ลบ
│   ├── masterlist.db      # (สร้างอัตโนมัติ ไม่ขึ้น Git) ฐานข้อมูล
│   └── local_uploads/     # (สร้างอัตโนมัติ ไม่ขึ้น Git) ไฟล์เอกสารที่อัปโหลด
├── generate_mock_data.py  # สร้างข้อมูลจำลองไว้ลองระบบ
├── requirements.txt       # รายการ Library พร้อมเวอร์ชัน
├── .env.example           # แม่แบบไฟล์ตั้งค่า SharePoint
└── planning.md            # เอกสารวางแผนและ Coding Standards ของทีม
```

> `planning.md` เป็นเอกสารร่างแรก โครงสร้างบางส่วนต่างจากของจริง (เช่น ตอนนี้ใช้ `database.py` ไฟล์เดียวแทน `database/` และ `pages_ui/` แทน `pages/`) ให้ยึดตาม README นี้เป็นหลัก

### อยากแก้อะไร ไปที่ไหน

| ต้องการ | แก้ที่ |
|---|---|
| เปลี่ยนจำนวนวันแจ้งเตือนใบกำกับภาษี (14 วัน) | `OVERDUE_DAYS_LIMIT` บนสุดของ `pages_ui/overview.py` |
| เพิ่ม/ลบหมวดหมู่ในฟอร์ม | `CATEGORY_OPTIONS` ใน `config.py` **และ** เพิ่มสีใน `CATEGORY_COLORS` ของ `pages_ui/dashboard.py` |
| เปลี่ยนชื่อเว็บ / โลโก้ (วางไฟล์ `assets/logo.png`) / สี Sidebar | ค่าคงที่ต้นไฟล์ `sidebar_ui.py` |
| เปลี่ยนสี/ฟอนต์/ความมน/เงาของทั้งระบบ | `PALETTE`, `FONT_FAMILY`, `RADIUS_PX` ใน `styles.py` (และสีหัวตารางใน `.streamlit/config.toml`) |
| เปลี่ยนสีกราฟ | `CATEGORY_COLORS` บนสุดของ `pages_ui/dashboard.py` |
| เพิ่มช่องกรอกในฟอร์ม | `render_entry_form()` ใน `overview.py` (ดู Comment "ส่วนที่ 1-5") และถ้าเป็นคอลัมน์ใหม่ ต้องแก้ `data/database.py` + `TABLE_COLUMN_LABELS` ด้วย |
| เพิ่มหน้าใหม่ / เมนูใหม่ | สร้างไฟล์ใน `pages_ui/` ที่มีฟังก์ชัน `render(start_date, end_date)` แล้วเพิ่ม `MenuItem` ใน `MENU_GROUPS` ของ `app.py` |
| ปรับกฎดึงข้อมูลจาก PDF | รายการค่าคงที่บนสุดของ `utils/text_extractor.py` |
| เปลี่ยนช่วงวันที่เริ่มต้นของ Date Filter | `DEFAULT_RANGE_DAYS` ใน `app.py` |

### ข้อควรรู้ในการดูแลระบบ

- **สำรองข้อมูล:** คัดลอกโฟลเดอร์ `data/` (ทั้งไฟล์ `.db` และ `local_uploads/`) เก็บไว้เป็นระยะ
- **วันที่:** เก็บในฐานข้อมูลเป็น ค.ศ. (`YYYY-MM-DD`) หน้าจอแสดงเป็น `วัน/เดือน/ปี` ค.ศ.
- **ใช้พร้อมกันหลายคน:** SQLite รองรับผู้ใช้จำนวนน้อยได้ แต่ถ้าวางไฟล์ `.db` บนโฟลเดอร์แชร์ที่หลายคนเขียนพร้อมกัน อาจเจอ error "database is locked" แนะนำให้รันระบบบนเครื่องเดียวแล้วให้คนอื่นเข้าผ่านเบราว์เซอร์
- **Coding Standards:** Type Hint ทุกฟังก์ชัน, Docstring และ Comment เป็นภาษาไทย, ครอบ try-except พร้อมข้อความที่เข้าใจง่าย (รายละเอียดใน `planning.md`)
