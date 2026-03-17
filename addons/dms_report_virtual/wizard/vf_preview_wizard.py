from odoo import models, fields


class VFPreview(models.TransientModel):
    _name = 'dms.report.vf.preview'
    _description = '虛擬欄位報表預覽'

    rule_id = fields.Many2one(
        'dms.report.rule', string='報表規則', readonly=True)
    virtual_field_id = fields.Many2one(
        'dms.report.virtual.field', string='虛擬欄位', readonly=True)
    truncated = fields.Boolean(
        string='結果已截斷', readonly=True,
        help='資料筆數超過 1,000 筆，本次預覽僅取前 1,000 筆計算。')

    # 指標標籤（來自 ir.model.fields.field_description）
    measure_label_1 = fields.Char(string='指標 1', readonly=True)
    measure_label_2 = fields.Char(string='指標 2', readonly=True)
    measure_label_3 = fields.Char(string='指標 3', readonly=True)

    line_ids = fields.One2many(
        'dms.report.vf.preview.line', 'preview_id',
        string='分組結果', readonly=True)


class VFPreviewLine(models.TransientModel):
    _name = 'dms.report.vf.preview.line'
    _description = '虛擬欄位報表預覽行'
    _order = 'virtual_value'

    preview_id = fields.Many2one(
        'dms.report.vf.preview', string='預覽', ondelete='cascade')
    virtual_value = fields.Char(string='虛擬分組值', readonly=True)
    record_count = fields.Integer(string='記錄數', readonly=True)
    measure_total_1 = fields.Float(
        string='指標 1 合計', readonly=True, digits=(16, 2))
    measure_total_2 = fields.Float(
        string='指標 2 合計', readonly=True, digits=(16, 2))
    measure_total_3 = fields.Float(
        string='指標 3 合計', readonly=True, digits=(16, 2))
