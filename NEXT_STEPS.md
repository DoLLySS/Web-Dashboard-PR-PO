# NEXT_STEPS — บันทึกช่วยจำสำหรับวันกลับมาทำต่อ

อัปเดตล่าสุด: 2026-10-26 (Save point: Local MVP complete)

## 1. สถานะปัจจุบัน: ระบบ Local ทำงานสมบูรณ์

ใช้งานจริงในเครื่องได้ครบ โดยไม่ต้องพึ่ง SharePoint

| ฟีเจอร์ | รายละเอียด |
|---|---|
| Master-List | เพิ่ม / แก้ไขในตาราง / ลบรายการ PR/PO และใบกำกับภาษี เก็บใน SQLite (`data/`) |
| ดึงข้อมูลจากไฟล์ | อ่าน PDF/Excel แล้วเติม TaxID, Vendor, Net Price ลงฟอร์มให้อัตโนมัติ (`utils/text_extractor.py`) |
| เก็บไฟล์แนบ | บันทึกลง `data/local_uploads/` แล้วผูกกับรายการ (`utils/local_storage.py`) |
| แจ้งเตือน | Banner เตือนรายการค้างใบกำกับภาษีเกินกำหนด |
| Dashboard | สรุปยอดตามสถานะ และ Net Price |
| Logging | บันทึกลง `logs/app.log` (หมุนไฟล์อัตโนมัติ) ตั้งระดับด้วย `LOG_LEVEL` ใน `.env` |
| ความทนทาน | `init_db()` ทำครั้งเดียวต่อการรัน กัน "database is locked", ดัก Error แบบเจาะจง, ค่า `.env` ผิดไม่ทำให้แครช |

## 2. สิ่งที่ต้องทำเมื่อได้สิทธิ์ SharePoint

**ขั้นที่ 1 — ขอข้อมูลจากผู้ดูแล SharePoint/Azure**
- URL ของ Site, Client ID, Client Secret (App ต้องมีสิทธิ์เขียนใน Site นั้น)
- โฟลเดอร์ปลายทางต้องมีอยู่แล้วบน SharePoint (ค่าเริ่มต้น `Shared Documents/PR-PO`)

**ขั้นที่ 2 — เติมค่าใน `.env`** (คัดลอกจาก `.env.example`; ห้าม commit `.env`)
```
SHAREPOINT_URL=https://<บริษัท>.sharepoint.com/sites/<ชื่อ site>
SHAREPOINT_CLIENT_ID=<Application (client) ID>
SHAREPOINT_CLIENT_SECRET=<Client Secret>
SHAREPOINT_FOLDER_PATH=Shared Documents/PR-PO   # ไม่บังคับ
```

**ขั้นที่ 3 — เปิดใช้โค้ดใน `pages_ui/overview.py`** (มี 2 จุด)
1. ใกล้บรรทัด 38-39: ปลดคอมเมนต์ `from utils.sharepoint_api import SharePointError, upload_document_to_sharepoint`
2. ฟังก์ชัน `save_document_and_get_path()` ใกล้บรรทัด 315: **แทนที่** บล็อก `try ... save_document_locally ... except LocalStorageError` ด้วยบล็อก SharePoint ที่คอมเมนต์ไว้ข้างล่าง (อย่าแค่ปลดคอมเมนต์ เพราะโค้ดเดิมมี `return` ก่อนแล้ว โค้ดใหม่จะไม่ถูกรัน)
   - ถ้าอยากเก็บสำรองในเครื่องด้วย ให้เรียก `save_document_locally` ก่อน แล้วค่อยอัปโหลดขึ้น SharePoint

**ขั้นที่ 4 — ตรวจ `utils/sharepoint_api.py`**
- วิธีหลัก (Client ID/Secret) ทำงานอยู่แล้ว ไม่ต้องปลดคอมเมนต์อะไร
- ปลดคอมเมนต์ `UserCredential` เฉพาะกรณีไม่มี App/Secret และบัญชีไม่เปิด MFA (ทำตามขั้นตอนในคอมเมนต์ของไฟล์ + ใส่ `SHAREPOINT_USERNAME/PASSWORD` ใน `.env`)

**ขั้นที่ 5 — ทดสอบ**
1. รีสตาร์ทแอป (ต้องรีสตาร์ทเพื่อให้โหลด `.env` ใหม่)
2. อัปโหลดไฟล์ทดสอบ 1 ไฟล์ → ตรวจว่าไฟล์ขึ้นในโฟลเดอร์บน SharePoint และไอคอนไฟล์ในตารางเปิดลิงก์ได้
3. ถ้า Error: ข้อความไทยบนหน้าจอบอกสิ่งที่ควรตรวจ และดูรายละเอียดใน `logs/app.log`

## 2.4 ทดสอบส่งไฟล์ขึ้น Google Drive (แทน SharePoint ระหว่างรอสิทธิ์)

