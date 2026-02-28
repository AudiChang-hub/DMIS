from odoo import models, fields


class DmsProduct(models.Model):
    _name = "dms.product"
    _description = "產品管理"

    # ── 基本資料 ──────────────────────────────────────────
    brand_id = fields.Many2one('dms.brand', string="品牌", required=True, ondelete='restrict')
    name = fields.Char(string="名稱", required=True)
    model = fields.Char(string="型號")
    brake_type = fields.Char(string="煞車型式")
    energy_type = fields.Selection(
        [('oil', '油車'), ('electric', '電車')],
        string="能源型式",
        required=True,
    )
    color = fields.Char(string="顏色")

    # ── 動力規格（油車） ──────────────────────────────────
    engine_displacement = fields.Float(string="總排氣量")
    fuel_tank = fields.Float(string="油箱容量")
    engine_type = fields.Char(string="引擎型式")
    consumption_grade = fields.Char(string="能耗等級")
    efficiency = fields.Char(string="能源效率")
    max_hp = fields.Integer(string="最大馬力")
    max_torque = fields.Integer(string="最大扭力")

    # ── 動力規格（電車） ──────────────────────────────────
    power_system = fields.Char(string="動力系統")
    max_output = fields.Float(string="最大功率")
    ev_max_hp = fields.Integer(string="最大馬力(EV)")
    ev_max_torque = fields.Integer(string="最大扭力(EV)")
    ev_efficiency = fields.Char(string="能源效率(EV)")
    transmission = fields.Char(string="傳動系統")
    battery_capacity = fields.Float(string="電池容量")
    battery_type = fields.Char(string="電池型式")
    charge_time = fields.Float(string="充電時間")

    # ── 車身規格 ──────────────────────────────────────────
    dimensions = fields.Text(string="車輛尺寸")
    seat_height = fields.Float(string="座高")
    wheel_base = fields.Float(string="軸距")
    vehicle_weight = fields.Float(string="車重")
    tire_front = fields.Char(string="前輪規格")
    tire_rear = fields.Char(string="後輪規格")
