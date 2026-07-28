from odoo import api, fields, models


class DmsProductInstallmentLog(models.Model):
    _name = 'dms.product.installment.log'
    _description = '分期方案異動日誌'
    _order = 'changed_at desc'
    _rec_name = 'changed_at'

    product_id = fields.Many2one(
        'dms.product', string='產品項', required=True,
        ondelete='cascade', index=True)
    changed_at = fields.Datetime(
        string='異動時間', required=True,
        default=fields.Datetime.now, readonly=True)
    user_id = fields.Many2one(
        'res.users', string='操作者', required=True,
        default=lambda self: self.env.user, readonly=True)
    action = fields.Selection(
        [('add', '新增'), ('modify', '修改'), ('delete', '刪除')],
        string='動作', required=True, readonly=True)
    periods = fields.Integer(string='期數', readonly=True)
    description = fields.Char(string='異動摘要', readonly=True)
    note = fields.Char(string='異動說明', readonly=True)
