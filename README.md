# IT PR/PO & Tax Invoice MasterList

## 📌 ภาพรวมของระบบ

เครื่องมือภายในสำหรับทีม IT Support ใช้บันทึกและติดตามเอกสารจัดซื้อ (PR/PO) และใบกำกับภาษี
สร้างด้วย Python + Streamlit เก็บข้อมูลในไฟล์ SQLite (`data/masterlist.db`) ไม่ต้องติดตั้งฐานข้อมูลแยก

**ทำอะไรได้บ้าง**

| หน้า | ฟีเจอร์ |
|---|---|
| **Overview** | ฟอร์มเพิ่มรายการ (วันที่, ผู้ขาย, Tax ID, PO, หมวดหมู่, ราคา) + แนบไฟล์ PDF/รูป, ช่องค้นหา, ตารางข้อมูล, **แจ้งเตือนเมื่อใบกำกับภาษีค้างเกิน 14 วัน** |
| **Dashboard** | ตัวเลขสรุป, กราฟเส้นแนวโน้มยอดซื้อแยกตามหมวดหมู่, ตาราง Top 10 ผู้ขาย |
| **Date Filter** | ตัวกรองช่วงวันที่มุมขวาบน ใช้กับทั้งสองหน้า (ค่าเริ่มต้นคือย้อนหลัง 30 วัน) |

**สถานะของฟีเจอร์ (ตรงไปตรงมา)**

| ฟีเจอร์ | สถานะ |
|---|---|
| บันทึก / ค้นหา / แจ้งเตือน / Dashboard | ✅ ใช้งานได้ |
| ดึงข้อความจาก PDF (`text_extractor.py`) | ✅ ต่อกับฟอร์มแล้ว: อัปโหลด PDF ในกล่อง "Upload P/O to Purchase" จะเติม TaxID / Vendor / ยอดรวมให้ (ต้องตรวจก่อนกด Upload) |
| ปุ่มเปลี่ยนสถานะเป็น "ได้รับใบกำกับภาษีแล้ว" | ⚠️ ฟังก์ชัน `mark_invoice_received()` พร้อมแล้ว แต่ **ยังไม่มีปุ่มบนหน้าจอ** |
| แก้ไข / ลบรายการผ่านหน้าเว็บ | ❌ ยังไม่มี (มีเฉพาะฟังก์ชันใน `database.py`) |
| เชื่อม SharePoint | ❌ ยังไม่ได้ทำ (ดูหัวข้อ .env ด้านล่าง) |
| OCR สำหรับ PDF สแกน / รูปภาพ | ❌ ยังไม่ได้ทำ |

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
เบราว์เซอร์จะเปิดที่ http://localhost:8501 ครั้งแรกระบบจะสร้างไฟล์ `data/masterlist.db` ให้เอง

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

## ⚙️ การตั้งค่าไฟล์ .env สำหรับเชื่อมต่อ SharePoint

> ⚠️ **ตอนนี้โค้ดยังไม่มีส่วนเชื่อม SharePoint และยังไม่อ่านไฟล์ `.env`** ระบบรันได้ปกติโดยไม่ต้องมี `.env`
> หัวข้อนี้คือ "ค่าที่เตรียมไว้" สำหรับตอนที่ทีมเริ่มทำฟีเจอร์ SharePoint (ชื่อ Key เป็นข้อเสนอ เปลี่ยนได้ตามที่ทีมตกลง)

**วิธีเตรียมไฟล์**
1. คัดลอก `.env.example` เป็น `.env` (อยู่โฟลเดอร์เดียวกับ `app.py`)
2. กรอกค่าตามตารางด้านล่าง
3. **ห้ามนำ `.env` ขึ้น Git หรือส่งต่อในแชท** (`.gitignore` ตั้งไว้ให้ข้ามไฟล์นี้แล้ว)

**Key ที่ต้องใส่** (สมมติว่าเชื่อมแบบ App Registration ของ Microsoft Entra ID / Azure AD)

| Key | ความหมาย | หาได้จากที่ไหน |
|---|---|---|
| `SHAREPOINT_TENANT_ID` | รหัสองค์กร (Tenant) | Azure Portal → Microsoft Entra ID → Overview → *Tenant ID* |
| `SHAREPOINT_CLIENT_ID` | รหัสแอปที่ลงทะเบียน | Azure Portal → App registrations → แอปของเรา → *Application (client) ID* |
| `SHAREPOINT_CLIENT_SECRET` | รหัสลับของแอป (**เป็นความลับ**) | App registrations → Certificates & secrets → New client secret (มีวันหมดอายุ ควรจดไว้) |
| `SHAREPOINT_SITE_URL` | URL ของ SharePoint Site | เช่น `https://yourcompany.sharepoint.com/sites/IT` |
| `SHAREPOINT_FOLDER_PATH` | โฟลเดอร์ปลายทางเก็บไฟล์ | เช่น `Shared Documents/PR-PO` |

