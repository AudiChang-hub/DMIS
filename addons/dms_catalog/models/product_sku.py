from odoo import models, fields


class DmsProductSku(models.Model):
    _name = 'dms.product.sku'
    _description = 'SKU（顏色 × 年份）'
    _inherit = ['image.mixin']
    _rec_name = 'display_name'
    _order = 'template_id, manufacture_year desc, color'

    template_id = fields.Many2one(
        'dms.product.template', string='型式', required=True, ondelete='restrict')
    color = fields.Char(string='顏色名稱')
    color_code = fields.Char(string='色碼', help='原廠色碼或色票代號，例如：Pearl White / #FFFFFF')
    manufacture_year = fields.Char(string='出廠年份', help='例：2026')
    sku_code = fields.Char(string='SKU 代碼', copy=False)
    active = fields.Boolean(string='啟用', default=True)

    display_name = fields.Char(
        string='顯示名稱', compute='_compute_display_name', store=True)

    def _compute_display_name(self):
        for rec in self:
            parts = [rec.template_id.name or '']
            if rec.color:
                parts.append(rec.color)
            if rec.manufacture_year:
                parts.append(rec.manufacture_year)
            rec.display_name = ' / '.join(filter(None, parts))

    _sql_constraints = [
        ('unique_sku',
         'UNIQUE(template_id, color_code, manufacture_year)',
         '同一型式下相同色碼與年份的 SKU 已存在，請勿重複建立。'),
    ]
