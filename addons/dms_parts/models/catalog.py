from odoo import models, fields


class DmsPartCatalog(models.Model):
    """零件目錄：對應一份車型 PDF 目錄的一個版本"""
    _name = 'dms.part.catalog'
    _description = '零件目錄'
    _rec_name = 'name'
    _order = 'template_id, setup_date desc'

    name = fields.Char(string='目錄名稱', required=True, help='如「UQ125DA 2025版」')
    template_id = fields.Many2one(
        'dms.product.template',
        string='車型',
        required=True,
        ondelete='restrict',
    )
    engine_prefix = fields.Char(
        string='引擎號碼前綴',
        help='如「DD」，用於搜尋時自動比對引擎號碼',
    )
    frame_prefix = fields.Char(
        string='車架號碼前綴',
        help='如「RF1A」，選填',
    )
    setup_date = fields.Date(
        string='設變日期',
        help='PDF 上的設計變更日期（設變：YYYY-MM-DD）',
    )
    active = fields.Boolean(string='啟用', default=True)
    note = fields.Text(string='備註')
    section_ids = fields.One2many(
        'dms.part.catalog.section',
        'catalog_id',
        string='分區清單',
    )
    section_count = fields.Integer(
        string='分區數',
        compute='_compute_section_count',
    )

    def _compute_section_count(self):
        for rec in self:
            rec.section_count = len(rec.section_ids)

    def action_open_sections(self):
        """從目錄直接跳到爆炸圖 Kanban"""
        self.ensure_one()
        return {
            'name': f'{self.name}－爆炸圖分區',
            'type': 'ir.actions.act_window',
            'res_model': 'dms.part.catalog.section',
            'view_mode': 'kanban,tree,form',
            'domain': [('catalog_id', '=', self.id)],
            'context': {'default_catalog_id': self.id},
        }
