"""
16.0.2.0.5 — 年利率欄位從小數改為百分比

舊：interest_rate = 0.05 代表 5%
新：interest_rate = 5.0  代表 5%

將現有資料全部乘以 100。
"""


def migrate(cr, version):
    if not version:
        return
    cr.execute("""
        UPDATE dms_product_installment_line
        SET interest_rate = interest_rate * 100
        WHERE interest_rate != 0
    """)
