from odoo import models, fields


class OrderSyncLog(models.Model):
    _name = 'dms.sync.log'
    _description = 'OrderProcessor 同步紀錄'
    _order = 'sync_time desc'
    _rec_name = 'folder_name'

    sync_time = fields.Datetime(
        string='同步時間', required=True, default=fields.Datetime.now, readonly=True)
    folder_name = fields.Char(string='資料夾名稱', required=True, readonly=True)
    state = fields.Selection(
        [('success', '成功'), ('fail', '失敗'), ('skip', '略過'), ('ignored', '已標記忽略')],
        string='狀態', required=True, readonly=True)
    order_id = fields.Many2one(
        'dms.sale.order', string='關聯訂單', ondelete='set null', readonly=True)
    error_msg = fields.Text(string='錯誤訊息', readonly=True)
