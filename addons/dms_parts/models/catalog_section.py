from odoo import models, fields


class DmsPartCatalogSection(models.Model):
    """零件目錄分區：對應爆炸圖的一個區段（E01、E02...）"""
    _name = 'dms.part.catalog.section'
    _description = '目錄分區'
    _rec_name = 'display_name'
    _order = 'catalog_id, sequence, code'

    catalog_id = fields.Many2one(
        'dms.part.catalog',
        string='所屬目錄',
        required=True,
        ondelete='cascade',
    )
    code = fields.Char(string='分區代號', required=True, help='如 E01、E02、F01')
    name = fields.Char(string='分區名稱', required=True, help='如 蓋蓋、節流組')
    display_name = fields.Char(
        string='顯示名稱',
        compute='_compute_display_name',
        store=True,
    )
    category = fields.Selection(
        [('engine', '引擎'), ('frame', '車架')],
        string='部位分類',
        required=True,
        default='engine',
    )
    diagram_image = fields.Binary(string='爆炸圖', attachment=True)
    diagram_filename = fields.Char(string='圖檔名稱')
    sequence = fields.Integer(string='排序', default=10)
    line_ids = fields.One2many(
        'dms.part.catalog.line',
        'section_id',
        string='零件明細',
    )
    line_count = fields.Integer(
        string='零件數',
        compute='_compute_line_count',
    )

    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f'{rec.code} {rec.name}' if rec.code and rec.name else (rec.code or rec.name or '')

    def _compute_line_count(self):
        for rec in self:
            rec.line_count = len(rec.line_ids)
