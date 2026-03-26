from odoo import models, fields


class DmsPriceVersion(models.Model):
    _name = 'dms.price.version'
    _description = '定價版本'
    _rec_name = 'name'
    _order = 'effective_date desc'

    name = fields.Char(string='版本名稱', required=True)
    effective_date = fields.Date(string='生效日期', required=True)
    state = fields.Selection(
        [('draft', '草稿'), ('active', '有效'), ('archived', '封存')],
        string='狀態', default='draft', required=True)
    note = fields.Text(string='備註')
    line_ids = fields.One2many('dms.price.line', 'version_id', string='定價明細')
