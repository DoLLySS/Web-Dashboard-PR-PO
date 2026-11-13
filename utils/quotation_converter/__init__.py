"""ตัวแปลงใบเสนอราคา PDF เป็น Excel (ใช้ผ่าน wrapper.py เท่านั้น)"""

from utils.quotation_converter.wrapper import ConversionResult, convert_pdf_to_excel

__all__ = ["ConversionResult", "convert_pdf_to_excel"]
