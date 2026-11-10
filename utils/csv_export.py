"""สร้างไฟล์ CSV ที่เปิดใน Excel ได้อย่างปลอดภัย

ข้อมูลหลายช่อง (Description, Company, QT No. ฯลฯ) มาจาก PDF/Excel ที่ผู้ใช้อัปโหลด ถ้าค่าขึ้นต้นด้วย = + - @ Excel จะตีเป็นสูตรและรันตอนเปิดไฟล์
และ Excel ตัดเลข 0 นำหน้าของเบอร์โทร / แปลง Tax ID 13 หลักเป็น 1.23E+12 จึงต้องเตรียมค่าก่อนเขียน

ไฟล์นี้ไม่เรียก Streamlit (ผู้เรียกเป็นคนแสดง error เอง)
"""

import re
from typing import Any, Iterable

import pandas as pd

FORMULA_PREFIXES: tuple[str, ...] = ("=", "+", "-", "@", "\t", "\r")
TEXT_MARKER: str = "'"
# ค่าที่เป็นเลขล้วนของคอลัมน์รหัส (เบอร์โทร / Tax ID): ปลอดภัยพอจะห่อเป็น ="..." ให้ Excel เก็บเป็นข้อความ
ID_VALUE_PATTERN: re.Pattern[str] = re.compile(r"[0-9+\-() ]{1,40}")
CSV_ENCODING: str = "utf-8-sig"  # มี BOM เพื่อให้ Excel เปิดภาษาไทยไม่เพี้ยน


def _prepare_cell(value: Any, is_id_column: bool) -> Any:
    """เตรียมค่า 1 ช่อง: ข้อความที่อาจถูกตีเป็นสูตรใส่ ' นำหน้า, เลขรหัสห่อเป็น ="..." ค่าที่ไม่ใช่ข้อความไม่แตะ"""
    if not isinstance(value, str):
        return value
    if is_id_column and ID_VALUE_PATTERN.fullmatch(value):
        return f'="{value}"'
    if value.startswith(FORMULA_PREFIXES):
        return TEXT_MARKER + value
    return value


def make_csv_safe(table: pd.DataFrame, id_columns: Iterable[str] = ()) -> pd.DataFrame:
    """คืนสำเนาของตารางที่เตรียมค่าพร้อมเขียน CSV (ไม่แก้ตารางเดิม)

    Args:
        table: ตารางที่จะส่งออก
        id_columns: ชื่อคอลัมน์ที่เป็นรหัสตัวเลข (เบอร์โทร, Tax ID, เลขที่เอกสาร) ที่ต้องคง 0 นำหน้า
    """
    safe = table.copy()
    id_names = frozenset(id_columns)
    for column in safe.columns:
        if safe[column].dtype == object:
            is_id_column = column in id_names
            safe[column] = safe[column].map(lambda value: _prepare_cell(value, is_id_column))
    return safe


def dataframe_to_csv_bytes(table: pd.DataFrame, id_columns: Iterable[str] = ()) -> bytes:
    """แปลงตารางเป็นไบต์ของไฟล์ CSV (UTF-8 มี BOM) ที่ปลอดภัยต่อ Excel"""
    return make_csv_safe(table, id_columns).to_csv(index=False).encode(CSV_ENCODING)