ผู้ดูแล Azure ของบริษัทต้องให้สิทธิ์แอป (เช่น `Sites.Selected` หรือ `Sites.ReadWrite.All`) และกด *Grant admin consent* ก่อน
เมื่อเริ่มทำฟีเจอร์ ให้ถอดเครื่องหมาย `#` ของ `python-dotenv` และไลบรารี SharePoint ใน `requirements.txt`

---

## 📂 คำอธิบายโครงสร้างโฟลเดอร์สั้นๆ

```
Project ฝึกงาน/
├── app.py                 # ตัวควบคุมหลัก (Router): Sidebar + Date Filter + เรียกหน้าที่เลือก
├── config.py              # ค่าคงที่ที่ใช้หลายหน้า (หมวดหมู่)
├── ui_common.py           # ธีมการ์ด (CSS) + ตารางสรุปอุปกรณ์ ที่ใช้ร่วมกัน
├── styles.py              # ธีมกลางของทั้งระบบ: ฟอนต์ สี ความมน เงา + CSS (ฉีดจาก app.py)
├── sidebar_ui.py          # หน้าตา Sidebar: โลโก้, ชื่อเว็บ, เมนูแบบจัดกลุ่ม, สี/CSS
├── database.py            # ที่เดียวที่เขียน SQL: สร้างตาราง + เพิ่ม/ดู/แก้/ลบ
├── text_extractor.py      # อ่าน PDF แล้วหา Tax ID / ยอดรวม / ผู้ขาย (ยังไม่ต่อกับฟอร์ม)
├── pages_ui/
│   ├── overview.py        # หน้า Overview: แจ้งเตือน + ฟอร์ม + ตาราง
│   ├── dashboard.py       # หน้า Dashboard: Metric + กราฟ + Top Vendors
│   └── settings.py        # หน้า Setting (โครงเปล่า)
├── .streamlit/config.toml # ตั้งค่าธีมสว่างของ Streamlit
├── data/                  # (สร้างอัตโนมัติ) masterlist.db และ uploads/ (ไฟล์ที่แนบ)
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
| เพิ่มช่องกรอกในฟอร์ม | `render_entry_form()` ใน `overview.py` (ดู Comment "ส่วนที่ 1-5") และถ้าเป็นคอลัมน์ใหม่ ต้องแก้ `database.py` + `TABLE_COLUMN_LABELS` ด้วย |
| เพิ่มหน้าใหม่ / เมนูใหม่ | สร้างไฟล์ใน `pages_ui/` ที่มีฟังก์ชัน `render(start_date, end_date)` แล้วเพิ่ม `MenuItem` ใน `MENU_GROUPS` ของ `app.py` |
| ปรับกฎดึงข้อมูลจาก PDF | รายการค่าคงที่บนสุดของ `text_extractor.py` |
| เปลี่ยนช่วงวันที่เริ่มต้นของ Date Filter | `DEFAULT_RANGE_DAYS` ใน `app.py` |

### ข้อควรรู้ในการดูแลระบบ

- **สำรองข้อมูล:** คัดลอกโฟลเดอร์ `data/` (ทั้งไฟล์ `.db` และ `uploads/`) เก็บไว้เป็นระยะ
- **วันที่:** เก็บในฐานข้อมูลเป็น ค.ศ. (`YYYY-MM-DD`) หน้าจอแสดงเป็น `วัน/เดือน/ปี` ค.ศ.
- **ใช้พร้อมกันหลายคน:** SQLite รองรับผู้ใช้จำนวนน้อยได้ แต่ถ้าวางไฟล์ `.db` บนโฟลเดอร์แชร์ที่หลายคนเขียนพร้อมกัน อาจเจอ error "database is locked" แนะนำให้รันระบบบนเครื่องเดียวแล้วให้คนอื่นเข้าผ่านเบราว์เซอร์
- **Coding Standards:** Type Hint ทุกฟังก์ชัน, Docstring และ Comment เป็นภาษาไทย, ครอบ try-except พร้อมข้อความที่เข้าใจง่าย (รายละเอียดใน `planning.md`)
