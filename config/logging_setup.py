"""ตั้งค่าระบบ Logging ของทั้งโปรเจค: บันทึกลงไฟล์ logs/app.log (และแสดงที่ Terminal ด้วย)

วิธีใช้ในไฟล์อื่น (ไม่ต้องเรียก setup เอง เพราะ get_logger เรียกให้อัตโนมัติ):
    from config.logging_setup import get_logger
    logger = get_logger(__name__)
    logger.info("บันทึกรายการ id=%s", new_id)
    logger.error("เกิดปัญหา", exc_info=True)   # exc_info=True = เก็บรายละเอียด Error ไว้ในไฟล์ Log

ไฟล์ Log หมุนเวียนอัตโนมัติ (เต็ม 1 MB แล้วสร้างไฟล์ใหม่ เก็บย้อนหลัง 5 ไฟล์) จึงไม่กินดิสก์
ห้ามเขียนรหัสผ่าน / Client Secret ลง Log
"""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from config.settings import DEFAULT_LOG_LEVEL, PROJECT_ROOT, get_env_text

# โฟลเดอร์และชื่อไฟล์ Log (โฟลเดอร์ logs/ ถูกกันไม่ให้ขึ้น Git แล้ว)
LOG_DIRECTORY: Path = PROJECT_ROOT / "logs"
LOG_FILE_PATH: Path = LOG_DIRECTORY / "app.log"
# ขนาดสูงสุดต่อไฟล์ (ไบต์) และจำนวนไฟล์เก่าที่เก็บไว้
LOG_MAX_BYTES: int = 1_000_000
LOG_BACKUP_COUNT: int = 5
# รูปแบบบรรทัด Log: เวลา | ระดับ | ชื่อโมดูล | ข้อความ
LOG_FORMAT: str = "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"

# ชื่อ logger หลักของโปรเจค (ทุกไฟล์ใช้ชื่อขึ้นต้นด้วยชื่อนี้ เพื่อแยกจาก Log ของ Library อื่น)
ROOT_LOGGER_NAME: str = "masterlist"

_is_configured: bool = False


def _resolve_log_level() -> int:
    """แปลงค่า LOG_LEVEL จาก .env เป็นระดับของ logging (ใส่ผิด/ไม่ใส่ = INFO)

    Returns:
        ค่าระดับของ logging เช่น logging.INFO
    """
    level_name = get_env_text("LOG_LEVEL", DEFAULT_LOG_LEVEL).upper()
    level_value = logging.getLevelName(level_name)
    # getLevelName คืน int ถ้าชื่อถูก, คืนข้อความ "Level xxx" ถ้าชื่อผิด
    return level_value if isinstance(level_value, int) else logging.INFO


def setup_logging() -> None:
    """ตั้งค่า Logging ครั้งเดียว (เรียกซ้ำได้ ไม่เพิ่ม handler ซ้ำ)

    ถ้าสร้างไฟล์ Log ไม่ได้ (เช่น ไม่มีสิทธิ์เขียน) จะใช้แค่ Terminal แทน และแอปทำงานต่อได้ตามปกติ
    """
    global _is_configured
    project_logger = logging.getLogger(ROOT_LOGGER_NAME)
    # ตรวจ handlers ด้วย กันเพิ่มซ้ำถ้าโมดูลนี้ถูกโหลดใหม่ (เช่น Streamlit hot reload)
    if _is_configured or project_logger.handlers:
        return

    project_logger.setLevel(_resolve_log_level())
    # ไม่ส่งต่อไป root logger เพื่อกันบรรทัด Log ซ้ำสองครั้ง
    project_logger.propagate = False
    formatter = logging.Formatter(LOG_FORMAT)

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter)
    project_logger.addHandler(console_handler)

    try:
        LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            LOG_FILE_PATH, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        project_logger.addHandler(file_handler)
    except OSError as error:
        project_logger.warning("สร้างไฟล์ Log ที่ %s ไม่ได้ (%s) จึงแสดง Log ที่ Terminal อย่างเดียว", LOG_FILE_PATH, error)

    _is_configured = True


def get_logger(module_name: str) -> logging.Logger:
    """ขอ logger สำหรับโมดูลหนึ่ง ๆ (ตั้งค่าระบบ Logging ให้อัตโนมัติถ้ายังไม่ได้ตั้ง)

    Args:
        module_name: ชื่อโมดูล ให้ส่ง __name__ เสมอ เช่น get_logger(__name__)

    Returns:
        logger ที่เขียนลง logs/app.log
    """
    setup_logging()
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{module_name}")
