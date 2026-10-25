"""หน้า Setting: ตั้งค่าระบบ (โครงเปล่า ยังไม่ได้พัฒนา)"""

from datetime import date

import streamlit as st


def render(start_date: date, end_date: date) -> None:
    """แสดงเนื้อหาหน้า Setting

    Args:
        start_date: วันที่เริ่มต้นจาก Date Filter (หน้านี้ยังไม่ใช้)
        end_date: วันที่สิ้นสุดจาก Date Filter (หน้านี้ยังไม่ใช้)

    Returns:
        ไม่มีค่าคืน (วาดหน้าจอด้วย Streamlit)
    """
    # TODO: เช่น จัดการหมวดหมู่, ตั้งค่าจำนวนวันแจ้งเตือน, ตั้งค่า SharePoint
    st.info("หน้านี้ยังไม่ได้พัฒนา")
