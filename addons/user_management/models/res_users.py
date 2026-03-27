from odoo import fields, models

# 不應由 um 系統自動授予的廣域系統群組
_EXCLUDE_XML_IDS = [
    'base.group_user',
    'base.group_system',
    'base.group_public',
    'base.group_portal',
    'base.group_erp_manager',
]


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
        """根據 um_group_ids 自動同步 Odoo 原生群組。

        授予來源（聯集）：
        1. um.access.group.odoo_group_ids  — 管理員手動指定
        2. um.access.group.menu_ids 的所有 groups_id — 自動從菜單推導

        只移除「屬於 um 管理範圍」的群組，不動其他手動賦予的群組。
        排除廣域系統群組（base.group_user 等）以避免過度授權。
        """
        # 計算需排除的廣域群組 ID
        exclude_ids = set()
        for xml_id in _EXCLUDE_XML_IDS:
            g = self.env.ref(xml_id, raise_if_not_found=False)
            if g:
                exclude_ids.add(g.id)

        # 全系統 um 群組可能授予的所有群組 ID（manual + auto from menus）
        all_um_groups = self.env['um.access.group'].sudo().search([])
        all_um_managed_ids = set()
        for g in all_um_groups:
            all_um_managed_ids |= set(g.odoo_group_ids.ids)
            all_um_managed_ids |= set(g.menu_ids.mapped('groups_id').ids)
        all_um_managed_ids -= exclude_ids

        for user in self:
            um_groups = user.sudo().um_group_ids

            # 1. 手動指定的 Odoo 群組
            manual_ids = set(um_groups.mapped('odoo_group_ids').ids)
            # 2. 從菜單自動推導的 Odoo 群組
            menu_group_ids = set(um_groups.mapped('menu_ids').mapped('groups_id').ids)

            should_have_ids = (manual_ids | menu_group_ids) - exclude_ids
            current_ids = set(user.groups_id.ids)
            currently_um_managed = current_ids & all_um_managed_ids

            to_add = should_have_ids - current_ids
            to_remove = currently_um_managed - should_have_ids

            if to_add or to_remove:
                cmds = [(4, gid) for gid in to_add] + [(3, gid) for gid in to_remove]
                super(ResUsers, user).write({'groups_id': cmds})
