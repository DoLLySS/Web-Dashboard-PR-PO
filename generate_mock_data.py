"""สร้างข้อมูลจำลอง (Mock Data) ลงฐานข้อมูล masterlist.db เพื่อทดสอบระบบโดยไม่ต้องรอข้อมูลจริง

วิธีใช้ (รันครั้งเดียวก่อนเปิดแอป):
    python generate_mock_data.py

กติกา:
- ถ้าในตารางมีข้อมูลอยู่แล้ว สคริปต์จะ "ไม่เพิ่มซ้ำ" (รันกี่ครั้งก็ปลอดภัย)
- ถ้าเป็นฐานข้อมูลใหม่ (ตารางว่าง) จะเพิ่มข้อมูลจำลอง 18 แถว
- วันที่ทั้งหมดคำนวณย้อนหลังจาก "วันนี้" จึงทดสอบ Date Filter และแจ้งเตือนค้าง 14 วันได้เสมอ
  ไม่ว่าจะรันสคริปต์วันไหน

ข้อมูลจำลองครอบคลุมสถานการณ์เหล่านี้:
  - รายการใหม่ในสัปดาห์นี้ (Pending)
  - รายการที่ค้าง 9-14 วัน (Pending ยังไม่เกินกำหนด รวมกรณีพอดี 14 วัน)
  - รายการที่ค้างเกิน 14 วัน รวมของเดือนที่แล้ว (Overdue)
  - รายการที่ได้รับใบกำกับภาษีแล้ว (Completed)
"""

import random
from datetime import date, timedelta
from typing import Optional

from data.database import (
    STATUS_PENDING,
    STATUS_RECEIVED,
    add_transaction,
    count_transactions,
    init_db,
)

# ---------------------------------------------------------------------------
# ข้อมูลจำลอง (แก้/เพิ่มแถวที่นี่ได้)
# ---------------------------------------------------------------------------

# ลิงก์ SharePoint จำลอง ({number} คือเลขลำดับ PO เช่น 1001)
MOCK_SHAREPOINT_URL_TEMPLATE: str = "https://sharepoint.company.com/PO_{number}.pdf"

# ข้อมูลผู้ขายจำลอง: ชื่อ -> (เบอร์โทร, อีเมล, ชื่อผู้ติดต่อ)
MOCK_VENDOR_CONTACTS: dict[str, tuple[str, str, str]] = {
    "Company A": ("02-123-4567", "sales@company-a.example", "Somchai"),
    "Company B": ("02-234-5678", "contact@company-b.example", "Suda"),
    "Company C": ("081-345-6789", "info@company-c.example", "Anan"),
    "Vendor IT": ("089-456-7890", "support@vendor-it.example", "Malee"),
    "Network Solutions Co.": ("02-567-8901", "sales@netsol.example", "Kittipong"),
    "Service Plus": ("086-678-9012", "hello@serviceplus.example", "Pimchanok"),
}

# แถวข้อมูล: (กี่วันก่อนวันนี้, ผู้ขาย, หมวดหมู่, ราคา, ได้รับใบกำกับภาษีแล้วหรือยัง, มีลิงก์ SharePoint หรือไม่)
# เรียงจากใหม่ไปเก่า ช่วงวันที่เว้นไว้ให้ครอบคลุมทั้งในและนอกช่วง Date Filter เริ่มต้น (30 วัน)
MOCK_ROWS: list[tuple[int, str, str, float, bool, bool]] = [
    # --- สัปดาห์นี้ (Pending ใหม่) ---
    (0, "Vendor IT", "Service", 4500.00, False, True),
    (1, "Company A", "Hardware", 32500.00, False, True),
    (2, "Company B", "Software", 18900.00, False, False),
    (4, "Network Solutions Co.", "Network", 27800.00, False, True),
    (6, "Company A", "Hardware", 15400.50, True, True),  # Completed
    # --- ค้าง 9-14 วัน (ยังไม่เกินกำหนด) ---
    (9, "Company C", "Software", 8200.00, False, True),
    (12, "Vendor IT", "Hardware", 21000.00, False, False),
    (14, "Service Plus", "Service", 6500.00, False, True),  # พอดี 14 วัน = ยังไม่ Overdue
    # --- ค้างเกิน 14 วัน (Overdue 🔴) รวมของเดือนที่แล้ว ---
    (16, "Company B", "Network", 39900.00, False, True),
    (21, "Company A", "Hardware", 48000.00, False, True),
    (33, "Vendor IT", "Software", 12500.00, False, False),
    (41, "Company C", "Hardware", 26750.00, False, True),
    # --- ได้รับใบกำกับภาษีแล้ว (Completed ✅) ---
    (18, "Network Solutions Co.", "Network", 31200.00, True, True),
    (25, "Company B", "Software", 9800.00, True, True),
    (38, "Service Plus", "Service", 7300.00, True, False),
    (52, "Company A", "Hardware", 55000.00, True, True),
    (60, "Vendor IT", "Service", 5200.00, True, True),
    (75, "Company C", "Software", 14400.00, True, True),
]

# รายละเอียดอุปกรณ์จำลองแยกตามหมวด (สุ่มเลือก 1 รายการต่อแถว) -> คอลัมน์ description
MOCK_DESCRIPTIONS: dict[str, list[str]] = {
    "Hardware": ["Notebook Dell Latitude 14 inch x2", "Monitor 24 inch x5", "SSD 1TB x10", "Printer HP LaserJet x1"],
    "Software": ["Microsoft 365 Business License x20", "Antivirus Endpoint License x50", "Adobe Acrobat Pro x5"],
    "Network": ["Switch 24 Port PoE x2", "Wi-Fi Access Point x4", "Firewall FortiGate 60F x1"],
    "Service": ["ค่าบริการดูแลระบบรายเดือน", "ค่าติดตั้งระบบเครือข่าย", "ค่าบริการ Cloud Backup รายปี"],
}

