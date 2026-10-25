# IT PR/PO & Tax Invoice MasterList — Project Planning

ระบบภายในสำหรับทีม IT Support (3-4 คน) ใช้บันทึกและติดตามเอกสาร PR / PO / ใบกำกับภาษี
สร้างด้วย **Streamlit + SQLite + Plotly** เป้าหมายหลักคือ **โค้ดอ่านง่าย แก้ไขง่าย ส่งต่องานได้สบาย**

---

## 1. Tech Stack

| ส่วน | เครื่องมือ | เหตุผล |
|---|---|---|
| UI | Streamlit | เขียนเร็ว ทีมไม่ต้องรู้ HTML/JS |
| ฐานข้อมูล | SQLite (`sqlite3` มาตรฐาน) | ไม่ต้องติดตั้ง server, ไฟล์เดียว, ทีมเล็กใช้พอ |
| กราฟ | Plotly Express | โต้ตอบได้ ใช้กับ Streamlit ง่าย |
| ข้อมูลตาราง | pandas | อ่าน SQL → DataFrame แสดงผล/กรองง่าย |
| Extract Text | `pdfplumber` (PDF), `pytesseract` (รูปภาพ, ทางเลือก) | ดึงข้อความจากเอกสารที่อัปโหลด |
| SharePoint (อนาคต) | `Office365-REST-Python-Client` หรือ Microsoft Graph | เตรียม interface ไว้ก่อน ยังไม่ implement |

---

## 2. โครงสร้างโปรเจค

```
Project ฝึกงาน/
├── planning.md                # เอกสารนี้ (โครงสร้าง + Coding Standards)
├── requirements.txt           # รายการ library
├── app.py                     # จุดเริ่มต้นแอป: Sidebar, Date Filter, สลับหน้า
├── config.py                  # ค่าคงที่ทั้งระบบ (path DB, จำนวนวันแจ้งเตือน, ชื่อสถานะ)
│
├── database/
│   ├── __init__.py
│   ├── connection.py          # เปิด/ปิด connection SQLite, สร้างตารางครั้งแรก
│   ├── models.py              # dataclass ของ Record + SQL สร้างตาราง
│   └── repository.py          # ฟังก์ชัน CRUD ทั้งหมด (เพิ่ม/แก้/ลบ/ค้นหา)
│
├── pages/
│   ├── __init__.py
│   ├── overview.py            # หน้า Overview: ฟอร์ม + ตาราง + แจ้งเตือน
│   └── dashboard.py           # หน้า Dashboard: ตัวเลขสรุป + กราฟ
│
├── components/
│   ├── __init__.py
│   ├── date_filter.py         # Date Filter มุมขวาบน
│   ├── upload_form.py         # ฟอร์มอัปโหลดไฟล์ + ช่องกรอกข้อมูล
│   ├── data_table.py          # ตารางแสดงข้อมูลจาก SQLite
│   ├── alert_banner.py        # แจ้งเตือนใบกำกับภาษีค้างเกิน 14 วัน
│   └── charts.py              # ฟังก์ชันสร้างกราฟ Plotly
│
├── services/
│   ├── __init__.py
│   ├── text_extractor.py      # อ่านไฟล์ → ข้อความดิบ (PDF/รูปภาพ)
│   ├── field_parser.py        # แยกข้อความดิบ → เลข PR/PO, ยอดเงิน, วันที่ ฯลฯ
│   ├── tax_invoice_checker.py # ตรรกะหาใบกำกับภาษีที่ค้างเกิน 14 วัน
│   ├── summary_service.py     # คำนวณตัวเลขสรุปสำหรับ Dashboard
│   └── sharepoint_client.py   # (อนาคต) Interface เชื่อม SharePoint — ตอนนี้เป็น stub
│
├── utils/
│   ├── __init__.py
│   ├── date_utils.py          # แปลง/เทียบวันที่ (รองรับ พ.ศ. ↔ ค.ศ.)
│   └── error_handler.py       # ตัวช่วยแสดง error ใน Streamlit อย่างเป็นมิตร
│
├── data/
│   ├── masterlist.db          # ไฟล์ SQLite (ไม่ commit)
│   └── uploads/               # ไฟล์ที่อัปโหลด (ไม่ commit)
│
└── tests/                     # (แนะนำ) ทดสอบ services และ repository
    ├── test_field_parser.py
    └── test_tax_invoice_checker.py
```

