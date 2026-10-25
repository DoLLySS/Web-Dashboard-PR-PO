"""ค่าคงที่ที่ใช้ร่วมกันหลายหน้า (แก้ที่นี่ที่เดียว)"""

# หมวดหมู่ที่เลือกได้ในฟอร์ม (ช่อง "หมวดหมู่" และตัวกรอง Item) จะเพิ่มหมวดใหม่ให้แก้ที่นี่
# ถ้าเพิ่มหมวดใหม่ ให้เพิ่มสีใน CATEGORY_COLORS ของ pages_ui/dashboard.py ด้วย
CATEGORY_OPTIONS: list[str] = ["Hardware", "Software", "Service", "Network", "อื่น ๆ"]

# หมวดที่แสดงในตารางสรุปจำนวนอุปกรณ์ (Quantity of equipment) เรียงตามลำดับที่แสดง
EQUIPMENT_CATEGORIES: list[str] = ["Hardware", "Software", "Network", "Service"]
