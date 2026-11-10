# Resume State — IT PR/PO & Tax Invoice MasterList

อัปเดตล่าสุด: 2026-11-09 (ปิดงานวันนี้ ผู้ใช้กลับมาต่อพรุ่งนี้) branch `master` ฐานโค้ดล่าสุดที่ทดสอบและส่งงานได้คือ commit **`2ce30d5`** (โค้ดแอปไม่เปลี่ยนหลังจากนั้น มีแค่เอกสาร: `handoff/` ใน `76e5e00` และไฟล์นี้)
ยังไม่เคย push: local นำ `origin/master` (`d69d911`) อยู่ 12 commit (9 commit ของงานจริง + `76135fd` + `76e5e00` handoff + commit ของไฟล์นี้) ผู้ใช้สั่งไว้ว่า **ยังไม่ต้อง push**
ไฟล์ `.vscode/settings.json` มีการแก้ค้างอยู่ ไม่ใช่ของผู้ช่วย **ห้ามรวมใน commit**

**อัปเดต 2026-11-10:** S2b (ส่ง Master-List ผ่าน Flow ปลอม) ทำแล้วใน commit `187c245` และ `e6ae19f` ดู `NEXT_STEPS.md` หัวข้อ S2b และ `handoff/00_SUMMARY.md` (ผลทดสอบและ checksum ล่าสุดอยู่ที่นั่น ไม่ใช่ตารางข้างล่างซึ่งเป็นของวันที่ 2026-11-09)

อ่านคู่กับ: `README.md` (ภาพรวมและข้อจำกัด), `DEPLOY.md` (ขึ้น Linux, สำรอง, กู้คืน, ล้างข้อมูลเก่า), `NEXT_STEPS.md` (แผน Power Automate S0–S6)

---

## 1. ทำเสร็จแล้ว (ทุกอย่างอยู่ใน git)

| Commit | เนื้อหา |
|---|---|
| `7a7b00d` | ไฟล์ที่จับคู่ PR ได้และไม่ใช่เอกสารอื่น เปลี่ยนแถวเป็น Completed ทันที, ลบแถวถาวรพร้อมไฟล์ในเครื่อง, หน้ายืนยันก่อนลบ, `scripts/backup.py` ตัวแรก |
| `ee41a5a` | ลบแถวแล้วล้างรายละเอียดใน Audit Log ของแถวนั้น, `scripts/purge_deleted.py` ล้างแถวที่เคยถูกซ่อนไว้ |
| `752b73e` | เอกสารขั้น 2: `DEPLOY.md` สำหรับ Linux, `README.md`, `NEXT_STEPS.md`, `.env.example` ให้ตรงกับโค้ด |
| `a50da50` | เครื่องมือสำรอง/ล้างแบบ **รันเดี่ยว** (Python มาตรฐานเท่านั้น, `utils/file_removal.py`, `--db`/`--uploads`/`--code`, `MANIFEST.sha256`, กันระบุ path ผิด) |
| `2ce30d5` | ส่งไฟล์ขึ้น SharePoint ผ่าน **Power Automate** (`utils/power_automate_api.py`, backend `powerautomate`, `scripts/check_flow.py`) ทดสอบกับ Flow ปลอมเท่านั้น + ปรับเอกสาร |

ความสามารถที่เพิ่มตลอดรอบนี้ (สรุป):
- **ใบกำกับ → Completed:** ไฟล์ที่มีคำว่าใบกำกับ หรือไฟล์ที่ตรงกับ PR และไม่ได้บอกว่าเป็นใบเสนอราคา/คู่เทียบ/ใบสั่งซื้อ เปลี่ยนสถานะทันทีและแจ้งผู้ใช้ว่าเดาจากการจับคู่ แก้กลับในตารางได้ ใบกำกับที่จับคู่เองไม่ได้ให้ผู้ใช้เลือกแถว
- **ลบแถว:** ลบถาวรทั้งแถวและไฟล์ในเครื่อง (ไม่ลบไฟล์ที่แถวอื่นยังใช้) ต้องยืนยันก่อน Audit Log ของแถวที่ลบเหลือแค่วันเวลา/ประเภท/รหัสแถว ไม่ลบไฟล์บนที่เก็บออนไลน์
- **เครื่องมือสำรอง/ล้าง:** รันเดี่ยวได้โดยไม่ต้องอัปเดตโค้ดแอป วิธีใช้อยู่ใน `DEPLOY.md` หัวข้อ 5
- **Power Automate:** URL ของ Flow ถือเป็นรหัสผ่าน ไม่ลง log/ข้อความ error, ต้องเป็น https (ยกเว้นเครื่องตัวเองตอนทดสอบ), ไม่ตาม redirect, retry เฉพาะ 429/502/503/504, ไม่ retry เมื่อ timeout (กันไฟล์ซ้ำ), ส่งไม่สำเร็จแล้วแถวและไฟล์ในเครื่องยังอยู่

