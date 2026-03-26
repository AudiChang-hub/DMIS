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
    odoo_group_ids = fields.Many2many(
        'res.groups',
        'um_access_group_res_groups_rel',
        'um_group_id',
        'res_group_id',
        string='授予的 Odoo 群組',
        help='指派至此群組的使用者，將自動獲得這些 Odoo 原生群組（用於通過 model 層 ACL 存取）。',
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
        if 'menu_ids' in vals or 'odoo_group_ids' in vals or 'user_ids' in vals:
            # 同步所有成員使用者的 Odoo 群組
            self.mapped('user_ids')._sync_um_odoo_groups()
        return result

    def action_sync_odoo_groups(self):
        """手動觸發：同步所有成員使用者的 Odoo 原生群組。"""
        self.mapped('user_ids')._sync_um_odoo_groups()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': '同步完成',
                'message': f'已同步 {sum(len(g.user_ids) for g in self)} 位使用者的 Odoo 群組。',
                'type': 'success',
                'sticky': False,
            },
        }