### หลักการแบ่งชั้น (Layered)

```
pages/ + components/   →   services/   →   database/
   (แสดงผล UI)          (ตรรกะธุรกิจ)     (อ่าน/เขียนข้อมูล)
```

- **UI ห้ามเขียน SQL ตรง ๆ** — ต้องเรียกผ่าน `repository.py`
- **services ห้าม import streamlit** — เพื่อทดสอบง่ายและใช้ซ้ำได้
- ชั้นบนเรียกชั้นล่างได้ แต่ชั้นล่างห้ามเรียกชั้นบน

---

## 3. หน้าที่ของแต่ละไฟล์ .py

### ไฟล์หลัก

| ไฟล์ | หน้าที่ |
|---|---|
| `app.py` | ตั้งค่าหน้า (`st.set_page_config`), สร้าง Sidebar เมนู (Overview / Dashboard), วาง Date Filter มุมขวาบน, เรียกหน้าที่เลือก, ส่งช่วงวันที่ให้ทุกหน้า |
| `config.py` | เก็บค่าคงที่เท่านั้น เช่น `DB_PATH`, `UPLOAD_DIR`, `TAX_INVOICE_ALERT_DAYS = 14`, รายชื่อสถานะ/ประเภทเอกสาร — **แก้ค่าที่นี่ที่เดียว** |

### `database/`

| ไฟล์ | หน้าที่ |
|---|---|
| `connection.py` | `get_connection()` เปิด SQLite, `init_database()` สร้างตารางถ้ายังไม่มี |
| `models.py` | `@dataclass DocumentRecord` กำหนดฟิลด์ของแต่ละรายการ + คำสั่ง `CREATE TABLE` |
| `repository.py` | `insert_record()`, `update_record()`, `delete_record()`, `get_records(start, end)`, `get_pending_tax_invoices()` — ทุกฟังก์ชัน SQL อยู่ที่นี่ที่เดียว (ใช้ parameterized query เสมอ) |

### `pages/`

| ไฟล์ | หน้าที่ |
|---|---|
| `overview.py` | ประกอบหน้า Overview: `alert_banner` → `upload_form` → `data_table` ตามลำดับ |
| `dashboard.py` | ประกอบหน้า Dashboard: การ์ดตัวเลขสรุป + กราฟจาก `charts.py` |

### `components/`

| ไฟล์ | หน้าที่ |
|---|---|
| `date_filter.py` | วาดช่องเลือกช่วงวันที่ คืนค่า `(start_date, end_date)` |
| `upload_form.py` | ฟอร์มอัปโหลดไฟล์ → เรียก `text_extractor` + `field_parser` → **ทยอยเติมค่าลงช่องฟอร์มอัตโนมัติ** (ผู้ใช้แก้ไขได้ก่อนกดบันทึก) → บันทึกผ่าน `repository` |
| `data_table.py` | แสดงรายการจาก SQLite เป็นตาราง, ค้นหา/กรอง, ปุ่มแก้ไข/ลบ |
| `alert_banner.py` | แสดงกล่องเตือนสีเหลือง/แดงเมื่อมีใบกำกับภาษีค้างเกิน 14 วัน พร้อมรายการ |
| `charts.py` | ฟังก์ชันสร้างกราฟ Plotly (เช่น `build_monthly_spend_chart()`, `build_status_pie_chart()`) คืนค่า `Figure` ไม่วาดเอง |

### `services/`

| ไฟล์ | หน้าที่ |
|---|---|
| `text_extractor.py` | รับไฟล์ → คืนข้อความดิบ (`str`) แยกตามชนิดไฟล์ |
| `field_parser.py` | ใช้ regex แยกข้อความดิบเป็น dict ของฟิลด์ (เลข PR, เลข PO, ผู้ขาย, ยอดเงิน, วันที่) ถ้าหาไม่เจอคืนค่าว่าง ไม่ error |
| `tax_invoice_checker.py` | หาว่ารายการ PO ไหนยังไม่ได้ใบกำกับภาษีเกิน `TAX_INVOICE_ALERT_DAYS` วัน |
| `summary_service.py` | คำนวณจำนวน PR/PO, ยอดรวม, จำนวนค้าง ฯลฯ ในช่วงวันที่ที่เลือก |
| `sharepoint_client.py` | **Stub สำหรับอนาคต** — กำหนด class `SharePointClient` พร้อมเมธอด `upload_file()`, `list_files()` ที่ยัง `raise NotImplementedError("ยังไม่เปิดใช้งาน SharePoint")` เพื่อให้จุดเชื่อมต่อชัดเจน |

