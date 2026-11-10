"""ทดสอบ CSV ที่ปลอดภัยต่อ Excel (utils/csv_export.py): ไม่ถูกตีเป็นสูตร และเลขที่ขึ้นต้นด้วย 0 ไม่เพี้ยน"""

import csv
import io

import pandas as pd
import pytest

from utils.csv_export import dataframe_to_csv_bytes

ID_COLUMNS = frozenset({"Tel.", "Tax ID"})


def read_back(data: bytes) -> list[dict[str, str]]:
    assert data.startswith(b"\xef\xbb\xbf")  # BOM ให้ Excel เปิดภาษาไทยไม่เพี้ยน
    return list(csv.DictReader(io.StringIO(data.decode("utf-8-sig"))))


@pytest.mark.parametrize("value", ["=1+1", "+66812345678x", "-2+3", "@SUM(A1)", "\tcmd", "\rcmd", "=HYPERLINK(\"http://x\")"])
def test_text_that_looks_like_a_formula_gets_a_leading_quote(value: str) -> None:
    table = pd.DataFrame({"Description": [value]})

    (row,) = read_back(dataframe_to_csv_bytes(table, ID_COLUMNS))

    assert row["Description"] == "'" + value


@pytest.mark.parametrize("value", ["ปกติ", "Monitor Dell", "a=b", "ราคา -5", "", "https://x.test/f?a=1"])
def test_ordinary_text_is_unchanged(value: str) -> None:
    table = pd.DataFrame({"Description": [value]})

    (row,) = read_back(dataframe_to_csv_bytes(table, ID_COLUMNS))

    assert row["Description"] == value


def test_numbers_and_empty_cells_are_not_touched() -> None:
    table = pd.DataFrame({"Price": [-100.5, None, 20.0], "Company": ["ก", None, "ข"]})

    rows = read_back(dataframe_to_csv_bytes(table, ID_COLUMNS))

    assert [row["Price"] for row in rows] == ["-100.5", "", "20.0"]
    assert [row["Company"] for row in rows] == ["ก", "", "ข"]


@pytest.mark.parametrize("value", ["0812345678", "1234567890123", "+66 81 234 5678", "02-123-4567", "(02) 123 4567"])
def test_id_columns_keep_leading_zero_and_long_digits_in_excel(value: str) -> None:
    table = pd.DataFrame({"Tel.": [value], "Tax ID": [value]})

    (row,) = read_back(dataframe_to_csv_bytes(table, ID_COLUMNS))

    assert row["Tel."] == f'="{value}"' and row["Tax ID"] == f'="{value}"'


def test_id_column_with_unexpected_text_is_not_turned_into_a_formula() -> None:
    table = pd.DataFrame({"Tel.": ['0812345678"&CMD()&"', "=1+1"]})

    rows = read_back(dataframe_to_csv_bytes(table, ID_COLUMNS))

    assert not rows[0]["Tel."].startswith("=")  # มีอักขระนอกรูปแบบเบอร์ จึงไม่ห่อด้วย =""
    assert rows[1]["Tel."] == "'=1+1"


def test_empty_table_gives_header_only_and_original_is_not_modified() -> None:
    table = pd.DataFrame({"Description": ["=1+1"]})

    dataframe_to_csv_bytes(table, ID_COLUMNS)

    assert table.loc[0, "Description"] == "=1+1"
    assert read_back(dataframe_to_csv_bytes(table.iloc[0:0], ID_COLUMNS)) == []
