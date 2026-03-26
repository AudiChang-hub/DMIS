from odoo import api, models, SUPERUSER_ID


class IrUiMenu(models.Model):
    _inherit = 'ir.ui.menu'

    @api.model
    def _visible_menu_ids(self, debug=False):
        """覆寫菜單可見性，加入 um.access.group 白名單過濾。

        過濾規則：
        - SUPERUSER 或 base.group_system 成員：不施加額外限制。
        - 無 um_group_ids：不施加額外限制（原 Odoo 行為）。
        - 有 um_group_ids：顯示所有群組的菜單聯集，並自動補齊祖先菜單（供導航使用）。
        """
        visible = super()._visible_menu_ids(debug=debug)

        # SUPERUSER 不受限
        if self.env.uid == SUPERUSER_ID:
            return visible

        user = self.env.user

        # 系統管理員不受限
        if user.has_group('base.group_system'):
            return visible

        um_groups = user.sudo().um_group_ids
        # 未指派自訂群組：不施加額外限制
        if not um_groups:
            return visible

        # 計算所有群組菜單的聯集
        allowed_menu_ids = set()
        for group in um_groups:
            allowed_menu_ids |= set(group.sudo().menu_ids.ids)

        if not allowed_menu_ids:
            return []

        visible_set = set(visible)
        base_allowed = visible_set & allowed_menu_ids

        if not base_allowed:
            return []

        # 直接用 SQL 查詢父菜單 ID，避免觸發 _filter_visible_menus 造成遞迴
        self.env.cr.execute(
            "SELECT id, parent_id FROM ir_ui_menu WHERE id = ANY(%s)",
            (list(visible_set),)
        )
        parent_map = {row[0]: row[1] for row in self.env.cr.fetchall()}

        # 補齊祖先菜單（讓使用者可以展開導覽樹）
        final_allowed = set(base_allowed)
        for mid in list(base_allowed):
            pid = parent_map.get(mid)
            while pid is not None:
                final_allowed.add(pid)
                pid = parent_map.get(pid)

        return list(final_allowed)