ไฟล์จากหน้า Upload / ฟอร์ม จะถูกส่งไปที่ `<โฟลเดอร์ราก>/ปี/เดือน/วัน/Vendor/` (ใช้วันที่อัปโหลดจริง) ผ่าน `utils/storage_backend.py`
1. สร้าง Service Account ใน Google Cloud (เปิด Drive API) แล้วดาวน์โหลดไฟล์ JSON key เก็บไว้นอกโปรเจค/Git
2. สร้างโฟลเดอร์ใน **Shared Drive** (Service Account ไม่มีพื้นที่เก็บของตัวเองใน My Drive) แล้วแชร์ให้อีเมลของ Service Account แบบ Editor
3. ใส่ใน `.env`: `STORAGE_BACKEND=gdrive`, `GDRIVE_SERVICE_ACCOUNT_FILE=<path ของ JSON key>`, `GDRIVE_ROOT_FOLDER_ID=<ID โฟลเดอร์>` แล้วรีสตาร์ทแอป
4. เมื่อได้สิทธิ์ SharePoint: เปลี่ยนเป็น `STORAGE_BACKEND=sharepoint` (โครงโฟลเดอร์เดียวกัน; ส่วนสร้างโฟลเดอร์ย่อยบน SharePoint ยังไม่เคยทดสอบจริง)
   - เมื่อ SharePoint ตั้งค่าครบ: ตอน Upload ระบบสร้างโฟลเดอร์ `ปี/เดือน(Jan..Dec)/วัน/Vendor` แล้วส่งไฟล์ขึ้นทันที และเก็บ **ลิงก์โฟลเดอร์** ลงคอลัมน์ File — ไอคอน File จะเปิดโฟลเดอร์นั้นในแท็บใหม่ (`utils/sharepoint_api.py` `build_folder_url`; รูปลิงก์ `Forms/AllItems.aspx?id=` ยังไม่ยืนยันกับ SharePoint จริง)
   - แถวที่ยังไม่มีลิงก์ออนไลน์ ไอคอนยังคัดลอกไฟล์ไป Desktop เหมือนเดิม
   - **เมื่อได้สิทธิ์และยืนยันแล้ว ให้ลบฟีเจอร์ Desktop**: `export_files_to_desktop` + `get_desktop_directory` ใน `utils/local_storage.py`, `handle_file_icon_click` / `find_clicked_file_position` / `_open_folder_in_explorer` ใน `pages_ui/overview.py` (+ `cellClicked` ใน `update_on`) และกิ่ง `isLocalFile` ใน `FILE_LINK_RENDERER_JS`
5. Master-List: `utils/masterlist_client.py` เป็น stub รอ API (ตั้ง `MASTERLIST_API_URL` และเติมการเรียกจริงใน `send_to_masterlist`)

## 2.5 ภารกิจหลักรอบถัดไป: AgGrid + Typography

1. ยกเลิกตาราง Streamlit พื้นฐาน และติดตั้ง `streamlit-aggrid` สำหรับหน้า Overview และ Dashboard
2. ปรับแต่ง GridOptions ขยายขนาดตัวอักษรและเพิ่มระยะห่าง (Padding) ให้ตารางอ่านง่ายและดูเป็น Enterprise
3. อัปเกรด Typography ฝัง Global CSS ขยายขนาดฟอนต์ของ Popup, เมนู และปุ่มต่างๆ ให้สมมาตรกับหน้าจอใหญ่

สถานะตอน save point: โค้ดร่างของทั้ง 3 ข้อมีอยู่แล้ว (`ui_grid.py` เป็นโมดูลตารางกลาง, `requirements.txt` ปักเวอร์ชัน `streamlit-aggrid`, ฟอนต์ตั้งใน `.streamlit/config.toml` และ `config/styles.py`)
แต่ตอนนี้ **ทดสอบกับข้อมูลสาธิตเท่านั้น** ให้ตรวจซ้ำกับข้อมูลจริงก่อนถือว่าเสร็จ
- หลัง pull ต้องรัน `pip install -r requirements.txt`
- ที่จอประมาณ 1366px ถ้าเปิด sidebar จะมีแถบเลื่อนแนวนอนเล็กน้อย; คอลัมน์ Vendor/Item/Tel/PR No. ถูกตัดด้วย "…" บนจอแคบ (ชี้เมาส์ดูข้อความเต็ม)
- ปรับความกว้างคอลัมน์ได้ที่ `TABLE_COLUMN_WIDTHS` ใน `pages_ui/overview.py` และธีมที่ `ui_grid.py`

## 3. ข้อควรระวัง / งานค้างที่รู้อยู่แล้ว

- **ยังไม่เคยทดสอบกับ SharePoint จริง** อาจต้องปรับเล็กน้อยตอนต่อจริง
- ไฟล์เก่าที่อยู่ใน `data/local_uploads/` จะไม่ถูกย้ายขึ้น SharePoint อัตโนมัติ (ต้องเขียนสคริปต์ย้ายเองถ้าต้องการ)
- โฟลเดอร์โปรเจคอยู่ใน OneDrive: ค่าเริ่มต้นไม่เปิดโหมด WAL ของ SQLite ตั้งใจ (ไฟล์ `-wal/-shm` ที่ถูก sync อาจทำให้ DB เสีย) บน Server ให้ตั้ง `DB_FILE_PATH` ชี้ดิสก์ในเครื่อง + `DB_JOURNAL_MODE=WAL` ใน `.env`
- การนำขึ้น Server: ดู `DEPLOY.md` (ล็อกอิน/SSO, HTTPS, service, backup เป็นงานฝั่ง IT) และ `LOCAL_DESKTOP_EXPORT` ต้องเป็น `0` บน Server (ฟีเจอร์ Desktop ยังไม่ลบ จะลบเมื่อได้สิทธิ์ SharePoint)
- ถ้าบันทึกรายการไม่สำเร็จแล้วกดซ้ำ ไฟล์แนบอาจถูกบันทึกซ้ำใน `local_uploads/` (ไฟล์เหลือทิ้งเล็กน้อย)
- `planning.md` เป็นเอกสารช่วงแรก อาจไม่ตรงกับโครงสร้างปัจจุบัน ให้ยึด `README.md` เป็นหลัก
- `generate_mock_data.py` ยังใช้ `print()` (เป็นสคริปต์ CLI ตั้งใจไว้)
