"""
16.0.2.0.6 — 月付金公式改為年金現值公式

舊：單利 PMT = PV × (1 + rate_pct/100 × years) / n
新：年金 PMT = PV × r / (1 - (1+r)^-n)，r = rate_pct/100/12

monthly_payment 為 computed+store，升級後不會自動重算；
此 post_migrate 強制觸發重新計算所有資料。
"""


def migrate(cr, version):
    if not version:
        return
    from odoo import api, registry as odoo_registry
    env = api.Environment(cr, 1, {})
    lines = env['dms.product.installment.line'].search([])
    lines._compute_monthly_payment()
    # 手動 flush 確保寫入 DB
    lines.flush_recordset(['monthly_payment'])