### `utils/`

| ไฟล์ | หน้าที่ |
|---|---|
| `date_utils.py` | `days_between()`, `parse_thai_date()`, `to_buddhist_year()` |
| `error_handler.py` | `show_error(message, detail)` แสดงข้อความ error ภาษาไทยใน UI + บันทึก log |

---

## 4. โครงสร้างฐานข้อมูล (ร่าง)

ตาราง `documents`

| คอลัมน์ | ชนิด | คำอธิบาย |
|---|---|---|
| `id` | INTEGER PK | รหัสอัตโนมัติ |
| `doc_type` | TEXT | `PR` / `PO` |
| `pr_number` | TEXT | เลขที่ PR |
| `po_number` | TEXT | เลขที่ PO |
| `vendor` | TEXT | ผู้ขาย |
| `description` | TEXT | รายการสินค้า/บริการ |
| `amount` | REAL | ยอดเงิน (บาท) |
| `doc_date` | TEXT | วันที่เอกสาร (ISO `YYYY-MM-DD`) |
| `tax_invoice_no` | TEXT | เลขใบกำกับภาษี (ว่าง = ยังไม่ได้รับ) |
| `tax_invoice_date` | TEXT | วันที่ได้รับใบกำกับภาษี |
| `status` | TEXT | สถานะ |
| `file_path` | TEXT | path ไฟล์ที่อัปโหลด |
| `sharepoint_url` | TEXT | (อนาคต) ลิงก์ SharePoint |
| `created_by` | TEXT | ผู้บันทึก |
| `created_at` | TEXT | เวลาบันทึก |

> เก็บวันที่เป็น ISO (ค.ศ.) เสมอ แปลงเป็น พ.ศ. เฉพาะตอนแสดงผล

---

## 5. Flow การทำงานหลัก

**อัปโหลด + Extract**
```
ผู้ใช้อัปโหลดไฟล์ → text_extractor (ข้อความดิบ) → field_parser (แยกฟิลด์)
→ เติมลงฟอร์มอัตโนมัติ → ผู้ใช้ตรวจ/แก้ → กดบันทึก → repository.insert_record()
```

**แจ้งเตือนใบกำกับภาษีค้าง**
```
เปิดหน้า Overview → tax_invoice_checker ดึงรายการที่ tax_invoice_no ว่าง
และ (วันนี้ − doc_date) > 14 วัน → alert_banner แสดงรายการ
```

**Date Filter**
```
app.py เรียก date_filter → ได้ (start, end) → ส่งให้ overview/dashboard → ส่งต่อ repository
```

---

## 6. Coding Standards (บังคับใช้ทุกไฟล์)

### 6.1 Type Hinting — ทุกฟังก์ชัน

ต้องระบุชนิดของพารามิเตอร์และค่าที่คืน **ทุกฟังก์ชัน** (รวมฟังก์ชันที่ไม่คืนค่า ให้ใช้ `-> None`)

```python
from datetime import date

def is_overdue(invoice_date: date, limit_days: int = 14) -> bool:
    ...

def get_records(start: date, end: date) -> list[DocumentRecord]:
    ...

def save_upload(file_name: str) -> None:
    ...
```

### 6.2 Docstring + Comment ภาษาไทย

- **ทุกฟังก์ชันและคลาส** ต้องมี Docstring ภาษาไทย อธิบาย: ทำอะไร / รับอะไร (`Args`) / คืนอะไร (`Returns`) / error ที่อาจเกิด (`Raises`, ถ้ามี)
- **Inline Comment** ใส่เฉพาะจุดที่ซับซ้อน (regex, SQL join, การคำนวณวัน, เงื่อนไขซ้อน) และอธิบาย "ทำไม" ไม่ใช่แค่ "ทำอะไร"
- **Comment และ Docstring เขียนเป็นภาษาไทยทั้งหมด** (ชื่อตัวแปร/ฟังก์ชันใช้ภาษาอังกฤษ)

