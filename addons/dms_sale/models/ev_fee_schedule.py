from odoo import models, fields, api


class EvFeeSchedule(models.Model):
    _name = 'dms.ev.fee.schedule'
    _description = '電車牌險費率'
    _rec_name = 'product_id'
    _order = 'product_id, valid_from desc'

    product_id = fields.Many2one(
        'dms.product', string='車款（電車）', required=True, ondelete='restrict',
        domain="[('energy_type','=','electric')]")
    fee_vehicle_registration = fields.Float(string='代繳行照費', digits=(12, 0))
    fee_inspection = fields.Float(string='代繳檢驗費', digits=(12, 0))
    fee_plate = fields.Float(string='代繳號牌費', digits=(12, 0))
    fee_stamp = fields.Float(string='代繳刻印費', digits=(12, 0))
    fee_insurance = fields.Float(string='代繳保險費', digits=(12, 0))
    fee_guild_cert = fields.Float(string='公會證明費', digits=(12, 0))
    fee_document = fields.Float(string='文件處理費', digits=(12, 0))
    fee_other = fields.Float(string='其他', digits=(12, 0))
    fee_total = fields.Float(
        string='合計', digits=(12, 0),
        compute='_compute_fee_total', store=True)
    valid_from = fields.Date(string='有效起始')
    valid_to = fields.Date(string='有效截止')
    active = fields.Boolean(string='啟用', default=True)
    note = fields.Text(string='備註')

    @api.depends(
        'fee_vehicle_registration', 'fee_inspection', 'fee_plate', 'fee_stamp',
        'fee_insurance', 'fee_guild_cert', 'fee_document', 'fee_other')
    def _compute_fee_total(self):
        for rec in self:
            rec.fee_total = (
                rec.fee_vehicle_registration + rec.fee_inspection +
                rec.fee_plate + rec.fee_stamp + rec.fee_insurance +
                rec.fee_guild_cert + rec.fee_document + rec.fee_other
            )
