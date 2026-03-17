import logging

from odoo import models, fields, _

_logger = logging.getLogger(__name__)


class VFTestWizard(models.TransientModel):
    _name = 'dms.report.vf.test.wizard'
    _description = '虛擬欄位測試精靈'

    virtual_field_id = fields.Many2one(
        'dms.report.virtual.field', string='虛擬欄位',
        required=True, ondelete='cascade')

    model_name = fields.Char(
        related='virtual_field_id.model_id.model',
        string='目標模型', readonly=True)

    record_id = fields.Integer(
        string='測試記錄 ID',
        help='輸入欲測試的記錄 ID，例如：dms.sale.order 的資料庫 ID。\n'
             '可由對應模型的清單視圖中查看 URL 取得記錄 ID。')

    result_value = fields.Char(string='計算結果', readonly=True)
    computation_log = fields.Text(string='評估日誌', readonly=True)
    computation_done = fields.Boolean(default=False)

    def action_compute(self):
        """執行虛擬欄位計算並展示結果。"""
        self.ensure_one()
        vf = self.virtual_field_id

        if not self.record_id:
            self.result_value = _('請填寫記錄 ID 後再按「執行計算」')
            self.computation_log = ''
            self.computation_done = True
        else:
            try:
                record = self.env[vf.model_id.model].browse(self.record_id)
                if record.exists():
                    val, log = vf.compute_value_with_log(record)
                    self.result_value = val if val else _('（空值 — 無預設值且無規則匹配）')
                    self.computation_log = log
                else:
                    self.result_value = _('ID %d 不存在於模型 %s') % (
                        self.record_id, vf.model_id.model)
                    self.computation_log = ''
            except Exception as exc:
                self.result_value = _('執行錯誤')
                self.computation_log = str(exc)
                _logger.exception('VFTestWizard computation error: %s', exc)

        self.computation_done = True

        # 重新開啟精靈以顯示結果
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }
