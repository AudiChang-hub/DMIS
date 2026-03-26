from odoo import fields, models


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
    create_date = fields.Datetime(string='時間', readonly=True, index=True)
