# Resume State — IT PR/PO & Tax Invoice MasterList

จุดเซฟล่าสุด: Git commit `6e39665` ("Checkpoint: อัปเดต UI, Responsive Layout, ระบบ Database และ Mock Data พร้อมพัฒนาต่อ")
ย้อนกลับมาจุดนี้ได้ด้วย `git checkout 6e39665 -- .` (หรือ `git stash` / `git restore .` เพื่อทิ้งการแก้ไขที่ยังไม่ commit)

## 1. โครงสร้างไฟล์ปัจจุบัน

```
Project ฝึกงาน/
├── app.py                  # Router: ฉีดธีม, Sidebar, แถบหัวหน้า (ชื่อหน้า + Date Filter), เรียกหน้าที่เลือก
├── styles.py               # ธีมกลาง: ฟอนต์ สี ความมน เงา + Responsive 4 ช่วงจอ + ซ่อนเมนู/Footer ของ Streamlit
├── sidebar_ui.py           # Sidebar: โลโก้ + ชื่อเว็บ + เมนูแบบจัดกลุ่ม (MenuItem)
├── ui_common.py            # CSS การ์ดที่ใช้ร่วมกัน + ตาราง Quantity of equipment
├── config.py               # ค่าคงที่ร่วม: CATEGORY_OPTIONS, EQUIPMENT_CATEGORIES
├── database.py             # SQLite (ที่เดียวที่เขียน SQL): CRUD, นับ/สรุปตามหมวด, migration คอลัมน์ใหม่อัตโนมัติ
├── text_extractor.py       # อ่าน PDF (pdfplumber) หา Tax ID / ยอดรวม / ผู้ขาย (คืน "" ถ้าหาไม่เจอ)
├── generate_mock_data.py   # สร้างข้อมูลจำลอง 18 แถว (ข้ามถ้าตารางมีข้อมูลแล้ว)
├── pages_ui/
│   ├── overview.py         # แจ้งเตือนค้าง 14 วัน, ตาราง+ตัวกรอง+Total Price, แท็บ กรอก Form/Upload File, Quantity of equipment
│   └── dashboard.py        # Price (ช่วงเวลา + Detail Graph), Equipment, Vendor, Export CSV
├── .streamlit/config.toml  # ธีมของ Streamlit (สีหลัก/พื้นหลัง/สีหัวตาราง)
├── requirements.txt, .env.example, .gitignore, README.md
├── planning.md             # แผนเดิม (บางส่วนล้าสมัย ให้ยึด README.md เป็นหลัก)
└── data/                   # (ไม่อยู่ใน Git) masterlist.db และ uploads/ — สร้างอัตโนมัติ
```

## 2. ฟีเจอร์ที่เสร็จสมบูรณ์แล้ว

- ฐานข้อมูล SQLite + CRUD + migration คอลัมน์ใหม่ (tel, email, contact_name, sharepoint_url)
- ฟอร์มกรอกข้อมูล 8 ฟิลด์ตามดีไซน์ + ตรวจข้อมูล (Tax ID 13 หลัก, Tel., Email, ลิงก์ https)
- อัปโหลดไฟล์ + Auto-fill TaxID/Vendor/ยอดรวมจาก PDF (กล่อง "Upload P/O to Purchase")
- ตาราง Overview: Search bar, Item/Vendor, สถานะ ✅ Completed / ⏳ Pending / 🔴 Overdue, Price มีคอมม่า, Total Price ตามตัวกรอง, แถวสลับสี, ไอคอน 📁 เปิดลิงก์ SharePoint ในแท็บใหม่
- แจ้งเตือนใบกำกับภาษีค้างเกิน 14 วัน (`OVERDUE_DAYS_LIMIT` ใน overview.py)
- Dashboard: Price (ยอดรวม + กราฟเส้น, เลือก 7d/30d/90d, สวิตช์ Detail Graph), Equipment, Vendor, ปุ่ม Export CSV
- ธีม Enterprise (Inter + Noto Sans Thai, สี/มุม 8px/เงา) และ Responsive Mobile/Tablet/Laptop/Desktop
- ข้อมูลทดลอง: `python generate_mock_data.py`

วิธีรัน: `python -m streamlit run app.py` (ติดตั้ง: `pip install -r requirements.txt`)

## 3. ที่ยังไม่ได้ทำ / ข้อจำกัดที่รู้อยู่

- **ไม่มีปุ่มเปลี่ยนสถานะเป็น "ได้รับใบกำกับภาษีแล้ว" บนหน้าจอ** (ฟังก์ชัน `mark_invoice_received()` พร้อมใน database.py) จึงยังไม่มีทางทำให้รายการ Overdue/Pending กลายเป็น Completed จากหน้าเว็บ
- ยังไม่มีแก้ไข/ลบรายการผ่านหน้าเว็บ (มีเฉพาะฟังก์ชันใน database.py)
- SharePoint ยังไม่เชื่อมจริง: กล่อง "Upload P/O to SharePoint" แค่เก็บไฟล์ในคิว `data/sharepoint_pending/`; ลิงก์ในตารางมาจากการกรองเอง (ช่องในแถบ "รายละเอียดเพิ่มเติม")
- OCR สำหรับ PDF สแกน/รูปภาพ ยังไม่มี
- ปุ่ม Detail Graph/ช่วงเวลา ทำงานแล้ว แต่ปุ่ม Export บนมือถือยังไม่เต็มความกว้าง
- ฟอร์มซ่อนช่องราคา/หมวดหมู่ไว้ในแถบ "รายละเอียดเพิ่มเติม" ถ้าไม่กรอก ราคา = 0 ทำให้ยอดรวมต่ำกว่าจริง
- ยังไม่ได้ทดสอบบนมือถือ/iPad จริง (ทดสอบแค่จำลองขนาดจอ)
- ค่า `.streamlit/config.toml` และ CSS ผูกกับ Streamlit 1.66.1 (ถ้าอัปเกรดแล้วสไตล์หลุด ดู `data-testid` ใน styles.py)

## 4. Next Step เมื่อกลับมาทำงาน

1. **ทำปุ่ม/คอลัมน์เปลี่ยนสถานะ "ได้รับใบกำกับภาษีแล้ว"** ในตาราง Overview (เรียก `mark_invoice_received()`) เพื่อให้ ✅ Completed เกิดขึ้นจากหน้าเว็บได้ และแจ้งเตือน Overdue หายไปเมื่อปิดงาน
2. จากนั้นเลือกต่อ: เชื่อม SharePoint จริง (`.env` ตาม README, เขียนลิงก์ลงคอลัมน์ `sharepoint_url`) หรือแก้ไข/ลบรายการ
3. ก่อนใช้งานจริง: ลบ `data/masterlist.db` ที่มีข้อมูลทดลอง แล้วให้ระบบสร้างใหม่

คำถามที่ยังไม่ได้ตัดสินใจ (จาก planning.md): นับ 14 วันจาก "วันที่เอกสาร" (ตอนนี้ใช้อันนี้) หรือวันรับของ, ต้องมี login ไหม, DB อยู่เครื่องเดียวหรือโฟลเดอร์แชร์
