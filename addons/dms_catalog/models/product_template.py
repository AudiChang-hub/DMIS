from odoo import models, fields


class DmsProductTemplate(models.Model):
    _name = 'dms.product.template'
    _description = '產品型式'
    _inherit = ['image.mixin']
    _rec_name = 'name'
    _order = 'brand_id, name'

    # ── 基本資料 ──────────────────────────────────────────
    brand_id = fields.Many2one(
        'dms.brand', string='品牌', required=True, ondelete='restrict')
    brand_logo = fields.Binary(
        related='brand_id.image_128', string='品牌Logo', store=False)
    name = fields.Char(string='型式名稱', required=True)
    model_code = fields.Char(string='原廠型號代碼')
    energy_type = fields.Selection(
        [('oil', '油車'), ('electric', '電車')],
        string='能源型式', required=True)
    brake_type = fields.Char(string='煞車型式')
    active = fields.Boolean(string='啟用', default=True)

    # ── 動力規格（油車）───────────────────────────────────
    engine_displacement = fields.Float(string='總排氣量 (cc)')
    fuel_tank = fields.Float(string='油箱容量 (L)')
    engine_type = fields.Char(string='引擎型式')
    consumption_grade = fields.Char(string='能耗等級')
    efficiency = fields.Float(string='能源效率 (km/L)')
    max_hp = fields.Float(string='最大馬力 (hp)')
    max_torque = fields.Float(string='最大扭力 (Nm)')

    # ── 動力規格（電車）───────────────────────────────────
    power_system = fields.Char(string='動力系統')
    max_output = fields.Float(string='最大功率 (kW)')
    ev_max_hp = fields.Float(string='最大馬力 EV (hp)')
    ev_max_torque = fields.Float(string='最大扭力 EV (Nm)')
    ev_efficiency = fields.Float(string='能源效率 EV (kWh/km)')
    transmission = fields.Char(string='傳動系統')
    battery_capacity = fields.Float(string='電池容量 (kWh)')
    battery_type = fields.Char(string='電池型式')
    charge_time = fields.Float(string='充電時間 (hr)')

    # ── 車身規格 ──────────────────────────────────────────
    dimensions = fields.Char(string='車輛尺寸 (mm)')
    seat_height = fields.Float(string='座高 (mm)')
    wheel_base = fields.Float(string='軸距 (mm)')
    vehicle_weight = fields.Float(string='車重 (kg)')
    tire_front = fields.Char(string='前輪規格')
    tire_rear = fields.Char(string='後輪規格')

    # ── 關聯 ──────────────────────────────────────────────
    sku_ids = fields.One2many('dms.product.sku', 'template_id', string='SKU 清單')

    # ── Kanban 顯示旗標（由 dms.kanban.product.config 驅動）──────────
    kanban_cfg_model = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_year = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_brake_type = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_energy_type = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_color = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_color_code = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_engine_displacement = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_fuel_tank = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_engine_type = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_consumption_grade = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_efficiency = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_max_hp = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_max_torque = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_power_system = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_max_output = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_ev_max_hp = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_ev_max_torque = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_ev_efficiency = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_transmission = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_battery_capacity = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_battery_type = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_charge_time = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_dimensions = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_seat_height = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_wheel_base = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_vehicle_weight = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_tire_front = fields.Boolean(compute='_compute_kanban_cfg', store=False)
    kanban_cfg_tire_rear = fields.Boolean(compute='_compute_kanban_cfg', store=False)

    def _compute_kanban_cfg(self):
        config = self.env['dms.kanban.product.config'].sudo().search(
            [], limit=1, order='id asc'
        )
        defaults = {k: False for k in [
            'kanban_cfg_model', 'kanban_cfg_year', 'kanban_cfg_brake_type',
            'kanban_cfg_energy_type', 'kanban_cfg_color', 'kanban_cfg_color_code',
            'kanban_cfg_engine_displacement', 'kanban_cfg_fuel_tank',
            'kanban_cfg_engine_type', 'kanban_cfg_consumption_grade',
            'kanban_cfg_efficiency', 'kanban_cfg_max_hp', 'kanban_cfg_max_torque',
            'kanban_cfg_power_system', 'kanban_cfg_max_output',
            'kanban_cfg_ev_max_hp', 'kanban_cfg_ev_max_torque',
            'kanban_cfg_ev_efficiency', 'kanban_cfg_transmission',
            'kanban_cfg_battery_capacity', 'kanban_cfg_battery_type',
            'kanban_cfg_charge_time', 'kanban_cfg_dimensions', 'kanban_cfg_seat_height',
            'kanban_cfg_wheel_base', 'kanban_cfg_vehicle_weight',
            'kanban_cfg_tire_front', 'kanban_cfg_tire_rear',
        ]}
        defaults.update({'kanban_cfg_model': True, 'kanban_cfg_year': True,
                         'kanban_cfg_energy_type': True, 'kanban_cfg_color': True})

        if config:
            cfg = dict(
                kanban_cfg_model=config.show_model,
                kanban_cfg_year=config.show_year,
                kanban_cfg_brake_type=config.show_brake_type,
                kanban_cfg_energy_type=config.show_energy_type,
                kanban_cfg_color=config.show_color,
                kanban_cfg_color_code=config.show_color_code,
                kanban_cfg_engine_displacement=config.show_engine_displacement,
                kanban_cfg_fuel_tank=config.show_fuel_tank,
                kanban_cfg_engine_type=config.show_engine_type,
                kanban_cfg_consumption_grade=config.show_consumption_grade,
                kanban_cfg_efficiency=config.show_efficiency,
                kanban_cfg_max_hp=config.show_max_hp,
                kanban_cfg_max_torque=config.show_max_torque,
                kanban_cfg_power_system=config.show_power_system,
                kanban_cfg_max_output=config.show_max_output,
                kanban_cfg_ev_max_hp=config.show_ev_max_hp,
                kanban_cfg_ev_max_torque=config.show_ev_max_torque,
                kanban_cfg_ev_efficiency=config.show_ev_efficiency,
                kanban_cfg_transmission=config.show_transmission,
                kanban_cfg_battery_capacity=config.show_battery_capacity,
                kanban_cfg_battery_type=config.show_battery_type,
                kanban_cfg_charge_time=config.show_charge_time,
                kanban_cfg_dimensions=config.show_dimensions,
                kanban_cfg_seat_height=config.show_seat_height,
                kanban_cfg_wheel_base=config.show_wheel_base,
                kanban_cfg_vehicle_weight=config.show_vehicle_weight,
                kanban_cfg_tire_front=config.show_tire_front,
                kanban_cfg_tire_rear=config.show_tire_rear,
            )
        else:
            cfg = defaults
        for rec in self:
            for k, v in cfg.items():
                setattr(rec, k, v)
