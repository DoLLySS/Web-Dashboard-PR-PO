# งานค้างแยกตามผู้รับผิดชอบ

ณ commit `2ce30d5` (ยังไม่ push)

## งานของคนอื่น

| ผู้รับผิดชอบ | งาน | ติดอะไร |
|---|---|---|
| **หัวหน้า** (หรือผู้เข้าโฟลเดอร์ข้อมูลจริงได้) | ทำตาม `01_RUNBOOK_REAL_DATA.md`: สำรอง, ล้างแถวที่ซ่อนและ Audit Log (เส้นทาง B ก่อน), ตัดสินใจว่าจะอัปเดตโค้ดจริงหรือไม่ (เส้นทาง A) | ผู้พัฒนาเข้าข้อมูลจริงไม่ได้ ไม่ใช้ sudo |
| **IT / ผู้ดูแล Microsoft 365** | ตอบ `02_S0_IT_REQUEST.md` ข้อ 1–6 แล้วสร้าง Flow (S4) | ยังไม่ได้ส่งเอกสารถึง IT |
| **ผู้ดูแลเซิร์ฟเวอร์** | ขึ้นเซิร์ฟเวอร์ Linux (systemd, nginx+WebSocket, HTTPS, firewall, cron `scripts/backup.py`) และตัดสินใจเรื่องล็อกอิน/SSO | ยังไม่มีเซิร์ฟเวอร์ ตัวอย่างใน `DEPLOY.md` ยังไม่ได้ทดสอบ ตอนนี้ไม่มีล็อกอิน |
| **เจ้าของงาน** | ยืนยันวันที่เริ่มนับ 14 วัน (`OVERDUE_RULE` ใน `config/constants.py`), ตัดสินใจเรื่อง Excel หลายแถวต่อไฟล์ และ OCR | ยังไม่มีคำตอบ |

## ขั้นตอนต่อไปของ Power Automate (หลัง IT ตอบ)

- S4 สร้าง Flow จริง
- S5 ทดสอบกับไลบรารีว่างด้วย `scripts/check_flow.py` แล้วทดสอบทั้งแอปบนสำเนาข้อมูล (ชื่อไฟล์ซ้ำ ชื่อภาษาไทย ไฟล์ใหญ่ Flow ปิด/ล้มเหลว)
- S6 เปิดใช้: ตั้ง `.env`, ตัดสินใจเรื่องย้ายไฟล์เดิมขึ้น SharePoint และนโยบายลบไฟล์ออนไลน์, แล้วพิจารณาลบ `utils/sharepoint_api.py` พร้อม `Office365-REST-Python-Client`

## งานโค้ดที่เลื่อนไว้ (ไม่ทำรอบนี้)

- S2b ส่ง Master-List ผ่าน Flow (`utils/masterlist_client.py`)
- ลบฟังก์ชันที่ไม่มีใครเรียก: `ui_common.render_equipment_table`, `submit_pipeline.find_pr_folder_by_description`, `text_extractor.extract_fields_from_file`
- ตัดสินใจเรื่องโค้ด Windows / Desktop export ใน `pages_ui/overview.py`, `utils/local_storage.py`
- เพิ่ม ruff ใน `requirements-dev.txt`
- แตก `pages_ui/overview.py` (ราว 3,300 บรรทัด)
- เพิ่มเทสต์ให้ `data/database.py`, `utils/text_extractor.py`, `utils/excel_export.py`, การคำนวณใน `pages_ui/dashboard.py`

## ฟีเจอร์ที่รอตัดสินใจ

Excel หนึ่งไฟล์หลายแถว, OCR, เก็บไฟล์ที่รอเลือกแถวลงดิสก์ชั่วคราว, กันไฟล์ซ้ำด้วย hash, หน้าดู Audit Log, แจ้งเตือน Overdue ทางอีเมลหรือ LINE
