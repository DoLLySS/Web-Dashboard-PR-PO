# IT PR/PO & Tax Invoice MasterList

## 📌 ภาพรวมของระบบ

เครื่องมือภายในสำหรับทีม IT Support ใช้บันทึกและติดตามเอกสารจัดซื้อ (PR/PO) และใบกำกับภาษี
สร้างด้วย Python + Streamlit เก็บข้อมูลในไฟล์ SQLite (ค่าเริ่มต้น `data/masterlist.db`) และไฟล์เอกสารใน `static/local_uploads/` ไม่ต้องติดตั้งฐานข้อมูลแยก

**ทำอะไรได้บ้าง**

| หน้า | ฟีเจอร์ |
|---|---|
| **Overview** | อัปโหลดไฟล์ PDF / Excel / รูป หรือกรอกฟอร์ม (อยู่ในหน้าต่างที่เปิดจากปุ่มเพิ่มข้อมูล), ช่องค้นหา, ตารางแก้ไขได้, Export CSV / Excel, **แจ้งเตือนเมื่อใบกำกับภาษีค้างเกิน 14 วัน** |
| **Dashboard** | การ์ด **ยอดรวมค่าใช้จ่ายทั้งหมด** (รวม Net Price), กราฟเส้นแนวโน้มราคา, สรุปอุปกรณ์, กราฟแท่ง **Top Vendors by Spend** และตารางผู้ขาย |
| **Date Filter** | ตัวกรองช่วงวันที่มุมขวาบน ใช้กับทั้งสองหน้า (ค่าเริ่มต้นคือย้อนหลัง 30 วัน) |

**การทำงานของการอัปโหลด**

- **ไฟล์ PR (PDF หรือ `.xlsx`):** ระบบอ่านค่าแล้วสร้างแถวทันที ถ้า Description + Company + Tel ตรงกับแถวเดิมจะแนบเข้าแถวเดิม
- **ไฟล์อื่น:** ระบบจับคู่กับ PR จากชื่อไฟล์และเนื้อหา แล้วเก็บเข้าโฟลเดอร์ของแถวนั้น ถ้าจับคู่ไม่ได้จะไม่บันทึก
- **ใบกำกับภาษี:** ไฟล์ที่มีคำว่า "ใบกำกับภาษี" / "Tax Invoice" หรือไฟล์ที่จับคู่กับ PR ได้และไม่ได้บอกว่าเป็นใบเสนอราคา คู่เทียบ หรือใบสั่งซื้อ จะเปลี่ยนแถวเป็น Completed ทันที ถ้าสถานะผิด แก้กลับเป็น Pending ในตารางได้
- **ใบกำกับที่จับคู่เองไม่ได้:** ถ้าชื่อไฟล์หรือเนื้อหามีคำว่าใบกำกับ ระบบจะให้ผู้ใช้เลือกแถวเอง

**การลบแถว:** ติ๊กแถวแล้วกดลบ ระบบให้ยืนยันก่อน แล้วลบแถวและไฟล์ในเครื่องถาวร (ยกเว้นไฟล์ที่แถวอื่นยังใช้) Audit Log ของแถวนั้นเหลือเฉพาะวันเวลา ประเภทการกระทำ และรหัสแถว ไฟล์บนที่เก็บออนไลน์ไม่ถูกลบ

**สถานะของฟีเจอร์**

| ฟีเจอร์ | สถานะ |
|---|---|
| บันทึก / ค้นหา / แก้ไข / ลบ / แจ้งเตือน / Dashboard | ✅ ใช้งานได้ |
| อ่านค่าจาก PR แบบ PDF และ `.xlsx` | ✅ ใช้งานได้ ควรตรวจค่าในตารางหลังอัปโหลด |
| เก็บไฟล์เอกสารในเครื่อง (`static/local_uploads/`) | ✅ ใช้งานได้ |
| สำรองข้อมูล (`scripts/backup.py`) และล้างข้อมูลเก่า (`scripts/purge_deleted.py`) | ✅ ทดสอบบนสำเนาแล้ว วิธีใช้อยู่ใน `DEPLOY.md` |
| ส่งไฟล์ขึ้น Google Drive | 🟡 ใช้ทดสอบ ดู `NEXT_STEPS.md` |
| ส่งไฟล์ขึ้น SharePoint ผ่าน Power Automate | 🟡 โค้ดฝั่งแอปเสร็จและทดสอบกับ Flow ปลอมแล้ว **ยังไม่เคยใช้กับ Flow จริง** รอ Flow จากทีม IT ดู `NEXT_STEPS.md` |
| ส่งข้อมูลแถวเข้า Master-List ผ่าน Flow | 🟡 โค้ดฝั่งแอปเสร็จและทดสอบกับ Flow ปลอมแล้ว (`MASTERLIST_API_URL`) **ยังไม่เคยใช้กับ Flow จริง** ปลายทางจริงรอ IT ยืนยัน |
| OCR สำหรับ PDF สแกน / รูปภาพ | ❌ ยังไม่ได้ทำ ไฟล์สแกนจับคู่ได้จากชื่อไฟล์เท่านั้น |
| Excel หนึ่งไฟล์หลายแถว | ❌ ยังไม่รองรับ Excel หนึ่งไฟล์นับเป็น PR 1 ใบ |
| ล็อกอิน | ❌ ไม่มี ดู `DEPLOY.md` ก่อนเปิดให้ผู้อื่นใช้ |
| ผู้ใช้หลายคนพร้อมกัน / หลายเบราว์เซอร์ | ⚠️ ยังไม่ได้ทดสอบ |