## 2. กำลังทำอะไรอยู่

ผู้ใช้สั่งแผน 3 ข้อ ทำทีละข้อและสรุปให้ดูก่อนไปข้อต่อไป:
1. โค้ดที่เหลือ (Power Automate S2–S3 + เครื่องมือรันเดี่ยว) — **เสร็จ**
2. ทดสอบทั้งระบบบน 8599 + รันเทสต์ทั้งหมด — **เสร็จ** (ผลในหัวข้อ 4)
3. **ชุดส่งงานให้ทีม — เขียนเสร็จและ commit แล้ว** (`76e5e00`, โฟลเดอร์ `handoff/` 4 ไฟล์) รอผู้ใช้อ่านทวนและส่งให้หัวหน้า/IT

ไฟล์ส่งงานที่สร้างแล้ว (อยู่ใน `deliverables/` ของ scratchpad และสำรองไว้ที่ `~/masterlist_scratch_backup/scratch/deliverables/`):

| ไฟล์ | sha256 |
|---|---|
| `masterlist_code.tar.gz` (โค้ดจาก commit `2ce30d5` ไม่มี `.env`/ข้อมูล/venv/`.vscode`) | `8693afed6e7a8c33e99c7da496af34540e6ad64cd994aa573cb4de70d79710ab` |
| `masterlist_tools.tar.gz` (เครื่องมือรันเดี่ยว 5 ไฟล์) | `3503e9bbaf445d4b5f8f7b9cb4c6039fa25e64fbe54463b5ed59d0ec4b2b69cc` |

สร้างใหม่ได้ผลเหมือนเดิมทุกไบต์ (ตรวจแล้ว) ถ้าอ้างอิง commit `2ce30d5` ไม่ใช่ `HEAD`:
```
git archive --format=tar --prefix=masterlist/ 2ce30d5 -- . ':(exclude).vscode' | gzip -n > masterlist_code.tar.gz
```
(ไฟล์เครื่องมือ: ดึง `scripts/__init__.py`, `scripts/backup.py`, `scripts/purge_deleted.py`, `utils/__init__.py`, `utils/file_removal.py` จาก `2ce30d5` ด้วย `git show` แล้ว tar ด้วย `--sort=name --owner=0 --group=0 --numeric-owner --mtime='2026-11-09 00:00:00'` และ `gzip -n`)

## 3. ขั้นต่อไป (ตามลำดับ)

1. ผู้ใช้อ่าน `handoff/` (`00_SUMMARY.md`, `01_RUNBOOK_REAL_DATA.md`, `02_S0_IT_REQUEST.md`, `03_PENDING_ACTIONS.md`) แก้ถ้าต้องการ แล้วส่ง `01` ให้หัวหน้า และ `02` ให้ IT (พร้อมไฟล์ส่งงานและ checksum ในหัวข้อ 2) ผู้ช่วยยังไม่ได้ส่งอะไรให้ใคร
2. ระหว่างรอ: เลือกงานโค้ดที่เลื่อนไว้ (หัวข้อ 5) ถ้าผู้ใช้สั่ง ยังไม่ต้อง push
3. เมื่อ IT ตอบ S0: S4–S6 (สร้าง Flow จริง, ทดสอบกับไลบรารีว่างด้วย `scripts/check_flow.py`, เปิดใช้)
4. ถ้าแก้โค้ดแอป ไฟล์ส่งงานในหัวข้อ 2 จะล้าสมัย ต้องสร้างใหม่และอัปเดต checksum ใน `handoff/00_SUMMARY.md`

## 4. ผลทดสอบที่ผ่านแล้ว (ที่ commit `2ce30d5`; pytest รันซ้ำหลัง restart แล้ว ที่เหลือไม่ได้รันซ้ำ)

