from odoo import models, fields, api


class ResPartner(models.Model):
    _inherit = 'res.partner'

    is_dms_customer = fields.Boolean(string="DMS 客戶", default=False)
    id_number = fields.Char(string="身分證字號")
    dms_birthday = fields.Date(string="生日（西元）")
    dms_birthday_roc = fields.Char(
        string="民國生日",
        compute='_compute_birthday_roc',
        store=False,
    )
    address_registered = fields.Text(string="戶籍地址")
    old_vehicle_ids = fields.One2many(
        'dms.old.vehicle', 'partner_id', string="舊車資訊"
    )

    @api.depends('dms_birthday')
    def _compute_birthday_roc(self):
        for rec in self:
            if rec.dms_birthday:
                roc_year = rec.dms_birthday.year - 1911
                rec.dms_birthday_roc = (
                    f"{roc_year}/{rec.dms_birthday.month:02d}/{rec.dms_birthday.day:02d}"
                )
            else:
                rec.dms_birthday_roc = False
