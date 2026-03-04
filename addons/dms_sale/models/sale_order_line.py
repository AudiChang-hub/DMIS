from odoo import models, fields, api


class SaleOrderLine(models.Model):
    _name = 'dms.sale.order.line'
    _description = '精品明細'
    _rec_name = 'accessory_id'
    _order = 'order_id, sequence'

    order_id = fields.Many2one(
        'dms.sale.order', string='訂單', required=True, ondelete='cascade')
    sequence = fields.Integer(string='序號', default=10)
    accessory_id = fields.Many2one(
        'dms.accessory', string='精品', required=True, ondelete='restrict')
    unit_price = fields.Float(string='單價', digits=(12, 0))
    install_fee = fields.Float(string='安裝費', digits=(12, 0))
    quantity = fields.Integer(string='數量', default=1)
    subtotal = fields.Float(
        string='小計', digits=(12, 0),
        compute='_compute_subtotal', store=True)

    @api.depends('unit_price', 'install_fee', 'quantity')
    def _compute_subtotal(self):
        for rec in self:
            rec.subtotal = (rec.unit_price + rec.install_fee) * rec.quantity

    @api.onchange('accessory_id')
    def _onchange_accessory_id(self):
        if self.accessory_id:
            self.unit_price = self.accessory_id.unit_price
            self.install_fee = self.accessory_id.install_fee