| ชุดทดสอบ | ผล |
|---|---|
| `venv/bin/python -m pytest -q` | **236 ผ่าน, ข้าม 1** (เดิม 124 ก่อนรอบนี้) **รันซ้ำหลัง restart เมื่อ 2026-11-09 ได้ผลเดิม (~67 วินาที)** |
| เบราว์เซอร์จริง (Playwright) บน 8599 โหมดปกติ (รันก่อน restart ที่ `2ce30d5`) | **22/22** อัปโหลด PR, ใบเสนอราคา/คู่เทียบ, ใบกำกับ→Completed, แก้กลับ Pending, เลือกแถวเอง/ข้าม, Export CSV/Excel, Dashboard, ลบ (ยกเลิก/ยืนยัน), Audit Log ถูกล้าง, อัปโหลด PR เดิมซ้ำสะอาด |
| เบราว์เซอร์จริงบน 8599 โหมด Flow ปลอม (รันก่อน restart ที่ `2ce30d5`) | **15/15** ไฟล์ขึ้นที่เก็บปลอมตามโครงปี/เดือน/วัน/ชื่อ, ลิงก์โฟลเดอร์, ป้าย SharePoint, ใบกำกับแนบโฟลเดอร์เดิม, Flow ล้ม/ช้า/ตอบเพี้ยนแล้วแถวและไฟล์ในเครื่องยังอยู่, ไม่มี URL/คีย์ใน log และหน้าจอ |
| ซ้อมคู่มือกับข้อมูลปลอมและโค้ดรุ่นเก่า (`d69d911`) (รันก่อน restart) | **21/21** ทั้งเส้นทาง B และ A รวมกู้คืนข้อมูลและย้อนโค้ดเหมือนเดิมทุกไบต์ |

ข้อสังเกตจากการทดสอบ:
1. กด Export CSV แล้วกด Export Excel ทันทีก่อนหน้าวาดใหม่ → ปุ่มที่สองไม่ดาวน์โหลด และ log ของ Streamlit มี `Deferred file not found` (น่าจะเป็นพฤติกรรมของ Streamlit ยังไม่ได้ตรวจสาเหตุ) ถ้ารอให้หน้าวาดใหม่ก่อนก็ผ่าน
2. แก้ฐานข้อมูลจากนอกแอป: หน้าเว็บแคชข้อมูล 60 วินาที ตารางไม่เห็นข้อมูลใหม่จนกว่าจะมีการบันทึกผ่านแอปหรือแคชหมดอายุ
3. Flow ตอบช้าจนแอปเลิกรอ แต่ Flow อาจสร้างไฟล์ตามหลัง (จำลองแล้ว) แอปจึงไม่ส่งซ้ำและบอกให้ตรวจในไลบรารีก่อน
4. ย้อนโค้ดจากชุดสำรองแล้วไฟล์ที่รุ่นใหม่เพิ่มมา (22 ไฟล์ในการซ้อม) ไม่ถูกลบ ไม่กระทบรุ่นเก่า

**ยังไม่ได้ทดสอบ:** Flow และ SharePoint จริง (รูปแบบข้อมูลที่แอปส่งให้ Flow ยังเป็นการกำหนดเอง), ข้อมูลจริง, เซิร์ฟเวอร์ Linux จริง (systemd/nginx/HTTPS), หลายผู้ใช้พร้อมกัน, ขั้น `pip install` ใน venv ของโฟลเดอร์จริง (venv เครื่องนี้ไม่มี pip), โหมด Desktop export ในเบราว์เซอร์

## 5. สิ่งที่ต้องให้หัวหน้า / IT / ผู้ดูแลเซิร์ฟเวอร์ทำ