# ส่วนลดจำลอง (ราคาสุทธิ = ราคารวม x (1 - ส่วนลด)) -> คอลัมน์ unit_price
MOCK_DISCOUNT_RANGE: tuple[float, float] = (0.00, 0.12)
# วันที่ PR จะอยู่ก่อนวันที่เอกสารกี่วัน (ต่ำสุด, สูงสุด) -> คอลัมน์ pr_request_date
MOCK_PR_LEAD_DAYS: tuple[int, int] = (3, 10)
# เมล็ดสุ่มคงที่ เพื่อให้รันซ้ำแล้วได้ข้อมูลชุดเดิม (ทดสอบซ้ำได้)
MOCK_RANDOM_SEED: int = 2026


# ---------------------------------------------------------------------------
# ฟังก์ชัน
# ---------------------------------------------------------------------------


def make_valid_tax_id(first_twelve_digits: str) -> str:
    """สร้างเลขผู้เสียภาษี 13 หลักที่ check digit ถูกต้อง จากเลข 12 หลักแรก (ให้ตรงกับที่ text_extractor ตรวจ)

    Args:
        first_twelve_digits: เลข 12 หลักแรก

    Returns:
        เลข 13 หลักล้วน
    """
    weighted_sum = sum(int(digit) * weight for digit, weight in zip(first_twelve_digits, range(13, 1, -1)))
    check_digit = (11 - weighted_sum % 11) % 10
    return f"{first_twelve_digits}{check_digit}"


def generate_test_data(today: Optional[date] = None) -> int:
    """เพิ่มข้อมูลจำลองลงฐานข้อมูล ถ้าตารางยังว่างเท่านั้น

    Args:
        today: วันที่ที่ใช้เป็น "วันนี้" (ไม่ระบุ = วันนี้จริง ใส่เพื่อให้ทดสอบซ้ำได้ผลเหมือนเดิม)

    Returns:
        จำนวนแถวที่เพิ่มสำเร็จ (0 ถ้าข้ามเพราะมีข้อมูลอยู่แล้ว หรือเตรียมฐานข้อมูลไม่สำเร็จ)
    """
    if not init_db():
        return 0  # init_db แสดง error ให้แล้ว

    # ตรวจก่อนว่ามีข้อมูลหรือยัง ถ้ามีแล้วไม่เพิ่มซ้ำ (กันข้อมูลจำลองไปปนกับข้อมูลจริง)
    existing_count = count_transactions()
    if existing_count > 0:
        print(f"ข้ามการสร้างข้อมูลจำลอง: ฐานข้อมูลมีข้อมูลอยู่แล้ว {existing_count} รายการ")
        return 0

    today = today or date.today()
    inserted_count = 0
    random_generator = random.Random(MOCK_RANDOM_SEED)

    for row_number, (days_ago, vendor, category, price, is_completed, has_link) in enumerate(MOCK_ROWS, start=1):
        document_date = today - timedelta(days=days_ago)
        po_sequence = 1000 + row_number  # เลขลำดับ PO เช่น 1001
        po_number = f"PO-{document_date.year}-{po_sequence}"
        phone, email, contact_name = MOCK_VENDOR_CONTACTS[vendor]
        # เลขผู้เสียภาษีจำลองต่อผู้ขาย (ผู้ขายคนเดิมได้เลขเดิมเสมอ) สร้างจากลำดับของผู้ขายในรายการ
        vendor_index = list(MOCK_VENDOR_CONTACTS).index(vendor)
        tax_id = make_valid_tax_id(f"01055610{vendor_index:02d}0{vendor_index + 1}"[:12])

        # ข้อมูลจาก PR / Quotation (ฟิลด์ใหม่): สุ่มแบบคงที่ตาม MOCK_RANDOM_SEED
        pr_request_date = document_date - timedelta(days=random_generator.randint(*MOCK_PR_LEAD_DAYS))
        discount_rate = random_generator.uniform(*MOCK_DISCOUNT_RANGE)

        new_id = add_transaction(
            date=document_date.isoformat(),
            vendor=vendor,
            total_price=price,
            tax_id=tax_id,
            po_no=po_number,
            pr_run_no=f"PR-{document_date.year}-{100 + row_number:04d}",
            category=category,
            invoice_status=STATUS_RECEIVED if is_completed else STATUS_PENDING,
            tel=phone,
            email=email,
            contact_name=contact_name,
            sharepoint_url=MOCK_SHAREPOINT_URL_TEMPLATE.format(number=po_sequence) if has_link else None,
            pr_request_date=pr_request_date.isoformat(),
            qt_no=f"QT-{document_date.year}-{200 + row_number:04d}",
            description=random_generator.choice(MOCK_DESCRIPTIONS[category]),
            unit_price=round(price * (1 - discount_rate), 2),
            created_at=f"{document_date.isoformat()} 09:00:00",  # วันที่ Upload จำลอง = วันที่เอกสารจำลอง (ใช้นับวันค้าง)
        )
        if new_id is not None:
            inserted_count += 1

    print(f"เพิ่มข้อมูลจำลองเรียบร้อย {inserted_count} จาก {len(MOCK_ROWS)} รายการ")
    return inserted_count


if __name__ == "__main__":
    generate_test_data()
