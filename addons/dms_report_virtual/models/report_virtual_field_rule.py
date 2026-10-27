import logging
import re as _re
import math as _math

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError
from odoo.tools.safe_eval import safe_eval, wrap_module

_logger = logging.getLogger(__name__)

# 白名單：python 規則可使用的全域物件
_SAFE_GLOBALS = {
    're': wrap_module(_re, {
        'compile': {},
        'escape': {},
        'findall': {},
        'finditer': {},
        'fullmatch': {},
        'match': {},
        'search': {},
        'split': {},
        'sub': {},
        'subn': {},
        'IGNORECASE': {},
        'MULTILINE': {},
        'DOTALL': {},
    }),
    'math': wrap_module(_math, {
        'ceil': {},
        'e': {},
        'fabs': {},
        'floor': {},
        'pi': {},
        'pow': {},
        'sqrt': {},
    }),
    '__builtins__': {},
}


class ReportVirtualFieldRule(models.Model):
    _name = 'dms.report.virtual.field.rule'
    _description = '報表虛擬欄位規則行'
    _order = 'sequence, id'

    # ── 關聯 ─────────────────────────────────────────────────
    virtual_field_id = fields.Many2one(
        'dms.report.virtual.field', string='虛擬欄位',
        required=True, ondelete='cascade', index=True)

    # ── 規則設定 ─────────────────────────────────────────────
    sequence = fields.Integer(string='順序', default=10)

    match_type = fields.Selection([
        ('contains', '包含字串'),
        ('regex',    '正則表達式'),
        ('python',   'Python 表達式'),
    ], string='匹配類型', required=True, default='contains')

    field_name = fields.Char(
        string='比對欄位',
        help='要讀取的欄位路徑，支援點號分隔，例如：dealer_id.name\n'
             'Python 類型可留空（在表達式中直接用 record.xxx 取值）')

    condition = fields.Char(
        string='條件值',
        help='contains：包含此字串即匹配\n'
             'regex：用於 re.search 的正則表達式')

    python_expression = fields.Text(
        string='Python 表達式',
        help='僅 Python 類型使用（safe_eval）。\n'
             '可用變數：record（目前記錄）、re（正則模組）、math（數學模組）。\n'
             '若表達式返回非空非 False 的值視為匹配；True 則使用「輸出值」欄位。\n'
             '範例：record.dealer_id.name.startswith("A") and "品牌A" or False')

    value = fields.Char(
        string='輸出值', required=True, translate=True,
        help='匹配成功時輸出的分類名稱（Python 類型可被表達式返回值覆蓋）')

    description = fields.Text(string='規則說明')

    # ── 驗證 ─────────────────────────────────────────────────
    @api.constrains('match_type', 'field_name', 'python_expression')
    def _check_rule_fields(self):
        for rec in self:
            if rec.match_type in ('contains', 'regex') and not rec.field_name:
                raise ValidationError(
                    _('「包含字串」與「正則表達式」類型的規則必須填寫「比對欄位」。'))
            if rec.match_type == 'python' and not rec.python_expression:
                raise ValidationError(
                    _('「Python 表達式」類型的規則必須填寫「Python 表達式」欄位。'))

    @api.constrains('match_type', 'condition')
    def _check_regex(self):
        for rec in self:
            if rec.match_type == 'regex' and rec.condition:
                try:
                    _re.compile(rec.condition)
                except _re.error as exc:
                    raise ValidationError(
                        _('正則表達式格式不正確：%s') % str(exc))

    # ── 欄位值讀取（點號路徑安全遍歷）────────────────────────
    def _get_field_value(self, record):
        """
        安全遍歷點號分隔的欄位路徑（如 dealer_id.name），
        返回字串；任何錯誤均返回空字串。
        """
        if not self.field_name:
            return ''
        val = record
        for part in self.field_name.split('.'):
            if val is False or val is None:
                return ''
            if isinstance(val, models.BaseModel):
                if not val:
                    return ''
                val = getattr(val, part, False)
            else:
                val = getattr(val, part, '')
        # Many2one record without further path: use display_name
        if isinstance(val, models.BaseModel):
            return val.display_name if val else ''
        return str(val) if val is not False and val is not None else ''

    # ── 規則評估 ─────────────────────────────────────────────
    def _eval_rule(self, record):
        """
        評估此規則是否匹配 record。

        Returns:
            (matched: bool, output: str)
            matched=True 時 output 為輸出值（字串），否則 output=''
        """
        if self.match_type == 'contains':
            field_val = self._get_field_value(record)
            if self.condition and self.condition in field_val:
                return True, self.value or ''
            return False, ''

        elif self.match_type == 'regex':
            field_val = self._get_field_value(record)
            if self.condition:
                try:
                    if _re.search(self.condition, field_val):
                        return True, self.value or ''
                except _re.error as exc:
                    _logger.warning(
                        'Invalid regex in virtual field rule %s: %s', self.id, exc)
            return False, ''

        elif self.match_type == 'python':
            if not self.python_expression:
                return False, ''
            try:
                ctx = dict(_SAFE_GLOBALS, record=record)
                result = safe_eval(self.python_expression, ctx)
                if result is not None and result is not False and result != '':
                    # expression returned a direct value → use as output
                    output = str(result) if result is not True else (self.value or '')
                    return True, output
            except Exception as exc:
                _logger.warning(
                    'Python expression error in virtual field rule %s: %s',
                    self.id, exc)
            return False, ''

        return False, ''
