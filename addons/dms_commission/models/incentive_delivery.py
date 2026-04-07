from odoo import models, fields, api
from odoo.exceptions import ValidationError


class DmsIncentiveDelivery(models.Model):
    """激勵核銷記錄：一台已結案訂單對應一條激勵品項記錄"""
    _name = 'dms.incentive.delivery'
    _description = '激勵核銷記錄'
    _rec_name = 'sale_order_id'
    _order = 'sale_order_id desc, incentive_type_id'

    sale_order_id = fields.Many2one(
        'dms.sale.order', string='銷貨訂單', required=True,
        ondelete='cascade', index=True)
    dealer_id = fields.Many2one(
        'dms.dealer', string='車行', ondelete='restrict', index=True)
    incentive_rule_id = fields.Many2one(
        'dms.incentive.rule', string='觸發規則', ondelete='restrict')
    contract_line_id = fields.Many2one(
        'dms.commission.dealer.contract.line', string='來源合約明細',
        ondelete='restrict',
        help='由車行傭金合約產生的激勵記錄')
    incentive_type_id = fields.Many2one(
        'dms.incentive.type', string='激勵品項', required=True,
        ondelete='restrict')
    qty = fields.Integer(string='數量', required=True, default=1)
    state = fields.Selection(
        [
            ('pending', '待給'),
            ('delivered', '已給'),
            ('voided', '已作廢'),
        ],
        string='狀態', default='pending', required=True, index=True)
    delivery_method = fields.Selection(
        [
            ('self', '自送'),
            ('manufacturer', '原廠區經理'),
        ],
        string='給出方式',
        help='狀態為「已給」時必填')
    delivered_date = fields.Date(string='給出日期')
    delivered_by = fields.Char(string='給出人員')
    remark = fields.Text(string='備註')
    closed_month = fields.Char(
        string='月份', related='sale_order_id.closed_month',
        store=True, index=True)

    @api.constrains('state', 'delivery_method')
    def _check_delivered_method(self):
        for rec in self:
            if rec.state == 'delivered' and not rec.delivery_method:
                raise ValidationError('標記為「已給」時必須填寫給出方式')

    def action_mark_delivered(self):
        """標記為已給（從 form/tree 按鈕呼叫）"""
        for rec in self:
            if rec.state == 'pending':
                rec.state = 'delivered'
                if not rec.delivered_date:
                    rec.delivered_date = fields.Date.today()