```python
def find_overdue_invoices(records: list[DocumentRecord], limit_days: int = 14) -> list[DocumentRecord]:
    """หารายการที่ยังไม่ได้รับใบกำกับภาษีและเกินกำหนดวันที่ระบุ

    Args:
        records: รายการเอกสารทั้งหมดที่ต้องการตรวจสอบ
        limit_days: จำนวนวันสูงสุดที่ยอมให้ค้าง (ค่าเริ่มต้น 14 วัน)

    Returns:
        รายการเอกสารที่ค้างเกินกำหนด เรียงจากค้างนานที่สุดก่อน
    """
    today = date.today()
    overdue: list[DocumentRecord] = []

    for record in records:
        # ถ้ามีเลขใบกำกับภาษีแล้ว ถือว่าครบ ไม่ต้องแจ้งเตือน
        if record.tax_invoice_no:
            continue
        # นับวันจากวันที่ออก PO จนถึงวันนี้ (ไม่นับวันที่ได้รับใบกำกับ เพราะยังไม่มี)
        if (today - record.doc_date).days > limit_days:
            overdue.append(record)

    return sorted(overdue, key=lambda r: r.doc_date)
```

### 6.3 Error Handling — Try-Except พร้อมข้อความที่เข้าใจง่าย

- ทุกจุดที่เสี่ยง (อ่าน/เขียนไฟล์, SQLite, Extract Text, เรียก SharePoint, แปลงวันที่/ตัวเลข) ต้องครอบด้วย `try-except`
- **ห้ามใช้ `except:` เปล่า ๆ** ให้จับ exception เฉพาะชนิด (`sqlite3.Error`, `FileNotFoundError`, `ValueError` ฯลฯ)
- ข้อความที่แสดงผู้ใช้ต้องเป็น **ภาษาไทย ภาษาคนทั่วไป** บอกว่า "เกิดอะไรขึ้น" และ "ควรทำอย่างไรต่อ" ไม่โชว์ traceback ให้ผู้ใช้ปลายทาง
- รายละเอียดทางเทคนิคให้เขียนลง log (`logging`) เพื่อให้ทีม IT ตามแก้ได้
- ชั้น `services/` และ `database/` ให้ **raise exception ที่มีข้อความชัดเจน** ส่วนชั้น UI เป็นคนจับและแสดงผลด้วย `show_error()`

```python
import logging
import sqlite3

logger = logging.getLogger(__name__)

def insert_record(record: DocumentRecord) -> int:
    """บันทึกรายการใหม่ลงฐานข้อมูล

    Returns:
        id ของรายการที่เพิ่งบันทึก

    Raises:
        RuntimeError: เมื่อบันทึกลงฐานข้อมูลไม่สำเร็จ
    """
    try:
        with get_connection() as conn:
            cursor = conn.execute(INSERT_SQL, record.to_tuple())
            return cursor.lastrowid
    except sqlite3.IntegrityError as error:
        logger.error("ข้อมูลซ้ำ: %s", error)
        raise RuntimeError("เลขที่เอกสารนี้มีอยู่ในระบบแล้ว กรุณาตรวจสอบเลข PR/PO อีกครั้ง") from error
    except sqlite3.Error as error:
        logger.exception("บันทึกฐานข้อมูลล้มเหลว")
        raise RuntimeError("บันทึกข้อมูลไม่สำเร็จ กรุณาลองใหม่ หากยังไม่ได้ให้แจ้งทีม IT") from error
```

### 6.4 มาตรฐานเสริม (เพื่อให้ Maintainable)

