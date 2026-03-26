from odoo import fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    um_group_ids = fields.Many2many(
        'um.access.group',
        'um_user_group_rel',
        'user_id',
        'group_id',
        string='自訂存取群組',
    )

    def write(self, vals):
        result = super().write(vals)
        if 'um_group_ids' in vals:
            self.env['ir.ui.menu'].clear_caches()
        return result
