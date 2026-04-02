from odoo import models, fields, api


class DmsCommissionRecord(models.Model):
    """傭金計算記錄：訂單結案時自動產生，存放計算結果"""
    _name = 'dms.commission.record'
    _description = '傭金記錄'
    _rec_name = 'sale_order_id'
    _order = 'closed_date desc'

    sale_order_id = fields.Many2one(
        'dms.sale.order', string='銷貨訂單', required=True,
        ondelete='cascade', index=True)
    dealer_id = fields.Many2one(
        'dms.dealer', string='車行', ondelete='restrict', index=True)
    product_tmpl_id = fields.Many2one(
        'dms.product.template', string='車型', ondelete='restrict')
    closed_date = fields.Datetime(string='結案時間')
    closed_month = fields.Char(
        string='月份', compute='_compute_closed_month', store=True,
        help='格式 YYYY-MM，用於月結查詢')
    base_commission = fields.Float(
        string='基礎傭金', digits=(12, 0),
        help='基礎規則或車行覆蓋後的傭金金額')
    volume_bonus = fields.Float(
        string='台數獎金', digits=(12, 0), default=0.0,
        help='當月台數達標後的加碼（可被重算更新）')
    total_commission = fields.Float(
        string='合計傭金', digits=(12, 0),
        compute='_compute_total', store=True)
    state = fields.Selection(
        [('active', '正常'), ('voided', '已撤銷')],
        string='狀態', default='active', required=True, index=True)

    _sql_constraints = [
        ('sale_order_uniq', 'unique(sale_order_id)',
         '一張訂單只能對應一筆傭金記錄'),
    ]

    @api.depends('closed_date')
    def _compute_closed_month(self):
        for rec in self:
            if rec.closed_date:
                rec.closed_month = rec.closed_date.strftime('%Y-%m')
            else:
                rec.closed_month = False

    @api.depends('base_commission', 'volume_bonus')
    def _compute_total(self):
        for rec in self:
            rec.total_commission = rec.base_commission + rec.volume_bonus
