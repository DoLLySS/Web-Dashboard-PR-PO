"""ค่าคงที่ที่ใช้ร่วมกันหลายหน้า (แก้ที่นี่ที่เดียว)"""

from dataclasses import dataclass


@dataclass(frozen=True)
class OverdueRule:
    """เกณฑ์ใบกำกับภาษีค้าง

    Attributes:
        days_limit: แจ้งเตือนเมื่อค้าง "เกิน" กี่วัน
        reference_date_columns: คอลัมน์ที่ใช้เริ่มนับวัน เรียงตามลำดับ (ใช้คอลัมน์ถัดไปเมื่ออ่านค่าไม่ได้)
        reference_date_label: ชื่อวันที่อ้างอิงในข้อความแจ้งสถานะ
        reference_date_column_title: หัวคอลัมน์วันที่อ้างอิงในตารางรายการค้าง
    """

    days_limit: int
    reference_date_columns: tuple[str, ...]
    reference_date_label: str
    reference_date_column_title: str


# แก้เกณฑ์ค้างที่นี่ที่เดียว (จำนวนวันและวันที่อ้างอิงแยกกัน)
# ตอนนี้นับจากวันอัปโหลดเป็นการชั่วคราว ระหว่างรอเจ้าของงานยืนยันว่าควรนับจากวันใด
OVERDUE_RULE: OverdueRule = OverdueRule(
    days_limit=14,
    reference_date_columns=("created_at", "date"),
    reference_date_label="วันที่ Upload / บันทึกข้อมูล",
    reference_date_column_title="วันที่อัปโหลด",
)

# key ของ Date Filter ใน st.session_state (ใช้ร่วมกันระหว่าง app.py และหน้าที่ต้องปรับช่วงวันที่)
FILTER_START_DATE_KEY: str = "filter_start_date"
FILTER_END_DATE_KEY: str = "filter_end_date"

# หมวดหมู่ที่เลือกได้ในฟอร์ม (ช่อง "หมวดหมู่" และตัวกรอง Item) จะเพิ่มหมวดใหม่ให้แก้ที่นี่
# ถ้าเพิ่มหมวดใหม่ ให้เพิ่มสีใน CATEGORY_COLORS ของ pages_ui/dashboard.py ด้วย
CATEGORY_OPTIONS: list[str] = ["Hardware", "Software", "Service", "Network", "อื่น ๆ"]

# หมวดที่แสดงในตารางสรุปจำนวนอุปกรณ์ (Quantity of equipment) เรียงตามลำดับที่แสดง
EQUIPMENT_CATEGORIES: list[str] = ["Hardware", "Software", "Network", "Service"]
