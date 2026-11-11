# NEXT_STEPS — งานที่เหลือ

อัปเดตล่าสุด: 2026-11-09

## 1. สถานะปัจจุบัน

ระบบทำงานในเครื่องได้ครบโดยไม่ต้องใช้ที่เก็บออนไลน์ ดูรายการฟีเจอร์และข้อจำกัดใน `README.md` และการนำขึ้น Server ใน `DEPLOY.md`

ยังไม่ได้เชื่อม SharePoint, Master-List หรือ Server จริง

## 2. เชื่อม SharePoint ผ่าน Power Automate

**ไม่ใช้ `utils/sharepoint_api.py` แล้ว** โค้ดนั้นล็อกอินแบบ Client ID/Secret ผ่าน Azure ACS ซึ่ง Microsoft ประกาศเลิกใช้กับ SharePoint Online ตั้งแต่ 2 เม.ย. 2026 ([MC693863](https://mc.merill.net/message/MC693863))

แนวทาง: แอปส่งไฟล์ไปที่ HTTP trigger ของ Flow แล้ว Flow สร้างโฟลเดอร์ `ปี/เดือน/วัน/ชื่อ` ใน Document Library และตอบลิงก์กลับ ไฟล์ในเครื่องยังเป็นต้นฉบับ ถ้าส่งออนไลน์ไม่สำเร็จ แถวและไฟล์ในเครื่องยังอยู่ และระบบแจ้งเตือน

**S0 — ข้อมูลที่ต้องถาม IT (ยังไม่ต้องเขียนโค้ด)**
1. สิทธิ์ใช้ HTTP trigger ของ Power Automate (ปกติเป็นฟีเจอร์ Premium)
2. Site URL, ชื่อ Document Library และโฟลเดอร์ราก พร้อมไลบรารีทดสอบที่ว่าง
3. เจ้าของ Flow ควรเป็นบัญชีบริการหรือกลุ่ม ไม่ใช่บุคคล และ connection ต้องเขียนไลบรารีได้
4. นโยบายของ tenant ว่า HTTP trigger ให้ใครเรียกได้ (ตรวจกับเอกสาร Microsoft ปัจจุบัน)
5. เพดานขนาดคำขอและเวลาตอบของ Flow เทียบกับไฟล์ 50 MB (base64 ใหญ่ขึ้นราว 1/3) ถ้าไม่พอต้องแบ่งส่งเป็นชิ้น
6. ต้องส่งข้อมูลแถวเข้า Master-List ด้วยหรือไม่ และเมื่อลบแถวต้องลบไฟล์ออนไลน์ด้วยหรือไม่

**S1 — กำหนดรูปแบบการส่ง**
- คำขอต่อ 1 ไฟล์: `{requestId, folderParts[], fileName, contentBase64, sha256}` (`requestId` เป็น UUID ที่เท่ากันทุกครั้งที่ retry ให้ Flow กันสร้างไฟล์ซ้ำ; `fileName` ผ่านการแทนอักขระต้องห้ามของ SharePoint แล้ว)
- คำตอบ: `{fileUrl, folderUrl}` หรือ `{error}`
- URL ของ Flow มีลายเซ็นลับในตัว ถือเป็นรหัสผ่าน เก็บใน `.env` (`POWER_AUTOMATE_UPLOAD_URL`) ห้ามลง log หรือ Git และเพิ่ม header `X-Api-Key` (`POWER_AUTOMATE_API_KEY`) ให้ Flow ตรวจซ้ำ

**S2 — เขียนโค้ด: เสร็จ** `utils/power_automate_api.py` และ backend `powerautomate` ใน `utils/storage_backend.py` (ส่งทีละไฟล์, ลิงก์โฟลเดอร์มาจากคำตอบของ Flow, ไม่เปิดเผย URL/คีย์, ไม่ตาม redirect, retry เฉพาะ 429/503, ไม่ retry เมื่อ timeout / 502 / 504 / การเชื่อมต่อหลุด เพราะ Flow อาจสร้างไฟล์ไปแล้ว) 

**S2b — ส่ง Master-List ผ่าน Flow: เสร็จ (ทดสอบกับ Flow ปลอมเท่านั้น)** `utils/masterlist_client.py` ส่ง `POST {requestId, record}` (record = 13 ฟิลด์ใน `MASTERLIST_FIELDS` ไม่มีไฟล์/path) ไปที่ `MASTERLIST_API_URL` (+ `MASTERLIST_API_KEY`, `MASTERLIST_TIMEOUT_SECONDS` ค่าเริ่มต้น 30) คาดคำตอบ `{"ok": true}` ใช้แกนส่ง HTTP เดียวกับการส่งไฟล์ (ไม่ตาม redirect, ต้อง https (ยกเว้นตัวเลือก `MASTERLIST_ALLOW_HTTP=1` ที่รับ http ไป IP ภายในเฉพาะ Master-List ไว้ทดสอบ ค่าเริ่มต้นปิด ก่อนใช้จริงต้องเป็น https), ไม่ลง log ซึ่ง URL/คีย์, retry เฉพาะ 429/503 ด้วย `requestId` เดิม) ส่งล้มหรือช้าแล้วแถวและไฟล์ในเครื่องยังอยู่ และสรุปหลังอัปโหลดแจ้งว่า Master-List ส่งไม่สำเร็จ timeout/502/504/คำตอบเพี้ยนไม่ retry เพราะ Flow อาจสร้างรายการไปแล้ว **ยังไม่มี:** ปุ่มส่งแถวนี้ซ้ำ และสถานะ "ส่งแล้ว/ยัง" ต่อแถวในฐานข้อมูล สัญญาและปลายทางจริงรอ IT ยืนยัน (S0 ข้อ 6)

**S3 — เทสต์กับเซิร์ฟเวอร์ปลอม: เสร็จ** `tests/test_power_automate.py` ครอบคลุมสำเร็จ, 4xx/5xx, retry, timeout, JSON เพี้ยน, redirect, URL ไม่ปลอดภัย, ความลับไม่โผล่ใน log, ส่งไม่สำเร็จแล้วแถวและไฟล์ในเครื่องยังอยู่

**S4 — สร้าง Flow:** trigger พร้อม schema, ตรวจ `X-Api-Key`, สร้างโฟลเดอร์ซ้อนชั้น (ต้องลองจริงว่าสร้างซ้ำแล้ว error หรือไม่), สร้างไฟล์, ตอบลิงก์ และเปิดการแจ้งเตือนเมื่อ Flow ล้มเหลว

**S5 — ทดสอบกับไลบรารีว่าง:** รัน `venv/bin/python scripts/check_flow.py` (ส่งไฟล์ทดสอบเล็ก ๆ ไปโฟลเดอร์ `_connection_test`) ก่อน แล้วทดสอบทั้งแอปบนสำเนาข้อมูล ทั้งชื่อไฟล์ซ้ำ ชื่อภาษาไทย ไฟล์ใหญ่ และกรณี Flow ปิดหรือล้มเหลว

**S6 — เปิดใช้งาน:** ตั้งค่าใน `.env` ตัดสินใจเรื่องการย้ายไฟล์เดิมขึ้น SharePoint และนโยบายการลบไฟล์ออนไลน์ จากนั้นพิจารณาลบ `utils/sharepoint_api.py` พร้อม `Office365-REST-Python-Client`

## 3. Google Drive (ใช้ทดสอบระหว่างยังไม่มี SharePoint)

1. สร้าง Service Account ใน Google Cloud เปิด Drive API แล้วเก็บไฟล์ JSON key ไว้นอกโปรเจกต์
2. สร้างโฟลเดอร์ใน **Shared Drive** (Service Account ไม่มีพื้นที่ของตัวเองใน My Drive) แล้วแชร์ให้อีเมลของ Service Account แบบ Editor
3. ใส่ `STORAGE_BACKEND=gdrive`, `GDRIVE_SERVICE_ACCOUNT_FILE` และ `GDRIVE_ROOT_FOLDER_ID` ใน `.env` แล้วรีสตาร์ทแอป

## 4. งานถัดไป

**จัดระเบียบโค้ด (ไม่เปลี่ยนพฤติกรรม)**
- ลบโค้ดที่ไม่มีใครเรียก: `ui_common.render_equipment_table`, `submit_pipeline.find_pr_folder_by_description`, `text_extractor.extract_fields_from_file` (และตรวจเพิ่ม: `ui_grid.render_readonly_grid`, `overview.TABLE_COLUMN_HELP`, `database.delete_transaction` ที่ใช้ในเทสต์เท่านั้น)
- ตัดสินใจเรื่องโค้ด Windows และโหมด Desktop export ใน `pages_ui/overview.py` และ `utils/local_storage.py`
- เพิ่ม ruff ใน `requirements-dev.txt` และแตก `pages_ui/overview.py` (ประมาณ 3,300 บรรทัด) เป็นโมดูลย่อย
- เพิ่มเทสต์ `data/database.py`, `utils/text_extractor.py`, `utils/excel_export.py` และการคำนวณใน `pages_ui/dashboard.py`

**ส่งล้มกลางชุด ทาง B (หลัง IT ยืนยัน `requestId` ของ Flow จริง):** คอลัมน์ "ไฟล์ที่ยังไม่ขึ้นออนไลน์" + ปุ่มส่งซ้ำเฉพาะที่ค้าง + แถบเตือนค้าง (ตอนนี้ทำทาง A: เก็บลิงก์ไฟล์ที่ส่งแล้วและบอกไฟล์ที่ค้างตอนอัปโหลด)

**ต้องให้เจ้าของงานตัดสินใจ:** การรวมแถวด้วยคีย์ Description+Company+Tel (ข้อ 9 ของรีวิว) และ "ลบถาวร" vs หน้าว่างของไฟล์ DB/ชุดสำรอง (`secure_delete`, ข้อ 25) รายการทำทีหลังอื่น ๆ ดู `handoff/03_PENDING_ACTIONS.md`

**ฟีเจอร์ที่รอตัดสินใจ:** Excel หนึ่งไฟล์หลายแถว, OCR, เก็บไฟล์ที่รอเลือกแถวลงดิสก์ชั่วคราว, กันไฟล์ซ้ำด้วย hash, หน้าดู Audit Log, แจ้งเตือน Overdue ทางอีเมลหรือ LINE

## 5. ข้อควรระวังที่รู้อยู่แล้ว

- เกณฑ์ค้าง 14 วันนับจากวันอัปโหลดเป็นการชั่วคราว รอเจ้าของงานยืนยันว่าควรนับจากวันใด (`OVERDUE_RULE` ใน `config/constants.py`)
- ไฟล์ที่จับคู่กับ PR ได้และไม่มีคำบอกว่าเป็นเอกสารอื่น จะถูกนับเป็นใบกำกับ จึงเปลี่ยนสถานะผิดได้ ผู้ใช้แก้กลับเป็น Pending ในตารางได้ แต่ไฟล์ที่แนบแล้วยังอยู่
- ไฟล์ที่รอเลือกแถวเก็บอยู่ในเซสชันของเบราว์เซอร์ รีเฟรชแล้วหาย
- ถ้าโฟลเดอร์โปรเจกต์อยู่บน OneDrive ห้ามใช้ `DB_JOURNAL_MODE=WAL` เพราะไฟล์ `-wal` / `-shm` ที่ถูก sync อาจทำให้ฐานข้อมูลเสีย
- CSS ผูกกับ Streamlit 1.66.1 (selector `data-testid`) ถ้าอัปเกรดต้องตรวจหน้าจอใหม่
