"""
16.0.2.0.7 — price_change_note / installment_change_note 改為 store=False

欄位改為非儲存（store=False），DB column 雖保留但 Odoo 不再讀寫。
此 migration 清除現有殘留值。
"""


def migrate(cr, version):
    if not version:
        return
    cr.execute(
        "UPDATE dms_product SET price_change_note = NULL"
        " WHERE price_change_note IS NOT NULL"
    )
    cr.execute(
        "UPDATE dms_product_installment_line SET installment_change_note = NULL"
        " WHERE installment_change_note IS NOT NULL"
    )
