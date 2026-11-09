"""ทดสอบเกณฑ์ใบกำกับภาษีค้าง: ค่าทั้งหมดต้องมาจาก OVERDUE_RULE ใน config/constants.py"""

from dataclasses import replace
from datetime import date, timedelta
from typing import Any

import pytest

import pages_ui.overview as overview
from config.constants import OVERDUE_RULE

TODAY: date = date(2026, 11, 9)


def make_row(days_ago: int, document_days_ago: int = 0) -> dict[str, Any]:
    """สร้างรายการที่บันทึกเมื่อ days_ago วันก่อน และมีวันที่เอกสารเมื่อ document_days_ago วันก่อน"""
    return {
        "created_at": f"{TODAY - timedelta(days=days_ago)} 09:00:00",
        "date": (TODAY - timedelta(days=document_days_ago)).isoformat(),
    }


def test_row_is_overdue_only_after_exceeding_the_limit() -> None:
    """ครบ 14 วันยังไม่เกินกำหนด และ 15 วันเกินกำหนด"""
    assert OVERDUE_RULE.days_limit == 14
    assert overview.find_overdue_transactions([make_row(14)], TODAY) == []
    overdue = overview.find_overdue_transactions([make_row(15)], TODAY)
    assert [row["days_pending"] for row in overdue] == [15]


def test_upload_date_is_used_instead_of_document_date() -> None:
    """ค่าเริ่มต้นนับจากวันที่บันทึก แม้วันที่เอกสารจะเก่ามาก"""
    assert overview.find_overdue_transactions([make_row(1, document_days_ago=300)], TODAY) == []


def test_next_column_is_used_when_reference_date_is_invalid() -> None:
    """วันที่บันทึกอ่านไม่ได้ ให้ใช้คอลัมน์ถัดไปในเกณฑ์"""
    row = {"created_at": "ไม่ใช่วันที่", "date": (TODAY - timedelta(days=20)).isoformat()}
    assert overview.find_overdue_transactions([row], TODAY)[0]["days_pending"] == 20


def test_changing_days_limit_changes_result_and_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """เปลี่ยนจำนวนวันในเกณฑ์จุดเดียว ต้องมีผลทั้งการคำนวณและข้อความบนหน้าจอ"""
    monkeypatch.setattr(overview, "OVERDUE_RULE", replace(OVERDUE_RULE, days_limit=3))
    assert len(overview.find_overdue_transactions([make_row(4)], TODAY)) == 1
    assert "3 วัน" in overview.build_no_overdue_html()


def test_changing_reference_columns_changes_result(monkeypatch: pytest.MonkeyPatch) -> None:
    """เปลี่ยนวันที่อ้างอิงในเกณฑ์จุดเดียว ต้องเปลี่ยนการนับวันค้าง"""
    monkeypatch.setattr(overview, "OVERDUE_RULE", replace(OVERDUE_RULE, reference_date_columns=("date",)))
    overdue = overview.find_overdue_transactions([make_row(1, document_days_ago=30)], TODAY)
    assert [row["days_pending"] for row in overdue] == [30]
