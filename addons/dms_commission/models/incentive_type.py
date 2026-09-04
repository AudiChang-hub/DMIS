from odoo import models, fields


class DmsIncentiveType(models.Model):
    """激勵品項類型定義（機油、紅包、刮刮卡…）"""
    _name = 'dms.incentive.type'
    _description = '激勵品項類型'
    _rec_name = 'name'
    _order = 'name'

    name = fields.Char(string='品項名稱', required=True)
    type = fields.Selection(
        [
            ('physical', '實物'),
            ('voucher', '憑證'),
            ('points', '點數'),
        ],
        string='類型', required=True, default='physical')
    active = fields.Boolean(string='啟用', default=True)
    note = fields.Text(string='備註')

    _sql_constraints = [
        ('name_uniq', 'unique(name)', '激勵品項名稱不可重複'),
    ]
