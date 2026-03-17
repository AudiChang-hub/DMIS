import logging
from odoo import models, fields, api, _
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)

CHART_TYPE_SELECTION = [
    ('pivot', 'Pivot 樞紐分析'),
    ('bar',   'Bar 橫條圖'),
    ('line',  'Line 折線圖'),
    ('pie',   'Pie 圓餅圖'),
]

# 維度欄位可用的欄位型別
DIMENSION_TTYPES = ['date', 'datetime', 'many2one', 'selection', 'char']

# 指標欄位可用的欄位型別
MEASURE_TTYPES = ['float', 'integer', 'monetary']


class ReportRule(models.Model):
    _name = 'dms.report.rule'
    _description = '報表規則'
    _rec_name = 'name'
    _order = 'name'

    # ── 基本欄位 ─────────────────────────────────────────────
    name = fields.Char(
        string='規則名稱', required=True, translate=False)

    model_id = fields.Many2one(
        'ir.model', string='資料模型', required=True, ondelete='cascade',
        domain=[('transient', '=', False), ('model', 'like', 'dms.')],
        help='選擇要分析的 DMS 資料模型')

    model_name = fields.Char(
        related='model_id.model', string='模型技術名稱',
        store=True, readonly=True)

    # ── 維度（group by）─────────────────────────────────────
    dimension_ids = fields.Many2many(
        'ir.model.fields',
        relation='dms_report_rule_dimension_rel',
        column1='rule_id',
        column2='field_id',
        string='維度欄位',
        domain="[('model_id', '=', model_id), ('ttype', 'in', %s)]" % str(DIMENSION_TTYPES),
        help='用於分組（group by）的欄位，可選 date/datetime/many2one/selection/char 型態')

    # ── 指標（measure）──────────────────────────────────────
    measure_ids = fields.Many2many(
        'ir.model.fields',
        relation='dms_report_rule_measure_rel',
        column1='rule_id',
        column2='field_id',
        string='指標欄位',
        domain="[('model_id', '=', model_id), ('ttype', 'in', %s)]" % str(MEASURE_TTYPES),
        help='用於數值聚合的欄位，可選 float/integer/monetary 型態')

    # ── 圖表設定 ─────────────────────────────────────────────
    chart_type = fields.Selection(
        CHART_TYPE_SELECTION,
        string='圖表類型', required=True, default='bar')

    filter_domain = fields.Text(
        string='篩選條件（Domain）',
        help="以 Odoo domain 格式輸入，例如：[('state', '=', 'confirmed')]\n"
             "留空表示不篩選。")

    # ── 狀態與共享 ───────────────────────────────────────────
    active = fields.Boolean(string='啟用', default=True)

    owner_id = fields.Many2one(
        'res.users', string='建立者',
        default=lambda self: self.env.user,
        required=True, ondelete='cascade', index=True)

    public = fields.Boolean(
        string='公開給所有人', default=False,
        help='勾選後，所有使用者均可瀏覽此規則（但僅建立者與管理員可修改）')

    # ── 變更模型時清空維度/指標 ──────────────────────────────
    @api.onchange('model_id')
    def _onchange_model_id(self):
        self.dimension_ids = [(5, 0, 0)]
        self.measure_ids = [(5, 0, 0)]

    # ── 預覽報表 ─────────────────────────────────────────────
    def action_preview_report(self):
        """
        依規則設定動態產生 ir.actions.act_window，
        以 Odoo 原生 Pivot / Graph 視圖呈現。
        """
        self.ensure_one()

        if not self.model_id:
            return {}

        model = self.model_id.model
        group_by = [f.name for f in self.dimension_ids]
        measures = [f.name for f in self.measure_ids]

        # 解析 filter_domain（使用 safe_eval 防止注入）
        domain = []
        if self.filter_domain and self.filter_domain.strip():
            try:
                parsed = safe_eval(self.filter_domain)
                if isinstance(parsed, list):
                    domain = parsed
                else:
                    _logger.warning(
                        'dms.report.rule id=%s: filter_domain 非列表，忽略。',
                        self.id)
            except Exception as e:
                _logger.warning(
                    'dms.report.rule id=%s: filter_domain 解析失敗 (%s)，使用空 domain。',
                    self.id, e)

        # 建立 context
        ctx = {}
        if group_by:
            ctx['group_by'] = group_by
        if measures:
            ctx['pivot_measures'] = measures

        # 決定 view_mode 及 graph 類型
        if self.chart_type == 'pivot':
            view_mode = 'pivot,tree'
        else:
            view_mode = 'graph,tree'
            ctx['graph_type'] = self.chart_type

        return {
            'type': 'ir.actions.act_window',
            'name': self.name,
            'res_model': model,
            'view_mode': view_mode,
            'domain': domain,
            'context': ctx,
            'target': 'current',
        }
