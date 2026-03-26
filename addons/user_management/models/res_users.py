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
            self._sync_um_odoo_groups()
        return result

    def _sync_um_odoo_groups(self):
        """根據目前的 um_group_ids，同步 Odoo 原生群組（groups_id）。

        - 計算所有 um 群組的 odoo_group_ids 聯集，作為「應有」集合。
        - 計算全系統所有 um 群組的 odoo_group_ids 聯集，作為「um 管理群組」集合。
        - 對每位使用者：加入缺少的群組；移除已不需要（且屬 um 管理範圍）的群組。
        """
        # 全系統所有 um 可能授予的群組 ID（用於判斷哪些是 um 系統管理的）
        all_um_groups = self.env['um.access.group'].sudo().search([])
        all_um_managed_ids = set(all_um_groups.mapped('odoo_group_ids').ids)

        for user in self:
            should_have_ids = set(
                user.sudo().um_group_ids.mapped('odoo_group_ids').ids
            )
            current_ids = set(user.groups_id.ids)
            currently_um_managed = current_ids & all_um_managed_ids

            to_add = should_have_ids - current_ids
            to_remove = currently_um_managed - should_have_ids

            if to_add or to_remove:
                cmds = [(4, gid) for gid in to_add] + [(3, gid) for gid in to_remove]
                # 使用 super() 避免觸發本覆寫造成遞迴
                super(ResUsers, user).write({'groups_id': cmds})
