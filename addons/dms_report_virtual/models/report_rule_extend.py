import logging

from odoo import models, fields, api
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)

# V1 限制：預覽最多處理此筆數
PREVIEW_MAX_RECORDS = 1000


class ReportRuleVirtualExtend(models.Model):
    _inherit = 'dms.report.rule'

    # ── 虛擬維度欄位 ─────────────────────────────────────────
    virtual_dimension_ids = fields.Many2many(
        'dms.report.virtual.field',
        'dms_report_rule_vf_rel',
        'rule_id',
        'vf_id',
        string='虛擬維度',
        help='選擇要加入分組的虛擬欄位（依規則動態計算分類值）。\n'
             'V1 每次預覽僅取第一個虛擬維度；最多處理 1,000 筆記錄。',
    )

    @api.onchange('model_id')
    def _onchange_model_id_clear_virtual(self):
        self.virtual_dimension_ids = [(5, 0, 0)]

    # ── 覆寫預覽方法 ─────────────────────────────────────────
    def action_preview_report(self):
        base_action = super().action_preview_report()
        if not self.virtual_dimension_ids:
            return base_action
        return self._action_virtual_preview()

    # ── 虛擬分組預覽核心 ─────────────────────────────────────
    def _action_virtual_preview(self):
        self.ensure_one()

        # V1：僅取第一個虛擬維度
        vf = self.virtual_dimension_ids[0]
        model = self.model_id.model

        # 解析篩選 domain
        domain = []
        if self.filter_domain and self.filter_domain.strip():
            try:
                parsed = safe_eval(self.filter_domain)
                if isinstance(parsed, list):
                    domain = parsed
            except Exception as exc:
                _logger.warning(
                    'dms.report.rule id=%s: filter_domain parse error: %s',
                    self.id, exc)

        # 取得記錄（限制筆數）
        records = self.env[model].search(domain, limit=PREVIEW_MAX_RECORDS)
        truncated = len(records) >= PREVIEW_MAX_RECORDS

        # 依虛擬欄位值分組
        groups = {}
        for rec in records:
            try:
                val = vf.compute_value(rec)
            except Exception as exc:
                _logger.warning(
                    'compute_value error for record %s: %s', rec.id, exc)
                val = '（計算錯誤）'
            label = val if val else '（未分類）'
            if label not in groups:
                groups[label] = {'count': 0, 'records': []}
            groups[label]['count'] += 1
            groups[label]['records'].append(rec)

        # 決定指標欄位（最多 3 個）
        measures = list(self.measure_ids[:3])

        def _sum(recs, fname):
            total = 0.0
            for r in recs:
                try:
                    total += float(getattr(r, fname, 0) or 0)
                except (TypeError, ValueError):
                    pass
            return total

        # 建立預覽精靈記錄
        lines = [
            (0, 0, {
                'virtual_value': label,
                'record_count': data['count'],
                'measure_total_1': _sum(data['records'], measures[0].name) if len(measures) > 0 else 0.0,
                'measure_total_2': _sum(data['records'], measures[1].name) if len(measures) > 1 else 0.0,
                'measure_total_3': _sum(data['records'], measures[2].name) if len(measures) > 2 else 0.0,
            })
            for label, data in sorted(groups.items())
        ]

        preview = self.env['dms.report.vf.preview'].create({
            'rule_id': self.id,
            'virtual_field_id': vf.id,
            'truncated': truncated,
            'measure_label_1': measures[0].field_description if len(measures) > 0 else '',
            'measure_label_2': measures[1].field_description if len(measures) > 1 else '',
            'measure_label_3': measures[2].field_description if len(measures) > 2 else '',
            'line_ids': lines,
        })

        return {
            'type': 'ir.actions.act_window',
            'name': '%s（虛擬分組：%s）' % (self.name, vf.name),
            'res_model': 'dms.report.vf.preview',
            'view_mode': 'form',
            'res_id': preview.id,
            'target': 'new',
        }
