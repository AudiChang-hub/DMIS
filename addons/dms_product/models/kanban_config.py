from odoo import models, fields, api
from odoo.exceptions import ValidationError

_SHOW_FIELDS = [
    'show_model', 'show_year', 'show_brake_type', 'show_energy_type',
    'show_color', 'show_color_code',
    'show_engine_displacement', 'show_fuel_tank', 'show_engine_type',
    'show_consumption_grade', 'show_efficiency', 'show_max_hp', 'show_max_torque',
    'show_power_system', 'show_max_output', 'show_ev_max_hp', 'show_ev_max_torque',
    'show_ev_efficiency', 'show_transmission', 'show_battery_capacity',
    'show_battery_type', 'show_charge_time',
    'show_dimensions', 'show_seat_height', 'show_wheel_base',
    'show_vehicle_weight', 'show_tire_front', 'show_tire_rear',
]


class DmsKanbanProductConfig(models.Model):
    _name = 'dms.kanban.product.config'
    _description = '產品 Kanban 卡片欄位設定'

    # ── 基本資料 ──────────────────────────────────────────
    show_model = fields.Boolean(string='型號', default=True)
    show_year = fields.Boolean(string='年份', default=True)
    show_brake_type = fields.Boolean(string='煞車型式', default=False)
    show_energy_type = fields.Boolean(string='能源型式', default=True)
    show_color = fields.Boolean(string='顏色', default=True)
    show_color_code = fields.Boolean(string='顏色代碼', default=False)

    # ── 動力規格（油車）───────────────────────────────────
    show_engine_displacement = fields.Boolean(string='總排氣量 (cc)', default=False)
    show_fuel_tank = fields.Boolean(string='油箱容量 (L)', default=False)
    show_engine_type = fields.Boolean(string='引擎型式', default=False)
    show_consumption_grade = fields.Boolean(string='能耗等級', default=False)
    show_efficiency = fields.Boolean(string='能源效率 km/L', default=False)
    show_max_hp = fields.Boolean(string='最大馬力 (hp)', default=False)
    show_max_torque = fields.Boolean(string='最大扭力 (Nm)', default=False)

    # ── 動力規格（電車）───────────────────────────────────
    show_power_system = fields.Boolean(string='動力系統', default=False)
    show_max_output = fields.Boolean(string='最大功率 (kW)', default=False)
    show_ev_max_hp = fields.Boolean(string='最大馬力 EV (hp)', default=False)
    show_ev_max_torque = fields.Boolean(string='最大扭力 EV (Nm)', default=False)
    show_ev_efficiency = fields.Boolean(string='能源效率 EV kWh/km', default=False)
    show_transmission = fields.Boolean(string='傳動系統', default=False)
    show_battery_capacity = fields.Boolean(string='電池容量 (kWh)', default=False)
    show_battery_type = fields.Boolean(string='電池型式', default=False)
    show_charge_time = fields.Boolean(string='充電時間 (hr)', default=False)

    # ── 車身規格 ──────────────────────────────────────────
    show_dimensions = fields.Boolean(string='車輛尺寸 (mm)', default=False)
    show_seat_height = fields.Boolean(string='座高 (mm)', default=False)
    show_wheel_base = fields.Boolean(string='軸距 (mm)', default=False)
    show_vehicle_weight = fields.Boolean(string='車重 (kg)', default=False)
    show_tire_front = fields.Boolean(string='前輪規格', default=False)
    show_tire_rear = fields.Boolean(string='後輪規格', default=False)

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

    def action_save_config(self):
        return True
