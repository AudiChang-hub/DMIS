from odoo import models, fields, api


class DealerKanban(models.Model):
    """繼承 dms.dealer，新增 Kanban 卡片欄位顯示設定的 computed 旗標"""
    _inherit = 'dms.dealer'

    # ── Kanban 顯示旗標（store=False，每次渲染由設定讀取）─────────────
    kanban_cfg_code = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_store_type = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_owner = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_manager = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_phone1 = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_phone2 = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_mobile = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_email = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_address = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_brand = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_visits = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_line = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_gift = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_symgas = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_symev = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_suzukigas = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_suzukiev = fields.Boolean(compute='_compute_kanban_cfg', store=False)

    def _compute_kanban_cfg(self):
        """
        一次讀取設定後套用到所有記錄（一批一次 DB query）。
        若尚未建立設定記錄，使用預設值。
        """
        config = self.env['dms.kanban.dealer.config'].sudo().search(
            [], limit=1, order='id asc'
        )
        if config:
            cfg = dict(
                kanban_cfg_code=config.show_code,
                kanban_cfg_store_type=config.show_store_type,
                kanban_cfg_owner=config.show_owner_name,
                kanban_cfg_manager=config.show_store_manager,
                kanban_cfg_phone1=config.show_phone_1,
                kanban_cfg_phone2=config.show_phone_2,
                kanban_cfg_mobile=config.show_mobile,
                kanban_cfg_email=config.show_email,
                kanban_cfg_address=config.show_address,
                kanban_cfg_brand=config.show_brand,
                kanban_cfg_visits=config.show_visit_count,
                kanban_cfg_line=config.show_line_group,
                kanban_cfg_gift=config.show_holiday_gift,
                kanban_cfg_symgas=config.show_sym_gas,
                kanban_cfg_symev=config.show_sym_ev,
                kanban_cfg_suzukigas=config.show_suzuki_gas,
                kanban_cfg_suzukiev=config.show_suzuki_ev,
            )
        else:
            # 預設值（尚未設定時）
            cfg = dict(
                kanban_cfg_code=True,
                kanban_cfg_store_type=True,
                kanban_cfg_owner=True,
                kanban_cfg_manager=False,
                kanban_cfg_phone1=True,
                kanban_cfg_phone2=False,
                kanban_cfg_mobile=False,
                kanban_cfg_email=False,
                kanban_cfg_address=False,
                kanban_cfg_brand=True,
                kanban_cfg_visits=True,
                kanban_cfg_line=False,
                kanban_cfg_gift=False,
                kanban_cfg_symgas=False,
                kanban_cfg_symev=False,
                kanban_cfg_suzukigas=False,
                kanban_cfg_suzukiev=False,
            )

        for rec in self:
            for key, val in cfg.items():
                setattr(rec, key, val)
