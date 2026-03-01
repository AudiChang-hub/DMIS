from odoo import models, fields


class DmsOldVehicle(models.Model):
    _name = 'dms.old.vehicle'
    _description = '舊車資訊'

    partner_id = fields.Many2one(
        'res.partner', string="客戶", required=True, ondelete='cascade'
    )
    plate_number = fields.Char(string="車牌號碼")
    vehicle_owner = fields.Char(string="舊車車主")
    control_account = fields.Char(string="車控帳號")
    note = fields.Text(string="備註")
