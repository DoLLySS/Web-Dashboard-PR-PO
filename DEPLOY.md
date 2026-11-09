# คู่มือนำระบบขึ้น Server Linux (สำหรับทีม IT)

เอกสารนี้สรุปสิ่งที่ต้องตั้งค่าและตัดสินใจก่อนใช้งานจริง

> **สถานะการทดสอบ:** ระบบทดสอบบน Linux กับ Python 3.12.3 ด้วยคำสั่ง `streamlit run` ในเครื่องพัฒนาเท่านั้น ยังไม่เคยขึ้น Server จริง ตัวอย่าง systemd และ nginx ด้านล่างยังไม่ได้ทดสอบ ควรทดลองกับผู้ใช้กลุ่มเล็กก่อน

## 1. ติดตั้งและรัน

ต้องมี Python 3.12 และแพ็กเกจ venv ของระบบ (บน Ubuntu คือ `python3-venv`)

```bash
cd /opt/masterlist                  # โฟลเดอร์โปรเจกต์ ตัวอย่างเท่านั้น
python3 -m venv venv
venv/bin/pip install -r requirements.txt
cp .env.example .env                # แล้วกรอกค่าจริง ห้าม commit ไฟล์นี้
chmod 600 .env
venv/bin/python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

- บัญชีที่รันแอปต้องเขียนได้ใน `data/` (หรือโฟลเดอร์ของ `DB_FILE_PATH`), `static/local_uploads/` และ `logs/`
- ไฟล์เอกสารเก็บที่ `static/local_uploads/` ในโฟลเดอร์โปรเจกต์เสมอ ถ้าย้ายโปรเจกต์ต้องย้ายโฟลเดอร์นี้ไปด้วย
- ค่าตั้งต้นของ Server อยู่ใน `.streamlit/config.toml` (headless, ไฟล์อัปโหลดไม่เกิน 50 MB, ป้องกัน XSRF, ปิดการส่งสถิติ, ซ่อนเมนูนักพัฒนา)
- **รัน Streamlit โปรเซสเดียวเท่านั้น** เลขเวอร์ชันข้อมูลที่ใช้ล้าง cache อยู่ในหน่วยความจำของโปรเซส (`_data_version` ใน `data/database.py`) ถ้ารันหลายโปรเซส ผู้ใช้อาจเห็นข้อมูลเก่าได้นานสูงสุด 60 วินาที

### รันเป็นบริการด้วย systemd (ตัวอย่าง)

```ini
# /etc/systemd/system/masterlist.service
[Unit]
Description=IT PR/PO Masterlist
After=network.target

[Service]
User=masterlist
WorkingDirectory=/opt/masterlist
ExecStart=/opt/masterlist/venv/bin/python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

### Reverse proxy ด้วย nginx (ตัวอย่าง)

ต้องส่งต่อ WebSocket ไม่เช่นนั้นหน้าเว็บจะโหลดไม่ขึ้น และต้องตั้ง `client_max_body_size` ให้รับไฟล์ได้เท่ากับ `maxUploadSize`

```nginx
server {
    listen 443 ssl;
    server_name masterlist.example.com;
    # ใส่ค่าใบรับรอง TLS ของบริษัทที่นี่
    client_max_body_size 50m;

    location / {
        proxy_pass http://127.0.0.1:8501;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 86400;
    }
}
```

## 2. ตัวแปรใน `.env` ที่เกี่ยวกับ Server

| ตัวแปร | ค่าบน Server | ความหมาย |
|---|---|---|
| `LOCAL_DESKTOP_EXPORT` | `0` (ค่าเริ่มต้น) | `1` = กดไอคอน File แล้วคัดลอกไฟล์ไป Desktop ของเครื่องที่รันโปรแกรม ใช้ได้เฉพาะตอนรันบนเครื่องตัวเอง ส่วน `0` = กดแล้วเปิดหน้าต่างรายการไฟล์ของแถวให้กดเปิดในเบราว์เซอร์ (แถวที่มีแต่ลิงก์ออนไลน์จะเปิดลิงก์นั้น) |
| `DB_FILE_PATH` | เช่น `/var/lib/masterlist/masterlist.db` | ที่เก็บฐานข้อมูล ต้องเป็นดิสก์ในเครื่อง ห้ามอยู่บน OneDrive หรือ network share เพราะ SQLite อาจเสียหาย ถ้าไม่ตั้งจะใช้ `data/masterlist.db` |
| `DB_JOURNAL_MODE` | `WAL` | ให้ผู้อ่านไม่ขวางผู้เขียน ใช้ได้เมื่อฐานข้อมูลอยู่บนดิสก์ในเครื่อง |
| `STORAGE_BACKEND` | `powerautomate` เมื่อ Flow พร้อม | ที่เก็บไฟล์ออนไลน์ (`gdrive` หรือ `powerautomate`) ถ้าตั้งค่าไม่ครบ ระบบจะข้ามการส่งไฟล์ออนไลน์และเก็บในเครื่องอย่างเดียว |
| `POWER_AUTOMATE_UPLOAD_URL` | URL ของ Flow | **เป็นรหัสผ่าน** (มีลายเซ็นลับในตัว) เก็บใน `.env` ที่ `chmod 600` ต้องเป็น `https://` |
| `POWER_AUTOMATE_API_KEY` | คีย์ที่ตกลงกับผู้ดูแล Flow | ไม่บังคับ ส่งใน header `X-Api-Key` |
| `POWER_AUTOMATE_TIMEOUT_SECONDS` / `POWER_AUTOMATE_MAX_FILE_MB` | `120` / `50` | รอ Flow กี่วินาที / ไฟล์ใหญ่สุดที่ส่งผ่าน Flow ปรับตามเพดานของ Flow |
| `LOG_LEVEL` | `INFO` | ระดับ log ที่เขียนลง `logs/app.log` (หมุนไฟล์อัตโนมัติ) |