| ผู้รับผิดชอบ | งาน | ติดอะไร |
|---|---|---|
| **หัวหน้า** (หรือผู้ที่เข้า home ของ `mjbangkok` ได้) | หาตำแหน่งข้อมูลจริง, สำรองข้อมูล+โค้ด, ล้างแถวที่ซ่อนและ Audit Log (เส้นทาง B แนะนำก่อน), เลือกว่าจะอัปเดตโค้ดจริงหรือไม่ (เส้นทาง A) | บัญชีที่ผู้ช่วยใช้ (`intern`) เข้า `/home/mjbangkok` ไม่ได้ และห้ามใช้ sudo ข้อมูลจริงไม่อยู่ในเครื่องนี้ที่เข้าถึงได้ |
| **IT / ผู้ดูแล Microsoft 365** | ตอบคำถาม S0 (สิทธิ์ HTTP trigger ซึ่งปกติเป็น Premium, Site URL และไลบรารีทดสอบที่ว่าง, บัญชีเจ้าของ Flow ที่ไม่ใช่บุคคล, นโยบาย tenant ของ HTTP trigger, เพดานขนาด/เวลาตอบของ Flow เทียบไฟล์ 50 MB, ต้องส่ง Master-List และลบไฟล์ออนไลน์ด้วยไหม) แล้วสร้าง Flow (S4) | ยังไม่ได้ติดต่อ IT, ผู้ใช้จะส่งเอกสาร S0 ทีเดียวพร้อมชุดส่งงาน |
| **ผู้ดูแลเซิร์ฟเวอร์** | ขึ้นเซิร์ฟเวอร์ Linux จริง (systemd, nginx+WebSocket, HTTPS, firewall, cron สำรอง `scripts/backup.py`), ตัดสินใจเรื่องล็อกอิน/SSO (ตอนนี้ไม่มีล็อกอิน และไฟล์ใน `/app/static/...` เปิดได้โดยไม่ล็อกอิน) | ยังไม่มีเซิร์ฟเวอร์จริง ตัวอย่างใน `DEPLOY.md` ยังไม่ได้ทดสอบ |
| **เจ้าของงาน** | ยืนยันวันที่เริ่มนับ 14 วัน (ตอนนี้นับจากวันอัปโหลดชั่วคราว: `OVERDUE_RULE` ใน `config/constants.py`), Excel หลายแถวต่อไฟล์, OCR | ยังไม่มีคำตอบ |

งานโค้ดที่ผู้ใช้เลือกเลื่อนไว้ (ไม่ทำรอบนี้): ลบฟังก์ชันที่ไม่มีใครเรียก (`ui_common.render_equipment_table`, `submit_pipeline.find_pr_folder_by_description`, `text_extractor.extract_fields_from_file`), เพิ่มเทสต์ให้ `data/database.py`/`excel_export`/`text_extractor`/`dashboard`, แตก `pages_ui/overview.py` (ราว 3,300 บรรทัด), ลบโค้ด Windows/Desktop export, ติดตั้ง ruff, ลบ `utils/sharepoint_api.py` พร้อม dependency `Office365-REST-Python-Client` (หลัง Flow จริงใช้ได้)

## 6. ข้อตกลงกับผู้ใช้ที่ยังใช้อยู่

- ตอบเป็นภาษาไทย ใช้ they/them กับบุคคลที่ไม่ระบุสรรพนาม
- **ไม่ push** และ **ไม่ commit เอง** นอกจากผู้ใช้สั่ง (ผู้ใช้สั่งเป็นรอบ ๆ) ห้ามรวม `.vscode/settings.json`
- ไม่ใช้ sudo / ไม่ติดตั้งแพ็กเกจระบบ (venv ของโปรเจกต์ไม่มี pip, ruff, pyflakes) ไม่เข้า home ของผู้ใช้อื่น
- ไม่อ่าน/แสดงค่าใน `.env`; ไม่แตะข้อมูลจริง; ทดสอบกับสำเนา/ข้อมูลปลอม/ปลายทางออนไลน์ว่างเท่านั้น
- ไฟล์ตัวอย่าง PR เป็นของอ่านอย่างเดียว ห้ามเข้า repo
- ถ้าเอกสารขัดกับโค้ด ให้บอกผู้ใช้ (ตัวอย่างที่เจอ: Azure ACS เลิกใช้ 2 เม.ย. 2026 แต่เอกสารเดิมบอกให้ใช้ Client ID/Secret)
- ทำทีละข้อ สรุปสั้นก่อนไปข้อต่อไป

---

## 7. วิธีกลับมาหลัง restart / พรุ่งนี้

**สถานะตอนปิดงาน (2026-11-09):** หลัง restart ยัง **ไม่ได้กู้คืน scratchpad และไม่ได้เปิด 8599 หรือเซิร์ฟเวอร์ปลอม** ถ้าไม่ต้องทดสอบอะไรในเบราว์เซอร์ ไม่ต้องทำขั้นตอนด้านล่าง ชุด Playwright (`pwvenv`, `browsers`) ยังไม่มี ต้องสร้างใหม่ถ้าจะรัน e2e

**สำคัญ:** `/tmp` ถูกล้างตอนบูต (systemd-tmpfiles `D /tmp`) → scratchpad เดิม (`/tmp/claude-1001/.../scratchpad`, 494 MB) น่าจะหายหมด ผู้ช่วยสำรองส่วนจำเป็นไว้ที่ **`~/masterlist_scratch_backup/`** (5.5 MB สิทธิ์ 700 อยู่นอก repo ไม่เข้า git) แล้ว

