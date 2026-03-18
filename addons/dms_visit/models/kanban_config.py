from odoo import models, fields, api
from odoo.exceptions import ValidationError

# 所有可選欄位（供 constraint 迭代用）
_SHOW_FIELDS = [
    'show_code', 'show_store_type', 'show_owner_name', 'show_store_manager',
    'show_phone_1', 'show_phone_2', 'show_mobile', 'show_email', 'show_address',
    'show_brand', 'show_visit_count', 'show_line_group', 'show_holiday_gift',
    'show_sym_gas', 'show_sym_ev', 'show_suzuki_gas', 'show_suzuki_ev',
]


class DmsKanbanDealerConfig(models.Model):
    _name = 'dms.kanban.dealer.config'
    _description = '車行 Kanban 卡片欄位設定'

    # ── 基本資訊 ──────────────────────────────────────────────────
    show_code = fields.Boolean(string='車行代碼', default=True)
    show_store_type = fields.Boolean(string='車行類型', default=True)
    show_brand = fields.Boolean(string='品牌', default=True)

    # ── 人員 ──────────────────────────────────────────────────────
    show_owner_name = fields.Boolean(string='負責人', default=True)
    show_store_manager = fields.Boolean(string='店長', default=False)

    # ── 聯絡資訊 ──────────────────────────────────────────────────
    show_phone_1 = fields.Boolean(string='電話1', default=True)
    show_phone_2 = fields.Boolean(string='電話2', default=False)
    show_mobile = fields.Boolean(string='手機', default=False)
    show_email = fields.Boolean(string='電子信箱', default=False)
    show_address = fields.Boolean(string='地址', default=False)

    # ── 拜訪與活動 ────────────────────────────────────────────────
    show_visit_count = fields.Boolean(string='拜訪次數', default=True)
    show_line_group = fields.Boolean(string='LINE 群組', default=False)
    show_holiday_gift = fields.Boolean(string='年節送禮', default=False)

    # ── 價格表 ────────────────────────────────────────────────────
    show_sym_gas = fields.Boolean(string='三陽油車價格表', default=False)
    show_sym_ev = fields.Boolean(string='三陽電車價格表', default=False)
    show_suzuki_gas = fields.Boolean(string='台鈴油車價格表', default=False)
    show_suzuki_ev = fields.Boolean(string='台鈴電車價格表', default=False)

    # ── 已選數量（computed）────────────────────────────────────────
    selected_count = fields.Integer(
        compute='_compute_selected_count',
        string='已選欄位數',
    )

    @api.depends(
        'show_code', 'show_store_type', 'show_owner_name', 'show_store_manager',
        'show_phone_1', 'show_phone_2', 'show_mobile', 'show_email', 'show_address',
        'show_brand', 'show_visit_count', 'show_line_group', 'show_holiday_gift',
        'show_sym_gas', 'show_sym_ev', 'show_suzuki_gas', 'show_suzuki_ev',
    )
    def _compute_selected_count(self):
        for rec in self:
            rec.selected_count = sum(1 for f in _SHOW_FIELDS if getattr(rec, f))

    @api.constrains(
        'show_code', 'show_store_type', 'show_owner_name', 'show_store_manager',
        'show_phone_1', 'show_phone_2', 'show_mobile', 'show_email', 'show_address',
        'show_brand', 'show_visit_count', 'show_line_group', 'show_holiday_gift',
        'show_sym_gas', 'show_sym_ev', 'show_suzuki_gas', 'show_suzuki_ev',
    )
    def _check_max_fields(self):
        for rec in self:
            count = sum(1 for f in _SHOW_FIELDS if getattr(rec, f))
            if count > 10:
                raise ValidationError(
                    '卡片最多顯示 10 個欄位（目前已選 %d 個），請取消部分勾選。' % count
                )

    @api.model
    def get_kanban_config(self):
        """取得或自動建立 singleton 設定記錄"""
        config = self.search([], limit=1, order='id asc')
        if not config:
            config = self.sudo().create({})
        return config
