from odoo import models, fields


class DmsProduct(models.Model):
    _name = "dms.product"
    _description = "產品管理"

    # ── 基本資料 ──────────────────────────────────────────
    brand_id = fields.Many2one('dms.brand', string="品牌", required=True, ondelete='restrict')
    name = fields.Char(string="名稱", required=True)
    model = fields.Char(string="型號")
    year = fields.Char(string="年份")
    brake_type = fields.Char(string="煞車型式")
    energy_type = fields.Selection(
        [('oil', '油車'), ('electric', '電車')],
        string="能源型式",
        required=True,
    )
    color_ids = fields.One2many(
        'dms.product.color', 'product_id', string='顏色清單')
    active = fields.Boolean(string="啟用", default=True)

    # ── 動力規格（油車） ──────────────────────────────────
    engine_displacement = fields.Char(string="總排氣量 (cc)")
    fuel_tank = fields.Char(string="油箱容量 (L)")
    engine_type = fields.Char(string="引擎型式")
    consumption_grade = fields.Char(string="能耗等級")
    efficiency = fields.Char(string="能源效率 (km/L)")
    max_hp = fields.Char(string="最大馬力 (hp)")
    max_torque = fields.Char(string="最大扭力 (Nm)")

    # ── 動力規格（電車） ──────────────────────────────────
    power_system = fields.Char(string="動力系統")
    max_output = fields.Char(string="最大功率 (kW)")
    ev_max_hp = fields.Char(string="最大馬力 EV (hp)")
    ev_max_torque = fields.Char(string="最大扭力 EV (Nm)")
    ev_efficiency = fields.Char(string="能源效率 EV (kWh/km)")
    transmission = fields.Char(string="傳動系統")
    battery_capacity = fields.Char(string="電池容量 (kWh)")
    battery_type = fields.Char(string="電池型式")
    charge_time = fields.Char(string="充電時間 (hr)")

    # ── 車身規格 ──────────────────────────────────────────
    dimensions = fields.Text(string="車輛尺寸 (mm)")
    seat_height = fields.Char(string="座高 (mm)")
    wheel_base = fields.Char(string="軸距 (mm)")
    vehicle_weight = fields.Char(string="車重 (kg)")
    tire_front = fields.Char(string="前輪規格")
    tire_rear = fields.Char(string="後輪規格")
