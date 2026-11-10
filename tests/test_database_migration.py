"""ทดสอบการเพิ่มคอลัมน์ที่ขาดตอนเริ่มแอป (data/database.py) เมื่อมีสองโปรเจกต์เริ่มพร้อมกัน"""

import sqlite3
from typing import Any

import pytest

import data.database as database


class FakeConnection:
    """connection ปลอม: PRAGMA บอกว่าไม่มีคอลัมน์ที่เพิ่มทีหลังเลย และ ALTER ที่ชื่ออยู่ใน raise_for จะ error"""

    def __init__(self, raise_for: dict[str, str]) -> None:
        self.raise_for = raise_for
        self.altered: list[str] = []

    def execute(self, sql: str, *_args: Any) -> list[tuple[Any, ...]]:
        if sql.startswith("PRAGMA table_info"):
            return [(0, "id", "INTEGER", 0, None, 1)]
        column = sql.split("ADD COLUMN ", 1)[1].split(" ", 1)[0]
        if column in self.raise_for:
            raise sqlite3.OperationalError(self.raise_for[column])
        self.altered.append(column)
        return []


def test_column_added_by_another_process_in_the_meantime_is_skipped() -> None:
    first = next(iter(database.ADDED_COLUMNS))
    conn = FakeConnection({first: f"duplicate column name: {first}"})

    database._add_missing_columns(conn)  # type: ignore[arg-type]

    assert first not in conn.altered
    assert conn.altered == [name for name in database.ADDED_COLUMNS if name != first]  # คอลัมน์อื่นยังถูกเพิ่มต่อ


def test_other_database_errors_are_not_hidden() -> None:
    first = next(iter(database.ADDED_COLUMNS))
    conn = FakeConnection({first: "database is locked"})

    with pytest.raises(sqlite3.OperationalError, match="locked"):
        database._add_missing_columns(conn)  # type: ignore[arg-type]