| สิ่งที่อยู่ใน scratchpad | หลัง restart | หมายเหตุ |
|---|---|---|
| `manual_test/` (เซิร์ฟเวอร์ 8599, `test.db`, `snapshots/pre_e2e`, `snapshots/after_e2e_pa`, `start.sh`, `start_pa.sh`) | **หาย** แต่สำรองแล้ว | `test.db` ที่สำรองคือสถานะที่ผู้ใช้ทดสอบก่อนรอบนี้ (ซ่อน 10 แถว + ใช้งาน 1 แถว) |
| `deliverables/` (ไฟล์ส่งงาน + `SHA256SUMS` + `BUILD_INFO.txt`) | **หาย** แต่สำรองแล้ว | สร้างใหม่จาก `2ce30d5` ได้ผลเหมือนเดิมทุกไบต์ |
| `e2e_samples/` (สำเนาไฟล์ตัวอย่าง PR/ใบกำกับ) | **หาย** แต่สำรองแล้ว | ห้ามเข้า repo (สำรองไว้นอก repo) |
| สคริปต์ทดสอบ: `fake_flow.py`, `e2e_full.py`, `rehearse.py`, `run_full_normal.sh`, `run_full_pa.sh`, `isolated_env.sh`, `fonts.conf` ฯลฯ | **หาย** แต่สำรองแล้ว | ฝัง path scratchpad เดิม ต้องแทนที่ด้วยสคริปต์กู้คืนด้านล่าง |
| `pwvenv/` (144 MB), `browsers/` (278 MB), `libs/` (31 MB), `debs/` (18 MB) = ชุด Playwright | **หาย ไม่ได้สำรอง** | จำเป็นเฉพาะเมื่อจะรัน e2e ในเบราว์เซอร์อีก ต้องสร้างใหม่ (venv ย้ายที่ไม่ได้) ส่วนเซิร์ฟเวอร์ 8599 ไม่ต้องใช้ |
| repo `/home/intern/Web-Dashboard-PR-PO`, `~/.claude/plans/…`, transcript และ memory ใน `~/.claude/` | **อยู่รอด** | |

เซิร์ฟเวอร์ 8599 / เซิร์ฟเวอร์ปลอมที่รันอยู่จะดับเองตอน restart ไม่ต้องหยุดก่อน

### กรณีหลัก: `/tmp` ถูกล้าง → กู้คืนไปไว้ที่ถาวร แล้วเปิด 8599

```bash
bash ~/masterlist_scratch_backup/restore_scratch.sh ~/masterlist_scratch
bash ~/masterlist_scratch/manual_test/start.sh
```
เปิด http://127.0.0.1:8599 แล้วกด Ctrl+F5 (โหมดปกติ ที่เก็บออนไลน์ว่าง) `start.sh` ซิงก์โค้ดจาก repo ทุกครั้งที่สั่ง จึงได้โค้ดล่าสุดใน git เสมอ ถ้าพอร์ตยังค้าง: `bash ~/masterlist_scratch/manual_test/stop.sh`

### เปิดโหมดเซิร์ฟเวอร์ปลอมของ Power Automate (8600) พร้อม 8599

```bash
bash ~/masterlist_scratch/manual_test/stop.sh
nohup python3 ~/masterlist_scratch/fake_flow.py ~/masterlist_scratch/fake_flow_store ~/masterlist_scratch/fake_flow.log >/dev/null 2>&1 &
echo $! > ~/masterlist_scratch/fake_flow.pid
bash ~/masterlist_scratch/manual_test/start_pa.sh
```
`start_pa.sh` ใช้ค่าทดสอบ (URL `127.0.0.1:8600`, คีย์ปลอม, timeout 3 วินาที) ไม่ใช่ค่าจริง ไฟล์ที่ Flow ปลอมรับจะอยู่ใน `~/masterlist_scratch/fake_flow_store/` ตัวทดสอบ: ไฟล์ที่ชื่อมี `FAIL500` → Flow ตอบ 500, `SLOW` → ตอบช้า, `BADJSON` → ตอบรูปแบบเพี้ยน

หยุดทั้งหมด (ใช้เลข PID ที่บันทึกไว้ ไม่ใช้ `pkill -f` เพราะอาจฆ่าเชลล์ที่มีชื่อสคริปต์อยู่ในคำสั่งเอง):
```bash
bash ~/masterlist_scratch/manual_test/stop.sh
kill $(cat ~/masterlist_scratch/fake_flow.pid)
```