---

## 🛠️ วิธีการติดตั้ง

ทดสอบกับ **Python 3.12.3 บน Linux** ถ้าจะนำขึ้น Server ดู `DEPLOY.md`

```bash
cd Web-Dashboard-PR-PO
python3 -m venv venv
venv/bin/pip install -r requirements.txt
venv/bin/python -m streamlit run app.py
```

เปิดเบราว์เซอร์ที่ http://localhost:8501 ครั้งแรกระบบจะสร้างไฟล์ `data/masterlist.db` ให้เอง และรันได้โดยไม่ต้องมีไฟล์ `.env`

```bash
venv/bin/python generate_mock_data.py                 # ไม่บังคับ: ใส่ข้อมูลจำลอง ทำเฉพาะตอนฐานข้อมูลยังว่าง
venv/bin/pip install -r requirements-dev.txt          # สำหรับนักพัฒนา
venv/bin/python -m pytest -q                          # รันเทสต์ ไม่แตะข้อมูลจริงและไม่ส่งข้อมูลออนไลน์
```

### ปัญหาที่พบบ่อย

| อาการ | วิธีแก้ |
|---|---|
| `ModuleNotFoundError` | ยังไม่ได้ติดตั้ง Library หรือไม่ได้รันด้วย `venv/bin/python` |
| หน้าเว็บแจ้ง "ฐานข้อมูลถูกใช้งานอยู่" | รอสักครู่แล้วลองใหม่ และปิดโปรแกรมอื่นที่เปิด `masterlist.db` ค้างไว้ |
| แจ้งว่าไม่มีสิทธิ์เขียนไฟล์ | ตรวจสิทธิ์โฟลเดอร์ `data/` และ `static/local_uploads/` |
| เปิดพอร์ต 8501 ไม่ได้ | รันด้วยพอร์ตอื่น: `venv/bin/python -m streamlit run app.py --server.port 8502` |

---

## 📂 คำอธิบายโครงสร้างโฟลเดอร์สั้นๆ

```
Web-Dashboard-PR-PO/
├── app.py                 # ตัวควบคุมหลัก: Sidebar + Date Filter + เรียกหน้าที่เลือก
├── config/
│   ├── constants.py       # ค่าคงที่ที่ใช้หลายหน้า (เกณฑ์ค้าง, หมวดหมู่)
│   ├── settings.py        # อ่านค่าจาก .env พร้อมค่าเริ่มต้น
│   ├── logging_setup.py   # ตั้งค่า Logging -> logs/app.log
│   └── styles.py          # ธีมกลางและ CSS ของทั้งระบบ
├── pages_ui/
│   ├── overview.py        # หน้า Overview: แจ้งเตือน + ตาราง + ฟอร์ม + อัปโหลด
│   └── dashboard.py       # หน้า Dashboard
├── ui_common.py           # ส่วนหน้าจอที่ใช้ร่วมกัน
├── ui_grid.py             # ตาราง AgGrid
├── sidebar_ui.py          # Sidebar
├── utils/
│   ├── pr_reader.py       # อ่านค่าจากฟอร์ม PR (PDF / Excel)
│   ├── upload_processor.py # อัปโหลดอัตโนมัติ: แยก PR, จับคู่ไฟล์, ตรวจใบกำกับ
│   ├── submit_pipeline.py # บันทึกแถว + เก็บไฟล์ + ส่งออนไลน์ + จับคู่ไฟล์กับ PR
│   ├── row_cleanup.py     # ลบแถวถาวรพร้อมไฟล์
│   ├── text_extractor.py  # อ่านข้อความจาก PDF / Excel
│   ├── local_storage.py   # เก็บไฟล์ลง static/local_uploads/
│   ├── storage_backend.py # เลือกที่เก็บไฟล์ออนไลน์
│   ├── gdrive_api.py      # Google Drive
│   ├── power_automate_api.py # ส่งไฟล์ผ่าน Power Automate ไปที่ SharePoint
│   ├── file_removal.py    # ตรรกะลบไฟล์ใต้ local_uploads (ใช้ร่วมกับ scripts/)
│   ├── sharepoint_api.py  # SharePoint แบบเดิม (ใช้ไม่ได้แล้ว ดู NEXT_STEPS.md)
│   ├── masterlist_client.py # Master-List ผ่าน Flow (ทดสอบกับ Flow ปลอมเท่านั้น)
│   └── excel_export.py    # Export Excel
├── data/
│   ├── database.py        # ที่เดียวที่เขียน SQL
│   └── masterlist.db      # (สร้างอัตโนมัติ ไม่ขึ้น Git) ฐานข้อมูล
├── static/local_uploads/  # (สร้างอัตโนมัติ ไม่ขึ้น Git) ไฟล์เอกสาร ปี/เดือน/วัน/ชื่อ
├── scripts/
│   ├── backup.py          # สำรองฐานข้อมูล ไฟล์เอกสาร และโค้ด (รันเดี่ยวได้)
│   ├── purge_deleted.py   # ล้างแถวที่ซ่อนและรายละเอียดใน Audit Log (รันเดี่ยวได้)
│   └── check_flow.py      # ให้ IT ตรวจ Flow ของ Power Automate
├── tests/                 # เทสต์ pytest
├── logs/                  # ไฟล์ Log (ไม่ขึ้น Git)
├── assets/                # รูปโลโก้
├── .streamlit/config.toml # ตั้งค่า Streamlit
├── generate_mock_data.py  # สร้างข้อมูลจำลอง
├── requirements.txt       # Library พร้อมเวอร์ชัน
├── requirements-dev.txt   # Library สำหรับพัฒนา
├── .env.example           # แม่แบบไฟล์ตั้งค่า
├── DEPLOY.md              # การนำขึ้น Server, สำรอง, กู้คืน, ล้างข้อมูลเก่า
├── NEXT_STEPS.md          # งานที่เหลือ รวมแผนเชื่อม SharePoint
└── planning.md            # เอกสารวางแผนช่วงแรกและ Coding Standards
```

