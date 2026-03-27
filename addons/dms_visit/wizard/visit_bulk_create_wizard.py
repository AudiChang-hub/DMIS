from odoo import fields, models
from odoo.exceptions import UserError


class VisitBulkCreateWizard(models.TransientModel):
    _name = 'dms.visit.bulk.create.wizard'
    _description = '批次建立拜訪'

    visit_date = fields.Datetime(
        string='拜訪日期',
        required=True,
        default=fields.Datetime.now,
    )
    visitor_id = fields.Many2one(
        'res.users',
        string='拜訪人員',
        required=True,
        default=lambda self: self.env.user,
    )
    purpose_id = fields.Many2one(
        'dms.visit.purpose',
        string='拜訪目的',
        ondelete='set null',
    )
    dealer_ids = fields.Many2many(
        'dms.dealer',
        'dms_visit_bulk_create_wizard_dealer_rel',
        'wizard_id',
        'dealer_id',
        string='拜訪車行',
        required=True,
        domain="[('active', '=', True)]",
    )
    note = fields.Text(string='備註')

    def action_create_visits(self):
        self.ensure_one()
        if not self.dealer_ids:
            raise UserError('請至少選擇一間車行。')

        vals_list = []
        for dealer in self.dealer_ids:
            vals_list.append({
                'visit_date': self.visit_date,
                'dealer_id': dealer.id,
                'visitor_id': self.visitor_id.id,
                'purpose_id': self.purpose_id.id or False,
                'note': self.note or False,
            })

        self.env['dms.visit'].create(vals_list)
        return {
            'type': 'ir.actions.client',
            'tag': 'reload',
        }