| หัวข้อ | กฎ |
|---|---|
| การตั้งชื่อ | ตัวแปร/ฟังก์ชัน `snake_case`, คลาส `PascalCase`, ค่าคงที่ `UPPER_CASE`; ชื่อต้องสื่อความหมาย (`overdue_invoices` ไม่ใช่ `lst2`) |
| ขนาดฟังก์ชัน | 1 ฟังก์ชัน = 1 หน้าที่ ควรไม่เกิน ~30 บรรทัด ถ้ายาวกว่านั้นให้แยก |
| ค่าคงที่ | ห้าม hard-code ตัวเลข/ข้อความ (เช่น `14`, path DB) ในโค้ด ให้ใส่ใน `config.py` |
| SQL | ใช้ parameterized query (`?`) เท่านั้น ห้ามต่อ string เพื่อกัน SQL Injection |
| Streamlit | ใช้ `@st.cache_data` กับการอ่านข้อมูลที่ไม่เปลี่ยนบ่อย และ clear cache หลังเขียน DB; เก็บ state ผ่าน `st.session_state` โดยตั้งชื่อ key เป็นค่าคงที่ |
| Import | เรียงเป็นกลุ่ม: standard library → third-party → โมดูลในโปรเจค |
| Format | ใช้ `black` (ความยาวบรรทัด 100) และ `ruff` ตรวจโค้ดก่อน commit |
| Logging | ใช้ `logging` ไม่ใช้ `print()` ในโค้ดจริง |
| ข้อมูลลับ | Credential ของ SharePoint ในอนาคตเก็บใน `.env` / `st.secrets` ห้ามใส่ในโค้ด |

### 6.5 Checklist ก่อนส่งงาน (Self Review)

- [ ] ทุกฟังก์ชันมี Type Hint ครบ (พารามิเตอร์ + ค่าที่คืน)
- [ ] ทุกฟังก์ชันมี Docstring ภาษาไทย
- [ ] จุดซับซ้อนมี Comment ภาษาไทยอธิบายเหตุผล
- [ ] จุดเสี่ยงมี Try-Except และข้อความ error ภาษาไทยที่เข้าใจง่าย
- [ ] ไม่มี magic number / hard-code (ใช้ `config.py`)
- [ ] ไม่มี SQL อยู่นอก `repository.py`
- [ ] รันแอปแล้วทดสอบทั้ง 2 หน้าได้ไม่มี error

---

## 7. ลำดับการพัฒนา (Roadmap)

| Phase | งาน | ไฟล์ที่เกี่ยวข้อง |
|---|---|---|
| 1 | วางโครงโปรเจค, config, ฐานข้อมูล | `config.py`, `database/*` |
| 2 | Sidebar + Date Filter + หน้าเปล่า 2 หน้า | `app.py`, `components/date_filter.py`, `pages/*` |
| 3 | หน้า Overview: ฟอร์มกรอกมือ + ตารางข้อมูล | `upload_form.py`, `data_table.py` |
| 4 | แจ้งเตือนใบกำกับภาษีค้าง 14 วัน | `tax_invoice_checker.py`, `alert_banner.py` |
| 5 | หน้า Dashboard: ตัวเลขสรุป + กราฟ Plotly | `summary_service.py`, `charts.py`, `dashboard.py` |
| 6 | Extract Text + ทยอยเติมลงฟอร์ม | `text_extractor.py`, `field_parser.py` |
| 7 | ทดสอบ + เอกสารส่งมอบ (README) | `tests/*` |
| 8 | (อนาคต) เชื่อม SharePoint | `sharepoint_client.py` |

---

## 8. ประเด็นที่ต้องยืนยันก่อนเริ่มเขียนโค้ด

1. **นิยาม "ค้างเกิน 14 วัน"** — นับจากวันที่ออก PO หรือวันที่ส่งมอบ/รับของ?
2. **ชนิดไฟล์ที่อัปโหลด** — PDF ที่มีข้อความ (text-based) หรือสแกนเป็นรูป (ต้องใช้ OCR)? ภาษาในเอกสารเป็นไทย/อังกฤษ?
3. **ฟิลด์ในฟอร์ม** — ตามร่างตารางข้อ 4 ครบหรือยัง ต้องการเพิ่ม เช่น แผนก, งบประมาณ, ผู้ขอซื้อ?
4. **การเข้าใช้งาน** — มีระบบ login หรือไม่ (ทีม 3-4 คน อาจใช้ช่องกรอกชื่อผู้บันทึกแทน)?
5. **ที่ตั้งไฟล์ DB** — เครื่องเดียว หรือโฟลเดอร์แชร์ (ถ้าหลายคนเขียนพร้อมกัน SQLite อาจมีปัญหา lock)?
6. **รูปแบบวันที่** — แสดงเป็น พ.ศ. หรือ ค.ศ.?
