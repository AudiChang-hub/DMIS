from odoo import models


class DmsProductInstallmentLineProxy(models.Model):
    """dms_sale 早於 dms_product 載入，需在此宣告 comodel 讓 Many2one field setup 成功。
    完整欄位定義與商業邏輯由 dms_product/models/product_installment_line.py 提供。"""
    _name = 'dms.product.installment.line'
    _description = '產品分期方案明細（代理宣告）'
