# Resume State — IT PR/PO & Tax Invoice MasterList

อัปเดตล่าสุด: 2026-10-27 — จุดเซฟนี้คือ Git commit ล่าสุดบน branch `master` (ดู `git log -1`)
ย้อนกลับมาจุดนี้ได้ด้วย `git checkout <hash> -- .`

วิธีรัน: `python -m streamlit run app.py` (ติดตั้ง: `pip install -r requirements.txt`)

## 1. โครงสร้างหลัก

- `app.py` — Router อย่างเดียว: ฉีดธีม, Sidebar, หัวหน้า (ชื่อหน้า + Date Filter), เรียกหน้าที่เลือก
- `config/styles.py` — CSS กลางทั้งแอป (ธีม, Responsive, หัวข้อ gradient, Date Filter, ปฏิทิน, ไอคอนปฏิทิน)
- `ui_grid.py` — ตาราง AgGrid (`build_grid_options`, `show_grid`)
- `pages_ui/overview.py` — แจ้งเตือนค้าง 14 วัน (การ์ดเตือน + expander + ตารางเต็มความกว้าง), ตารางหลัก, ฟอร์ม/อัปโหลด
- `pages_ui/dashboard.py`, `sidebar_ui.py`, `data/database.py` (SQL อยู่ที่นี่ที่เดียว), `utils/text_extractor.py`
- ความลับ (SHAREPOINT_*) โหลดจาก `.env` ซึ่งไม่อยู่ใน Git; `.env.example` เป็นข้อมูลหลอก

## 2. งานที่เสร็จใน session นี้

- ฟอร์ม "กรอก Form", อัปโหลดไฟล์ (รอบ A/B/C), Status dropdown
- รอบ D (หน้า Overview): หัวข้อใหญ่ gradient, Date filter กระชับ + animation, การ์ดแจ้งเตือนค้างแบบเร่งด่วน, ตารางค้างเต็มความกว้าง, animation เปิด/ปิด expander
- รอบ E (ปฏิทิน): ขนาดคงที่ 300x320px ทุกเดือน, animation pop-in, ไอคอนปฏิทินใหม่ (gradient + mask)

## 3. ยังไม่ได้ตรวจ / ข้อจำกัด

- animation ตอนเคลื่อนไหวจริง และจอสัมผัส ตรวจจากภาพนิ่ง/ค่า computed style เท่านั้น
- ปฏิทิน/ไอคอนใช้กับช่องวันที่ทุกช่อง รวมฟอร์มเพิ่มข้อมูล แต่ยังไม่ได้เปิดดูในฟอร์ม
- ยังไม่ได้ดูหัวหน้า Dashboard หลังเปลี่ยนสไตล์หัวข้อ
- SharePoint จริงและฐานข้อมูลจริงยังไม่ได้ทดสอบ
- แจ้งเตือน Line OA เป็นฟีเจอร์ในอนาคต (มีคอมเมนต์ระบุจุดวางปุ่มใน `build_overdue_alert_html`)
- CSS ผูกกับ Streamlit 1.66.1 (selector `data-testid`, โดยเฉพาะ `stDateInputCalendar`) ถ้าอัปเกรดแล้วสไตล์หลุดให้ตรวจ DOM ใหม่

## 4. Next Step พรุ่งนี้

1. เปิดแอป กด Ctrl+F5 ดูภาพรวมทุกหน้า (Overview, Dashboard, ฟอร์มเพิ่มข้อมูล) ว่าสไตล์ใหม่ไม่ทำให้อะไรเพี้ยน
2. รับ feedback รอบถัดไปจากผู้ใช้
3. เชื่อม SharePoint จริงผ่าน `.env` เมื่อพร้อม และเตรียมฟีเจอร์ Line OA
