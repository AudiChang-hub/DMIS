import logging
import re

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class ReportVirtualField(models.Model):
    _name = 'dms.report.virtual.field'
    _description = '報表虛擬欄位定義'
    _rec_name = 'name'
    _order = 'name'

    # ── 基本欄位 ─────────────────────────────────────────────
    name = fields.Char(
        string='虛擬欄位名稱', required=True, translate=True)

    code = fields.Char(
        string='代碼', required=True,
        help='系統識別碼，僅允許英文字母開頭並由英數字與底線組成，用於程式引用。')

    model_id = fields.Many2one(
        'ir.model', string='作用模型', required=True, ondelete='cascade',
        domain=[('transient', '=', False), ('model', 'like', 'dms.')],
        help='選擇此虛擬欄位應用的 DMS 資料模型')

    model_name = fields.Char(
        related='model_id.model', string='模型技術名稱',
        store=True, readonly=True)

    compute_type = fields.Selection(
        [('rule', '規則匹配')],
        string='運算類型', required=True, default='rule',
        help='V1 僅支援「規則匹配」；未來可擴充其他計算方式')

    # ── 規則列表 ─────────────────────────────────────────────
    rule_ids = fields.One2many(
        'dms.report.virtual.field.rule', 'virtual_field_id',
        string='規則列表', copy=True)

    rule_count = fields.Integer(
        string='規則數', compute='_compute_rule_count')

    # ── 預設值 ───────────────────────────────────────────────
    default_value = fields.Char(
        string='預設值', translate=True,
        help='當所有規則均未匹配時回傳此值；留空代表回傳空字串')

    # ── 共享設定 ─────────────────────────────────────────────
    owner_id = fields.Many2one(
        'res.users', string='建立者',
        default=lambda self: self.env.user,
        required=True, ondelete='cascade', index=True)

    public = fields.Boolean(
        string='公開', default=False,
        help='公開後其他使用者可在報表規則中引用此虛擬欄位')

    active = fields.Boolean(string='啟用', default=True)
    color = fields.Integer(string='顏色標籤')

    # ── SQL 約束 ─────────────────────────────────────────────
    _sql_constraints = [
        ('code_unique', 'UNIQUE(code)', '虛擬欄位代碼必須唯一。'),
    ]

    # ── 計算 ─────────────────────────────────────────────────
    @api.depends('rule_ids')
    def _compute_rule_count(self):
        for rec in self:
            rec.rule_count = len(rec.rule_ids)

    # ── 驗證 ─────────────────────────────────────────────────
    @api.constrains('code')
    def _check_code(self):
        pattern = re.compile(r'^[a-zA-Z][a-zA-Z0-9_]*$')
        for rec in self:
            if not pattern.match(rec.code):
                raise ValidationError(
                    _('代碼「%s」格式不正確，必須以英文字母開頭，並只含英數字與底線。') % rec.code
                )

    # ── 核心計算方法 ─────────────────────────────────────────
    def compute_value(self, record):
        """
        輸入一筆 Odoo 記錄，遍歷規則（依 sequence 升冪），
        回傳第一個匹配規則的輸出值（字串）。
        若無規則匹配，回傳 default_value（空字串若未設定）。
        """
        self.ensure_one()
        value, _log = self.compute_value_with_log(record)
        return value

    def compute_value_with_log(self, record):
        """
        回傳 (value: str, log: str) tuple。
        log 為逐行說明每條規則評估過程的多行字串。
        """
        self.ensure_one()
        log_lines = []

        for rule in self.rule_ids.sorted('sequence'):
            try:
                field_val = rule._get_field_value(record)
                matched, output = rule._eval_rule(record)
                if matched:
                    log_lines.append(
                        '規則 %d [%s] 欄位=%s 條件=%s 欄位值="%s" → ✓ 匹配，輸出: %s' % (
                            rule.sequence, rule.match_type,
                            rule.field_name or '',
                            rule.condition or rule.python_expression or '',
                            field_val, output,
                        )
                    )
                    return output, '\n'.join(log_lines)
                else:
                    log_lines.append(
                        '規則 %d [%s] 欄位=%s 條件=%s 欄位值="%s" → ✗ 未匹配' % (
                            rule.sequence, rule.match_type,
                            rule.field_name or '',
                            rule.condition or '',
                            field_val,
                        )
                    )
            except Exception as exc:
                log_lines.append('規則 %d → 計算錯誤：%s' % (rule.sequence, exc))
                _logger.warning(
                    'dms.report.virtual.field %s rule %d error: %s',
                    self.code, rule.sequence, exc)

        default = self.default_value or ''
        log_lines.append('所有規則未匹配，使用預設值: %s' % (default or '（空值）'))
        return default, '\n'.join(log_lines)

    # ── 測試精靈 ─────────────────────────────────────────────
    def action_open_test_wizard(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': '測試虛擬欄位：%s' % self.name,
            'res_model': 'dms.report.vf.test.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_virtual_field_id': self.id},
        }
