from odoo import models, fields, api


class DealerVisit(models.Model):
    _inherit = 'dms.dealer'

    visit_ids = fields.One2many(
        'dms.visit', 'dealer_id', string='拜訪紀錄',
    )
    visit_count = fields.Integer(
        compute='_compute_visit_count',
        string='拜訪次數',
    )

    @api.depends('visit_ids')
    def _compute_visit_count(self):
        for rec in self:
            rec.visit_count = len(rec.visit_ids)

    def action_open_visits(self):
        self.ensure_one()
        return {
            'name': '%s — 拜訪紀錄' % self.name,
            'type': 'ir.actions.act_window',
            'res_model': 'dms.visit',
            'view_mode': 'tree,form,calendar',
            'domain': [('dealer_id', '=', self.id)],
            'context': {
                'default_dealer_id': self.id,
                'default_visitor_id': self.env.user.id,
            },
        }