> `planning.md` และ `resume_state.md` เป็นเอกสารประวัติ โครงสร้างในนั้นต่างจากของจริง ให้ยึด README นี้

### อยากแก้อะไร ไปที่ไหน

| ต้องการ | แก้ที่ |
|---|---|
| เปลี่ยนจำนวนวันแจ้งเตือนใบกำกับภาษี (14 วัน) | `OVERDUE_RULE` ใน `config/constants.py` |
| เพิ่ม/ลบหมวดหมู่ในฟอร์ม | `CATEGORY_OPTIONS` ใน `config/constants.py` **และ** เพิ่มสีใน `CATEGORY_COLORS` ของ `pages_ui/dashboard.py` |
| เปลี่ยนชื่อเว็บ / โลโก้ (วางไฟล์ `assets/logo.png`) / สี Sidebar | ค่าคงที่ต้นไฟล์ `sidebar_ui.py` |
| เปลี่ยนสี/ฟอนต์/ความมน/เงาของทั้งระบบ | `PALETTE`, `FONT_FAMILY`, `RADIUS_PX` ใน `config/styles.py` (และสีหัวตารางใน `.streamlit/config.toml`) |
| เปลี่ยนสีกราฟ | `CATEGORY_COLORS` บนสุดของ `pages_ui/dashboard.py` |
| เพิ่มช่องกรอกในฟอร์ม | `render_entry_form()` ใน `pages_ui/overview.py` และถ้าเป็นคอลัมน์ใหม่ ต้องแก้ `data/database.py` + `TABLE_COLUMNS` ด้วย |
| ปรับคำที่ใช้ตัดสินว่าเป็นใบกำกับหรือเอกสารอื่น | `TAX_INVOICE_KEYWORDS`, `NON_INVOICE_KEYWORDS` ใน `utils/upload_processor.py` |
| เพิ่มหน้าใหม่ / เมนูใหม่ | สร้างไฟล์ใน `pages_ui/` ที่มีฟังก์ชัน `render(start_date, end_date)` แล้วเพิ่ม `MenuItem` ใน `MENU_GROUPS` ของ `app.py` |
| ปรับกฎอ่านฟอร์ม PR | ค่าคงที่บนสุดของ `utils/pr_reader.py` |
| เปลี่ยนช่วงวันที่เริ่มต้นของ Date Filter | `DEFAULT_RANGE_DAYS` ใน `app.py` |

### ข้อควรรู้ในการดูแลระบบ

- **สำรองข้อมูล:** ใช้ `scripts/backup.py` วิธีตั้งเวลาและกู้คืนอยู่ใน `DEPLOY.md`
- **วันที่:** เก็บในฐานข้อมูลเป็น ค.ศ. (`YYYY-MM-DD`) หน้าจอแสดงเป็น `วัน/เดือน/ปี` ค.ศ.
- **ใช้พร้อมกันหลายคน:** SQLite รองรับผู้ใช้จำนวนน้อยได้ แต่ถ้าวางไฟล์ `.db` บนโฟลเดอร์แชร์ที่หลายคนเขียนพร้อมกัน อาจเจอ error "database is locked" แนะนำให้รันระบบบนเครื่องเดียวแล้วให้คนอื่นเข้าผ่านเบราว์เซอร์
- **Coding Standards:** Type Hint ทุกฟังก์ชัน, Docstring และ Comment เป็นภาษาไทย, ครอบ try-except พร้อมข้อความที่เข้าใจง่าย (รายละเอียดใน `planning.md`)
