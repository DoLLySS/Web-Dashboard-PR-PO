# assets ของตัวแปลงใบเสนอราคา

- `logo.png` — โลโก้บริษัท (อยู่ใน Git)
- `signature_requested.png` — **ลายเซ็นจริง ห้ามเข้า Git** (อยู่ใน .gitignore)

## วางลายเซ็นบนเครื่องใหม่
1. ขอไฟล์ `signature_requested.png` จากหัวหน้า/IT ผ่านช่องทางภายใน
2. วางที่ `utils/quotation_converter/assets/signature_requested.png`
3. ตรวจ `git status` ต้องไม่เห็นไฟล์นี้

ถ้าไม่วาง ระบบยังสร้าง Excel ได้ แต่ช่องลายเซ็นจะว่าง และหน้าเว็บแสดงคำเตือน
