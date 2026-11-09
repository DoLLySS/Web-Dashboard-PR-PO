"""ตรวจว่า Flow ของ Power Automate ใช้งานได้ โดยส่งไฟล์ข้อความเล็ก ๆ 1 ไฟล์ไปที่โฟลเดอร์ _connection_test เท่านั้น

วิธีใช้ (รันในโฟลเดอร์โปรเจกต์ ด้วย venv ของแอป เพราะอ่านค่า POWER_AUTOMATE_* จากไฟล์ .env):
    venv/bin/python scripts/check_flow.py

ใช้กับไลบรารีทดสอบที่ว่างก่อนเสมอ ไฟล์ที่ส่งไม่มีข้อมูลจริง (ข้อความตายตัวกับเวลา) ส่งเสร็จแล้วต้องลบไฟล์ทดสอบเองในไลบรารี
ผลลัพธ์พิมพ์เฉพาะชื่อเซิร์ฟเวอร์ ลิงก์ที่ Flow ตอบ และผลตรวจ ไม่พิมพ์ URL เต็มของ Flow หรือคีย์
"""

import sys
from datetime import datetime
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config.settings import get_env_text  # noqa: E402
from utils.power_automate_api import URL_SETTING, PowerAutomateError, upload_file_to_flow  # noqa: E402

TEST_FOLDER_PARTS: list[str] = ["_connection_test"]


def main(argv: Optional[list[str]] = None) -> int:
    """ส่งไฟล์ทดสอบ 1 ไฟล์ คืนค่า 0 เมื่อ Flow ตอบลิงก์กลับมาถูกต้อง และ 1 เมื่อไม่สำเร็จ"""
    del argv  # ไม่มีพารามิเตอร์ ตั้งใจให้รันง่ายที่สุด
    url = get_env_text(URL_SETTING)
    if not url:
        print(f"ยังไม่ได้ตั้ง {URL_SETTING} ในไฟล์ .env", file=sys.stderr)
        return 1
    host = urlparse(url).hostname or "(อ่านชื่อเซิร์ฟเวอร์ไม่ได้)"
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"check_flow_{stamp}.txt"
    content = f"Masterlist connection test {stamp}\nไฟล์นี้ไม่มีข้อมูลจริง ลบได้\n".encode()
    print(f"ส่งไฟล์ทดสอบ {file_name} ไปที่โฟลเดอร์ {'/'.join(TEST_FOLDER_PARTS)} (เซิร์ฟเวอร์ {host})")
    try:
        uploaded = upload_file_to_flow(file_name, content, TEST_FOLDER_PARTS)
    except PowerAutomateError as error:
        print(f"ไม่สำเร็จ: {error}", file=sys.stderr)
        return 1
    print("สำเร็จ: Flow ตอบกลับลิงก์")
    print(f"  ไฟล์: {uploaded.file_url}")
    print(f"  โฟลเดอร์: {uploaded.folder_url or '(Flow ไม่ได้ตอบ folderUrl)'}")
    print("ตรวจในไลบรารีว่ามีไฟล์นี้อยู่ในโฟลเดอร์ _connection_test จริง แล้วลบไฟล์ทดสอบทิ้ง")
    return 0


if __name__ == "__main__":
    sys.exit(main())