### กลับสู่สถานะ 8599 ก่อนทดสอบ / ดูสถานะหลังทดสอบ

สแนปช็อตอยู่ที่ `~/masterlist_scratch/manual_test/snapshots/` (`pre_e2e` = สถานะเดิมของผู้ใช้, `after_e2e_pa` = หลังทดสอบโหมด Flow ปลอม) ตัวสำรอง/ตัวคืนค่าเดิม: `manual_test/backup.sh <ชื่อ>`, `manual_test/reset.sh` (ล้างข้อมูลทดสอบของ 8599 เท่านั้น)

### กรณี `/tmp` ยังอยู่ (ไม่น่าเกิด)

ใช้ path เดิม `S=/tmp/claude-1001/-home-intern-Web-Dashboard-PR-PO/2d7a594a-56dd-47c7-ba13-9c467c2c666d/scratchpad` แทน `~/masterlist_scratch` ในคำสั่งด้านบน

### ตรวจว่าทุกอย่างปกติหลังกลับมา

```bash
cd ~/Web-Dashboard-PR-PO && git status --short && git log --oneline -6
venv/bin/python -m pytest -q          # คาด 236 ผ่าน ข้าม 1 (ใช้เวลา ~1 นาที)
curl -s http://127.0.0.1:8599/_stcore/health   # คาด ok เมื่อเปิด 8599 แล้ว
```
`git status` ต้องเหลือแค่ ` M .vscode/settings.json`

## 8. ข้อความสั้นสำหรับวางตอนกลับมา

```
กลับมาต่องาน Web-Dashboard-PR-PO ให้อ่าน resume_state.md ก่อน (สถานะล่าสุด commit 2ce30d5 + commit ของไฟล์นั้น ไม่ push)
ทำเสร็จ: โค้ดทั้งหมด + Power Automate S2–S3 + ทดสอบ 8599 (pytest 236 ผ่าน, e2e 22/22 และ 15/15, ซ้อมคู่มือ 21/21)
ข้อ 3 เสร็จแล้ว: handoff/ commit 76e5e00 (สรุปงาน, คู่มือหัวหน้า, S0 สำหรับ IT, รายการค้าง) ขั้นต่อไป: รอผมอ่านและส่งหัวหน้า/IT แล้วเลือกงานต่อ
/tmp ถูกล้างตอนบูต: กู้คืนด้วย bash ~/masterlist_scratch_backup/restore_scratch.sh ~/masterlist_scratch
แล้วเปิด 8599 ด้วย bash ~/masterlist_scratch/manual_test/start.sh
ตอบเป็นภาษาไทย ไม่ push ไม่ commit ถ้าไม่ได้สั่ง ไม่รวม .vscode/settings.json ไม่ใช้ sudo ไม่แตะข้อมูลจริง
```

---

## 9. ประวัติเดิมของรอบ UI (ย่อ เก็บไว้อ้างอิง)

โครงสร้างหลัก:
- `app.py` — Router: ฉีดธีม, Sidebar, หัวหน้า (ชื่อหน้า + Date Filter), เรียกหน้าที่เลือก
- `config/styles.py` — CSS กลางทั้งแอป (ธีม, Responsive, หัวข้อ gradient, Date Filter, ปฏิทิน)
- `ui_grid.py` — ตาราง AgGrid; `pages_ui/overview.py` — แจ้งเตือนค้าง 14 วัน, ตารางหลัก, ฟอร์ม/อัปโหลด; `pages_ui/dashboard.py`, `sidebar_ui.py`, `data/database.py` (SQL อยู่ที่นี่ที่เดียว)
- ความลับโหลดจาก `.env` ซึ่งไม่อยู่ใน Git; `.env.example` เป็นข้อมูลหลอก

ข้อจำกัดด้าน UI ที่ยังเป็นจริง: animation และจอสัมผัสตรวจจากภาพนิ่งเป็นหลัก, CSS ผูกกับ Streamlit 1.66.1 (selector `data-testid` โดยเฉพาะ `stDateInputCalendar`) ถ้าอัปเกรดแล้วสไตล์หลุดให้ตรวจ DOM ใหม่, แจ้งเตือน LINE OA เป็นฟีเจอร์อนาคต (มีคอมเมนต์จุดวางปุ่มใน `build_overdue_alert_html`)
