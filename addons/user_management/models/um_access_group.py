from odoo import api, fields, models


class UmAccessGroup(models.Model):
    _name = 'um.access.group'
    _description = '自訂存取群組'
    _order = 'name'

    name = fields.Char(string='群組名稱', required=True)
    description = fields.Text(string='說明')
    active = fields.Boolean(string='啟用', default=True)

    menu_ids = fields.Many2many(
        'ir.ui.menu',
        'um_access_group_menu_rel',
        'group_id',
        'menu_id',
        string='可存取菜單',
    )
    user_ids = fields.Many2many(
        'res.users',
        'um_user_group_rel',
        'group_id',
        'user_id',
        string='使用者',
    )

    menu_count = fields.Integer(
        string='菜單數',
        compute='_compute_menu_count',
    )
    user_count = fields.Integer(
        string='使用者數',
        compute='_compute_user_count',
    )

    @api.depends('menu_ids')
    def _compute_menu_count(self):
        for rec in self:
            rec.menu_count = len(rec.menu_ids)

    @api.depends('user_ids')
    def _compute_user_count(self):
        for rec in self:
            rec.user_count = len(rec.user_ids)

    def write(self, vals):
        result = super().write(vals)
        if 'menu_ids' in vals:
            self.env['ir.ui.menu'].clear_caches()
        return result
