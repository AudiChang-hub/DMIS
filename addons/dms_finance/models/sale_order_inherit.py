from odoo import models, fields, api


class SaleOrderFinance(models.Model):
    _inherit = 'dms.sale.order'

    finance_ids = fields.One2many(
        'dms.sale.finance', 'sale_order_id', string='財務結算')
    finance_count = fields.Integer(
        string='財務結算筆數', compute='_compute_finance_count')

    @api.depends('finance_ids')
    def _compute_finance_count(self):
        for rec in self:
            rec.finance_count = len(rec.finance_ids)

    def action_view_finance(self):
        """開啟（或自動建立）此訂單的財務結算記錄。"""
        self.ensure_one()
        if not self.finance_ids:
            finance = self.env['dms.sale.finance'].create({
                'sale_order_id': self.id,
            })
        else:
            finance = self.finance_ids[0]
        return {
            'type': 'ir.actions.act_window',
            'name': '財務結算',
            'res_model': 'dms.sale.finance',
            'view_mode': 'form',
            'res_id': finance.id,
            'target': 'current',
        }
