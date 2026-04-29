from odoo import _, models, fields
from odoo.exceptions import UserError


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

    def action_resync(self):
        """重新同步：刪除原訂單與本筆 log，再次掃描指定 folder。"""
        sync = self.env['dms.order.sync']
        rebuilt = []
        for log in self:
            folder_name = log.folder_name
            if log.order_id:
                log.order_id.unlink()
            log.unlink()
            sync._process_folder_by_name(folder_name)
            new_log = self.search(
                [('folder_name', '=', folder_name)], limit=1, order='id desc')
            if new_log:
                rebuilt.append(new_log.id)
        if not rebuilt:
            raise UserError(_('重新同步未產生任何紀錄，請確認資料夾仍存在。'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('重新同步結果'),
            'res_model': 'dms.sync.log',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', rebuilt)],
            'target': 'current',
        }

