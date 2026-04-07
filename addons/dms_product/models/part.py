from odoo import models, fields


class DmsPart(models.Model):
    """零件清單：供傭金折換實物使用，未來可擴充至庫存、目錄圖等"""
    _name = 'dms.part'
    _description = '零件'
    _rec_name = 'name'
    _order = 'category_id, name'

    name = fields.Char(string='零件名稱', required=True)
    part_number = fields.Char(string='料號', help='原廠料號 / 內部編號')
    category_id = fields.Many2one(
        'dms.part.category', string='分類', ondelete='restrict')
    uom = fields.Char(string='單位', default='個', help='瓶、個、組⋯')
    cost_price = fields.Float(
        string='進貨成本', digits=(12, 0),
        help='每單位進貨成本（TWD），用於傭金折換時的成本估算')
    active = fields.Boolean(string='啟用', default=True)
    note = fields.Text(string='備註')
