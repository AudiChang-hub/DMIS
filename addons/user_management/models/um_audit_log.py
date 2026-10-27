import json

from odoo import api, fields, models


class UmAuditLog(models.Model):
    _name = 'um.audit.log'
    _description = '使用者操作歷程'
    _order = 'id desc'
    _rec_name = 'record_name'

    user_id = fields.Many2one(
        'res.users', string='使用者', ondelete='set null', index=True, readonly=True,
    )
    user_name = fields.Char(string='使用者名稱', readonly=True)
    model_name = fields.Char(string='模型', readonly=True, index=True)
    model_desc = fields.Char(string='功能模組', readonly=True)
    record_id = fields.Integer(string='記錄 ID', readonly=True)
    record_name = fields.Char(string='記錄名稱', readonly=True)
    action = fields.Selection([
        ('create', '新增'),
        ('write', '修改'),
        ('unlink', '刪除'),
    ], string='操作', readonly=True, index=True)
    changed_fields = fields.Text(string='變更欄位（JSON）', readonly=True)
    changed_fields_html = fields.Html(
        string='變更內容', compute='_compute_changed_fields_html', readonly=True,
    )
    create_date = fields.Datetime(string='時間', readonly=True, index=True)

    @api.depends('changed_fields')
    def _compute_changed_fields_html(self):
        for rec in self:
            if not rec.changed_fields:
                rec.changed_fields_html = ''
                continue
            try:
                data = json.loads(rec.changed_fields)
            except Exception:
                rec.changed_fields_html = f'<pre>{rec.changed_fields}</pre>'
                continue
            rows = ''.join(
                f'<tr>'
                f'<td style="padding:4px 12px 4px 4px;font-weight:500;white-space:nowrap;">{ field }</td>'
                f'<td style="padding:4px 12px;color:#888;">{ vals.get("舊值", "") }</td>'
                f'<td style="padding:4px 4px;color:#222;">{ vals.get("新值", "") }</td>'
                f'</tr>'
                for field, vals in data.items()
            )
            rec.changed_fields_html = (
                '<table style="border-collapse:collapse;font-size:13px;width:100%">'
                '<thead><tr>'
                '<th style="text-align:left;padding:4px 12px 6px 4px;border-bottom:1px solid #ddd;">欄位</th>'
                '<th style="text-align:left;padding:4px 12px 6px;border-bottom:1px solid #ddd;">舊值</th>'
                '<th style="text-align:left;padding:4px 4px 6px;border-bottom:1px solid #ddd;">新值</th>'
                '</tr></thead>'
                f'<tbody>{rows}</tbody>'
                '</table>'
            )
