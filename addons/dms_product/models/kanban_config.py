from odoo import models, fields, api
from odoo.exceptions import ValidationError

_SHOW_FIELDS = [
    'show_model', 'show_year', 'show_brake_type',
    'show_energy_type', 'show_color', 'show_color_code',
]


class DmsKanbanProductConfig(models.Model):
    _name = 'dms.kanban.product.config'
    _description = '產品 Kanban 卡片欄位設定'

    show_model = fields.Boolean(string='型號', default=True)
    show_year = fields.Boolean(string='年份', default=True)
    show_brake_type = fields.Boolean(string='煞車型式', default=False)
    show_energy_type = fields.Boolean(string='能源型式', default=True)
    show_color = fields.Boolean(string='顏色', default=True)
    show_color_code = fields.Boolean(string='顏色代碼', default=False)

    selected_count = fields.Integer(
        compute='_compute_selected_count',
        string='已選欄位數',
    )

    @api.depends(*_SHOW_FIELDS)
    def _compute_selected_count(self):
        for rec in self:
            rec.selected_count = sum(1 for f in _SHOW_FIELDS if getattr(rec, f))

    @api.constrains(*_SHOW_FIELDS)
    def _check_max_fields(self):
        for rec in self:
            if rec.selected_count > 10:
                raise ValidationError('最多只能顯示 10 個欄位。')