**หมายเหตุ SharePoint:** อย่าตั้ง `STORAGE_BACKEND=sharepoint` โค้ดส่วนนั้นล็อกอินแบบ Client ID/Secret ผ่าน Azure ACS ซึ่ง Microsoft ประกาศเลิกใช้กับ SharePoint Online ตั้งแต่ 2 เม.ย. 2026 ([MC693863](https://mc.merill.net/message/MC693863)) ให้ใช้ `powerautomate` แทน ตอนนี้โค้ดฝั่งแอปเสร็จและทดสอบกับ Flow ปลอมแล้ว แต่ **ยังไม่เคยใช้กับ Flow จริง** ตรวจ Flow ด้วย `venv/bin/python scripts/check_flow.py` (ส่งไฟล์ทดสอบไปโฟลเดอร์ `_connection_test` เท่านั้น) ดู `NEXT_STEPS.md`

## 3. สิ่งที่ต้องตัดสินใจหรือตั้งค่าฝั่ง IT

1. **ล็อกอินและสิทธิ์** ตอนนี้ระบบไม่มีล็อกอิน ใครเข้า URL ได้ก็ดู แก้ และลบข้อมูลถาวรได้ ทางเลือกคือ
   - วางหลัง reverse proxy ที่บังคับ SSO ของบริษัท (แนะนำ เพราะไม่ต้องแก้โค้ด และกันไฟล์ตามข้อ 2 ได้ด้วย)
   - ใช้ `st.login()` ของ Streamlit ซึ่งต้องเพิ่มโค้ด และไม่ได้กันไฟล์ตามข้อ 2
2. **ไฟล์เอกสารเปิดได้โดยไม่ล็อกอิน** ไฟล์ใน `static/local_uploads/` ถูกเสิร์ฟที่ `/app/static/...` ใครรู้ลิงก์ก็เปิดได้ ห้ามเปิดพอร์ตสู่อินเทอร์เน็ต
3. **HTTPS** ทำที่ reverse proxy
4. **Firewall** เปิดพอร์ตให้เฉพาะเครือข่ายภายในบริษัท ถ้าใช้ proxy ให้แอปฟังที่ `127.0.0.1` ตามตัวอย่าง
5. **สำรองข้อมูล** ตั้ง cron ให้รัน `scripts/backup.py` รันได้ขณะแอปทำงาน เก็บ 14 ชุดล่าสุด (ปรับด้วย `--keep`) ปลายทางควรอยู่คนละดิสก์กับข้อมูลจริง และห้ามอยู่ใน `static/` วิธีกู้คืนอยู่ในหัวข้อ 5
   ```
   30 1 * * * cd /opt/masterlist && venv/bin/python scripts/backup.py --dest /mnt/backup/masterlist >> logs/backup.log 2>&1
   ```
6. **ความลับ** ตั้ง `.env` และไฟล์ key (เช่น Google Service Account) เป็น `chmod 600` ให้บัญชีที่รันแอปอ่านได้คนเดียว

## 4. ข้อจำกัดที่ควรรู้

- ฐานข้อมูลเป็น SQLite เหมาะกับทีมเล็ก ยังไม่ได้ทดสอบกับผู้ใช้หลายคนพร้อมกัน ถ้าต้องการรองรับผู้ใช้มากหรือ High Availability ต้องย้ายไปฐานข้อมูลแบบ server ซึ่งเป็นงานแยก
- การลบแถวในตารางเป็นการลบถาวรพร้อมไฟล์ในเครื่อง กู้คืนได้จากชุดสำรองเท่านั้น ไฟล์บนที่เก็บออนไลน์ไม่ถูกลบ
- โค้ดเปิด Explorer และคัดลอกไฟล์ไป Desktop (`LOCAL_DESKTOP_EXPORT`) ยังอยู่ในโปรแกรม แต่ไม่มีประโยชน์บน Server

## 5. สำรอง กู้คืน และล้างข้อมูลเก่า

### กู้คืนจากชุดสำรอง

ชุดสำรองแต่ละชุดคือโฟลเดอร์ `backup_ปปปปดดวว_ชชนนวว/` มี `masterlist.db` และ `local_uploads.tar.gz` หยุดแอปก่อน แล้วรัน

```bash
cp <ชุดสำรอง>/masterlist.db <ไฟล์ฐานข้อมูล>
rm -f <ไฟล์ฐานข้อมูล>-wal <ไฟล์ฐานข้อมูล>-shm
tar -xzf <ชุดสำรอง>/local_uploads.tar.gz -C <โปรเจกต์>/static
```

คำสั่ง `tar` แตกทับโฟลเดอร์เดิมโดยไม่ลบไฟล์ที่เพิ่มหลังวันที่สำรอง ถ้าต้องการให้ตรงกับชุดสำรองทุกไฟล์ ให้ย้าย `static/local_uploads/` เดิมออกก่อน

### ล้างแถวเก่าที่ถูกซ่อนและรายละเอียดใน Audit Log

รุ่นก่อนลบแถวด้วยการซ่อนไว้ แถวและไฟล์จึงยังอยู่ในระบบ ใช้ `scripts/purge_deleted.py` ล้างครั้งเดียว Audit Log ของแถวที่ลบแล้วจะเหลือวันเวลา ประเภทการกระทำ และรหัสแถว ส่วนแถวที่ใช้งานอยู่และ log ของแถวเหล่านั้นไม่ถูกแตะ

`scripts/backup.py` และ `scripts/purge_deleted.py` ใช้เฉพาะ Python มาตรฐาน (บวก `utils/file_removal.py`) จึง **คัดลอก `scripts/` กับ `utils/__init__.py` และ `utils/file_removal.py` ไปรันที่โฟลเดอร์อื่นได้ โดยไม่ต้องอัปเดตโค้ดหรือ venv ของแอปจริง** ให้ระบุ path จริงเองด้วย `--db <ไฟล์ฐานข้อมูล>` และ `--uploads <โฟลเดอร์ local_uploads>` (ถ้าไม่ระบุ ใช้ `DB_FILE_PATH` หรือ `data/masterlist.db` และ `static/local_uploads` ในโปรเจกต์) ถ้าแถวอ้างถึงไฟล์แต่ไม่พบไฟล์ใดเลยในโฟลเดอร์ที่ระบุ สคริปต์จะไม่ล้างให้ เพราะน่าจะระบุ `--uploads` ผิด

1. ดูสรุปก่อน คำสั่งนี้ไม่เปลี่ยนอะไร: `python3 scripts/purge_deleted.py --db <ไฟล์ฐานข้อมูล> --uploads <local_uploads>`
2. หยุดแอป แล้วสั่งล้าง ระบบสำรองข้อมูลให้ก่อนเสมอ และให้พิมพ์ `PURGE` เพื่อยืนยัน: เพิ่ม `--apply --dest /mnt/backup/masterlist_before_purge` ต่อท้ายคำสั่งเดิม
   ถ้าไม่ใส่ `--dest` ชุดสำรองจะอยู่ที่ `backups/before_purge/` ข้างสคริปต์
3. เปิดแอปใหม่และตรวจตาราง

สำรองทั้งโค้ดด้วยเมื่อจะอัปเดตโค้ด: `python3 scripts/backup.py --db ... --uploads ... --code <โฟลเดอร์โปรเจกต์> --dest <ที่เก็บ>` ได้ `code.tar.gz` (ไม่รวม venv, ฐานข้อมูล, ไฟล์เอกสารและ logs แต่ **รวม `.env` ที่มีรหัสลับ**) พร้อม `MANIFEST.sha256` ตรวจด้วย `sha256sum -c MANIFEST.sha256` ชุดสำรองตั้งสิทธิ์ให้เจ้าของอ่านได้คนเดียว

ชุดสำรองมีข้อมูลเก่าครบ รวม Description และ Company จึงต้องเก็บในที่ปลอดภัย และลบเองเมื่อไม่ต้องการแล้ว สคริปต์ไม่ลบไฟล์บนที่เก็บออนไลน์และไฟล์ใน `data/local_uploads/` ส่วนจำนวนที่เกี่ยวข้องจะแสดงในสรุป
