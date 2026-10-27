from odoo import _, models, fields
from odoo.exceptions import UserError


class OrderSyncLog(models.Model):
    _name = 'dms.sync.log'
    _description = 'OrderProcessor 暫存紀錄'
    _order = 'sync_time desc'
    _rec_name = 'folder_name'

    sync_time = fields.Datetime(
        string='同步時間', required=True, default=fields.Datetime.now, readonly=True)
    folder_name = fields.Char(string='資料夾名稱', required=True, readonly=True)
    state = fields.Selection(
        [('success', '成功'), ('fail', '失敗'), ('skip', '略過'), ('ignored', '已標記忽略')],
        string='狀態', required=True, readonly=True)
    fallback_used = fields.Boolean(string='使用 xlsx fallback', readonly=True)
    customer_name = fields.Char(string='客戶姓名', readonly=True)
    id_number = fields.Char(string='身分證字號', readonly=True)
    customer_phone = fields.Char(string='聯絡電話', readonly=True)
    customer_email = fields.Char(string='Email', readonly=True)
    birthday_ad = fields.Date(string='西元生日', readonly=True)
    address_registered = fields.Text(string='戶籍地址', readonly=True)
    source_product_name = fields.Char(string='原始車款字串', readonly=True)
    source_color_name = fields.Char(string='原始顏色字串', readonly=True)
    source_dealer_name = fields.Char(string='原始車行字串', readonly=True)
    product_id = fields.Many2one('dms.product', string='車款', ondelete='set null', readonly=True)
    color_id = fields.Many2one('dms.product.color', string='顏色', ondelete='set null', readonly=True)
    dealer_id = fields.Many2one('dms.dealer', string='車行', ondelete='set null', readonly=True)
    sale_type = fields.Selection(
        [('store', '店面'), ('dealer', '車行'), ('online', '網路平台')],
        string='交易類型', readonly=True)
    payment_method = fields.Selection(
        [('cash', '現金'), ('credit', '信用卡'), ('installment', '分期')],
        string='付款方式', readonly=True)
    finance_company = fields.Selection(
        [('和潤', '和潤'), ('遠信', '遠信'), ('仲信', '仲信'), ('other', '其他')],
        string='分期公司', readonly=True)
    finance_company_other = fields.Char(string='其他分期公司', readonly=True)
    installment_periods = fields.Integer(string='分期期數', readonly=True)
    is_trade_in = fields.Boolean(string='有汰舊', readonly=True)
    extra_other = fields.Char(string='配件', readonly=True)
    extra_note = fields.Text(string='備註', readonly=True)
    raw_result_json = fields.Text(string='原始 result.json', readonly=True)
    fallback_payload_json = fields.Text(string='xlsx fallback 內容', readonly=True)
    staged_vals_json = fields.Text(string='標準化欄位快照', readonly=True)
    order_id = fields.Many2one(
        'dms.sale.order', string='歷史關聯訂單', ondelete='set null', readonly=True)
    error_msg = fields.Text(string='錯誤訊息', readonly=True)

    def action_resync(self):
        """重新同步：刪除本筆 staging/log，再次掃描指定 folder。"""
        sync = self.env['dms.order.sync']
        rebuilt = []
        for log in self:
            folder_name = log.folder_name
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

