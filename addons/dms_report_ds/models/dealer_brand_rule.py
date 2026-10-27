from odoo import api, fields, models


class DealerBrandRule(models.Model):
    """車行品牌分類規則 — 動態套用至 ds.sales.report 的 brand_type 欄位"""

    _name = 'dms.dealer.brand.rule'
    _description = '車行品牌規則'
    _order = 'sequence, id'

    name = fields.Char(string='規則名稱', required=True)
    sequence = fields.Integer(string='順序', default=10,
                              help='數字越小越先比對；首個命中為最終結果')
    pattern = fields.Char(
        string='正則表達式', required=True,
        help='PostgreSQL POSIX 正則，套用於車行名稱（不區分大小寫）。'
             '範例：鑫輝|特色|捷盛')
    result = fields.Char(
        string='品牌名稱', required=True,
        help='例：光陽 / 三陽 / 山葉 / 台鈴 / 睿能 / 一般車行 / 網路平台 / 中古車')
    active = fields.Boolean(string='啟用', default=True)
    note = fields.Text(string='備註')

    _sql_constraints = [
        ('pattern_not_empty',
         "CHECK (pattern IS NOT NULL AND pattern <> '')",
         '正則表達式不可為空'),
        ('result_not_empty',
         "CHECK (result IS NOT NULL AND result <> '')",
         '品牌名稱不可為空'),
    ]

    def _rebuild_sales_report_view(self):
        """規則異動後重建 ds.sales.report SQL view，使新規則即時生效。"""
        report = self.env.get('ds.sales.report')
        if report is not None:
            report.init()

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        self._rebuild_sales_report_view()
        return records

    def write(self, vals):
        result = super().write(vals)
        trigger_fields = {'pattern', 'result', 'sequence', 'active'}
        if trigger_fields.intersection(vals.keys()):
            self._rebuild_sales_report_view()
        return result

    def unlink(self):
        result = super().unlink()
        self._rebuild_sales_report_view()
        return result

    def action_rebuild_view(self):
        self._rebuild_sales_report_view()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': '已重新套用規則',
                'message': 'ds.sales.report 視圖已根據最新規則重建。',
                'type': 'success',
                'sticky': False,
            },
        }
