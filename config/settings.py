"""อ่านค่าตั้งค่าจากไฟล์ .env พร้อมค่าเริ่มต้น (fallback) เพื่อไม่ให้แอปล่มถ้าทีม IT ลืมใส่ค่า

หลักการ: ทุกที่ที่ต้องอ่านค่าจาก .env ให้เรียกผ่านฟังก์ชันในไฟล์นี้ (ห้ามเรียก os.getenv ตรง ๆ)
- ค่าที่ไม่บังคับ (เช่น LOG_LEVEL): ถ้าไม่ใส่/ใส่ผิดรูปแบบ จะใช้ค่าเริ่มต้นและบันทึกคำเตือนลง Log
- ค่าที่บังคับเฉพาะฟีเจอร์ (เช่น SHAREPOINT_*): ถ้าไม่ใส่ ฟีเจอร์นั้นจะแจ้งผู้ใช้เป็นข้อความไทย แต่แอปส่วนอื่นยังใช้ได้

วิธีเพิ่มตัวแปรใหม่: (1) เพิ่มชื่อ + ค่าเริ่มต้นเป็นค่าคงที่ด้านล่าง (2) อ่านค่าด้วย get_env_text / get_env_int
(3) เพิ่มตัวอย่างใน .env.example
"""

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

# โฟลเดอร์หลักของโปรเจค (config/ ขึ้นไป 1 ชั้น)
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent

# โหลดไฟล์ .env ครั้งเดียวตอน import (ไม่เขียนทับตัวแปรที่ตั้งไว้ในระบบอยู่แล้ว)
# ถ้าไม่มีไฟล์ .env ก็ไม่ error — ทุกค่าจะใช้ค่าเริ่มต้นแทน
load_dotenv(PROJECT_ROOT / ".env")

# ---------------------------------------------------------------------------
# ค่าเริ่มต้น (ใช้เมื่อไม่มีค่าใน .env) — แก้ค่าเริ่มต้นได้ที่นี่
# ---------------------------------------------------------------------------

# ระดับ Log: DEBUG / INFO / WARNING / ERROR (INFO = บันทึกการทำงานปกติ + ปัญหา)
DEFAULT_LOG_LEVEL: str = "INFO"
# รอสูงสุดกี่วินาทีถ้าฐานข้อมูลถูกล็อก
DEFAULT_DB_TIMEOUT_SECONDS: int = 10
# โหมดบันทึกของ SQLite: DELETE = ค่าเดิมของ SQLite (ปลอดภัยกับโฟลเดอร์ที่ OneDrive ซิงก์)
# WAL = รองรับผู้ใช้หลายคนพร้อมกันดีกว่า ใช้ได้เฉพาะเมื่อไฟล์ DB อยู่ดิสก์ในเครื่อง Server (ห้ามอยู่ network share / OneDrive)
DEFAULT_DB_JOURNAL_MODE: str = "DELETE"
# โฟลเดอร์ปลายทางบน SharePoint (เทียบจาก root ของ Site)
DEFAULT_SHAREPOINT_FOLDER_PATH: str = "Shared Documents/PR-PO"

# ใช้ชื่อขึ้นต้นเดียวกับ logger ของโปรเจค (ดู config/logging_setup.py) แต่ไม่ import ตรง ๆ เพื่อกัน import วนกัน
_logger = logging.getLogger("masterlist.config.settings")


def get_env_text(variable_name: str, default_value: str = "") -> str:
    """อ่านค่าข้อความจาก .env / ตัวแปรระบบ ตัดช่องว่างหัวท้าย

    Args:
        variable_name: ชื่อตัวแปร เช่น "LOG_LEVEL"
        default_value: ค่าที่ใช้เมื่อไม่มีตัวแปรนี้ หรือมีแต่เป็นค่าว่าง

    Returns:
        ค่าที่อ่านได้ หรือ default_value (ไม่โยน Error)
    """
    raw_value = os.getenv(variable_name, "")
    cleaned_value = raw_value.strip() if isinstance(raw_value, str) else ""
    return cleaned_value or default_value


def get_env_flag(variable_name: str, default_value: bool = False) -> bool:
    """อ่านค่าเปิด/ปิดจาก .env (1 / true / yes / on = เปิด, 0 / false / no / off = ปิด)

    Args:
        variable_name: ชื่อตัวแปร เช่น "LOCAL_DESKTOP_EXPORT"
        default_value: ค่าที่ใช้เมื่อไม่มีตัวแปรนี้ หรือเขียนไม่เข้าใจ

    Returns:
        True/False (ไม่โยน Error)
    """
    raw_value = get_env_text(variable_name).lower()
    if raw_value in ("1", "true", "yes", "on"):
        return True
    if raw_value in ("0", "false", "no", "off"):
        return False
    if raw_value:
        _logger.warning("ค่า %s ใน .env ('%s') ไม่ใช่ 1/0 จึงใช้ค่าเริ่มต้น %s แทน", variable_name, raw_value, default_value)
    return default_value


def get_env_int(variable_name: str, default_value: int) -> int:
    """อ่านค่าตัวเลขจำนวนเต็มบวกจาก .env ถ้าไม่ใส่หรือใส่ผิดรูปแบบจะใช้ค่าเริ่มต้น

    Args:
        variable_name: ชื่อตัวแปร เช่น "DB_TIMEOUT_SECONDS"
        default_value: ค่าที่ใช้เมื่อไม่มี / ไม่ใช่ตัวเลข / ไม่เป็นจำนวนบวก

    Returns:
        ตัวเลขที่อ่านได้ หรือ default_value (ไม่โยน Error)
    """
    raw_value = get_env_text(variable_name)
    if not raw_value:
        return default_value
    try:
        parsed_value = int(raw_value)
    except ValueError:
        _logger.warning("ค่า %s ใน .env ('%s') ไม่ใช่ตัวเลข จึงใช้ค่าเริ่มต้น %s แทน", variable_name, raw_value, default_value)
        return default_value
    if parsed_value <= 0:
        _logger.warning("ค่า %s ใน .env ต้องมากกว่า 0 จึงใช้ค่าเริ่มต้น %s แทน", variable_name, default_value)
        return default_value
    return parsed_value
